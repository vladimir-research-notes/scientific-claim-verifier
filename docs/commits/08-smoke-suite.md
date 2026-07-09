# Commit note — M8 Smoke suite

## Commit message

```
M8: offline smoke suite (11 tasks, gated on wrong verdicts, not on accuracy)

Add tasks/smoke_suite.yaml, src/scientific_claim_verifier/suite.py, and
`claimverifier run-suite`: eleven claim-verification tasks driven end to end --
extraction, evidence linking, deterministic checks, sandboxed fixture execution,
scoring -- on a CPU, offline, in ~1.5s. Writes a JSONL trace and a result JSON per
task plus summary.csv, summary.json, and summary.txt to <out>/<suite_id>/.

THE SUITE IS A GATE, AND THE GATE IS ASYMMETRIC. Any wrong verdict -- a committal
support label the task's gold outcome disagrees with -- fails the run. A conservative
miss -- predicting unverifiable_from_artifacts where gold commits -- fails the run only
if the SET of them changed: a new one is a regression, a fixed one must be removed from
the suite file. This is M7's wrong_verdicts / conservative_misses split given teeth. A
change that raises label accuracy by turning a claim the pipeline honestly declined to
decide into one it decides WRONGLY has made the tool worse, and a single accuracy number
would have called it an improvement.

The suite file CANNOT declare a wrong verdict. SuiteExpectation has exactly one field
(conservative_misses); extra="forbid" rejects a wrong_verdicts key, and a test pins it.
The harness cannot be weakened by editing YAML.

Grow the fixture set from 7 tasks to 11. The original seven never produced
partially_supported, approximately_reproduced, failed_numeric_mismatch,
failed_environment, statistic_mismatch, passage_does_not_assert, or execution_error --
seven vocabulary values with no task behind them, one of which (approximately_reproduced)
the M7 review named as unexercised end to end. Four new fixtures, authored AFTER the M7
rule table was frozen, reach them:
- statistical_claims/dataset_std: pstdev 1.1298967 vs a claim of 1.1, inside the +/-0.05
  its one decimal place admits but not on it -> approximately_reproduced
- statistical_claims/dataset_mean_overstated: contradiction via RECOMPUTATION
  (failed_numeric_mismatch / statistic_mismatch), where contradicted_f1 reaches it via a
  table cell
- code_reproduction/unreproducible_accuracy: a script whose predictions.csv was never
  released -> partially_supported / failed_environment / execution_error. A script that
  will not run refutes nothing; numeric_tolerance is SKIPPED, not FAIL, because no number
  disagreed -- no number exists.
- ml_claims/negated_training_data: contradiction via POLARITY (passage_does_not_assert)
Each landed on its hand-written gold outcome on the first run, with no change to the
extractor, the linker, the checks, or the rule tables. All five CheckStatus values now
fire on a real task.

Add data/fixtures/code/reproduce_from_predictions.py: the only fixture that fails on
purpose -- a complete, working script whose input the paper never shipped, the most
ordinary reproducibility failure there is. Exits 1 with one stable stderr line rather
than a traceback, so the record does not drift with the interpreter version.

Suites are told apart from tasks BY CONTENT, not by filename: a document with a
top-level suite_id is a suite. A file that does not PARSE is classified as a task, so
validate-fixtures reports its parse error rather than skipping it as "not a task". Add
loader.SuiteSpec / SuiteExpectation / LoadedSuite / is_suite_document /
discover_documents / index_tasks / load_suite / SuiteLoadError, and
validation.validate_suite_file (a suite naming a task no file declares is an ERROR).

`--no-execute` yields Gate(applicable=False), not a pile of wrong verdicts: skipping the
scripts turns three supported claims into partially_supported ones, and blaming the
pipeline for the operator's flag would be a lie. Reports NOT APPLICABLE, exits 0. A
suite full of `contradicted` claims exits 0 -- finding a contradiction is the tool
working. A schema error in a suite or task file is REPORTED, not raised: run_and_report
catches pydantic.ValidationError alongside the loader's errors and prints what is wrong
with the file before exiting 1.

Two runs into two directories: byte-identical traces, summary.csv, summary.json. The two
artifacts that differ do so in exactly one field each -- result.json's absolute
trace_path (an M7 field) and summary.txt's output directory -- and the test diffs them
field by field rather than exempting them.

Result: 11 tasks, 26 checks (20 pass / 3 fail / 1 inconclusive / 1 error / 1 skipped),
support 10/11, reproduction 11/11, failure mode 10/11, 0 WRONG VERDICTS, gate PASS.

Add tests/test_suite.py (44 new); tests/test_scoring.py now parametrizes 11 fixtures
instead of 7 (+4). 500 total. The gate is tested by injecting each regression in turn --
a wrong verdict, a new miss, a stale declared miss -- because a gate that never fails
proves nothing when it passes. Update RESULTS (new M8 section; M2-M7 numbers restated
over 11 fixtures), ARTIFACT_FORMAT (suite format + validation rules), data/README,
README, website (index, results, milestones, reproducibility, checks, limitations,
roadmap), and milestone/commit/review notes.
```

## What this commit adds

- A **regression gate**, not a scoreboard. `run-suite` exits non-zero when the pipeline
  asserts a label its own fixtures deny, or when the set of claims it declines to decide
  changes. It exits zero on a suite full of contradictions.
- A suite file that **cannot bless a wrong verdict**, because the schema has no field for
  one.
- Four fixtures that give seven previously-unreachable vocabulary values a task each, and
  the first fixture in the repo that **fails on purpose** — a script whose data was never
  released.
- The distinction the schema was built for, now exercised end to end: a script that *will
  not run* (`failed_environment`, `execution_error`) is not a script that runs and prints
  the wrong number (`failed_numeric_mismatch`).
- Machine-readable artifacts a reader can audit without re-running: 11 traces, 11 result
  JSONs, `summary.csv`, `summary.json`, `summary.txt`.
- Content-based suite/task discovery, so `tasks/` can hold both and a broken file still
  surfaces its parse error.

## Deliberately excluded (per the operating principles)

- **Markdown / HTML reports.** Milestone 9. M8 writes machine-readable artifacts and one
  rendered text summary (`summary.txt`, byte-for-byte what was printed). Nothing here
  formats a report.
- **A `wrong_verdicts` escape hatch in the suite file.** The single most damaging change
  available to this harness. Refused by the schema, pinned by a test.
- **Tuning the standing miss away.** `synthetic_data_passage` could be moved to
  `supported` by stemming or a coverage threshold. It stays, declared by name in the
  suite file. `wrong_verdicts = 0` is the claim being made, not `support_label = 11/11`.
- **Gating a `--no-execute` run.** The gold outcomes assume the scripts ran. Gating anyway
  would report three wrong verdicts caused by a command-line flag.
- **Fixtures for `failed_missing_data` / `failed_missing_code`.** A task naming an absent
  fixture file fails to *load*, so neither can be expressed as a task. Both stay
  unit-tested, and `docs/RESULTS.md` says which vocabulary values have no fixture behind
  them and why.
- **A fixture exercising worst-wins across two reproduction channels.** Still no task has
  both a script and a dataset; the `SEVERITY` order remains pinned by unit tests only.
  Carried forward from the M7 review as an open item.
- **Timing in the trace or the summary.** Wall-clock duration is the one value in an
  execution record that cannot be reproduced. The suite reports none.
- **Parallelism.** Eleven tasks in ~1.5 s on one core. Concurrency would buy nothing and
  cost determinism of the interleaved output.
- **New dependencies.** `csv`, `io`, `json`, `dataclasses`, `argparse`, `pathlib`.

## Verification performed at commit time

- `python3 -m pytest -q` → 500 passed (452 prior + 48 new).
- `ruff check .` → all checks passed.
- `python3 scripts/01_validate_fixtures.py` → 11 tasks ok, 1 suite ok, 0 failed,
  0 warnings (exit 0).
- `python3 scripts/00_check_environment.py` → exit 0 (`READY`).
- `python3 scripts/05_run_smoke_suite.py --out results/runs/` → 11 tasks, gate **PASS**,
  exit 0; 25 artifacts written under `results/runs/smoke_suite/` (gitignored).
- `claimverifier run-suite --no-execute` → gate `NOT APPLICABLE`, exit 0.
- `claimverifier run-suite --json` → parses; `gate.ok = true`, `suite.n_tasks = 11`.
- `claimverifier run-suite --suite <absent>` → exit 1, error on stderr.
- A suite with an unknown `task_id`, a `wrong_verdicts` key, or a miss declared for a task
  it does not run → exit 1 with a one-line error on stderr, **no traceback**.
- A one-task suite with an undeclared conservative miss → gate **FAIL**, exit 1;
  the same suite with `--no-gate` → exit 0, same report.
- The three regressions the gate exists to catch, injected into a temp copy of the suite:
  a new conservative miss → exit 1; a stale declared miss → exit 1; the unmodified suite →
  exit 0.
- Suite run twice into two different directories → all 11 `.trace.jsonl`, `summary.csv`,
  and `summary.json` byte-identical; `result.json` differs only in `trace_path` and
  `summary.txt` only in the `Artifacts` line (both verified field by field).
- `claimverifier verify` over each of the four new tasks → each matches its gold outcome
  on all three fields (support, reproduction, failure mode).
- `claimverifier link-evidence --no-declared-source` over the four new tasks → 7/7 gold
  links recovered, 0 spurious.
- `claimverifier run-sandbox --task tasks/code_reproduction/unreproducible_accuracy.yaml`
  → `exited 1`, empty stdout, one stderr line, no network attempts, no files written.
- Static site served locally on port 9002; all 11 pages fetched via Python's `urllib`
  (no `curl`/`wget`, per the permission policy), HTML tag balance and internal links
  checked.
- `git status` clean after commit. Nothing under `results/` is tracked.
