"""Command-line interface for scientific-claim-verifier.

Console script entry point: ``claimverifier`` (see ``pyproject.toml``).

Commands online so far:

- ``claimverifier check-env``          — offline environment self-check (M0).
- ``claimverifier version``            — print the package version (M0).
- ``claimverifier validate-fixtures``  — validate task and suite fixtures (M2, M8).
- ``claimverifier extract-claims``     — claim extraction; ``--extractor rule`` (M3,
  default) or ``recorded``/``mock`` via an offline adapter (M10).
- ``claimverifier link-evidence``      — evidence linking (M4).
- ``claimverifier run-checks``         — deterministic verification checks (M5).
- ``claimverifier run-sandbox``        — controlled fixture execution + trace (M6).
- ``claimverifier verify``             — score a claim: support label + trace (M7).
- ``claimverifier run-suite``          — run the offline smoke suite, gated (M8).
- ``claimverifier report``             — render reports from a run's traces (M9).

``link-evidence``, ``run-checks``, and ``run-sandbox`` are additions beyond the
``docs/PLAN.md`` section 10 contract: that section lists the end-to-end verbs, but a
per-stage command keeps each subsystem independently runnable and auditable.
``run-checks`` is not ``verify``: it computes checks and stops there, while ``verify``
draws the inference the checks are forbidden to draw.

``report`` completes the section 10 contract. It reads the JSONL traces a ``verify`` or
``run-suite`` run left behind and renders them; it never re-runs the pipeline, so a report
can be produced from an archived run whose artifacts are long gone.
"""

from __future__ import annotations

import argparse

from . import __version__, envcheck, suite
from .artifacts import validation
from .checks import verification
from .claims import extraction, linking
from .reports import render
from .sandbox import runner
from .scoring import verdict


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for the ``claimverifier`` CLI."""
    parser = argparse.ArgumentParser(
        prog="claimverifier",
        description=(
            "Verify scientific claims against papers, datasets, code, and "
            "reproducibility evidence (CPU-only, offline)."
        ),
        epilog=(
            "Live commands: `check-env`, `version`, `validate-fixtures`, "
            "`extract-claims`, `link-evidence`, `run-checks`, `run-sandbox`, `verify`, "
            "`run-suite`, `report` (see docs/PLAN.md)."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"claimverifier {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    subparsers.add_parser(
        "check-env",
        help="Check the Python environment and library availability (offline).",
    )
    subparsers.add_parser(
        "version",
        help="Print the scientific-claim-verifier version and exit.",
    )

    validate = subparsers.add_parser(
        "validate-fixtures",
        help="Validate task and suite fixtures under a directory (offline).",
    )
    validate.add_argument(
        "tasks_dir",
        nargs="?",
        default=validation.DEFAULT_TASKS_DIR,
        help=f"Directory of task files to validate (default: {validation.DEFAULT_TASKS_DIR}/).",
    )

    extract = subparsers.add_parser(
        "extract-claims",
        help="Extract a task's claim (rule-based by default; --extractor recorded|mock, offline).",
    )
    extraction.add_extract_arguments(extract)

    link = subparsers.add_parser(
        "link-evidence",
        help="Link a task's claim to its supporting evidence (offline).",
    )
    linking.add_link_arguments(link)

    checks = subparsers.add_parser(
        "run-checks",
        help="Run the deterministic verification checks for a task (offline).",
    )
    verification.add_check_arguments(checks)

    sandbox = subparsers.add_parser(
        "run-sandbox",
        help="Execute a task's fixture scripts in the controlled sandbox (offline).",
    )
    runner.add_sandbox_arguments(sandbox)

    verify = subparsers.add_parser(
        "verify",
        help="Score a claim: support label, reproduction status, failure mode (offline).",
    )
    verdict.add_verify_arguments(verify)

    run_suite = subparsers.add_parser(
        "run-suite",
        help="Run the offline smoke suite end to end and gate on regressions.",
    )
    suite.add_suite_arguments(run_suite)

    report = subparsers.add_parser(
        "report",
        help="Render a Markdown (or HTML) report for each claim in a run, from its trace.",
    )
    render.add_report_arguments(report)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "check-env":
        return envcheck.run()
    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "validate-fixtures":
        return validation.run([args.tasks_dir])
    if args.command == "extract-claims":
        return extraction.extract_and_report(
            args.task,
            out_dir=args.out,
            as_json=args.json,
            extractor=args.extractor,
            recordings=args.recordings,
        )
    if args.command == "link-evidence":
        return linking.link_and_report(
            args.task,
            out_dir=args.out,
            as_json=args.json,
            use_declared_source=not args.no_declared_source,
        )
    if args.command == "run-checks":
        return verification.check_and_report(
            args.task,
            out_dir=args.out,
            as_json=args.json,
            use_declared_source=not args.no_declared_source,
            execute=not args.no_execute,
            abs_tol=args.abs_tol,
            rel_tol=args.rel_tol,
        )
    if args.command == "run-sandbox":
        return runner.sandbox_and_report(
            args.task,
            out_dir=args.out,
            as_json=args.json,
            code_id=args.code_id,
            timeout=args.timeout,
            allow_network=args.allow_network,
            with_timing=args.with_timing,
        )
    if args.command == "verify":
        return verdict.verify_and_report(
            args.task,
            out_dir=args.out,
            as_json=args.json,
            use_declared_source=not args.no_declared_source,
            execute=not args.no_execute,
            abs_tol=args.abs_tol,
            rel_tol=args.rel_tol,
        )
    if args.command == "run-suite":
        return suite.run_and_report(
            args.suite,
            out_dir=args.out,
            as_json=args.json,
            tasks_dir=args.tasks_dir,
            use_declared_source=not args.no_declared_source,
            execute=not args.no_execute,
            enforce_gate=not args.no_gate,
            abs_tol=args.abs_tol,
            rel_tol=args.rel_tol,
        )
    if args.command == "report":
        return render.report_and_write(
            args.run,
            out=args.out,
            fmt=args.format,
            index=not args.no_index,
        )

    # No subcommand: show help. Treated as success so `claimverifier` alone is
    # a friendly, non-error introduction.
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
