Human review: M7 — Scoring & failure modes

TL;DR
Milestone 7 adds the `scoring/` package and `claimverifier verify`: the one stage in the
pipeline allowed to draw an inference. Four decisions carry it. (1) A check's `status` is
a fact about the **check**, not about the claim, so scoring never reads it directly —
each check is reduced to a `Signal` (`supports` / `refutes` / `ambiguous` / `undecided`)
and the mapping is not one-to-one: `evidence_presence` fails two ways (a passage that
*negates* the claim refutes it; one that never mentions it refutes nothing, because
silence is not refutation), `table_value` passes two ways (the cell the claim named
supports it; the same value found somewhere in a multi-row column means the claim is
*ambiguous*), and `code_execution` passes two ways (printing the bundle's declared output
supports the claim; exit 0 with nothing declared is not evidence for any number). (2)
Refutation beats ambiguity beats support, and `nothing_decided` maps to
`unverifiable_from_artifacts`, **never** to `contradicted` — a checker that cannot decide
has learned nothing about the claim. (3) `FailureMode.EVIDENCE_UNDECIDABLE` (schema 1.2,
additive) gives M5's `inconclusive` status somewhere honest to land; recording
`passage_does_not_assert` there would publish the checker's ignorance as a fact about the
paper. (4) Reading a table cell is a lookup, not a reproduction, so table claims are
`not_applicable`. Every inference names the `Rule` that produced it and the check IDs
that rule read, into the report and a byte-reproducible JSONL trace. Over the seven
fixtures: support 6/7, reproduction 7/7, failure mode 6/7, and **0 wrong verdicts** — the
single miss is a refusal to decide. 106 new tests (452 total). No new dependencies. No
check's status changed: still 18 checks, 16 pass / 1 fail / 1 inconclusive.

**This directly answers the M6 review's open question.** M6 asked: *"Verify that no later
milestone (M7 scoring) treats `error` as evidence against a claim."* It does not. An
`error` check reduces to `undecided`, never `refutes`, and therefore can never produce
`contradicted`. It is test-pinned for every check type.

What changed
- New package: src/scientific_claim_verifier/scoring/ (__init__.py with Signal, Rule,
  CheckSignal, the per-check-type reducers, error_kind(), is_ambiguous_column(),
  decidedness(); support_labels.py with the five ordered rules; reproducibility.py with
  Channel, the SEVERITY worst-wins order, classify_reproduction; failure_modes.py with
  Cause, causes(), MODE_PRIORITY, classify_failure, limitations(); verdict.py with
  score(), build_trace(), render_result(), verify_task(), and the `verify` CLI;
  summary.py with TaskOutcome, SuiteSummary, and the conservative_misses /
  wrong_verdicts split).
- schemas.py: FailureMode.EVIDENCE_UNDECIDABLE added; SCHEMA_VERSION 1.1 -> 1.2.
- checks/__init__.py: new ErrorKind StrEnum (12 values).
- checks/{code_execution,statistical,table_recompute,consistency,verification}.py: every
  `error` path stamps inputs.error_kind; code_execution also records
  inputs.declared_expectations on every outcome (including `skipped`). Behaviour is
  otherwise untouched and no verdict moved.
- CLI: `verify --task X [--task Y ...] [--out DIR] [--json] [--no-declared-source]
  [--no-execute] [--abs-tol F] [--rel-tol F]`. No numbered script: docs/PLAN.md reserves
  scripts/04_ for report generation and scripts/05_ for the smoke suite.
- Tests: tests/test_scoring.py (100 new); 6 added to tests/test_checks.py pinning the
  error_kind vocabulary on every error path and declared_expectations on every outcome.
- Docs: docs/SCORING.md (new); CLAIM_SCHEMA, CHECKS, RESULTS, README updated.
- Website: index, checks, reproducibility, results, example-report, milestones,
  limitations. `example-report.html` was a hand-written mock describing a task that does
  not exist (`statistical_claims/samples_mean`, 120 samples, mean 3.387); it now shows
  real `claimverifier verify` output for `dataset_mean` and a real trace.

What should be checked later
- **The headline number is `wrong_verdicts = 0`, not `6/7`.** This is a deliberate framing
  choice, and it deserves scrutiny. A mismatch is bucketed: predicting a *non-committal*
  label (`unverifiable_from_artifacts`, `not_checked`) where gold commits is a
  "conservative miss"; asserting a *committal* label gold disagrees with is a "wrong
  verdict". Confirm the buckets are drawn in the right place — in particular, predicting
  `underspecified` where gold says `supported` is currently counted as a **wrong verdict**,
  not a conservative one, even though it is arguably an under-claim. The stricter reading
  was chosen on purpose. Also confirm that reporting zero of something is not being used to
  paper over 6/7.
- **The scoring rules were written by the same agent that wrote the gold outcomes they are
  measured against.** This is the compounding overfitting risk from M3–M5 in its sharpest
  form yet: seven hand-authored fixtures, and a rule table with the ordering chosen so
  `underspecified_split` lands on `underspecified`. RESULTS.md, SCORING.md, the milestone
  note, and the website all call it a regression harness rather than a benchmark. Confirm
  that framing is prominent enough, and consider whether M8's smoke suite should add tasks
  authored *before* the rules that score them.
- `synthetic_data_passage` is the one miss, and the temptation to fix it is real. It could
  be moved to `supported` by stemming (`trained` ~ `training`), a synonym list, or a
  coverage threshold. That would be overclaimed NLP, and it would risk moving
  `contradicted_f1`'s passage check off `pass`. Confirm that leaving a visible 6/7 rather
  than tuning to 7/7 is the wanted trade. The stated success criterion for a better
  evidence checker is: move this claim to `pass` **without** moving `contradicted_f1`'s.
- **`confidence` = decidedness.** The schema field is named `confidence`, and a reader may
  reasonably expect a calibrated probability. It is the share of checks that reached a
  `pass`/`fail` verdict, defined in the docstring, in docs/SCORING.md, on the website, in
  limitations.html, and printed inline next to every value. Confirm the field should carry
  a meaning its *name* does not imply, versus leaving it `None` until there is labelled
  data — or renaming it (a schema break, hence not done here).
- **`ErrorKind` is a change to a prior milestone's checks.** It was needed because
  distinguishing `missing_code` from `sandbox_failure` from a timeout by the *shape* of
  `inputs` is fragile (a `SandboxError` and a missing script both lack `exit_code`), and
  matching English in `notes` is not a contract. Confirm the twelve values are the right
  granularity, and that stamping them into `inputs` (a free-form `dict[str, Any]`) is
  preferable to adding a typed field to `VerificationCheck` (a schema change that would
  have touched every check).
- **`code_execution` PASS with nothing declared is `undecided`, not `supports`.** This is
  the reduction most likely to surprise. It means a code claim whose bundle omits
  `expected_outputs` and whose claim has no `expected_value` scores
  `unverifiable_from_artifacts` even though its script ran cleanly. No committed fixture
  hits it. Confirm the conservatism is right, or whether "the script the claim names ran to
  completion" is itself weak support.
- **`failure_mode: none` on a `partially_supported` claim.** `--no-execute` on `gc_content`
  yields `partially_supported` / `not_attempted` / `none`. Nothing failed, so no failure
  mode — but a reader scanning only `failure_mode` sees `none` and may read "clean".
  `reproduction_status` and `limitations` carry the real story. Confirm.
- **Worst-wins across reproduction channels is untested by any fixture.** No committed task
  has both a script and a dataset. The `SEVERITY` order (`reproduced` <
  `approximately_reproduced` < `not_attempted` < `failed_numeric_mismatch` <
  `failed_missing_data` < `failed_missing_code` < `failed_environment`) is pinned only by
  unit tests. In particular, `not_attempted` ranking *above* `approximately_reproduced` —
  so one reproduced channel plus one un-attempted channel reports `not_attempted` — is a
  judgement call. Confirm.
- **`approximately_reproduced` never fires on a fixture.** All three reproducing fixtures
  match exactly. The path is unit-tested, but the tolerance semantics it depends on
  (`difference == 0.0` after 12-decimal rounding) have not been exercised end to end. A
  check with `difference is None` degrades to `approximately_reproduced` (the conservative
  direction) — that behaviour was found by a test, not by design, and the docstring now
  states it.
- Two failure-mode mappings are coarse and named as such: a failing `comparison` (the
  *relation* does not hold) records `numeric_out_of_tolerance`; a failing `code_execution`
  (ran, printed the wrong text) records `other`. Confirm `other` is better than inventing
  `declared_output_mismatch`.
- **`_VERDICT_PHRASE` is a hand-written English phrase per label**, because
  `f"is {label.value.replace('_',' ')}"` produced "is unverifiable from artifacts by the
  supplied artifacts". A test pins that the dict covers every `SupportLabel`, so adding a
  label fails loudly. Confirm the summary sentence belongs in code at all, versus being
  M9's (the report generator's) business.
- **`scoring/` imports `checks/`** (for `Assertion` and `ErrorKind`) and `sandbox/trace`
  (for `write_trace`). That matches the layering in docs/PLAN.md §5. Confirm, and confirm
  that reading `check.inputs["assertion"]` / `["row_named"]` / `["n_rows"]` /
  `["declared_expectations"]` is an acceptable coupling — these are the signals M5
  deliberately recorded *for* M7, and CHECKS.md documents them, but they are string keys in
  an untyped dict.
- `verify` exits `0` on a `contradicted` claim. Finding a contradiction is the tool
  working. Exit `1` is reserved for a task that cannot be loaded. Confirm no CI wrapper will
  want a non-zero exit for a failed claim (a `--fail-on` flag would be trivial to add).
- The aggregate summary prints only when more than one `--task` is given, and
  `summary.json` is written only then. A single-task `--out` run writes two files, not
  three. Confirm.
- `RunTrace.result` holds the `VerificationResult`, which holds `trace_path` — but
  `to_jsonl()` serializes only `events`, and no event carries a path. That is why traces are
  byte-identical across output directories while `result.json` is not. Confirm the trace,
  not `result.json`, is the artifact the determinism guarantee attaches to.
- `causes()` and `limitations()` each recompute `signals(checks)`. Pure and cheap on
  three-check claims; `verdict.score()` computes it once for its own use. Confirm the
  duplication is acceptable for the sake of standalone, testable functions.
- `scoring/verdict.py` is a fourth module beyond the three docs/PLAN.md §5 names for
  `scoring/`, on the same reasoning as `checks/verification.py`. `summary.py` is a fifth.
  Confirm the growing surface is wanted.

Technical risks
- **No new execution surface.** Scoring is pure functions over already-computed checks. It
  starts no process, opens no socket, and reads no file except through `verify_task`, which
  delegates to the M2 loader and the M6 sandbox unchanged.
- **The `error` → `undecided` invariant is load-bearing.** If a future check reported
  `error` and scoring treated it as `refutes`, a missing dataset file would silently become
  a contradicted claim. `_inert_signal` is the single place this is decided, and it is
  test-pinned for every check type.
- **The `inconclusive` → `unverifiable_from_artifacts` invariant is equally load-bearing**,
  and is the reason `evidence_presence`'s `absent` case had to be split out of `fail`. Both
  paths are test-pinned, including the explicit assertion that the paraphrase fixture is not
  `contradicted`.
- Determinism is enforced and test-pinned: no wall clock, no RNG, no absolute path in any
  trace event; two runs of `recompute_accuracy` (whose script executes) produce byte-identical
  JSONL. The rule tables are module constants and check order is fixed by M5.
- Verdicts remain **relative to the supplied artifacts**. `supported` means these fixtures
  back this claim, not that the claim is true. Said in schemas.py, SCORING.md, RESULTS.md,
  limitations.html, and the report's own header.
- `--out` writes under `results/runs/`, which is gitignored; nothing generated is committed.
- The gold outcomes in the task files were never fed to the pipeline — `TaskExpectation` is
  read only by the reporter and the summary, after scoring has returned. The input/gold
  separation M2 established still holds.

Commands to verify
- python3 -m pytest -q
- python3 -m pytest tests/test_scoring.py -q
- ruff check .
- python3 scripts/01_validate_fixtures.py
- claimverifier verify --task tasks/ml_claims/synthetic_data_passage.yaml    (after `pip install -e .`)
      (the miss the project is built to make visible: unverifiable_from_artifacts,
       evidence_undecidable, confidence 0.00, and the report marks its own MISS)
- claimverifier verify --task tasks/table_claims/contradicted_f1.yaml
      (evidence_presence passes AND table_value fails; label contradicted; exit code 0)
- claimverifier verify --task tasks/ml_claims/underspecified_split.yaml
      (same locator shape as contradicted_f1, opposite label; rule `claim_ambiguous`)
- claimverifier verify --task tasks/bioinformatics_claims/gc_content.yaml --no-execute
      (partially_supported / not_attempted / none -- nothing was attempted, so nothing broke)
- claimverifier verify --task tasks/statistical_claims/dataset_mean.yaml --out results/runs/
      (run twice; the two .trace.jsonl AND .result.json files must be byte-identical)
- claimverifier verify --task tasks/table_claims/accuracy_improvement.yaml \
                       --task tasks/table_claims/contradicted_f1.yaml \
                       --task tasks/statistical_claims/dataset_mean.yaml \
                       --task tasks/bioinformatics_claims/gc_content.yaml \
                       --task tasks/code_reproduction/recompute_accuracy.yaml \
                       --task tasks/ml_claims/synthetic_data_passage.yaml \
                       --task tasks/ml_claims/underspecified_split.yaml
      (aggregate: support 6/7, reproduction 7/7, failure mode 6/7, 0 wrong verdicts)
- claimverifier verify --task tasks/nonexistent.yaml                          (exits 1)
- claimverifier run-checks --task tasks/table_claims/contradicted_f1.yaml
      (unchanged by the error_kind additions: 2 checks, 1 pass 1 fail)
- ./scripts/serve_site.sh   then load http://localhost:9002/reproducibility.html,
      results.html, and example-report.html

Human feedback
<!-- Human will fill this later. -->
