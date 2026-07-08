"""Rule-based claim extraction — a transparent, auditable heuristic baseline.

Given the claim *as authored* (an input :class:`~scientific_claim_verifier.schemas.ScientificClaim`
carrying only id/text/type/provenance) and the artifact
:class:`~scientific_claim_verifier.schemas.ArtifactBundle`, the
:class:`RuleBasedClaimExtractor` recovers the claim's structured fields —
numeric values, the comparison operator, metric names, dataset references,
entities, conditions, and units — using small, independently-testable rules.

**This is a heuristic, and it is labelled as one.** It does no learned NLP and
makes no attempt to be a general claim parser. Its purpose is the project's
purpose: *auditability*. Every populated field is produced by a named rule whose
firing is recorded in :attr:`Extraction.rules_fired`, so a reviewer can see
exactly why a value was extracted. The rules are deliberately conservative — they
prefer to leave a field empty over guessing — because an unextracted field is
scored ``underspecified`` downstream, which is a safe outcome, whereas a wrong
guess is not.

Scope of each channel (documented honestly in ``docs/EXTRACTION.md``):

- **Numbers / operator / metrics / units** — reliable regex + a small closed
  lexicon. These are the fields the checks (Milestone 5) consume.
- **Datasets / entities / conditions** — best-effort. Dataset detection is a
  known-name lexicon plus a ``"<name> dataset"`` pattern; entity detection is a
  minimal role lexicon plus a ``"Method X"`` pattern; condition detection covers
  only sample-count conditions (``"n = N"``). Free-form semantic conditions
  (e.g. "trained only on synthetic data") are beyond a transparent rule set and
  are intentionally *not* guessed.

Scored evidence *linking* — searching the bundle for the passage that best
supports a claim, with a relevance score — is the evidence linker's job
(Milestone 4). The extractor only records artifact references the claim text
names *explicitly* (a ``.py`` filename, a "Table N" mention, a dataset name),
resolved against the bundle where possible; these carry no score.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..artifacts import loader
from ..artifacts.loader import GoldClaim, LoadedTask
from ..schemas import (
    ArtifactBundle,
    ClaimType,
    ComparisonOperator,
    EvidenceKind,
    ScientificClaim,
)
from . import normalization

# ---------------------------------------------------------------------------
# Lexicons and patterns (small, closed, and documented — this is the heuristic)
# ---------------------------------------------------------------------------

# A numeric token: an optional sign, digits, an optional decimal part, and an
# optional trailing "%". The leading look-behind refuses digits that are part of
# an identifier or hyphenated name, so "2" in "SST-2" and "10" in "CIFAR-10" are
# NOT read as numbers, while "72.0", "-5", "0.50", and "90%" are.
_NUMBER_RE = re.compile(r"(?<![\w.\-])(-?\d+(?:\.\d+)?)(%?)")

# The "from X to Y" comparison shape ("improves accuracy from 72.0 to 78.0").
_FROM_TO_RE = re.compile(
    r"\bfrom\s+(-?\d+(?:\.\d+)?)%?\s+to\s+(-?\d+(?:\.\d+)?)%?", re.IGNORECASE
)

# Nouns that turn an integer into a sample count (=> a `count` metric and an
# "n = N" condition), rather than a headline value. Order longest-first so
# multi-word nouns win.
_COUNT_NOUNS = (
    "data points",
    "samples",
    "examples",
    "instances",
    "observations",
    "records",
    "sequences",
    "points",
    "rows",
)
_COUNT_NOUN_RE = re.compile(r"^\s*(?:" + "|".join(_COUNT_NOUNS) + r")\b", re.IGNORECASE)

# Metric surface forms -> canonical name, applied longest/most-specific first.
# Count-inducing nouns map to `count`. This is the whole metric vocabulary; it is
# meant to be small and obvious, not exhaustive.
_METRIC_PATTERNS: list[tuple[str, str]] = [
    (r"gc[\s-]?content", "gc_content"),
    (r"f1(?:[\s-]?score)?", "f1"),
    (r"accuracy", "accuracy"),
    (r"precision", "precision"),
    (r"recall", "recall"),
    (r"au[cr]oc|auc", "auc"),
    (r"bleu", "bleu"),
    (r"rouge", "rouge"),
    (r"perplexity", "perplexity"),
    (r"correlation", "correlation"),
    (r"standard deviation|std", "std"),
    (r"median", "median"),
    (r"mean|average", "mean"),
    (r"loss", "loss"),
    (r"|".join(_COUNT_NOUNS), "count"),
    (r"count", "count"),
]
_METRIC_RES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"\b(?:{pat})\b", re.IGNORECASE), name) for pat, name in _METRIC_PATTERNS
]

# Metrics conventionally reported on a 0–100 percentage scale. Used only by the
# units heuristic (a value > 1 for one of these implies "%").
_PERCENT_SCALE_METRICS = frozenset({"accuracy", "f1", "precision", "recall", "auc"})

# Known dataset/benchmark names (canonical casing). Matched case-insensitively.
_KNOWN_DATASETS = (
    "SST-2",
    "SST2",
    "MNLI",
    "QNLI",
    "RTE",
    "CoLA",
    "STS-B",
    "MRPC",
    "QQP",
    "GLUE",
    "SQuAD",
    "ImageNet",
    "CIFAR-10",
    "CIFAR-100",
    "MNIST",
    "WikiText",
)
_KNOWN_DATASET_RES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE), name) for name in _KNOWN_DATASETS
]
# "<token> dataset|corpus|benchmark" -> token (e.g. "measurements dataset").
_DATASET_PHRASE_RE = re.compile(
    r"\b([A-Za-z][\w-]*)\s+(?:dataset|corpus|benchmark)\b", re.IGNORECASE
)

# Entity heuristics: a "Method X" proper-name pattern plus a minimal role lexicon.
# Deliberately conservative — a bare lowercase "method" is NOT an entity.
_METHOD_RE = re.compile(r"\bMethod\s+[A-Z0-9][\w-]*\b")
_ROLE_ENTITIES = ("baseline", "model")

# Comparison-direction verbs (used only when there is no explicit "from X to Y").
# Inflections are enumerated and matched on WORD BOUNDARIES, not as substrings:
# "against" must not fire "gain", and "dropout" must not fire "drop".
_UP_WORDS = (
    "improve", "improves", "improved", "improvement", "improvements",
    "outperform", "outperforms", "outperformed",
    "increase", "increases", "increased",
    "higher", "better", "gain", "gains",
    "surpass", "surpasses", "exceed", "exceeds",
)
_DOWN_WORDS = (
    "reduce", "reduces", "reduced",
    "lower", "lowers", "lowered",
    "decrease", "decreases", "decreased",
    "drop", "drops", "dropped",
    "worse", "fewer", "shrink", "shrinks",
)
_UP_RE = re.compile(r"\b(?:" + "|".join(_UP_WORDS) + r")\b", re.IGNORECASE)
_DOWN_RE = re.compile(r"\b(?:" + "|".join(_DOWN_WORDS) + r")\b", re.IGNORECASE)

# A ".py" filename token, resolved against the bundle's code artifacts by basename.
_PYFILE_RE = re.compile(r"\b([\w./-]+\.py)\b")
# "Table N" / "Figure N" / "Fig. N" mentions (numeric or roman).
_TABLE_FIG_RE = re.compile(r"\b(Table|Figure|Fig\.?)\s+([0-9]+|[IVXLC]+)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Small value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Number:
    """One numeric token found in text."""

    value: float
    is_percent: bool
    start: int
    end: int
    raw: str


@dataclass(frozen=True)
class ArtifactReference:
    """A reference the claim text names explicitly, resolved where possible.

    ``target_id`` is the bundle artifact this resolves to (``None`` if the
    mention could not be resolved, e.g. a bare "Table 1" with no id mapping).
    ``mention`` is the exact surface text. These are *not* scored — scored
    linking is Milestone 4.
    """

    kind: EvidenceKind
    mention: str
    target_id: str | None = None
    locator: str | None = None


@dataclass
class Extraction:
    """The result of running the extractor on one claim.

    ``claim`` is the populated :class:`ScientificClaim` (a new object; the input
    is never mutated). ``references`` are the explicit artifact references found
    in the claim text. ``rules_fired`` is an ordered, human-readable audit trail
    of which heuristics contributed, for the trace and the report.
    """

    claim: ScientificClaim
    references: list[ArtifactReference] = field(default_factory=list)
    rules_fired: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Sub-extractors (each is a pure function of its inputs — independently tested)
# ---------------------------------------------------------------------------


def extract_numbers(text: str) -> list[Number]:
    """Return every numeric token in ``text``, left to right.

    Digits embedded in identifiers or hyphenated names (``SST-2``, ``CIFAR-10``,
    ``eval2.py``) are not numbers; ``72.0``, ``-5``, ``0.50``, and ``90%`` are.
    """
    numbers: list[Number] = []
    for m in _NUMBER_RE.finditer(text):
        numbers.append(
            Number(
                value=float(m.group(1)),
                is_percent=m.group(2) == "%",
                start=m.start(1),
                end=m.end(),
                raw=m.group(0),
            )
        )
    return numbers


def find_from_to(text: str) -> tuple[float | None, float | None]:
    """Return ``(baseline, target)`` for a "from X to Y" phrase, else ``(None, None)``."""
    m = _FROM_TO_RE.search(text)
    if m is None:
        return None, None
    return float(m.group(1)), float(m.group(2))


def _is_count_number(text: str, number: Number) -> bool:
    """True if ``number`` is immediately followed by a count noun (a sample count)."""
    return bool(_COUNT_NOUN_RE.match(text[number.end :]))


def detect_count(text: str, numbers: list[Number]) -> int | None:
    """Return the integer sample count (``"12 samples"`` -> 12), or ``None``."""
    for number in numbers:
        if number.value == int(number.value) and _is_count_number(text, number):
            return int(number.value)
    return None


def extract_metrics(text: str) -> list[str]:
    """Return canonical metric names present in ``text``, in first-appearance order."""
    hits: list[tuple[int, str]] = []
    seen: set[str] = set()
    for regex, name in _METRIC_RES:
        for m in regex.finditer(text):
            hits.append((m.start(), name))
    ordered: list[str] = []
    for _, name in sorted(hits, key=lambda pair: pair[0]):
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def extract_datasets(text: str) -> list[str]:
    """Return dataset references: known names, plus ``"<name> dataset"`` phrases."""
    found: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if name not in seen:
            seen.add(name)
            found.append(name)

    for regex, canonical in _KNOWN_DATASET_RES:
        if regex.search(text):
            add(canonical)
    for m in _DATASET_PHRASE_RE.finditer(text):
        add(m.group(1))
    return found


def extract_entities(text: str) -> list[str]:
    """Return entities: ``"Method X"`` proper names plus a minimal role lexicon."""
    found: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if name not in seen:
            seen.add(name)
            found.append(name)

    for m in _METHOD_RE.finditer(text):
        add(m.group(0))
    for role in _ROLE_ENTITIES:
        if re.search(rf"\b{role}\b", text, re.IGNORECASE):
            add(role)
    return found


def detect_operator(
    text: str,
    claim_type: ClaimType,
    baseline: float | None,
    expected: float | None,
) -> ComparisonOperator | None:
    """Pick the comparison operator from the phrasing and the claim type.

    Precedence: an explicit "from X to Y" (direction from the sign of Y − X) →
    an up/down comparison verb → the claim-type default (recomputation claims
    compare within tolerance, ``~``; a plain numeric claim asserts equality,
    ``=``; a comparison claim defaults to ``>``). Descriptive claims with no
    numeric signal get no operator.
    """
    if baseline is not None and expected is not None:
        if expected > baseline:
            return ComparisonOperator.GT
        if expected < baseline:
            return ComparisonOperator.LT
        return ComparisonOperator.EQ

    if _UP_RE.search(text):
        return ComparisonOperator.GT
    if _DOWN_RE.search(text):
        return ComparisonOperator.LT

    if claim_type in (ClaimType.DATASET, ClaimType.CODE_REPRODUCTION):
        return ComparisonOperator.APPROX
    if claim_type == ClaimType.NUMERIC:
        return ComparisonOperator.EQ
    if claim_type == ClaimType.COMPARISON:
        return ComparisonOperator.GT
    return None


def extract_units(text: str, metrics: list[str], expected_value: float | None) -> str | None:
    """Return ``"%"`` if the text has a percent sign, or a 0–100 accuracy-scale value.

    The second branch is an explicit heuristic: a percentage-scale metric
    (accuracy/F1/…) whose value exceeds 1 is read as a percentage even when the
    ``%`` sign is absent (``"from 72.0 to 78.0"`` accuracy → ``%``).
    """
    if "%" in text:
        return "%"
    if (
        expected_value is not None
        and expected_value > 1.0
        and any(metric in _PERCENT_SCALE_METRICS for metric in metrics)
    ):
        return "%"
    return None


def extract_references(text: str, bundle: ArtifactBundle) -> list[ArtifactReference]:
    """Return artifact references named in ``text``, resolved against ``bundle``.

    Resolves ``.py`` filenames to code artifacts by basename and dataset names to
    dataset artifacts by id/description; records "Table N"/"Figure N" mentions
    (unresolved — there is no number→id map). Scored linking is Milestone 4.
    """
    refs: list[ArtifactReference] = []

    code_by_basename = {
        Path(c.path).name: c.artifact_id for c in bundle.code_files if c.path
    }
    for m in _PYFILE_RE.finditer(text):
        mention = m.group(1)
        target = code_by_basename.get(Path(mention).name)
        refs.append(ArtifactReference(EvidenceKind.CODE, mention=mention, target_id=target))

    for name in extract_datasets(text):
        target = _resolve_dataset(name, bundle)
        refs.append(ArtifactReference(EvidenceKind.DATASET, mention=name, target_id=target))

    for m in _TABLE_FIG_RE.finditer(text):
        kind = EvidenceKind.FIGURE if m.group(1).lower().startswith("fig") else EvidenceKind.TABLE
        refs.append(ArtifactReference(kind, mention=m.group(0), target_id=None))

    return refs


def _resolve_dataset(name: str, bundle: ArtifactBundle) -> str | None:
    """Resolve a dataset name to a dataset artifact id via id/description match."""
    needle = name.lower()
    for ds in bundle.datasets:
        haystack = f"{ds.artifact_id} {ds.description or ''}".lower()
        if needle in haystack:
            return ds.artifact_id
    return None


# ---------------------------------------------------------------------------
# The extractor
# ---------------------------------------------------------------------------


class RuleBasedClaimExtractor:
    """Transparent, deterministic claim extractor. No state; safe to reuse."""

    def extract(self, claim: ScientificClaim, bundle: ArtifactBundle) -> Extraction:
        """Populate a copy of ``claim`` from its text and ``bundle``.

        The input claim is never mutated: a fresh :class:`ScientificClaim` is
        built with the recovered fields and returned inside an :class:`Extraction`
        alongside the explicit references and a record of which rules fired.
        """
        text = claim.claim_text
        fired: list[str] = []

        numbers = extract_numbers(text)
        baseline, expected = find_from_to(text)
        if baseline is not None:
            fired.append(f"from-to: {baseline} -> {expected}")

        count = detect_count(text, numbers)
        conditions: list[str] = []
        if count is not None:
            conditions.append(f"n = {count}")
            fired.append(f"count: n = {count}")

        # No explicit "from X to Y": the headline value is the first numeric token
        # that is not the sample count.
        if expected is None:
            for number in numbers:
                if not _is_count_number(text, number):
                    expected = number.value
                    fired.append(f"value: {expected}")
                    break

        metrics = extract_metrics(text)
        if metrics:
            fired.append(f"metrics: {', '.join(metrics)}")
        datasets = extract_datasets(text)
        if datasets:
            fired.append(f"datasets: {', '.join(datasets)}")
        entities = extract_entities(text)
        if entities:
            fired.append(f"entities: {', '.join(entities)}")

        operator = detect_operator(text, claim.claim_type, baseline, expected)
        if operator is not None:
            fired.append(f"operator: {operator.value}")

        units = extract_units(text, metrics, expected)
        if units is not None:
            fired.append(f"units: {units}")

        references = extract_references(text, bundle)

        populated = ScientificClaim(
            claim_id=claim.claim_id,
            claim_text=claim.claim_text,
            source_document_id=claim.source_document_id,
            source_passage=claim.source_passage,
            claim_type=claim.claim_type,
            entities=entities,
            metrics=metrics,
            datasets=datasets,
            conditions=conditions,
            expected_value=expected,
            baseline_value=baseline,
            comparison_operator=operator,
            units=units,
        )
        populated.normalized_claim = normalization.normalize(populated)
        return Extraction(claim=populated, references=references, rules_fired=fired)


# ---------------------------------------------------------------------------
# Scoring against the gold extraction target
# ---------------------------------------------------------------------------

# The structured fields the extractor is scored on. `normalized_claim` is
# deliberately excluded (it is the extractor's own canonical form, not a gold
# match target — see normalization.py).
SCORED_FIELDS = (
    "expected_value",
    "baseline_value",
    "comparison_operator",
    "units",
    "metrics",
    "datasets",
    "entities",
    "conditions",
)
_SET_FIELDS = frozenset({"metrics", "datasets", "entities", "conditions"})


def _values_match(field_name: str, extracted: object, gold: object) -> bool:
    """Field-appropriate equality: set for list fields, isclose for floats."""
    if field_name in _SET_FIELDS:
        return set(extracted or []) == set(gold or [])  # type: ignore[arg-type]
    if isinstance(extracted, float) or isinstance(gold, float):
        if extracted is None or gold is None:
            return extracted is None and gold is None
        return math.isclose(float(extracted), float(gold), rel_tol=1e-9, abs_tol=1e-9)
    return extracted == gold


@dataclass
class ExtractionScore:
    """Per-field correctness of an extracted claim against a gold target."""

    fields: dict[str, bool]

    @property
    def n_correct(self) -> int:
        return sum(1 for ok in self.fields.values() if ok)

    @property
    def n_total(self) -> int:
        return len(self.fields)

    @property
    def accuracy(self) -> float:
        return self.n_correct / self.n_total if self.fields else 1.0

    @property
    def all_correct(self) -> bool:
        return all(self.fields.values())


def score_extraction(extracted: ScientificClaim, gold: GoldClaim) -> ExtractionScore:
    """Compare an extracted claim to a :class:`GoldClaim`, field by field.

    Scores only :data:`SCORED_FIELDS`; list fields compare as sets (order is not
    meaningful) and float fields compare with :func:`math.isclose`.
    """
    result: dict[str, bool] = {}
    for name in SCORED_FIELDS:
        result[name] = _values_match(name, getattr(extracted, name), getattr(gold, name))
    return ExtractionScore(fields=result)


def aggregate_scores(scores: list[ExtractionScore]) -> dict[str, tuple[int, int]]:
    """Aggregate per-field ``(n_correct, n_total)`` across many scored claims."""
    totals: dict[str, tuple[int, int]] = {}
    for name in SCORED_FIELDS:
        correct = sum(1 for s in scores if s.fields.get(name))
        total = sum(1 for s in scores if name in s.fields)
        totals[name] = (correct, total)
    return totals


# ---------------------------------------------------------------------------
# Rendering + CLI entry points
# ---------------------------------------------------------------------------


def _fmt(value: object) -> str:
    """Render a field value for the text report."""
    if value is None:
        return "—"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) if value else "—"
    return str(value)


def extraction_to_dict(extraction: Extraction, score: ExtractionScore | None = None) -> dict:
    """Serialize an extraction (and optional score) to a JSON-ready dict."""
    payload: dict = {
        "claim": extraction.claim.model_dump(mode="json"),
        "references": [
            {
                "kind": ref.kind.value,
                "mention": ref.mention,
                "target_id": ref.target_id,
                "locator": ref.locator,
            }
            for ref in extraction.references
        ],
        "rules_fired": extraction.rules_fired,
    }
    if score is not None:
        payload["score"] = {
            "fields": score.fields,
            "n_correct": score.n_correct,
            "n_total": score.n_total,
        }
    return payload


def render_extraction(
    extraction: Extraction, gold: GoldClaim | None = None, task_id: str | None = None
) -> str:
    """Render a human-readable extraction report (and gold comparison if given)."""
    claim = extraction.claim
    op = claim.comparison_operator.value if claim.comparison_operator else None
    lines = [
        "scientific-claim-verifier — rule-based claim extraction",
        "=" * 54,
    ]
    if task_id:
        lines.append(f"Task            : {task_id}")
    lines += [
        f"Claim           : {claim.claim_id} ({claim.claim_type.value})",
        f"Text            : {claim.claim_text.strip()}",
        f"Normalized      : {claim.normalized_claim}",
        "",
        f"expected_value  : {_fmt(claim.expected_value)}",
        f"baseline_value  : {_fmt(claim.baseline_value)}",
        f"operator        : {_fmt(op)}",
        f"units           : {_fmt(claim.units)}",
        f"metrics         : {_fmt(claim.metrics)}",
        f"datasets        : {_fmt(claim.datasets)}",
        f"entities        : {_fmt(claim.entities)}",
        f"conditions      : {_fmt(claim.conditions)}",
    ]

    if extraction.references:
        lines.append("")
        lines.append("References (explicit in text; scored linking is M4):")
        for ref in extraction.references:
            target = ref.target_id or "unresolved"
            lines.append(f"  - {ref.kind.value}: {ref.mention!r} -> {target}")

    lines.append("")
    lines.append("Rules fired:")
    for rule in extraction.rules_fired:
        lines.append(f"  - {rule}")

    if gold is not None:
        score = score_extraction(claim, gold)
        lines.append("")
        lines.append(f"Gold comparison : {score.n_correct}/{score.n_total} scored fields match")
        for name in SCORED_FIELDS:
            mark = "ok " if score.fields[name] else "MISS"
            got, want = _fmt(getattr(claim, name)), _fmt(getattr(gold, name))
            lines.append(f"  [{mark}] {name}: got {got} / gold {want}")

    return "\n".join(lines)


def extract_and_report(
    task_path: str | Path,
    out_dir: str | Path | None = None,
    as_json: bool = False,
    repo_root: str | Path | None = None,
) -> int:
    """Load a task, extract its claim, print a report, optionally write JSON.

    Returns 0 on success, 1 if the task could not be loaded. Compares against the
    task's gold extraction target when the report is shown.
    """
    try:
        task: LoadedTask = loader.load_task(task_path, repo_root)
    except (loader.TaskLoadError, OSError) as exc:
        print(f"error: could not load task {task_path}: {exc}", file=sys.stderr)
        return 1

    extraction = RuleBasedClaimExtractor().extract(task.input_claim, task.bundle)
    gold = task.spec.expected.claim
    score = score_extraction(extraction.claim, gold)

    if as_json:
        print(json.dumps(extraction_to_dict(extraction, score), indent=2, sort_keys=True))
    else:
        print(render_extraction(extraction, gold=gold, task_id=task.spec.task_id))

    if out_dir is not None:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        target = out_path / f"{task.spec.task_id}.extraction.json"
        target.write_text(
            json.dumps(extraction_to_dict(extraction, score), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {target}", file=sys.stderr)
    return 0


def run_cli(argv: list[str]) -> int:
    """Parse ``extract-claims`` arguments and run. Shared by the CLI and script."""
    parser = argparse.ArgumentParser(
        prog="claimverifier extract-claims",
        description="Run the rule-based claim extractor on a task (offline).",
    )
    add_extract_arguments(parser)
    args = parser.parse_args(argv)
    return extract_and_report(args.task, out_dir=args.out, as_json=args.json)


def add_extract_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``extract-claims`` flags. Shared by the CLI and the script.

    The flag names follow the CLI contract in ``docs/PLAN.md`` §10
    (``--task``, ``--out``); ``--json`` is an addition for machine-readable output.
    """
    parser.add_argument(
        "--task",
        required=True,
        metavar="PATH",
        help="Path to a task YAML/JSON file.",
    )
    parser.add_argument(
        "--out",
        metavar="DIR",
        default=None,
        help="Write <task_id>.extraction.json to this directory.",
    )
    parser.add_argument("--json", action="store_true", help="Print the extraction as JSON.")


def main(argv: list[str] | None = None) -> int:
    return run_cli(argv if argv is not None else sys.argv[1:])


__all__ = [
    "Number",
    "ArtifactReference",
    "Extraction",
    "RuleBasedClaimExtractor",
    "ExtractionScore",
    "SCORED_FIELDS",
    "extract_numbers",
    "find_from_to",
    "detect_count",
    "extract_metrics",
    "extract_datasets",
    "extract_entities",
    "detect_operator",
    "extract_units",
    "extract_references",
    "score_extraction",
    "aggregate_scores",
    "extraction_to_dict",
    "render_extraction",
    "extract_and_report",
    "add_extract_arguments",
    "run_cli",
    "main",
]
