"""Table evidence: locate the column, and the cell, a numeric claim points at.

A claim like *"Method A improves accuracy from 72.0 to 78.0 over the baseline"*
is checked against a results table. This module answers **where** in the table to
look, and emits a locator precise enough for the check (Milestone 5) to read the
cell back:

- ``row=A,col=accuracy`` — a specific cell;
- ``col=accuracy`` — the whole column, when no single row can be justified.

## The row rule

A cell link is only emitted when the claim **names the row**. Consider
*"The method reaches 90% accuracy"* against a table with ``dev 90.0`` and
``test 82.0``. The value 90.0 matches exactly one cell, so it is tempting to link
``row=dev``. That would silently attribute the claim to a split the claim never
mentioned — the underspecification would vanish into a confident-looking locator.
Instead the linker falls back to ``col=accuracy``, and the claim stays visibly
ambiguous over that column, which is the signal scoring (Milestone 7) needs to
label it ``underspecified``.

Conversely, when the value matches a cell **and** the claim names its row label
(``Method A`` names row ``A``; the word "baseline" names row ``baseline``), the
cell locator is justified and emitted.

When the metric column exists but no claim value matches any of its cells, the
column link is still emitted: that is precisely the case a ``contradicted`` verdict
must be able to reach, and it cannot be reached without a link to check.

The rules are transparent, but note honestly that the two committed table fixtures
(``accuracy_improvement``, ``underspecified_split``) were in view while they were
written; see ``docs/EVIDENCE_LINKING.md``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# The metric lexicon lives in the extractor. Reusing it here means a table header
# and a claim metric are canonicalized by exactly one piece of code ("F1 score"
# and "f1" are the same metric in both places).
from ..claims.extraction import extract_metrics
from ..schemas import ScientificClaim, Table
from . import MatchMethod, locators
from .passages import STOPWORDS


@dataclass(frozen=True)
class TableMatch:
    """A located piece of table evidence: a cell, a whole column, or a whole table."""

    table_id: str
    locator: str | None
    method: MatchMethod
    matched_value: float | None = None


def normalize_header(name: str) -> str:
    """Canonicalize a column header for comparison (``"F1 Score"`` -> ``"f1_score"``)."""
    return re.sub(r"[\s\-]+", "_", name.strip().lower())


def header_matches_metric(header: str, metrics: list[str]) -> bool:
    """True if a column ``header`` denotes one of the claim's ``metrics``.

    Two ways to match: the normalized header *is* a claim metric, or the header's
    own canonical metric names (via the extractor's lexicon) intersect them.
    """
    if not metrics:
        return False
    wanted = {m.lower() for m in metrics}
    if normalize_header(header) in wanted:
        return True
    return bool(set(extract_metrics(header)) & wanted)


def metric_column_indices(table: Table, metrics: list[str]) -> list[int]:
    """Indices of ``table``'s columns that denote one of ``metrics``, in order."""
    return [i for i, col in enumerate(table.columns) if header_matches_metric(col, metrics)]


def label_column_index(table: Table) -> int | None:
    """Index of the row-label column: the first column that is a string in every row.

    Returns ``None`` for a table with no rows or no all-string column (in which
    case no row can be named, so only column-level links are possible).
    """
    if not table.rows:
        return None
    width = len(table.columns) or max(len(row) for row in table.rows)
    for index in range(width):
        cells = [row[index] for row in table.rows if index < len(row)]
        if cells and all(isinstance(cell, str) and cell.strip() for cell in cells):
            return index
    return None


def row_label(table: Table, row_index: int, label_index: int | None) -> str | None:
    """The label of row ``row_index``, or ``None`` if the table has no label column."""
    if label_index is None:
        return None
    row = table.rows[row_index]
    if label_index >= len(row):
        return None
    cell = row[label_index]
    return cell.strip() if isinstance(cell, str) and cell.strip() else None


def claim_names_row(label: str, claim: ScientificClaim) -> bool:
    """True if ``claim`` identifies the table row called ``label``.

    Three routes, in order:

    - an extracted entity contains the label as a whole word (``"Method A"`` names
      row ``A``) — matched case-sensitively, since entities are proper names;
    - for labels of three or more characters, the label appears as a whole word in
      the claim text, case-insensitively, and is not a stopword;
    - for one- and two-character labels, the same word match but **case-sensitive**,
      so a row called ``A`` is not named by the article "a".
    """
    label = label.strip()
    if not label:
        return False
    cased = re.compile(rf"\b{re.escape(label)}\b")
    if any(cased.search(entity) for entity in claim.entities):
        return True
    if len(label) >= 3:
        if label.lower() in STOPWORDS:
            return False
        return bool(re.search(rf"\b{re.escape(label)}\b", claim.claim_text, re.IGNORECASE))
    return bool(cased.search(claim.claim_text))


def _is_number(cell: object) -> bool:
    """True for a numeric cell. ``bool`` is excluded — a flag is not a measurement."""
    return isinstance(cell, int | float) and not isinstance(cell, bool)


def link_table(claim: ScientificClaim, table: Table) -> list[TableMatch]:
    """Locate ``claim``'s evidence in ``table``: named cells, else the metric column.

    Returns an empty list when the table has no column for any of the claim's
    metrics — such a table is not evidence for this claim and is not linked.
    """
    matches: list[TableMatch] = []
    label_index = label_column_index(table)
    values = [v for v in (claim.expected_value, claim.baseline_value) if v is not None]

    for column_index in metric_column_indices(table, claim.metrics):
        column = table.columns[column_index]
        cells: list[TableMatch] = []

        for value in values:
            for row_index, row in enumerate(table.rows):
                cell = row[column_index] if column_index < len(row) else None
                if not _is_number(cell) or not math.isclose(
                    float(cell), value, rel_tol=1e-9, abs_tol=1e-9
                ):
                    continue
                label = row_label(table, row_index, label_index)
                if label is None or not claim_names_row(label, claim):
                    continue
                cells.append(
                    TableMatch(
                        table_id=table.table_id,
                        locator=locators.table_cell(label, column),
                        method=MatchMethod.TABLE_CELL,
                        matched_value=float(cell),
                    )
                )

        # No cell the claim can justify: link the column, so the check still has
        # somewhere to look (and a contradiction stays discoverable).
        matches.extend(
            cells
            or [
                TableMatch(
                    table_id=table.table_id,
                    locator=locators.table_column(column),
                    method=MatchMethod.TABLE_COLUMN,
                )
            ]
        )

    return _dedupe(matches)


def link_tables(
    claim: ScientificClaim, tables: list[Table], figure_or_table_mentioned: bool = False
) -> list[TableMatch]:
    """Link ``claim`` against every table, with a sole-table fallback.

    If no table yields a metric column but the claim names a table ("as shown in
    Table 1") and the bundle holds exactly one table, that table is linked whole —
    the reference is unambiguous even though the locator is not.
    """
    matches: list[TableMatch] = []
    for table in tables:
        matches.extend(link_table(claim, table))
    if matches:
        return _dedupe(matches)
    if figure_or_table_mentioned and len(tables) == 1:
        return [
            TableMatch(
                table_id=tables[0].table_id,
                locator=None,
                method=MatchMethod.TABLE_MENTION,
            )
        ]
    return []


def _dedupe(matches: list[TableMatch]) -> list[TableMatch]:
    """Drop repeated ``(table_id, locator)`` pairs, preserving first-seen order."""
    seen: set[tuple[str, str | None]] = set()
    unique: list[TableMatch] = []
    for match in matches:
        key = (match.table_id, match.locator)
        if key not in seen:
            seen.add(key)
            unique.append(match)
    return unique


__all__ = [
    "TableMatch",
    "normalize_header",
    "header_matches_metric",
    "metric_column_indices",
    "label_column_index",
    "row_label",
    "claim_names_row",
    "link_table",
    "link_tables",
]
