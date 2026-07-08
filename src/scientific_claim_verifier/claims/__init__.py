"""Claim processing: rule-based extraction, normalization, and evidence linking.

Milestone 3 turns the claim *as authored* (the input ``ScientificClaim`` produced
by :meth:`~scientific_claim_verifier.artifacts.loader.LoadedTask.input_claim` —
id, text, type, provenance, and nothing else) into a *populated* claim whose
typed fields (numeric values, comparison operator, metrics, datasets, entities,
conditions, units) are recovered by transparent, rule-based heuristics:

- :mod:`scientific_claim_verifier.claims.extraction` — the
  :class:`~.extraction.RuleBasedClaimExtractor` and its independently-testable
  sub-extractors (numbers, comparison phrases, metric lexicon, dataset/table/code
  references, entities, conditions, units), plus a per-field scorer against the
  gold :class:`~scientific_claim_verifier.artifacts.loader.GoldClaim`.
- :mod:`scientific_claim_verifier.claims.normalization` — a deterministic
  canonical ``normalized_claim`` string built from the populated claim.

Milestone 4 then links that populated claim to the artifacts that bear on it:

- :mod:`scientific_claim_verifier.claims.linking` — the
  :class:`~.linking.EvidenceLinker`, which drives the per-artifact channels in
  :mod:`scientific_claim_verifier.evidence` and emits scored
  :class:`~scientific_claim_verifier.schemas.EvidenceLink` provenance records,
  plus a scorer against a task's gold evidence.

These are *heuristics*, labelled as such (see ``docs/EXTRACTION.md`` and
``docs/EVIDENCE_LINKING.md``). They do not attempt sophisticated NLP; they attempt
transparency — every populated field and every link is traceable to the rule that
produced it. The linker *retrieves* evidence; deciding whether linked evidence
**asserts** a claim is a verification check (Milestone 5).
"""

from __future__ import annotations

__all__: list[str] = []
