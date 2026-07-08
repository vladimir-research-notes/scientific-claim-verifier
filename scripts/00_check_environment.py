#!/usr/bin/env python3
"""Milestone 0 environment check.

Runnable directly (before any install) or via the console script:

    python3 scripts/00_check_environment.py
    claimverifier check-env

Reports the interpreter, platform, and library availability, and exits non-zero
if the environment cannot support the pipeline. Purely local and offline.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from a source checkout without an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from scientific_claim_verifier import envcheck  # noqa: E402  (path bootstrap above)

if __name__ == "__main__":
    raise SystemExit(envcheck.main())
