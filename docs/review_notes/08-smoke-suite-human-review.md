Human review: M8 — Smoke suite

TL;DR
Milestone 8 adds `tasks/smoke_suite.yaml`, `src/scientific_claim_verifier/suite.py`, and
`claimverifier run-suite`: eleven tasks driven end to end, offline, on a CPU, in ~1.5 s,
writing a JSONL trace and a result JSON per task plus `summary.csv`, `summary.json`, and
`summary.txt`. Three decisions carry it. (1) **The suite is a gate, and the gate is
asymmetric.** Any *wrong verdict* — a committal support label the task's gold outcome
disagrees with — fails the run; a *conservative miss* fails only if the **set** of them
changed. The suite file names the standing misses and has **no key** for wrong verdicts,
so it cannot bless one (`extra="forbid"`, test-pinned). (2) **The fixture set grew from 7
to 11**, with the four new tasks authored *after* the M7 rule table was frozen, to reach
seven vocabulary values no existing fixture produced — `partially_supported`,
`approximately_reproduced`, `failed_numeric_mismatch`, `failed_environment`,
`statistic_mismatch`, `passage_does_not_assert`, `execution_error`. Each landed on its
hand-written gold outcome on the first run with **no change to any pipeline stage**. All
five `CheckStatus` values now fire on a real task. (3) **`--no-execute` does not gate** —
it turns three `supported` claims into `partially_supported` ones, and calling those
"wrong verdicts" would blame the pipeline for the operator's flag. Result: 11 tasks, 26
checks (20 pass / 3 fail / 1 inconclusive / 1 error / 1 skipped), support 10/11,
reproduction 11/11, failure mode 10/11, **0 wrong verdicts**, gate PASS. 48 new tests
(500 total). No new dependencies.

**This addresses two open items from the M7 review.** M7 asked whether "M8's smoke suite
should add tasks authored *before* the rules that score them" — the four new fixtures were
authored after the rules were frozen and needed no rule change, which is the closest this
repo gets to a held-out set (see the caveat below). M7 also flagged that
"`approximately_reproduced` never fires on a fixture"; `dataset_std` now fires it end to
end.

What changed
- New: tasks/smoke_suite.yaml (11 task_ids, ordered by evidence channel; expected.
  conservative_misses names the one standing miss).
- New task fixtures: statistical_claims/dataset_std, statistical_claims/
  dataset_mean_overstated, code_reproduction/unreproducible_accuracy, ml_claims/
  negated_training_data.
- New fixture script: data/fixtures/code/reproduce_from_predictions.py — the only fixture
  that fails on purpose. A complete, working script whose predictions.csv the paper never
  released. Exits 1 with one stable stderr line (deliberately not a traceback, which would
  drift with the interpreter version and appear in every trace).
- New module: src/scientific_claim_verifier/suite.py (SuiteRecord, SuiteRun, Gate,
  run_suite, gate, summary_row, summary_csv, suite_to_dict, render_suite, write_artifacts,
  run_and_report, and the run-suite CLI).
- artifacts/loader.py: the on-disk suite format — SuiteSpec, SuiteExpectation, LoadedSuite,
  SuiteLoadError, is_suite_document, discover_documents, discover_suite_files, index_tasks,
  load_suite. discover_task_files now classifies files by content (it reads each one), so a
  suite can live beside its tasks.
- artifacts/validation.py: validate_suite_file; TaskValidation.kind; ValidationReport.
  n_tasks / n_suites; the report prints "(suite)" and "N task(s) and M suite(s)".
- CLI: run-suite registered; the epilog and module docstring now list it as live and leave
  only `report` (M9) unimplemented.
- scripts/05_run_smoke_suite.py (runnable without an editable install).
- Tests: tests/test_suite.py (44 new). tests/test_scoring.py's FIXTURES and
  EXPECTED_VERDICTS grew from 7 to 11 (+4 parametrized cases), so
  `test_the_committed_fixtures_produce_no_wrong_verdicts` really covers every committed
  fixture. tests/test_extraction.py and tests/test_linking.py had hardcoded fixture-set
  totals (7 and 14) updated to 11 and 21.
- Docs: RESULTS (new M8 section; M2–M7 numbers restated over 11 fixtures),
  ARTIFACT_FORMAT (suite format + validation rules), data/README, README.
- Website: index, results, milestones, reproducibility, checks, limitations, roadmap.

What should be checked later
- **The gate's asymmetry is the central claim of this milestone, and it deserves the
  hardest look.** A wrong verdict always fails; a conservative miss fails only on drift.
  The justification is that declining to decide asserts nothing false. Confirm this is the
  right trade for a verification tool, and in particular confirm the case that motivated
  it: predicting `underspecified` where gold says `supported` is counted a **wrong
  verdict** (it is committal), even though it is arguably an under-claim. That strictness
  was inherited from M7's `NON_COMMITTAL` set and is unchanged here.
- **`--no-execute` sets `Gate(applicable=False)` and exits 0.** This means a caller can
  make the gate stop gating by passing a flag. It prints `NOT APPLICABLE` in bold-ish text
  and names the flag, and the alternative (reporting three wrong verdicts caused by an
  operator switch) seemed worse. Confirm. Consider whether CI should be told to fail if it
  ever sees `gate.applicable == false` in summary.json.
- **"Authored after the rules were frozen" is weaker than it sounds.** The same agent wrote
  the rules, the fixtures, and their gold outcomes, in one session, with the rule tables in
  view. The four new fixtures needed no rule change, which is real evidence that the rule
  table generalises *a little* — but it is not a held-out set in any meaningful sense.
  RESULTS.md says so explicitly. Confirm the framing is not overclaiming, and consider
  whether a genuinely independent fixture set (authored by a different process, or drawn
  from real open papers) belongs on the roadmap.
- **`dataset_std`'s gold outcome encodes a real judgement call.** pstdev = 1.1298967…, the
  claim says 1.1, and the tolerance (±0.05) comes from the claim's own one decimal place.
  So the claim is `supported` and the reproduction is `approximately_reproduced`. A reader
  might reasonably expect `supported` + `reproduced`, or even that a 2.7% relative gap
  should not count as support at all. The distinction exists because "within the tolerance
  the claim's wording implies" and "the number the claim states" are different facts.
  Confirm.
- **`unreproducible_accuracy` is `partially_supported`, not `unverifiable_from_artifacts`.**
  Its passage asserts the claim verbatim (`evidence_presence` passes → `supports`), and two
  checks are undecided, so M7's `some_checks_support` rule fires. A reader may feel that a
  claim whose *only* computational check could not run has not been "partially supported"
  by anything worth the name — the support is purely textual. Confirm the label, and
  confirm that `failure_mode: execution_error` plus `reproduction_status:
  failed_environment` carry enough of the story.
- **`negated_training_data` is the only fixture where a *text-only* check produces
  `contradicted`.** It rests entirely on `NEGATION_CUES` and on polarity being read from
  the best-matching *sentence*. The passage is one sentence (a semicolon does not split it),
  so the negation and the synthetic-data clause are judged together. Check that a
  multi-sentence passage where the negation lives in a *different* sentence than the claim's
  tokens still behaves sensibly — no fixture covers that, and `docs/CHECKS.md` notes the
  contraction limitation ("doesn't" does not tokenize as a cue) but not this one.
- **`discover_task_files` now reads every file it discovers**, to classify it. Previously it
  only globbed. This is 12 small reads per call and it is called by several tests and by
  `validate-fixtures`. Confirm the cost is acceptable, and confirm the classification rule
  ("unparseable ⇒ task") is right: it exists so `validate-fixtures` reports a parse error
  rather than silently ignoring the file, but it means a *suite* with a YAML syntax error is
  reported as a broken **task**.
- **`index_tasks` raises `SuiteLoadError` on a duplicate `task_id`.** Two tasks in different
  family directories with the same id is currently a hard error at suite-load and
  suite-validate time, but `load_task` itself is happy to load either. Confirm the id should
  be repo-globally unique.
- **`run-suite` reports a schema error; `verify` still raises one.** `suite.run_and_report`
  catches `pydantic.ValidationError` (via `LOAD_ERRORS`) and prints what is wrong with the
  file before exiting 1. `scoring.verdict.verify_and_report` catches only `TaskLoadError` and
  `OSError`, so `claimverifier verify --task <schema-invalid.yaml>` still hands the user a
  pydantic traceback. That is an M7 code path and was left alone in this milestone. It is a
  one-line fix and probably should be made; confirm it belongs in M9's cleanup rather than
  here. (`validate-fixtures` already reports such files correctly.)
- **`summary.json` contains the tasks twice**, once inside `summary` (the M7 aggregate
  document, with predicted vs. gold) and once at the top level (with family, claim type,
  confidence, check counts, trace filename). They join on `task_id`. The alternative was to
  mutate M7's `summary_to_dict` output. Confirm the duplication is acceptable, or whether
  `summary.tasks` should be dropped for suite runs.
- **`SuiteRecord.scored` is `None` in the synthetic runs used to test the gate.** `gate()`
  reads only `record.outcome`, so this works, but the field is typed non-optional and the
  test carries a `type: ignore`. Confirm; a `GateInput` protocol over outcomes alone would
  be cleaner.
- **Determinism has two named exceptions and they are asserted, not waived.**
  `<task_id>.result.json` records its own absolute `trace_path` (an M7 field) and
  `summary.txt` names the output directory. Every trace, `summary.csv`, and `summary.json`
  is byte-identical across two runs into two directories. Confirm the guarantee attaches to
  the right artifacts, and whether `result.json` should store a *relative* trace path (an M7
  behaviour change, deliberately not made here).
- **`summary.csv` writes `confidence` as `"%.6f"`.** It is decidedness (the share of checks
  that reached a verdict), not a calibrated probability — the same caveat M7's review
  raised, now printed in a CSV column where the caveat does not fit. Confirm the column
  name, or whether it should be `decidedness`.
- Three vocabulary values still have no fixture: `not_checked` (unreachable — the check
  runner always emits an `evidence_presence` check), `failed_missing_data`, and
  `failed_missing_code` (a task naming an absent fixture file fails to *load*, so it cannot
  be expressed as a task). RESULTS.md names all three. Confirm none of them needs a fixture
  via some other route (e.g. a dataset artifact with `path: null`).
- **Worst-wins across reproduction channels is still untested by any fixture** — no
  committed task has both a script and a dataset. Carried forward unchanged from the M7
  review. M8 would have been the natural place to add one; it was not, because no plausible
  claim in the fixture domains needs both.
- The suite runs every committed task, and a test asserts `set(suite.task_ids) ==
  set(index_tasks(tasks/))`. This means adding a task file *without* adding it to the suite
  fails the test suite. Confirm that is the wanted coupling (it is, on the reasoning that a
  task nobody runs is a task nobody maintains) rather than an annoyance.
- `run-suite --out DIR` writes to `DIR/<suite_id>/`, whereas `verify --out DIR` writes
  directly into `DIR`. Confirm the inconsistency is worth the self-describing directory.

Technical risks
- **New execution surface: none beyond M6.** The suite starts exactly the processes the
  code-execution check already started — three trusted, committed, stdlib-only fixture
  scripts — through the unchanged M6 sandbox. It opens no socket and reads no file outside
  `tasks/` and `data/fixtures/`.
- **`reproduce_from_predictions.py` is a fixture that fails on purpose.** It is harmless: it
  checks for a file, prints one line to stderr, and exits 1. It writes nothing, imports only
  `csv`/`sys`/`pathlib`, and its sandbox record shows no network attempts and no files
  written. The sandbox is still controlled fixture execution, not a security boundary
  (`docs/SANDBOX.md`).
- **The gate is the safety-critical code in this milestone.** If `gate()` silently returned
  `ok=True`, every future regression would land unnoticed. It is tested by injecting each
  failure in turn — a wrong verdict, a new conservative miss, a stale declared miss — and
  asserting rejection. A gate that never fails proves nothing when it passes.
- **The suite schema is load-bearing.** `SuiteExpectation` forbids extra fields, which is the
  only thing preventing a future `wrong_verdicts: [...]` line from legalising an assertion a
  fixture contradicts. Test-pinned.
- Determinism is enforced and test-pinned: no wall clock, no RNG, and no absolute path in
  any trace event or in `summary.csv`. Task order is the suite's declared order.
- The gold outcomes were never fed to the pipeline. `run_suite` calls `verify_task`, which
  reads `TaskExpectation` only through `outcome_of`, after scoring has returned. The
  input/gold separation M2 established still holds.
- `--out` writes under `results/runs/`, which is gitignored; nothing generated is committed.
- Verdicts remain **relative to the supplied artifacts**. `supported` means these fixtures
  back this claim, not that the claim is true.

Commands to verify
- python3 -m pytest -q                                     (500 passed)
- python3 -m pytest tests/test_suite.py -q                 (44 passed)
- ruff check .
- python3 scripts/01_validate_fixtures.py                  (11 tasks + 1 suite, VALID)
- python3 scripts/05_run_smoke_suite.py --out results/runs/
      (11 tasks, 0 wrong verdicts, gate PASS, exit 0; 25 artifacts under
       results/runs/smoke_suite/)
- claimverifier run-suite --no-execute                     (gate NOT APPLICABLE, exit 0)
- claimverifier run-suite --json | python3 -m json.tool | head -20
- claimverifier run-suite --suite tasks/nonexistent.yaml   (exits 1)
- Run the suite twice into two different directories and diff:
      the 11 .trace.jsonl, summary.csv, and summary.json must be byte-identical;
      result.json must differ ONLY in `trace_path`; summary.txt ONLY in `Artifacts`.
- Break the gate on purpose and confirm it catches it. Copy tasks/smoke_suite.yaml to a
  temp file, edit the copy, and run with --suite <copy> --tasks-dir tasks/ so the committed
  tree is untouched. All of these were run at commit time:
      conservative_misses: []            ->  exit 1, "new conservative miss"
      ... plus `- dataset_mean`          ->  exit 1, "stale conservative miss"
      conservative_misses: [] --no-gate  ->  exit 0, same FAIL report
      task_ids: [ghost_task]             ->  exit 1, clean error, no traceback
      expected: {wrong_verdicts: [...]}  ->  exit 1, clean schema error; validate-fixtures
                                             also FAILS on the same file
- claimverifier verify --task tasks/code_reproduction/unreproducible_accuracy.yaml
      (partially_supported / failed_environment / execution_error; numeric_tolerance is
       SKIPPED, not FAIL -- no number disagreed, because no number exists)
- claimverifier verify --task tasks/statistical_claims/dataset_std.yaml
      (supported / approximately_reproduced: 1.1298967 is inside +/-0.05, not on 1.1)
- claimverifier verify --task tasks/ml_claims/negated_training_data.yaml
      (contradicted / passage_does_not_assert, from polarity alone; no number involved)
- claimverifier run-sandbox --task tasks/code_reproduction/unreproducible_accuracy.yaml
      (exited 1, empty stdout, one stderr line, no network attempts, no files written)
- ./scripts/serve_site.sh   then load http://localhost:9002/results.html and
      milestones.html

Human feedback
<!-- Human will fill this later. -->
