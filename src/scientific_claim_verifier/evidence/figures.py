"""Figure evidence: resolve a figure by its data series, or by an explicit mention.

A :class:`~scientific_claim_verifier.schemas.Figure` carries metadata and the
*data series* behind the plot — never pixels. So a figure is linked the same way a
table is: by finding the series whose name is one of the claim's metrics, giving
the locator ``series=accuracy``. Failing that, a claim that names "Figure 2" in a
bundle holding exactly one figure resolves to that figure, unlocated.

**No committed fixture has a figure yet.** This module exists because
``EvidenceKind.FIGURE`` and the extractor's "Figure N" mention detection already
do, and a mention that silently resolved to nothing would be a hole in the audit
trail. It is unit-tested against synthetic figures; figure *recomputation* lands
with the checks (Milestone 5).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas import Figure, ScientificClaim
from . import MatchMethod, locators
from .tables import normalize_header


@dataclass(frozen=True)
class FigureMatch:
    """A figure linked to a claim, located to a data series where possible."""

    figure_id: str
    locator: str | None
    method: MatchMethod


def matching_series(figure: Figure, metrics: list[str]) -> str | None:
    """The first series of ``figure`` named after one of ``metrics``, or ``None``.

    Series keys are visited in sorted order so the choice is deterministic when a
    figure carries several matching series.
    """
    wanted = {m.lower() for m in metrics}
    for key in sorted(figure.series):
        if normalize_header(key) in wanted:
            return key
    return None


def link_figures(
    claim: ScientificClaim, figures: list[Figure], figure_mentioned: bool = False
) -> list[FigureMatch]:
    """Link ``claim`` to the figures whose series carry one of its metrics.

    Falls back to a sole-figure link when the claim names a figure but no series
    matches. Returns an empty list when neither route resolves.
    """
    matches: list[FigureMatch] = []
    for figure in figures:
        series = matching_series(figure, claim.metrics)
        if series is not None:
            matches.append(
                FigureMatch(
                    figure.figure_id, locators.figure_series(series), MatchMethod.FIGURE_SERIES
                )
            )
    if matches:
        return matches
    if figure_mentioned and len(figures) == 1:
        return [FigureMatch(figures[0].figure_id, None, MatchMethod.FIGURE_MENTION)]
    return []


__all__ = ["FigureMatch", "matching_series", "link_figures"]
