# M7 — Scoring & failure modes

## Summary

Introduces the `scoring/` package and `claimverifier verify`: the first stage in the
pipeline allowed to draw an inference. It turns the Milestone 5 checks into a
`VerificationResult` — a support label, a reproduction status, a failure mode, a
decidedness score, and the limitations that survive the verdict — plus a JSONL trace in
which **every inference names the rule that produced it and the check IDs that rule
read**.

Four ideas carry the milestone.

**A check's `status` is a fact about the check, not about the claim.** Scoring never
reads `status` directly. Each check is first reduced to a `Signal` — `supports`,
`refutes`, `ambiguous`, `undecided` — and the mapping is not one-to-one in either
direction. `evidence_presence` *fails* two different ways: a passage that **negates** the
claim refutes it, while a passage that never mentions it refutes nothing — silence is
not refutation. `table_value` *passes* two different ways: the value in the cell the
claim named supports it, while the same value found somewhere in a column of several
rows means the claim is **ambiguous**, which is what `underspecified` means.
`code_execution` *passes* two different ways: printing the output the bundle declared
supports the claim, while exit 0 with nothing declared is not evidence for any number.
Collapsing any of these three pairs would either overclaim or manufacture a
contradiction.

**Refutation beats ambiguity beats support, and the order is the argument.** Five ordered
rules assign the support label. `underspecified_split` genuinely *does* find `90.0` in
the accuracy column — the table reports 90.0 on dev and 82.0 on test, and the claim never
says which — so `claim_ambiguous` fires before `all_checks_support` and the label is
`underspecified`, not `supported`. And `nothing_decided` maps onto
`unverifiable_from_artifacts`, never onto `contradicted`: a checker that cannot decide has
learned nothing about the claim.

**`evidence_undecidable` (schema 1.2) exists because `inconclusive` had nowhere honest to
land.** M5 added `CheckStatus.INCONCLUSIVE` so a lexical check faced with a paraphrase
could say *"I cannot tell"* instead of `fail`. But `FailureMode` had no matching value,
and the nearest one — `passage_does_not_assert` — asserts something the pipeline does not
know. `synthetic_data_passage`'s passage *does* assert its claim; a bag-of-words rule
simply cannot see it. Recording `passage_does_not_assert` there would have published the
checker's ignorance as a fact about the paper. The addition is additive: every 1.0
document stays valid.

**Reading a table cell is a lookup, not a reproduction.** Only `code_execution` and
`dataset_statistic` re-derive a number, so a claim with neither is `not_applicable`.
Treating a table lookup as a reproduction would have inflated three of the seven fixtures
into reproduced results and made `reproduction_status` meaningless as a signal.

**The measured result: 0 wrong verdicts.** A mismatch against gold is bucketed by kind. A
*conservative miss* predicts a non-committal label where gold commits — the system
declined to decide and asserted nothing false. A *wrong verdict* asserts a committal label
gold disagrees with. Over the seven fixtures: 6/7 support labels, 7/7 reproduction
statuses, 6/7 failure modes, **0 wrong verdicts**, and 1 conservative miss
(`synthetic_data_passage`). That last is the number to watch: a change to the extractor,
the linker, or the checks that raises label accuracy by turning a conservative miss into a
wrong verdict has made the tool worse.

## Deliverables

- **`src/scientific_claim_verifier/scoring/`** (new package, per `docs/PLAN.md` §5):
  - `__init__.py` — `Signal`, `Rule`, `CheckSignal`, the per-check-type reducers,
    `error_kind`, `is_ambiguous_column`, `decidedness`.
  - `support_labels.py` — the five ordered rules and their names.
  - `reproducibility.py` — `Channel`, the `SEVERITY` worst-wins order, `classify_reproduction`.
  - `failure_modes.py` — `Cause`, `causes`, `MODE_PRIORITY`, `classify_failure`, `limitations`.
  - `verdict.py` — `score`, `build_trace`, `render_result`, `verify_task`, and the
    `verify` CLI (an addition beyond `docs/PLAN.md` §5's three modules, mirroring
    `checks/verification.py`).
  - `summary.py` — `TaskOutcome`, `SuiteSummary`, `conservative_misses` vs.
    `wrong_verdicts`. M8's smoke suite builds on this.
- **`schemas.py`** — `FailureMode.EVIDENCE_UNDECIDABLE`; `SCHEMA_VERSION` 1.1 → 1.2.
- **`checks/__init__.py`** — new `ErrorKind` closed vocabulary (12 values).
- **`checks/{code_execution,statistical,table_recompute,consistency,verification}.py`** —
  every `error` path now records `inputs.error_kind`; `code_execution` also records
  `inputs.declared_expectations` on every outcome. **No check's status changed**; the
  M5 table is still 18 checks, 16 pass / 1 fail / 1 inconclusive.
- **CLI:** `claimverifier verify --task X [--task Y …] [--out DIR] [--json]
  [--no-declared-source] [--no-execute] [--abs-tol F] [--rel-tol F]`.
- **Tests:** `tests/test_scoring.py` (100) and 6 added to `tests/test_checks.py`. 452 total.
- **Docs:** `docs/SCORING.md` (new); `CLAIM_SCHEMA`, `CHECKS`, `RESULTS`, `README` updated.
- **Website:** `index`, `checks`, `reproducibility`, `results`, `example-report`,
  `milestones`, `limitations`.

## Design decisions

- **`ErrorKind` was added to the M5 checks so M7 could classify causes from data.** The
  failure-mode and reproduction taxonomies must tell `missing_code` from `sandbox_failure`
  from `execution_timeout` from `nonzero_exit`. Discriminating them from the shape of
  `inputs` was fragile (a `SandboxError` and a missing script both lack `exit_code`), and
  matching English in `notes` is not a contract. Each `error` path now stamps one of
  twelve closed-vocabulary values, and scoring maps them with a table lookup. This is the
  only change to a prior milestone's behaviour, and it moved no verdict.
- **`code_execution` records `declared_expectations`.** Without it, "exit 0" was
  indistinguishable from "printed the declared output", and the check would have supported
  a claim it verified nothing about. It is recorded on every outcome, including `skipped`.
- **`confidence` is decidedness, and says so everywhere it appears.** The schema has the
  field; inventing a calibrated probability would need labelled data this project does not
  have. It is defined as the share of a claim's checks that reached a `pass`/`fail`
  verdict, so `synthetic_data_passage` scores `0.00` — *nothing about this claim was
  decided* — and the report prints the definition next to the number.
- **`failure_mode: none` means "nothing failed", not "clean".** `--no-execute` yields
  `partially_supported` / `not_attempted` / `none`, which is the honest record: nothing was
  attempted, so nothing broke. What went unchecked is in `limitations`. The rule is named
  `no_failure_named` rather than the bug-sounding `no_cause_found`.
- **Every rule is a named object, not a comment.** `Rule(name, because, check_ids)` is
  returned by each classifier and written into the trace and the report. "Why does this
  claim say `contradicted`?" is answered by a lookup, not by re-reading the code.
- **`causes()` names every reason; the winner is one of them.** A claim contradicted by its
  table *and* undecidable from its text is not fully described by either fact, so the
  losers survive in the failure rule's `because` and in `limitations`.
- **Two coarse mappings, both named in `docs/SCORING.md`.** A failing `comparison` (the
  *relation* does not hold) is recorded as `numeric_out_of_tolerance` — fair, since the
  check does apply a threshold, but a `relation_does_not_hold` would be more precise. A
  failing `code_execution` (ran, printed the wrong text) is recorded as `other`, since the
  declared expectation may be arbitrary text and `execution_error` would be false.
- **Worst-wins across reproduction channels.** A script that reproduced does not excuse a
  dataset that went missing. No fixture exercises both channels, so the rule is pinned by
  unit tests rather than by a task — and `docs/SCORING.md` says so.
- **`verify` exits `0` on a `contradicted` claim.** Finding a contradiction is the tool
  working, not failing. Exit `1` is reserved for a task that cannot be loaded.
- **The trace holds no path and no clock.** `RunTrace.to_jsonl` serializes only events, and
  no event carries `trace_path`. Two runs of one task produce byte-identical bytes,
  including `recompute_accuracy`, whose script actually executes. The one
  machine-dependent value written anywhere is `result.json`'s `trace_path`, which is the
  `--out` directory the caller chose.
- **No new dependencies.** `dataclasses`, `enum`, `collections.Counter`, `json`, `argparse`.

## Validation

Commands run (CPU-only, offline):

| Command | Result |
| --- | --- |
| `python3 -m pytest -q` | 452 passed (346 prior + 106 new) |
| `ruff check .` | All checks passed |
| `python3 scripts/01_validate_fixtures.py` | 7 ok, 0 failed, 0 warnings — VALID (exit 0) |
| `python3 scripts/00_check_environment.py` | exit 0 — `READY` |
| `claimverifier verify --task <task>` | verdict + rules + trace, exit 0 |
| `claimverifier run-checks --task <task>` | 18 checks over 7 fixtures — **unchanged** |
| site served on :9002, 11 pages fetched via `urllib` | 200, balanced HTML, no broken links |

### Verdicts over the committed fixtures

| Task | Support label | Reproduction | Failure mode | vs. gold |
| --- | --- | --- | --- | --- |
| `accuracy_improvement` | `supported` | `not_applicable` | `none` | ✓ ✓ ✓ |
| `contradicted_f1` | `contradicted` | `not_applicable` | `table_cell_mismatch` | ✓ ✓ ✓ |
| `dataset_mean` | `supported` | `reproduced` | `none` | ✓ ✓ ✓ |
| `gc_content` | `supported` | `reproduced` | `none` | ✓ ✓ ✓ |
| `recompute_accuracy` | `supported` | `reproduced` | `none` | ✓ ✓ ✓ |
| `underspecified_split` | `underspecified` | `not_applicable` | `underspecified` | ✓ ✓ ✓ |
| `synthetic_data_passage` | `unverifiable_from_artifacts` | `not_applicable` | `evidence_undecidable` | ✗ ✓ ✗ |

**support 6/7 · reproduction 7/7 · failure mode 6/7 · wrong verdicts 0/7 · conservative
misses 1/7.**

Seven hand-authored synthetic fixtures whose gold outcomes were written alongside the
rules that score them: a regression harness, not a benchmark. What the table shows is that
the rule table is coherent (no fixture needs a special case), that it never asserts a
verdict gold contradicts, and that the one claim its methods cannot read is *reported as
unread* rather than guessed at.

The tests additionally pin: every status→signal reduction, including the two ways
`evidence_presence` fails, the two ways `table_value` passes, and the two ways
`code_execution` passes; a single-row column being unambiguous; refutation outranking
ambiguity and ambiguity outranking support; `absent` and `inconclusive` both landing on
`unverifiable_from_artifacts`; every `ErrorKind` → `ReproductionStatus` and
`ErrorKind` → `FailureMode` mapping; exact vs. approximate reproduction, and a passing
check with no recorded `difference` degrading to `approximately_reproduced`; a script with
nothing to compare against reproducing nothing; worst-wins across two channels;
`MODE_PRIORITY` covering every mode a cause can produce; `SEVERITY` covering every status
but `not_applicable`; the most concrete refutation winning while the losers survive in
`because`; a skipped check being a limitation rather than a failure; a clean code claim
still carrying the sandbox caveat; the eight trace events and their order; two runs of one
task producing byte-identical JSONL, including a task whose script executes; the
`conservative_miss` / `wrong_verdict` bucketing in all four combinations; and nine CLI
paths including `--json`, `--out`, `--no-execute`, a repeated `--task` with an aggregate
summary, an unloadable task exiting 1, a `contradicted` claim still exiting 0, and
`scoring.verdict.main()` as a direct entry point.

## Status

**Complete.** Next: **M8 — Smoke suite** (8–15 tasks run fully offline; saved run traces,
results, a summary CSV/JSON, and reports). It builds directly on `scoring/summary.py`,
which already emits the aggregate `verify --task A --task B …` prints today.
