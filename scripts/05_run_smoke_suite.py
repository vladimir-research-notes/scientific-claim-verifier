#!/usr/bin/env python3
"""Milestone 8 offline smoke suite.

Runnable directly (no install needed) or via the console script:

    python3 scripts/05_run_smoke_suite.py --out results/runs/
    claimverifier run-suite            --out results/runs/

Runs every task named by `tasks/smoke_suite.yaml` through the whole pipeline —
extraction, evidence linking, deterministic checks, sandboxed fixture execution, and
scoring — then writes a JSONL trace and a result JSON per task plus `summary.csv`,
`summary.json`, and `summary.txt` into `<out>/<suite_id>/`.

The suite is a **gate**: it exits 1 if any claim receives a committal support label its
own fixture's gold outcome contradicts, or if the set of claims the pipeline declines to
decide has changed. It exits 0 on a suite full of `contradicted` claims — finding a
contradiction is the tool working, not failing. Pass `--no-gate` to report regressions
without failing.

Purely local and offline; the only processes it starts are trusted, committed fixture
scripts. See `docs/RESULTS.md`.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from a source checkout without an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from scientific_claim_verifier import suite  # noqa: E402  (path bootstrap)

if __name__ == "__main__":
    raise SystemExit(suite.main(sys.argv[1:]))
