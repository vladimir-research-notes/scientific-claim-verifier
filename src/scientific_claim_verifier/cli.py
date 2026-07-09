"""Command-line interface for scientific-claim-verifier.

Console script entry point: ``claimverifier`` (see ``pyproject.toml``).

Commands online so far:

- ``claimverifier check-env``          — offline environment self-check (M0).
- ``claimverifier version``            — print the package version (M0).
- ``claimverifier validate-fixtures``  — validate task fixtures (M2).
- ``claimverifier extract-claims``     — rule-based claim extraction (M3).
- ``claimverifier link-evidence``      — evidence linking (M4).
- ``claimverifier run-checks``         — deterministic verification checks (M5).

``link-evidence`` and ``run-checks`` are additions beyond the ``docs/PLAN.md``
section 10 contract: that section lists the end-to-end verbs, but a per-stage
command keeps each subsystem independently runnable and auditable. ``run-checks``
is not ``verify``: it computes checks and stops there. ``verify`` implies a support
label, which is inferred by scoring (M7), and it is registered in that milestone.

The remaining verification commands advertised in ``docs/PLAN.md`` section 10
(``verify``, ``run-suite``, ``report``) come online in their respective
milestones. They are deliberately not registered yet, so an unimplemented
command fails loudly rather than pretending to work.
"""

from __future__ import annotations

import argparse

from . import __version__, envcheck
from .artifacts import validation
from .checks import verification
from .claims import extraction, linking


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
            "`extract-claims`, `link-evidence`, `run-checks`; the remaining "
            "verification commands land in later milestones (see docs/PLAN.md)."
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
        help="Validate task fixtures under a directory (offline).",
    )
    validate.add_argument(
        "tasks_dir",
        nargs="?",
        default=validation.DEFAULT_TASKS_DIR,
        help=f"Directory of task files to validate (default: {validation.DEFAULT_TASKS_DIR}/).",
    )

    extract = subparsers.add_parser(
        "extract-claims",
        help="Run the rule-based claim extractor on a task (offline).",
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
        return extraction.extract_and_report(args.task, out_dir=args.out, as_json=args.json)
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

    # No subcommand: show help. Treated as success so `claimverifier` alone is
    # a friendly, non-error introduction.
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
