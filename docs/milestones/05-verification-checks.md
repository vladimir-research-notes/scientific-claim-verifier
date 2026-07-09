# M5 — Verification checks

## Summary

Introduces the `checks/` package: given an extracted claim (M3) and the evidence
links that say *where to look* (M4), each check reads the artifact at that locator,
computes something, and records a `VerificationCheck` carrying its inputs, the
computed value, the expected value, the tolerance actually applied, the signed
difference, and the evidence it used.

Three ideas carry the milestone.

**A check does not decide the claim's fate.** Checks produce evidence *about* a
claim; the support label is an inference drawn from the whole set of them, and it
belongs to M7. A new fixture, `contradicted_f1`, makes this concrete rather than
rhetorical: the paper's abstract asserts *"Method B reaches an F1 score of 91.0 on
MNLI"* verbatim, so `evidence_presence` **passes**, while its own results table
reports 86.0, so `table_value` **fails**. Both are true. A system that collapsed
them into one verdict would destroy the only interesting fact about the claim.

**A check that cannot decide says so.** `CheckStatus` gains `INCONCLUSIVE`
(schema `1.1`, additive). The `evidence_presence` check is a transparent lexical
rule; faced with the paraphrase in `synthetic_data_passage` — *"trained **only** on
synthetic data"* supported by *"no real corpora were used at any stage of
**training**"* — it reports 40% token coverage and refuses the verdict. Reporting
`fail` would manufacture a contradiction out of the checker's own ignorance.

**Tolerance is read off the claim, not chosen.** The default threshold is the
claim's own *reported precision*: half of the last decimal place of the number as
written. `3.4` → ±0.05; `0.80` → ±0.005; `90%` → ±0.5; a count is exact. So the
tolerance is a property of how the claim was *stated*, not a constant tuned until
the fixtures went green. It is recorded on every check, and can be overridden per
task (`tolerance:`) or per run (`--abs-tol` / `--rel-tol`).

## Deliverables

- **`src/scientific_claim_verifier/checks/`** (new package, per `docs/PLAN.md` §5):
  - `__init__.py` — `Tolerance`, the reported-precision rule, `compare`,
    `operator_holds`, stable float rounding, and the `check_id` scheme.
  - `consistency.py` — `evidence_presence` (five assertion levels) and `comparison`.
  - `table_recompute.py` — cell and column lookup, the ambiguity signal.
  - `statistical.py` — CSV statistic recomputation and `numeric_tolerance`.
  - `code_execution.py` — the `ScriptRunner` protocol, `SubprocessScriptRunner`,
    stdout observable parsing.
  - `verification.py` — the `CheckRun`, dispatch, rendering, JSON, and the CLI.
- **`src/scientific_claim_verifier/evidence/locators.py`** — the locator grammar,
  extracted so the linker writes and the checks read through one module.
- **Schema:** `CheckStatus.INCONCLUSIVE`; `SCHEMA_VERSION` `1.0` → `1.1`.
- **Loader:** `read_csv_rows` / `read_csv_column` (one CSV reader, shared with the
  M2 shape check), and an optional `TaskSpec.tolerance` block.
- **CLI:** `claimverifier run-checks --task X [--out DIR] [--json]
  [--no-declared-source] [--no-execute] [--abs-tol F] [--rel-tol F]`, plus
  `scripts/03_run_checks.py`.
- **Fixture:** `tasks/table_claims/contradicted_f1.yaml` (family `contradiction`,
  gold `contradicted` / `table_cell_mismatch`) — seven fixtures now.
- **Tests:** `tests/test_checks.py` (112) plus 2 added to `test_schemas.py` /
  `test_linking.py`. 285 total.
- **Docs:** `docs/CHECKS.md` (new); `RESULTS`, `CLAIM_SCHEMA`, `ARTIFACT_FORMAT`,
  `EXTRACTION`, `EVIDENCE_LINKING`, `README` updated.
- **Website:** `index`, `checks`, `claim-schema`, `reproducibility`, `results`,
  `milestones`, `limitations`.

## Design decisions

- **`inconclusive` is a status, not a rounding of `fail`.** The four negative
  outcomes mean different things to M7: `fail` = the artifacts disagree;
  `inconclusive` = the method cannot decide (→ `unverifiable_from_artifacts`, never
  `contradicted`); `error` = the check could not run; `skipped` = it did not apply.
  `CheckStatus` is our own vocabulary (`docs/PLAN.md` §6 does not define it), so the
  addition is a clean, additive schema bump.
- **Tolerance from reported precision.** A claim writing `3.4` asserts only that
  the quantity rounds to `3.4`. Deriving the threshold from the claim's own text
  means no number in the checker was chosen to make a fixture pass. Its cost is a
  real asymmetry: `78` and `78.0` mean different things (±0.5 vs ±0.05). Documented.
- **A column check `pass`es when the value is present, and records the ambiguity.**
  `underspecified_split` (90.0 present at row `dev`, no row named) and
  `contradicted_f1` (91.0 present nowhere) produce the same locator shape and
  opposite verdicts. The difference lives in `inputs.matching_rows` / `n_rows`,
  which is exactly the signal M7 needs to separate `underspecified` from
  `contradicted`.
- **Execution failure is not numeric disagreement.** A timeout or a non-zero exit is
  `error`, never `fail`: a script that will not run tells you nothing about the
  claim's number. Agreement is judged by a separate `numeric_tolerance` check. This
  is *why* the schema distinguishes `failed_environment` from
  `failed_numeric_mismatch`, and a single boolean could not.
- **The runner sits behind a protocol.** `SubprocessScriptRunner` is a bare child
  process with a timeout — no temp dir, no env scrubbing, no network policy. That is
  stated plainly in the module docstring, `docs/CHECKS.md`, and on the website
  (the Limitations page previously claimed a temp dir; it now describes reality).
  M6 replaces the implementation, not the interface.
- **Determinism is enforced against the machine, not just the RNG.** The executed
  command is recorded as `("python", "gc_content.py")`, never `sys.executable`,
  which would vary per machine and break trace reproducibility. No duration is
  recorded. Floats are rounded to 12 decimal places, so `40.8 / 12` is written
  `3.4` — far below any tolerance, so rounding cannot flip a verdict.
- **One locator grammar.** M4 formatted locators with f-strings and M5 would have
  parsed them with its own regex. `evidence/locators.py` now owns both directions,
  and the four evidence modules were refactored to emit through it. The two
  conventions (`col=` for tables, `column=` for datasets) are kept verbatim because
  they are already committed in the fixtures' gold evidence.
- **Comparison checks the relation, not the magnitude.** *"improves from 72.0 to
  78.0"* → does the artifacts' target really exceed their baseline? Each magnitude
  is already checked against its own cell by `table_value`. Strict operators require
  the gap to *exceed* the tolerance: a difference smaller than the claim's reported
  precision is noise, not an improvement.
- **`run-checks`, not `verify`.** `docs/PLAN.md` §10 reserves `verify` for the
  end-to-end verb, and `verify` implies a support label. This stage computes checks
  and stops. Same reasoning as M4's `link-evidence`.
- **A new fixture rather than only synthetic tests.** The `fail` path deserved a
  real task. `contradicted_f1` also advances the M8 requirement of ≥8 smoke tasks
  and adds the `contradiction` family (`docs/PLAN.md` §7 family 6). The M3/M4
  measured tables were re-run and updated (7/7 fields, 14/14 gold links).
- **No new dependencies.** `statistics`, `subprocess`, `re`, `csv` from the stdlib.
  numpy/pandas remain unneeded.
- **`figure_recompute` and `correlation` are named, not stubbed.** Neither is in the
  M5 contract, neither has a fixture, and correlation needs a two-column locator the
  grammar does not express. They are listed as untouched work in `docs/CHECKS.md`
  and marked *not implemented* on the website's check table.

## Validation

Commands run (CPU-only, offline):

| Command | Result |
| --- | --- |
| `python3 -m pytest -q` | 285 passed (171 prior + 114 new) |
| `ruff check .` | All checks passed |
| `python3 scripts/01_validate_fixtures.py` | 7 ok, 0 failed, 0 warnings — VALID (exit 0) |
| `python3 scripts/00_check_environment.py` | exit 0 — `READY` |
| `claimverifier run-checks --task <task>` | text/JSON report, exit 0, on all 7 tasks |
| `python3 scripts/03_run_checks.py --task <task>` | runs without an editable install |
| site served on :9002, 11 pages fetched via `urllib` | 200, balanced HTML, no broken links |

### Checks over the seven committed fixtures

18 checks: **16 pass, 1 fail, 1 inconclusive**, 0 error, 0 skipped.

| Task | Checks | Outcome |
| --- | --- | --- |
| `accuracy_improvement` | 4 | `evidence_presence` pass · `table_value` pass ×2 · `comparison` pass |
| `contradicted_f1` | 2 | `evidence_presence` **pass** · `table_value` **fail** |
| `dataset_mean` | 3 | `evidence_presence` pass · `dataset_statistic` pass ×2 |
| `gc_content` | 3 | `evidence_presence` pass · `code_execution` pass · `numeric_tolerance` pass |
| `recompute_accuracy` | 3 | `evidence_presence` pass · `code_execution` pass · `numeric_tolerance` pass |
| `synthetic_data_passage` | 1 | `evidence_presence` **inconclusive** |
| `underspecified_split` | 2 | `evidence_presence` pass · `table_value` pass (ambiguous over 2 rows) |

The `contradicted_f1` and `synthetic_data_passage` rows are the milestone's result.
The first shows the two audit channels disagreeing, which is the whole reason the
report keeps them apart. The second is the honest cost of a transparent method:
gold says `supported`, the passage really does support the claim, and a
bag-of-words rule cannot confirm it — so it reports `inconclusive` rather than
guessing. A stronger evidence checker is measured by whether it can move that claim
to `pass` **without** moving `contradicted_f1`'s passage check off `pass`.

The tests additionally pin: the reported-precision rule on five written forms;
tolerance precedence (CLI > task > precision > float noise); the threshold formula;
`operator_holds` on all six operators including the "a gap below tolerance is not a
gain" case; float-noise rounding out of the record; locator round-trips and unknown
keys; column-index matching (exact then normalized); unlabelled-row keying; the cell
check naming which claim field it matched; the column check's `matching_rows` /
`nearest_row` signals; every dataset-statistic error path; both standard-deviation
definitions; the refusal to silently drop a non-numeric CSV row; the five assertion
levels including polarity judged on the quoting sentence only; comparison direction,
reversal, and delta disagreement; observable parsing including the refusal to guess
between rival metric lines; the real subprocess runner's stdout, non-zero exit, and
timeout; the machine-independent recorded command; dangling links as `error`; check
ordering, id uniqueness, purity, and determinism; and eight CLI paths.

## Status

**Complete.** Next: **M6 — Reproducibility sandbox** (temp dir, timeout,
stdout/stderr/exit capture, no-network policy, trace record), which replaces
`SubprocessScriptRunner` behind the `ScriptRunner` protocol this milestone
introduced.
