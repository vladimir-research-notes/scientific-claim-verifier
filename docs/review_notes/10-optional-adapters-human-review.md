Human review: Milestone 10 — Optional adapters

TL;DR
An optional LLM-adapter layer, disabled by default and free by construction: mock, recorded,
and a paid-API stub with all five CLAUDE.md guards but no transport and no HTTP-client
dependency. Claim extraction can route through an adapter (`extract-claims --extractor
recorded|mock`) and is scored against the same gold as the rule-based baseline. 70 new
tests; 670 total; ruff clean; smoke gate unchanged (adapters are off the default path).

Provenance (please note)
This milestone was completed by the interactive Claude Code session, not the autonomous
milestone runner. The runner hit an account session limit partway through M10: it had
written the eight adapter modules, `llm_extraction.py`, `scripts/06_record_llm_fixtures.py`,
and the recordings JSON, but had not written tests, the `data/fixtures/llm/README.md` and
`docs/ADAPTERS.md` the code already referenced, the CLI wiring, the website/docs updates,
the milestone notes, or a commit. The interactive session reviewed the partial code, wrote
those missing pieces, and committed. No adapter module's logic was rewritten; the only edits
to the pre-written code were three ruff line-length fixes (`adapters/base.py:55`,
`claims/llm_extraction.py:298`).

What changed
- Added `src/scientific_claim_verifier/adapters/` (8 modules) and
  `claims/llm_extraction.py` (pre-written by the runner; reviewed here).
- Added `extract-claims --extractor {rule,recorded,mock}` (edits to `claims/extraction.py`
  and `cli.py` — the only committed-file changes made by this session).
- Added `tests/test_adapters.py`, `data/fixtures/llm/README.md`, `docs/ADAPTERS.md`, the
  `docs/RESULTS.md` M10 section, and website updates.

What should be checked later
- Whether an `adapters` inspection CLI verb (printing each adapter's `describe()` — the
  disabled/dry-run/guard posture) is worth adding; it is available programmatically but not
  surfaced on the CLI. Deliberately left out to keep the milestone focused.
- Whether `MatchMethod`-style typing should extend to the adapter provenance in
  `rules_fired` (currently free-text `llm:` lines), if a later stage needs to branch on it.
- The token estimator is a heuristic upper bound, not a tokenizer — confirm that framing is
  acceptable for any future real-provider integration (it bounds the next call, not the last).

Technical risks
- Low for the default path: no network, no paid API, no new runtime dependency; the adapter
  package is imported lazily and never constructed unless `--extractor` asks for it.
- The paid `ApiAdapterStub` is the only `spends_money` adapter; a test enumerates the
  registry to keep it that way, and the four gates each have a counting-transport test
  proving the transport is not reached. If a future change adds a transport or an HTTP
  dependency, `test_no_adapter_module_imports_an_http_client` and
  `test_pyproject_declares_no_http_client` should fail loudly.

Commands to verify
- `python3 -m pytest tests/test_adapters.py -q`
- `python3 scripts/06_record_llm_fixtures.py`
- `claimverifier extract-claims --task tasks/table_claims/accuracy_improvement.yaml --extractor recorded`
- `claimverifier extract-claims --task tasks/table_claims/contradicted_f1.yaml --extractor recorded`  # exit 1

Human feedback
<!-- Human will fill this later. -->
