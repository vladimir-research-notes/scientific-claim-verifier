# M9 — Reports

## Summary

Adds the `reports/` package, `claimverifier report`, and `scripts/04_generate_report.py`:
an auditable Markdown (or standalone HTML) report per claim — extracted claim, supporting
text, computed checks, inference, limitations, trace link — rendered **from the JSONL
trace and nothing else**. Eleven reports and an index from the smoke suite's eleven
traces, on a CPU, offline, in under a tenth of a second. This completes the CLI contract
in `docs/PLAN.md` §10.

Four ideas carry the milestone.

**A report is a function of its trace, and that is enforced by a test rather than by
intention.** The renderer imports no pipeline stage, opens no artifact, re-runs no check,
and never reads `result.json`. `tests/test_reports.py` scores every committed fixture,
writes its trace, reads it back through `reports.reader`, and asserts the reconstructed M7
`ScoredClaim` **equals** the original — the `VerificationResult`, all three named `Rule`s,
every per-check `CheckSignal`, and the extracted `ScientificClaim`. If a later milestone
records a fact in a result but not in its trace, the build breaks. `docs/PLAN.md` §11's
"reports are generated from traces" is now a property, not a slogan.

**The trace was not yet self-describing, so M9 changed it and bumped the schema.**
`RunTrace.to_jsonl()` serializes the event stream and nothing else, so a trace's `run_id`,
`task_id`, and `bundle_id` — real fields on the model — survived on disk only in the
*filename*, and `scoring.claim` recorded five of the extracted claim's fields rather than
all of them. A generator claiming to "read the trace" would have been reading the trace
plus a guess about the path. `SCHEMA_VERSION` moved `1.2` → `1.3`: **no model changed**,
the event contract did. A `scoring.run` event now opens every stream; `scoring.claim`
carries the whole claim minus its evidence links (which `scoring.evidence` already
records); `scoring.result` no longer repeats the version. A pre-1.3 trace is refused *with
an instruction*, never guessed at from its filename.

**Refusing to render is a feature.** Every object comes back through its pydantic model
(`extra="forbid"`), and twelve tests assert that a missing, empty, non-JSONL, truncated,
reordered, duplicated, foreign (`sandbox.*`), schema-violating, or future-major-version
trace raises `ReportError` naming the file — rather than producing a plausible-looking
report built from garbage. No traceback reaches the user: a malformed trace is a fact about
the file, not a bug in the renderer.

**One document, two serializers.** `build_document()` makes every content decision;
`markdown.py` and `html.py` make none. The two formats cannot disagree about what a run
concluded, only about punctuation, and a test asserts they carry the same labels, check
ids, section titles, and limitations. Blocks carry plain text, never inline markup — a
serializer can only escape safely if it is not also handed markup to preserve.

## Deliverables

- **`src/scientific_claim_verifier/reports/`** (new package):
  - `__init__.py` — the block model (`Paragraph`, `Quote`, `Bullets`, `Table`, `Code`,
    `Link`), `Section`, `Document`, and `build_document` / `build_index_document`: every
    decision about *what a report says*.
  - `reader.py` — `ReportInput`, `read_report`, `discover_traces`, `read_summary`,
    `order_of`, `ReportError`. Reconstructs the M7 object graph from JSONL.
  - `markdown.py` — `render_markdown`, `escape_cell`. The default format.
  - `html.py` — `render_html`, `escape`. One standalone file: no stylesheet, no JS, no
    network fetch.
  - `render.py` — `report_and_write`, `write_reports`, `href`, `ordered`, and the
    `report` CLI.
- **`scoring/verdict.py`** — `build_trace` emits `scoring.run` first and records the whole
  claim; `SCORING_EVENT_KINDS` grew by one. The docstring states why.
- **`schemas.py`** — `SCHEMA_VERSION` `1.2` → `1.3`, with the reason in a comment. No model
  changed.
- **CLI:** `claimverifier report --run PATH [--out PATH] [--format markdown|html|both]
  [--no-index]`.
- **`scripts/04_generate_report.py`** — the last of the numbered scripts `docs/PLAN.md` §5
  lists; runnable without an editable install.
- **Tests:** `tests/test_reports.py` (98 new); `tests/test_scoring.py` +2 (the run event,
  the whole-claim event); `tests/test_schemas.py` updated for `1.3`. **600 total.**
- **Docs:** `REPORTS.md` (new), `RESULTS` (new M9 section; test table), `README`.
- **Website:** `example-report` (rewritten around the real generated report), `index`,
  `results`, `milestones`, `limitations`.

## Design decisions

- **The report reads the trace, not `result.json`.** `result.json` is a convenience
  serialization; the trace is the audit record. Reading the trace forces the trace to be
  *complete*, and the round-trip test is what keeps it so. A test deletes `result.json`,
  moves the lone trace into an empty directory, and renders from it.
- **`scoring.run` is a new event, not five new keys on `scoring.claim`.** The claim event
  is about the claim. Run identity is a different fact and gets its own event, symmetric
  with `scoring.result` closing the stream.
- **`evidence_links` is excluded from the claim dump.** `scoring.evidence` already records
  that list. One fact, one place; two copies would eventually disagree.
- **The schema version was bumped although no model changed.** `SCHEMA_VERSION` is stamped
  into every trace precisely so a reader can tell whether it understands the bytes. A 1.2
  trace does not satisfy a 1.3 reader. Leaving it at 1.2 would have made the version
  string decorative. Readers compare the **major** component: within a major, event data
  only grows, so a 1.9 trace reads and a 2.0 trace is refused.
- **A report never prints its task's gold outcome**, and cannot: the trace records what the
  pipeline concluded, not what it should have. Gold agreement lives in `summary.csv` and
  `summary.json`, where a wrong verdict and an honest refusal to decide are counted apart.
  A report that scored itself would be answering a different question.
- **The index is the one exception to "reports read only traces."** It reads `summary.json`
  when a suite left one, for the gate line and the declared task order (evidence channel:
  text, table, dataset, code — not alphabetical). An unreadable summary is treated as
  absent rather than fatal: the reports it would have decorated are all still valid.
- **The trace link is relative to where the report is written.** Reports written beside
  their traces link them as bare filenames, so a run directory can be copied, archived, or
  served with no broken link and no absolute path. The bytes are then identical across
  output directories — the same guarantee `summary.csv` carries, for the same reason.
- **Reports are named from the `run_id` recorded *in* the trace**, not from its filename. A
  renamed file does not rename the run it describes, and a test pins that.
- **Blocks carry plain text; `Link` is a value, not a substring.** Markdown table cells
  escape `\` and `|` and collapse newlines, because an unescaped pipe silently eats a
  column. Prose is *not* escaped: mangling `p < 0.05` to defend against a Markdown reading
  of `<` costs more than it buys. Stated in `docs/REPORTS.md` §6, not papered over.
- **HTML is one standalone file.** An audit artefact may be read years later from a copied
  directory, so it must not depend on anything that directory does not contain. Every
  string, hrefs included, goes through `html.escape`; a test asserts no `http://` appears
  in any report.
- **`report` exits 0 on a `contradicted` claim**, as `verify` and `run-suite` do. Reporting
  a contradiction is the tool working.
- **`reports/` has five modules where `docs/PLAN.md` §5 sketches two.** The reader, the
  document model, and the CLI are separate concerns from the two serializers, and the
  split is what makes "the formats cannot disagree" testable. The same precedent exists in
  `evidence/locators.py`, `checks/verification.py`, and `scoring/verdict.py`.
- **No new dependencies.** `argparse`, `collections`, `dataclasses`, `html`, `json`, `os`,
  `pathlib`.

## Validation

Commands run (CPU-only, offline):

| Command | Result |
| --- | --- |
| `python3 -m pytest -q` | 600 passed (500 prior + 100 new) |
| `ruff check .` | All checks passed |
| `python3 scripts/01_validate_fixtures.py` | 11 tasks ok, 1 suite ok, 0 failed — VALID (exit 0) |
| `python3 scripts/00_check_environment.py` | exit 0 — `READY` |
| `python3 scripts/05_run_smoke_suite.py --out results/runs/` | 11 tasks, gate **PASS**, exit 0 |
| `claimverifier report --run results/runs/smoke_suite --out results/reports/` | 12 files, exit 0 |
| `claimverifier report ... --format both` | 24 files, HTML balanced, exit 0 |
| reports generated from two run directories | byte-identical; no absolute path in either |
| a lone trace in an empty directory (no `result.json`) | renders |
| site served on :9002, 11 pages fetched via `urllib` | 200, balanced HTML, no broken links |

### The measured result

| | |
| --- | --- |
| Reports rendered | 11 + index, from 11 traces |
| Pipeline stages the renderer imports | **0** |
| Round trip (trace → `ScoredClaim`) | **exact on 11/11** — result, rules, signals, claim |
| Markdown per claim | ~5 KB (median 5,130 bytes) |
| Refusal tests | 12 |
| Formats | Markdown, standalone HTML |

The tests additionally pin: the six numbered sections in order; `contradicted_f1` printing
the passage that asserts its claim in §2 and the table that refutes it in §3;
`synthetic_data_passage` printing `confidence 0.00`, its exact reason, and *nowhere* the
word `contradicted` or `passage_does_not_assert`; every check id and every signal reason
reaching the report; every rule and the check ids it read reaching the report;
`confidence` never printed without its caveat; the sandbox limitation appearing on a
*supported*, *reproduced* claim; a `Table` row narrower than its header failing at
construction; a Markdown cell unable to smuggle a column break; HTML escaping hrefs;
multi-line bullets surviving both formats; an unknown block type failing loudly in both;
the two formats reporting the same run; balanced standalone HTML for all eleven fixtures;
byte-identical renders; relative trace links; the index in the suite's declared order,
carrying the gate and refusing to be a scoreboard; an unreadable `summary.json` not
failing the reports it would decorate; and thirteen CLI paths including stdout, `--format
both` without `--out`, many claims into one file, a format its extension denies, a missing
run, an empty directory, a malformed trace reported without a traceback, and
`scripts/04_generate_report.py` as a subprocess.

Two facts are recorded rather than measured. No committed fixture is refuted by its table
*and* undecidable from its text at once, so §4's multi-cause block is exercised by a unit
test on a synthetic `ReportInput`, not by a real run. And the `not_checked` /
`no evidence` degenerate rendering path is likewise unit-tested, since the check runner
always emits an `evidence_presence` check.

## Status

**Complete.** Next: **M10 — Optional adapters** (`RecordedLLMAdapter`, `MockLLMAdapter`,
`ApiAdapterStub` with a cost guard). Disabled by default; no paid API required anywhere in
the default path. The report is the natural consumer of a recorded adapter's output, and
the `Signal`/`Rule` vocabulary an adapter would have to produce is already fixed by M7.
