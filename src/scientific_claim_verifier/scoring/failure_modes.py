"""Classifying *why* a claim did not come out cleanly supported and reproduced.

A support label says the claim is not backed. A failure mode says what to go and fix.
That is what makes an aggregate result diagnostic instead of a pass rate: eight
`contradicted` claims are one number, but "six table-cell mismatches and two
paraphrases the lexical checker could not read" is a work list.

Causes, then a winner
---------------------
:func:`causes` walks the checks and names **every** reason the claim is not clean —
each as a :class:`Cause` carrying the failure mode, the check that produced it, and
why. :func:`classify_failure` then picks one by :data:`MODE_PRIORITY`, and the rest
survive on the result as ``limitations``, because a claim that is both contradicted by
its table *and* undecidable from its text is not fully described by either fact.

The priority order runs from the most concrete refutation to the vaguest gap: a table
cell that disagrees outranks a passage whose polarity is off, which outranks a
recomputation that never ran, which outranks a checker that could not decide. Every
mode below `underspecified` is a statement about the **checker's reach**, not about
the paper.

``evidence_undecidable`` vs. ``passage_does_not_assert``
--------------------------------------------------------
These are the two the taxonomy most needed to separate, and the reason
``FailureMode.EVIDENCE_UNDECIDABLE`` was added to the schema in this milestone.
``CheckStatus.INCONCLUSIVE`` arrived with the checks (M5) and had no failure mode to
map onto; the nearest existing value, ``passage_does_not_assert``, asserts something
the pipeline does not know. ``synthetic_data_passage``'s passage *does* assert its
claim — a bag-of-words rule simply cannot see it. Recording
``passage_does_not_assert`` there would have published the checker's ignorance as a
fact about the paper. See ``docs/SCORING.md``.

Coarse mappings, named
----------------------
Two mappings lose information, and both are deliberate:

- ``comparison`` failing (the asserted *relation* does not hold) is recorded as
  ``numeric_out_of_tolerance``. The check does apply a tolerance threshold, so this
  is fair, but a dedicated ``relation_does_not_hold`` would be more precise.
- ``code_execution`` failing (the script ran, but stdout lacks the bundle's declared
  expectation) is recorded as ``other``. The declared expectation may be arbitrary
  text, so neither the numeric modes nor ``execution_error`` — the script executed
  fine — describes it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..checks import ErrorKind
from ..schemas import (
    CheckStatus,
    CheckType,
    FailureMode,
    ReproductionStatus,
    SupportLabel,
    VerificationCheck,
)
from . import CheckSignal, Rule, Signal, error_kind, signals

# Most concrete refutation first; the checker's own limits last. `none` is not here —
# it is the answer when there are no causes at all.
MODE_PRIORITY: tuple[FailureMode, ...] = (
    FailureMode.TABLE_CELL_MISMATCH,
    FailureMode.STATISTIC_MISMATCH,
    FailureMode.NUMERIC_OUT_OF_TOLERANCE,
    FailureMode.EXECUTION_TIMEOUT,
    FailureMode.EXECUTION_ERROR,
    FailureMode.MISSING_CODE,
    FailureMode.MISSING_DATA,
    FailureMode.UNDERSPECIFIED,
    FailureMode.PASSAGE_DOES_NOT_ASSERT,
    FailureMode.EVIDENCE_UNDECIDABLE,
    FailureMode.MISSING_EVIDENCE_LINK,
    FailureMode.OTHER,
)

# Which mode a *refuting* check implies, by the check that refuted.
_REFUTATION_MODES: dict[CheckType, FailureMode] = {
    CheckType.TABLE_VALUE: FailureMode.TABLE_CELL_MISMATCH,
    CheckType.DATASET_STATISTIC: FailureMode.STATISTIC_MISMATCH,
    CheckType.NUMERIC_TOLERANCE: FailureMode.NUMERIC_OUT_OF_TOLERANCE,
    CheckType.COMPARISON: FailureMode.NUMERIC_OUT_OF_TOLERANCE,
    CheckType.EVIDENCE_PRESENCE: FailureMode.PASSAGE_DOES_NOT_ASSERT,
    CheckType.CODE_EXECUTION: FailureMode.OTHER,
    CheckType.FIGURE_RECOMPUTE: FailureMode.OTHER,
}

# Which mode an *errored* check implies, by the structured cause it recorded.
_ERROR_MODES: dict[str, FailureMode] = {
    ErrorKind.DANGLING_LINK.value: FailureMode.MISSING_EVIDENCE_LINK,
    ErrorKind.MISSING_PASSAGE.value: FailureMode.MISSING_EVIDENCE_LINK,
    ErrorKind.MISSING_DATA.value: FailureMode.MISSING_DATA,
    ErrorKind.UNREADABLE_DATA.value: FailureMode.MISSING_DATA,
    ErrorKind.MISSING_CODE.value: FailureMode.MISSING_CODE,
    ErrorKind.SANDBOX_FAILURE.value: FailureMode.EXECUTION_ERROR,
    ErrorKind.NONZERO_EXIT.value: FailureMode.EXECUTION_ERROR,
    ErrorKind.EXECUTION_TIMEOUT.value: FailureMode.EXECUTION_TIMEOUT,
    ErrorKind.MISSING_COLUMN.value: FailureMode.OTHER,
    ErrorKind.MISSING_ROW.value: FailureMode.OTHER,
    ErrorKind.NON_NUMERIC_CELL.value: FailureMode.OTHER,
    ErrorKind.EMPTY_COLUMN.value: FailureMode.OTHER,
}

# Reproduction outcomes that mean the computation failed, as opposed to never applying.
FAILED_REPRODUCTION = (
    ReproductionStatus.FAILED_ENVIRONMENT,
    ReproductionStatus.FAILED_MISSING_DATA,
    ReproductionStatus.FAILED_MISSING_CODE,
    ReproductionStatus.FAILED_NUMERIC_MISMATCH,
)


@dataclass(frozen=True)
class Cause:
    """One named reason a claim is not cleanly supported, and the check that saw it."""

    mode: FailureMode
    check_id: str
    because: str

    def to_dict(self) -> dict:
        return {"failure_mode": self.mode.value, "check_id": self.check_id, "because": self.because}


def _cause_for(check: VerificationCheck, reduced: CheckSignal) -> Cause | None:
    """The cause one check contributes, or ``None`` when it contributes none."""
    if reduced.signal is Signal.REFUTES:
        mode = _REFUTATION_MODES.get(check.check_type, FailureMode.OTHER)
        return Cause(mode, check.check_id, reduced.because)
    if reduced.signal is Signal.AMBIGUOUS:
        return Cause(FailureMode.UNDERSPECIFIED, check.check_id, reduced.because)
    if reduced.signal is not Signal.UNDECIDED:
        return None

    if check.status is CheckStatus.ERROR:
        mode = _ERROR_MODES.get(error_kind(check) or "", FailureMode.OTHER)
        return Cause(mode, check.check_id, reduced.because)
    if check.check_type is CheckType.EVIDENCE_PRESENCE:
        if check.status is CheckStatus.INCONCLUSIVE:
            return Cause(FailureMode.EVIDENCE_UNDECIDABLE, check.check_id, reduced.because)
        if check.status is CheckStatus.FAIL:  # `absent`: the passage never mentions it
            return Cause(FailureMode.PASSAGE_DOES_NOT_ASSERT, check.check_id, reduced.because)
        if check.status is CheckStatus.SKIPPED:
            return Cause(FailureMode.MISSING_EVIDENCE_LINK, check.check_id, reduced.because)
    # A `skipped` value check compared against nothing — because the claim stated no
    # value, or the caller passed `--no-execute`. Neither is a *failure*: nothing was
    # attempted, so nothing broke. It reaches the result as a limitation instead, and
    # the reproduction status already records `not_attempted`.
    return None


def causes(checks: list[VerificationCheck]) -> list[Cause]:
    """Every reason this claim is not clean, in check order. Empty means it is."""
    reduced = signals(checks)
    found = (_cause_for(check, signal) for check, signal in zip(checks, reduced, strict=True))
    return [cause for cause in found if cause is not None]


def classify_failure(
    checks: list[VerificationCheck],
    support: SupportLabel,
    reproduction: ReproductionStatus,
) -> tuple[FailureMode, Rule]:
    """Assign the single failure mode that best explains a non-clean outcome.

    A ``supported`` claim whose computation also reproduced has no failure, even when
    individual checks were skipped for want of anything to compare.
    """
    if support is SupportLabel.SUPPORTED and reproduction not in FAILED_REPRODUCTION:
        return FailureMode.NONE, Rule(
            "clean",
            "the artifacts support the claim and nothing failed to reproduce",
            tuple(c.check_id for c in checks),
        )

    found = causes(checks)
    if not found:
        # Reachable and legitimate: `--no-execute`, or a claim that states no value for
        # a located artifact, leaves checks `skipped` and the label short of `supported`
        # without anything having failed. `limitations` says what went unchecked.
        return FailureMode.NONE, Rule(
            "no_failure_named",
            f"the label is {support.value}, but no check failed — some simply did not "
            "run or had nothing to compare against",
            tuple(c.check_id for c in checks),
        )

    winner = min(found, key=lambda cause: MODE_PRIORITY.index(cause.mode))
    others = [cause for cause in found if cause is not winner]
    because = winner.because
    if others:
        because += f" (also: {', '.join(cause.mode.value for cause in others)})"
    return winner.mode, Rule(
        f"cause:{winner.mode.value}", because, tuple(cause.check_id for cause in found)
    )


def limitations(checks: list[VerificationCheck]) -> list[str]:
    """What this verdict does **not** settle, stated plainly, in check order.

    Every entry is derived from a check that actually ran. A clean, fully supported
    code-reproduction claim still carries one — the sandbox is a reproducibility
    control, not an isolation boundary — because that is true of the verdict whether
    or not the verdict was favourable.
    """
    stated: list[str] = []
    for check, reduced in zip(checks, signals(checks), strict=True):
        if reduced.signal in (Signal.UNDECIDED, Signal.AMBIGUOUS):
            stated.append(f"{check.check_type.value}: {reduced.because}")
    if any(c.check_type is CheckType.CODE_EXECUTION for c in checks):
        stated.append(
            "code_execution: the script ran under a recorded policy in a temp directory, "
            "which is controlled fixture execution and not a security boundary "
            "(docs/SANDBOX.md)"
        )
    return stated


__all__ = [
    "MODE_PRIORITY",
    "FAILED_REPRODUCTION",
    "Cause",
    "causes",
    "classify_failure",
    "limitations",
]
