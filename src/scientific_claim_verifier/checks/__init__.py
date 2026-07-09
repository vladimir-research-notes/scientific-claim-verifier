"""Deterministic verification checks: turning located evidence into computed facts.

Milestone 5. A check takes an extracted claim (M3) plus the evidence links that say
*where to look* (M4), reads the artifact at that locator, computes something, and
records the result as a :class:`~scientific_claim_verifier.schemas.VerificationCheck`
carrying its inputs, the computed value, the expected value, the tolerance actually
applied, the signed difference, and the evidence it used.

A check does not decide the claim's fate
----------------------------------------
Checks produce *evidence about* a claim; the support label, the reproduction
status, and the failure mode are inferred from the set of checks by scoring
(Milestone 7). This separation is the point of the project: a report shows the
**supporting text** and the **computed check** as two independently auditable
channels, and they are allowed to disagree. The ``contradicted_f1`` fixture exists
precisely to exhibit that — the paper's own sentence asserts the claim verbatim
(``evidence_presence`` passes) while the results table refutes it
(``table_value`` fails).

Five outcomes, not two
----------------------
``pass`` and ``fail`` are the easy cases. ``error`` means the check could not run.
``skipped`` means it did not apply. ``inconclusive`` means it ran and its method
**genuinely cannot tell** — the honest verdict for a transparent bag-of-words
evidence check faced with a paraphrase. Collapsing ``inconclusive`` into ``fail``
would manufacture contradictions out of the checker's own ignorance.

Tolerance comes from the claim, not from a constant
---------------------------------------------------
Numeric comparisons never use exact float equality. The default tolerance is the
claim's own **reported precision**: a value written ``3.4`` asserts only that the
quantity rounds to ``3.4``, so the threshold is half of the last reported decimal
place (``0.05``). ``0.80`` gives ``0.005``; ``90%`` gives ``0.5``. This makes the
tolerance a property of how the claim was *written* rather than a magic constant,
and it is recorded on every check. A task may override it (``tolerance:`` in the
task file), and so may a caller (``--abs-tol`` / ``--rel-tol``). Counts are
compared exactly — a dataset has an integer number of rows.

Determinism
-----------
Every check is a pure function of its inputs apart from the code-execution check,
which shells out to a fixture script. No wall clock, no RNG, and no absolute
filesystem paths reach a check's recorded output, so a trace is byte-reproducible
across machines. Floats are rounded to :data:`STABLE_DIGITS` decimal places before
being recorded, which is far below any tolerance in play.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from ..claims.extraction import extract_numbers

# Capping a child process's captured output is the sandbox's concern (Milestone 6).
# Re-exported here so a check has one import for the helpers it records with.
from ..sandbox.policy import MAX_CAPTURE_CHARS, truncate
from ..schemas import CheckType, ComparisonOperator, ScientificClaim

# Recorded floats are rounded to this many decimal places so that a value such as
# ``40.8 / 12 = 3.4000000000000004`` is written as ``3.4``. Well below every
# tolerance the checks apply, so rounding can never flip a verdict.
STABLE_DIGITS = 12


class ErrorKind(StrEnum):
    """Why a check reported ``error``, as a closed vocabulary rather than prose.

    Every ``error`` check records one of these in ``inputs["error_kind"]``. Scoring
    (Milestone 7) maps them onto reproduction statuses and failure modes, so *"the
    dataset file is missing"* and *"the column is not numeric"* can be told apart by
    a table lookup instead of by matching English in ``notes``. A check's ``notes``
    remain the human explanation; this is the machine one.
    """

    DANGLING_LINK = "dangling_link"  # the evidence link resolves to no artifact
    MISSING_PASSAGE = "missing_passage"  # a passage link pointing at no passage
    MISSING_DATA = "missing_data"  # dataset declares no path, or the file is absent
    UNREADABLE_DATA = "unreadable_data"  # column absent, non-numeric, or statistic undefined
    MISSING_CODE = "missing_code"  # code declares no path, or the script is absent
    SANDBOX_FAILURE = "sandbox_failure"  # the sandbox could not enforce its own policy
    EXECUTION_TIMEOUT = "execution_timeout"  # the script exceeded its wall-clock timeout
    NONZERO_EXIT = "nonzero_exit"  # the script ran and exited non-zero
    MISSING_COLUMN = "missing_column"  # the locator names a column the table lacks
    MISSING_ROW = "missing_row"  # the locator names a row the table lacks
    NON_NUMERIC_CELL = "non_numeric_cell"  # the located cell is absent or not a number
    EMPTY_COLUMN = "empty_column"  # the located column holds no numeric cell


@dataclass(frozen=True)
class Tolerance:
    """An absolute and a relative tolerance, resolved against an expected value.

    The threshold applied to ``|computed − expected|`` is
    ``max(abs_tol, rel_tol · |expected|)``. Keeping both and recording the
    *resolved scalar* on the check means a reader sees the number that was
    actually applied, not a formula to re-evaluate.
    """

    abs_tol: float = 0.0
    rel_tol: float = 0.0

    def threshold(self, expected: float) -> float:
        """The effective absolute threshold for this ``expected`` value."""
        return max(self.abs_tol, self.rel_tol * abs(expected))


# Exact equality. Correct for counts: a CSV has a whole number of rows.
EXACT = Tolerance()

# The fallback when a claim's number cannot be located in its own text (so its
# reported precision is unknown). Admits IEEE-754 accumulation noise, nothing more.
FLOAT_NOISE = Tolerance(abs_tol=1e-9, rel_tol=1e-9)


def stable(value: float) -> float:
    """Round ``value`` for recording. See :data:`STABLE_DIGITS`."""
    return round(value, STABLE_DIGITS)


def decimal_places(raw: str) -> int:
    """Digits after the decimal point in a number *as written* (``"0.80"`` → 2)."""
    _, _, fraction = raw.rstrip("%").partition(".")
    return len(fraction)


def reported_precision_tolerance(claim_text: str, value: float) -> Tolerance | None:
    """Half of the last reported decimal place of ``value`` as written in ``claim_text``.

    ``"a mean value of 3.4"`` → ``Tolerance(abs_tol=0.05)``: any computed value that
    rounds to ``3.4`` is consistent with what the claim actually asserts. Returns
    ``None`` when ``value`` appears nowhere in the text, in which case the caller
    falls back to :data:`FLOAT_NOISE`.
    """
    for number in extract_numbers(claim_text):
        if math.isclose(number.value, value, rel_tol=0.0, abs_tol=1e-12):
            return Tolerance(abs_tol=0.5 * 10 ** -decimal_places(number.raw))
    return None


def resolve_tolerance(
    claim: ScientificClaim,
    value: float | None = None,
    *,
    override: Tolerance | None = None,
    exact: bool = False,
) -> Tolerance:
    """Pick the tolerance for comparing against ``value`` (default: the claim's own).

    Precedence: an explicit ``override`` (task file or CLI flag) → ``exact`` for
    integer-valued quantities → the claim's reported precision → float noise.
    """
    if override is not None:
        return override
    if exact:
        return EXACT
    target = claim.expected_value if value is None else value
    if target is None:
        return FLOAT_NOISE
    return reported_precision_tolerance(claim.claim_text, target) or FLOAT_NOISE


@dataclass(frozen=True)
class Comparison:
    """One numeric comparison, with everything needed to audit it."""

    computed: float
    expected: float
    difference: float
    threshold: float
    within: bool


def compare(computed: float, expected: float, tolerance: Tolerance) -> Comparison:
    """Compare ``computed`` against ``expected``; ``difference`` is ``computed − expected``."""
    threshold = tolerance.threshold(expected)
    difference = computed - expected
    return Comparison(
        computed=stable(computed),
        expected=stable(expected),
        difference=stable(difference),
        threshold=stable(threshold),
        within=abs(difference) <= threshold,
    )


def operator_holds(
    operator: ComparisonOperator, observed: float, reference: float, threshold: float
) -> bool:
    """True if ``observed <operator> reference`` holds, given a tolerance ``threshold``.

    Strict operators require the gap to *exceed* the threshold: a difference smaller
    than the claim's own reported precision is not an improvement, it is noise.
    """
    gap = observed - reference
    if operator in (ComparisonOperator.EQ, ComparisonOperator.APPROX):
        return abs(gap) <= threshold
    if operator is ComparisonOperator.GT:
        return gap > threshold
    if operator is ComparisonOperator.GE:
        return gap >= -threshold
    if operator is ComparisonOperator.LT:
        return -gap > threshold
    if operator is ComparisonOperator.LE:
        return -gap >= -threshold
    raise ValueError(f"unhandled comparison operator: {operator!r}")


def check_id(claim_id: str, check_type: CheckType, ordinal: int = 1) -> str:
    """A stable, readable id: ``c_dataset_mean.dataset_statistic.2``."""
    return f"{claim_id}.{check_type.value}.{ordinal}"


__all__ = [
    "STABLE_DIGITS",
    "MAX_CAPTURE_CHARS",
    "ErrorKind",
    "Tolerance",
    "EXACT",
    "FLOAT_NOISE",
    "Comparison",
    "stable",
    "truncate",
    "decimal_places",
    "reported_precision_tolerance",
    "resolve_tolerance",
    "compare",
    "operator_holds",
    "check_id",
]
