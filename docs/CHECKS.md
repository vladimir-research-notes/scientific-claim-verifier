# CHECKS — the deterministic verification checks

Milestone 5. A **check** takes an extracted claim (`docs/EXTRACTION.md`) and the
evidence links that say *where to look* (`docs/EVIDENCE_LINKING.md`), reads the
artifact at that locator, computes something, and records a `VerificationCheck`.

Reach them with:

```bash
claimverifier run-checks --task tasks/table_claims/contradicted_f1.yaml
python3 scripts/03_run_checks.py --task <task.yaml> [--json] [--no-execute]
```

## A check does not decide the claim's fate

Checks produce *evidence about* a claim. The support label, the reproduction
status, and the failure mode are **inferences** drawn from the whole set of
checks, and they belong to scoring (Milestone 7). `run-checks` prints the checks
and says so explicitly; it never emits a verdict.

This is not pedantry, and one committed fixture exists to prove it.
`contradicted_f1` claims *"Method B reaches an F1 score of 91.0 on MNLI"*. The
paper's own abstract states exactly that, so `evidence_presence` **passes**. The
paper's own results table reports 86.0, so `table_value` **fails**. Both are true.
A system that collapsed them into one number would destroy the only interesting
fact about this claim: the paper contradicts itself, and a reader needs to see
both channels to know that.

## Five outcomes, not two

| Status | Meaning | Typical scoring consequence (M7) |
| --- | --- | --- |
| `pass` | The check ran; the artifacts agree with the claim. | supports `supported` |
| `fail` | The check ran; the artifacts **disagree**. | supports `contradicted` |
| `inconclusive` | The check ran; its **method cannot decide**. | `unverifiable_from_artifacts` |
| `error` | The check could not run (missing file, dangling link, crash). | `failed_*` |
| `skipped` | The check did not apply (nothing was located). | `not_checked` |

`inconclusive` was added to `CheckStatus` in this milestone (schema `1.1`, an
additive change). Without it, a transparent lexical check faced with a paraphrase
would have to report `fail`, and scoring would manufacture a *contradiction* out
of the checker's own ignorance. The distinction between "the artifacts say you are
wrong" and "I cannot tell" is the difference between an auditable tool and a
confident one.

## Tolerance is read off the claim, not chosen

Numeric comparisons never use exact float equality. The default tolerance is the
claim's own **reported precision**: half of the last decimal place of the number
*as it was written*.

| Claim text | Value | Tolerance | Reasoning |
| --- | --- | --- | --- |
| `a mean value of 3.4` | 3.4 | ±0.05 | anything that rounds to 3.4 |
| `an accuracy of 0.80` | 0.80 | ±0.005 | two decimals were reported |
| `reaches 90% accuracy` | 90 | ±0.5 | reported to the nearest integer |
| `12 samples` | 12 | ±0 | a count is exact |

So the tolerance is a property of how the claim was *stated*, not a constant tuned
until the fixtures went green. The effective threshold applied to
`|computed − expected|` is `max(abs_tol, rel_tol · |expected|)`, and it is recorded
on every check next to the signed difference.

Overrides, in precedence order:

1. `--abs-tol` / `--rel-tol` on the command line;
2. a `tolerance: {abs_tol, rel_tol}` block in the task file;
3. the claim's reported precision;
4. float noise (`1e-9`), when the claim's number appears nowhere in its own text.

**Limitation.** `78` and `78.0` mean different things to this rule (±0.5 vs ±0.05),
which is correct in principle and surprising in practice. A claim that rounds `78.04`
to `78.0` is consistent; one that rounds `78.4` is not.

## The checks

| Check | Module | Reads | Answers |
| --- | --- | --- | --- |
| `evidence_presence` | `checks/consistency.py` | the linked passage | Does the text *assert* the claim? |
| `table_value` | `checks/table_recompute.py` | `row=A,col=accuracy` or `col=accuracy` | Is the claimed value in that cell / column? |
| `comparison` | `checks/consistency.py` | two located cells | Does the asserted relation hold in the artifacts? |
| `dataset_statistic` | `checks/statistical.py` | `column=value` in a CSV | Does the recomputed statistic match? |
| `code_execution` | `checks/code_execution.py` | a fixture script's `stdout` | Does the script run and print the declared observable? |
| `numeric_tolerance` | `checks/statistical.py` | a value another check produced | Does the number the artifacts produced match the claim's? |
| `figure_recompute` | *not implemented* | — | see **Not implemented**, below |

### `evidence_presence`

The counterpart to evidence linking. The linker *retrieves* the passage most
lexically similar to the claim and explicitly refuses to judge it; this check asks
the narrower, answerable question. It reports one of five assertion levels:

| Level | Rule | Status |
| --- | --- | --- |
| `verbatim` | the claim's canonicalized text occurs in the passage | `pass` |
| `token_subsumed` | every content token of the claim occurs, polarity matching | `pass` |
| `polarity_mismatch` | tokens all present, but the quoting sentence negates the claim | `fail` |
| `partial_overlap` | some claim tokens are missing | **`inconclusive`** |
| `absent` | no claim token occurs at all | `fail` |

Negation is checked on the passage's **best-matching sentence**, not the whole
passage, and only where it can flip a would-be `pass`: a paper may negate something
else nearby without negating the claim. Cues are a closed set of function words
(`no`, `not`, `never`, `none`, `nor`, `neither`, `without`, `cannot`), which survive
stopword removal by design.

**Known limits.** Contractions do not tokenize as cues (`does not` is caught,
`doesn't` is not). Verbatim containment is not polarity-checked, so a passage
reading *"it is not true that X"* would pass on `X`. Morphology and synonymy are
absent: `trained` does not match `training`.

### `table_value`

Two locator shapes, two questions:

- `row=A,col=accuracy` — the claim named the row, so one cell is read and compared.
- `col=accuracy` — the claim named no row, so the question weakens to *does the
  claimed value appear anywhere in this column?* A hit is a `pass`, and
  `inputs.matching_rows` / `inputs.n_rows` record that the claim is **ambiguous over
  the column**. A miss is a `fail`, and the nearest cell is recorded.

That single distinction separates the two column-linked fixtures:

| Fixture | Claim | Column | `matching_rows` | Status |
| --- | --- | --- | --- | --- |
| `underspecified_split` | 90.0 | `dev 90.0`, `test 82.0` | `["dev"]` | `pass` (ambiguous over 2 rows) |
| `contradicted_f1` | 91.0 | `baseline 84.0`, `B 86.0` | `[]` | `fail` (nearest 86.0 at row B) |

Same locator, opposite verdict. The `inputs` are what let M7 tell `underspecified`
from `contradicted`.

The linker only emits a cell locator once the cell's value matched a claim value, so
a cell check will usually pass. It is not a tautology: the check reads the table
itself rather than trusting the linker's memo, so the number that reaches the report
is derived from the artifact.

### `comparison`

For *"improves accuracy from 72.0 to 78.0"*: verify the asserted relation between
the two values the artifacts actually hold. It answers *"is the target really
greater than the baseline?"*, not *"is the delta the claimed size?"* — each
magnitude is already checked against its own cell by `table_value`. Strict
operators require the gap to *exceed* the tolerance: a difference smaller than the
claim's reported precision is not an improvement, it is noise.

### `dataset_statistic`

Recomputes the statistic over the located CSV column with the standard library
only. Available: `count`, `sum`, `mean`, `median`, `std`, `std_sample`, `min`,
`max`. Both standard deviations are named explicitly rather than hiding a `ddof`
convention — `std` is the population deviation (`ddof=0`, numpy's default) and
`std_sample` the sample deviation (`ddof=1`, pandas' default).

A stated sample count (`"12 samples"` → the extractor's `n = 12` condition) is a
second, independently checkable assertion about the same dataset, so `dataset_mean`
produces two `dataset_statistic` checks — and the count is compared exactly.

A dataset link with **no column locator** means the linker declined to guess which
column was measured. That is underspecification, so the check is `skipped`, not
`error`. A non-numeric cell is an `error`: a statistic over silently-dropped rows is
a statistic over a different dataset.

### `code_execution` and `numeric_tolerance`

The code channel is split across two checks because the schema must distinguish two
different reproduction outcomes:

- `code_execution` judges **execution**. A timeout, a non-zero exit, or a missing
  file is `error` — a script that will not run says nothing about the claim's
  number. A clean run that omits the observable the bundle declared is `fail`.
- `numeric_tolerance` judges **agreement** between the number the script printed and
  the number the claim asserts.

`failed_environment` and `failed_numeric_mismatch` are different reproduction
statuses, and a report cannot tell them apart from a single boolean. The table and
dataset channels need no such split — reading a cell either works or errors.

The observable is parsed from a `name=value` line in stdout, preferring a name that
matches one of the claim's metrics. If the script prints several unrelated metric
lines and none matches, no value is parsed: picking one would be a guess.

## Sandbox honesty

`SubprocessScriptRunner` runs `python <script>` as a child process with a wall-clock
timeout, `stdin` closed, and stdout/stderr/exit-code captured. That is **all**. It
does not copy the script to a temp directory, scrub the environment, restrict the
filesystem, or block the network. **It is not a security boundary of any kind.** The
scripts it runs are trusted, committed, stdlib-only fixtures in this repository.

Milestone 6 adds the temp working directory, the no-network policy, and the trace
record **behind the same `ScriptRunner` protocol**, so no check changes when it
lands. `PYTHONHASHSEED=0` is set for the child — a determinism measure, not
isolation.

## Determinism

Every check is a pure function of its inputs apart from `code_execution`, which
starts a child process. No wall clock, no RNG, and no absolute filesystem paths
reach a check's recorded output: the executed command is recorded as
`("python", "gc_content.py")`, never the machine's interpreter path, and no duration
is recorded (timing belongs in M6's trace). Floats are rounded to 12 decimal places
before being recorded, so `40.8 / 12` is written `3.4` rather than
`3.4000000000000004` — far below any tolerance in play, so rounding can never flip a
verdict. Checks are emitted in a fixed type order, and `check_id`s are numbered per
type (`c_dataset_mean.dataset_statistic.2`).

## Not implemented, and why

- **`figure_recompute`.** `CheckType.FIGURE_RECOMPUTE` exists and `evidence/figures.py`
  resolves `series=` locators, but no committed fixture has a figure, and the
  Milestone 5 contract in `docs/PLAN.md` §9 does not list it. Regenerating a summary
  table or figure from a dataset (task family 3) is untouched work, not a silent gap.
- **`correlation`.** In scope per `docs/PLAN.md` §3, but it needs a two-column
  locator that the locator grammar does not express and no fixture exercises.
- **A support label.** Milestone 7.

## The locator grammar

Written by the linker, parsed by the checks, defined once in
`evidence/locators.py`: a comma-separated list of `key=value` pairs, plus bare
tokens (`stdout`). Tables say `col` and datasets say `column` because those are the
conventions already committed in the fixtures' gold evidence. Values are not
escaped, so a row label containing `,` or `=` would be ambiguous; no fixture does.

## Results

Measured outcomes over the seven committed fixtures are in `docs/RESULTS.md`.
