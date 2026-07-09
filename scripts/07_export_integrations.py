#!/usr/bin/env python3
"""Milestone 11 integration exports.

Runnable directly (no install needed) or via the console script:

    python3 scripts/07_export_integrations.py --list
    python3 scripts/07_export_integrations.py --format benchmark --run results/runs/smoke_suite
    claimverifier export                       --format benchmark --run results/runs/smoke_suite

Writes one of five versioned, self-describing documents — `runnable-tasks`,
`evidence-records`, `benchmark`, `metrics`, `episodes` — each derived from artifacts this
repository already produced (task files and JSONL traces). Nothing here re-runs the
pipeline, opens a socket, or depends on any of the systems the formats are shaped for; no
external schema was consulted. See `docs/INTEGRATIONS.md`.

Replay an exported `episodes` document with `claimverifier replay --episodes PATH`.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from a source checkout without an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from scientific_claim_verifier.integrations import export  # noqa: E402  (path bootstrap)

if __name__ == "__main__":
    raise SystemExit(export.main(sys.argv[1:]))
