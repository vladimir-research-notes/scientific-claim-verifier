"""Claim processing: rule-based extraction and normalization.

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

These are *heuristics*, labelled as such (see ``docs/EXTRACTION.md``). They do not
attempt sophisticated NLP; they attempt transparency — every populated field is
traceable to the rule that produced it. Scored evidence *linking* (searching the
bundle for the best supporting passage) is the evidence linker's job (Milestone
4); the extractor only records references the claim text names explicitly.
"""

from __future__ import annotations

__all__: list[str] = []
