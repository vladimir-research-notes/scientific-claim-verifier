"""Run every applicable check for one claim, and report them channel by channel.

The orchestration layer for Milestone 5. It takes the extracted claim (M3) and its
evidence links (M4), dispatches each link to the check that knows how to read it,
and returns an ordered, deterministic list of
:class:`~scientific_claim_verifier.schemas.VerificationCheck` records.

Which checks run is driven by the **evidence**, not by the claim type. A claim with
a table link gets a table check; one with a dataset column gets a statistic
recomputed; one with a code link gets its script run. A claim whose only evidence
is a passage gets exactly one check — and that is a fact about the claim worth
seeing, not a gap to paper over.

What this stage deliberately does not do
----------------------------------------
It assigns no support label, no reproduction status, and no failure mode. Those are
inferences drawn from the whole set of checks, and they are Milestone 7's. The
report below therefore prints the *supporting text* and the *computed checks* as
separate blocks, lists what could not be decided, and states plainly that the
verdict has not been reached. A task's gold label is shown only as context.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..artifacts import loader
from ..artifacts.loader import LoadedTask
from ..claims.extraction import RuleBasedClaimExtractor
from ..claims.linking import EvidenceLinker
from ..schemas import (
    ArtifactBundle,
    CheckStatus,
    CheckType,
    EvidenceKind,
    EvidenceLink,
    Passage,
    ScientificClaim,
    VerificationCheck,
)
from . import Tolerance, check_id
from .code_execution import ScriptRunner, code_execution_check
from .consistency import comparison_check, evidence_presence_check
from .statistical import (
    count_condition,
    dataset_statistic_check,
    numeric_tolerance_check,
    primary_statistic,
)
from .table_recompute import table_value_check

# Emission order. Evidence first (what does the paper say?), then what the artifacts
# compute, then whether the number agrees. Fixed so a run's checks — and therefore
# the JSON artifact and the trace — are byte-stable.
_CHECK_ORDER = (
    CheckType.EVIDENCE_PRESENCE,
    CheckType.TABLE_VALUE,
    CheckType.COMPARISON,
    CheckType.DATASET_STATISTIC,
    CheckType.FIGURE_RECOMPUTE,
    CheckType.CODE_EXECUTION,
    CheckType.NUMERIC_TOLERANCE,
)

# Statuses a report groups under "could not be decided from these artifacts".
UNDECIDED = (CheckStatus.INCONCLUSIVE, CheckStatus.ERROR, CheckStatus.SKIPPED)


@dataclass
class CheckRun:
    """Every check run against one claim, plus the counts a summary line needs."""

    claim: ScientificClaim
    checks: list[VerificationCheck] = field(default_factory=list)

    def of_type(self, check_type: CheckType) -> list[VerificationCheck]:
        """The checks of one type, in emission order."""
        return [c for c in self.checks if c.check_type is check_type]

    def of_status(self, status: CheckStatus) -> list[VerificationCheck]:
        """The checks with one status, in emission order."""
        return [c for c in self.checks if c.status is status]

    @property
    def counts(self) -> dict[str, int]:
        """Per-status counts, always including every status (zeros included)."""
        return {status.value: len(self.of_status(status)) for status in CheckStatus}


class _Ordinals:
    """Per-check-type counters, so ids read ``…dataset_statistic.1``, ``.2``."""

    def __init__(self) -> None:
        self._seen: dict[CheckType, int] = {}

    def next(self, claim_id: str, check_type: CheckType) -> str:
        self._seen[check_type] = self._seen.get(check_type, 0) + 1
        return check_id(claim_id, check_type, self._seen[check_type])


def find_passage(bundle: ArtifactBundle, passage_id: str) -> Passage | None:
    """The passage with ``passage_id`` in any paper of ``bundle``, or ``None``."""
    for paper in bundle.papers:
        passage = paper.passage(passage_id)
        if passage is not None:
            return passage
    return None


def _dangling(
    ident: str, claim: ScientificClaim, check_type: CheckType, link: EvidenceLink
) -> VerificationCheck:
    """An evidence link whose target is not in the bundle: a pipeline defect, so ``error``."""
    return VerificationCheck(
        check_id=ident,
        check_type=check_type,
        claim_id=claim.claim_id,
        status=CheckStatus.ERROR,
        evidence=[link],
        inputs={"target_id": link.target_id},
        notes=f"linked {link.kind.value} {link.target_id!r} does not resolve to any artifact",
    )


def _observed_cell_values(checks: list[VerificationCheck]) -> dict[str, float]:
    """Map ``expected_value``/``baseline_value`` to the cell value read back for it.

    Only cell checks contribute: a column check found the value *somewhere* in the
    column, which is not enough to say which side of a comparison it is.
    """
    observed: dict[str, float] = {}
    for check in checks:
        claim_field = check.inputs.get("claim_field")
        value = check.computed_value
        if claim_field and isinstance(value, int | float) and check.status is not CheckStatus.ERROR:
            observed[str(claim_field)] = float(value)
    return observed


def run_checks(
    claim: ScientificClaim,
    bundle: ArtifactBundle,
    links: list[EvidenceLink],
    *,
    repo_root: Path,
    override: Tolerance | None = None,
    runner: ScriptRunner | None = None,
    execute: bool = True,
) -> CheckRun:
    """Run every check the claim's evidence supports, in a fixed order."""
    ordinals = _Ordinals()
    checks: list[VerificationCheck] = []

    def ident(check_type: CheckType) -> str:
        return ordinals.next(claim.claim_id, check_type)

    # --- evidence: does the supporting text actually assert the claim? ---------
    passage_links = [link for link in links if link.kind is EvidenceKind.PASSAGE]
    passage_link = passage_links[0] if passage_links else None
    passage = find_passage(bundle, passage_link.target_id) if passage_link else None
    checks.append(
        evidence_presence_check(ident(CheckType.EVIDENCE_PRESENCE), claim, passage_link, passage)
    )

    # --- tables: read the located cell or column back from the bundle ----------
    table_checks: list[VerificationCheck] = []
    for link in (x for x in links if x.kind is EvidenceKind.TABLE):
        target = bundle.table(link.target_id)
        table_checks.append(
            _dangling(ident(CheckType.TABLE_VALUE), claim, CheckType.TABLE_VALUE, link)
            if target is None
            else table_value_check(ident(CheckType.TABLE_VALUE), claim, target, link, override)
        )
    checks.extend(table_checks)

    # --- comparison: only for a claim that actually asserts a relation ---------
    if (
        claim.comparison_operator is not None
        and claim.baseline_value is not None
        and claim.expected_value is not None
    ):
        observed = _observed_cell_values(table_checks)
        checks.append(
            comparison_check(
                ident(CheckType.COMPARISON),
                claim,
                observed.get("baseline_value"),
                observed.get("expected_value"),
                [c.evidence[0] for c in table_checks if c.evidence],
                override,
            )
        )

    # --- datasets: recompute the statistic over the located column -------------
    statistic = primary_statistic(claim)
    count = count_condition(claim)
    for link in (x for x in links if x.kind is EvidenceKind.DATASET):
        dataset = bundle.dataset(link.target_id)
        if dataset is None:
            statistic_type = CheckType.DATASET_STATISTIC
            checks.append(_dangling(ident(statistic_type), claim, statistic_type, link))
            continue
        if statistic is None:
            checks.append(
                VerificationCheck(
                    check_id=ident(CheckType.DATASET_STATISTIC),
                    check_type=CheckType.DATASET_STATISTIC,
                    claim_id=claim.claim_id,
                    status=CheckStatus.SKIPPED,
                    evidence=[link],
                    inputs={"dataset_id": dataset.artifact_id, "metrics": list(claim.metrics)},
                    notes="the claim names no statistic this checker can recompute "
                    f"(metrics: {claim.metrics or 'none'})",
                )
            )
            continue

        expected = count if statistic == "count" else claim.expected_value
        checks.append(
            dataset_statistic_check(
                ident(CheckType.DATASET_STATISTIC),
                claim,
                dataset,
                link,
                statistic,
                float(expected) if expected is not None else None,
                repo_root,
                override,
            )
        )
        # A stated sample count ("12 samples") is a second, independently checkable
        # assertion about the same dataset — and it is compared exactly.
        if statistic != "count" and count is not None:
            checks.append(
                dataset_statistic_check(
                    ident(CheckType.DATASET_STATISTIC),
                    claim,
                    dataset,
                    link,
                    "count",
                    float(count),
                    repo_root,
                    override,
                )
            )

    # --- code: run the script, then judge its number separately ----------------
    for link in (x for x in links if x.kind is EvidenceKind.CODE):
        artifact = bundle.code(link.target_id)
        if artifact is None:
            checks.append(
                _dangling(ident(CheckType.CODE_EXECUTION), claim, CheckType.CODE_EXECUTION, link)
            )
            continue
        execution = code_execution_check(
            ident(CheckType.CODE_EXECUTION),
            claim,
            artifact,
            link,
            bundle.expected_outputs,
            repo_root,
            runner,
            execute,
        )
        checks.append(execution)
        if claim.expected_value is None:
            continue

        value = execution.computed_value if isinstance(execution.computed_value, float) else None
        observable = execution.inputs.get("observable")
        source = f"stdout: {observable}" if observable else f"{link.target_id} stdout"
        checks.append(
            numeric_tolerance_check(
                ident(CheckType.NUMERIC_TOLERANCE), claim, value, source, [link], override
            )
        )

    # The blocks above already append in `_CHECK_ORDER`; sorting makes that an
    # enforced invariant rather than an accident of statement order.
    checks.sort(key=lambda check: _CHECK_ORDER.index(check.check_type))
    return CheckRun(claim=claim, checks=checks)


# ---------------------------------------------------------------------------
# Rendering + CLI entry points
# ---------------------------------------------------------------------------


def _target(check: VerificationCheck) -> str:
    """A short ``artifact[locator]`` label for a check's evidence."""
    if not check.evidence:
        return "—"
    link = check.evidence[0]
    return f"{link.target_id}{f'[{link.locator}]' if link.locator else ''}"


def checks_to_dict(run: CheckRun, task_id: str | None = None) -> dict:
    """Serialize a check run to a JSON-ready dict."""
    payload: dict = {
        "claim_id": run.claim.claim_id,
        "checks": [check.model_dump(mode="json") for check in run.checks],
        "counts": run.counts,
    }
    if task_id is not None:
        payload["task_id"] = task_id
    return payload


def render_checks(run: CheckRun, task: LoadedTask | None = None) -> str:
    """Render the run with the audit channels kept visibly separate."""
    claim = run.claim
    lines = [
        "scientific-claim-verifier — verification checks",
        "=" * 46,
    ]
    if task is not None:
        lines.append(f"Task            : {task.spec.task_id}")
    lines += [
        f"Claim           : {claim.claim_id} ({claim.claim_type.value})",
        f"Text            : {claim.claim_text.strip()}",
        f"Normalized      : {claim.normalized_claim}",
        "",
        "Supporting text (retrieved evidence; whether it *asserts* the claim is checked below):",
    ]
    presence = run.of_type(CheckType.EVIDENCE_PRESENCE)
    quote = presence[0].inputs.get("quoted_sentence") if presence else None
    if quote:
        lines.append(f'  "{quote}"')
    else:
        lines.append("  (no passage was linked to this claim)")

    lines.append("")
    lines.append("Computed checks (each reads an artifact; none of them decides the verdict):")
    decided = [c for c in run.checks if c.status not in UNDECIDED]
    for check in decided:
        lines.append(
            f"  [{check.status.value:4}] {check.check_type.value:<18} "
            f"{_target(check):<28} {check.notes}"
        )
    if not decided:
        lines.append("  (none — no check could reach a pass/fail verdict)")

    undecided = [c for c in run.checks if c.status in UNDECIDED]
    lines.append("")
    lines.append("Not decided by these artifacts (inconclusive / error / skipped):")
    for check in undecided:
        lines.append(
            f"  [{check.status.value:12}] {check.check_type.value:<18} "
            f"{_target(check):<28} {check.notes}"
        )
    if not undecided:
        lines.append("  (none)")

    counts = run.counts
    lines += [
        "",
        f"Summary         : {len(run.checks)} check(s) — "
        + ", ".join(f"{n} {status}" for status, n in counts.items() if n),
        "",
        "Inference       : NOT produced by this stage. The support label, reproduction",
        "                  status, and failure mode are inferred from these checks in",
        "                  Milestone 7 (scoring).",
    ]
    if task is not None:
        expected = task.spec.expected
        lines.append(
            f"Task gold       : {expected.support_label.value} / "
            f"{expected.reproduction_status.value} / {expected.failure_mode.value} "
            "(context only; not scored at this stage)"
        )
    return "\n".join(lines)


def resolve_override(
    task: LoadedTask, abs_tol: float | None = None, rel_tol: float | None = None
) -> Tolerance | None:
    """Resolve the tolerance override: CLI flags beat the task file; both may be absent.

    ``None`` means "no override" — each check then derives its tolerance from the
    claim's own reported precision.
    """
    if abs_tol is not None or rel_tol is not None:
        return Tolerance(abs_tol=abs_tol or 0.0, rel_tol=rel_tol or 0.0)
    declared = task.spec.tolerance
    if declared is not None:
        return Tolerance(abs_tol=declared.abs_tol, rel_tol=declared.rel_tol)
    return None


def check_and_report(
    task_path: str | Path,
    out_dir: str | Path | None = None,
    as_json: bool = False,
    use_declared_source: bool = True,
    execute: bool = True,
    abs_tol: float | None = None,
    rel_tol: float | None = None,
    repo_root: str | Path | None = None,
    runner: ScriptRunner | None = None,
) -> int:
    """Load a task, extract, link, run its checks, print a report, optionally write JSON.

    Returns 0 on success, 1 if the task could not be loaded. Extraction and linking
    run first — the three stages stay separate modules but form one pipeline.
    """
    try:
        task: LoadedTask = loader.load_task(task_path, repo_root)
    except (loader.TaskLoadError, OSError) as exc:
        print(f"error: could not load task {task_path}: {exc}", file=sys.stderr)
        return 1

    root = Path(repo_root) if repo_root is not None else loader.find_repo_root(task.path.parent)
    extraction = RuleBasedClaimExtractor().extract(task.input_claim, task.bundle)
    linking = EvidenceLinker(use_declared_source=use_declared_source).link(
        extraction.claim, task.bundle
    )
    run = run_checks(
        linking.claim,
        task.bundle,
        linking.links,
        repo_root=root,
        override=resolve_override(task, abs_tol, rel_tol),
        runner=runner,
        execute=execute,
    )

    payload = checks_to_dict(run, task_id=task.spec.task_id)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_checks(run, task=task))

    if out_dir is not None:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        target = out_path / f"{task.spec.task_id}.checks.json"
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nwrote {target}", file=sys.stderr)
    return 0


def add_check_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``run-checks`` flags. Shared by the CLI and ``scripts/03_run_checks.py``."""
    parser.add_argument("--task", required=True, metavar="PATH", help="Path to a task YAML/JSON.")
    parser.add_argument(
        "--out", metavar="DIR", default=None, help="Write <task_id>.checks.json to this directory."
    )
    parser.add_argument("--json", action="store_true", help="Print the checks as JSON.")
    parser.add_argument(
        "--no-declared-source",
        action="store_true",
        help="Ignore the task's claim.source_passage and link passages blind.",
    )
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="Do not run fixture scripts; record the code-execution check as skipped.",
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
    """Parse ``run-checks`` arguments and run. Shared by the CLI and the script."""
    parser = argparse.ArgumentParser(
        prog="claimverifier run-checks",
        description="Run the deterministic verification checks for a task (offline).",
    )
    add_check_arguments(parser)
    args = parser.parse_args(argv)
    return check_and_report(
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
    "UNDECIDED",
    "CheckRun",
    "find_passage",
    "run_checks",
    "resolve_override",
    "checks_to_dict",
    "render_checks",
    "check_and_report",
    "add_check_arguments",
    "run_cli",
    "main",
]
