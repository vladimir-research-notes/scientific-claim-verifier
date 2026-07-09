# REPRODUCIBILITY

How to reproduce every number in this repository, offline, on one CPU, for free.

`docs/RESULTS.md` reports the measured outcomes and explains how to read them. This
document is the operational counterpart: the environment, the commands, what is
byte-reproducible and what is not, and — in §2 — a table of headline numbers that a
test re-derives from the live pipeline on every run, so that a doc which drifts from
the code **fails the build**.

---

## 1. Environment

| | |
| --- | --- |
| Target hardware | AWS `m5.2xlarge`, CPU-only. No GPU, at any point. |
| Python | `>= 3.11` (developed and measured on 3.12) |
| Runtime dependencies | `pydantic >= 2`, `pyyaml >= 6` — that is the whole list |
| Dev dependencies | `pytest >= 7`, `ruff >= 0.5` |
| Network | never, in any test or default-path command |
| Paid API | never, in any default-path command |

No install is required to run the tests: `pyproject.toml` sets `pythonpath = ["src"]`,
so `pytest` imports the package straight from the source tree. An editable install is
only needed for the `claimverifier` console script.

```bash
git clone <this repo> && cd scientific-claim-verifier
pip install -e .            # optional; only for the `claimverifier` entry point
python3 scripts/00_check_environment.py     # offline interpreter + library self-check
```

Every command below has a script form (no install needed) and a CLI form. They are the
same code path; the scripts are thin wrappers.

## 2. The headline numbers

Each row is re-derived from a live suite run by
`tests/test_docs.py::test_reproducibility_headline_numbers_match_the_live_pipeline`.
If the pipeline's behaviour changes and this table is not updated, that test fails.
**This table is checked, not maintained by hand.**

| Key | Value | Reproduce with |
| --- | --- | --- |
| `tasks` | 11 | `claimverifier run-suite` |
| `checks` | 26 | `claimverifier run-suite` |
| `checks_pass` | 20 | `claimverifier run-suite` |
| `checks_fail` | 3 | `claimverifier run-suite` |
| `checks_inconclusive` | 1 | `claimverifier run-suite` |
| `checks_error` | 1 | `claimverifier run-suite` |
| `checks_skipped` | 1 | `claimverifier run-suite` |
| `scripts_executed` | 3 | `claimverifier run-suite` |
| `wrong_verdicts` | 0 | `claimverifier run-suite` |
| `conservative_misses` | 1 | `claimverifier run-suite` |
| `support_agreement` | 10 | `claimverifier run-suite` |
| `reproduction_agreement` | 11 | `claimverifier run-suite` |
| `failure_agreement` | 10 | `claimverifier run-suite` |
| `export_formats` | 5 | `claimverifier export --list` |
| `cli_commands` | 13 | `claimverifier --help` |
| `final_checks` | 17 | `claimverifier final-check` |

Two of these are the ones to read. **`wrong_verdicts` is 0**: the pipeline has never
asserted a support label its own fixtures deny. **`conservative_misses` is 1**: it
declines to decide `synthetic_data_passage` rather than guessing. Do not sum them, and
do not replace them with `support_agreement` — see `docs/METHODOLOGY.md` §7.

Numbers deliberately **not** in the table: the test count (a test that asserts how many
tests exist is self-referential and rots on contact), and any wall-clock timing (§6).

## 3. Reproducing each result

Run in this order; each is independent and offline.

### Everything at once

```bash
python3 -m pytest -q                        # 1004 tests, CPU-only, offline
python3 -m ruff check .                     # lint
python3 scripts/01_validate_fixtures.py     # 11 tasks + 1 suite valid
python3 scripts/05_run_smoke_suite.py --out results/runs/    # the gate; exit 0
python3 scripts/08_final_check.py           # all four, plus hygiene; 17 checks, exit 0
```

The last command runs the other four and eleven more, and is the only one whose subject is
the repository rather than a claim. It is what `docs/PLAN.md` §11 means by "done", made
executable — see `docs/FINAL_CHECK.md`, including the four things it cannot check.

### `docs/RESULTS.md` §M2 — fixture validation

```bash
python3 scripts/01_validate_fixtures.py     # or: claimverifier validate-fixtures tasks/
```
Expect `11 tasks ok, 1 suite ok, 0 failed, 0 warnings — VALID`.

### §M3 — claim extraction vs. gold

```bash
python3 -m pytest tests/test_extraction.py -q
claimverifier extract-claims --task tasks/table_claims/accuracy_improvement.yaml
```
Per-field recovery against each task's `expected.claim`; the `Rules fired` block names
the rule behind every field. `8/8 scored fields match` on ten of eleven fixtures;
`synthetic_data_passage` scores 7/8 (`conditions`).

### §M4 — evidence linking vs. gold

```bash
python3 -m pytest tests/test_linking.py -q
claimverifier link-evidence --task tasks/ml_claims/underspecified_split.yaml --no-declared-source
```
`--no-declared-source` ignores the task's authored `claim.source_passage` and links
passages blind — the setting under which retrieval is worth measuring. Strict 21/21
gold links recovered, 0 spurious.

### §M5 — verification checks

```bash
python3 -m pytest tests/test_checks.py -q
claimverifier run-checks --task tasks/table_claims/contradicted_f1.yaml
```
Prints supporting text and computed checks as separate blocks, and assigns **no**
verdict. On `contradicted_f1` the passage check passes and the table check fails; that
is the fixture working, not a bug.

### §M6 — the sandbox

```bash
python3 -m pytest tests/test_sandbox.py -q
claimverifier run-sandbox --task tasks/code_reproduction/recompute_accuracy.yaml
```
The policy is printed *before* the number, and recorded before it in the trace:
`accuracy=0.80` is not a result until you know what produced it.

### §M7 — scoring

```bash
python3 -m pytest tests/test_scoring.py -q
claimverifier verify --task tasks/ml_claims/synthetic_data_passage.yaml
```
`verify` exits **0** on a `contradicted` claim — finding a contradiction is the tool
working. Repeat `--task` to score several and get an aggregate summary.

### §M8 — the smoke suite (the gate)

```bash
python3 scripts/05_run_smoke_suite.py --out results/runs/    # or: claimverifier run-suite
echo $?      # 0
```
Eleven tasks end to end. Writes a JSONL trace and a result JSON per task, plus
`summary.csv`, `summary.json`, `summary.txt` into `results/runs/smoke_suite/`.

### §M9 — reports, rendered from traces

```bash
python3 -m pytest tests/test_reports.py -q
claimverifier report --run results/runs/smoke_suite --out results/reports/
```
Twelve files for eleven claims (eleven reports plus an index), reading nothing but the
traces. Add `--format both` for standalone HTML.

### §M10 — the optional adapters (still free)

```bash
python3 -m pytest tests/test_adapters.py -q
python3 scripts/06_record_llm_fixtures.py     # asserts the recordings are current
claimverifier extract-claims --task tasks/table_claims/accuracy_improvement.yaml --extractor recorded
```
The `recorded` extractor replays four committed, **hand-authored** synthetic responses.
No API is called; no language model produced them.

### §M11 — exports, and the replay round trip

```bash
python3 -m pytest tests/test_integrations.py -q
claimverifier export --list
claimverifier run-suite --out results/runs/
claimverifier export --format episodes --run results/runs/smoke_suite --out ep.json
claimverifier replay --episodes ep.json --strict
```
`replay` re-runs the whole pipeline — extraction, linking, checks, the three fixture
scripts in the sandbox — and compares against the recorded verdict and trace digest.
Expect `Reproduced: 11/11`, `PASS`.

## 4. Determinism: what is byte-reproducible

Nothing determinism-critical reads the wall clock or an RNG. Concretely, and asserted by
tests that hash artifacts across two runs into two directories:

**Byte-identical across runs and across output directories**

- all eleven `<task_id>.trace.jsonl` — including the three whose scripts actually execute
- `summary.csv` (it names each trace by filename alone, so it stays portable)
- `summary.json`
- every Markdown and HTML report
- every one of the five export documents (sorted-key JSON, no absolute paths)

**Not byte-identical, by construction, in exactly one field each**

| Artifact | The field | Why |
| --- | --- | --- |
| `<task_id>.result.json` | `trace_path` | records the absolute path of its own trace |
| `summary.txt` | the output directory | it names the directory it was written to |

Both are paths the caller chose. A test hashes every artifact of two runs and diffs
these two exceptions field by field.

## 5. Determinism: what is not, and why

- **Wall-clock duration** is measured (≈30 ms per fixture script) and deliberately kept
  out of the trace unless `--with-timing` is passed. It is the only value in an execution
  record that cannot be reproduced.
- **A failing script's traceback** embeds the host's stdlib paths, because captured output
  is recorded verbatim apart from the sandbox path. Traces of *failing* runs are therefore
  reproducible per machine, not across machines. Redacting the traceback would be worse.
- **The interpreter is not pinned.** Fixture scripts run under whichever Python invoked
  them, and the trace does not record the version.

## 6. Timing, and why it is not in the headline table

On the target CPU the whole suite — eleven tasks, twenty-six checks, three scripts
executed in the sandbox — runs in about **1.5 seconds**, and the full test suite in about
**23 seconds**. Both numbers are reported as approximations and neither is asserted
anywhere, because a machine-dependent number that a test pins is a test that fails on a
slower machine for no reason.

Two tests *are* load-bearing on the wall clock: the `RLIMIT_CPU` test burns ~1 CPU-second
and the process-group test waits ~1 s for its timeout. Both assert that something was
**killed**, so a slow machine makes them more likely to pass, not less.

## 7. What a green build actually proves

`pytest` passing, `ruff` clean, fixtures valid, and the suite gate at `PASS` together mean:

> This commit did not make the pipeline assert something its own fixtures deny, did not
> change the set of claims it declines to decide, and did not break the trace → report →
> export → replay round trip.

It does **not** mean the verdicts are right, and it certainly does not mean the claims are
true. The fixtures are a regression harness, not a benchmark; see `docs/LIMITATIONS.md` §4
and `docs/PAPER_PATH.md`.

## See also

- `docs/RESULTS.md` — the measured outcomes and how to read each one
- `docs/METHODOLOGY.md` — why the gate is asymmetric, and why determinism is a precondition
- `docs/SANDBOX.md` — what execution enforces, guard by guard, with the test that fires it
- `docs/INTEGRATIONS.md` — the export contracts and the four replay statuses
