"""``claimverifier export`` — write one integration document, or describe the contracts.

Three modes, one verb:

.. code-block:: bash

    claimverifier export --list                       # the five formats and what they read
    claimverifier export --format benchmark --schema   # its JSON Schema, from the models
    claimverifier export --format episodes --run results/runs/smoke_suite --out ep.json

A request is validated against the registry *before* anything is built, so asking for a
run-based format without ``--run`` is an error with the flag named, not a traceback from
inside a builder. Omitting ``--out`` prints to stdout, which is what makes an export
pipeable.

Exit codes
----------
``0`` when the document was written. ``1`` when the request is impossible (unknown format,
missing ``--run``) or when the artifacts cannot support it — a run with no gold outcomes,
a run whose summary and traces disagree, a task that no longer loads. Each is a fact about
the inputs, reported with the command that would fix it, rather than raised.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..artifacts import loader
from ..reports.reader import ReportError
from . import FORMAT_NAMES, NEEDS_RUN, NEEDS_TASKS, REGISTRY, export_document, format_schema
from .envelope import IntegrationError, dumps, write
from .records import Controls, ExportContext

#: Where tasks are resolved from, relative to the repository root.
DEFAULT_TASKS_DIR = "tasks"

#: Everything a bad request or a bad artifact can raise on the way through.
EXPORT_ERRORS = (
    IntegrationError,
    ReportError,
    loader.TaskLoadError,
    loader.SuiteLoadError,
    OSError,
)


def render_formats() -> str:
    """The ``--list`` table: every format, its consumer role, and what it reads."""
    lines = [
        "scientific-claim-verifier — integration export formats",
        "=" * 53,
        "",
        "No external schema was consulted. These are proposed contracts shaped for the",
        "consumer role named, not adapters validated against those projects. See",
        "docs/INTEGRATIONS.md.",
        "",
    ]
    for spec in REGISTRY.values():
        needs = " + ".join(f"--{need}" for need in spec.needs)
        lines += [
            f"  {spec.name}  ({spec.format} v{spec.version})",
            f"    consumer : {spec.consumer}",
            f"    reads    : {needs}",
            f"    payload  : {spec.summary}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def context_for(args: argparse.Namespace, repo_root: Path) -> ExportContext:
    """Turn parsed flags into the context every builder is handed."""
    return ExportContext(
        repo_root=repo_root,
        run_dir=Path(args.run) if args.run else None,
        tasks_dir=Path(args.tasks) if args.tasks else repo_root / DEFAULT_TASKS_DIR,
        suite_path=Path(args.suite) if args.suite else None,
        hide_gold=args.hide_gold,
        controls=Controls(
            execute=not args.no_execute,
            use_declared_source=not args.no_declared_source,
            abs_tol=args.abs_tol,
            rel_tol=args.rel_tol,
        ),
    )


def check_request(name: str, args: argparse.Namespace) -> str | None:
    """The reason this request cannot be served, or ``None``. Checked before building."""
    spec = REGISTRY[name]
    if NEEDS_RUN in spec.needs and not args.run:
        return (
            f"--format {name} reads a run directory; pass --run DIR "
            "(produce one with `claimverifier run-suite --out results/runs/`)"
        )
    if NEEDS_TASKS not in spec.needs and args.suite:
        return f"--format {name} does not read a suite; --suite has no effect"
    return None


def export_and_write(
    name: str,
    ctx: ExportContext,
    out: str | Path | None = None,
) -> int:
    """Build one export and write it. Returns a process exit code."""
    try:
        envelope = export_document(name, ctx)
    except EXPORT_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if out is None:
        print(dumps(envelope), end="")
        return 0
    try:
        path = write(envelope, out)
    except OSError as exc:
        print(f"error: cannot write {out}: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {path} ({envelope.format} v{envelope.format_version})")
    return 0


def add_export_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``export`` flags. Shared by the CLI and ``scripts/07_export_integrations.py``.

    ``--list`` and ``--schema`` are served before any artifact is read, so a consumer can
    fetch a contract without owning a run.
    """
    parser.add_argument(
        "--format",
        choices=FORMAT_NAMES,
        default=None,
        metavar="NAME",
        help=f"The export format: {', '.join(FORMAT_NAMES)}.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print every format, its consumer role, and what it reads; then exit.",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Print the JSON Schema of --format's envelope and payload; then exit.",
    )
    parser.add_argument(
        "--run",
        metavar="DIR",
        default=None,
        help="A run directory of *.trace.jsonl files (and, for some formats, summary.json).",
    )
    parser.add_argument(
        "--tasks",
        metavar="DIR",
        default=None,
        help=f"Where task files live (default: {DEFAULT_TASKS_DIR}/ under the repository root).",
    )
    parser.add_argument(
        "--suite",
        metavar="PATH",
        default=None,
        help="Order and select tasks by a suite file (runnable-tasks only).",
    )
    parser.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="Write the document here. Omit to print it to stdout.",
    )
    parser.add_argument(
        "--hide-gold",
        action="store_true",
        help="Omit each task's gold outcome (runnable-tasks): never show it to a solver.",
    )
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="Declare that the run being described skipped its fixture scripts (episodes).",
    )
    parser.add_argument(
        "--no-declared-source",
        action="store_true",
        help="Declare that the run being described linked passages blind (episodes).",
    )
    parser.add_argument(
        "--abs-tol",
        type=float,
        default=None,
        metavar="F",
        help="Declare the absolute tolerance the run being described used (episodes).",
    )
    parser.add_argument(
        "--rel-tol",
        type=float,
        default=None,
        metavar="F",
        help="Declare the relative tolerance the run being described used (episodes).",
    )


def dispatch(args: argparse.Namespace) -> int:
    """Serve one parsed ``export`` request. Shared by ``claimverifier`` and the script."""
    if args.list:
        print(render_formats(), end="")
        return 0
    if args.format is None:
        print("error: --format is required (or use --list)", file=sys.stderr)
        return 1
    if args.schema:
        print(json.dumps(format_schema(args.format), indent=2, sort_keys=True))
        return 0

    problem = check_request(args.format, args)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1

    repo_root = loader.find_repo_root(Path.cwd())
    return export_and_write(args.format, context_for(args, repo_root), out=args.out)


def run_cli(argv: list[str]) -> int:
    """Parse ``export`` arguments and run. Shared by the CLI and the script."""
    parser = argparse.ArgumentParser(
        prog="claimverifier export",
        description="Export a run or a task set in one of the integration contracts (offline).",
    )
    add_export_arguments(parser)
    return dispatch(parser.parse_args(argv))


def main(argv: list[str] | None = None) -> int:
    return run_cli(argv if argv is not None else sys.argv[1:])


__all__ = [
    "DEFAULT_TASKS_DIR",
    "EXPORT_ERRORS",
    "add_export_arguments",
    "check_request",
    "context_for",
    "dispatch",
    "export_and_write",
    "main",
    "render_formats",
    "run_cli",
]
