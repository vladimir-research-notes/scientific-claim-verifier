"""Deterministic normalization of an extracted claim into a canonical string.

``normalized_claim`` is a compact, canonical rendering of a claim's *structured*
content — the primary metric, the comparison operator, and the value(s) — used
downstream for display and rough matching. It is built solely from the fields the
extractor already populated (:mod:`scientific_claim_verifier.claims.extraction`),
so it is a pure, deterministic function of the claim object: same claim in, same
string out, no wall-clock or RNG.

This is the *extractor's own* canonical form. It is intentionally **not** compared
against a task's gold ``normalized_claim`` (which is a hand-authored human
reference in a different notation): a rule-based system cannot be expected to
reproduce arbitrary hand-written phrasing, and pretending otherwise would be
overclaiming. The scored fields are the structured ones (see
:func:`~scientific_claim_verifier.claims.extraction.score_extraction`).
"""

from __future__ import annotations

import re

from ..schemas import ScientificClaim

# Metrics that name a *count*, not a headline value (see the extraction lexicon).
# The primary metric for the normalized string is the first non-count metric.
_NON_VALUE_METRICS = frozenset({"count"})

_WHITESPACE_RE = re.compile(r"\s+")


def _num(value: float) -> str:
    """Format a numeric value compactly and deterministically (``72``, ``3.4``)."""
    return f"{value:g}"


def _primary_metric(metrics: list[str]) -> str:
    """The headline metric for the normalized form: first non-count metric.

    Falls back to the first metric, then to ``"value"`` if there are none, so the
    function is total.
    """
    for metric in metrics:
        if metric not in _NON_VALUE_METRICS:
            return metric
    return metrics[0] if metrics else "value"


def canonical_text(text: str) -> str:
    """Lowercase, collapse internal whitespace, and strip a trailing period."""
    collapsed = _WHITESPACE_RE.sub(" ", text).strip()
    return collapsed.rstrip(".").strip().lower()


def normalize(claim: ScientificClaim) -> str:
    """Build the canonical ``normalized_claim`` string for a populated claim.

    Three shapes, chosen by what the extractor recovered:

    - a *comparison* with both endpoints → ``"accuracy: 72 -> 78 (>)"``;
    - a single *value* → ``"accuracy = 90"``, ``"mean ~ 3.4"``;
    - otherwise (no numeric value, e.g. a descriptive claim) → the canonicalized
      claim text.

    A trailing units token (e.g. ``%``) is appended when known. The output is the
    extractor's own canonical notation, not a match target for gold.
    """
    metric = _primary_metric(claim.metrics)
    operator = claim.comparison_operator.value if claim.comparison_operator else None

    if claim.baseline_value is not None and claim.expected_value is not None:
        op = operator or "->"
        core = f"{metric}: {_num(claim.baseline_value)} -> {_num(claim.expected_value)} ({op})"
    elif claim.expected_value is not None:
        core = f"{metric} {operator or '='} {_num(claim.expected_value)}"
    else:
        core = canonical_text(claim.claim_text)

    if claim.units:
        core = f"{core} {claim.units}"
    return core


__all__ = ["canonical_text", "normalize"]
