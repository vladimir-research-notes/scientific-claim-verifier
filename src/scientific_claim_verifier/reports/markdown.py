"""Rendering a :class:`~scientific_claim_verifier.reports.Document` as Markdown.

Milestone 9, and the default report format: Markdown renders in a terminal, in a diff, on
a code-review page, and in a browser, and it stays readable when none of those are
available. Nothing here decides *what* a report says — that is
:func:`~scientific_claim_verifier.reports.build_document`. This module only punctuates.

Escaping, and its honest limit
------------------------------
Table cells escape ``\\`` and ``|``, and collapse newlines, because an unescaped pipe
silently eats a column and a newline silently ends the table — both would make the
document say something false about the run. Prose blocks are **not** escaped: a claim
sentence is scientific text, and mangling ``p < 0.05`` into ``p \\< 0.05`` to defend
against a Markdown reading of ``<`` costs more than it buys. A claim containing ``*`` or
``_`` therefore renders with emphasis. That is a formatting artefact, not a correctness
one, and it is stated in ``docs/REPORTS.md`` rather than papered over.
"""

from __future__ import annotations

from . import Block, Bullets, Cell, Code, Document, Link, Paragraph, Quote, Section, Table

#: Fence for :class:`~scientific_claim_verifier.reports.Code` blocks.
FENCE = "```"


def escape_cell(text: str) -> str:
    """Make ``text`` safe inside a Markdown table cell, preserving what it says."""
    flat = " ".join(text.split())
    return flat.replace("\\", "\\\\").replace("|", "\\|")


def _link(link: Link) -> str:
    return f"[{link.label}]({link.href})"


def _cell(cell: Cell) -> str:
    return _link(cell) if isinstance(cell, Link) else escape_cell(cell)


def _table(block: Table) -> str:
    header = " | ".join(escape_cell(column) for column in block.columns)
    divider = " | ".join("---" for _ in block.columns)
    rows = [" | ".join(_cell(cell) for cell in row) for row in block.rows]
    return "\n".join([f"| {header} |", f"| {divider} |", *(f"| {row} |" for row in rows)])


def _bullets(block: Bullets) -> str:
    """One ``- `` per item; a multi-line item's continuations are indented to align."""
    items = []
    for item in block.items:
        head, *rest = item.split("\n")
        items.append("\n".join([f"- {head}", *(f"  {line}" for line in rest)]))
    return "\n".join(items)


def _quote(block: Quote) -> str:
    return "\n".join(f"> {line}" for line in block.text.split("\n"))


def render_block(block: Block) -> str:
    """Render one block. Blocks are separated by a blank line by :func:`render_markdown`."""
    if isinstance(block, Paragraph):
        return block.text
    if isinstance(block, Quote):
        return _quote(block)
    if isinstance(block, Bullets):
        return _bullets(block)
    if isinstance(block, Table):
        return _table(block)
    if isinstance(block, Code):
        return f"{FENCE}\n{block.text}\n{FENCE}"
    if isinstance(block, Link):
        return _link(block)
    raise TypeError(f"unrenderable block: {type(block).__name__}")


def render_section(section: Section) -> list[str]:
    """A section's heading (when it has one) followed by its blocks."""
    parts = [f"## {section.title}"] if section.title else []
    return parts + [render_block(block) for block in section.blocks]


def render_markdown(document: Document) -> str:
    """Render a whole document. Ends with exactly one newline."""
    parts = [f"# {document.title}"]
    if document.lede:
        parts.append(document.lede)
    for section in document.sections:
        parts += render_section(section)
    parts += ["---", document.footer]
    return "\n\n".join(parts) + "\n"


__all__ = [
    "FENCE",
    "escape_cell",
    "render_block",
    "render_markdown",
    "render_section",
]
