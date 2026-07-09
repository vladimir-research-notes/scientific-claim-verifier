"""Scoring: the one place in the pipeline allowed to draw an inference.

Milestone 7. Extraction (M3) recovered the claim's fields, linking (M4) said where
to look, the checks (M5) read the artifacts, and the sandbox (M6) ran the scripts.
None of them decided anything about the claim. This package does: it turns a set of
:class:`~scientific_claim_verifier.schemas.VerificationCheck` records into a
:class:`~scientific_claim_verifier.schemas.VerificationResult` — a support label, a
reproduction status, a failure mode, and the limitations that survive the verdict.

Signals, not statuses
---------------------
A check's ``status`` is about the *check*; scoring needs to know what the check says
about the *claim*. Those are not the same question, and one status maps to more than
one answer:

- ``evidence_presence`` **fails** two different ways. ``polarity_mismatch`` — the
  passage contains the claim's tokens and negates them — **refutes** the claim.
  ``absent`` — the passage shares no token with the claim — refutes nothing at all;
  silence is not refutation. It leaves the claim undecided by the text.
- ``table_value`` **passes** two different ways. Against a cell locator, the value is
  where the claim said it would be, and that **supports** the claim. Against a bare
  column locator with more than one row, the value merely appears *somewhere* in the
  column: the claim is **ambiguous** over the rows, which is what
  ``underspecified`` means.
- ``code_execution`` **passes** two different ways. If the bundle declared an expected
  stdout and the script printed it, that **supports** the claim. If the bundle
  declared nothing, "exit 0" is not evidence for any number, so the check leaves the
  claim undecided and the accompanying ``numeric_tolerance`` check carries the weight.

So each check is first reduced to one :class:`Signal` — ``supports``, ``refutes``,
``ambiguous``, or ``undecided`` — together with the reason. The label rules then read
only signals. Every mapping below is a pure function of a check's recorded
``status`` and ``inputs``; nothing is re-derived from an artifact, and no prose is
parsed.

Rules are named and recorded
----------------------------
Each of the three classifiers returns its value **and** a :class:`Rule`: the rule's
name, why it fired, and the ``check_id``s it consulted. Those land in the JSONL trace
and in the report, so "why does this claim say ``contradicted``?" is answered by a
lookup rather than by re-reading the code. A verdict a reader cannot re-derive is an
opinion.

Determinism
-----------
Every function here is a pure function of the checks it is handed. Check order is
fixed by ``checks/verification.py``, the rule tables are module constants, and nothing
consults the wall clock, an RNG, or the filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..checks.consistency import Assertion
from ..schemas import CheckStatus, CheckType, VerificationCheck

# Checks whose subject is *reproducing a computation* rather than reading a value
# back. A claim with neither is `not_applicable` for reproduction — reading a table
# cell is a lookup, not a reproduction.
REPRODUCTION_CHECKS = (CheckType.CODE_EXECUTION, CheckType.DATASET_STATISTIC)


class Signal(StrEnum):
    """What one check says about the claim (as opposed to about itself)."""

    SUPPORTS = "supports"
    REFUTES = "refutes"
    AMBIGUOUS = "ambiguous"
    UNDECIDED = "undecided"


@dataclass(frozen=True)
class Rule:
    """A named inference step, with its reason and the checks it consulted.

    Recorded verbatim into the trace. ``check_ids`` may be empty when a rule fires on
    the *absence* of a check (e.g. "no reproduction channel exists").
    """

    name: str
    because: str
    check_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """A JSON-ready dict, keys stable."""
        return {"rule": self.name, "because": self.because, "check_ids": list(self.check_ids)}


@dataclass(frozen=True)
class CheckSignal:
    """One check reduced to what it says about the claim, and why."""

    check_id: str
    check_type: CheckType
    status: CheckStatus
    signal: Signal
    because: str

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "check_type": self.check_type.value,
            "status": self.status.value,
            "signal": self.signal.value,
            "because": self.because,
        }


def error_kind(check: VerificationCheck) -> str | None:
    """The structured cause an ``error`` check recorded, if any.

    See :class:`~scientific_claim_verifier.checks.ErrorKind`. Returns ``None`` for a
    check that did not error, or for one written before the vocabulary existed.
    """
    kind = check.inputs.get("error_kind")
    return str(kind) if kind is not None else None


def is_column_lookup(check: VerificationCheck) -> bool:
    """True when a table check read a whole column because the claim named no row.

    ``_column_check`` records ``row_named: False``; the cell path records ``row``.
    """
    return check.inputs.get("row_named") is False


def is_ambiguous_column(check: VerificationCheck) -> bool:
    """True when a passing column lookup leaves the claim ambiguous over the rows.

    The claimed value was found, but the claim never said *which* row it refers to,
    and the column offers more than one. A single-row column offers no choice, so it
    is not ambiguous.
    """
    if not is_column_lookup(check) or check.status is not CheckStatus.PASS:
        return False
    return int(check.inputs.get("n_rows", 0)) > 1


def _undecidable_because(check: VerificationCheck) -> str:
    """Why a lexical evidence check declined to decide, quoting what it could see."""
    reason = "a lexical check cannot decide whether the passage asserts the claim"
    coverage = check.inputs.get("coverage")
    if not isinstance(coverage, float):
        return reason
    missing = list(check.inputs.get("missing_tokens", []))
    return f"{reason} ({coverage:.0%} token coverage, missing {missing})"


def _evidence_signal(check: VerificationCheck) -> tuple[Signal, str]:
    """Reduce an ``evidence_presence`` check, splitting its two ways of failing."""
    if check.status is CheckStatus.PASS:
        assertion = check.inputs.get("assertion")
        return Signal.SUPPORTS, f"the linked passage states the claim ({assertion})"
    if check.status is CheckStatus.FAIL:
        if check.inputs.get("assertion") == Assertion.POLARITY_MISMATCH.value:
            return (
                Signal.REFUTES,
                "the linked passage contains the claim's tokens but negates them",
            )
        # `absent`: the passage shares no token with the claim. Refutes nothing.
        return (
            Signal.UNDECIDED,
            "the linked passage shares no content token with the claim; "
            "it neither states nor denies it",
        )
    if check.status is CheckStatus.INCONCLUSIVE:
        return Signal.UNDECIDED, _undecidable_because(check)
    if check.status is CheckStatus.SKIPPED:
        return Signal.UNDECIDED, "no passage was linked to this claim"
    return Signal.UNDECIDED, f"the evidence check could not run ({error_kind(check) or 'error'})"


def _table_signal(check: VerificationCheck) -> tuple[Signal, str]:
    """Reduce a ``table_value`` check, splitting its two ways of passing."""
    if is_ambiguous_column(check):
        matching = check.inputs.get("matching_rows", [])
        n_rows = check.inputs.get("n_rows")
        return (
            Signal.AMBIGUOUS,
            f"the claimed value appears at row(s) {list(matching)}, but the claim names no "
            f"row and the column has {n_rows}",
        )
    if check.status is CheckStatus.PASS:
        return Signal.SUPPORTS, "the table holds the claimed value where the claim says it is"
    if check.status is CheckStatus.FAIL:
        return Signal.REFUTES, "the table does not hold the claimed value"
    return _inert_signal(check)


def _execution_signal(check: VerificationCheck) -> tuple[Signal, str]:
    """Reduce a ``code_execution`` check. Exit 0 alone is not evidence for a number."""
    if check.status is CheckStatus.PASS:
        if check.inputs.get("declared_expectations"):
            return Signal.SUPPORTS, "the script printed the output the bundle declared"
        return (
            Signal.UNDECIDED,
            "the script ran cleanly, but the bundle declared no expected output for it "
            "to match; exit 0 alone supports nothing",
        )
    if check.status is CheckStatus.FAIL:
        return Signal.REFUTES, "the script ran but did not print the output the bundle declared"
    return _inert_signal(check)


def _inert_signal(check: VerificationCheck) -> tuple[Signal, str]:
    """The default reduction for a check that reached no verdict about the claim."""
    if check.status is CheckStatus.ERROR:
        return Signal.UNDECIDED, f"the check could not run ({error_kind(check) or 'error'})"
    if check.status is CheckStatus.SKIPPED:
        return Signal.UNDECIDED, "the check did not apply"
    return Signal.UNDECIDED, "the check reached no verdict"


def _value_signal(check: VerificationCheck) -> tuple[Signal, str]:
    """Reduce the numeric-agreement checks, which have exactly two verdicts."""
    if check.status is CheckStatus.PASS:
        return Signal.SUPPORTS, "the computed value agrees with the claim"
    if check.status is CheckStatus.FAIL:
        return Signal.REFUTES, "the computed value disagrees with the claim"
    return _inert_signal(check)


_REDUCERS = {
    CheckType.EVIDENCE_PRESENCE: _evidence_signal,
    CheckType.TABLE_VALUE: _table_signal,
    CheckType.CODE_EXECUTION: _execution_signal,
}


def signal_for(check: VerificationCheck) -> CheckSignal:
    """Reduce one check to what it says about the claim, with the reason kept."""
    reduce = _REDUCERS.get(check.check_type, _value_signal)
    signal, because = reduce(check)
    return CheckSignal(
        check_id=check.check_id,
        check_type=check.check_type,
        status=check.status,
        signal=signal,
        because=because,
    )


def signals(checks: list[VerificationCheck]) -> list[CheckSignal]:
    """Reduce every check, preserving the checks' fixed emission order."""
    return [signal_for(check) for check in checks]


def of_signal(reduced: list[CheckSignal], signal: Signal) -> list[CheckSignal]:
    """The reduced checks carrying one signal, in order."""
    return [item for item in reduced if item.signal is signal]


def decidedness(checks: list[VerificationCheck]) -> float:
    """The share of a claim's checks that reached a ``pass``/``fail`` verdict.

    Recorded as :attr:`~scientific_claim_verifier.schemas.VerificationResult.confidence`.
    It is **not** a probability that the label is correct, and it is not calibrated
    against anything. It answers one narrow question — *how much of this claim could
    the artifacts decide?* — and a claim whose only check is ``inconclusive`` scores
    ``0.0`` no matter how confident the wording of its label sounds.
    """
    if not checks:
        return 0.0
    decided = sum(1 for c in checks if c.status in (CheckStatus.PASS, CheckStatus.FAIL))
    return round(decided / len(checks), 6)


__all__ = [
    "REPRODUCTION_CHECKS",
    "Signal",
    "Rule",
    "CheckSignal",
    "error_kind",
    "is_column_lookup",
    "is_ambiguous_column",
    "signal_for",
    "signals",
    "of_signal",
    "decidedness",
]
