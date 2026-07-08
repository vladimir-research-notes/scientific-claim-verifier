"""Dataset evidence: resolve a dataset mention, then name the measured column.

A claim like *"The measurements dataset has 12 samples with a mean value of 3.4"*
must be linked to the committed CSV and, where possible, to the column the
statistic is computed over — the locator ``column=value`` is what lets the
dataset-statistic check (Milestone 5) recompute the mean without guessing.

Column selection is deliberately narrow:

1. Drop **identifier** columns (``id``, ``sample_id``, ``index``, ``name``, …).
   They label rows; they are never the measured quantity.
2. If a remaining column is named after one of the claim's metrics, take it.
3. Otherwise, if **exactly one** column remains, it is unambiguously the measured
   column; take it.
4. Otherwise **decline**: link the dataset as a whole with no column locator.

Step 4 matters. A dataset with several candidate columns and a claim that names
none of them is underspecified, and the honest link says so by leaving the
locator empty rather than picking the first column.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Dataset-name resolution is shared with the extractor's explicit-reference pass,
# so a mention resolves to the same artifact in both places.
from ..claims.extraction import resolve_dataset_reference
from ..schemas import ArtifactBundle, DatasetArtifact, ScientificClaim
from . import MatchMethod
from .tables import normalize_header

# Columns that identify a row rather than measure it.
_ID_COLUMN_RE = re.compile(r"^(?:id|idx|index|key|name|label|.*_id)$")


@dataclass(frozen=True)
class DatasetMatch:
    """A dataset linked to a claim, with the measured column when it is unambiguous."""

    artifact_id: str
    locator: str | None
    method: MatchMethod
    mention: str


def is_identifier_column(name: str) -> bool:
    """True if ``name`` looks like a row identifier rather than a measurement."""
    return bool(_ID_COLUMN_RE.match(normalize_header(name)))


def measured_column(dataset: DatasetArtifact, claim: ScientificClaim) -> str | None:
    """Return the column ``claim``'s statistic is computed over, or ``None``.

    ``None`` means "cannot be justified from the declared columns" — the linker
    does not guess. See the module docstring for the four-step rule.
    """
    candidates = [c for c in dataset.columns if not is_identifier_column(c)]
    if not candidates:
        return None
    metrics = {m.lower() for m in claim.metrics}
    for column in candidates:
        if normalize_header(column) in metrics:
            return column
    return candidates[0] if len(candidates) == 1 else None


def link_datasets(
    claim: ScientificClaim, bundle: ArtifactBundle, dataset_names: list[str]
) -> list[DatasetMatch]:
    """Resolve each dataset name the claim mentions against ``bundle``.

    ``dataset_names`` comes from the extractor (known-name lexicon plus the
    ``"<name> dataset"`` phrase pattern). Mentions that resolve to no artifact are
    dropped here — the extractor already records them as unresolved references, so
    nothing is silently lost.
    """
    matches: list[DatasetMatch] = []
    seen: set[str] = set()
    for name in dataset_names:
        artifact_id = resolve_dataset_reference(name, bundle)
        if artifact_id is None or artifact_id in seen:
            continue
        seen.add(artifact_id)
        dataset = bundle.dataset(artifact_id)
        column = measured_column(dataset, claim) if dataset is not None else None
        matches.append(
            DatasetMatch(
                artifact_id=artifact_id,
                locator=f"column={column}" if column else None,
                method=MatchMethod.DATASET_NAME,
                mention=name,
            )
        )
    return matches


__all__ = [
    "DatasetMatch",
    "is_identifier_column",
    "measured_column",
    "link_datasets",
]
