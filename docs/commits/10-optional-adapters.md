# Commit note — Milestone 10

**Commit message:** `M10: optional LLM adapters (disabled by default, free by construction)`

## What this commit adds

- `src/scientific_claim_verifier/adapters/` — the adapter contract (`base.py`), token
  estimator + price table + hard `CostGuard` (`cost.py`), fingerprint-keyed response cache
  (`cache.py`), and three adapters: `mock_llm.py`, `recorded_llm.py`, `api_stub.py` (four
  gates), plus `fixtures.py` and `__init__.py` (`build_adapter`, `registry`).
- `src/scientific_claim_verifier/claims/llm_extraction.py` — `LLMClaimExtractor` and the
  strict, deterministic prompt/response layer.
- CLI wiring: `extract-claims --extractor {rule,recorded,mock} [--recordings]`
  (`claims/extraction.py` + `cli.py`).
- `data/fixtures/llm/extraction_recordings.json` + `README.md`;
  `scripts/06_record_llm_fixtures.py`.
- `tests/test_adapters.py` (70 tests); `docs/ADAPTERS.md`; `docs/RESULTS.md` M10 section;
  website `index.html` and `milestones.html`; milestone/commit/review notes.

## Excluded (per operating principles)

No HTTP client dependency, no network transport, no paid-API outputs, no vendor prices, no
real model names. Runtime paid-API caches would live under `results/cache/` (gitignored);
only free, hand-authored synthetic recordings are committed.

## Verification at commit time

- `python3 -m pytest -q` → 670 passed.
- `ruff check .` → all checks passed.
- `python3 scripts/06_record_llm_fixtures.py` → recordings current.
- `python3 scripts/01_validate_fixtures.py` → VALID; `05_run_smoke_suite.py` → gate PASS.
- All 11 site pages fetched via `urllib` (200, balanced HTML).
