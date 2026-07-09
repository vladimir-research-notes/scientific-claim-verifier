# Milestone 10 — Optional adapters

## Summary

An optional LLM-adapter layer, **disabled by default and free by construction**. Three
adapters behind one interface let claim extraction route through a (mock or recorded) model
for comparison with the rule-based baseline, and specify a paid path complete with all five
guards `CLAUDE.md` requires — without integrating any paid provider. The default pipeline
never constructs an adapter.

## Deliverables

- `src/scientific_claim_verifier/adapters/` — `base.py` (the `LLMRequest`/`LLMResponse`/
  `TokenUsage` contract and fingerprint), `cost.py` (over-counting token estimator, model
  price table, hard `CostGuard`), `cache.py` (fingerprint-keyed response cache), `mock_llm.py`,
  `recorded_llm.py`, `api_stub.py` (four gates), `fixtures.py` (authored recordings + `--check`),
  and `__init__.py` (`build_adapter`, `registry`, `ADAPTER_NAMES`).
- `src/scientific_claim_verifier/claims/llm_extraction.py` — `LLMClaimExtractor`, the strict
  response schema, the deterministic prompt template (`PROMPT_VERSION`), and `strip_code_fence`.
- CLI: `claimverifier extract-claims --extractor {rule,recorded,mock} [--recordings PATH]`
  (`claims/extraction.py` gains `build_extractor` + the flags; `cli.py` wires them).
- `data/fixtures/llm/extraction_recordings.json` + `data/fixtures/llm/README.md` (provenance).
- `scripts/06_record_llm_fixtures.py` — check/regenerate the recordings.
- `tests/test_adapters.py` — 70 tests.
- `docs/ADAPTERS.md`; `docs/RESULTS.md` M10 section; website (`index`, `milestones`).

## Validation

- `python3 -m pytest -q` → **670 passed** (600 prior + 70 new).
- `ruff check .` → all checks passed (fixed three pre-existing long lines in the adapter code).
- `python3 scripts/06_record_llm_fixtures.py` → recordings current.
- `python3 scripts/01_validate_fixtures.py` → 12 ok / VALID (unchanged).
- `python3 scripts/05_run_smoke_suite.py` → gate PASS (unchanged; adapters are off the default path).
- `claimverifier extract-claims --extractor recorded|mock` on committed tasks → exit 0;
  `--extractor recorded` on a task with no recording → loud refusal, exit 1.

## Notes / decisions

- **Free by construction, not configuration.** The load-bearing safety property is that no
  HTTP client is declared in `pyproject.toml` or imported under `adapters/`; a test asserts
  it. The five guards (dry-run, cache, estimator, cost guard, opt-in) are real, but the
  transport being `None` is what makes a live call impossible without deliberate injection.
- **Exactly one paid adapter, shipped disabled.** `spends_money` is a class attribute so a
  test can enumerate the registry and prove it, rather than trusting a docstring.
- **The recorded 30/32 measures the harness, not a model.** Responses are hand-authored;
  `dataset_mean` is deliberately 6/8 so the number cannot pass for a benchmark. The mock
  returns an empty extraction on purpose.
- **Provenance completed by this session.** The interactive session finished this milestone
  after the autonomous runner hit an account session limit partway through M10 — it had
  written the adapter modules but no tests, docs, CLI wiring, or commit. See the review note.

## Status

Complete. Next: Milestone 11 — Integration contracts.
