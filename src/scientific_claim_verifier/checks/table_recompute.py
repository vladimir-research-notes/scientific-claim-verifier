"""The table-value check: read the cell (or column) a claim points at, and compare.

Given a table :class:`~scientific_claim_verifier.schemas.EvidenceLink` and the
locator the linker (Milestone 4) attached to it, this check reads the value back
**from the bundle** and compares it to the claim's number within the claim's own
reported precision.

Two locator shapes, two questions
---------------------------------
``row=A,col=accuracy`` — the claim named the row, so there is one cell to check:
*does that cell hold the claimed value?*

``col=accuracy`` — the claim named no row, so the question weakens to: *does the
claimed value appear anywhere in this column?* A hit is a ``pass``; the rows it
matched, and how many rows the column has, are recorded in ``inputs`` so scoring
(Milestone 7) can see that the claim is **ambiguous over the column** and label it
``underspecified`` rather than ``supported``. A miss is a ``fail`` — the artifacts
disagree with the claim — and the nearest cell is recorded so the report can say
*how far off* the claim was.

Why re-read a cell the linker already matched
---------------------------------------------
The linker only emits a cell locator once the cell's value matched a claim value,
so a cell check will usually pass. It is not a tautology: the check reads the
table itself rather than trusting the linker's memo, so the number that reaches
the report is derived from the artifact, and a hand-written or third-party locator
is checked rather than believed. The column path is where contradictions surface,
and it is not pre-filtered at all.

Recomputing a summary table *from a dataset* (task family 3) is not this check; see
``docs/CHECKS.md`` for what is and is not implemented.
"""

from __future__ import annotations

from ..evidence import locators
from ..evidence.tables import label_column_index, normalize_header, row_label
from ..schemas import (
    CellValue,
    CheckStatus,
    CheckType,
    EvidenceLink,
    ScientificClaim,
    Table,
    VerificationCheck,
)
from . import Tolerance, compare, resolve_tolerance, stable

_CHECK_TYPE = CheckType.TABLE_VALUE


def column_index(table: Table, header: str) -> int | None:
    """Index of the column called ``header``, matched exactly then normalized."""
    if header in table.columns:
        return table.columns.index(header)
    wanted = normalize_header(header)
    for index, column in enumerate(table.columns):
        if normalize_header(column) == wanted:
            return index
    return None


def row_index(table: Table, label: str) -> int | None:
    """Index of the row whose label column holds ``label`` (case-insensitively)."""
    label_index = label_column_index(table)
    if label_index is None:
        return None
    wanted = label.strip().lower()
    for index in range(len(table.rows)):
        found = row_label(table, index, label_index)
        if found is not None and found.lower() == wanted:
            return index
    return None


def cell_at(table: Table, row: int, column: int) -> CellValue:
    """The cell at ``(row, column)``, or ``None`` if the row is too short."""
    cells = table.rows[row]
    return cells[column] if column < len(cells) else None


def _as_number(cell: CellValue) -> float | None:
    """``float`` for a numeric cell, ``None`` otherwise. Booleans are not measurements."""
    if isinstance(cell, bool) or not isinstance(cell, int | float):
        return None
    return float(cell)


def numeric_column(table: Table, column: int) -> list[tuple[str, float]]:
    """The numeric cells of a column as ``(row_label, value)``, top to bottom.

    Rows whose cell is absent or non-numeric are dropped. A row with no label is
    keyed by its position (``#3``) so every value stays addressable.
    """
    label_index = label_column_index(table)
    values: list[tuple[str, float]] = []
    for index in range(len(table.rows)):
        number = _as_number(cell_at(table, index, column))
        if number is None:
            continue
        label = row_label(table, index, label_index) or f"#{index}"
        values.append((label, number))
    return values


def _claim_values(claim: ScientificClaim) -> list[tuple[str, float]]:
    """The claim's numeric fields, as ``(field_name, value)``, most salient first."""
    pairs = (("expected_value", claim.expected_value), ("baseline_value", claim.baseline_value))
    return [(name, value) for name, value in pairs if value is not None]


def _check(
    check_id: str,
    claim: ScientificClaim,
    status: CheckStatus,
    link: EvidenceLink,
    inputs: dict,
    notes: str,
    **fields: object,
) -> VerificationCheck:
    return VerificationCheck(
        check_id=check_id,
        check_type=_CHECK_TYPE,
        claim_id=claim.claim_id,
        status=status,
        inputs=inputs,
        evidence=[link],
        notes=notes,
        **fields,  # type: ignore[arg-type]
    )


def table_value_check(
    check_id: str,
    claim: ScientificClaim,
    table: Table,
    link: EvidenceLink,
    override: Tolerance | None = None,
) -> VerificationCheck:
    """Check ``claim``'s number against the cell or column ``link`` locates in ``table``."""
    locator = locators.parse(link.locator)
    inputs: dict = {"table_id": table.table_id, "locator": link.locator}

    if locator.col is None:
        return _check(
            check_id,
            claim,
            CheckStatus.SKIPPED,
            link,
            inputs,
            "table linked without a column locator; there is no value to read",
        )

    index = column_index(table, locator.col)
    if index is None:
        return _check(
            check_id,
            claim,
            CheckStatus.ERROR,
            link,
            inputs,
            f"column {locator.col!r} is not in table {table.table_id!r}",
        )

    claimed = _claim_values(claim)
    if not claimed:
        return _check(
            check_id,
            claim,
            CheckStatus.SKIPPED,
            link,
            inputs,
            "claim carries no numeric value to compare against the table",
        )

    if locator.row is not None:
        return _cell_check(check_id, claim, table, link, locator.row, locator.col, index, override)
    return _column_check(check_id, claim, table, link, locator.col, index, override)


def _cell_check(
    check_id: str,
    claim: ScientificClaim,
    table: Table,
    link: EvidenceLink,
    row: str,
    column: str,
    index: int,
    override: Tolerance | None,
) -> VerificationCheck:
    """The claim named the row: compare that one cell to the claim value it stands for."""
    inputs: dict = {
        "table_id": table.table_id,
        "locator": link.locator,
        "row": row,
        "column": column,
    }

    position = row_index(table, row)
    if position is None:
        return _check(
            check_id, claim, CheckStatus.ERROR, link, inputs, f"row {row!r} is not in the table"
        )

    cell = _as_number(cell_at(table, position, index))
    if cell is None:
        return _check(
            check_id,
            claim,
            CheckStatus.ERROR,
            link,
            inputs,
            f"cell row={row},col={column} is absent or not numeric",
        )

    # A comparison claim carries two numbers ("from 72.0 to 78.0"); the cell stands
    # for whichever it is nearer. Which one is recorded, so the pairing is auditable.
    field, expected = min(_claim_values(claim), key=lambda pair: abs(cell - pair[1]))
    result = compare(cell, expected, resolve_tolerance(claim, expected, override=override))
    inputs["claim_field"] = field
    return _check(
        check_id,
        claim,
        CheckStatus.PASS if result.within else CheckStatus.FAIL,
        link,
        inputs,
        f"cell row={row},col={column} = {result.computed:g}; "
        f"claim {field} = {result.expected:g}; "
        f"|difference| = {abs(result.difference):g} "
        f"{'<=' if result.within else '>'} tolerance {result.threshold:g}",
        computed_value=result.computed,
        expected_value=result.expected,
        tolerance=result.threshold,
        difference=result.difference,
    )


def _column_check(
    check_id: str,
    claim: ScientificClaim,
    table: Table,
    link: EvidenceLink,
    column: str,
    index: int,
    override: Tolerance | None,
) -> VerificationCheck:
    """The claim named no row: ask only whether its value appears in the column."""
    values = numeric_column(table, index)
    inputs: dict = {
        "table_id": table.table_id,
        "locator": link.locator,
        "column": column,
        "row_named": False,
        "n_rows": len(values),
        "column_values": {label: stable(value) for label, value in values},
    }

    if not values:
        return _check(
            check_id,
            claim,
            CheckStatus.ERROR,
            link,
            inputs,
            f"column {column!r} holds no numeric cells",
        )

    expected = claim.expected_value
    if expected is None:
        return _check(
            check_id,
            claim,
            CheckStatus.SKIPPED,
            link,
            inputs,
            "claim carries no expected value to look for in the column",
        )

    tolerance = resolve_tolerance(claim, expected, override=override)
    threshold = tolerance.threshold(expected)
    matching = [label for label, value in values if abs(value - expected) <= threshold]
    inputs["matching_rows"] = matching

    if matching:
        # The value IS present. Whether the claim is *supported* depends on whether
        # the row it silently refers to is determined; that inference is M7's, and
        # `matching_rows` / `n_rows` are the signal it reads.
        value = next(v for label, v in values if label == matching[0])
        result = compare(value, expected, tolerance)
        ambiguity = (
            f"; claim names no row, so it is ambiguous over {len(values)} rows"
            if len(values) > 1
            else ""
        )
        return _check(
            check_id,
            claim,
            CheckStatus.PASS,
            link,
            inputs,
            f"claimed {result.expected:g} found in column {column!r} at "
            f"row(s) {', '.join(matching)}{ambiguity}",
            computed_value=result.computed,
            expected_value=result.expected,
            tolerance=result.threshold,
            difference=result.difference,
        )

    nearest_label, nearest = min(values, key=lambda pair: abs(pair[1] - expected))
    result = compare(nearest, expected, tolerance)
    inputs["nearest_row"] = nearest_label
    return _check(
        check_id,
        claim,
        CheckStatus.FAIL,
        link,
        inputs,
        f"claimed {result.expected:g} is absent from column {column!r} "
        f"(nearest {result.computed:g} at row {nearest_label}; "
        f"|difference| = {abs(result.difference):g} > tolerance {result.threshold:g})",
        computed_value=result.computed,
        expected_value=result.expected,
        tolerance=result.threshold,
        difference=result.difference,
    )


__all__ = [
    "column_index",
    "row_index",
    "cell_at",
    "numeric_column",
    "table_value_check",
]
