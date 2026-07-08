"""Evidence channels: finding the artifacts that bear on a claim.

Milestone 4. Each module here answers one question about one artifact kind —
*which passage, table cell, dataset column, code file, or figure series does this
claim point at, and how do we know?* — and returns candidate matches carrying the
**named rule** that produced them. The orchestration (turning candidates into a
claim's :class:`~scientific_claim_verifier.schemas.EvidenceLink` list) lives in
:mod:`scientific_claim_verifier.claims.linking`.

- :mod:`~scientific_claim_verifier.evidence.passages` — exact passage lookup plus
  a keyword-overlap (Dice) baseline that ranks every passage in the bundle.
- :mod:`~scientific_claim_verifier.evidence.tables` — metric-column lookup and
  cell/column locators.
- :mod:`~scientific_claim_verifier.evidence.datasets` — dataset-name resolution
  and measured-column selection.
- :mod:`~scientific_claim_verifier.evidence.code_refs` — code-artifact resolution
  and the observable (stdout) locator.
- :mod:`~scientific_claim_verifier.evidence.figures` — figure series/mention
  resolution.

These modules **retrieve**; they do not judge. A high-scoring passage is one that
is lexically similar to the claim, not one that has been shown to *assert* it —
that is the ``evidence_presence`` check (Milestone 5). Keeping retrieval and
judgement apart is what lets a report show the supporting text and the computed
check as separate, separately-auditable things.

Every function is a pure, deterministic function of its inputs: no wall clock, no
RNG, and stable (sorted) ordering wherever ties are possible.
"""

from __future__ import annotations

from enum import StrEnum


class MatchMethod(StrEnum):
    """The named rule that produced an evidence match.

    Recorded in each :class:`~scientific_claim_verifier.schemas.EvidenceLink`'s
    ``notes`` so a reviewer can tell a link that was *asserted* by the task author
    (``declared_source_passage``) from one the linker *discovered* (``exact_text``,
    ``token_overlap``), and an exact cell hit (``table_cell``) from a coarser
    fallback (``table_column``).
    """

    # Passages
    DECLARED_SOURCE = "declared_source_passage"
    EXACT_TEXT = "exact_text"
    TOKEN_OVERLAP = "token_overlap"
    # Tables
    TABLE_CELL = "table_cell"
    TABLE_COLUMN = "table_column"
    TABLE_MENTION = "table_mention"
    # Datasets
    DATASET_NAME = "dataset_name"
    # Code
    CODE_FILENAME = "code_filename"
    CODE_SOLE = "code_sole_artifact"
    # Figures
    FIGURE_SERIES = "figure_series"
    FIGURE_MENTION = "figure_mention"


__all__ = ["MatchMethod"]
