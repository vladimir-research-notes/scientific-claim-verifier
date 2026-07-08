Human review: M3 — Rule-based claim extraction

TL;DR
Milestone 3 adds the `claims/` package: a transparent, deterministic, rule-based
extractor that populates a `ScientificClaim`'s typed fields (numeric values,
comparison operator, units, metrics, datasets, entities, conditions) from the
claim text plus its artifact bundle, and a deterministic `normalized_claim`
builder. Every populated field is traceable to a named rule via
`Extraction.rules_fired`. A per-field scorer compares the extraction to each
task's gold `expected.claim`. On the six committed fixtures, seven of eight scored
fields match on all six tasks; `conditions` matches on five of six — the miss is a
free-form semantic condition the extractor deliberately does not guess. 36 new
tests (102 total). No new dependencies. Extraction is labelled a heuristic
throughout; scored evidence linking remains M4.

What changed
- New package: src/scientific_claim_verifier/claims/ (extraction.py,
  normalization.py, __init__.py).
- CLI: `extract-claims <task> [--out DIR] [--json]` verb added to cli.py.
- Script: scripts/02_extract_claims.py.
- Tests: tests/test_extraction.py (36 tests).
- Docs: docs/EXTRACTION.md (new, rule-by-rule reference + limits),
  docs/RESULTS.md (new, measured results), docs/milestones + docs/commits notes.
- Website: site/index.html, site/milestones.html, site/claim-schema.html,
  site/results.html.

What should be checked later
- The units heuristic has a second branch with no textual evidence: a
  percentage-scale metric (accuracy/F1/precision/recall/AUC) whose value exceeds
  1 is labelled "%" even when no "%" sign is present. This is what makes
  `accuracy_improvement` (72.0 -> 78.0, no "%" in the text) come out as "%".
  Confirm that inferring units from a value's magnitude is acceptable, or whether
  units should be left `None` when the text does not state them.
- The `datasets`, `entities`, and `metrics` lexicons were authored against the six
  committed fixtures. Their `6/6` scores are therefore weak evidence. Confirm the
  lexicons belong in code at all (vs. a data file), and consider adding held-out
  fixtures the lexicons were *not* written against before trusting these numbers.
- `entities` is a `Method X` regex plus a two-word role lexicon
  (`baseline`, `model`). This is narrow by design. Confirm the intended long-term
  entity strategy (extend the lexicon? defer to the M10 LLM adapter behind the
  same interface?).
- `normalized_claim` is deliberately excluded from scoring; the extractor emits
  its own notation (`accuracy: 72 -> 78 (>) %`) that does not match gold's
  hand-authored form (`accuracy(A) > accuracy(baseline): 72.0 -> 78.0`). Confirm
  this is the right call, or whether gold `normalized_claim` should be dropped
  from the task format (currently it is authored but never used).
- The headline-value rule is "first numeric token that is not a sample count".
  With two non-count numbers in one claim it silently takes the first. No fixture
  exercises this. Confirm whether a multi-number claim should instead extract
  nothing and be scored `underspecified`.
- `detect_operator` returns `>` as the fallback for a `comparison_claim` with no
  `from…to` and no comparison verb. Confirm a direction-less comparison should
  default to `>` rather than `None`.
- Operator direction for `from X to Y` comes from the sign of `Y − X`, not the
  verb. "accuracy drops from 78 to 72" therefore yields `<` — correct here, but it
  means a claim whose verb and numbers disagree silently trusts the numbers.
- `extract_references` resolves `.py` mentions by basename only. Two code
  artifacts with the same basename in different directories would collide (the
  dict keeps the last). No fixture has this; confirm whether it should be an error.
- Reference resolution for datasets uses a substring match against
  `artifact_id + description`. `measurements` -> `ds_measurements` works, but a
  short dataset name could match an unrelated description. Confirm the matching
  rule.
- `conditions` currently only ever contains `n = N`. Confirm the M7 scorer's
  expectations for the `underspecified` label do not depend on richer conditions.
- The CLI uses `--task` to match the contract in docs/PLAN.md §10. Note that
  §10 (and, until this milestone, README.md) illustrates it with
  `tasks/table_claims/basic_accuracy_claim.yaml`, which does not exist — M2 named
  that fixture `accuracy_improvement.yaml`. README was corrected here; PLAN.md §10
  was left untouched (it is the runner's source of truth and its examples are
  illustrative). Confirm PLAN.md §10 should be corrected too.

Technical risks
- Low. Extraction is pure, deterministic, offline, stdlib-only (`re`), and touches
  no artifact files beyond what the M2 loader already reads. It executes nothing.
- The main risk is not correctness but **overfitting to six hand-authored
  fixtures**, which is called out in docs/EXTRACTION.md and docs/RESULTS.md rather
  than hidden. The reported per-field numbers should not be read as a benchmark.
- The extractor never mutates its input claim (test-pinned) and produces identical
  output and `rules_fired` across runs (test-pinned).
- `_NUMBER_RE`'s look-behind is load-bearing: it prevents `SST-2` from yielding the
  number 2. It is unit-tested, but a future edit to that regex could silently
  reintroduce spurious values.
- `--out` writes under `results/runs/`, which is gitignored; nothing generated is
  committed.

Commands to verify
- python3 -m pytest -q
- python3 -m pytest tests/test_extraction.py -q
- ruff check .
- python3 scripts/01_validate_fixtures.py
- python3 scripts/02_extract_claims.py --task tasks/table_claims/accuracy_improvement.yaml
- python3 scripts/02_extract_claims.py --task tasks/statistical_claims/dataset_mean.yaml --json
- claimverifier extract-claims --task tasks/ml_claims/synthetic_data_passage.yaml   (after `pip install -e .`)
- ./scripts/serve_site.sh   then load http://localhost:9002/claim-schema.html and results.html

Human feedback
<!-- Human will fill this later. -->
