# REPORTS

How `scientific-claim-verifier` renders a verification result a human can audit, what a
report is allowed to say, and what it deliberately does not say. Milestone 9.

```bash
claimverifier report --run results/runs/smoke_suite --out results/reports/
claimverifier report --run results/runs/smoke_suite/contradicted_f1.trace.jsonl
python3 scripts/04_generate_report.py --run results/runs/smoke_suite --format both --out results/reports/
```

---

## 1. A report is a function of its trace

The report generator imports no pipeline stage. It does not open the task file, the paper,
the CSV, or the script; it does not run the extractor, the linker, the checks, or the
sandbox; it does not read `<task_id>.result.json`. It reads one `<task_id>.trace.jsonl`
and reconstructs the Milestone 7 `ScoredClaim` from those bytes.

This is a constraint, not an optimisation. `docs/PLAN.md` §11 requires that *reports are
generated from traces*, and a trace that cannot be turned back into the verdict it
recorded is not an audit record — it is a log. The property is kept true by a test rather
than by intention: `tests/test_reports.py` scores every committed fixture, writes its
trace, reads it back, and asserts

```python
report.result == scored.result
report.support_rule == scored.support_rule       # and reproduction, and failure
report.signals == scored.signals
report.claim == claim
```

If a later milestone records a fact in a `VerificationResult` but not in its trace, that
test fails. Two consequences fall out of the constraint:

- **An archived run still reports.** Copy a directory of traces onto a machine that has
  never seen the papers, the datasets, or the task files, and every report renders.
- **A corrupt trace raises rather than rendering.** Every object comes back through its
  pydantic model (`extra="forbid"`), so a misspelled field, an out-of-range `confidence`,
  or an unknown enum value is a `ReportError` naming the file — not a plausible-looking
  report built from garbage.

## 2. What Milestone 9 changed about the trace

`RunTrace.to_jsonl()` serializes the **event stream** and nothing else. So a trace's
`run_id`, `task_id`, and `bundle_id` — real fields on the model — survived on disk only in
the *filename*, and `scoring.claim` recorded five of the extracted claim's fields rather
than all of them. A report generator that "read the trace" would in fact have been reading
the trace *plus a guess about the path*.

`SCHEMA_VERSION` moved from `1.2` to `1.3`. No model changed. The **event contract** did:

| Event | Change |
| --- | --- |
| `scoring.run` | **new**, and first. Carries `run_id`, `task_id`, `bundle_id`, `schema_version`. |
| `scoring.claim` | now carries the whole claim under `claim`, minus `evidence_links`. |
| `scoring.result` | no longer carries `schema_version` (it moved to `scoring.run`). |

`evidence_links` is excluded from the claim dump because `scoring.evidence` already
records exactly that list. One fact, one place; two copies would eventually disagree.

The reader compares the **major** version. Within a major version event data only grows,
so a `1.9` trace reads fine. A `2.0` trace is refused. A pre-`1.3` trace — one with no
`scoring.run` event — is refused with an instruction:

```
error: <path>: no 'scoring.run' event — this trace predates schema 1.3 and cannot say
which run it describes. Regenerate it with `claimverifier verify --out`.
```

Guessing the run id from the filename was the alternative, and it is the kind of guess
this project exists to avoid.

## 3. The six sections

`CLAUDE.md` requires five things to stay visibly apart. They are §1–§5, numbered so they
cannot quietly merge; §6 is the provenance appendix.

| § | Channel | Holds |
| --- | --- | --- |
| 1 | **extracted claim** | the typed fields the heuristic extractor recovered, quoted claim text |
| 2 | **supporting text** | the passages the linker retrieved, with locator, score, and method |
| 3 | **computed check** | each check's status, target, computed and expected value, tolerance, and **signal** |
| 4 | **inference** | support label, reproduction status, failure mode — each with the rule that produced it and the check ids that rule read |
| 5 | **unverifiable** | what this verdict does not settle |
| 6 | trace | the JSONL link, the event count, and the command that regenerates the report |

Three of those columns are load-bearing.

**§2 is retrieval, not support.** That a passage was retrieved says nothing about whether
it asserts the claim. §3 is where that is checked, and the two are separated because
`contradicted_f1` — a paper whose abstract states a number its own results table denies —
is the fixture this project exists for. Its §2 quotes the abstract asserting the claim;
its §3 shows the table refuting it. A report that collapsed them would print
`contradicted` and destroy the only interesting fact about the claim.

**§3 prints `status` and `signal` in different columns.** A check's status is a fact about
the *check*; its signal is what the check says about the *claim*. One status maps to more
than one signal: an `evidence_presence` check that `fail`s because the passage never
mentions the claim signals `undecided`, not `refutes`. Silence is not refutation. See
`docs/SCORING.md`.

**§4 is an inference, not a summary.** Each label names its rule and the check ids the
rule read, so *"why does this claim say `contradicted`?"* is a lookup rather than an
exercise in re-reading the source. Where a claim fails in more than one way, §4 lists
every cause and marks the highest-priority one as the failure mode; the rest survive in
§5.

`confidence` never appears without the sentence that says what it is not: it is
*decidedness* — the share of checks that reached a verdict — and it is not calibrated
against anything.

## 4. Two formats, one document

`build_document()` makes every content decision. `reports/markdown.py` and
`reports/html.py` make none: they walk the same `Document` and emit text. The two formats
therefore cannot disagree about what a run concluded, only about punctuation, and a test
asserts they carry the same labels, check ids, section titles, and limitations.

Blocks carry **plain text**, never inline markup. A serializer can only escape safely if
it is not also being handed markup to preserve. `Link` exists because a link is the one
piece of inline structure a report genuinely needs, and it is a value, not a substring.

- **Markdown** is the default. Table cells escape `\` and `|` and collapse newlines,
  because an unescaped pipe silently eats a column and a newline silently ends the table —
  both would make the document say something false about the run.
- **HTML** (`--format html`) is one standalone file: no stylesheet to ship beside it, no
  JavaScript, no network fetch. An audit artefact may be read years after the run, from a
  directory someone copied off a machine, so it must not depend on anything that directory
  does not contain. Every string, hrefs included, goes through `html.escape`.

## 5. Determinism and portability

Nothing in the renderer reads the wall clock, an RNG, or the filesystem beyond the trace
it was handed. Two renders of one trace are byte-identical.

A report names its trace **relative to where the report is written**. Reports written
beside their traces link them as bare filenames, so a run directory can be copied,
archived, or served with no broken link and no absolute path of the machine that produced
it. That also makes the bytes identical across output directories — the same guarantee
`summary.csv` carries (Milestone 8), and for the same reason: the one field that could
hold a machine-specific path is computed from the caller's own arguments.

## 6. What a report does not say

**It never prints the task's gold outcome.** A trace records what the pipeline concluded,
not what it should have concluded, and the report is a function of the trace. Gold
agreement lives in `summary.csv` and `summary.json`, where a *wrong verdict* and an
*honest refusal to decide* are counted apart. The index reports the gate a suite run
already decided and points at those files; it does not tally an accuracy.

**It is not an authority on the claim.** Every verdict is relative to the supplied
artifacts. `unverifiable_from_artifacts` means *these artifacts do not settle it* — never
*it is false*.

**Known formatting limits**, stated rather than papered over:

- Prose blocks are not Markdown-escaped, so a claim containing `*` or `_` renders with
  emphasis. Mangling `p < 0.05` to defend against a Markdown reading of `<` would cost
  more than it buys.
- No committed fixture is refuted by its table *and* undecidable from its text at once, so
  §4's multi-cause block is exercised by a unit test rather than by a real run.
- The index reads `summary.json` when a suite left one beside the traces — the single
  exception to "reports read only traces", and it decorates the index alone. An
  unreadable summary is treated as absent, never as fatal: the reports it would have
  decorated are all still valid.

## 7. CLI

```
claimverifier report --run PATH [--out PATH] [--format markdown|html|both] [--no-index]
```

| Flag | Meaning |
| --- | --- |
| `--run` | a run directory of `*.trace.jsonl`, or one such file |
| `--out` | a report file (`.md`/`.html`, one trace only), or a directory. Omit to print. |
| `--format` | `markdown` (default), `html`, or `both` (needs `--out DIR`) |
| `--no-index` | do not write an index over a run directory's reports |

Reports are named from the `run_id` **recorded in the trace**, not from the trace's
filename: a renamed file does not rename the run it describes.

Exit `0` when every requested report rendered — including reports of `contradicted`
claims, which are the tool working. Exit `1` when a trace is missing, empty, not JSONL,
foreign (a `sandbox.*` stream), incomplete, reordered, duplicated, schema-violating, or
written under an unreadable major version. The file is named, and no traceback is printed:
a malformed trace is a fact about the file, not a bug in the renderer.
