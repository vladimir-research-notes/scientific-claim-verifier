"""Statistic recomputation over a committed CSV, and the numeric-agreement record.

Two checks live here.

``dataset_statistic`` — recompute the statistic a claim asserts (``mean``,
``count``, …) directly from the dataset column the linker located
(``column=value``), and compare it to the claimed value within the claim's own
reported precision. The CSV is re-read from disk: the declared ``columns`` /
``n_rows`` shape hints in the task file are checked by fixture validation
(Milestone 2), never trusted here.

``numeric_tolerance`` — a standalone record of *"the number the artifacts produced
vs. the number the claim asserts"*. It exists because the code-execution channel
has two genuinely different ways to go wrong, and the schema must tell them apart:
a script that will not run (``failed_environment`` / ``execution_error``) is not a
script that runs and prints the wrong number (``failed_numeric_mismatch``). So
``code_execution`` judges *execution*, and this check judges *agreement*. The table
and dataset channels need no such split — reading a cell either works or errors —
so they judge agreement themselves.

Statistics
----------
Only the transparent, stdlib-computable ones, and both standard deviations are
named explicitly rather than hiding a ``ddof`` convention: ``std`` is the
population deviation (``ddof=0``, numpy's default) and ``std_sample`` the sample
deviation (``ddof=1``, pandas' default). ``correlation`` is **not** implemented —
it needs a two-column locator, which the locator grammar does not yet express and
no fixture exercises. See ``docs/CHECKS.md``.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable, Sequence
from pathlib import Path

from ..artifacts import loader
from ..evidence import locators
from ..schemas import (
    CheckStatus,
    CheckType,
    DatasetArtifact,
    EvidenceLink,
    ScientificClaim,
    VerificationCheck,
)
from . import ErrorKind, Tolerance, compare, resolve_tolerance, stable

# The statistics a claim may name, computed with the stdlib only.
STATISTICS: dict[str, Callable[[Sequence[float]], float]] = {
    "count": lambda values: float(len(values)),
    "sum": lambda values: float(sum(values)),
    "mean": statistics.fmean,
    "median": statistics.median,
    "std": statistics.pstdev,
    "std_sample": statistics.stdev,
    "min": min,
    "max": max,
}

# Statistics whose value is a whole number, compared exactly.
EXACT_STATISTICS = frozenset({"count"})

# Statistics needing at least this many values to be defined.
_MIN_VALUES: dict[str, int] = {
    "mean": 1,
    "median": 1,
    "std": 1,
    "std_sample": 2,
    "min": 1,
    "max": 1,
}

# A sample-count condition as the extractor writes it: ``"n = 12"``.
_COUNT_CONDITION_RE = re.compile(r"^\s*n\s*=\s*(\d+)\s*$", re.IGNORECASE)


def primary_statistic(claim: ScientificClaim) -> str | None:
    """The statistic the claim's headline number refers to, or ``None``.

    The first metric that names a statistic, preferring a real statistic over
    ``count`` — ``"12 samples with a mean value of 3.4"`` extracts both, but ``3.4``
    is the mean, and the count is a stated condition (see :func:`count_condition`).
    """
    for metric in claim.metrics:
        if metric in STATISTICS and metric not in EXACT_STATISTICS:
            return metric
    return next((m for m in claim.metrics if m in STATISTICS), None)


def count_condition(claim: ScientificClaim) -> int | None:
    """The sample count the claim states as a condition (``"n = 12"`` → 12)."""
    for condition in claim.conditions:
        match = _COUNT_CONDITION_RE.match(condition)
        if match:
            return int(match.group(1))
    return None


def compute_statistic(name: str, values: Sequence[float]) -> float:
    """Compute a named statistic. Raises ``KeyError``/``ValueError`` if it cannot."""
    if name not in STATISTICS:
        raise KeyError(f"unknown statistic: {name!r}")
    if len(values) < _MIN_VALUES.get(name, 0):
        raise ValueError(f"{name} needs at least {_MIN_VALUES[name]} value(s), got {len(values)}")
    return float(STATISTICS[name](values))


def read_numeric_column(path: Path, column: str) -> list[float]:
    """Read ``column`` from a CSV and convert every cell to ``float``.

    Raises :class:`~scientific_claim_verifier.artifacts.loader.TaskLoadError` if the
    column is missing, and ``ValueError`` if any cell is not a number — a statistic
    over silently-dropped rows would be a statistic over a different dataset.
    """
    cells = loader.read_csv_column(path, column)
    values: list[float] = []
    for row, cell in enumerate(cells, start=1):
        try:
            values.append(float(cell))
        except ValueError as exc:
            raise ValueError(f"row {row} of column {column!r} is not numeric: {cell!r}") from exc
    return values


def _check(
    check_id: str,
    claim: ScientificClaim,
    check_type: CheckType,
    status: CheckStatus,
    evidence: list[EvidenceLink],
    inputs: dict,
    notes: str,
    **fields: object,
) -> VerificationCheck:
    return VerificationCheck(
        check_id=check_id,
        check_type=check_type,
        claim_id=claim.claim_id,
        status=status,
        inputs=inputs,
        evidence=evidence,
        notes=notes,
        **fields,  # type: ignore[arg-type]
    )


def dataset_statistic_check(
    check_id: str,
    claim: ScientificClaim,
    dataset: DatasetArtifact,
    link: EvidenceLink,
    statistic: str,
    expected: float | None,
    repo_root: Path,
    override: Tolerance | None = None,
) -> VerificationCheck:
    """Recompute ``statistic`` over the located dataset column and compare to ``expected``."""
    locator = locators.parse(link.locator)
    inputs: dict = {
        "dataset_id": dataset.artifact_id,
        "locator": link.locator,
        "statistic": statistic,
        "path": dataset.path,
        "content_hash": dataset.content_hash,
    }
    if statistic in ("std", "std_sample"):
        inputs["definition"] = "population (ddof=0)" if statistic == "std" else "sample (ddof=1)"

    def fail(status: CheckStatus, notes: str) -> VerificationCheck:
        return _check(
            check_id, claim, CheckType.DATASET_STATISTIC, status, [link], inputs, notes
        )

    def errored(kind: ErrorKind, notes: str) -> VerificationCheck:
        inputs["error_kind"] = kind.value
        return fail(CheckStatus.ERROR, notes)

    if locator.column is None:
        # The linker declined to name a measured column (several candidates, none
        # named by the claim). That is underspecification, not an error.
        return fail(
            CheckStatus.SKIPPED, "dataset linked without a column locator; nothing to recompute"
        )
    if dataset.path is None:
        return errored(
            ErrorKind.MISSING_DATA, f"dataset {dataset.artifact_id!r} declares no file path"
        )

    try:
        path = loader.resolve_fixture_path(dataset.path, repo_root)
    except loader.TaskLoadError as exc:
        return errored(ErrorKind.MISSING_DATA, str(exc))
    if not path.is_file():
        return errored(ErrorKind.MISSING_DATA, f"dataset file not found: {dataset.path}")

    try:
        values = read_numeric_column(path, locator.column)
        computed = compute_statistic(statistic, values)
    except (loader.TaskLoadError, KeyError, ValueError) as exc:
        return errored(ErrorKind.UNREADABLE_DATA, f"cannot compute {statistic}: {exc}")

    inputs["column"] = locator.column
    inputs["n_values"] = len(values)

    if expected is None:
        return _check(
            check_id,
            claim,
            CheckType.DATASET_STATISTIC,
            CheckStatus.SKIPPED,
            [link],
            inputs,
            f"{statistic}({locator.column}) = {stable(computed):g}; "
            "the claim states no value to compare it against",
            computed_value=stable(computed),
        )

    tolerance = resolve_tolerance(
        claim, expected, override=override, exact=statistic in EXACT_STATISTICS
    )
    result = compare(computed, expected, tolerance)
    return _check(
        check_id,
        claim,
        CheckType.DATASET_STATISTIC,
        CheckStatus.PASS if result.within else CheckStatus.FAIL,
        [link],
        inputs,
        f"{statistic}({locator.column}) over {len(values)} values = {result.computed:g}; "
        f"claim states {result.expected:g}; |difference| = {abs(result.difference):g} "
        f"{'<=' if result.within else '>'} tolerance {result.threshold:g}",
        computed_value=result.computed,
        expected_value=result.expected,
        tolerance=result.threshold,
        difference=result.difference,
    )


def numeric_tolerance_check(
    check_id: str,
    claim: ScientificClaim,
    computed: float | None,
    source: str,
    evidence: list[EvidenceLink],
    override: Tolerance | None = None,
) -> VerificationCheck:
    """Compare a value the artifacts produced against the claim's ``expected_value``.

    ``source`` names where ``computed`` came from (e.g. ``"stdout: accuracy=0.80"``)
    so the record stands on its own in a report. ``computed=None`` — nothing was
    produced — is ``skipped``, not ``fail``: no number disagreed, because no number
    exists.
    """
    inputs: dict = {"source": source}
    expected = claim.expected_value

    if expected is None:
        return _check(
            check_id,
            claim,
            CheckType.NUMERIC_TOLERANCE,
            CheckStatus.SKIPPED,
            evidence,
            inputs,
            "the claim states no numeric value to compare",
            computed_value=None if computed is None else stable(computed),
        )
    if computed is None:
        return _check(
            check_id,
            claim,
            CheckType.NUMERIC_TOLERANCE,
            CheckStatus.SKIPPED,
            evidence,
            inputs,
            f"no numeric value could be read from {source}",
            expected_value=stable(expected),
        )

    result = compare(computed, expected, resolve_tolerance(claim, expected, override=override))
    return _check(
        check_id,
        claim,
        CheckType.NUMERIC_TOLERANCE,
        CheckStatus.PASS if result.within else CheckStatus.FAIL,
        evidence,
        inputs,
        f"{source} gives {result.computed:g}; claim states {result.expected:g}; "
        f"|difference| = {abs(result.difference):g} "
        f"{'<=' if result.within else '>'} tolerance {result.threshold:g}",
        computed_value=result.computed,
        expected_value=result.expected,
        tolerance=result.threshold,
        difference=result.difference,
    )


__all__ = [
    "STATISTICS",
    "EXACT_STATISTICS",
    "primary_statistic",
    "count_condition",
    "compute_statistic",
    "read_numeric_column",
    "dataset_statistic_check",
    "numeric_tolerance_check",
]
