"""Rendering a :class:`~scientific_claim_verifier.reports.Document` as standalone HTML.

Milestone 9's *optional* format, per ``docs/PLAN.md`` §9. It walks the same
:class:`~scientific_claim_verifier.reports.Document`
:mod:`~scientific_claim_verifier.reports.markdown` walks and makes no content decision of
its own, so the two formats cannot disagree about what a run concluded.

The output is one self-contained file: no build step, no stylesheet to ship beside it, no
JavaScript, no network fetch. A report is an audit artefact that may be read years after
the run, from a directory someone copied off a machine, so it must not depend on anything
that directory does not contain.

Every string reaching the document goes through :func:`escape` — including hrefs, which
are report and trace filenames. Blocks carry plain text by construction (see the package
docstring), so escaping is total: there is no markup to preserve, and therefore nothing
that must be let through.
"""

from __future__ import annotations

from html import escape as _escape

from . import Block, Bullets, Cell, Code, Document, Link, Paragraph, Quote, Section, Table

#: Inline, deliberately small, and readable in a terminal browser. Kept close to the
#: project website's palette without depending on ``site/style.css``.
STYLE = """\
:root { color-scheme: light dark; }
body { margin: 2rem auto; max-width: 54rem; padding: 0 1rem;
       font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }
h1 { font-size: 1.6rem; margin-bottom: 0.2rem; }
h2 { font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #8884; padding-bottom: 0.2rem; }
.lede { font-size: 1.05rem; color: #555; }
@media (prefers-color-scheme: dark) { .lede { color: #aaa; } }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.92rem; }
th, td { border: 1px solid #8884; padding: 0.35rem 0.55rem; text-align: left;
         vertical-align: top; }
th { font-weight: 600; }
blockquote { margin: 1rem 0; padding: 0.4rem 0 0.4rem 1rem; border-left: 3px solid #8886;
             font-style: italic; }
pre { background: #8881; padding: 0.7rem; overflow-x: auto; border-radius: 4px; }
code, pre, td:first-child { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
li { margin: 0.35rem 0; }
footer { margin-top: 2.5rem; padding-top: 0.8rem; border-top: 1px solid #8884;
         font-size: 0.85rem; color: #666; }
"""


def escape(text: str) -> str:
    """HTML-escape ``text``, quotes included. Applied to every string in the document."""
    return _escape(text, quote=True)


def _link(link: Link) -> str:
    return f'<a href="{escape(link.href)}">{escape(link.label)}</a>'


def _cell(cell: Cell) -> str:
    return _link(cell) if isinstance(cell, Link) else escape(cell)


def _table(block: Table) -> str:
    head = "".join(f"<th>{escape(column)}</th>" for column in block.columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_cell(cell)}</td>" for cell in row) + "</tr>"
        for row in block.rows
    )
    return f"<table>\n<thead><tr>{head}</tr></thead>\n<tbody>{body}</tbody>\n</table>"


def _bullets(block: Bullets) -> str:
    """A multi-line item keeps its lines, joined by ``<br>`` rather than collapsed."""
    items = "".join(
        "<li>" + "<br>".join(escape(line) for line in item.split("\n")) + "</li>"
        for item in block.items
    )
    return f"<ul>{items}</ul>"


def _quote(block: Quote) -> str:
    lines = "<br>".join(escape(line) for line in block.text.split("\n"))
    return f"<blockquote>{lines}</blockquote>"


def render_block(block: Block) -> str:
    """Render one block as an HTML element."""
    if isinstance(block, Paragraph):
        return f"<p>{escape(block.text)}</p>"
    if isinstance(block, Quote):
        return _quote(block)
    if isinstance(block, Bullets):
        return _bullets(block)
    if isinstance(block, Table):
        return _table(block)
    if isinstance(block, Code):
        return f"<pre><code>{escape(block.text)}</code></pre>"
    if isinstance(block, Link):
        return f"<p>{_link(block)}</p>"
    raise TypeError(f"unrenderable block: {type(block).__name__}")


def render_section(section: Section) -> list[str]:
    """A section's heading (when it has one) followed by its blocks."""
    parts = [f"<h2>{escape(section.title)}</h2>"] if section.title else []
    return parts + [render_block(block) for block in section.blocks]


def render_html(document: Document) -> str:
    """Render a whole document as one standalone HTML file. Ends with one newline."""
    body = [f"<h1>{escape(document.title)}</h1>"]
    if document.lede:
        body.append(f'<p class="lede">{escape(document.lede)}</p>')
    for section in document.sections:
        body += render_section(section)
    body.append(f"<footer>{escape(document.footer)}</footer>")

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{escape(document.title)}</title>",
            f"<style>\n{STYLE}</style>",
            "</head>",
            "<body>",
            *body,
            "</body>",
            "</html>",
        ]
    ) + "\n"


__all__ = [
    "STYLE",
    "escape",
    "render_block",
    "render_html",
    "render_section",
]
