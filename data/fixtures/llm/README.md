# LLM recordings — provenance

`extraction_recordings.json` holds the responses the
[`RecordedLLMAdapter`](../../../docs/ADAPTERS.md) replays.

**These responses are hand-authored. No language model produced them, and no API was
called to obtain them.** They are what a competent model *would* plausibly return, written
directly in the extractor's response schema. The model name they carry,
`recorded-fixture-v1`, is **fictitious** — naming a real vendor model in a committed
fixture would assert something false about where the bytes came from.

Because the responses are authored, any accuracy computed over them (currently 30/32
fields against gold; see [`docs/RESULTS.md`](../../../docs/RESULTS.md)) is a fact about
**this file and the replay/parse/score harness**, not a measurement of any model. One
recording (`dataset_mean`) is deliberately wrong in two fields so the number cannot be
mistaken for a perfect score that proves nothing.

## The file is derived, not maintained by hand

Every byte is generated from:

- the authored response strings in
  `src/scientific_claim_verifier/adapters/fixtures.py` (`AUTHORED_RESPONSES`), and
- the current prompt template in `src/scientific_claim_verifier/claims/llm_extraction.py`,
  against the current committed tasks.

Each recording is keyed by the request **fingerprint** (model, system, prompt, temperature,
max_tokens). If the prompt template or a task changes, every recording misses at once — so
the file is regenerated, not edited:

```bash
python3 scripts/06_record_llm_fixtures.py            # --check: fail if stale (CI runs this)
python3 scripts/06_record_llm_fixtures.py --write    # regenerate
```

`tests/test_adapters.py` runs the same check, so a stale file fails the build with an
instruction rather than surfacing later as an unexplained replay error.

## What is *not* here

Runtime paid-API responses (were any ever fetched) are cache artifacts, not fixtures: they
live under `results/cache/`, which `.gitignore` excludes. `CLAUDE.md` forbids committing
paid-API outputs. Only these free, synthetic, hand-authored recordings are committed.
