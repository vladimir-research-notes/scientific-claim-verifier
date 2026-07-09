"""Scoring one claim end to end: checks in, `VerificationResult` and trace out.

The orchestration layer for Milestone 7, and the home of ``claimverifier verify`` —
the first command in the pipeline that answers *"is this claim supported?"*. It loads
a task, runs extraction (M3), linking (M4), and the checks (M5/M6), then applies the
three classifiers and assembles the result.

What the report keeps separate
------------------------------
``CLAUDE.md`` requires five things to stay visibly apart, and they are the five blocks
this module renders and records:

=====================  ==================================================================
extracted claim        the typed fields M3 recovered from the sentence
supporting text        the passage M4 retrieved, quoted
computed check         each M5 check, its value, its tolerance, its status
inference              the support label, reproduction status, failure mode — and the
                       named rule that produced each
unverifiable           what this verdict does *not* settle (``limitations``)
=====================  ==================================================================

A verdict is not a summary of the checks; it is an inference *from* them, and the
report shows both so a reader can disagree with the second without losing the first.

The trace
---------
Every run emits a :class:`~scientific_claim_verifier.schemas.RunTrace` as JSONL: the
run's identity, the claim, the evidence, one event per check, one event per classifier
(carrying the rule name, the reason, and the check ids it consulted), and the result.
Keys are sorted and nothing is read from the wall clock, so two runs of one task produce
byte-identical bytes. ``created_at`` stays unset for the same reason.

The trace is **self-describing**, and Milestone 9 depends on that: a report is rendered
from the trace and nothing else — no task file, no bundle, no re-run. So the stream opens
with a ``scoring.run`` event naming the run, the task, the bundle, and the schema version
(``RunTrace.to_jsonl`` serializes events only, so those four facts would otherwise survive
only in the *filename*), and ``scoring.claim`` carries the whole extracted claim rather
than a hand-picked five of its fields. ``reports.reader`` reconstructs this module's
:class:`ScoredClaim` from those bytes, and a test asserts the round trip is exact.

Exit codes
----------
``verify`` exits ``0`` for a claim it manages to score, including a ``contradicted``
one — finding a contradiction is the tool working, not failing. It exits ``1`` only
when a task cannot be loaded.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from ..artifacts import loader
from ..artifacts.loader import LoadedTask
from ..checks import Tolerance
from ..checks.code_execution import ScriptRunner
from ..checks.verification import CheckRun, resolve_override, run_checks
from ..claims.extraction import RuleBasedClaimExtractor
from ..claims.linking import EvidenceLinker
from ..sandbox.trace import write_trace
from ..schemas import (
    CheckStatus,
    CheckType,
    EvidenceKind,
    FailureMode,
    ReproductionStatus,
    RunTrace,
    ScientificClaim,
    SupportLabel,
    VerificationResult,
)
from . import CheckSignal, Rule, decidedness, signals
from .failure_modes import causes, classify_failure, limitations
from .reproducibility import classify_reproduction
from .summary import TaskOutcome, render_summary, summarize, summary_to_dict
from .support_labels import classify_support_signals

#: Every event kind :func:`build_trace` emits, in emission order.
SCORING_EVENT_KINDS = (
    "scoring.run",
    "scoring.claim",
    "scoring.evidence",
    "scoring.check",
    "scoring.support",
    "scoring.reproduction",
    "scoring.failure",
    "scoring.result",
)


@dataclass(frozen=True)
class ScoredClaim:
    """A scored claim: the result, plus the named rules that produced each part of it."""

    result: VerificationResult
    support_rule: Rule
    reproduction_rule: Rule
    failure_rule: Rule
    signals: tuple[CheckSignal, ...]

    @property
    def claim_id(self) -> str:
        return self.result.claim_id

    @property
    def verdict(self) -> tuple[SupportLabel, ReproductionStatus, FailureMode]:
        """The three-part inference, as one comparable tuple."""
        return (
            self.result.support_label,
            self.result.reproduction_status,
            self.result.failure_mode,
        )


# How each label reads in a sentence. Written out rather than derived from the enum
# value, because "is unverifiable_from_artifacts by the supplied artifacts" is not a
# sentence, and a report a human cannot read is not an auditable one.
_VERDICT_PHRASE: dict[SupportLabel, str] = {
    SupportLabel.SUPPORTED: "is supported by the supplied artifacts",
    SupportLabel.CONTRADICTED: "is contradicted by the supplied artifacts",
    SupportLabel.PARTIALLY_SUPPORTED: "is partially supported by the supplied artifacts",
    SupportLabel.UNDERSPECIFIED: "is underspecified: the artifacts cannot pin down what it "
    "refers to",
    SupportLabel.UNVERIFIABLE_FROM_ARTIFACTS: "cannot be verified from the supplied artifacts",
    SupportLabel.NOT_CHECKED: "was not checked against any artifact",
}


def summarize_claim(
    claim: ScientificClaim,
    result: VerificationResult,
    support_rule: Rule,
) -> str:
    """One paragraph a human can read without the tables. Deterministic."""
    checks = result.computed_checks
    decided = sum(1 for c in checks if c.status in (CheckStatus.PASS, CheckStatus.FAIL))
    phrase = _VERDICT_PHRASE[result.support_label]
    lines = [
        f"Claim {claim.claim_id!r} {phrase} ({support_rule.name}: {support_rule.because}).",
        f"Reproduction: {result.reproduction_status.value}. "
        f"Failure mode: {result.failure_mode.value}.",
        f"{decided} of {len(checks)} check(s) reached a verdict.",
    ]
    if result.limitations:
        lines.append(f"{len(result.limitations)} limitation(s) remain; see the report.")
    return " ".join(lines)


def score(run: CheckRun, trace_path: str | None = None) -> ScoredClaim:
    """Apply the three classifiers to a check run and assemble the result."""
    checks = run.checks
    reduced = signals(checks)

    support, support_rule = classify_support_signals(reduced)
    reproduction, reproduction_rule = classify_reproduction(checks)
    failure, failure_rule = classify_failure(checks, support, reproduction)

    evidence_passages = [
        link
        for check in checks
        if check.check_type is CheckType.EVIDENCE_PRESENCE
        for link in check.evidence
        if link.kind is EvidenceKind.PASSAGE
    ]

    result = VerificationResult(
        claim_id=run.claim.claim_id,
        support_label=support,
        reproduction_status=reproduction,
        failure_mode=failure,
        evidence_passages=evidence_passages,
        computed_checks=list(checks),
        confidence=decidedness(checks),
        limitations=limitations(checks),
        trace_path=trace_path,
    )
    result.human_readable_summary = summarize_claim(run.claim, result, support_rule)

    return ScoredClaim(
        result=result,
        support_rule=support_rule,
        reproduction_rule=reproduction_rule,
        failure_rule=failure_rule,
        signals=tuple(reduced),
    )


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------


def build_trace(
    scored: ScoredClaim,
    claim: ScientificClaim,
    *,
    run_id: str,
    task_id: str | None = None,
    bundle_id: str | None = None,
) -> RunTrace:
    """The ordered, byte-stable JSONL record of one scored claim."""
    trace = RunTrace(
        run_id=run_id,
        task_id=task_id,
        bundle_id=bundle_id,
        claim=claim,
        checks=list(scored.result.computed_checks),
        result=scored.result,
    )
    result = scored.result

    trace.add_event(
        "scoring.run",
        "the run this trace records, and the schema its events are written under",
        run_id=run_id,
        task_id=task_id,
        bundle_id=bundle_id,
        schema_version=trace.schema_version,
    )
    # The whole claim, minus its evidence links — those are the next event's subject, and
    # recording them twice would let one copy drift from the other.
    trace.add_event(
        "scoring.claim",
        claim.claim_text.strip(),
        claim=claim.model_dump(mode="json", exclude={"evidence_links"}),
    )
    trace.add_event(
        "scoring.evidence",
        "the supporting text this verdict rests on, as retrieved",
        links=[link.model_dump(mode="json") for link in claim.evidence_links],
    )
    for check, reduced in zip(result.computed_checks, scored.signals, strict=True):
        trace.add_event(
            "scoring.check",
            check.notes,
            check=check.model_dump(mode="json"),
            signal=reduced.signal.value,
            signal_because=reduced.because,
        )
    trace.add_event(
        "scoring.support",
        result.support_label.value,
        support_label=result.support_label.value,
        **scored.support_rule.to_dict(),
    )
    trace.add_event(
        "scoring.reproduction",
        result.reproduction_status.value,
        reproduction_status=result.reproduction_status.value,
        **scored.reproduction_rule.to_dict(),
    )
    trace.add_event(
        "scoring.failure",
        result.failure_mode.value,
        failure_mode=result.failure_mode.value,
        causes=[cause.to_dict() for cause in causes(result.computed_checks)],
        **scored.failure_rule.to_dict(),
    )
    trace.add_event(
        "scoring.result",
        result.human_readable_summary,
        claim_id=result.claim_id,
        confidence=result.confidence,
        limitations=list(result.limitations),
    )
    return trace


# ---------------------------------------------------------------------------
# Serialization and rendering
# ---------------------------------------------------------------------------


def result_to_dict(scored: ScoredClaim, task_id: str | None = None) -> dict:
    """Serialize a scored claim to a JSON-ready dict."""
    payload: dict = {
        "result": scored.result.model_dump(mode="json"),
        "rules": {
            "support": scored.support_rule.to_dict(),
            "reproduction": scored.reproduction_rule.to_dict(),
            "failure": scored.failure_rule.to_dict(),
        },
        "signals": [item.to_dict() for item in scored.signals],
        "causes": [cause.to_dict() for cause in causes(scored.result.computed_checks)],
    }
    if task_id is not None:
        payload["task_id"] = task_id
    return payload


def _gold_line(task: LoadedTask, scored: ScoredClaim) -> str:
    """How the verdict compares to the task's gold outcome, marked field by field."""
    expected = task.spec.expected
    gold = (expected.support_label, expected.reproduction_status, expected.failure_mode)
    marks = [
        "ok " if got is want else "MISS"
        for got, want in zip(scored.verdict, gold, strict=True)
    ]
    return (
        f"Task gold       : {gold[0].value} [{marks[0]}] / {gold[1].value} [{marks[1]}] "
        f"/ {gold[2].value} [{marks[2]}]"
    )


def render_result(
    scored: ScoredClaim, claim: ScientificClaim, task: LoadedTask | None = None
) -> str:
    """Render the verdict with the five audit channels kept visibly separate."""
    result = scored.result
    lines = [
        "scientific-claim-verifier — verification result",
        "=" * 46,
    ]
    if task is not None:
        lines.append(f"Task            : {task.spec.task_id}")
    lines += [
        f"Claim           : {claim.claim_id} ({claim.claim_type.value})",
        f"Text            : {claim.claim_text.strip()}",
        f"Normalized      : {claim.normalized_claim}",
        "",
        "Supporting text (retrieved evidence):",
    ]
    quote = next((link.quote for link in result.evidence_passages if link.quote), None)
    lines.append(f'  "{quote}"' if quote else "  (no passage was linked to this claim)")

    lines += ["", "Computed checks (what each artifact says about the claim):"]
    for check, reduced in zip(result.computed_checks, scored.signals, strict=True):
        target = check.evidence[0].target_id if check.evidence else "—"
        lines.append(
            f"  [{check.status.value:12}] {check.check_type.value:<18} {target:<16} "
            f"-> {reduced.signal.value}"
        )

    lines += [
        "",
        "Inference (drawn from the checks above; each rule names the checks it read):",
        f"  support_label       : {result.support_label.value}",
        f"    rule              : {scored.support_rule.name} "
        f"[{', '.join(scored.support_rule.check_ids) or 'no checks'}]",
        f"    because           : {scored.support_rule.because}",
        f"  reproduction_status : {result.reproduction_status.value}",
        f"    rule              : {scored.reproduction_rule.name}",
        f"    because           : {scored.reproduction_rule.because}",
        f"  failure_mode        : {result.failure_mode.value}",
        f"    rule              : {scored.failure_rule.name}",
        f"    because           : {scored.failure_rule.because}",
        f"  confidence          : {result.confidence:.2f} "
        "(share of checks that reached a verdict; not a probability)",
        "",
        "Unverifiable from these artifacts (what this verdict does NOT settle):",
    ]
    for limitation in result.limitations:
        lines.append(f"  - {limitation}")
    if not result.limitations:
        lines.append("  (none — every check reached a verdict)")

    lines += ["", f"Summary         : {result.human_readable_summary}"]
    if task is not None:
        lines.append(_gold_line(task, scored))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------


def verify_task(
    task_path: str | Path,
    *,
    out_dir: str | Path | None = None,
    use_declared_source: bool = True,
    execute: bool = True,
    abs_tol: float | None = None,
    rel_tol: float | None = None,
    repo_root: str | Path | None = None,
    runner: ScriptRunner | None = None,
) -> tuple[LoadedTask, ScientificClaim, ScoredClaim]:
    """Run the whole pipeline over one task and score it. Writes artifacts if asked.

    Raises :class:`~scientific_claim_verifier.artifacts.loader.TaskLoadError` or
    ``OSError`` if the task cannot be loaded; the CLI turns that into exit code 1.
    """
    task: LoadedTask = loader.load_task(task_path, repo_root)
    root = Path(repo_root) if repo_root is not None else loader.find_repo_root(task.path.parent)

    extraction = RuleBasedClaimExtractor().extract(task.input_claim, task.bundle)
    linking = EvidenceLinker(use_declared_source=use_declared_source).link(
        extraction.claim, task.bundle
    )
    override: Tolerance | None = resolve_override(task, abs_tol, rel_tol)
    run = run_checks(
        linking.claim,
        task.bundle,
        linking.links,
        repo_root=root,
        override=override,
        runner=runner,
        execute=execute,
    )

    task_id = task.spec.task_id
    trace_path = str(Path(out_dir) / f"{task_id}.trace.jsonl") if out_dir is not None else None
    scored = score(run, trace_path=trace_path)

    if out_dir is not None:
        target = Path(out_dir)
        target.mkdir(parents=True, exist_ok=True)
        trace = build_trace(
            scored,
            linking.claim,
            run_id=task_id,
            task_id=task_id,
            bundle_id=task.bundle.bundle_id,
        )
        write_trace(trace, trace_path)
        payload = result_to_dict(scored, task_id=task_id)
        (target / f"{task_id}.result.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    return task, linking.claim, scored


def outcome_of(task: LoadedTask, scored: ScoredClaim) -> TaskOutcome:
    """Pair a scored claim with its task's gold outcome, for the aggregate summary."""
    expected = task.spec.expected
    return TaskOutcome(
        task_id=task.spec.task_id,
        claim_id=scored.claim_id,
        predicted_support=scored.result.support_label,
        predicted_reproduction=scored.result.reproduction_status,
        predicted_failure=scored.result.failure_mode,
        gold_support=expected.support_label,
        gold_reproduction=expected.reproduction_status,
        gold_failure=expected.failure_mode,
    )


def verify_and_report(
    task_paths: list[str] | list[Path],
    out_dir: str | Path | None = None,
    as_json: bool = False,
    use_declared_source: bool = True,
    execute: bool = True,
    abs_tol: float | None = None,
    rel_tol: float | None = None,
    repo_root: str | Path | None = None,
    runner: ScriptRunner | None = None,
) -> int:
    """Verify one or more tasks, print reports, and (for several) an aggregate summary."""
    outcomes: list[TaskOutcome] = []
    payloads: list[dict] = []

    for task_path in task_paths:
        try:
            task, claim, scored = verify_task(
                task_path,
                out_dir=out_dir,
                use_declared_source=use_declared_source,
                execute=execute,
                abs_tol=abs_tol,
                rel_tol=rel_tol,
                repo_root=repo_root,
                runner=runner,
            )
        except (loader.TaskLoadError, OSError) as exc:
            print(f"error: could not load task {task_path}: {exc}", file=sys.stderr)
            return 1

        outcomes.append(outcome_of(task, scored))
        if as_json:
            payloads.append(result_to_dict(scored, task_id=task.spec.task_id))
        else:
            print(render_result(scored, claim, task=task))
            print()
        if out_dir is not None:
            print(f"wrote {Path(out_dir) / task.spec.task_id}.{{result.json,trace.jsonl}}",
                  file=sys.stderr)

    summary = summarize(outcomes)
    if as_json:
        document: dict = {"results": payloads}
        if len(outcomes) > 1:
            document["summary"] = summary_to_dict(summary)
        print(json.dumps(document, indent=2, sort_keys=True))
    elif len(outcomes) > 1:
        print(render_summary(summary))

    if out_dir is not None and len(outcomes) > 1:
        target = Path(out_dir) / "summary.json"
        target.write_text(
            json.dumps(summary_to_dict(summary), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"\nwrote {target}", file=sys.stderr)
    return 0


def add_verify_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``verify`` flags. Shared by the CLI and any script."""
    parser.add_argument(
        "--task",
        required=True,
        action="append",
        metavar="PATH",
        help="Path to a task YAML/JSON. Repeat to score several and get a summary.",
    )
    parser.add_argument(
        "--out",
        metavar="DIR",
        default=None,
        help="Write <task_id>.result.json and <task_id>.trace.jsonl (and summary.json) here.",
    )
    parser.add_argument("--json", action="store_true", help="Print the results as JSON.")
    parser.add_argument(
        "--no-declared-source",
        action="store_true",
        help="Ignore the task's claim.source_passage and link passages blind.",
    )
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="Do not run fixture scripts; reproduction is reported as not_attempted.",
    )
    parser.add_argument(
        "--abs-tol",
        type=float,
        default=None,
        metavar="F",
        help="Absolute tolerance, overriding the claim's reported precision.",
    )
    parser.add_argument(
        "--rel-tol",
        type=float,
        default=None,
        metavar="F",
        help="Relative tolerance, overriding the claim's reported precision.",
    )


def run_cli(argv: list[str]) -> int:
    """Parse ``verify`` arguments and run. Shared by the CLI and any script."""
    parser = argparse.ArgumentParser(
        prog="claimverifier verify",
        description="Verify a claim against its artifacts and assign a support label (offline).",
    )
    add_verify_arguments(parser)
    args = parser.parse_args(argv)
    return verify_and_report(
        args.task,
        out_dir=args.out,
        as_json=args.json,
        use_declared_source=not args.no_declared_source,
        execute=not args.no_execute,
        abs_tol=args.abs_tol,
        rel_tol=args.rel_tol,
    )


def main(argv: list[str] | None = None) -> int:
    return run_cli(argv if argv is not None else sys.argv[1:])


__all__ = [
    "SCORING_EVENT_KINDS",
    "ScoredClaim",
    "score",
    "summarize_claim",
    "build_trace",
    "result_to_dict",
    "render_result",
    "verify_task",
    "outcome_of",
    "verify_and_report",
    "add_verify_arguments",
    "run_cli",
    "main",
]
