#!/usr/bin/env python3
"""Milestone 2 fixture validation.

Runnable directly (no install needed) or via the console script:

    python3 scripts/01_validate_fixtures.py [tasks_dir]
    claimverifier validate-fixtures [tasks_dir]

Validates every task under ``tasks/`` (default) against the Milestone 1 schema:
each task must parse, satisfy the schema, reference existing in-tree fixture
files, agree with its declared dataset shapes, and resolve every evidence link.
Exits non-zero if any task has an error. Purely local and offline. The milestone
runner invokes this as a between-milestone guard.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from a source checkout without an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from scientific_claim_verifier.artifacts import validation  # noqa: E402  (path bootstrap)

if __name__ == "__main__":
    raise SystemExit(validation.main(sys.argv[1:]))
