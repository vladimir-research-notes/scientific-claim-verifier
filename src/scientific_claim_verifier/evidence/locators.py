"""The locator grammar: one place that writes evidence locators and reads them back.

An :class:`~scientific_claim_verifier.schemas.EvidenceLink` names *which* artifact
bears on a claim; its ``locator`` names *where inside it*. The evidence linker
(Milestone 4) writes locators; the checks (Milestone 5) parse them to read the
value back. Both go through this module so the two can never drift.

The grammar is a comma-separated list of ``key=value`` pairs, plus bare tokens for
positions that need no value::

    row=A,col=accuracy      a table cell
    col=accuracy            a whole table column
    column=value            a dataset column
    series=accuracy         a figure series
    stdout                  a script's standard output

Tables say ``col`` and datasets say ``column``: these are the conventions already
committed in the gold ``expected.evidence`` of the task fixtures, so they are kept
verbatim rather than harmonized.

**Limitation.** Values are not escaped, so a table row label containing ``,`` or
``=`` would produce an ambiguous locator. No fixture does; a schema that carried
the row/column as typed fields rather than a string would remove the hazard.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

# The bare token used when a check should read a script's standard output.
STDOUT = "stdout"


def table_cell(row: str, column: str) -> str:
    """Locator for one table cell: ``row=A,col=accuracy``."""
    return f"row={row},col={column}"


def table_column(column: str) -> str:
    """Locator for a whole table column: ``col=accuracy``."""
    return f"col={column}"


def dataset_column(column: str) -> str:
    """Locator for a dataset column: ``column=value``."""
    return f"column={column}"


def figure_series(name: str) -> str:
    """Locator for a figure's data series: ``series=accuracy``."""
    return f"series={name}"


@dataclass(frozen=True)
class Locator:
    """A parsed locator. ``parts`` maps each key to its value (``""`` for a bare token)."""

    raw: str
    parts: Mapping[str, str]

    @property
    def row(self) -> str | None:
        """The table row label, if the locator names one."""
        return self.parts.get("row")

    @property
    def col(self) -> str | None:
        """The table column header, if the locator names one."""
        return self.parts.get("col")

    @property
    def column(self) -> str | None:
        """The dataset column name, if the locator names one."""
        return self.parts.get("column")

    @property
    def series(self) -> str | None:
        """The figure series name, if the locator names one."""
        return self.parts.get("series")

    @property
    def is_stdout(self) -> bool:
        """True when the locator points at a script's standard output."""
        return STDOUT in self.parts

    @property
    def is_empty(self) -> bool:
        """True for a link with no locator — the artifact as a whole."""
        return not self.parts


def parse(raw: str | None) -> Locator:
    """Parse a locator string. ``None`` / ``""`` yields an empty locator.

    Unknown keys are preserved in ``parts`` rather than rejected: a check that does
    not understand a locator declines (``skipped``) instead of guessing.
    """
    if not raw:
        return Locator(raw="", parts=MappingProxyType({}))
    parts: dict[str, str] = {}
    for chunk in raw.split(","):
        token = chunk.strip()
        if not token:
            continue
        key, sep, value = token.partition("=")
        parts[key.strip()] = value.strip() if sep else ""
    return Locator(raw=raw, parts=MappingProxyType(parts))


__all__ = [
    "STDOUT",
    "Locator",
    "table_cell",
    "table_column",
    "dataset_column",
    "figure_series",
    "parse",
]
