#!/usr/bin/env python3
"""Milestone 10 — verify or regenerate the committed LLM recordings.

Runnable directly (no install needed):

    python3 scripts/06_record_llm_fixtures.py            # check the committed file
    python3 scripts/06_record_llm_fixtures.py --write    # rebuild it

``data/fixtures/llm/extraction_recordings.json`` is a derived artifact: its requests are
built from the current prompt template and the current task fixtures, and its responses
are the hand-authored strings in
:mod:`scientific_claim_verifier.adapters.fixtures`. **No API is called and nothing costs
money** — this script neither can nor does reach a network.

``--check`` (the default) regenerates the file in memory and compares bytes, so a prompt
edit that would make every committed recording miss fails here, with an instruction,
rather than surfacing later as an unexplained replay error. ``tests/test_adapters.py``
runs the same check, so the build enforces it.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from a source checkout without an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from scientific_claim_verifier.adapters import fixtures  # noqa: E402  (path bootstrap)

if __name__ == "__main__":
    raise SystemExit(fixtures.main(sys.argv[1:]))
