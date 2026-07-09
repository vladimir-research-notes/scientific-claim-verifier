Human review: M9 — Reports

TL;DR
Milestone 9 adds `src/scientific_claim_verifier/reports/`, `claimverifier report`, and
`scripts/04_generate_report.py`: an auditable Markdown (or standalone HTML) report per
claim — extracted claim, supporting text, computed checks, inference, limitations, trace
link — in six numbered sections, so the five audit channels cannot silently merge. Eleven
reports and an index from the smoke suite's eleven traces, offline, on a CPU, in under a
tenth of a second. This completes the `docs/PLAN.md` §10 CLI contract. Four decisions carry
it. (1) **A report is a function of its trace.** The renderer imports no pipeline stage,
opens no artifact, re-runs no check, and never reads `result.json`; a test scores every
committed fixture, writes its trace, reads it back, and asserts the reconstructed M7
`ScoredClaim` **equals** the original result, rules, signals, and claim. `docs/PLAN.md`
§11's "reports are generated from traces" is now a build-enforced property. (2) **The trace
was not self-describing, so it changed and `SCHEMA_VERSION` went 1.2 → 1.3** — no model
changed, the event contract did. (3) **Refusing to render is a feature**: 12 tests assert
that a malformed, foreign, or wrong-version trace raises `ReportError` naming the file
rather than rendering plausible garbage. (4) **One document, two serializers**, so Markdown
and HTML cannot disagree about what a run concluded. 100 new tests (600 total). No new
dependencies.

**This addresses one open item and defers another.** The M7 review asked whether
`_VERDICT_PHRASE` (the hand-written English phrase per support label) "belongs in code at
all, versus being M9's business" — it stays in M7: the phrase is recorded *in the trace*
as `scoring.result`'s message, and moving it into the renderer would mean the trace no
longer carried its own human-readable summary. The M8 review asked whether
`verify --task <schema-invalid.yaml>` handing the user a pydantic traceback (where
`run-suite` reports it cleanly) belongs in "M9's cleanup"; it does not — it is an M7 code
path unrelated to reports — and it is deferred to **M13 — Final cleanup**, restated below
so it is not lost.

What changed
- New package: src/scientific_claim_verifier/reports/
  - __init__.py — the block model (Paragraph, Quote, Bullets, Table, Code, Link), Section,
    Document, build_document, build_index_document. Every decision about *what a report
    says* lives here; the serializers make none.
  - reader.py — ReportInput, read_report, discover_traces, read_summary, order_of,
    ReportError, REQUIRED_EVENT_KINDS. Reconstructs the M7 object graph from JSONL,
    re-validating every object through its pydantic model.
  - markdown.py — render_markdown, escape_cell, render_block, render_section.
  - html.py — render_html, escape, STYLE. One standalone file per report.
  - render.py — report_and_write, write_reports, write_one, href, ordered, report_name,
    trace_paths, formats_of, is_file_target, and the `report` CLI.
- schemas.py: SCHEMA_VERSION 1.2 → 1.3, with the reason in a comment. No model changed.
- scoring/verdict.py: build_trace now emits `scoring.run` first (run_id, task_id,
  bundle_id, schema_version); `scoring.claim` carries the whole claim minus evidence_links;
  `scoring.result` no longer repeats schema_version. SCORING_EVENT_KINDS grew by one. The
  module docstring states why.
- cli.py: `report` registered; epilog and docstring no longer describe it as pending.
- scripts/04_generate_report.py (runnable without an editable install) — the last of the
  numbered scripts docs/PLAN.md §5 lists.
- Tests: tests/test_reports.py (98 new); tests/test_scoring.py +2 (the run event, the
  whole-claim event, and two existing assertions updated for the new stream);
  tests/test_schemas.py updated for 1.3. 600 total.
- Docs: REPORTS.md (new), RESULTS (new M9 section; status and test tables), README.
- Website: example-report (rewritten around the real generated report), index, results,
  milestones, limitations.

What should be checked later
- **The schema bump is the most arguable decision here, and it should be argued.**
  `SCHEMA_VERSION` moved 1.2 → 1.3 although *no pydantic model changed*. The reasoning: the
  version is stamped into every trace so a reader can tell whether it understands the bytes,
  and a 1.2 trace does not satisfy a 1.3 reader (no `scoring.run` event). Leaving it at 1.2
  would have made the string decorative. The counter-argument is that `SCHEMA_VERSION` has,
  until now, tracked the *model* vocabulary (1.1 = `CheckStatus.INCONCLUSIVE`, 1.2 =
  `FailureMode.EVIDENCE_UNDECIDABLE`), and that a trace-format version deserves its own
  field. Confirm the conflation is acceptable, or whether `RunTrace` should carry a separate
  `trace_format` alongside `schema_version`.
- **The pre-1.3 refusal is unconditional.** A trace without a `scoring.run` event is refused
  with an instruction to regenerate it, even though the run id could be read off the
  filename. No such traces are committed, and none survive a `run-suite`, so nothing in this
  repo is locked out — but a user with an old `results/runs/` directory must re-run. Confirm
  that refusing is better than falling back to the filename with a printed warning. (I think
  it is: the fallback would make "a report is a function of its trace" false in exactly the
  case where nobody would notice.)
- **`scoring.result` losing `schema_version` is a breaking change to that event**, not an
  additive one, and the reader now insists on finding the version in `scoring.run`. The
  version bump is what licenses it. Confirm; the alternative was to record it twice.
- **The round-trip test compares `VerificationResult` by value**, which includes
  `trace_path`. The reader sets `trace_path` to the path it was handed, and the test passes
  the same path `verify --out` wrote, so equality holds. If a future change resolves or
  normalises that path in one place and not the other, the test fails for a reason that has
  nothing to do with the trace's completeness. Confirm the coupling is acceptable, or whether
  the test should compare `model_dump(exclude={"trace_path"})`.
- **The index reads `summary.json`.** This is the one exception to "reports read only
  traces", and it buys the gate line and the suite's declared task order (evidence channel,
  not alphabetical). An unreadable summary is treated as *absent*, not fatal. Confirm the
  exception is worth it, and confirm that silently ignoring a corrupt `summary.json` is right
  — the alternative (failing every report because one decoration is broken) seemed worse, but
  it does mean a truncated summary downgrades the index without saying so.
- **`reports/` has five modules where docs/PLAN.md §5 sketches two** (`markdown.py`,
  `html.py`). The split isolates the reader and the document model from the serializers, and
  it is what makes "the two formats cannot disagree" testable. Precedent exists
  (`evidence/locators.py`, `checks/verification.py`, `scoring/verdict.py`). Confirm, or
  confirm the PLAN's layout map should be amended rather than quietly exceeded.
- **Prose is not Markdown-escaped.** Table cells escape `\` and `|` and collapse newlines;
  paragraphs, quotes, and bullets do not. A claim sentence containing `*` or `_` renders with
  emphasis. The judgement was that mangling `p < 0.05` into `p \< 0.05` costs more than it
  buys, and no fixture triggers it. Confirm — this is a real, if cosmetic, correctness gap,
  and it is stated in `docs/REPORTS.md` §6 and on the Limitations page rather than hidden.
- **The multi-cause block in §4 has no fixture.** No committed task is refuted by its table
  *and* undecidable from its text at once, so the block is exercised by a unit test on a
  hand-built `ReportInput`. Confirm; a fixture reaching it would be more convincing than a
  test, and would also exercise `classify_failure`'s "(also: …)" suffix end to end.
- **`is_file_target` keys off the extension**, so `--out report.pdf` is treated as a
  *directory* named `report.pdf` and silently filled with `.md` files. A test pins that
  behaviour rather than the alternative (rejecting unknown extensions). Confirm this is the
  friendlier reading; the argument for it is that `--out results/reports` and `--out
  results/v2.1` must both be directories, and extension-sniffing cannot tell `v2.1` from a
  format.
- **Nothing generated is committed.** `results/reports/` stays gitignored, and the website
  embeds the real `contradicted_f1.md` verbatim instead. Confirm this is preferred to
  force-adding one small example report (which `.gitignore` explicitly contemplates), since
  the embedded copy can drift from what the code emits and only a human would notice.
- **Still open from M8, and now deferred to M13:** `claimverifier verify --task
  <schema-invalid.yaml>` raises a pydantic traceback, while `run-suite` catches
  `ValidationError` and reports it cleanly. It is a one-line fix in
  `scoring.verdict.verify_and_report` (widen the `except`), unrelated to reports.
- **Report determinism has one input the renderer does not control:** the `trace_href` the
  CLI computes with `os.path.relpath`. Reports written beside their traces contain no
  absolute path and are byte-identical across output directories (test-pinned). Reports
  written elsewhere embed a relative path like `../runs/smoke_suite/x.trace.jsonl`, which is
  stable but depends on the two directories' relationship. Confirm this is the right
  guarantee to advertise.

Technical risks
- The reader trusts the *order* of `scoring.check` events to reproduce
  `result.computed_checks` in the order `checks/verification.py` fixed. A check and the
  signal it produced travel in the **same event**, so they cannot be paired with each
  other's neighbours — but a writer that emitted the check events out of order would produce
  a report whose check *table* is reordered, silently. `_index_events` rejects a
  non-contiguous `seq`, which is the only ordering guarantee the format carries.
- `ScoredClaim` is a frozen dataclass compared by value in the round-trip test. `Rule` and
  `CheckSignal` are too. If any of them gains an unhashable or float field, equality may
  become fragile.
- `_index_events` rejects a stream with duplicate singleton events and a non-contiguous
  `seq`, but does not verify that the singletons appear in `SCORING_EVENT_KINDS` order. A
  trace with `scoring.result` before `scoring.support` would render. The events carry no
  cross-references that make this dangerous, and `build_trace` cannot produce it.
- The HTML report inlines ~20 lines of CSS per file. Twelve files is ~4 KB of duplication —
  irrelevant here, but the standalone guarantee is what buys it, and that should stay the
  stated reason.
- `read_summary` catches `OSError` and `JSONDecodeError` and returns `None`. A `summary.json`
  that parses but is *wrong* (a stale gate, a task list from another run) would decorate the
  index with a false gate line. The index says "the comparison against gold lives in
  summary.csv and summary.json", so a reader is pointed at the source of truth, but the gate
  sentence is copied rather than recomputed.

Commands to verify
```bash
python3 -m pytest -q                                     # 600 passed
python3 -m pytest tests/test_reports.py -q                # 98 passed
ruff check .                                             # clean
python3 scripts/00_check_environment.py                  # READY
python3 scripts/01_validate_fixtures.py                  # 11 tasks + 1 suite, VALID
python3 scripts/05_run_smoke_suite.py --out results/runs/ # 11 tasks, gate PASS
claimverifier report --run results/runs/smoke_suite --out results/reports/
claimverifier report --run results/runs/smoke_suite --out results/reports/ --format both
claimverifier report --run results/runs/smoke_suite/contradicted_f1.trace.jsonl   # stdout
scripts/serve_site.sh                                    # then fetch :9002 with urllib
```

To check the central claim by hand — that a report needs nothing but its trace:

```bash
mkdir /tmp/archived && cp results/runs/smoke_suite/contradicted_f1.trace.jsonl /tmp/archived/
claimverifier report --run /tmp/archived --out /tmp/archived   # renders; no task, no paper, no CSV
```

Human feedback
<!-- Human will fill this later. -->
