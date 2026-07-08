#!/usr/bin/env python3
"""Milestone 3 rule-based claim extraction.

Runnable directly (no install needed) or via the console script:

    python3 scripts/02_extract_claims.py --task <task.yaml> [--out DIR] [--json]
    claimverifier extract-claims --task <task.yaml> [--out DIR] [--json]

Loads a task, runs the transparent :class:`RuleBasedClaimExtractor` on its input
claim, prints the recovered structured fields (numbers, operator, metrics,
datasets, entities, conditions, units) plus the explicit artifact references and
which rules fired, and — because the task carries a gold extraction target —
shows a per-field comparison. Purely local and offline. Extraction is a
clearly-labelled heuristic; see ``docs/EXTRACTION.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from a source checkout without an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from scientific_claim_verifier.claims import extraction  # noqa: E402  (path bootstrap)

if __name__ == "__main__":
    raise SystemExit(extraction.main(sys.argv[1:]))
