"""One run directory, read once: its traces, its aggregate, and its gold outcomes.

Four of the five export formats are functions of a completed run, and Milestone 9
established what "a function of a run" is allowed to mean: the traces are the record, and
a report re-runs nothing. The exports inherit that. :func:`load_run` reads
``<task_id>.trace.jsonl`` through :mod:`scientific_claim_verifier.reports.reader`, which
re-validates every object against the schema on the way in, and reads the run's
``summary.json`` if there is one.

Where each fact comes from, and why
-----------------------------------
============================  ==========================================================
predicted verdict, checks     the **trace** — the artifact that recorded the run
gold verdict                  ``summary.json`` — a trace never carries gold, because gold
                              is never an input to the pipeline that wrote it
suite id, gate, family        ``summary.json`` — facts about the *suite*, not the claim
============================  ==========================================================

So an export that states a gold outcome needs a ``summary.json``, and one that does not
(``evidence-records``) needs only traces. :func:`require_gold` and :func:`require_suite`
say so out loud, with the command that would produce what is missing, rather than
emitting a document with an empty column.

Disagreement is an error, not a tie-break
-----------------------------------------
The predicted verdict exists in two places — in each trace, and again in the summary the
same run wrote. :func:`check_agreement` compares them and raises when they differ.
A run directory whose summary and traces disagree has been assembled from two different
runs, and any number computed from it is a fiction. The alternative — silently preferring
one source — is how a benchmark starts reporting a score nobody produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..reports.reader import (
    ReportError,
    ReportInput,
    discover_traces,
    order_of,
    read_report,
    read_summary,
)
from .envelope import IntegrationError
from .records import ExportContext, Verdict

#: The command that produces a run directory with everything every format needs.
SUITE_COMMAND = "claimverifier run-suite --out results/runs/"


def task_id_of(report: ReportInput) -> str:
    """A report's task id, falling back to its run id (they coincide for suite runs)."""
    return report.task_id or report.run_id


def run_dir_of(ctx: ExportContext) -> Path:
    """The run directory a run-based format needs. Raises if the caller supplied none.

    The registry declares which formats need one and the CLI refuses the request before it
    gets here, so this raises only for a programmatic caller that built its own context.
    """
    if ctx.run_dir is None:
        raise IntegrationError("this format needs a run directory (--run DIR)")
    return ctx.run_dir


@dataclass(frozen=True)
class LoadedRun:
    """Every trace in a run directory, in suite order, plus the aggregate beside them."""

    run_dir: Path
    reports: tuple[ReportInput, ...]
    summary: dict[str, Any] | None = None

    @property
    def run_name(self) -> str:
        """The run directory's own name (e.g. ``smoke_suite``). Never an absolute path."""
        return self.run_dir.name

    @property
    def suite(self) -> dict[str, Any] | None:
        """The ``suite`` block a ``run-suite`` aggregate carries, or ``None``."""
        return self._block("suite")

    @property
    def gate(self) -> dict[str, Any] | None:
        """The ``gate`` block a ``run-suite`` aggregate carries, or ``None``."""
        return self._block("gate")

    def _block(self, key: str) -> dict[str, Any] | None:
        block = (self.summary or {}).get(key)
        return block if isinstance(block, dict) else None

    @property
    def _outcomes(self) -> dict[str, dict[str, Any]]:
        """Per-task outcome records carrying gold, from either summary shape.

        ``run-suite`` nests the Milestone 7 aggregate under ``summary``; a multi-task
        ``verify --out`` writes that aggregate at the top level. Both carry ``gold``.
        """
        summary = self.summary or {}
        node = summary.get("summary") if isinstance(summary.get("summary"), dict) else summary
        tasks = node.get("tasks") if isinstance(node, dict) else None
        if not isinstance(tasks, list):
            return {}
        return {
            str(task["task_id"]): task
            for task in tasks
            if isinstance(task, dict) and "task_id" in task and "gold" in task
        }

    @property
    def _metadata(self) -> dict[str, dict[str, Any]]:
        """Per-task suite metadata (family, claim type, trace name). Suite runs only."""
        tasks = (self.summary or {}).get("tasks")
        if not isinstance(tasks, list) or self.suite is None:
            return {}
        return {
            str(task["task_id"]): task
            for task in tasks
            if isinstance(task, dict) and "task_id" in task
        }

    @property
    def has_gold(self) -> bool:
        return bool(self._outcomes)

    def gold(self, task_id: str) -> Verdict | None:
        """The task's gold verdict, as its task file declares it."""
        outcome = self._outcomes.get(task_id)
        return Verdict.model_validate(outcome["gold"]) if outcome else None

    def predicted(self, task_id: str) -> Verdict | None:
        """The verdict the *summary* recorded — to be compared against the trace's."""
        outcome = self._outcomes.get(task_id)
        return Verdict.model_validate(outcome["predicted"]) if outcome else None

    def family(self, task_id: str) -> str | None:
        """The task's human-facing family label (``numeric_table``, ``code_reproduction``)."""
        meta = self._metadata.get(task_id)
        family = meta.get("family") if meta else None
        return str(family) if isinstance(family, str) else None


def load_run(run_dir: str | Path) -> LoadedRun:
    """Read every scoring trace under ``run_dir``, in suite order, with its aggregate.

    Raises :class:`IntegrationError` if the directory does not exist, holds no trace, or
    holds one that will not validate. A malformed trace is a fact about the file, so the
    file is named.
    """
    target = Path(run_dir)
    if not target.is_dir():
        raise IntegrationError(f"{target}: no such run directory")

    traces = discover_traces(target)
    if not traces:
        raise IntegrationError(
            f"{target}: no *.trace.jsonl to export. Produce a run with `{SUITE_COMMAND}`"
        )
    try:
        reports = [read_report(trace) for trace in traces]
    except ReportError as exc:
        raise IntegrationError(str(exc)) from exc

    summary = read_summary(target)
    declared = order_of(target, summary)
    rank = {run_id: index for index, run_id in enumerate(declared)}
    reports.sort(key=lambda report: (rank.get(report.run_id, len(rank)), report.run_id))
    return LoadedRun(run_dir=target, reports=tuple(reports), summary=summary)


def require_gold(run: LoadedRun) -> None:
    """Raise unless the run carries the gold outcomes its tasks declare."""
    if not run.has_gold:
        raise IntegrationError(
            f"{run.run_dir}: this format states each task's gold outcome, and no "
            f"summary.json beside these traces carries one. A trace never records gold — "
            f"gold is never an input to the run. Produce one with `{SUITE_COMMAND}`"
        )


def require_suite(run: LoadedRun) -> None:
    """Raise unless the run was produced by ``run-suite`` (so it has a suite and a gate)."""
    if run.suite is None or run.gate is None:
        raise IntegrationError(
            f"{run.run_dir}: this format describes a *suite* run — its id, its gate, and "
            f"whether its fixture scripts were executed — and no summary.json beside these "
            f"traces declares one. Produce one with `{SUITE_COMMAND}`"
        )


def check_agreement(run: LoadedRun) -> None:
    """Raise if a trace and the run's own summary disagree about a predicted verdict."""
    for report in run.reports:
        task_id = task_id_of(report)
        recorded = run.predicted(task_id)
        if recorded is None:
            continue
        computed = Verdict.of(report.result)
        if recorded.triple != computed.triple:
            raise IntegrationError(
                f"{run.run_dir}: summary.json and {report.trace_path.name} disagree about "
                f"{task_id!r} — the summary says "
                f"{'/'.join(v.value for v in recorded.triple)}, the trace says "
                f"{'/'.join(v.value for v in computed.triple)}. This directory holds "
                "artifacts from more than one run; re-run the suite"
            )


__all__ = [
    "SUITE_COMMAND",
    "LoadedRun",
    "check_agreement",
    "load_run",
    "require_gold",
    "require_suite",
    "run_dir_of",
    "task_id_of",
]
