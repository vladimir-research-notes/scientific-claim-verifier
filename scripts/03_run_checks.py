#!/usr/bin/env python3
"""Milestone 5 deterministic verification checks.

Runnable directly (no install needed) or via the console script:

    python3 scripts/03_run_checks.py --task <task.yaml> [--out DIR] [--json]
    claimverifier run-checks         --task <task.yaml> [--out DIR] [--json]

Loads a task, extracts its claim (M3), links its evidence (M4), then runs every
check the evidence supports: the linked passage is tested for whether it actually
*asserts* the claim, table cells and columns are read back, dataset statistics are
recomputed from the committed CSV, and tiny fixture scripts are executed and their
printed metric compared to the claim.

No support label is produced here. Checks are evidence; the verdict is inferred
from them by scoring (Milestone 7). Purely local and offline; the only process this
starts is a trusted, committed fixture script. See ``docs/CHECKS.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from a source checkout without an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from scientific_claim_verifier.checks import verification  # noqa: E402  (path bootstrap)

if __name__ == "__main__":
    raise SystemExit(verification.main(sys.argv[1:]))
