#!/usr/bin/env python3
"""Milestone 13 final check: the definition of done, executed.

Runnable directly (no install needed) or via the console script:

    python3 scripts/08_final_check.py
    claimverifier final-check

Runs every condition `docs/PLAN.md` §11 places on a finished repository, and every rule
`CLAUDE.md` places on a committed one, then exits 0 only if all of them hold **and** all
of them ran. `--no-subprocess` skips the two checks that shell out (`pytest`, `ruff`);
the run is then reported INCOMPLETE and exits non-zero, because a partial gate that
printed PASS would be worse than no gate at all.

The gate reads the repository and writes nothing into it: the suite it runs lands in a
temporary directory, along with the reports it renders from those traces. Purely local
and offline; the only processes it starts are `git`, `ruff`, `pytest`, and the three
trusted, committed fixture scripts. See `docs/FINAL_CHECK.md`.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from a source checkout without an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from scientific_claim_verifier import final_check  # noqa: E402  (path bootstrap)

if __name__ == "__main__":
    raise SystemExit(final_check.main(sys.argv[1:]))
