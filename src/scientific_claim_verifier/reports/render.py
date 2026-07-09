"""Turning a run's traces into report files, and the home of ``claimverifier report``.

Milestone 9, and the last command ``docs/PLAN.md`` §10 advertises:

    claimverifier report --run results/runs/smoke_suite --out results/reports/

``--run`` takes a single ``*.trace.jsonl`` or a directory of them; ``--out`` takes a file
(for one trace) or a directory (for many), and its absence prints to stdout. A directory
run also gets an ``index`` linking every report and its trace.

Relative links, and why they matter
-----------------------------------
A report names its trace, and the name is resolved **relative to where the report is
written**. Reports written beside their traces link them as bare filenames, so the
directory can be copied, archived, or served without a broken link and without leaking
the absolute path of the machine that produced it. That also makes the output
byte-identical across output directories, exactly as ``summary.csv`` is (Milestone 8):
the one field that could carry a machine-specific path is the one field computed from the
caller's own arguments.

Exit codes
----------
``0`` when every requested report was rendered — including reports of ``contradicted``
claims, which are the tool working. ``1`` when a trace is missing, unreadable, malformed,
or written under an unreadable schema version, with the offending file named. A malformed
trace is a fact about the file, not a bug in the renderer, so it is reported rather than
raised.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import Document, IndexEntry, build_document, build_index_document
from .html import render_html
from .markdown import render_markdown
from .reader import (
    TRACE_SUFFIX,
    ReportError,
    ReportInput,
    discover_traces,
    order_of,
    read_report,
    read_summary,
)

#: The formats ``--format`` accepts. ``both`` writes two files per claim, and needs ``--out``.
MARKDOWN = "markdown"
HTML = "html"
BOTH = "both"
FORMATS = (MARKDOWN, HTML, BOTH)

#: File extension per format, and the stem of a directory run's index.
SUFFIXES = {MARKDOWN: ".md", HTML: ".html"}
INDEX_STEM = "index"

_RENDERERS = {MARKDOWN: render_markdown, HTML: render_html}


def formats_of(fmt: str) -> tuple[str, ...]:
    """The concrete formats a ``--format`` value asks for."""
    return (MARKDOWN, HTML) if fmt == BOTH else (fmt,)


def render(document: Document, fmt: str) -> str:
    """Render one document in one concrete format (never ``both``)."""
    return _RENDERERS[fmt](document)


def href(target: Path, *, relative_to: Path | None) -> str:
    """Link ``target`` from a document written into ``relative_to``.

    Uses a POSIX-style relative path so the link works in a browser and in a Markdown
    viewer on any platform. Without a destination directory (stdout), the path is given
    as the caller wrote it — there is nothing for it to be relative to.
    """
    if relative_to is None:
        return str(target)
    return Path(os.path.relpath(target, relative_to)).as_posix()


# ---------------------------------------------------------------------------
# Assembling a run
# ---------------------------------------------------------------------------


def trace_paths(run: Path) -> list[Path]:
    """The traces ``--run`` names: itself if a file, else every trace directly under it."""
    if run.is_file():
        return [run]
    if run.is_dir():
        return discover_traces(run)
    raise ReportError(f"{run}: no such trace or run directory")


def ordered(reports: list[ReportInput], run_dir: Path) -> list[ReportInput]:
    """Reports in the suite's declared order, then anything the summary did not name.

    A suite orders its tasks by evidence channel — text, table, dataset, code — so an
    index in that order reads as the pipeline does. Traces the summary does not mention
    (or every trace, when there is no summary) keep filename order, which is stable.
    """
    declared = order_of(run_dir, read_summary(run_dir))
    if not declared:
        return reports
    rank = {run_id: index for index, run_id in enumerate(declared)}
    return sorted(reports, key=lambda r: (rank.get(r.run_id, len(rank)), r.run_id))


def report_name(report: ReportInput, fmt: str) -> str:
    """A report's filename, taken from the run it describes rather than from its trace's."""
    return f"{report.run_id}{SUFFIXES[fmt]}"


def build_index(reports: list[ReportInput], run_dir: Path, out_dir: Path, fmt: str) -> Document:
    """The index over a directory of reports, linking each to its report and its trace."""
    entries = tuple(
        IndexEntry(
            report=report,
            report_href=report_name(report, fmt),
            trace_href=href(report.trace_path, relative_to=out_dir),
        )
        for report in reports
    )
    return build_index_document(
        entries, run_name=run_dir.name, summary=read_summary(run_dir)
    )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def write_reports(
    reports: list[ReportInput],
    out_dir: Path,
    *,
    run_dir: Path,
    fmt: str = MARKDOWN,
    index: bool = True,
) -> list[Path]:
    """Write one report per claim into ``out_dir``, plus an index. Returns the paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for concrete in formats_of(fmt):
        for report in reports:
            document = build_document(
                report, trace_href=href(report.trace_path, relative_to=out_dir)
            )
            path = out_dir / report_name(report, concrete)
            path.write_text(render(document, concrete), encoding="utf-8")
            written.append(path)
        if index:
            document = build_index(reports, run_dir, out_dir, concrete)
            path = out_dir / f"{INDEX_STEM}{SUFFIXES[concrete]}"
            path.write_text(render(document, concrete), encoding="utf-8")
            written.append(path)
    return written


def write_one(report: ReportInput, out: Path, fmt: str) -> Path:
    """Write a single claim's report to the file ``out``. Returns the path."""
    out.parent.mkdir(parents=True, exist_ok=True)
    document = build_document(report, trace_href=href(report.trace_path, relative_to=out.parent))
    out.write_text(render(document, fmt), encoding="utf-8")
    return out


def _format_for_file(out: Path, fmt: str) -> str:
    """The format a named output *file* implies, and the flag that must agree with it."""
    suffix = out.suffix.lower()
    implied = next((name for name, ext in SUFFIXES.items() if ext == suffix), None)
    if implied is None:
        raise ReportError(f"{out}: unknown report extension {suffix!r}; use .md or .html")
    if fmt != BOTH and fmt != implied:
        raise ReportError(f"{out}: --format {fmt} does not match extension {suffix!r}")
    if fmt == BOTH:
        raise ReportError("--format both writes two files; give --out a directory")
    return implied


def is_file_target(out: Path) -> bool:
    """True when ``--out`` names a report file rather than a directory to fill."""
    return out.suffix.lower() in set(SUFFIXES.values())


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------


def report_and_write(
    run: str | Path,
    out: str | Path | None = None,
    fmt: str = MARKDOWN,
    index: bool = True,
) -> int:
    """Render the reports ``--run`` names. Returns a process exit code."""
    run_path = Path(run)
    try:
        traces = trace_paths(run_path)
        if not traces:
            raise ReportError(f"{run_path}: no *{TRACE_SUFFIX} to report on")
        reports = [read_report(trace) for trace in traces]
    except ReportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    run_dir = run_path if run_path.is_dir() else run_path.parent
    reports = ordered(reports, run_dir)

    if out is None:
        if fmt == BOTH:
            print("error: --format both requires --out", file=sys.stderr)
            return 1
        for report in reports:
            document = build_document(report, trace_href=href(report.trace_path, relative_to=None))
            print(render(document, fmt))
        return 0

    out_path = Path(out)
    try:
        if is_file_target(out_path):
            if len(reports) != 1:
                raise ReportError(
                    f"{out_path}: --out names one file but --run has {len(reports)} traces; "
                    "give --out a directory"
                )
            written = [write_one(reports[0], out_path, _format_for_file(out_path, fmt))]
        else:
            written = write_reports(
                reports,
                out_path,
                run_dir=run_dir,
                fmt=fmt,
                index=index and run_path.is_dir(),
            )
    except (ReportError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for path in written:
        print(f"wrote {path}", file=sys.stderr)
    print(f"wrote {len(written)} file(s) for {len(reports)} claim(s) from {run_path}")
    return 0


def add_report_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``report`` flags. Shared by the CLI and ``scripts/04_generate_report.py``."""
    parser.add_argument(
        "--run",
        required=True,
        metavar="PATH",
        help=f"A run directory of *{TRACE_SUFFIX} files, or one such file.",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="A report file (.md/.html, one trace only) or a directory. Omit to print.",
    )
    parser.add_argument(
        "--format",
        choices=FORMATS,
        default=MARKDOWN,
        help=f"Report format (default: {MARKDOWN}). `both` requires --out DIR.",
    )
    parser.add_argument(
        "--no-index",
        action="store_true",
        help="Do not write an index over a run directory's reports.",
    )


def run_cli(argv: list[str]) -> int:
    """Parse ``report`` arguments and run. Shared by the CLI and the script."""
    parser = argparse.ArgumentParser(
        prog="claimverifier report",
        description="Render an auditable report for each claim in a run, from its trace alone.",
    )
    add_report_arguments(parser)
    args = parser.parse_args(argv)
    return report_and_write(args.run, out=args.out, fmt=args.format, index=not args.no_index)


def main(argv: list[str] | None = None) -> int:
    return run_cli(argv if argv is not None else sys.argv[1:])


__all__ = [
    "BOTH",
    "FORMATS",
    "HTML",
    "INDEX_STEM",
    "MARKDOWN",
    "SUFFIXES",
    "add_report_arguments",
    "build_index",
    "formats_of",
    "href",
    "is_file_target",
    "main",
    "ordered",
    "render",
    "report_and_write",
    "report_name",
    "run_cli",
    "trace_paths",
    "write_one",
    "write_reports",
]
