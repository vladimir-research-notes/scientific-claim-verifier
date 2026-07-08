# M3 — Rule-based claim extraction

## Summary

Introduces the `claims/` package: a transparent, deterministic extractor that
turns the claim *as authored* (id, text, type, provenance — nothing else) into a
**populated** `ScientificClaim` whose typed fields the verification checks (M5)
will consume: `expected_value`, `baseline_value`, `comparison_operator`, `units`,
`metrics`, `datasets`, `entities`, `conditions`, and a canonical
`normalized_claim`.

The extractor is regular expressions plus small closed lexicons. It is labelled a
heuristic everywhere it appears, and it is built for **auditability** rather than
coverage: every populated field is produced by a named rule, and the rules that
fired are recorded in `Extraction.rules_fired` so a reviewer can see exactly why a
value was extracted. The rules are conservative — they leave a field empty rather
than guess, because an empty field is scored `underspecified` downstream (honest)
while a confidently wrong field is not.

## Deliverables

- **`src/scientific_claim_verifier/claims/`** (new package):
  - `extraction.py` — `RuleBasedClaimExtractor` plus independently-testable
    sub-extractors (`extract_numbers`, `find_from_to`, `detect_count`,
    `extract_metrics`, `extract_datasets`, `extract_entities`, `detect_operator`,
    `extract_units`, `extract_references`), the `Extraction` result object, the
    per-field scorer (`score_extraction`, `aggregate_scores`), text/JSON
    rendering, and the shared CLI entry point.
  - `normalization.py` — the deterministic `normalized_claim` builder.
- **CLI:** `claimverifier extract-claims <task> [--out DIR] [--json]`.
- **Script:** `scripts/02_extract_claims.py` (runnable without an install).
- **Tests:** `tests/test_extraction.py` (36) — unit tests pinning each rule on
  crafted inputs, plus integration over all six committed fixtures scored against
  gold.
- **Docs:** `docs/EXTRACTION.md` (canonical rule-by-rule reference, with limits);
  `docs/RESULTS.md` (new — measured results, reproducible commands).
- **Website:** `index.html`, `milestones.html`, `claim-schema.html`,
  `results.html` updated.

## Design decisions

- **Conservative over clever.** Every rule prefers an empty field to a guess.
  `reaches` is deliberately not a comparison verb ("reaches 90% accuracy" asserts
  `=`, it does not compare); `"data"` alone does not trigger a dataset; a bare
  lowercase `"the method"` is not an entity.
- **Numbers must not come from names.** A look-behind refuses digits inside
  identifiers and hyphenated names, so the `2` in `SST-2`, the `10` in `CIFAR-10`,
  and the `2` in `eval2.py` are not values. Without this the comparison fixture
  would extract a spurious `2`.
- **Counts are not headline values.** An integer followed by a count noun
  ("12 samples") becomes the `count` metric and the condition `n = 12`, and is
  excluded from `expected_value` — so "12 samples with a mean of 3.4" extracts
  `3.4`, not `12`.
- **Operator precedence is explicit and typed.** `from X to Y` (direction from the
  sign of `Y − X`) → comparison verb → claim-type default (`~` for
  dataset/code-reproduction claims, since recomputation compares within tolerance;
  `=` for a plain numeric claim). Documented as a table in `docs/EXTRACTION.md`.
- **`normalized_claim` is not scored against gold.** It is the extractor's own
  canonical notation (`accuracy: 72 -> 78 (>) %`); a task's gold
  `normalized_claim` is a hand-authored human reference in a different notation.
  Scoring a rule-based system on reproducing arbitrary phrasing would be
  overclaiming, so the scorer covers the eight *structured* fields only.
- **Extraction ≠ linking.** The extractor records artifact references the claim
  text names *explicitly* (a `.py` basename resolved to a code artifact, a dataset
  name resolved to a dataset artifact, an unresolved "Table N" mention) and
  attaches **no score**. Searching the bundle for the best supporting passage,
  with a relevance score, is the evidence linker's job (M4); `evidence_links` is
  left empty here.
- **The extractor is pure.** It never mutates its input claim (a test pins this)
  and is deterministic (no wall clock, no RNG); a second run produces an identical
  claim and an identical `rules_fired` trace.
- **Set comparison for list fields.** `metrics`/`datasets`/`entities`/`conditions`
  are scored as sets — order carries no meaning. (Gold lists `[mean, count]` while
  text order gives `[count, mean]`.)

## Validation

Commands run (CPU-only, offline):

| Command | Result |
| --- | --- |
| `python3 -m pytest -q` | 102 passed (66 prior + 36 new) |
| `ruff check .` | All checks passed |
| `python3 scripts/01_validate_fixtures.py` | 6 ok, 0 failed, 0 warnings — VALID (exit 0) |
| `python3 scripts/00_check_environment.py` | exit 0 — `READY` |
| `python3 scripts/02_extract_claims.py <task>` | text/JSON report, exit 0 |

### Extraction vs. gold, over the six committed fixtures

| Field | Recovered | Channel |
| --- | --- | --- |
| `expected_value` | 6/6 | reliable |
| `baseline_value` | 6/6 | reliable |
| `comparison_operator` | 6/6 | reliable |
| `units` | 6/6 | reliable |
| `metrics` | 6/6 | reliable |
| `datasets` | 6/6 | best effort |
| `entities` | 6/6 | best effort |
| `conditions` | **5/6** | best effort |

**These six fixtures are a sanity check, not a benchmark.** They are hand-authored
and the lexicons were chosen with them in view. The `5/6` on `conditions` is the
most informative figure: the miss is `synthetic_data_passage`, whose gold
condition `"synthetic data only"` is a semantic paraphrase of "trained only on
synthetic data". The extractor recovers only sample-count conditions and returns
`[]` rather than guessing — a test asserts precisely this, so the limitation is
pinned rather than papered over.

The new tests also pin: number parsing that ignores identifier digits; the
`from…to` shape; count detection; metric-lexicon hits, ordering, and word
boundaries; conservative dataset/entity heuristics; the full operator precedence
table; both units branches; code-file and table-mention reference resolution; the
three `normalized_claim` shapes; extractor purity and determinism; and all four
CLI paths (text, JSON, `--out`, missing-task error).

One bug was found and fixed while writing those tests: the comparison verbs were
originally matched as **substrings**, so `"against"` contains `"gain"` (a false
`>`) and `"dropout"` contains `"drop"` (a false `<`). Verbs are now enumerated with
their inflections and matched on word boundaries, with a regression test for both
cases.

## Status

**Complete.** Next: **M4 — Evidence linker** (exact passage lookup, a
keyword-overlap baseline, table and dataset ID matching, and scored provenance
records linking each claim to the exact evidence that supports it).
