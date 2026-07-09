"""Does the linked passage *assert* the claim, and does the claimed relation hold?

Two checks that judge consistency rather than recompute a number.

``evidence_presence`` — the counterpart to evidence linking. The linker
(Milestone 4) retrieves the passage most lexically similar to the claim; it
explicitly does not judge it. This check asks the narrower, answerable question:
*does that passage state the claim?* Its verdict is one of five
:class:`Assertion` levels, and only two of them are ``pass``.

The check is a transparent lexical rule, and it declares its own limits:

- **verbatim** — the claim's canonicalized text occurs inside the passage. Pass.
- **token_subsumed** — every content token of the claim occurs in the passage,
  with matching polarity. Pass.
- **polarity_mismatch** — the tokens are all there, but the quoting sentence
  carries a negation cue the claim does not (or vice versa): *"the model is **not**
  trained on synthetic data"*. Fail — the passage refutes the claim.
- **partial_overlap** — some claim tokens are missing. **Inconclusive.** A
  bag-of-words rule cannot tell a paraphrase that asserts the claim from one that
  merely discusses it. ``"trained"`` does not match ``"training"``; ``"only"`` does
  not match ``"no real corpora were used"``. Rather than guess, the check reports
  what it can see (coverage, which tokens are missing) and refuses the verdict.
- **absent** — no claim token occurs at all. Fail.

``partial_overlap`` is not a bug being hidden. It is the milestone's most
informative output: on the committed fixtures exactly one claim lands there, and
it is exactly the one whose supporting passage is a genuine paraphrase. Scoring
(Milestone 7) must map it to ``unverifiable_from_artifacts``, never to
``contradicted`` — the checker's ignorance is not evidence against the claim.

``comparison`` — for a directional claim (*"improves accuracy from 72.0 to 78.0"*),
verify the asserted relation between the two values the artifacts actually hold,
which the table check located. It answers *"is the target really greater than the
baseline?"*, not *"is the delta the claimed size?"* — the magnitudes are each
checked against their own cell by ``table_value``. A gap smaller than the claim's
reported precision does not count as an improvement.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..evidence.passages import best_sentence, contains_claim, content_tokens
from ..schemas import (
    CheckStatus,
    CheckType,
    EvidenceLink,
    Passage,
    ScientificClaim,
    VerificationCheck,
)
from . import ErrorKind, Tolerance, operator_holds, resolve_tolerance, stable

# Closed-class negators. They survive stopword removal by design (see
# ``evidence/passages.py``), so they are visible as tokens here.
#
# Limitation: contractions do not tokenize as cues — "isn't" becomes "isn", "t" —
# so `does not` is caught and `doesn't` is not. Fixture prose is unabbreviated.
NEGATION_CUES = frozenset({"no", "not", "never", "none", "nor", "neither", "without", "cannot"})


class Assertion(StrEnum):
    """How strongly a passage states a claim. Recorded as the check's computed value."""

    VERBATIM = "verbatim"
    TOKEN_SUBSUMED = "token_subsumed"
    PARTIAL_OVERLAP = "partial_overlap"
    POLARITY_MISMATCH = "polarity_mismatch"
    ABSENT = "absent"


# Only these two mean "the passage says the claim".
_ASSERTING = frozenset({Assertion.VERBATIM, Assertion.TOKEN_SUBSUMED})
_STATUS: dict[Assertion, CheckStatus] = {
    Assertion.VERBATIM: CheckStatus.PASS,
    Assertion.TOKEN_SUBSUMED: CheckStatus.PASS,
    Assertion.PARTIAL_OVERLAP: CheckStatus.INCONCLUSIVE,
    Assertion.POLARITY_MISMATCH: CheckStatus.FAIL,
    Assertion.ABSENT: CheckStatus.FAIL,
}


def negation_cues(text: str) -> tuple[str, ...]:
    """The negation cues present in ``text``, sorted for a stable record."""
    return tuple(sorted(content_tokens(text) & NEGATION_CUES))


@dataclass(frozen=True)
class Presence:
    """The lexical facts behind an :class:`Assertion`, kept for the audit trail."""

    assertion: Assertion
    coverage: float
    missing_tokens: tuple[str, ...]
    claim_cues: tuple[str, ...]
    sentence_cues: tuple[str, ...]
    sentence: str | None


def assess_presence(claim_text: str, passage_text: str) -> Presence:
    """Decide how strongly ``passage_text`` states ``claim_text``, and why.

    Polarity is judged on the passage's **best-matching sentence**, not the whole
    passage: a paper may negate something elsewhere without negating the claim.
    """
    claim_tokens = content_tokens(claim_text)
    passage_tokens = content_tokens(passage_text)
    missing = tuple(sorted(claim_tokens - passage_tokens))
    coverage = (
        (len(claim_tokens) - len(missing)) / len(claim_tokens) if claim_tokens else 0.0
    )

    sentence = best_sentence(claim_text, passage_text)
    claim_cues = negation_cues(claim_text)
    sentence_cues = negation_cues(sentence or "")
    polarity_differs = set(claim_cues) != set(sentence_cues)

    if contains_claim(claim_text, passage_text):
        assertion = Assertion.VERBATIM
    elif not missing and claim_tokens:
        assertion = Assertion.POLARITY_MISMATCH if polarity_differs else Assertion.TOKEN_SUBSUMED
    elif coverage == 0.0:
        assertion = Assertion.ABSENT
    else:
        assertion = Assertion.PARTIAL_OVERLAP

    return Presence(
        assertion=assertion,
        coverage=stable(coverage),
        missing_tokens=missing,
        claim_cues=claim_cues,
        sentence_cues=sentence_cues,
        sentence=sentence,
    )


def evidence_presence_check(
    check_id: str,
    claim: ScientificClaim,
    link: EvidenceLink | None,
    passage: Passage | None,
) -> VerificationCheck:
    """Check whether the linked passage asserts the claim.

    ``link=None`` (nothing was linked) is ``skipped``; a link whose ``target_id``
    resolves to no passage is ``error`` — a dangling provenance record is a defect
    in the pipeline, not a fact about the claim.
    """
    base = {
        "check_id": check_id,
        "check_type": CheckType.EVIDENCE_PRESENCE,
        "claim_id": claim.claim_id,
    }
    if link is None:
        return VerificationCheck(
            **base,
            status=CheckStatus.SKIPPED,
            notes="no passage was linked to this claim; there is no supporting text to check",
        )
    if passage is None:
        return VerificationCheck(
            **base,
            status=CheckStatus.ERROR,
            evidence=[link],
            inputs={"passage_id": link.target_id, "error_kind": ErrorKind.MISSING_PASSAGE.value},
            notes=f"linked passage {link.target_id!r} does not resolve to any passage",
        )

    presence = assess_presence(claim.claim_text, passage.text)
    notes = {
        Assertion.VERBATIM: "the passage states the claim verbatim",
        Assertion.TOKEN_SUBSUMED: "the passage contains every content token of the claim, "
        "with matching polarity",
        Assertion.POLARITY_MISMATCH: "the passage contains the claim's tokens but negates it "
        f"(cues {list(presence.sentence_cues)} vs. claim {list(presence.claim_cues)})",
        Assertion.PARTIAL_OVERLAP: "a lexical check cannot decide whether this passage asserts "
        f"the claim: {presence.coverage:.0%} token coverage, "
        f"missing {list(presence.missing_tokens)}",
        Assertion.ABSENT: "the passage shares no content token with the claim",
    }[presence.assertion]

    return VerificationCheck(
        **base,
        status=_STATUS[presence.assertion],
        computed_value=presence.assertion.value,
        evidence=[link],
        inputs={
            "passage_id": passage.passage_id,
            "section": passage.section,
            "assertion": presence.assertion.value,
            "coverage": presence.coverage,
            "missing_tokens": list(presence.missing_tokens),
            "claim_negation_cues": list(presence.claim_cues),
            "sentence_negation_cues": list(presence.sentence_cues),
            "quoted_sentence": presence.sentence,
        },
        notes=notes,
    )


def asserts_claim(presence: Presence) -> bool:
    """True when the passage was found to state the claim (verbatim or subsumed)."""
    return presence.assertion in _ASSERTING


def comparison_check(
    check_id: str,
    claim: ScientificClaim,
    observed_baseline: float | None,
    observed_target: float | None,
    evidence: list[EvidenceLink],
    override: Tolerance | None = None,
) -> VerificationCheck:
    """Verify the claim's asserted relation between the two values found in the artifacts.

    ``observed_baseline`` / ``observed_target`` are the values the table check read
    back for the claim's ``baseline_value`` and ``expected_value``. Either being
    ``None`` means the artifacts did not yield both sides, so the relation cannot be
    tested and the check is ``skipped``.
    """
    base = {
        "check_id": check_id,
        "check_type": CheckType.COMPARISON,
        "claim_id": claim.claim_id,
    }
    operator = claim.comparison_operator
    if operator is None or claim.baseline_value is None or claim.expected_value is None:
        return VerificationCheck(
            **base,
            status=CheckStatus.SKIPPED,
            evidence=evidence,
            notes="the claim does not assert a relation between two values",
        )

    claimed_delta = stable(claim.expected_value - claim.baseline_value)
    inputs: dict = {
        "operator": operator.value,
        "claimed_baseline": stable(claim.baseline_value),
        "claimed_target": stable(claim.expected_value),
        "claimed_delta": claimed_delta,
    }
    if observed_baseline is None or observed_target is None:
        return VerificationCheck(
            **base,
            status=CheckStatus.SKIPPED,
            evidence=evidence,
            inputs=inputs,
            expected_value=claimed_delta,
            notes="the artifacts do not yield both sides of the comparison "
            "(no located cell for the baseline and the target)",
        )

    tolerance = resolve_tolerance(claim, claim.baseline_value, override=override)
    threshold = tolerance.threshold(claim.baseline_value)
    holds = operator_holds(operator, observed_target, observed_baseline, threshold)
    observed_delta = stable(observed_target - observed_baseline)
    inputs |= {
        "observed_baseline": stable(observed_baseline),
        "observed_target": stable(observed_target),
    }

    return VerificationCheck(
        **base,
        status=CheckStatus.PASS if holds else CheckStatus.FAIL,
        computed_value=observed_delta,
        expected_value=claimed_delta,
        tolerance=stable(threshold),
        difference=stable(observed_delta - claimed_delta),
        evidence=evidence,
        inputs=inputs,
        notes=f"artifacts hold {stable(observed_target):g} vs {stable(observed_baseline):g}; "
        f"claim asserts target {operator.value} baseline — "
        f"{'holds' if holds else 'does NOT hold'} at tolerance {stable(threshold):g} "
        f"(observed delta {observed_delta:g}, claimed {claimed_delta:g})",
    )


__all__ = [
    "NEGATION_CUES",
    "Assertion",
    "Presence",
    "negation_cues",
    "assess_presence",
    "asserts_claim",
    "evidence_presence_check",
    "comparison_check",
]
