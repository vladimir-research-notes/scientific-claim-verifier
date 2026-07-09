"""``scv.metrics`` — one run as scalar metrics and labels, for regression comparison.

The consumer role: an observability or LLM-regression sink that stores a run's numbers
under a set of labels and, later, diffs two runs. The only property such a sink actually
needs from a producer is the one producers usually get wrong: **a fixed key space**.

Why every metric is always emitted
----------------------------------
A run in which no claim is ``contradicted`` could plausibly omit ``support_contradicted``.
Then a diff of that run against one where two claims are contradicted shows a key
*appearing*, and a tool that treats a missing key as "no data" reports nothing while a
tool that treats it as zero reports a regression. Both are guessing.

So :data:`METRIC_NAMES` is a module constant covering **every value of every closed
vocabulary** — all 6 support labels, all 8 reproduction statuses, all 13 failure modes —
and :func:`build` emits every one of them, zero-valued when unseen. The key space changes
only when :data:`VERSION` changes. A test enumerates the enums and fails if a vocabulary
grows without this format saying so.

``direction`` is the other half of the contract. A regression tool cannot know that more
``checks_fail`` is fine (a suite of contradicted claims *should* produce failing checks)
while more ``wrong_verdicts`` is not. Most counts are therefore ``neutral``, and only the
six metrics that have a good direction declare one. :func:`compare` is the reference
implementation of the diff this format exists for, and it refuses two documents whose key
sets differ rather than silently intersecting them.

The labels are fixed for the same reason as the metrics, which is why this format
describes a **suite** run and refuses anything else: ``suite_id``, ``suite_version``, and
``scripts_executed`` come from a ``run-suite`` aggregate, and a document that sometimes
carries them and sometimes does not is a document a sink cannot group by.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field

from ..schemas import CheckStatus, FailureMode, ReproductionStatus, SupportLabel
from .benchmark import outcome_of
from .envelope import Envelope, IntegrationError, _Model
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
FORMAT = "scv.metrics"
VERSION = "1.0"

#: The consumer role this format is shaped for.
CONSUMER = "LLM regression / observability"

#: Which way is better. Most counts have no direction, and saying so is the honest answer.
LOWER_IS_BETTER = "lower_is_better"
HIGHER_IS_BETTER = "higher_is_better"
NEUTRAL = "neutral"

#: Units. ``ratio`` is the only non-count, and it is not a probability.
TASKS = "tasks"
CHECKS = "checks"
RATIO = "ratio"

#: Prefixes under which a closed vocabulary is counted out, one metric per value.
SUPPORT_PREFIX = "support_"
REPRODUCTION_PREFIX = "reproduction_"
FAILURE_PREFIX = "failure_"


def _vocabulary_specs() -> tuple[tuple[str, str, str], ...]:
    """One ``(name, unit, direction)`` per value of each closed vocabulary, in enum order."""
    return (
        *((f"{SUPPORT_PREFIX}{v.value}", TASKS, NEUTRAL) for v in SupportLabel),
        *((f"{REPRODUCTION_PREFIX}{v.value}", TASKS, NEUTRAL) for v in ReproductionStatus),
        *((f"{FAILURE_PREFIX}{v.value}", TASKS, NEUTRAL) for v in FailureMode),
    )


#: Every metric this format emits, in emission order: ``(name, unit, direction)``.
#: The key space is fixed by this tuple, not by what a particular run happened to contain.
METRIC_SPECS: tuple[tuple[str, str, str], ...] = (
    ("tasks", TASKS, NEUTRAL),
    ("checks_total", CHECKS, NEUTRAL),
    ("checks_pass", CHECKS, NEUTRAL),
    ("checks_fail", CHECKS, NEUTRAL),
    ("checks_inconclusive", CHECKS, NEUTRAL),
    ("checks_error", CHECKS, LOWER_IS_BETTER),
    ("checks_skipped", CHECKS, NEUTRAL),
    ("mean_confidence", RATIO, NEUTRAL),
    *_vocabulary_specs(),
    ("gold_support_agreement", TASKS, HIGHER_IS_BETTER),
    ("gold_reproduction_agreement", TASKS, HIGHER_IS_BETTER),
    ("gold_failure_agreement", TASKS, HIGHER_IS_BETTER),
    ("wrong_verdicts", TASKS, LOWER_IS_BETTER),
    ("conservative_misses", TASKS, LOWER_IS_BETTER),
)

#: The names of every metric, in emission order. A consumer may pin this list.
METRIC_NAMES: tuple[str, ...] = tuple(name for name, _unit, _direction in METRIC_SPECS)


class Metric(_Model):
    """One scalar. ``direction`` says which way is a regression, or that nothing is."""

    name: str = Field(min_length=1)
    value: float
    unit: str = Field(min_length=1)
    direction: str = Field(min_length=1)


class Payload(_Model):
    """Labels that identify the run, and the fixed set of metrics measured over it."""

    labels: dict[str, str] = Field(default_factory=dict)
    metrics: list[Metric] = Field(default_factory=list)


@dataclass(frozen=True)
class MetricDelta:
    """One metric's movement between two runs, and whether that movement is bad."""

    name: str
    baseline: float
    candidate: float
    direction: str

    @property
    def delta(self) -> float:
        return self.candidate - self.baseline

    @property
    def changed(self) -> bool:
        return self.candidate != self.baseline

    @property
    def regression(self) -> bool:
        """True only when a metric with a declared direction moved the wrong way."""
        if self.direction == LOWER_IS_BETTER:
            return self.candidate > self.baseline
        if self.direction == HIGHER_IS_BETTER:
            return self.candidate < self.baseline
        return False

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "delta": self.delta,
            "direction": self.direction,
            "regression": self.regression,
        }


#: The labels every document carries, in every run. Fixed, like :data:`METRIC_NAMES`.
LABEL_NAMES = (
    "run",
    "scripts_executed",
    "suite_id",
    "suite_version",
    "trace_schema_version",
)


def labels_for(run: LoadedRun) -> dict[str, str]:
    """The labels that identify a run. All strings, and always the same keys."""
    suite = run.suite or {}
    return {
        "run": run.run_name,
        "scripts_executed": "true" if suite.get("scripts_executed", True) else "false",
        "suite_id": str(suite.get("suite_id", "")),
        "suite_version": str(suite.get("version") or ""),
        "trace_schema_version": run.reports[0].schema_version,
    }


def values_for(run: LoadedRun) -> dict[str, float]:
    """Every metric's value, zero where the run saw nothing. Keys are :data:`METRIC_NAMES`.

    The two miss counts are read off
    :class:`~scientific_claim_verifier.scoring.summary.TaskOutcome`, the same object the
    suite gate reads, so this document and the gate can never disagree about which kind of
    miss a task is.
    """
    values: dict[str, float] = dict.fromkeys(METRIC_NAMES, 0.0)
    values["tasks"] = float(len(run.reports))

    confidences: list[float] = []
    for report in run.reports:
        result = report.result
        confidences.append(result.confidence or 0.0)
        values[f"{SUPPORT_PREFIX}{result.support_label.value}"] += 1
        values[f"{REPRODUCTION_PREFIX}{result.reproduction_status.value}"] += 1
        values[f"{FAILURE_PREFIX}{result.failure_mode.value}"] += 1

        for check in result.computed_checks:
            values["checks_total"] += 1
            values[f"checks_{check.status.value}"] += 1

        task_id = task_id_of(report)
        gold = run.gold(task_id)
        if gold is None:  # pragma: no cover - require_gold ran first
            continue
        outcome = outcome_of(Verdict.of(result), gold, task_id, result.claim_id)
        values["gold_support_agreement"] += int(outcome.support_matches)
        values["gold_reproduction_agreement"] += int(outcome.reproduction_matches)
        values["gold_failure_agreement"] += int(outcome.failure_matches)
        values["conservative_misses"] += int(outcome.is_conservative_miss)
        values["wrong_verdicts"] += int(outcome.is_wrong_verdict)

    values["mean_confidence"] = (
        round(sum(confidences) / len(confidences), 6) if confidences else 0.0
    )
    # A status enum value that is not one of the six `checks_*` metrics would be dropped
    # silently, so the vocabulary is pinned here rather than trusted.
    unknown = sorted({f"checks_{s.value}" for s in CheckStatus} - set(METRIC_NAMES))
    if unknown:  # pragma: no cover - a test enumerates CheckStatus to keep this empty
        raise IntegrationError(f"{FORMAT}: check statuses with no metric: {unknown}")
    return values


def build(ctx: ExportContext) -> Payload:
    """One suite run's metrics.

    Needs gold, because agreement is half of what a regression is, and needs a suite,
    because the labels that identify the run come from its aggregate.
    """
    run = load_run(run_dir_of(ctx))
    require_gold(run)
    require_suite(run)
    check_agreement(run)
    values = values_for(run)
    return Payload(
        labels=labels_for(run),
        metrics=[
            Metric(name=name, value=values[name], unit=unit, direction=direction)
            for name, unit, direction in METRIC_SPECS
        ],
    )


def payload_of(envelope: Envelope) -> Payload:
    """Validate an envelope's payload as this format's. Raises :class:`IntegrationError`."""
    if envelope.format != FORMAT:
        raise IntegrationError(f"expected {FORMAT}, got {envelope.format!r}")
    return Payload.model_validate(envelope.payload)


def compare(baseline: Payload, candidate: Payload) -> tuple[MetricDelta, ...]:
    """Diff two metric documents, in emission order. The reference regression comparison.

    Raises :class:`IntegrationError` when the two key spaces differ. Two documents of the
    same ``format_version`` cannot disagree about which metrics exist — that is the whole
    promise — so a difference means one of them was not written by this contract, and
    quietly intersecting the keys would hide exactly the change worth seeing.
    """
    left = {metric.name: metric for metric in baseline.metrics}
    right = {metric.name: metric for metric in candidate.metrics}
    if set(left) != set(right):
        missing = sorted(set(left) - set(right))
        added = sorted(set(right) - set(left))
        raise IntegrationError(
            f"{FORMAT}: the two documents measure different metrics "
            f"(missing from candidate: {missing}; added: {added}). Within one "
            "format_version the key space is fixed"
        )
    return tuple(
        MetricDelta(
            name=name,
            baseline=left[name].value,
            candidate=right[name].value,
            direction=left[name].direction,
        )
        for name in (m.name for m in baseline.metrics)
    )


def regressions(deltas: tuple[MetricDelta, ...]) -> tuple[MetricDelta, ...]:
    """The deltas that moved a directional metric the wrong way."""
    return tuple(delta for delta in deltas if delta.regression)


__all__ = [
    "CHECKS",
    "CONSUMER",
    "LABEL_NAMES",
    "FAILURE_PREFIX",
    "FORMAT",
    "HIGHER_IS_BETTER",
    "LOWER_IS_BETTER",
    "METRIC_NAMES",
    "METRIC_SPECS",
    "NEUTRAL",
    "RATIO",
    "REPRODUCTION_PREFIX",
    "SUPPORT_PREFIX",
    "TASKS",
    "VERSION",
    "Metric",
    "MetricDelta",
    "Payload",
    "build",
    "compare",
    "labels_for",
    "payload_of",
    "regressions",
    "values_for",
]
