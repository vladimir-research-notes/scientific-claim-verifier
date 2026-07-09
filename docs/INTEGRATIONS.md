# INTEGRATIONS — export contracts and the replay loop (Milestone 11)

`docs/PLAN.md` §9 asks Milestone 11 for "compatible import/export formats for the
code-agent runtime, BioScientist OS, BioAgentBench, LLM regression/observability, and
agent-control-bench — without depending on those repos."

## What this is, and what it is not

**No external schema was consulted.** None of those five systems was read, imported, or
run. This repository therefore cannot claim, and does not claim, *compatibility* with any
of them. Anyone who tells you they built an adapter against a specification they never
saw is telling you about their optimism.

What exists instead is five **proposed contracts**, one per consumer *role* the plan
names. Each is versioned, each is derived from artifacts this repository actually
produces, each is validated by a strict reader, and each is confined to one module of
~200 lines. If a named repo wants different keys, the change is that module and a
`format_version` bump; no pipeline stage knows these formats exist.

That containment is the deliverable. It is a claim that can be checked, and
`tests/test_integrations.py` checks it: the test parses every module under
`integrations/` and fails if it imports anything but the standard library, `pydantic`,
and this project.

## The five formats

| `--format` | Document | Consumer role | Reads |
| --- | --- | --- | --- |
| `runnable-tasks` | `scv.runnable-tasks` | code-agent runtime | `tasks/` |
| `evidence-records` | `scv.evidence-records` | BioScientist OS | a run's traces |
| `benchmark` | `scv.benchmark` | BioAgentBench | a **suite** run (traces + gold) |
| `metrics` | `scv.metrics` | LLM regression / observability | a **suite** run (traces + gold) |
| `episodes` | `scv.episodes` | agent-control-bench | a **suite** run + `tasks/` |

```bash
claimverifier export --list                                   # the table above, live
claimverifier export --format benchmark --schema              # JSON Schema, from the models
claimverifier run-suite --out results/runs/                   # produce a run
claimverifier export --format episodes --run results/runs/smoke_suite --out episodes.json
claimverifier replay --episodes episodes.json                 # the import direction
```

## Four properties, held by every format

1. **An export is a function of committed artifacts.** Nothing re-runs the pipeline. The
   traces are the record, exactly as Milestone 9 established for reports; a test deletes
   the task directory and shows `evidence-records`, `benchmark`, and `metrics` are
   unaffected. The single exception is `replay`, which exists to re-run.
2. **An export is deterministic.** Canonical JSON: sorted keys, no wall clock, no RNG.
   Exporting a run twice produces byte-identical files. A non-diffable export is useless
   to a regression tool.
3. **An export is portable.** Every path is repo-relative; every trace is named by its
   filename. A test walks every string of every document and fails on an absolute path.
4. **An export is self-describing.** The envelope states `format`, `format_version`,
   `producer`, `producer_version`, and `trace_schema_version`. A reader that asks for one
   format and is handed another is told so, by name — and a *later major version* is
   refused rather than parsed into a plausible-looking object.

Within a major version, payload fields only ever grow. Across a major, a reader must
refuse. That is what the version is for.

## The envelope

```json
{
  "format": "scv.benchmark",
  "format_version": "1.0",
  "producer": "scientific-claim-verifier",
  "producer_version": "0.1.0",
  "trace_schema_version": "1.3",
  "payload": { "...": "..." }
}
```

Every payload record is a `pydantic` model with `extra="forbid"`. An export is a
contract, and the two ways a contract rots unnoticed are a consumer silently dropping a
field it does not recognise and a producer silently accepting one it never declared.

`format_schema(name)` — and `claimverifier export --format NAME --schema` — derives the
JSON Schema from the very models that write and validate the document, so a published
schema cannot drift from the code that honours it.

## One vocabulary, shared

Three formats state a verdict. If each spelled it differently, a consumer joining two
exports would need to know all five formats to know they agreed. So `Verdict` lives once,
in `integrations/records.py`:

```json
{"support_label": "contradicted",
 "reproduction_status": "not_applicable",
 "failure_mode": "table_cell_mismatch",
 "confidence": 1.0}
```

It is **never** flattened to a single score, in any export. `confidence` is the share of
a claim's checks that reached a verdict — not a probability that the label is right, and
not calibrated against anything. A gold verdict carries `confidence: null`, because no
pipeline computed it.

---

## `scv.runnable-tasks` — code-agent runtime

Each task as a unit a runtime can run: `argv` as a list (no shell, no quoting), the input
files it reads (repo-relative, content-hashed), and the success criterion. The runtime
appends `--out DIR` to get a trace.

Papers are not listed among the files: their passages are **inlined in the task file**,
which is listed, so the task file's hash covers them.

### The trace contract

`docs/PLAN.md` asks this format to "export traces in a compatible JSONL shape". The trace
already *is* JSONL; what a consumer lacks is a written guarantee about it. The document
carries one:

```json
{"path_template": "<out>/<task_id>.trace.jsonl",
 "media_type": "application/x-ndjson",
 "schema_version": "1.3",
 "event_kinds": ["scoring.run", "scoring.claim", "scoring.evidence", "scoring.check",
                 "scoring.support", "scoring.reproduction", "scoring.failure", "scoring.result"],
 "guarantees": ["one JSON object per line, UTF-8, newline-separated",
                "object keys are sorted within every line",
                "every line carries a contiguous `seq`, starting at 0",
                "every line's `kind` is one of `event_kinds`",
                "no value is read from the wall clock or an RNG",
                "the bytes are identical across re-runs and across output directories"]}
```

Those are claims about a real artifact, so a test re-derives **every one of them** from a
trace this repo produced. A guarantee nobody checks is a comment.

### Gold, and `--hide-gold`

`expected.verdict` is the task's hand-authored gold outcome. It is the success criterion
a *runtime* checks, and it must never be shown to a system asked to solve the task.
`--hide-gold` drops it and leaves `exit_code: 0`.

---

## `scv.evidence-records` — BioScientist OS

Not a verdict with a citation stapled to it. The five channels `CLAUDE.md` requires the
report to keep apart, as five sibling keys an evidence store cannot merge without
noticing:

| Key | Channel |
| --- | --- |
| `claim` | the extracted claim, as typed fields |
| `evidence` | the supporting text, quoted, with its locator |
| `checks` | each computed check: value, expected, tolerance, status |
| `verdict` | the inference — three labels wide |
| `unverifiable` | what this verdict does *not* settle |

`rules` sits beside them: the named inference step behind each of the verdict's three
fields, and the `check_id`s it read. A store that keeps the rule can answer *why does this
say `contradicted`?* by lookup. One that keeps only the label cannot.

### What is deliberately not exported

`VerificationCheck.inputs` — the per-check debugging bag whose keys vary by check type,
and which, for `code_execution`, holds captured stdout and stderr. A stable contract
cannot carry a field whose shape is decided by whichever check happened to write it, and
an evidence store is the last place that should start holding process output by accident.
It is in the trace, and `provenance` names the trace. A test asserts the string
`accuracy=0.80` — real captured stdout from a fixture script — appears in no record.

### The fixture that shows why the channels must not merge

`contradicted_f1` exports a passage that **asserts** the claim (`evidence_presence: pass →
supports`) beside a table that **refutes** it (`table_value: fail → refutes`). Both checks
are correct. `status` is a fact about the check; `signal` is what the check says about the
claim. Both are exported, because a consumer that sees only `fail` cannot tell a table
cell that refutes a claim from a passage that merely fails to mention it.

---

## `scv.benchmark` — BioAgentBench

A benchmark that ships records without declaring its metric is a spreadsheet. So the
document declares one:

```json
{"protocol": "exact_match_per_field",
 "fields": ["support_label", "reproduction_status", "failure_mode"],
 "primary_metric": "wrong_verdicts", "primary_metric_direction": "lower_is_better",
 "secondary_metric": "conservative_misses", "secondary_metric_direction": "lower_is_better",
 "outcomes": ["match", "conservative_miss", "wrong_verdict"]}
```

The metric a harness would reach for by default — label accuracy — is the wrong one here.
Over these fixtures the pipeline recovers **10 of 11** support labels, and its single miss
is a claim it *declined to decide*: a lexical evidence check cannot tell that a paraphrase
asserts a claim, so it returns `inconclusive` and scoring reports
`unverifiable_from_artifacts` rather than guessing. A change that "fixed" that miss by
guessing would score 11/11 and have made the tool worse.

So the primary metric is `wrong_verdicts` — committal labels the task's own artifacts
contradict — and over the committed fixtures it is **0**. `conservative_misses` is
secondary. **Do not sum them.** This is the same asymmetry `suite.gate()` enforces
(`docs/SCORING.md`), and the export computes each task's bucket with the *same*
`TaskOutcome` object the gate reads — not a re-implementation — so the two cannot come to
different conclusions.

`gate.applicable` is `false` for a `--no-execute` run: the gold outcomes assume the
fixture scripts ran. A harness that ignores that field will publish the operator's flag as
a score.

### Two sources, cross-checked

Predicted verdicts, claim types, and check counts come from the **traces**. Gold outcomes,
the suite's identity, and the gate come from `summary.json` — a trace never carries gold,
because gold is never an input to the run that wrote it. The two are compared, and a
directory whose traces and summary disagree is **refused**, not scored: it holds artifacts
from more than one run, and any number computed from it is a fiction. Silently preferring
one source is how a benchmark starts reporting a score nobody produced.

---

## `scv.metrics` — LLM regression / observability

The only property a metrics sink really needs from a producer is the one producers usually
get wrong: **a fixed key space**.

A run in which no claim is `contradicted` could plausibly omit `support_contradicted`.
Then a diff against a run with two contradictions shows a key *appearing*, and a tool that
reads a missing key as "no data" reports nothing while one that reads it as zero reports a
regression. Both are guessing. So `METRIC_NAMES` covers **every value of every closed
vocabulary** — 6 support labels, 8 reproduction statuses, 13 failure modes, 5 check
statuses — and all 40 metrics are emitted every time, zero-valued when unseen. The key
space changes only when `format_version` does, and a test enumerates the enums so a
vocabulary cannot grow without this format saying so. The labels are fixed for the same
reason, which is why this format describes a *suite* run and refuses anything else.

`direction` is the other half. A regression tool cannot know that more `checks_fail` is
fine — a suite of contradicted claims *should* produce failing checks — while more
`wrong_verdicts` is not. Most counts are therefore `neutral`; only six declare a
direction.

`metrics.compare()` is the reference implementation of the diff this format exists for.
It refuses two documents whose key sets differ rather than intersecting them:

```python
from scientific_claim_verifier.integrations import envelope, metrics

before = metrics.payload_of(envelope.read("before.json", expect=metrics.FORMAT))
after = metrics.payload_of(envelope.read("after.json", expect=metrics.FORMAT))
for delta in metrics.regressions(metrics.compare(before, after)):
    print(delta.name, delta.baseline, "->", delta.candidate)
```

A test drives the scenario the whole project is arranged to catch: a conservative miss
turning into a wrong verdict, with `gold_support_agreement` unchanged. Accuracy calls it a
wash. `compare` flags `wrong_verdicts`.

---

## `scv.episodes` — agent-control-bench

The one format with an **import** direction, and where the contract stops being a shape
and becomes a claim that can be false.

An episode pins the task (repo-relative, plus the hash of the task file), every artifact of
its bundle by `artifact_id` and content hash, the controls, the recorded verdict, and
`trace_content_hash` — the SHA-256 of the trace the run wrote. Traces are byte-stable
across re-runs and output directories (Milestone 8), so that digest is a real pin rather
than a courtesy.

`claimverifier replay --episodes PATH` re-runs each episode under its recorded controls
and reports one of four statuses:

| Status | Meaning |
| --- | --- |
| `reproduced` | same inputs, same verdict |
| `drifted` | same inputs, **different verdict** — the pipeline changed |
| `inputs_changed` | a fixture, a paper, or the task file is not the bytes the episode recorded; no re-run is attempted |
| `missing_task` | the task file is gone |

Only `drifted` is a statement about the *pipeline*. Collapsing the other three into
"failed" would let an edited CSV read as a code regression — precisely the mistake a
replay harness exists to prevent. Each of the four is produced by *injecting* its cause in
the tests: a tampered artifact hash, a tampered task hash, a deleted task, a doctored
verdict.

### Verdict equality gates; trace bytes are stricter

`trace_digest_matches` is reported for every replayed episode and gated only under
`--strict`. Reword one `because` string in the scoring rules and every trace's bytes
change while every verdict stands. That is worth seeing, and is not on its own a
regression — the same asymmetry the smoke suite draws between a wrong verdict and a
conservative miss.

Over the eleven committed fixtures, replay is `reproduced` 11/11 **and passes
`--strict`**: the traces come back byte-identical.

### An honest gap: a 1.3 trace does not record its controls

A trace records what the pipeline *computed*, not how an operator *invoked* it. None of
the four `controls` — `execute`, `use_declared_source`, `abs_tol`, `rel_tol` — appears in
it. So:

- `execute` is recovered from the one artifact that does record it, a suite
  `summary.json`'s `suite.scripts_executed`, and `export --format episodes` **refuses**
  when the operator's declared `--no-execute` disagrees with it.
- The other three are taken from the operator's flags and default to the pipeline's
  defaults.

A wrongly declared control does not silently lie — replaying it reports `drifted` and
names the field — but it *is* an assumption, and it is the one this milestone did not
remove. Recording the controls in the trace (a `scoring.controls` event, schema 1.4) would
remove it; that is a schema change and belongs to whichever milestone needs it, not to
this one. See `docs/review_notes/11-integration-contracts-human-review.md`.

---

## Honest limitations

- **No adapter was validated against any of the five named systems.** These are contracts
  shaped for a role, not against a specification. The word "compatible" in `docs/PLAN.md`
  should be read as "shaped to be compatible with", and nothing here demonstrates more.
- **`benchmark`, `metrics`, and `episodes` require a `run-suite` run.** They need gold
  outcomes, a suite identity, or a gate, and none of the three is in a trace.
  `evidence-records` needs only traces and works on an archived run.
- **`episodes` assumes three of its four controls** (see above).
- **The fixtures are eleven small synthetic tasks.** Every number that leaves here —
  `0 wrong_verdicts`, `10/11` support agreement — is a fact about this pipeline on those
  fixtures, and not a benchmark result about scientific claim verification.
- **`replay` runs the fixture scripts.** It inherits the sandbox's honest scope: controlled
  fixture execution in a temp directory, not an untrusted-code boundary (`docs/SANDBOX.md`).
