"""Assigning the support label: is the claim backed by *these* artifacts?

Five ordered rules over the :class:`~scientific_claim_verifier.scoring.Signal` each
check was reduced to. The first that fires wins, and it is recorded by name.

===========================  ==============================================================
``artifacts_refute``         Some check refutes the claim. → ``contradicted``
``claim_ambiguous``          Nothing refutes it, but a check cannot tell *which* value the
                             claim refers to. → ``underspecified``
``all_checks_support``       Every check reached a verdict, and every verdict supports the
                             claim. → ``supported``
``some_checks_support``      Some checks support it, others could not decide, none refute
                             it. → ``partially_supported``
``nothing_decided``          No check reached a verdict. → ``unverifiable_from_artifacts``
===========================  ==============================================================

Order is the argument
---------------------
Refutation beats ambiguity: a value absent from a column is contradicted whether or
not the claim also omitted the row. Ambiguity beats support: ``underspecified_split``
finds ``90.0`` in the accuracy column and would otherwise read as ``supported``, which
is precisely the overclaim the label exists to prevent — the table reports 90.0 on dev
and 82.0 on test, and the claim never says which.

And ``nothing_decided`` maps onto ``unverifiable_from_artifacts``, never onto
``contradicted``. A checker that cannot decide has learned nothing about the claim;
reporting a contradiction there would turn the checker's own ignorance into evidence
against the paper. ``synthetic_data_passage`` is the committed fixture that lands
here: the passage genuinely does support the claim, but the transparent lexical check
faced with a paraphrase says ``inconclusive``, so the honest verdict is *"these
artifacts, read this way, cannot settle it"*. Its gold label is ``supported``, and
this is the one fixture the pipeline does not recover — a conservative miss, not a
wrong verdict. See ``docs/SCORING.md``.

The empty case (``no_checks`` → ``not_checked``) is a guard: the check runner always
emits at least an ``evidence_presence`` check, so it should be unreachable through the
CLI. It exists so a caller assembling checks by hand cannot get a verdict for free.
"""

from __future__ import annotations

from ..schemas import SupportLabel, VerificationCheck
from . import CheckSignal, Rule, Signal, of_signal, signals


def _ids(items: list[CheckSignal]) -> tuple[str, ...]:
    """The check ids behind a set of signals, in check order."""
    return tuple(item.check_id for item in items)


def classify_support(checks: list[VerificationCheck]) -> tuple[SupportLabel, Rule]:
    """Assign a support label from the checks, and name the rule that assigned it."""
    reduced = signals(checks)
    return classify_support_signals(reduced)


def classify_support_signals(reduced: list[CheckSignal]) -> tuple[SupportLabel, Rule]:
    """The rule table itself, over already-reduced checks."""
    if not reduced:
        return SupportLabel.NOT_CHECKED, Rule(
            "no_checks", "no check was run against this claim, so nothing was verified"
        )

    refuting = of_signal(reduced, Signal.REFUTES)
    if refuting:
        return SupportLabel.CONTRADICTED, Rule(
            "artifacts_refute",
            "; ".join(item.because for item in refuting),
            _ids(refuting),
        )

    ambiguous = of_signal(reduced, Signal.AMBIGUOUS)
    if ambiguous:
        return SupportLabel.UNDERSPECIFIED, Rule(
            "claim_ambiguous",
            "; ".join(item.because for item in ambiguous),
            _ids(ambiguous),
        )

    supporting = of_signal(reduced, Signal.SUPPORTS)
    undecided = of_signal(reduced, Signal.UNDECIDED)

    if supporting and not undecided:
        return SupportLabel.SUPPORTED, Rule(
            "all_checks_support",
            f"all {len(supporting)} check(s) reached a verdict and every verdict "
            "supports the claim",
            _ids(supporting),
        )
    if supporting:
        return SupportLabel.PARTIALLY_SUPPORTED, Rule(
            "some_checks_support",
            f"{len(supporting)} check(s) support the claim, {len(undecided)} could not "
            "decide, and none refute it",
            _ids(supporting + undecided),
        )
    return SupportLabel.UNVERIFIABLE_FROM_ARTIFACTS, Rule(
        "nothing_decided",
        "no check reached a verdict: " + "; ".join(item.because for item in undecided),
        _ids(undecided),
    )


__all__ = ["classify_support", "classify_support_signals"]
