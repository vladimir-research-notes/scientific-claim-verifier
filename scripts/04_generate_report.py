#!/usr/bin/env python3
"""Milestone 9 report generation.

Runnable directly (no install needed) or via the console script:

    python3 scripts/04_generate_report.py --run results/runs/smoke_suite --out results/reports/
    claimverifier report                  --run results/runs/smoke_suite --out results/reports/

Renders an auditable Markdown (optionally HTML) report for every claim in a run: the
extracted claim, the supporting text, each computed check, the inference and the named
rule behind it, what remains unverifiable, and a link to the JSONL trace.

The report is rendered from the trace and from nothing else — no task file is read, no
artifact re-opened, no check re-run — so a run archived months ago still reports. Purely
local and offline; this script starts no process and opens no socket. See
`docs/REPORTS.md`.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from a source checkout without an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from scientific_claim_verifier.reports import render  # noqa: E402  (path bootstrap)

if __name__ == "__main__":
    raise SystemExit(render.main(sys.argv[1:]))
