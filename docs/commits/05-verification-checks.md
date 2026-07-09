# Commit note — M5 Verification checks

## Commit message

```
M5: deterministic verification checks (evidence, table, statistic, execution)

Add the checks/ package, which turns an extracted claim plus its evidence links
into computed facts about the artifacts they point at:
- checks/__init__.py: Tolerance derived from the claim's REPORTED PRECISION,
  compare(), operator_holds(), stable float rounding, the check_id scheme
- checks/consistency.py: evidence_presence (five assertion levels) and comparison
- checks/table_recompute.py: cell/column lookup plus the ambiguity signal
- checks/statistical.py: stdlib CSV statistic recomputation, numeric_tolerance
- checks/code_execution.py: the ScriptRunner protocol + an interim subprocess
  runner, stdout observable parsing
- checks/verification.py: dispatch, ordering, rendering, JSON, CLI

Extract evidence/locators.py so the linker writes and the checks read one locator
grammar. Add CheckStatus.INCONCLUSIVE (SCHEMA_VERSION 1.0 -> 1.1, additive), the
loader's read_csv_rows/read_csv_column, and an optional per-task tolerance block.
Wire `claimverifier run-checks` and scripts/03_run_checks.py. Add a contradicted_f1
fixture, tests/test_checks.py (112 new, 285 total), and docs/CHECKS.md; update
RESULTS, CLAIM_SCHEMA, ARTIFACT_FORMAT, EXTRACTION, EVIDENCE_LINKING, README,
website (index, checks, claim-schema, reproducibility, results, milestones,
limitations), and milestone/commit/review notes.

A check produces evidence; it does not decide the claim's fate. The new
contradicted_f1 fixture proves it: the paper's abstract asserts "F1 91.0" verbatim
so evidence_presence PASSES, while its own table reports 86.0 so table_value FAILS.
Both are true, and collapsing them would destroy the only interesting fact about
the claim. A check that cannot decide says `inconclusive` rather than `fail` -
on synthetic_data_passage a bag-of-words rule cannot confirm the paraphrase
("trained only" vs "no real corpora ... at any stage of training"), so it reports
40% coverage and refuses the verdict rather than manufacturing a contradiction out
of its own ignorance. Tolerance is read off the claim: "3.4" admits anything that
rounds to 3.4 (+-0.05), so no threshold was tuned to make a fixture pass.

18 checks over 7 fixtures: 16 pass, 1 fail, 1 inconclusive. No support label is
assigned here - that inference is M7.
```

## What this commit adds

- Six deterministic checks, each reading one artifact kind through the locator the
  linker attached, and each recording the tolerance it applied beside the signed
  difference.
- A fourth negative outcome, `inconclusive`, so a transparent method's ignorance is
  never laundered into a claim about the artifacts.
- A tolerance policy with no magic numbers: the threshold is half the last decimal
  place of the claim's own number, overridable per task and per run.
- `evidence/locators.py`: one module that formats and parses locators, so M4 and M5
  cannot drift.
- `contradicted_f1`, the fixture that exhibits the project's thesis — supporting text
  and computed check disagreeing, and the report keeping both.
- `claimverifier run-checks`, offline, with `--no-execute` for environments where
  child processes are unwanted, and `--abs-tol` / `--rel-tol` to interrogate a
  verdict's sensitivity.

## Deliberately excluded (per the operating principles)

- **A support label.** No check, and no combination of checks, emits `supported` or
  `contradicted` here. The report says so in its own output. Scoring is M7.
- **A hardened sandbox.** `SubprocessScriptRunner` is a bare child process with a
  timeout: no temp dir, no env scrubbing, no filesystem or network restriction, and
  **no security boundary**. It is documented as such in the module, in
  `docs/CHECKS.md`, and on the website — where the Limitations page's prior claim of
  "in a temp dir" was corrected rather than left flattering. M6 replaces the
  implementation behind the same `ScriptRunner` protocol.
- **`figure_recompute` and `correlation`.** Neither is in the M5 contract, neither
  has a fixture, and correlation needs a two-column locator the grammar does not
  express. Named as untouched work; the website's check table marks them
  *not implemented* rather than listing a module that does not exist.
- **Smarter evidence checking.** No stemming, no embeddings, no synonymy. The
  `inconclusive` on `synthetic_data_passage` is the measured cost, reported rather
  than hidden.
- **Guessing.** A dataset link with no column locator is `skipped`, not a guess at
  the first column. A script printing several rival metric lines yields no parsed
  value. A claim with no number does not get a comparison invented for it.
- **Timing in the check record.** Wall-clock duration is non-deterministic; it
  belongs in M6's trace, not in a byte-reproducible check.
- **New dependencies.** `statistics`, `subprocess`, `csv`, `re` from the stdlib.
  numpy/pandas still unneeded.

## Verification performed at commit time

- `python3 -m pytest -q` → 285 passed (171 prior + 114 new).
- `ruff check .` → all checks passed.
- `python3 scripts/01_validate_fixtures.py` → 7 ok, 0 failed, 0 warnings (exit 0).
- `python3 scripts/00_check_environment.py` → exit 0 (`READY`).
- `claimverifier run-checks` on all seven tasks → 18 checks (16 pass, 1 fail,
  1 inconclusive), exit 0; `--out` writes `<task_id>.checks.json` under the
  gitignored `results/runs/`.
- `python3 scripts/03_run_checks.py --task <task>` → runs without an editable
  install (test-pinned as a subprocess).
- `claimverifier extract-claims` / `link-evidence` re-run after the locator refactor
  and the seventh fixture → 8/8 scored fields per task, 14/14 gold links, 0 spurious.
- Static site served locally on port 9002; all 11 pages fetched via Python's
  `urllib` (no `curl`/`wget`, per the permission policy), HTML tag balance and
  internal links checked.
- `git status` clean after commit.
