Human review: M5 — Verification checks

TL;DR
Milestone 5 adds the `checks/` package (`consistency`, `table_recompute`,
`statistical`, `code_execution`, `verification`) plus `evidence/locators.py`: given
an extracted claim and its evidence links, each check reads the artifact at that
locator and records a `VerificationCheck` with its inputs, computed value, expected
value, the tolerance actually applied, the signed difference, and its evidence.
Three decisions carry the milestone. (1) A check produces evidence and never decides
the claim's fate — a new `contradicted_f1` fixture proves it, with the paper's
abstract asserting the claim verbatim (`evidence_presence` passes) while its own
table refutes it (`table_value` fails). (2) A check that cannot decide reports the
new `inconclusive` status rather than `fail`, so a bag-of-words evidence rule facing
a paraphrase never manufactures a contradiction out of its own ignorance. (3)
Tolerance is derived from the claim's *reported precision* — `3.4` admits anything
rounding to 3.4 — so no threshold was tuned to make a fixture pass. 18 checks over
7 fixtures: 16 pass, 1 fail, 1 inconclusive. 114 new tests (285 total). No new
dependencies. No support label is assigned here; that inference is M7's.

What changed
- New package: src/scientific_claim_verifier/checks/ (__init__.py with Tolerance,
  the reported-precision rule, compare, operator_holds, stable float rounding and
  check_id; consistency.py; table_recompute.py; statistical.py; code_execution.py;
  verification.py).
- New module: src/scientific_claim_verifier/evidence/locators.py — the locator
  grammar, formatted and parsed in one place. evidence/{tables,datasets,code_refs,
  figures}.py refactored to emit through it (no behaviour change; test-pinned).
- schemas.py: CheckStatus.INCONCLUSIVE added; SCHEMA_VERSION "1.0" -> "1.1"
  (additive — every 1.0 document stays valid).
- artifacts/loader.py: read_csv_rows / read_csv_column (one CSV reader, now shared
  with the M2 shape check); optional TaskSpec.tolerance block (TaskTolerance model).
- CLI: `run-checks --task X [--out DIR] [--json] [--no-declared-source]
  [--no-execute] [--abs-tol F] [--rel-tol F]`; scripts/03_run_checks.py.
- New fixture: tasks/table_claims/contradicted_f1.yaml (family `contradiction`,
  gold `contradicted` / `table_cell_mismatch`). Seven fixtures now, so the M3 and M4
  measured tables were re-run (7/7 fields, 14/14 gold links) across RESULTS.md,
  EXTRACTION.md, EVIDENCE_LINKING.md, ARTIFACT_FORMAT.md, and the website.
- Tests: tests/test_checks.py (112), plus 1 each added to test_schemas.py and
  test_linking.py; counts updated in test_extraction.py and test_linking.py.
- Docs: docs/CHECKS.md (new); RESULTS, CLAIM_SCHEMA, ARTIFACT_FORMAT, EXTRACTION,
  EVIDENCE_LINKING, README updated.
- Website: index, checks, claim-schema, reproducibility, results, milestones,
  limitations. The Limitations page previously claimed the executor runs scripts
  "in a temp dir"; it does not, and the page was corrected rather than left
  flattering.

What should be checked later
- `CheckStatus.INCONCLUSIVE` is a schema change made by a milestone that is not M1.
  It is additive and the version was bumped, but confirm the vocabulary belongs to
  us to extend (docs/PLAN.md §6 defines SupportLabel and ReproductionStatus, not
  CheckStatus) and that no downstream consumer assumed a four-value enum.
- The reported-precision tolerance means `78` and `78.0` are different claims
  (±0.5 vs ±0.05). This is principled, and it is surprising. Confirm it is wanted,
  and consider whether `expected_value: 78.0` in a *gold* block should therefore
  round-trip its written precision rather than being a bare float.
- `reported_precision_tolerance` locates the claim's number by scanning the claim
  *text* for a token equal to the value. If a claim states the same number twice at
  different precisions ("0.8 (i.e. 0.80)"), the first wins. No fixture does.
- `synthetic_data_passage` has gold `supported` and the pipeline reports
  `inconclusive`. That is the honest answer for this method, but it means M7 cannot
  reach `supported` on that task from checks alone. Decide now whether M7 is allowed
  to consider the *declared* `source_passage` as corroborating evidence — and if so,
  make sure the smoke suite reports blind numbers too, or the end-to-end result will
  look better than the system deserves.
- The negation rule only flips a would-be `pass` to `fail`. It is scoped to the
  quoting sentence and to a closed cue set. Verbatim containment is **not**
  polarity-checked, so a passage reading "it is not true that <claim>" would pass.
  Confirm whether verbatim should also be polarity-gated.
- `polarity_mismatch` and `absent` both map to `fail`, but they are very different
  situations (the passage refutes the claim vs. the linker linked something
  irrelevant). Only `inputs.assertion` distinguishes them. Confirm M7 reads it.
- The `contradicted_f1` fixture was hand-authored *in this milestone*, by the same
  agent that wrote the check it exercises. It is a demonstration, not independent
  evidence that the check generalizes. A held-out contradicted fixture, written
  against a different table shape, would be worth more.
- The column check calls a value "present" if any cell is within tolerance, and
  reports `matching_rows`. With a wide tolerance (e.g. `90%` → ±0.5) two rows could
  both match, and the check still passes, recording both. Confirm that a two-row
  match should be `pass`-with-ambiguity rather than `inconclusive`.
- `table_recompute._cell_check` pairs a cell with the claim field it stands for by
  taking whichever claim value is *nearest*, and records the choice in
  `inputs.claim_field`; `verification._observed_cell_values` reads that back to feed
  the comparison check. For a comparison claim whose two values sit close together
  relative to the tolerance, both cells could pair to the same field, and the
  comparison check would then be `skipped` (one side missing) rather than wrong.
  Confirm this degradation is acceptable, or key the pairing on the locator's row.
- `code_execution` uses `sys.executable`, so a script is run under whatever
  interpreter the tests run under. There is no declared-interpreter check and the
  artifact's `entrypoint` ("python compute_accuracy.py") is **declarative only** —
  it is never parsed or executed. Confirm that is the intended contract, or make
  `entrypoint` authoritative in M6.
- `PYTHONHASHSEED=0` is set for the child process. That is a determinism measure,
  and it is arguably environment policy, which is M6's. Confirm the placement.
- The child inherits the parent environment. Nothing in the committed fixtures reads
  it, but a fixture that did would produce machine-dependent output that the trace
  would record as fact. M6 should scrub.
- The subprocess timeout test sleeps up to 0.3s of wall clock. It is the only test
  in the suite whose duration is load-dependent; if CI is heavily loaded it could
  in principle report a timeout for the wrong reason (it asserts `timed_out`, so a
  slow machine makes it *more* likely to pass, not less). Confirm acceptable.
- `numeric_tolerance` is emitted only for the code channel. The rationale — that
  only there do "could not run" and "ran but disagreed" differ — is in docs/CHECKS.md.
  Confirm a reader agrees, since the check name suggests a general-purpose record.
- `figure_recompute` and `correlation` are named as unimplemented in docs and on the
  website. Confirm that is preferable to shipping untested code paths with no
  fixture behind them (M4 shipped `evidence/figures.py` on the opposite reasoning;
  the difference is that a mention resolving to nothing was a hole in the audit
  trail, whereas an unrun check is simply absent).
- The M4 review asked whether `MatchMethod` should become a typed
  `EvidenceLink.match_method` field rather than free text in `notes`. M5 did **not**
  need it — no check branches on how a link was found — so the question is deferred,
  not answered. M7 may still want it (a declared-source passage is weaker evidence
  than a verbatim one).
- The locator grammar does not escape values, so a table row label containing `,` or
  `=` would parse ambiguously. Unchanged from M4's implicit format; now that a
  parser exists, the hazard is real rather than theoretical. No fixture triggers it.
- `TaskSpec.tolerance` is exercised only by a synthetic task in the test suite; no
  committed fixture sets it. Confirm the field should exist at all, or whether run-level
  `--abs-tol`/`--rel-tol` is sufficient.
- Floats are rounded to 12 decimal places before being recorded. Confirm 12 is right:
  it is far below every tolerance in play, but it is a magic number.

Technical risks
- Moderate, and concentrated in one place: this is the first milestone that
  **executes code**. `SubprocessScriptRunner` starts a child process with a timeout,
  closed stdin, and captured output — and nothing else. No temp dir, no environment
  scrubbing, no filesystem or network restriction. It is **not a security boundary**,
  it is only ever pointed at two trusted, committed, stdlib-only fixture scripts, and
  the code, the docs, and the website all say so. Do not point it at anything else
  before M6.
- Path resolution for both datasets and scripts goes through the M2
  `resolve_fixture_path`, which rejects absolute paths and `..` escapes, so a task
  cannot make the checker read or execute a file outside the repository.
- Everything else is pure and deterministic: no wall clock, no RNG, no absolute
  paths in recorded output (the command is stored as `("python", "gc_content.py")`).
  Determinism and input-purity are both test-pinned.
- The main non-correctness risk is again **overfitting to hand-authored fixtures**,
  and it compounds: the fixtures, the linker's locator rules, and now the checks that
  read them were all written by the same agent with the same seven tasks in view.
  The 16/18 pass rate is a consistency check, not a benchmark, and RESULTS.md,
  CHECKS.md, and the website all say so.
- `--out` writes under `results/runs/`, which is gitignored; nothing generated is
  committed.

Commands to verify
- python3 -m pytest -q
- python3 -m pytest tests/test_checks.py -q
- ruff check .
- python3 scripts/01_validate_fixtures.py
- claimverifier run-checks --task tasks/table_claims/contradicted_f1.yaml   (after `pip install -e .`)
- claimverifier run-checks --task tasks/ml_claims/synthetic_data_passage.yaml
- claimverifier run-checks --task tasks/table_claims/contradicted_f1.yaml --abs-tol 10
- claimverifier run-checks --task tasks/statistical_claims/dataset_mean.yaml --json
- claimverifier run-checks --task tasks/code_reproduction/recompute_accuracy.yaml --no-execute
- python3 scripts/03_run_checks.py --task tasks/bioinformatics_claims/gc_content.yaml
- ./scripts/serve_site.sh   then load http://localhost:9002/checks.html and results.html

Human feedback
<!-- Human will fill this later. -->
