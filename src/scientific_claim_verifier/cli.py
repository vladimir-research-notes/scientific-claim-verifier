"""Command-line interface for scientific-claim-verifier.

Console script entry point: ``claimverifier`` (see ``pyproject.toml``).

Commands online so far:

- ``claimverifier check-env``          — offline environment self-check (M0).
- ``claimverifier version``            — print the package version (M0).
- ``claimverifier validate-fixtures``  — validate task fixtures (M2).

The remaining verification commands advertised in ``docs/PLAN.md`` section 10
(``extract-claims``, ``verify``, ``run-suite``, ``report``) come online in their
respective milestones. They are deliberately not registered yet, so an
unimplemented command fails loudly rather than pretending to work.
"""

from __future__ import annotations

import argparse

from . import __version__, envcheck
from .artifacts import validation


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for the ``claimverifier`` CLI."""
    parser = argparse.ArgumentParser(
        prog="claimverifier",
        description=(
            "Verify scientific claims against papers, datasets, code, and "
            "reproducibility evidence (CPU-only, offline)."
        ),
        epilog=(
            "Live commands: `check-env`, `version`, `validate-fixtures`; the "
            "remaining verification commands land in later milestones "
            "(see docs/PLAN.md)."
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

    # No subcommand: show help. Treated as success so `claimverifier` alone is
    # a friendly, non-error introduction.
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
