# SCORING — support labels, reproduction status, failure modes

Milestone 7. Scoring is the one stage in the pipeline allowed to draw an inference.
Extraction (M3) recovered the claim's fields, linking (M4) said where to look, the
checks (M5) read the artifacts, and the sandbox (M6) ran the scripts. None of them
decided anything about the claim. This stage does.

```bash
claimverifier verify --task tasks/table_claims/contradicted_f1.yaml
claimverifier verify --task A.yaml --task B.yaml --out results/runs/   # + aggregate summary
```

Everything below is a pure function of the checks it is handed. No wall clock, no RNG,
no filesystem, no LLM. A verdict a reader cannot re-derive is an opinion.

## 1. Signals: a check's status is not its meaning

A check's `status` is a fact about the **check**. Scoring needs a fact about the
**claim**, and one status maps to more than one answer. Each check is therefore first
reduced to a `Signal` — `supports`, `refutes`, `ambiguous`, or `undecided` — from its
recorded `status` and `inputs`, and nothing else. The label rules then read only
signals.

Three reductions carry the design:

| Check | Status | Signal | Why |
| --- | --- | --- | --- |
| `evidence_presence` | `fail` (`polarity_mismatch`) | **refutes** | The passage has the claim's tokens and negates them. |
| `evidence_presence` | `fail` (`absent`) | **undecided** | The passage never mentions the claim. Silence is not refutation. |
| `table_value` | `pass` (cell locator) | **supports** | The value is where the claim said it would be. |
| `table_value` | `pass` (column, >1 row) | **ambiguous** | The value appears *somewhere* in the column; the claim never said which row. |
| `code_execution` | `pass` (output declared) | **supports** | The script printed what the bundle declared. |
| `code_execution` | `pass` (nothing declared) | **undecided** | Exit 0 alone is not evidence for any number. |

The remaining reductions are unsurprising: `dataset_statistic`, `numeric_tolerance`,
`comparison`, and `figure_recompute` have exactly two verdicts (`pass` → supports,
`fail` → refutes), and `error`/`skipped` decide nothing anywhere.

## 2. Support label

Five ordered rules. The first that fires wins, and it is recorded by name, with the
`check_id`s it consulted, into the trace and the report.

| Rule | Fires when | Label |
| --- | --- | --- |
| `artifacts_refute` | any check refutes | `contradicted` |
| `claim_ambiguous` | nothing refutes, some check cannot tell *which* value the claim means | `underspecified` |
| `all_checks_support` | every check reached a verdict, and all support | `supported` |
| `some_checks_support` | some support, some undecided, none refute | `partially_supported` |
| `nothing_decided` | no check reached a verdict | `unverifiable_from_artifacts` |
| `no_checks` | there were no checks (guard; unreachable via the CLI) | `not_checked` |

**Order is the argument.** Refutation beats ambiguity: a value absent from a column is
contradicted whether or not the claim also omitted the row. Ambiguity beats support:
`underspecified_split` finds `90.0` in the accuracy column and would otherwise read as
`supported` — but the table reports 90.0 on dev and 82.0 on test, and the claim never
says which. That is exactly the overclaim the label exists to prevent.

And `nothing_decided` maps onto `unverifiable_from_artifacts`, **never** onto
`contradicted`. A checker that cannot decide has learned nothing about the claim.

## 3. Reproduction status

A *reproduction* re-derives a number from an artifact. Two check types do that:
`code_execution` runs the script; `dataset_statistic` recomputes the statistic from the
CSV. A claim with neither is `not_applicable` — **reading a value out of a table cell
is a lookup, not a reproduction**, and calling it one would inflate every table claim in
the suite into a reproduced result.

| Status | Assigned when |
| --- | --- |
| `reproduced` | the recomputed number matched the claim exactly (signed difference 0) |
| `approximately_reproduced` | it landed inside the tolerance but not on the value |
| `failed_numeric_mismatch` | it ran and produced the wrong number |
| `failed_missing_code` | the script is absent, or its link resolves to nothing |
| `failed_missing_data` | the dataset is absent or unusable |
| `failed_environment` | it timed out, exited non-zero, or the sandbox could not enforce its policy |
| `not_attempted` | `--no-execute`, or nothing was declared to compare against |
| `not_applicable` | the claim exercises no reproduction channel |

`reproduced` and `approximately_reproduced` are kept apart because the checks derive
their tolerance from the claim's own reported precision, so "within tolerance" can mean
a real gap the claim's wording simply failed to exclude.

**Execution failure is not numeric disagreement.** This is why `code_execution` judges
*execution* and a separate `numeric_tolerance` check judges *agreement*: a script that
will not run tells you nothing about the claim's number. `failed_environment` for a
timeout is a deliberate coarsening — the vocabulary has no `failed_timeout` — and the
failure mode records `execution_timeout` alongside, so nothing is lost.

When a claim exercises both channels, each yields a status and the **worst** wins
(`reproduced` < `approximately_reproduced` < `not_attempted` < `failed_numeric_mismatch`
< `failed_missing_data` < `failed_missing_code` < `failed_environment`). A script that
reproduced does not excuse a dataset that went missing. No committed fixture exercises
both, so this rule is pinned by unit tests rather than by a task.

## 4. Failure mode

A support label says the claim is not backed. A failure mode says what to go and fix.
That is what makes an aggregate result diagnostic instead of a pass rate: eight
`contradicted` claims are one number, but "six table-cell mismatches and two paraphrases
the lexical checker could not read" is a work list.

`causes()` names **every** reason the claim is not clean; `classify_failure()` picks one
by priority, and the rest survive on the result as `limitations`.

```
table_cell_mismatch → statistic_mismatch → numeric_out_of_tolerance
  → execution_timeout → execution_error → missing_code → missing_data
  → underspecified
  → passage_does_not_assert → evidence_undecidable → missing_evidence_link → other
```

Most concrete refutation first; the checker's own reach last. Everything below
`underspecified` is a statement about **the checker**, not about the paper.

### `evidence_undecidable` vs. `passage_does_not_assert`

`FailureMode.EVIDENCE_UNDECIDABLE` was added to the schema in this milestone
(`SCHEMA_VERSION` 1.1 → 1.2, additive). `CheckStatus.INCONCLUSIVE` arrived with the
checks in M5 and had no failure mode to map onto, and the nearest existing value —
`passage_does_not_assert` — asserts something the pipeline does not know.

`synthetic_data_passage`'s passage *does* assert its claim; a bag-of-words rule simply
cannot see it. Recording `passage_does_not_assert` there would have published the
checker's ignorance as a fact about the paper.

| Mode | Means |
| --- | --- |
| `passage_does_not_assert` | The passage negates the claim, or shares no token with it. |
| `evidence_undecidable` | The lexical check **could not tell**, and says so. |

### Coarse mappings, named

Two mappings lose information, and both are deliberate:

- **`comparison` failing** (the asserted *relation* does not hold) is recorded as
  `numeric_out_of_tolerance`. The check does apply a tolerance threshold, so this is
  fair, but a dedicated `relation_does_not_hold` would be more precise.
- **`code_execution` failing** (the script ran, but stdout lacks the bundle's declared
  expectation) is recorded as `other`. The declared expectation may be arbitrary text,
  so neither the numeric modes nor `execution_error` — the script executed fine —
  describes it.

### `none` does not mean "clean"

`failure_mode: none` means *nothing failed*. A claim scored `partially_supported` with
`reproduction_status: not_attempted` and `failure_mode: none` is the honest record of
`--no-execute`: nothing was attempted, so nothing broke. What went unchecked is in
`limitations`.

## 5. Confidence is decidedness, not probability

`VerificationResult.confidence` is the **share of the claim's checks that reached a
`pass`/`fail` verdict**. It is not calibrated against anything and it is not a
probability that the label is correct. It answers one narrow question — *how much of
this claim could the artifacts decide?* — and a claim whose only check is `inconclusive`
scores `0.00` no matter how confident the wording of its label sounds.

## 6. Limitations

Every entry is derived from a check that actually ran: each `undecided` or `ambiguous`
check contributes its reason, and any claim whose script was executed carries the
sandbox caveat — controlled fixture execution, not a security boundary — because that is
true of the verdict whether or not the verdict was favourable.

## 7. Aggregate summary: two kinds of miss

A single accuracy number over support labels hides the difference between a system that
says the wrong thing and one that declines to say anything. For a verification tool that
difference is the whole point.

| Bucket | Meaning |
| --- | --- |
| `conservative_misses` | Predicted a **non-committal** label (`unverifiable_from_artifacts`, `not_checked`) where gold commits. The system declined to decide. It asserted nothing false. |
| `wrong_verdicts` | Asserted a committal label the gold outcome disagrees with. **These are the mistakes.** |

Over the committed fixtures `wrong_verdicts` is **0**, and it is the number to watch: a
change to the extractor, the linker, or the checks that raises label accuracy by turning
a conservative miss into a wrong verdict has made the tool worse. See `docs/RESULTS.md`.

## 8. `error_kind`: causes from data, not prose

Scoring must tell "the script is missing" from "the sandbox broke" — they are different
reproduction statuses and different failure modes. So every `error` check now records a
closed-vocabulary `inputs.error_kind` (`checks.ErrorKind`), and scoring maps it with a
table lookup rather than by matching English in `notes`.

`dangling_link` · `missing_passage` · `missing_data` · `unreadable_data` ·
`missing_code` · `sandbox_failure` · `execution_timeout` · `nonzero_exit` ·
`missing_column` · `missing_row` · `non_numeric_cell` · `empty_column`

A check's `notes` remain the human explanation; this is the machine one.

## 9. The trace

Every run emits a `RunTrace` as JSONL: the claim, the evidence, one event per check
(with its signal), one event per classifier (with the rule name, the reason, and the
`check_id`s it read), and the result.

```
scoring.claim → scoring.evidence → scoring.check ×N
  → scoring.support → scoring.reproduction → scoring.failure → scoring.result
```

Keys are sorted and nothing is read from the wall clock, so two runs of one task produce
byte-identical bytes — including tasks whose script actually executes. `created_at` stays
unset for the same reason. The only machine-dependent value written anywhere is
`result.json`'s `trace_path`, which is the `--out` directory the caller chose.

## 10. Not implemented, and why

- **`run-suite` and `report`.** Milestones 8 and 9. `verify --task A --task B` already
  emits the aggregate summary the suite will use.
- **A calibrated confidence.** Would require labelled data this project does not have.
  `confidence` is decidedness, and says so everywhere it appears.
- **`relation_does_not_hold`.** See the coarse mappings above.
- **Cross-claim consistency.** Each claim is scored independently; the pipeline never
  asks whether two claims in one bundle contradict each other.
