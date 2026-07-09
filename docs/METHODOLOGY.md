# METHODOLOGY

How this system decides what it decides, and — more importantly — what it is
forbidden from deciding.

The per-stage documents (`EXTRACTION.md`, `EVIDENCE_LINKING.md`, `CHECKS.md`,
`SANDBOX.md`, `SCORING.md`, `REPORTS.md`) each specify one component and its
limits. This document is the connective tissue: the design commitments that make
those components add up to an *auditable* result rather than a confident one.

---

## 1. The question

> A summary tells you what a paper *says*. It does not tell you whether a specific
> claim is *supported* by the paper's own artifacts, nor whether the underlying
> computation *reproduces*.

So a claim is not scored by reading it. It is scored by *checking* it against the
artifacts shipped with it, through independent channels, each of which is recorded
and can be inspected separately from the others.

Everything below follows from one refusal: **the system may not collapse those
channels into a single opaque verdict.** A verdict is an inference drawn from
recorded facts, and both the inference and the facts must survive into the output.

## 2. The five audit channels

Every report keeps these five separate and labelled (`docs/SAFETY.md`, "Auditability,
not authority"):

| Channel | Produced by | What it is |
| --- | --- | --- |
| **Extracted claim** | `claims/extraction.py` | the typed fields a rule read out of a sentence |
| **Supporting text** | `claims/linking.py` | the passages and artifacts retrieved for it |
| **Computed check** | `checks/` | a fact about one artifact, computed deterministically |
| **Inference** | `scoring/` | the support label, and the named rule that produced it |
| **Unverifiable** | `scoring/` | what these artifacts could **not** settle, and why |

The channels are not a presentation choice. They are enforced by the module graph:
the linker cannot decide support, the checks cannot assign a label, and the report
imports no pipeline stage at all (§6).

## 3. The stage contract

The pipeline is staged so that each stage is *structurally incapable* of doing the
next stage's job. This is the project's central design commitment, and most of the
interesting behaviour is a consequence of it.

```
artifacts → claims → evidence → checks → sandbox → scoring → report / export
```

| Stage | May conclude | May **not** conclude |
| --- | --- | --- |
| `artifacts` | these bytes hashed to this digest | anything about the claim |
| `claims` | this sentence has these fields | whether the fields are right |
| `evidence` | this passage/cell/column is *about* the claim | whether it *supports* the claim |
| `checks` | this artifact holds (or does not hold) this value | what that means for the claim |
| `sandbox` | this script exited N and printed this | whether N is the right answer |
| `scoring` | **the support label** — and it names the rule and the checks it read | anything the checks did not record |
| `report` | what the trace says | anything not in the trace |

Two consequences worth stating plainly.

**Retrieval is not support.** `link-evidence` ranks passages by keyword overlap and
emits the best. On `negated_training_data` the winning passage *negates* the claim
and scores 0.571 anyway — the linker retrieves it and says nothing about whether it
supports anything. Deciding that is `evidence_presence`'s job, one stage later, and
it returns `fail`. A retriever that filtered out passages it thought unsupportive
would be silently doing the checker's job with worse tools.

**A check is not a verdict.** `run-checks` prints supporting text and computed checks
as separate blocks and assigns **no** support label. On `contradicted_f1` the passage
check passes (the abstract asserts the claim verbatim) and the table check fails (the
table says 86.0, not 91.0). Both are correct. A stage permitted to reconcile them
would have had to destroy one of them.

## 4. Status is a fact about the check; signal is a fact about the claim

The single most load-bearing distinction in `scoring/`.

A `VerificationCheck` records a `status` — `pass`, `fail`, `inconclusive`, `error`,
`skipped` — which describes *the check*. Scoring reduces each status to a **signal**
about the *claim*: `supports`, `refutes`, `ambiguous`, or `undecided`. The map is not
the identity, because **one status means more than one thing**:

| Check | Status | Signal | Why |
| --- | --- | --- | --- |
| `table_value` on `contradicted_f1` | `fail` | `refutes` | the column is present and 91.0 is not in it |
| `evidence_presence` on `negated_training_data` | `fail` | `refutes` | the passage asserts the negation |
| `evidence_presence` where the passage never mentions the claim | `fail` | `undecided` | **silence is not refutation** |
| `table_value` on `underspecified_split` | `pass` | `ambiguous` | 90.0 is in the column, but the claim names no row |
| `code_execution` on `unreproducible_accuracy` | `error` | `undecided` | the script did not run, so no number disagreed |

Collapsing status into signal would let a checker's *ignorance* be published as a
fact about the paper. `synthetic_data_passage` is the fixture that makes this
concrete: a lexical rule cannot read the paraphrase that supports the claim, so
`evidence_presence` returns `inconclusive`, scoring maps it to
`unverifiable_from_artifacts` with failure mode `evidence_undecidable`, and
`confidence` reads `0.00`. Reporting `fail` there would have manufactured a
contradiction out of a bag-of-words rule's limits.

## 5. Inference is rule-based, ordered, and recorded

`scoring/support_labels.py` applies five ordered rules to the signals. It does not
vote, weight, or average. Each rule has a name, and the trace records **which rule
fired and which checks it read**:

```
support_label       : contradicted
  rule              : artifacts_refute [c_contradicted_f1.table_value.1]
  because           : the table does not hold the claimed value
```

The `because` string and the check IDs in brackets are the audit trail. A reader who
disagrees with the verdict can go straight to the check that produced it, and from
there to the artifact and its content hash. Nothing in the default path is an LLM
judgement; nothing is a learned score. `confidence` is the share of a claim's checks
that reached a verdict — *decidedness*, not a probability, and not calibrated against
anything (`docs/LIMITATIONS.md`).

## 6. A report is a function of its trace

`docs/PLAN.md` §11 requires that reports be generated from traces. The only thing
separating that from a slogan is a test that fails when it stops being true.

The renderer imports no pipeline stage, opens no artifact, re-runs no check, and does
not read `result.json`. It reads one `<task_id>.trace.jsonl`, re-validates every object
against its pydantic model on the way in, and reconstructs the scored claim. A corrupt
trace **raises** rather than rendering into a plausible-looking report; twelve tests
inject truncated, reordered, duplicated, foreign, and schema-violating traces to prove
it. A run archived months ago, whose papers and CSVs are long gone, still reports.

The round trip is asserted, not asserted-in-prose: `tests/test_reports.py` scores every
committed fixture, writes its trace, reads it back, and asserts the reconstructed
`ScoredClaim` **equals** the original — result, the three named rules, every per-check
signal, and the extracted claim. If a later milestone records a fact in a result but not
in its trace, the build breaks.

Here is the whole of `contradicted_f1`, as it exists on disk — nine events, and the
verdict is the last one:

```
seq  kind                  message
 0   scoring.run           the run this trace records, and the schema its events are written under
 1   scoring.claim         Method B reaches an F1 score of 91.0 on MNLI.
 2   scoring.evidence      the supporting text this verdict rests on, as retrieved
 3   scoring.check         the passage states the claim verbatim
 4   scoring.check         claimed 91 is absent from column 'f1' (nearest 86 at row B ...)
 5   scoring.support       contradicted
 6   scoring.reproduction  not_applicable
 7   scoring.failure       table_cell_mismatch
 8   scoring.result        Claim 'c_contradicted_f1' is contradicted by the supplied
                           artifacts (artifacts_refute: the table does not hold the
                           claimed value). ... 2 of 2 check(s) reached a verdict.
```

The claim arrives before the evidence, the evidence before the checks, the checks
before the label. A trace read top to bottom is the argument in the order it was made.

## 7. The gate is asymmetric, because the obvious metric is wrong

The smoke suite exits non-zero when the pipeline **regresses**. Regression is defined
in two buckets that a single accuracy number would merge:

- A **wrong verdict** — a committal support label the task's gold outcome disagrees
  with. The system asserted something false. *Any* wrong verdict fails the run, and
  `tasks/smoke_suite.yaml` has no key that could declare one acceptable (a test asserts
  the schema rejects the field outright).
- A **conservative miss** — the pipeline predicted `unverifiable_from_artifacts` or
  `not_checked` where gold commits. The system declined to decide, and asserted nothing
  false. This fails the run *only if the set of them changed*.

Over the eleven committed fixtures the pipeline recovers 10/11 support labels. The
number to watch is not the 10. It is the **0 wrong verdicts**, and the fact that the
single miss is a refusal to decide.

> A change that raises label accuracy by turning a claim the pipeline honestly declined
> to decide into one it decides *wrongly* has made the tool worse — and a single accuracy
> number would have called it an improvement.

The exported `scv.benchmark` document therefore **declares its metric**: `wrong_verdicts`
(lower is better) primary, `conservative_misses` secondary, with a note that says *do not
sum them*. The gate is tested by injecting each failure in turn — a wrong verdict, a new
miss, a stale declared miss — and asserting it fails. A gate that never fails proves
nothing when it passes.

## 8. Determinism is a precondition, not a feature

Nothing determinism-critical reads the wall clock or an RNG. Two runs of the suite into
two different directories produce byte-identical `*.trace.jsonl` (all eleven),
`summary.csv`, and `summary.json`. Exactly two artifacts differ, in exactly one field
each, and both are paths the caller chose.

This is what makes `trace_content_hash` a pin rather than a courtesy, and it is what
`claimverifier replay` depends on: an episode records the SHA-256 of the trace its run
wrote, and `--strict` gates on it. Wall-clock duration *is* measured (≈30 ms per fixture
script) and deliberately kept out of the trace unless `--with-timing` is passed — it is
the only value in an execution record that cannot be reproduced.

Replay distinguishes four statuses, and **only one of them blames the pipeline**:

| Status | Meaning |
| --- | --- |
| `reproduced` | same inputs, same verdict |
| `drifted` | same inputs, **different verdict** — a code regression |
| `inputs_changed` | a fixture, paper, or task file is not the recorded bytes |
| `missing_task` | the task file is gone |

Collapsing the last three into "failed" would let an edited CSV read as a code
regression, which is precisely the mistake a replay harness exists to prevent.

## 9. Every method here is a labelled heuristic

The project does not claim NLP sophistication, and says so at every point where a
weaker method could be mistaken for a stronger one.

- **Extraction** is regexes plus small closed lexicons (metrics, known dataset names,
  role entities). Those lexicons were chosen with the committed fixtures in view.
- **Passage linking** is verbatim containment, then bag-of-words token overlap. It has
  no model of morphology, synonymy, or negation: `trained` does not match `training`,
  and `corpus` does not match `corpora`.
- **`evidence_presence`** decides assertion lexically — verbatim containment, or every
  content token present with matching polarity. Negation cues are a closed set of
  function words.
- **Reproduction** means recomputing a statistic or running a tiny script and comparing
  within tolerance. It is not environment reconstruction or dependency resolution.
- **The sandbox** is a *reproducibility* control, not a security boundary: temp dir,
  scrubbed environment, closed stdin, POSIX rlimits, process-group timeout, and an
  in-process socket guard that denies **and records**. There is no namespace, no seccomp
  filter, no user separation. It runs trusted, committed fixture scripts. It must never
  be used to run untrusted code.

A tolerance is derived, not chosen: a claim written `91.0` — one decimal place — admits
anything that rounds to 91.0, so the tolerance is `0.05`.

## 10. What the fixtures are, and what they are not

Eleven hand-authored synthetic tasks, whose gold outcomes were written alongside the
rules that score them. **They are a regression harness, not a benchmark.** 10/11 does
not mean scientific claim verification is 91% solved; a perfect 21/21 on evidence
linking means the linker reproduces the hand-authored provenance exactly and invents
nothing, which is a real property and a narrow one.

The closest thing here to a held-out set is the four fixtures added in Milestone 8. They
were authored *after* the scoring rule table was frozen, to reach verdicts the original
seven never produced, and each landed on its hand-written gold outcome without a single
change to the extractor, the linker, the checks, or the rules. That is weak evidence —
the same agent wrote both, with the rules in view — but it is stronger than the seven
that came before, where the rules were tuned as the fixtures were written.

`docs/PAPER_PATH.md` sets out what it would take to make any of this a claim about the
world rather than a claim about this repository.

## 11. What a verdict means

`supported` means: *the artifacts in this bundle back this claim, under these checks, at
these tolerances.* It does not mean the claim is true. There is no universal oracle of
scientific truth in this repository, and the absence is deliberate — see
`docs/SAFETY.md`, "Auditability, not authority."

## See also

- `docs/EXTRACTION.md` · `docs/EVIDENCE_LINKING.md` · `docs/CHECKS.md` — the stages
- `docs/SANDBOX.md` — what execution does and does not enforce
- `docs/SCORING.md` — every rule, in order, and its known limits
- `docs/REPORTS.md` — the trace contract and the refusal tests
- `docs/RESULTS.md` — the measured outcomes, with the command beside each
- `docs/REPRODUCIBILITY.md` — how to reproduce every number in this repository
- `docs/LIMITATIONS.md` — what this system cannot do
- `docs/PAPER_PATH.md` — what would have to be true to publish any of it
