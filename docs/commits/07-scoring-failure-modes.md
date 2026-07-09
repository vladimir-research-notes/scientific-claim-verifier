# Commit note — M7 Scoring & failure modes

## Commit message

```
M7: scoring (signals, support labels, reproduction status, failure modes)

Add the scoring/ package -- the one stage allowed to draw an inference -- and the
`claimverifier verify` command that assembles a VerificationResult and a trace:
- scoring/__init__.py: Signal, Rule, CheckSignal, the per-check-type reducers,
  decidedness()
- scoring/support_labels.py: five ordered, named rules
- scoring/reproducibility.py: Channel, SEVERITY worst-wins, classify_reproduction
- scoring/failure_modes.py: Cause, causes(), MODE_PRIORITY, classify_failure,
  limitations()
- scoring/verdict.py: score(), build_trace(), render_result(), the verify CLI
- scoring/summary.py: TaskOutcome, SuiteSummary, conservative_misses vs
  wrong_verdicts (M8's smoke suite builds on this)

A check's `status` is a fact about the CHECK, not about the claim, so scoring never
reads it directly: each check is first reduced to a Signal (supports / refutes /
ambiguous / undecided) and the mapping is not one-to-one. evidence_presence FAILS two
ways -- a passage that negates the claim refutes it; one that never mentions it
refutes nothing, because silence is not refutation. table_value PASSES two ways -- the
value in the cell the claim named supports it; the same value found somewhere in a
multi-row column means the claim is AMBIGUOUS, which is what underspecified means.
code_execution PASSES two ways -- printing the bundle's declared output supports the
claim; exit 0 with nothing declared is not evidence for any number.

Refutation beats ambiguity beats support, and the order is the argument.
`nothing_decided` maps to unverifiable_from_artifacts, NEVER to contradicted: a
checker that cannot decide has learned nothing about the claim. An `error` check is
undecided, never evidence against the claim (this answers the M6 review's question).

Add FailureMode.EVIDENCE_UNDECIDABLE; SCHEMA_VERSION 1.1 -> 1.2 (additive). M5 added
CheckStatus.INCONCLUSIVE with no failure mode to land on, and the nearest existing
value -- passage_does_not_assert -- asserts something the pipeline does not know.
synthetic_data_passage's passage DOES assert its claim; a bag-of-words rule simply
cannot see it.

Add checks.ErrorKind (12 values) and stamp inputs.error_kind on every error path, so
scoring tells missing_code from sandbox_failure from execution_timeout by table lookup
rather than by matching English in `notes`. code_execution also records
inputs.declared_expectations on every outcome. NO CHECK'S STATUS CHANGED: still 18
checks over 7 fixtures, 16 pass / 1 fail / 1 inconclusive.

Reading a table cell is a lookup, not a reproduction: only code_execution and
dataset_statistic re-derive a number, so table claims are not_applicable rather than
inflated into reproduced results. `confidence` is DECIDEDNESS -- the share of checks
that reached a verdict -- not a calibrated probability, and says so wherever it
appears. Every inference names the Rule that produced it and the check_ids that rule
read, into the report and the JSONL trace (byte-identical across runs, including for
tasks whose script executes).

Over the seven fixtures: support 6/7, reproduction 7/7, failure mode 6/7, and the
number that matters -- 0 WRONG VERDICTS. The single miss is a conservative one
(synthetic_data_passage: declined to decide where gold commits). A change that raises
label accuracy by turning a conservative miss into a wrong verdict has made the tool
worse.

Add tests/test_scoring.py (100 new) + 6 in tests/test_checks.py (452 total) and
docs/SCORING.md; update CLAIM_SCHEMA, CHECKS, RESULTS, README, website (index, checks,
reproducibility, results, example-report, milestones, limitations), and
milestone/commit/review notes. example-report.html now shows real `verify` output
instead of a mock.
```

## What this commit adds

- The inference the whole pipeline was built to withhold until it could be justified:
  a support label, a reproduction status, and a failure mode, each produced by a
  **named rule** that records the check IDs it read.
- A `Signal` layer that refuses three tempting collapses: a silent passage is not a
  refutation, a value found somewhere in a column is not support, and exit 0 is not
  evidence for a number.
- `FailureMode.EVIDENCE_UNDECIDABLE`, so *"the checker could not tell"* and *"the
  passage does not say it"* are different records.
- `checks.ErrorKind`: a closed vocabulary on every `error` path, so causes are
  classified from data rather than prose.
- An aggregate summary that separates **wrong verdicts** from **conservative misses**,
  because for a verification tool the difference between saying the wrong thing and
  declining to say anything is the whole point.
- `claimverifier verify`, offline, repeatable `--task`, writing `<task_id>.result.json`
  and a byte-reproducible `<task_id>.trace.jsonl`.

## Deliberately excluded (per the operating principles)

- **A calibrated confidence.** `VerificationResult.confidence` is *decidedness* — the
  share of a claim's checks that reached a `pass`/`fail` verdict. Producing a
  probability that the label is correct would need labelled data this project does not
  have. `synthetic_data_passage` scores `0.00`, and the report prints the definition
  next to the number rather than letting "confidence" imply calibration.
- **Any LLM in the scoring path.** Every rule is a pure function of the checks. Nothing
  here is graded by a model, per `docs/PLAN.md` §7.
- **Rescuing the one miss.** `synthetic_data_passage` could be moved to `supported` by
  loosening the evidence check (stemming, a synonym list, a coverage threshold). That
  would be overclaimed NLP, and it would risk moving `contradicted_f1`'s passage check
  off `pass`. The miss is reported, explained, and left in place; `wrong_verdicts = 0`
  is the claim being made, not `support_label = 7/7`.
- **`relation_does_not_hold`.** A failing `comparison` is recorded as
  `numeric_out_of_tolerance` — the check does apply a threshold, so it is fair, but the
  coarsening is named in `docs/SCORING.md` rather than hidden.
- **A failure mode for a `skipped` check.** `--no-execute` yields `partially_supported`
  / `not_attempted` / `none`: nothing was attempted, so nothing broke. What went
  unchecked lands in `limitations`, and the rule is named `no_failure_named`.
- **Cross-claim consistency.** Each claim is scored independently; the pipeline never
  asks whether two claims in one bundle contradict each other. Named as untouched work.
- **`run-suite` / `report`.** Milestones 8 and 9. `verify --task A --task B` already
  prints the aggregate the suite will consume.
- **New dependencies.** `dataclasses`, `enum`, `collections.Counter`, `json`, `argparse`.

## Verification performed at commit time

- `python3 -m pytest -q` → 452 passed (346 prior + 106 new).
- `ruff check .` → all checks passed.
- `python3 scripts/01_validate_fixtures.py` → 7 ok, 0 failed, 0 warnings (exit 0).
- `python3 scripts/00_check_environment.py` → exit 0 (`READY`).
- `claimverifier run-checks` re-run over all seven tasks after the `error_kind` /
  `declared_expectations` additions → 18 checks (16 pass, 1 fail, 1 inconclusive),
  identical to M5 and M6. No verdict moved.
- `claimverifier verify` over all seven tasks → support 6/7, reproduction 7/7, failure
  mode 6/7, 0 wrong verdicts, 1 conservative miss.
- `verify --task X --out DIR` run twice into the same directory → byte-identical
  `.trace.jsonl` **and** `.result.json`, including `recompute_accuracy`, whose script
  executes. Into two different directories the traces stay identical and only
  `result.json`'s `trace_path` differs, which is the `--out` the caller chose.
- `python3 -m scientific_claim_verifier.cli verify --task ...` → runs from a source
  checkout without an editable install. (`scoring.verdict` has a `main()`, test-pinned
  in-process, but no `__main__` guard — like `claims/linking.py` and
  `checks/verification.py`. `cli.py` is the module entry point.)
- `verify` on `contradicted_f1` exits `0`; on a nonexistent task exits `1`.
- Static site served locally on port 9002; all 11 pages fetched via Python's `urllib`
  (no `curl`/`wget`, per the permission policy), HTML tag balance and internal links
  checked.
- `git status` clean after commit.
