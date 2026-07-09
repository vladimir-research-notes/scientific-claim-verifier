"""The offline smoke suite: run every task end to end, and gate on the result.

Milestone 8, and the home of ``claimverifier run-suite``. A suite (``tasks/smoke_suite.yaml``)
names an ordered set of tasks; this module loads each, drives the whole pipeline over it —
extraction (M3), linking (M4), checks (M5), sandboxed execution (M6), scoring (M7) — and
writes the artifacts a reader needs to audit the run without re-running it:

======================  =====================================================
``<task_id>.trace.jsonl``  the ordered, byte-stable event stream for one claim
``<task_id>.result.json``  the verdict, the rules that produced it, the signals
``summary.csv``            one row per task: predicted vs. gold, check counts
``summary.json``           the aggregate, the gate, and per-task metadata
``summary.txt``            the rendered report, byte-for-byte as printed
======================  =====================================================

Markdown and HTML reports are Milestone 9's; nothing here renders one.

A suite is a gate, not a scoreboard
-----------------------------------
The suite exits non-zero when the pipeline **regresses**, and the definition of
regression is deliberately asymmetric (see :func:`gate`):

- Any **wrong verdict** — a committal support label the task's gold outcome disagrees
  with — fails the run. The suite file has no key that could declare one acceptable.
- A **conservative miss** — the pipeline predicted ``unverifiable_from_artifacts`` or
  ``not_checked`` where gold commits — fails the run *only if the set of them changed*.
  The suite file declares the standing misses by name; a new one is a regression, and a
  fixed one must be removed from the file rather than left to rot.

That asymmetry is the whole point. A change that raises label accuracy by turning a
claim the pipeline honestly declined to decide into one it decides *wrongly* has made
the tool worse, and a single accuracy number would have called it an improvement.

The gate does not apply to a ``--no-execute`` run: skipping the fixture scripts leaves
every code-reproduction claim undecided by its own artifacts, and the gold outcomes it
would be judged against assume the scripts ran. Such a run reports and exits ``0``.

Determinism
-----------
Tasks run in the suite's declared order. Nothing reads the wall clock or an RNG, and the
three code fixtures that execute do so under the recorded sandbox policy. Two runs of the
suite produce byte-identical ``*.trace.jsonl``, ``summary.csv``, and ``summary.json``.

The two artifacts that are *not* byte-identical across output directories are so by
construction, and in exactly one field each: ``<task_id>.result.json`` records the
absolute ``trace_path`` of its own trace (Milestone 7), and ``summary.txt`` names the
directory it was written to. Nothing else in either file varies. ``summary.csv`` names
each trace by filename alone, so it stays portable.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from .artifacts import loader
from .artifacts.loader import LoadedSuite, SuiteSpec
from .checks.code_execution import ScriptRunner
from .schemas import CheckStatus
from .scoring.summary import SuiteSummary, TaskOutcome, render_summary, summarize, summary_to_dict
from .scoring.verdict import ScoredClaim, outcome_of, verify_task

# Everything a malformed suite or task can raise on the way in. A schema error is a
# fact about the file, not a bug in the runner, so it is reported rather than raised:
# `run-suite` on a broken YAML file should print what is wrong with it and exit 1.
LOAD_ERRORS = (loader.SuiteLoadError, loader.TaskLoadError, ValidationError, OSError)

#: The default suite, per ``docs/PLAN.md`` §10.
DEFAULT_SUITE = "tasks/smoke_suite.yaml"

#: Where a suite's artifacts are written, under ``--out``: ``<out>/<suite_id>/``.
SUMMARY_JSON = "summary.json"
SUMMARY_CSV = "summary.csv"
SUMMARY_TXT = "summary.txt"

#: Columns of ``summary.csv``, in order. Every value is a scalar, and none is a path
#: outside the run directory, so the file is byte-stable across machines.
SUMMARY_CSV_COLUMNS = (
    "task_id",
    "family",
    "claim_id",
    "claim_type",
    "support_label",
    "gold_support_label",
    "support_matches",
    "support_outcome",
    "reproduction_status",
    "gold_reproduction_status",
    "reproduction_matches",
    "failure_mode",
    "gold_failure_mode",
    "failure_matches",
    "confidence",
    "n_checks",
    "n_pass",
    "n_fail",
    "n_inconclusive",
    "n_error",
    "n_skipped",
    "trace",
)

#: How a task's support label compares to its gold label. See :mod:`.scoring.summary`.
MATCH = "match"
CONSERVATIVE_MISS = "conservative_miss"
WRONG_VERDICT = "wrong_verdict"

# Per-task line markers, keyed by the outcome above.
_MARK = {MATCH: "ok  ", CONSERVATIVE_MISS: "shy ", WRONG_VERDICT: "MISS"}


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SuiteRecord:
    """One task's run: its verdict, its gold comparison, and where its trace landed."""

    task_id: str
    family: str
    claim_type: str
    scored: ScoredClaim
    outcome: TaskOutcome
    trace_name: str | None = None

    @property
    def claim_id(self) -> str:
        return self.outcome.claim_id

    @property
    def support_outcome(self) -> str:
        """``match``, ``conservative_miss``, or ``wrong_verdict``."""
        if self.outcome.support_matches:
            return MATCH
        return CONSERVATIVE_MISS if self.outcome.is_conservative_miss else WRONG_VERDICT

    @property
    def fully_matches(self) -> bool:
        """True when all three of support, reproduction, and failure mode match gold."""
        return (
            self.outcome.support_matches
            and self.outcome.reproduction_matches
            and self.outcome.failure_matches
        )

    @property
    def check_counts(self) -> dict[str, int]:
        """Per-status counts over this claim's checks, every status present."""
        checks = self.scored.result.computed_checks
        return {s.value: sum(1 for c in checks if c.status is s) for s in CheckStatus}


@dataclass(frozen=True)
class SuiteRun:
    """Every task in a suite, scored, plus the aggregate and where artifacts went."""

    spec: SuiteSpec
    records: tuple[SuiteRecord, ...]
    summary: SuiteSummary
    out_dir: Path | None = None
    executed: bool = True

    @property
    def suite_id(self) -> str:
        return self.spec.suite_id

    @property
    def n_tasks(self) -> int:
        return len(self.records)


@dataclass(frozen=True)
class Gate:
    """The regression verdict for a suite run: does it pass, and if not, why not.

    ``applicable`` is ``False`` for a run made with ``--no-execute``. The tasks' gold
    outcomes assume their scripts ran, so a run that skipped them has nothing to be
    compared against — and reporting the resulting label shifts as *wrong verdicts*
    would blame the pipeline for the operator's flag.
    """

    ok: bool
    problems: tuple[str, ...] = ()
    applicable: bool = True

    def to_dict(self) -> dict:
        return {"ok": self.ok, "applicable": self.applicable, "problems": list(self.problems)}


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def run_suite(
    suite: LoadedSuite,
    *,
    out_dir: str | Path | None = None,
    use_declared_source: bool = True,
    execute: bool = True,
    abs_tol: float | None = None,
    rel_tol: float | None = None,
    repo_root: str | Path | None = None,
    runner: ScriptRunner | None = None,
) -> SuiteRun:
    """Verify every task in ``suite``, in its declared order.

    When ``out_dir`` is given, each task's trace and result JSON are written there by
    :func:`~scientific_claim_verifier.scoring.verdict.verify_task`; the caller writes the
    aggregate files (see :func:`write_artifacts`). Raises
    :class:`~scientific_claim_verifier.artifacts.loader.TaskLoadError` or ``OSError`` if
    any task fails to load — a suite reports all its tasks or none.
    """
    target = Path(out_dir) if out_dir is not None else None
    records: list[SuiteRecord] = []

    for task_path in suite.task_paths:
        task, _claim, scored = verify_task(
            task_path,
            out_dir=target,
            use_declared_source=use_declared_source,
            execute=execute,
            abs_tol=abs_tol,
            rel_tol=rel_tol,
            repo_root=repo_root,
            runner=runner,
        )
        task_id = task.spec.task_id
        records.append(
            SuiteRecord(
                task_id=task_id,
                family=task.spec.family,
                claim_type=task.spec.claim.claim_type.value,
                scored=scored,
                outcome=outcome_of(task, scored),
                trace_name=f"{task_id}.trace.jsonl" if target is not None else None,
            )
        )

    return SuiteRun(
        spec=suite.spec,
        records=tuple(records),
        summary=summarize([record.outcome for record in records]),
        out_dir=target,
        executed=execute,
    )


def gate(run: SuiteRun) -> Gate:
    """Decide whether the run regressed. See this module's docstring for the asymmetry.

    A run with ``execute=False`` is not gated at all: skipping the fixture scripts turns
    every code-reproduction claim into one the artifacts no longer speak to, and the gold
    outcomes it would be measured against assume the opposite.
    """
    if not run.executed:
        return Gate(ok=True, applicable=False)

    problems: list[str] = []

    for task_id in run.summary.wrong_verdicts:
        record = next(r for r in run.records if r.task_id == task_id)
        problems.append(
            f"wrong verdict: {task_id} predicted "
            f"{record.outcome.predicted_support.value!r}, gold says "
            f"{record.outcome.gold_support.value!r} — the pipeline asserted a label its "
            "own fixture contradicts"
        )

    observed = set(run.summary.conservative_misses)
    declared = set(run.spec.expected.conservative_misses)
    for task_id in sorted(observed - declared):
        problems.append(
            f"new conservative miss: {task_id} — the pipeline declined to decide a claim the "
            "suite does not list as a standing miss. If this is intended, add it to "
            "expected.conservative_misses"
        )
    for task_id in sorted(declared - observed):
        problems.append(
            f"stale conservative miss: {task_id} is now decided, but the suite still "
            "declares it a standing miss. Remove it from expected.conservative_misses"
        )

    return Gate(ok=not problems, problems=tuple(problems))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _confidence(record: SuiteRecord) -> float:
    """A record's confidence, defaulting to 0.0 when scoring recorded none."""
    return record.scored.result.confidence or 0.0


def summary_row(record: SuiteRecord) -> dict[str, object]:
    """One task's row of ``summary.csv``, keyed by :data:`SUMMARY_CSV_COLUMNS`."""
    outcome = record.outcome
    counts = record.check_counts
    return {
        "task_id": record.task_id,
        "family": record.family,
        "claim_id": record.claim_id,
        "claim_type": record.claim_type,
        "support_label": outcome.predicted_support.value,
        "gold_support_label": outcome.gold_support.value,
        "support_matches": outcome.support_matches,
        "support_outcome": record.support_outcome,
        "reproduction_status": outcome.predicted_reproduction.value,
        "gold_reproduction_status": outcome.gold_reproduction.value,
        "reproduction_matches": outcome.reproduction_matches,
        "failure_mode": outcome.predicted_failure.value,
        "gold_failure_mode": outcome.gold_failure.value,
        "failure_matches": outcome.failure_matches,
        "confidence": f"{_confidence(record):.6f}",
        "n_checks": sum(counts.values()),
        "n_pass": counts[CheckStatus.PASS.value],
        "n_fail": counts[CheckStatus.FAIL.value],
        "n_inconclusive": counts[CheckStatus.INCONCLUSIVE.value],
        "n_error": counts[CheckStatus.ERROR.value],
        "n_skipped": counts[CheckStatus.SKIPPED.value],
        "trace": record.trace_name or "",
    }


def summary_csv(run: SuiteRun) -> str:
    """Render ``summary.csv`` as text. ``\\n`` line endings, so the bytes are portable."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(SUMMARY_CSV_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for record in run.records:
        writer.writerow(summary_row(record))
    return buffer.getvalue()


def suite_to_dict(run: SuiteRun, verdict: Gate | None = None) -> dict:
    """Serialize a suite run to a JSON-ready dict.

    ``summary`` is the Milestone 7 aggregate document verbatim (it carries each task's
    predicted and gold verdict); ``tasks`` adds the run-level metadata that only the
    suite knows — family, claim type, confidence, check counts, and the trace filename.
    The two join on ``task_id``.
    """
    decision = verdict if verdict is not None else gate(run)
    return {
        "suite": {
            "suite_id": run.suite_id,
            "name": run.spec.name,
            "version": run.spec.version,
            "n_tasks": run.n_tasks,
            "scripts_executed": run.executed,
        },
        "gate": decision.to_dict(),
        "summary": summary_to_dict(run.summary),
        "tasks": [
            {
                "task_id": record.task_id,
                "family": record.family,
                "claim_id": record.claim_id,
                "claim_type": record.claim_type,
                "support_outcome": record.support_outcome,
                "confidence": _confidence(record),
                "check_counts": record.check_counts,
                "trace": record.trace_name,
            }
            for record in run.records
        ],
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _verdict_line(record: SuiteRecord) -> str:
    outcome = record.outcome
    return (
        f"  [{_MARK[record.support_outcome]}] {record.task_id:<24} "
        f"{outcome.predicted_support.value} / {outcome.predicted_reproduction.value} / "
        f"{outcome.predicted_failure.value}"
    )


def _gold_line(record: SuiteRecord) -> str:
    """The gold verdict, indented to sit directly under the task id above it."""
    outcome = record.outcome
    return (
        f"{'':<9}gold: {outcome.gold_support.value} / "
        f"{outcome.gold_reproduction.value} / {outcome.gold_failure.value}"
    )


def render_suite(run: SuiteRun, verdict: Gate | None = None) -> str:
    """Render the suite report: per-task verdicts, the aggregate, and the gate."""
    decision = verdict if verdict is not None else gate(run)
    name = f" ({run.spec.name})" if run.spec.name else ""
    version = f" v{run.spec.version}" if run.spec.version else ""
    scripts = "executed in the controlled sandbox" if run.executed else "not run (--no-execute)"
    artifacts = str(run.out_dir) if run.out_dir is not None else "not written (no --out)"

    lines = [
        "scientific-claim-verifier — smoke suite",
        "=" * 39,
        f"Suite           : {run.suite_id}{name}{version}",
        f"Tasks           : {run.n_tasks}",
        f"Fixture scripts : {scripts}",
        f"Artifacts       : {artifacts}",
        "",
        "Per-task verdict (support / reproduction / failure_mode); gold shown where it differs:",
    ]
    for record in run.records:
        lines.append(_verdict_line(record))
        if not record.fully_matches:
            lines.append(_gold_line(record))

    lines += ["", render_summary(run.summary), ""]

    if not decision.applicable:
        lines += [
            "Gate            : NOT APPLICABLE",
            "  --no-execute skipped the fixture scripts, and the gold outcomes above assume",
            "  they ran. Any 'wrong verdict' reported here is that flag, not a regression.",
            "  Run without --no-execute to gate.",
        ]
    elif decision.ok:
        lines += [
            "Gate            : PASS",
            "  No wrong verdicts, and the claims the pipeline declined to decide are exactly",
            "  the ones the suite file declares. It asserted nothing its fixtures deny.",
        ]
    else:
        lines.append("Gate            : FAIL")
        for problem in decision.problems:
            lines.append(f"  - {problem}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


def write_artifacts(run: SuiteRun, verdict: Gate | None = None) -> list[Path]:
    """Write ``summary.{json,csv,txt}`` into the run's output directory; return the paths.

    The per-task traces and result JSON are already written by
    :func:`~scientific_claim_verifier.scoring.verdict.verify_task`. Returns ``[]`` when
    the run had no output directory.
    """
    if run.out_dir is None:
        return []
    decision = verdict if verdict is not None else gate(run)
    run.out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for name, body in (
        (SUMMARY_JSON, json.dumps(suite_to_dict(run, decision), indent=2, sort_keys=True) + "\n"),
        (SUMMARY_CSV, summary_csv(run)),
        (SUMMARY_TXT, render_suite(run, decision) + "\n"),
    ):
        path = run.out_dir / name
        path.write_text(body, encoding="utf-8")
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------


def run_and_report(
    suite_path: str | Path = DEFAULT_SUITE,
    out_dir: str | Path | None = None,
    as_json: bool = False,
    use_declared_source: bool = True,
    execute: bool = True,
    abs_tol: float | None = None,
    rel_tol: float | None = None,
    tasks_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
    enforce_gate: bool = True,
    runner: ScriptRunner | None = None,
) -> int:
    """Load a suite, run it, write its artifacts, and report. Returns a process exit code.

    Exits ``1`` when the suite or one of its tasks cannot be loaded — including a schema
    error, which is reported rather than raised — or, unless ``enforce_gate`` is ``False``,
    when :func:`gate` says the run regressed. A suite full of ``contradicted`` claims exits
    ``0``: finding contradictions is the tool working.
    """
    try:
        suite = loader.load_suite(suite_path, tasks_dir)
    except LOAD_ERRORS as exc:
        print(f"error: could not load suite {suite_path}: {exc}", file=sys.stderr)
        return 1

    # `--out DIR` writes to DIR/<suite_id>/, so several suites can share one root.
    target = Path(out_dir) / suite.suite_id if out_dir is not None else None
    try:
        run = run_suite(
            suite,
            out_dir=target,
            use_declared_source=use_declared_source,
            execute=execute,
            abs_tol=abs_tol,
            rel_tol=rel_tol,
            repo_root=repo_root,
            runner=runner,
        )
    except LOAD_ERRORS as exc:
        print(f"error: could not run suite {suite.suite_id}: {exc}", file=sys.stderr)
        return 1

    decision = gate(run)
    written = write_artifacts(run, decision)

    if as_json:
        print(json.dumps(suite_to_dict(run, decision), indent=2, sort_keys=True))
    else:
        print(render_suite(run, decision))
    for path in written:
        print(f"wrote {path}", file=sys.stderr)

    return 0 if decision.ok or not enforce_gate else 1


def add_suite_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``run-suite`` flags. Shared by the CLI and ``scripts/05_run_smoke_suite.py``."""
    parser.add_argument(
        "--suite",
        metavar="PATH",
        default=DEFAULT_SUITE,
        help=f"Path to a suite YAML/JSON (default: {DEFAULT_SUITE}).",
    )
    parser.add_argument(
        "--out",
        metavar="DIR",
        default=None,
        help="Write traces, per-task results, and summary.{json,csv,txt} to DIR/<suite_id>/.",
    )
    parser.add_argument("--json", action="store_true", help="Print the suite result as JSON.")
    parser.add_argument(
        "--tasks-dir",
        metavar="DIR",
        default=None,
        help="Where to resolve task_ids (default: the suite file's own directory).",
    )
    parser.add_argument(
        "--no-declared-source",
        action="store_true",
        help="Ignore each task's claim.source_passage and link passages blind.",
    )
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="Do not run fixture scripts; reproduction is reported as not_attempted.",
    )
    parser.add_argument(
        "--no-gate",
        action="store_true",
        help="Report regressions but always exit 0 (the gate is on by default).",
    )
    parser.add_argument(
        "--abs-tol",
        type=float,
        default=None,
        metavar="F",
        help="Absolute tolerance, overriding each claim's reported precision.",
    )
    parser.add_argument(
        "--rel-tol",
        type=float,
        default=None,
        metavar="F",
        help="Relative tolerance, overriding each claim's reported precision.",
    )


def run_cli(argv: list[str]) -> int:
    """Parse ``run-suite`` arguments and run. Shared by the CLI and the script."""
    parser = argparse.ArgumentParser(
        prog="claimverifier run-suite",
        description="Run the offline smoke suite end to end and gate on regressions.",
    )
    add_suite_arguments(parser)
    args = parser.parse_args(argv)
    return run_and_report(
        args.suite,
        out_dir=args.out,
        as_json=args.json,
        tasks_dir=args.tasks_dir,
        use_declared_source=not args.no_declared_source,
        execute=not args.no_execute,
        enforce_gate=not args.no_gate,
        abs_tol=args.abs_tol,
        rel_tol=args.rel_tol,
    )


def main(argv: list[str] | None = None) -> int:
    return run_cli(argv if argv is not None else sys.argv[1:])


__all__ = [
    "DEFAULT_SUITE",
    "LOAD_ERRORS",
    "SUMMARY_JSON",
    "SUMMARY_CSV",
    "SUMMARY_TXT",
    "SUMMARY_CSV_COLUMNS",
    "MATCH",
    "CONSERVATIVE_MISS",
    "WRONG_VERDICT",
    "SuiteRecord",
    "SuiteRun",
    "Gate",
    "run_suite",
    "gate",
    "summary_row",
    "summary_csv",
    "suite_to_dict",
    "render_suite",
    "write_artifacts",
    "run_and_report",
    "add_suite_arguments",
    "run_cli",
    "main",
]
