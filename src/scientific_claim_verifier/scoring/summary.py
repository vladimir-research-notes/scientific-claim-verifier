"""Aggregating scored claims, and comparing them to a task's gold outcome.

Counts of support labels, reproduction statuses, and failure modes across a set of
tasks — plus agreement with the gold outcomes the task files carry. This is what the
smoke suite (M8) will report, and what makes the fixtures a benchmark rather than a
demo.

Two kinds of miss, and only one of them is a mistake
----------------------------------------------------
A single accuracy number over support labels hides the difference between a system
that says the wrong thing and one that declines to say anything, and for a
verification tool that difference is the whole point. So a mismatch is bucketed:

``conservative_misses``
    The pipeline predicted a **non-committal** label — ``unverifiable_from_artifacts``
    or ``not_checked`` — where the gold label commits. The system declined to decide.
    It asserted nothing false; it under-delivered.

``wrong_verdicts``
    The pipeline asserted a committal label the gold outcome disagrees with: a claim
    called ``supported`` that gold says is ``contradicted``, or ``underspecified``
    where gold says ``supported``. **These are the mistakes.** Over the committed
    fixtures this count is zero, and it is the number to watch when the extractor, the
    linker, or the checks change: a change that raises label accuracy by moving a
    conservative miss into a wrong verdict has made the tool worse.

The gold outcomes are hand-authored on seven small synthetic fixtures, so nothing here
is a benchmark result about scientific claim verification in general. It is a
regression harness for this pipeline. See ``docs/RESULTS.md``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..schemas import FailureMode, ReproductionStatus, SupportLabel

# Labels that decline to commit. Predicting one where gold commits is a conservative
# miss, not a wrong verdict.
NON_COMMITTAL = (SupportLabel.UNVERIFIABLE_FROM_ARTIFACTS, SupportLabel.NOT_CHECKED)


@dataclass(frozen=True)
class TaskOutcome:
    """One task's predicted verdict beside the gold verdict its file declares."""

    task_id: str
    claim_id: str
    predicted_support: SupportLabel
    predicted_reproduction: ReproductionStatus
    predicted_failure: FailureMode
    gold_support: SupportLabel
    gold_reproduction: ReproductionStatus
    gold_failure: FailureMode

    @property
    def support_matches(self) -> bool:
        return self.predicted_support is self.gold_support

    @property
    def reproduction_matches(self) -> bool:
        return self.predicted_reproduction is self.gold_reproduction

    @property
    def failure_matches(self) -> bool:
        return self.predicted_failure is self.gold_failure

    @property
    def is_conservative_miss(self) -> bool:
        """Predicted a non-committal label where the gold outcome commits."""
        return (
            not self.support_matches
            and self.predicted_support in NON_COMMITTAL
            and self.gold_support not in NON_COMMITTAL
        )

    @property
    def is_wrong_verdict(self) -> bool:
        """Asserted a committal label the gold outcome disagrees with."""
        return not self.support_matches and not self.is_conservative_miss

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "claim_id": self.claim_id,
            "predicted": {
                "support_label": self.predicted_support.value,
                "reproduction_status": self.predicted_reproduction.value,
                "failure_mode": self.predicted_failure.value,
            },
            "gold": {
                "support_label": self.gold_support.value,
                "reproduction_status": self.gold_reproduction.value,
                "failure_mode": self.gold_failure.value,
            },
            "support_matches": self.support_matches,
            "reproduction_matches": self.reproduction_matches,
            "failure_matches": self.failure_matches,
        }


@dataclass(frozen=True)
class SuiteSummary:
    """Counts and gold agreement over a set of scored tasks."""

    outcomes: tuple[TaskOutcome, ...]

    @property
    def n_tasks(self) -> int:
        return len(self.outcomes)

    def _counts(self, attribute: str) -> dict[str, int]:
        """Counts of one field's values, sorted by value for a stable record."""
        counter = Counter(getattr(o, attribute).value for o in self.outcomes)
        return dict(sorted(counter.items()))

    @property
    def support_counts(self) -> dict[str, int]:
        return self._counts("predicted_support")

    @property
    def reproduction_counts(self) -> dict[str, int]:
        return self._counts("predicted_reproduction")

    @property
    def failure_counts(self) -> dict[str, int]:
        return self._counts("predicted_failure")

    @property
    def support_agreement(self) -> int:
        return sum(1 for o in self.outcomes if o.support_matches)

    @property
    def reproduction_agreement(self) -> int:
        return sum(1 for o in self.outcomes if o.reproduction_matches)

    @property
    def failure_agreement(self) -> int:
        return sum(1 for o in self.outcomes if o.failure_matches)

    @property
    def conservative_misses(self) -> tuple[str, ...]:
        return tuple(o.task_id for o in self.outcomes if o.is_conservative_miss)

    @property
    def wrong_verdicts(self) -> tuple[str, ...]:
        return tuple(o.task_id for o in self.outcomes if o.is_wrong_verdict)


def summarize(outcomes: list[TaskOutcome]) -> SuiteSummary:
    """Aggregate scored tasks, preserving the order they were scored in."""
    return SuiteSummary(outcomes=tuple(outcomes))


def summary_to_dict(summary: SuiteSummary) -> dict:
    """Serialize an aggregate summary to a JSON-ready dict."""
    return {
        "n_tasks": summary.n_tasks,
        "support_counts": summary.support_counts,
        "reproduction_counts": summary.reproduction_counts,
        "failure_counts": summary.failure_counts,
        "gold_agreement": {
            "support_label": summary.support_agreement,
            "reproduction_status": summary.reproduction_agreement,
            "failure_mode": summary.failure_agreement,
        },
        "conservative_misses": list(summary.conservative_misses),
        "wrong_verdicts": list(summary.wrong_verdicts),
        "tasks": [o.to_dict() for o in summary.outcomes],
    }


def _counts_line(counts: dict[str, int]) -> str:
    return ", ".join(f"{n} {name}" for name, n in counts.items()) or "none"


def render_summary(summary: SuiteSummary) -> str:
    """Render the aggregate summary, with the two kinds of miss kept apart."""
    total = summary.n_tasks
    lines = [
        "scientific-claim-verifier — aggregate summary",
        "=" * 44,
        f"Tasks scored        : {total}",
        "",
        f"Support labels      : {_counts_line(summary.support_counts)}",
        f"Reproduction        : {_counts_line(summary.reproduction_counts)}",
        f"Failure modes       : {_counts_line(summary.failure_counts)}",
        "",
        "Agreement with the tasks' gold outcomes:",
        f"  support_label       : {summary.support_agreement}/{total}",
        f"  reproduction_status : {summary.reproduction_agreement}/{total}",
        f"  failure_mode        : {summary.failure_agreement}/{total}",
        "",
        f"Wrong verdicts      : {len(summary.wrong_verdicts)} "
        f"{list(summary.wrong_verdicts) or ''}".rstrip(),
        "  (a committal label the gold outcome disagrees with — these are the mistakes)",
        f"Conservative misses : {len(summary.conservative_misses)} "
        f"{list(summary.conservative_misses) or ''}".rstrip(),
        "  (declined to decide where gold commits — asserted nothing false)",
    ]
    for outcome in summary.outcomes:
        if outcome.support_matches:
            continue
        lines.append(
            f"  [{'MISS' if outcome.is_wrong_verdict else 'shy '}] {outcome.task_id}: "
            f"predicted {outcome.predicted_support.value}, gold {outcome.gold_support.value}"
        )
    return "\n".join(lines)


__all__ = [
    "NON_COMMITTAL",
    "TaskOutcome",
    "SuiteSummary",
    "summarize",
    "summary_to_dict",
    "render_summary",
]
