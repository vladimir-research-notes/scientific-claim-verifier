# M8 — Smoke suite

## Summary

Adds `tasks/smoke_suite.yaml`, the `suite.py` runner, and `claimverifier run-suite`:
eleven claim-verification tasks driven end to end — extraction, evidence linking,
deterministic checks, sandboxed fixture execution, scoring — on a CPU, offline, in ~1.5 s,
emitting a JSONL trace and a result JSON per task plus `summary.csv`, `summary.json`, and
`summary.txt`.

Four ideas carry the milestone.

**The suite is a gate, not a scoreboard, and the gate is asymmetric.** Any *wrong
verdict* — a committal support label the task's gold outcome disagrees with — fails the
run, and the suite file has no key that could declare one acceptable. A *conservative
miss* — the pipeline predicted `unverifiable_from_artifacts` where gold commits — fails
the run only if the **set** of them changed: a new one is a regression, and a fixed one
must be removed from the file rather than left to rot. This is the M7 `wrong_verdicts` /
`conservative_misses` split given teeth. A change that raises label accuracy by turning a
claim the pipeline honestly declined to decide into one it decides *wrongly* has made the
tool worse, and a single accuracy number would have called it an improvement.

**The fixture set grew from seven tasks to eleven, and the four new ones were authored
after the rules that score them were frozen.** M7's review asked for exactly this. The
original seven never produced `partially_supported`, `approximately_reproduced`,
`failed_numeric_mismatch`, `failed_environment`, `statistic_mismatch`,
`passage_does_not_assert`, or `execution_error` — seven vocabulary values with no task
behind them, and one (`approximately_reproduced`) the M7 review named as unexercised
end to end. Each new fixture reaches one, and **each landed on its hand-written gold
outcome on the first run**, with no change to the extractor, the linker, the checks, or
the rule tables. All five `CheckStatus` values now fire on a real task.

**A gate that never fails proves nothing when it passes.** `suite.gate()` is tested by
injecting each failure in turn — a wrong verdict, a new conservative miss, a stale
declared miss — and asserting the gate rejects the run. A separate test asserts the suite
schema *refuses* a `wrong_verdicts` key outright, so the harness cannot be weakened by
editing a YAML file.

**`--no-execute` does not gate.** Skipping the fixture scripts turns three `supported`
claims into `partially_supported` ones. Those are not regressions — the operator disabled
the reproduction channel, and the gold outcomes assume it ran. Reporting them as wrong
verdicts would blame the pipeline for a flag. The gate reports `NOT APPLICABLE` and
exits 0.

**The measured result: 11 tasks, 26 checks, 0 wrong verdicts, gate PASS.** Support 10/11,
reproduction 11/11, failure mode 10/11; one conservative miss (`synthetic_data_passage`),
declared in the suite file.

## Deliverables

- **`tasks/smoke_suite.yaml`** (new) — 11 tasks ordered by evidence channel (text, table,
  dataset, code), with `expected.conservative_misses` naming the one standing miss.
- **Four new task fixtures**, each reaching a verdict no existing task could:
  - `statistical_claims/dataset_std` → `approximately_reproduced` (pstdev 1.1298967…,
    inside the ±0.05 its one-decimal claim admits, not on it).
  - `statistical_claims/dataset_mean_overstated` → contradiction via **recomputation**
    (`failed_numeric_mismatch` / `statistic_mismatch`).
  - `code_reproduction/unreproducible_accuracy` → a script that will not run
    (`partially_supported` / `failed_environment` / `execution_error`).
  - `ml_claims/negated_training_data` → contradiction via **polarity**
    (`passage_does_not_assert`).
- **`data/fixtures/code/reproduce_from_predictions.py`** (new) — the only fixture that
  fails on purpose: a complete, working script whose `predictions.csv` the paper never
  released. Exits 1 with one stable stderr line (no traceback, so the record does not
  drift with the interpreter version).
- **`src/scientific_claim_verifier/suite.py`** (new) — `SuiteRecord`, `SuiteRun`, `Gate`,
  `run_suite`, `gate`, `summary_csv`, `suite_to_dict`, `render_suite`, `write_artifacts`,
  and the `run-suite` CLI.
- **`artifacts/loader.py`** — the on-disk **suite** format: `SuiteSpec`,
  `SuiteExpectation`, `LoadedSuite`, `is_suite_document`, `discover_documents`,
  `discover_suite_files`, `index_tasks`, `load_suite`, `SuiteLoadError`.
  `discover_task_files` now classifies by content, so a suite may sit beside its tasks.
- **`artifacts/validation.py`** — `validate_suite_file`; `validate-fixtures` now reports
  `N task(s) and M suite(s)`, and fails a suite that names a task no file declares.
- **CLI:** `claimverifier run-suite [--suite PATH] [--out DIR] [--json] [--tasks-dir DIR]
  [--no-declared-source] [--no-execute] [--no-gate] [--abs-tol F] [--rel-tol F]`.
- **`scripts/05_run_smoke_suite.py`** — runnable without an editable install.
- **Tests:** `tests/test_suite.py` (44 new); `tests/test_scoring.py` grew from 7 to 11
  parametrized fixtures (+4). 500 total.
- **Docs:** `RESULTS` (new M8 section; M2–M7 numbers restated over 11 fixtures),
  `ARTIFACT_FORMAT` (suite format + validation rules), `data/README`, `README`.
- **Website:** `index`, `results`, `milestones`, `reproducibility`, `checks`,
  `limitations`, `roadmap`.

## Design decisions

- **Suites are told apart from tasks by content, not by filename.** `tasks/` holds both,
  and `docs/PLAN.md` §10 fixes the suite's path. A document with a top-level `suite_id`
  is a suite. A file that does **not parse** is classified as a *task*, so
  `validate-fixtures` reports its parse error rather than silently skipping it as "not a
  task" — the failure mode a name-based rule would have introduced.
- **A suite references tasks by `task_id`, never by path**, so it survives a task moving
  between family directories. `index_tasks` resolves them and raises on a duplicate id,
  because a suite naming that id could not say which file it meant.
- **The suite file cannot declare a wrong verdict.** `SuiteExpectation` has exactly one
  field. Adding a `wrong_verdicts` list would be the single most damaging change possible
  to this harness — it would let a future commit legalise an assertion its own fixture
  contradicts — so the schema (`extra="forbid"`) rejects the field, and a test pins that.
- **A stale conservative miss fails the gate too.** If a fixed claim stays listed, the
  suite file is lying about the pipeline. Both directions of drift fail, with a message
  saying which edit to make.
- **`--no-execute` yields `Gate(applicable=False)` rather than a pile of wrong verdicts.**
  The alternative — gating anyway — would have printed *"the pipeline asserted a label its
  own fixture contradicts"* about three claims whose channel the operator had switched
  off. The report says `NOT APPLICABLE`, names the flag, and exits 0.
- **The suite runs every committed task, and a test asserts it.** A task nobody runs is a
  task nobody maintains.
- **Tasks are ordered by evidence channel**, not alphabetically or by expected label, so a
  failure reads as *"the dataset channel broke"* rather than *"task 7 broke"*.
- **`summary.csv` names each trace by filename alone**, never by path, so the file is
  byte-identical across machines and output directories. The two artifacts that *do* vary
  (`result.json`'s `trace_path`, `summary.txt`'s output directory) vary in exactly one
  field each, and the determinism test diffs them field by field rather than exempting
  them wholesale.
- **`run-suite` writes to `<out>/<suite_id>/`**, so several suites can share one `--out`
  root and `results/runs/smoke_suite/` is self-describing.
- **A schema error in a suite or task file is reported, not raised.** `run_and_report`
  catches `pydantic.ValidationError` alongside the loader's own errors (`LOAD_ERRORS`) and
  prints what is wrong with the file before exiting 1. A malformed YAML file is a fact
  about the file, not a bug in the runner, and handing the user a pydantic traceback would
  say otherwise. (`claimverifier verify` does still raise on a schema-invalid *task* — an
  M7 code path, left alone here and recorded in the review notes.)
- **No Markdown or HTML report.** That is Milestone 9. M8 emits machine-readable artifacts
  and one rendered text summary (`summary.txt`, byte-for-byte what was printed).
- **`suite.py` is a top-level module**, not a package under `scoring/`. It orchestrates
  the whole pipeline rather than extending the inference layer, and it consumes
  `scoring/summary.py` unchanged — the aggregate M7 already emitted for
  `verify --task A --task B`.
- **No new dependencies.** `csv`, `io`, `json`, `dataclasses`, `argparse`, `pathlib`.

## Validation

Commands run (CPU-only, offline):

| Command | Result |
| --- | --- |
| `python3 -m pytest -q` | 500 passed (452 prior + 48 new) |
| `ruff check .` | All checks passed |
| `python3 scripts/01_validate_fixtures.py` | 11 tasks ok, 1 suite ok, 0 failed, 0 warnings — VALID (exit 0) |
| `python3 scripts/00_check_environment.py` | exit 0 — `READY` |
| `python3 scripts/05_run_smoke_suite.py --out results/runs/` | 11 tasks, gate **PASS**, exit 0 |
| `claimverifier run-suite --no-execute` | gate `NOT APPLICABLE`, exit 0 |
| `claimverifier run-suite --json` | machine-readable, gate `ok: true` |
| suite run twice into two directories | traces, `summary.csv`, `summary.json` byte-identical |
| site served on :9002, 11 pages fetched via `urllib` | 200, balanced HTML, no broken links |

### The suite result

| | |
| --- | --- |
| Tasks | 11 (`docs/PLAN.md` §11 asks for ≥ 8) |
| Checks | 26 — 20 pass, 3 fail, 1 inconclusive, 1 error, 1 skipped |
| Scripts executed | 3, in the controlled sandbox |
| Gold agreement | support 10/11 · reproduction 11/11 · failure mode 10/11 |
| **Wrong verdicts** | **0** |
| Conservative misses | 1 (`synthetic_data_passage`), declared |
| **Gate** | **PASS** |

Eleven hand-authored synthetic fixtures. `10/11` does not mean scientific claim
verification is 91% solved; the gate passing means *"this commit did not make the pipeline
assert something its own fixtures deny."* The suite's value is that it makes one specific
class of change impossible to land quietly: one that trades honesty for accuracy.

The tests additionally pin: suite/task classification by content, including an unparseable
file being classified as a task; `index_tasks` skipping the suite and rejecting duplicate
ids; the size gate (8 ≤ 11 ≤ 15); the suite running *every* committed task; the M1
`BenchmarkSuite` view; duplicate `task_ids` and a miss declared for a task not in the
suite both failing schema validation; loading a task file as a suite failing loudly; a
suite naming an unknown task failing to load; `validate-fixtures` catching a dangling
task reference; declared run order; the gate failing on each of the three regressions and
passing when the declared miss is exactly the observed one; a `contradicted` claim not
failing a run; every check status appearing across the suite; the four new fixtures'
verdicts; `numeric_tolerance` being `skipped` rather than `fail` when the script would not
run; `summary.csv`'s columns, row order, check counts, and absence of absolute paths;
`summary.json`'s suite/gate/aggregate shape; `summary.txt` equalling the printed report;
no artifacts written without `--out`; byte-identical traces and summaries across two runs,
with the two path-bearing exceptions diffed field by field; and eight CLI paths including
`--json`, `--no-gate`, `--tasks-dir`, a missing suite file, an unknown `task_id`, a schema
error reported without a traceback, and `scripts/05_run_smoke_suite.py` as a subprocess.

## Status

**Complete.** Next: **M9 — Reports** (Markdown, optionally HTML: input and extracted
claim, evidence, checks, support label, reproduction status, failure mode, limitations,
trace link). It reads the `RunTrace` and `VerificationResult` this milestone already
writes for every task, and `results/runs/smoke_suite/` gives it eleven real inputs.
