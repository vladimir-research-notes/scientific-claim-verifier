# Commit note — M3 Rule-based claim extraction

## Commit message

```
M3: rule-based claim extraction (transparent heuristic baseline)

Add the claims/ package, which populates a ScientificClaim's typed fields
from the claim text and its artifact bundle:
- claims/extraction.py: RuleBasedClaimExtractor + independently-testable
  sub-extractors (numbers that ignore identifier digits, from/to comparison,
  sample counts, metric lexicon, dataset/entity heuristics, operator
  precedence, units, explicit artifact references), the Extraction result
  with a rules_fired audit trail, and a per-field scorer vs. the gold claim
- claims/normalization.py: deterministic normalized_claim builder

Wire `claimverifier extract-claims --task X [--out DIR] [--json]` (flags per
the docs/PLAN.md section 10 contract) and scripts/02_extract_claims.py.
Add tests/test_extraction.py (36 new, 102 total): unit tests pin each rule on
crafted inputs; integration scores all six fixtures against gold. Comparison
verbs now match on word boundaries ("against" must not fire "gain",
"dropout" must not fire "drop") - found and fixed while testing.
Add docs/EXTRACTION.md (rule-by-rule reference + limits) and docs/RESULTS.md
(first measured results); update website (index, milestones, claim-schema,
results), README CLI section, and milestone/commit/review notes.

Extraction is a labelled heuristic: regexes + small closed lexicons, built
for auditability, not coverage. Rules are conservative and prefer an empty
field over a guess. On the six fixtures, 7 of 8 scored fields match on every
task; conditions matches on 5/6 - the miss is a free-form semantic condition
the extractor declines to guess, and a test pins that limitation.
normalized_claim is the extractor's own notation and is not scored against
gold. Scored evidence linking remains M4.
```

## What this commit adds

- A transparent extractor whose every populated field is traceable to a named
  rule, with the firing rules recorded for the trace and the report.
- Deterministic normalization into a canonical claim string.
- A per-field scorer against the gold `expected.claim` introduced in M2, plus the
  first measured results table in the repo (`docs/RESULTS.md`).
- `claimverifier extract-claims` and `scripts/02_extract_claims.py`, both offline.

## Deliberately excluded (per the operating principles)

- **Scored evidence linking.** The extractor records only references the claim
  text names explicitly, with no relevance score. Searching/ranking the bundle for
  supporting passages is M4; `evidence_links` is left empty.
- **Checks, sandbox execution, scoring, reports** — later milestones. M3 extracts
  fields; it verifies nothing.
- **Gold-matching `normalized_claim`.** Not scored — a rule-based system cannot be
  expected to reproduce hand-authored phrasing, and claiming otherwise would be
  overclaiming. The eight structured fields are what get scored.
- **Guessing semantic conditions.** The extractor recovers only sample-count
  conditions; the one gold semantic condition is knowingly missed, tested, and
  documented rather than special-cased.
- **New dependencies.** Pure stdlib `re` on top of the existing pydantic/PyYAML;
  numpy/pandas still arrive with M5.

## Verification performed at commit time

- `python3 -m pytest -q` → 102 passed (66 prior + 36 new).
- `ruff check .` → all checks passed.
- `python3 scripts/01_validate_fixtures.py` → 6 ok, 0 failed, 0 warnings (exit 0).
- `python3 scripts/00_check_environment.py` → exit 0 (`READY`).
- `python3 scripts/02_extract_claims.py` on the table, dataset, code, and
  underspecified tasks → text and JSON reports, exit 0; `--out` writes
  `<task_id>.extraction.json` under the gitignored `results/runs/`.
- Static site served locally on port 9002; pages fetched via Python's `urllib`
  (no `curl`/`wget`, per the permission policy).
- `git status` clean after commit.
