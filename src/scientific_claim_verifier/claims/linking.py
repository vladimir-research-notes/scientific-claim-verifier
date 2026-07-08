"""The evidence linker — from an extracted claim to scored provenance records.

Milestone 4. The linker takes a **populated** claim (the output of
:class:`~scientific_claim_verifier.claims.extraction.RuleBasedClaimExtractor`) and
an :class:`~scientific_claim_verifier.schemas.ArtifactBundle`, and answers: *which
artifacts bear on this claim, and exactly where?* It emits an ordered list of
:class:`~scientific_claim_verifier.schemas.EvidenceLink` records — one passage,
plus any table cells/columns, dataset columns, code files, and figure series the
claim resolves to — each carrying the named rule that produced it.

Retrieval, not judgement
------------------------
A link says "this is where to look", never "this proves the claim". A passage can
be linked with a high score and *contradict* the claim; a table column can be
linked precisely because no cell matches. Deciding whether linked evidence
**supports** a claim is the ``evidence_presence`` and value checks (Milestone 5)
and scoring (Milestone 7). Keeping the two apart is what lets a report display
*supporting text* and *computed check* as separately auditable channels.

Asserted vs. discovered provenance
----------------------------------
A task may declare ``claim.source_passage`` — the passage a human says the claim
came from. Using it makes passage linking trivially correct, so the linker records
it as :attr:`~scientific_claim_verifier.evidence.MatchMethod.DECLARED_SOURCE` and
still reports the passage's *measured* overlap alongside. Constructing the linker
with ``use_declared_source=False`` runs it **blind**, which is the setting under
which its retrieval is actually worth measuring (see ``docs/RESULTS.md``).

Scores
------
``EvidenceLink.score`` is a **retrieval confidence** in ``[0, 1]``: ``1.0`` for a
deterministic identifier match (a declared source, a verbatim passage, a resolved
artifact id, a located cell), and the Dice overlap for a keyword-matched passage.
It is not a probability that the claim is true. Locator granularity — cell vs.
column vs. whole artifact — is expressed by the ``locator``, not by the score.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..artifacts import loader
from ..artifacts.loader import LoadedTask
from ..evidence import code_refs, datasets, figures, passages, tables
from ..evidence.passages import MIN_PASSAGE_SCORE, PassageCandidate
from ..schemas import ArtifactBundle, EvidenceKind, EvidenceLink, ScientificClaim
from . import extraction
from .extraction import RuleBasedClaimExtractor

# Emission order of the evidence kinds. Fixed so a claim's links — and therefore
# the JSON artifact and the trace — are byte-stable across runs.
_KIND_ORDER = (
    EvidenceKind.PASSAGE,
    EvidenceKind.TABLE,
    EvidenceKind.DATASET,
    EvidenceKind.CODE,
    EvidenceKind.FIGURE,
)


@dataclass
class Linking:
    """The result of linking one claim against one bundle.

    ``claim`` is a copy of the input claim with ``evidence_links`` populated (the
    input is never mutated). ``passage_candidates`` is the *complete* ranking, not
    just the winner, so a reviewer can see what the linker considered and rejected.
    ``rules_fired`` mirrors the extractor's audit trail.
    """

    claim: ScientificClaim
    links: list[EvidenceLink] = field(default_factory=list)
    passage_candidates: list[PassageCandidate] = field(default_factory=list)
    rules_fired: list[str] = field(default_factory=list)

    def of_kind(self, kind: EvidenceKind) -> list[EvidenceLink]:
        """The emitted links of one evidence kind, in order."""
        return [link for link in self.links if link.kind is kind]


class EvidenceLinker:
    """Deterministic, rule-based evidence linker. No state; safe to reuse.

    Parameters
    ----------
    use_declared_source:
        Honour the task's ``claim.source_passage`` as asserted provenance. Default
        ``True`` (in production the claim really does know where it came from);
        set ``False`` to measure the linker's own retrieval.
    min_passage_score:
        A passage below this score is not linked. Rejects passages with essentially
        no lexical overlap; it is not a support threshold.
    """

    def __init__(
        self,
        use_declared_source: bool = True,
        min_passage_score: float = MIN_PASSAGE_SCORE,
    ) -> None:
        self.use_declared_source = use_declared_source
        self.min_passage_score = min_passage_score

    def link(self, claim: ScientificClaim, bundle: ArtifactBundle) -> Linking:
        """Link ``claim`` against ``bundle``; return the links and the audit trail."""
        fired: list[str] = []
        references = extraction.extract_references(claim.claim_text, bundle)

        code_ids = [
            ref.target_id
            for ref in references
            if ref.kind is EvidenceKind.CODE and ref.target_id is not None
        ]
        dataset_names = [ref.mention for ref in references if ref.kind is EvidenceKind.DATASET]
        table_mentioned = any(ref.kind is EvidenceKind.TABLE for ref in references)
        figure_mentioned = any(ref.kind is EvidenceKind.FIGURE for ref in references)

        links: list[EvidenceLink] = []

        # --- passages -------------------------------------------------------
        declared = claim.source_passage if self.use_declared_source else None
        candidates = passages.rank_passages(claim.claim_text, bundle, declared_passage_id=declared)
        best = passages.select_passage(candidates, self.min_passage_score)
        if best is not None:
            rank = candidates.index(best) + 1
            links.append(
                EvidenceLink(
                    kind=EvidenceKind.PASSAGE,
                    target_id=best.passage_id,
                    quote=best.quote,
                    score=round(best.score, 6),
                    notes=(
                        f"match={best.method.value}; "
                        f"overlap={best.overlap_score:.3f}; rank={rank}"
                    ),
                )
            )
            fired.append(f"passage: {best.passage_id} via {best.method.value}")
        elif candidates:
            fired.append(
                f"passage: none linked (best overlap {candidates[0].overlap_score:.3f} "
                f"< {self.min_passage_score})"
            )

        # --- tables ---------------------------------------------------------
        for match in tables.link_tables(claim, bundle.tables, table_mentioned):
            note = f"match={match.method.value}"
            if match.matched_value is not None:
                note += f"; value={match.matched_value:g}"
            links.append(
                EvidenceLink(
                    kind=EvidenceKind.TABLE,
                    target_id=match.table_id,
                    locator=match.locator,
                    score=1.0,
                    notes=note,
                )
            )
            fired.append(f"table: {match.table_id} {match.locator or '(whole)'}")

        # --- datasets -------------------------------------------------------
        for ds_match in datasets.link_datasets(claim, bundle, dataset_names):
            links.append(
                EvidenceLink(
                    kind=EvidenceKind.DATASET,
                    target_id=ds_match.artifact_id,
                    locator=ds_match.locator,
                    score=1.0,
                    notes=f"match={ds_match.method.value}; mention={ds_match.mention}",
                )
            )
            fired.append(f"dataset: {ds_match.artifact_id} {ds_match.locator or '(whole)'}")

        # --- code -----------------------------------------------------------
        for code_match in code_refs.link_code(claim, bundle, code_ids):
            links.append(
                EvidenceLink(
                    kind=EvidenceKind.CODE,
                    target_id=code_match.artifact_id,
                    locator=code_match.locator,
                    score=1.0,
                    notes=f"match={code_match.method.value}",
                )
            )
            observable = code_match.locator or "(no observable)"
            fired.append(f"code: {code_match.artifact_id} {observable}")

        # --- figures --------------------------------------------------------
        for fig_match in figures.link_figures(claim, bundle.figures, figure_mentioned):
            links.append(
                EvidenceLink(
                    kind=EvidenceKind.FIGURE,
                    target_id=fig_match.figure_id,
                    locator=fig_match.locator,
                    score=1.0,
                    notes=f"match={fig_match.method.value}",
                )
            )
            fired.append(f"figure: {fig_match.figure_id} {fig_match.locator or '(whole)'}")

        # Blocks above already append in _KIND_ORDER; sorting makes that an
        # enforced invariant rather than an accident of statement order.
        links.sort(key=lambda link: _KIND_ORDER.index(link.kind))
        linked_claim = claim.model_copy(update={"evidence_links": list(links)})
        return Linking(
            claim=linked_claim,
            links=links,
            passage_candidates=candidates,
            rules_fired=fired,
        )


# ---------------------------------------------------------------------------
# Scoring against the gold evidence links
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SetScore:
    """Precision/recall over a set of link keys, with the disagreements named.

    An empty prediction against an empty gold set scores ``precision = 1.0`` and
    ``recall = 1.0`` — vacuously correct. Read ``tp``/``fp``/``fn`` when that
    matters.
    """

    tp: int
    fp: int
    fn: int
    missing: tuple[str, ...] = ()
    spurious: tuple[str, ...] = ()

    @property
    def precision(self) -> float:
        denominator = self.tp + self.fp
        return self.tp / denominator if denominator else 1.0

    @property
    def recall(self) -> float:
        denominator = self.tp + self.fn
        return self.tp / denominator if denominator else 1.0

    @property
    def f1(self) -> float:
        precision, recall = self.precision, self.recall
        total = precision + recall
        return 2 * precision * recall / total if total else 0.0

    @property
    def exact(self) -> bool:
        """True when the predicted set equals the gold set."""
        return self.fp == 0 and self.fn == 0


@dataclass(frozen=True)
class LinkingScore:
    """A linking scored two ways.

    ``strict`` keys on ``(kind, target_id, locator)`` — the linker must find the
    right cell/column, not merely the right table. ``loose`` keys on
    ``(kind, target_id)`` and answers the weaker question "did it find the right
    artifact at all?". Keys are compared as **sets**, so two gold links into the
    same table collapse to one loose key.
    """

    strict: SetScore
    loose: SetScore


def _strict_key(link: EvidenceLink) -> tuple[str, str, str]:
    return (link.kind.value, link.target_id, link.locator or "")


def _loose_key(link: EvidenceLink) -> tuple[str, str]:
    return (link.kind.value, link.target_id)


def _format_key(key: tuple[str, ...]) -> str:
    return ":".join(part for part in key if part)


def _set_score(predicted: set[tuple[str, ...]], gold: set[tuple[str, ...]]) -> SetScore:
    return SetScore(
        tp=len(predicted & gold),
        fp=len(predicted - gold),
        fn=len(gold - predicted),
        missing=tuple(sorted(_format_key(k) for k in gold - predicted)),
        spurious=tuple(sorted(_format_key(k) for k in predicted - gold)),
    )


def score_linking(predicted: list[EvidenceLink], gold: list[EvidenceLink]) -> LinkingScore:
    """Compare predicted evidence links against a task's gold links.

    ``quote`` is deliberately **not** compared: gold quotes are hand-trimmed spans
    of a passage, while the linker quotes the best-matching whole sentence. Scoring
    a rule-based system on reproducing hand-authored spans would be overclaiming.
    """
    return LinkingScore(
        strict=_set_score({_strict_key(x) for x in predicted}, {_strict_key(x) for x in gold}),
        loose=_set_score({_loose_key(x) for x in predicted}, {_loose_key(x) for x in gold}),
    )


def aggregate_linking_scores(scores: list[LinkingScore]) -> LinkingScore:
    """Sum true/false positives and negatives across many scored tasks.

    The per-task ``missing``/``spurious`` detail is dropped; inspect the individual
    scores for that.
    """

    def total(select: Callable[[LinkingScore], SetScore]) -> SetScore:
        return SetScore(
            tp=sum(select(s).tp for s in scores),
            fp=sum(select(s).fp for s in scores),
            fn=sum(select(s).fn for s in scores),
        )

    return LinkingScore(strict=total(lambda s: s.strict), loose=total(lambda s: s.loose))


# ---------------------------------------------------------------------------
# Rendering + CLI entry points
# ---------------------------------------------------------------------------


def _render_link(link: EvidenceLink) -> str:
    """One line describing an emitted evidence link."""
    where = f" [{link.locator}]" if link.locator else ""
    score = f" score={link.score:g}" if link.score is not None else ""
    return f"{link.kind.value}: {link.target_id}{where}{score}  ({link.notes})"


def linking_to_dict(linking: Linking, score: LinkingScore | None = None) -> dict:
    """Serialize a linking (and optional score) to a JSON-ready dict."""
    payload: dict = {
        "claim_id": linking.claim.claim_id,
        "links": [link.model_dump(mode="json") for link in linking.links],
        "passage_candidates": [
            {
                "paper_id": candidate.paper_id,
                "passage_id": candidate.passage_id,
                "section": candidate.section,
                "method": candidate.method.value,
                "score": round(candidate.score, 6),
                "overlap_score": round(candidate.overlap_score, 6),
                "shared_tokens": list(candidate.shared_tokens),
            }
            for candidate in linking.passage_candidates
        ],
        "rules_fired": linking.rules_fired,
    }
    if score is not None:
        payload["score"] = {
            "strict": {
                "tp": score.strict.tp,
                "fp": score.strict.fp,
                "fn": score.strict.fn,
                "missing": list(score.strict.missing),
                "spurious": list(score.strict.spurious),
            },
            "loose": {"tp": score.loose.tp, "fp": score.loose.fp, "fn": score.loose.fn},
        }
    return payload


def render_linking(
    linking: Linking,
    gold: list[EvidenceLink] | None = None,
    task_id: str | None = None,
) -> str:
    """Render a human-readable linking report (and gold comparison if given)."""
    claim = linking.claim
    lines = [
        "scientific-claim-verifier — evidence linking",
        "=" * 43,
    ]
    if task_id:
        lines.append(f"Task            : {task_id}")
    lines += [
        f"Claim           : {claim.claim_id} ({claim.claim_type.value})",
        f"Text            : {claim.claim_text.strip()}",
        "",
        "Ranked passage candidates (retrieval, not support):",
    ]
    if linking.passage_candidates:
        for rank, candidate in enumerate(linking.passage_candidates, start=1):
            marker = "->" if candidate is linking.passage_candidates[0] else "  "
            section = f" [{candidate.section}]" if candidate.section else ""
            lines.append(
                f"  {marker} {rank}. {candidate.passage_id}{section} "
                f"score={candidate.score:.3f} overlap={candidate.overlap_score:.3f} "
                f"({candidate.method.value})"
            )
    else:
        lines.append("  (no passages in this bundle)")

    lines.append("")
    lines.append("Evidence links:")
    if linking.links:
        for link in linking.links:
            lines.append(f"  - {_render_link(link)}")
    else:
        lines.append("  (none — nothing in the bundle resolves to this claim)")

    passage_links = linking.of_kind(EvidenceKind.PASSAGE)
    if passage_links and passage_links[0].quote:
        lines.append("")
        lines.append("Supporting text (quote; whether it *asserts* the claim is an M5 check):")
        lines.append(f"  {passage_links[0].quote}")

    lines.append("")
    lines.append("Rules fired:")
    for rule in linking.rules_fired:
        lines.append(f"  - {rule}")

    if gold is not None:
        score = score_linking(linking.links, gold)
        lines.append("")
        lines.append(
            f"Gold comparison : strict {score.strict.tp}/{score.strict.tp + score.strict.fn} "
            f"gold links recovered, {score.strict.fp} spurious "
            f"(P={score.strict.precision:.2f} R={score.strict.recall:.2f})"
        )
        for key in score.strict.missing:
            lines.append(f"  [MISS] not linked: {key}")
        for key in score.strict.spurious:
            lines.append(f"  [EXTRA] not in gold: {key}")
        if score.strict.exact:
            lines.append("  [ok ] predicted links match gold exactly (kind, target, locator)")

    return "\n".join(lines)


def link_and_report(
    task_path: str | Path,
    out_dir: str | Path | None = None,
    as_json: bool = False,
    use_declared_source: bool = True,
    repo_root: str | Path | None = None,
) -> int:
    """Load a task, extract its claim, link evidence, print a report, optionally write JSON.

    Returns 0 on success, 1 if the task could not be loaded. The linker consumes the
    extractor's output, so this runs extraction first — the two stages stay separate
    modules but form one pipeline.
    """
    try:
        task: LoadedTask = loader.load_task(task_path, repo_root)
    except (loader.TaskLoadError, OSError) as exc:
        print(f"error: could not load task {task_path}: {exc}", file=sys.stderr)
        return 1

    extraction_result = RuleBasedClaimExtractor().extract(task.input_claim, task.bundle)
    linker = EvidenceLinker(use_declared_source=use_declared_source)
    linking = linker.link(extraction_result.claim, task.bundle)
    gold = task.spec.expected.evidence
    score = score_linking(linking.links, gold)

    if as_json:
        print(json.dumps(linking_to_dict(linking, score), indent=2, sort_keys=True))
    else:
        print(render_linking(linking, gold=gold, task_id=task.spec.task_id))

    if out_dir is not None:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        target = out_path / f"{task.spec.task_id}.linking.json"
        target.write_text(
            json.dumps(linking_to_dict(linking, score), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {target}", file=sys.stderr)
    return 0


def add_link_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``link-evidence`` flags. Shared by the CLI and any script."""
    parser.add_argument("--task", required=True, metavar="PATH", help="Path to a task YAML/JSON.")
    parser.add_argument(
        "--out",
        metavar="DIR",
        default=None,
        help="Write <task_id>.linking.json to this directory.",
    )
    parser.add_argument("--json", action="store_true", help="Print the linking as JSON.")
    parser.add_argument(
        "--no-declared-source",
        action="store_true",
        help=(
            "Ignore the task's claim.source_passage and link passages blind. "
            "This is the setting under which passage retrieval is worth measuring."
        ),
    )


def run_cli(argv: list[str]) -> int:
    """Parse ``link-evidence`` arguments and run. Shared by the CLI and any script."""
    parser = argparse.ArgumentParser(
        prog="claimverifier link-evidence",
        description="Link a task's claim to its supporting evidence (offline).",
    )
    add_link_arguments(parser)
    args = parser.parse_args(argv)
    return link_and_report(
        args.task,
        out_dir=args.out,
        as_json=args.json,
        use_declared_source=not args.no_declared_source,
    )


def main(argv: list[str] | None = None) -> int:
    return run_cli(argv if argv is not None else sys.argv[1:])


__all__ = [
    "Linking",
    "EvidenceLinker",
    "SetScore",
    "LinkingScore",
    "score_linking",
    "aggregate_linking_scores",
    "linking_to_dict",
    "render_linking",
    "link_and_report",
    "add_link_arguments",
    "run_cli",
    "main",
]
