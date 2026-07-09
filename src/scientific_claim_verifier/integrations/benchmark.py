"""``scv.benchmark`` — the smoke suite as a benchmark a harness can score.

The consumer role: a benchmark harness that runs a suite of tasks, compares each result
to a gold outcome, and reports a number. The interesting part of this format is not the
records — it is :class:`ScoringProtocol`, which says **which number**.

A benchmark that ships records without declaring its metric is a spreadsheet, and the
metric a harness would reach for by default — label accuracy — is the wrong one here.
Over these fixtures the pipeline recovers 10 of 11 support labels. Its single miss is a
claim it *declined to decide*: a lexical evidence check cannot tell that a paraphrase
asserts a claim, so it returns ``inconclusive`` and scoring reports
``unverifiable_from_artifacts`` rather than guessing. A change that "fixed" that miss by
guessing would raise accuracy to 11/11 and make the tool worse.

So the declared primary metric is ``wrong_verdicts``, **lower is better**: the number of
tasks where the pipeline asserted a committal label the gold outcome disagrees with. Over
the committed fixtures it is zero. ``conservative_misses`` is secondary, also lower is
better, and the two are never summed. This is the same asymmetry
:func:`scientific_claim_verifier.suite.gate` enforces, and ``outcome`` is computed by the
same :class:`~scientific_claim_verifier.scoring.summary.TaskOutcome` code the gate reads —
not re-implemented here, so the export and the gate cannot come to different conclusions.

Sources
-------
Predicted verdicts, claim types, and check counts come from the **traces**. Gold outcomes,
the suite's identity, and the gate come from ``summary.json`` — a trace never carries
gold, because gold is never an input to the run that wrote it. The two sources are
cross-checked (:func:`~scientific_claim_verifier.integrations.run.check_agreement`) and a
directory whose traces and summary disagree is refused rather than scored.
"""

from __future__ import annotations

from pydantic import Field

from ..reports.reader import ReportInput
from ..schemas import CheckStatus
from ..scoring.summary import TaskOutcome
from ..suite import CONSERVATIVE_MISS, MATCH, WRONG_VERDICT
from .envelope import _Model
from .records import ExportContext, Verdict
from .run import (
    LoadedRun,
    check_agreement,
    load_run,
    require_gold,
    require_suite,
    run_dir_of,
    task_id_of,
)

#: The format this module writes, and the version of its contract.
FORMAT = "scv.benchmark"
VERSION = "1.0"

#: The consumer role this format is shaped for.
CONSUMER = "BioAgentBench"

#: How a record is scored: each field compared to gold by exact match, no partial credit.
PROTOCOL = "exact_match_per_field"

#: The three fields compared against gold.
SCORED_FIELDS = ("support_label", "reproduction_status", "failure_mode")

#: The number to watch, and the one not to. Both are counts of tasks; neither is a rate.
PRIMARY_METRIC = "wrong_verdicts"
SECONDARY_METRIC = "conservative_misses"
LOWER_IS_BETTER = "lower_is_better"

#: The bucket a task's support label falls into. Same vocabulary as ``suite.py``.
OUTCOMES = (MATCH, CONSERVATIVE_MISS, WRONG_VERDICT)

PROTOCOL_NOTES = (
    "wrong_verdicts is primary because declining to decide and deciding wrongly are not "
    "the same failure, and a single accuracy number cannot tell them apart. A wrong "
    "verdict is an assertion the task's own artifacts contradict; a conservative miss is "
    "a refusal to assert. Do not sum them, and do not rank a system by their total. "
    "See docs/SCORING.md and docs/RESULTS.md."
)


class SuiteInfo(_Model):
    """The suite these records came from."""

    suite_id: str = Field(min_length=1)
    name: str | None = None
    version: str | None = None
    n_tasks: int = Field(ge=0)
    scripts_executed: bool


class GateInfo(_Model):
    """The suite's own regression verdict on the run, verbatim.

    ``applicable`` is ``False`` for a run made with ``--no-execute``: the gold outcomes
    assume the fixture scripts ran, so a run that skipped them has nothing to be compared
    against, and any ``wrong_verdict`` it reports is the operator's flag rather than a
    regression. A harness that ignores this field will publish that mistake as a score.
    """

    ok: bool
    applicable: bool
    problems: list[str] = Field(default_factory=list)


class ScoringProtocol(_Model):
    """What "score" means for this benchmark. Declared, so a harness need not guess."""

    protocol: str = Field(min_length=1)
    fields: list[str] = Field(min_length=1)
    primary_metric: str = Field(min_length=1)
    primary_metric_direction: str = Field(min_length=1)
    secondary_metric: str = Field(min_length=1)
    secondary_metric_direction: str = Field(min_length=1)
    outcomes: list[str] = Field(min_length=1)
    notes: str = Field(min_length=1)


class Matches(_Model):
    """Field-by-field agreement with gold. No partial credit, no averaging."""

    support_label: bool
    reproduction_status: bool
    failure_mode: bool


class Record(_Model):
    """One task: what the pipeline said, what gold says, and which bucket that lands in."""

    task_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    family: str | None = None
    claim_type: str = Field(min_length=1)
    predicted: Verdict
    gold: Verdict
    matches: Matches
    outcome: str = Field(min_length=1)
    check_counts: dict[str, int] = Field(default_factory=dict)
    trace: str = Field(min_length=1)


class Payload(_Model):
    """The suite, its gate, its scoring protocol, and one record per task."""

    suite: SuiteInfo
    gate: GateInfo
    scoring: ScoringProtocol
    records: list[Record] = Field(default_factory=list)


def scoring_protocol() -> ScoringProtocol:
    """The declared metric. A benchmark that omits this is a table of numbers."""
    return ScoringProtocol(
        protocol=PROTOCOL,
        fields=list(SCORED_FIELDS),
        primary_metric=PRIMARY_METRIC,
        primary_metric_direction=LOWER_IS_BETTER,
        secondary_metric=SECONDARY_METRIC,
        secondary_metric_direction=LOWER_IS_BETTER,
        outcomes=list(OUTCOMES),
        notes=PROTOCOL_NOTES,
    )


def check_counts(report: ReportInput) -> dict[str, int]:
    """Per-status counts over one claim's checks, every status present (zeros included)."""
    checks = report.result.computed_checks
    return {
        status.value: sum(1 for check in checks if check.status is status)
        for status in CheckStatus
    }


def outcome_of(predicted: Verdict, gold: Verdict, task_id: str, claim_id: str) -> TaskOutcome:
    """Pair a predicted verdict with gold, using the suite's own comparison object."""
    return TaskOutcome(
        task_id=task_id,
        claim_id=claim_id,
        predicted_support=predicted.support_label,
        predicted_reproduction=predicted.reproduction_status,
        predicted_failure=predicted.failure_mode,
        gold_support=gold.support_label,
        gold_reproduction=gold.reproduction_status,
        gold_failure=gold.failure_mode,
    )


def bucket(outcome: TaskOutcome) -> str:
    """``match``, ``conservative_miss``, or ``wrong_verdict`` — as the suite gate decides."""
    if outcome.support_matches:
        return MATCH
    return CONSERVATIVE_MISS if outcome.is_conservative_miss else WRONG_VERDICT


def record_for(report: ReportInput, run: LoadedRun) -> Record:
    """One benchmark record, joining the trace's prediction to the summary's gold."""
    task_id = task_id_of(report)
    predicted = Verdict.of(report.result)
    gold = run.gold(task_id)
    if gold is None:  # pragma: no cover - require_gold ran first
        raise AssertionError(f"no gold outcome for {task_id!r}")

    outcome = outcome_of(predicted, gold, task_id, report.result.claim_id)
    return Record(
        task_id=task_id,
        claim_id=report.result.claim_id,
        family=run.family(task_id),
        claim_type=report.claim.claim_type.value,
        predicted=predicted,
        gold=gold,
        matches=Matches(
            support_label=outcome.support_matches,
            reproduction_status=outcome.reproduction_matches,
            failure_mode=outcome.failure_matches,
        ),
        outcome=bucket(outcome),
        check_counts=check_counts(report),
        trace=report.trace_path.name,
    )


def suite_info(run: LoadedRun) -> SuiteInfo:
    """The suite block, as ``run-suite`` recorded it."""
    suite = run.suite or {}
    return SuiteInfo(
        suite_id=str(suite["suite_id"]),
        name=suite.get("name"),
        version=suite.get("version"),
        n_tasks=int(suite.get("n_tasks", len(run.reports))),
        scripts_executed=bool(suite.get("scripts_executed", True)),
    )


def gate_info(run: LoadedRun) -> GateInfo:
    """The gate block, as ``run-suite`` recorded it."""
    gate = run.gate or {}
    return GateInfo(
        ok=bool(gate.get("ok", False)),
        applicable=bool(gate.get("applicable", True)),
        problems=[str(problem) for problem in gate.get("problems", ())],
    )


def build(ctx: ExportContext) -> Payload:
    """The suite run as a scoreable benchmark. Refuses a run with no gold and no gate."""
    run = load_run(run_dir_of(ctx))
    require_suite(run)
    require_gold(run)
    check_agreement(run)
    return Payload(
        suite=suite_info(run),
        gate=gate_info(run),
        scoring=scoring_protocol(),
        records=[record_for(report, run) for report in run.reports],
    )


__all__ = [
    "CONSUMER",
    "FORMAT",
    "LOWER_IS_BETTER",
    "OUTCOMES",
    "PRIMARY_METRIC",
    "PROTOCOL",
    "PROTOCOL_NOTES",
    "SCORED_FIELDS",
    "SECONDARY_METRIC",
    "VERSION",
    "GateInfo",
    "Matches",
    "Payload",
    "Record",
    "ScoringProtocol",
    "SuiteInfo",
    "bucket",
    "build",
    "check_counts",
    "gate_info",
    "outcome_of",
    "record_for",
    "scoring_protocol",
    "suite_info",
]
