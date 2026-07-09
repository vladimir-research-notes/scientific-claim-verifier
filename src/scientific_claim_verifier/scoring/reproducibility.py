"""Assigning the reproduction status: did the underlying computation reproduce?

A *reproduction* re-derives a number from an artifact. Two check types do that:
``code_execution`` runs the script, and ``dataset_statistic`` recomputes the statistic
from the CSV. A claim with neither is ``not_applicable`` — reading a value out of a
table cell is a lookup, not a reproduction, and calling it one would inflate every
table claim in the suite into a reproduced result.

Reproduced vs. approximately reproduced
---------------------------------------
``reproduced`` means the recomputed number matched the claim **exactly** — a signed
difference of zero once rounded for recording. ``approximately_reproduced`` means it
landed inside the tolerance but not on the value. The distinction is worth keeping:
the checks derive their tolerance from the claim's own reported precision, so
"within tolerance" can mean a real gap that the claim's wording simply failed to
exclude. Both committed code fixtures and the dataset fixture reproduce exactly.

Execution failure is not numeric disagreement
---------------------------------------------
The four ``failed_*`` statuses are why ``code_execution`` judges *execution* and a
separate ``numeric_tolerance`` check judges *agreement*. A script that will not run
tells you nothing about the claim's number:

=========================  ====================================================
``failed_missing_code``    The script is absent, or its link resolves to nothing.
``failed_environment``     It timed out, exited non-zero, or the sandbox could not
                           enforce the policy it promised.
``failed_missing_data``    The dataset is absent or unusable.
``failed_numeric_mismatch``It ran, and produced the wrong number.
=========================  ====================================================

``failed_environment`` for a timeout is a deliberate coarsening: the vocabulary has no
``failed_timeout``, and the *failure mode* records ``execution_timeout`` alongside, so
nothing is lost.

Combining channels
------------------
A claim may exercise both channels. Each yields a status, and the **worst** wins, by
the fixed severity order in :data:`SEVERITY`: a script that reproduced does not excuse
a dataset that went missing. No committed fixture exercises both, so this rule is
pinned by unit tests rather than by a task.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..checks import ErrorKind
from ..schemas import CheckStatus, CheckType, ReproductionStatus, VerificationCheck
from . import Rule, error_kind

# Worst-wins ordering when a claim exercises more than one reproduction channel.
# `not_applicable` is absent: it means "no channel exists", never "a channel said so".
SEVERITY: tuple[ReproductionStatus, ...] = (
    ReproductionStatus.REPRODUCED,
    ReproductionStatus.APPROXIMATELY_REPRODUCED,
    ReproductionStatus.NOT_ATTEMPTED,
    ReproductionStatus.FAILED_NUMERIC_MISMATCH,
    ReproductionStatus.FAILED_MISSING_DATA,
    ReproductionStatus.FAILED_MISSING_CODE,
    ReproductionStatus.FAILED_ENVIRONMENT,
)

# How a check's structured `error_kind` becomes a reproduction status.
_CODE_ERRORS: dict[str, ReproductionStatus] = {
    ErrorKind.MISSING_CODE.value: ReproductionStatus.FAILED_MISSING_CODE,
    ErrorKind.DANGLING_LINK.value: ReproductionStatus.FAILED_MISSING_CODE,
    ErrorKind.EXECUTION_TIMEOUT.value: ReproductionStatus.FAILED_ENVIRONMENT,
    ErrorKind.NONZERO_EXIT.value: ReproductionStatus.FAILED_ENVIRONMENT,
    ErrorKind.SANDBOX_FAILURE.value: ReproductionStatus.FAILED_ENVIRONMENT,
}

_DATA_ERRORS: dict[str, ReproductionStatus] = {
    ErrorKind.MISSING_DATA.value: ReproductionStatus.FAILED_MISSING_DATA,
    ErrorKind.UNREADABLE_DATA.value: ReproductionStatus.FAILED_MISSING_DATA,
    ErrorKind.DANGLING_LINK.value: ReproductionStatus.FAILED_MISSING_DATA,
}


@dataclass(frozen=True)
class Channel:
    """One reproduction channel's verdict, with the checks that produced it."""

    name: str
    status: ReproductionStatus
    because: str
    check_ids: tuple[str, ...]


def worst(statuses: list[ReproductionStatus]) -> ReproductionStatus:
    """The most severe of ``statuses`` per :data:`SEVERITY`. Empty → ``not_applicable``."""
    if not statuses:
        return ReproductionStatus.NOT_APPLICABLE
    return max(statuses, key=SEVERITY.index)


def _exact(check: VerificationCheck) -> bool:
    """True when a passing numeric check landed exactly on the claimed value.

    A check that recorded no ``difference`` counts as inexact — the conservative
    direction, since ``approximately_reproduced`` claims less than ``reproduced``.
    """
    return check.difference == 0.0


def _of_type(checks: list[VerificationCheck], *types: CheckType) -> list[VerificationCheck]:
    return [c for c in checks if c.check_type in types]


def _ids(checks: list[VerificationCheck]) -> tuple[str, ...]:
    return tuple(c.check_id for c in checks)


def _gap(check: VerificationCheck) -> str:
    """How far a passing check landed from the claimed value, if it said."""
    if check.difference is None:
        return f"{check.check_id} recorded no difference"
    return f"{check.check_id} off by {check.difference:g}"


def _agreement(passing: list[VerificationCheck], channel: str) -> tuple[ReproductionStatus, str]:
    """Classify a set of passing numeric checks as an exact or an approximate match."""
    inexact = [c for c in passing if not _exact(c)]
    if inexact:
        gaps = ", ".join(_gap(c) for c in inexact)
        return (
            ReproductionStatus.APPROXIMATELY_REPRODUCED,
            f"the {channel} reproduced the claim within tolerance but not exactly ({gaps})",
        )
    return ReproductionStatus.REPRODUCED, f"the {channel} reproduced the claimed value exactly"


def _code_channel(checks: list[VerificationCheck]) -> Channel | None:
    """Classify the code-execution channel, or ``None`` if the claim has no script."""
    executions = _of_type(checks, CheckType.CODE_EXECUTION)
    if not executions:
        return None
    tolerance = _of_type(checks, CheckType.NUMERIC_TOLERANCE)
    ids = _ids(executions + tolerance)

    def channel(status: ReproductionStatus, because: str) -> Channel:
        return Channel("code_execution", status, because, ids)

    for execution in executions:
        if execution.status is CheckStatus.ERROR:
            kind = error_kind(execution) or ""
            status = _CODE_ERRORS.get(kind, ReproductionStatus.FAILED_ENVIRONMENT)
            return channel(status, f"the script did not run: {execution.notes}")
        if execution.status is CheckStatus.SKIPPED:
            return channel(
                ReproductionStatus.NOT_ATTEMPTED, f"the script was not run: {execution.notes}"
            )
        if execution.status is CheckStatus.FAIL:
            return channel(
                ReproductionStatus.FAILED_NUMERIC_MISMATCH,
                f"the script ran but did not produce the declared output: {execution.notes}",
            )

    # Every script ran and printed what the bundle declared. Whether the *number* it
    # printed matches the claim is the separate `numeric_tolerance` check's verdict.
    if any(c.status is CheckStatus.FAIL for c in tolerance):
        return channel(
            ReproductionStatus.FAILED_NUMERIC_MISMATCH,
            "the script ran but printed a value outside the claim's tolerance",
        )
    passing = [c for c in tolerance if c.status is CheckStatus.PASS]
    if passing:
        return channel(*_agreement(passing, "script"))
    if any(execution.inputs.get("declared_expectations") for execution in executions):
        return channel(
            ReproductionStatus.REPRODUCED, "the script reproduced the output the bundle declared"
        )
    return channel(
        ReproductionStatus.NOT_ATTEMPTED,
        "the script ran, but neither the bundle nor the claim declared anything to "
        "compare its output against",
    )


def _dataset_channel(checks: list[VerificationCheck]) -> Channel | None:
    """Classify the dataset-recomputation channel, or ``None`` if the claim has no dataset."""
    statistics = _of_type(checks, CheckType.DATASET_STATISTIC)
    if not statistics:
        return None
    ids = _ids(statistics)

    def channel(status: ReproductionStatus, because: str) -> Channel:
        return Channel("dataset_recomputation", status, because, ids)

    errored = [c for c in statistics if c.status is CheckStatus.ERROR]
    if errored:
        kind = error_kind(errored[0]) or ""
        status = _DATA_ERRORS.get(kind, ReproductionStatus.FAILED_MISSING_DATA)
        return channel(status, f"the statistic could not be recomputed: {errored[0].notes}")
    if any(c.status is CheckStatus.FAIL for c in statistics):
        return channel(
            ReproductionStatus.FAILED_NUMERIC_MISMATCH,
            "recomputing the statistic from the dataset gave a value outside the "
            "claim's tolerance",
        )
    passing = [c for c in statistics if c.status is CheckStatus.PASS]
    if not passing:
        return channel(
            ReproductionStatus.NOT_ATTEMPTED,
            "the dataset was linked but no statistic was recomputed against a claimed value",
        )
    return channel(*_agreement(passing, "recomputation"))


def channels(checks: list[VerificationCheck]) -> list[Channel]:
    """Every reproduction channel the claim exercises, in a fixed order."""
    found = (_code_channel(checks), _dataset_channel(checks))
    return [channel for channel in found if channel is not None]


def classify_reproduction(checks: list[VerificationCheck]) -> tuple[ReproductionStatus, Rule]:
    """Assign a reproduction status from the checks, and name the rule that assigned it."""
    exercised = channels(checks)
    if not exercised:
        return ReproductionStatus.NOT_APPLICABLE, Rule(
            "no_reproduction_channel",
            "the claim references no script to run and no dataset to recompute from, "
            "so nothing here re-derives a number",
        )

    status = worst([channel.status for channel in exercised])
    # The channel that produced the winning status is the one that explains it.
    decisive = next(channel for channel in exercised if channel.status is status)
    return status, Rule(decisive.name, decisive.because, decisive.check_ids)


__all__ = ["SEVERITY", "Channel", "worst", "channels", "classify_reproduction"]
