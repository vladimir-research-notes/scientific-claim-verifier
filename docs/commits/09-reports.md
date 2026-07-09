# Commit note — M9 Reports

## Commit message

```
M9: auditable reports rendered from traces (schema 1.3, self-describing traces)

Add src/scientific_claim_verifier/reports/, `claimverifier report`, and
scripts/04_generate_report.py: an auditable Markdown (or standalone HTML) report per
claim -- extracted claim, supporting text, computed checks, inference, limitations,
trace link -- in six numbered sections, so the five audit channels cannot silently
merge. Eleven reports and an index from the smoke suite's eleven traces, offline, on a
CPU, in <0.1s. Completes the docs/PLAN.md section 10 CLI contract.

A REPORT IS A FUNCTION OF ITS TRACE. The renderer imports no pipeline stage, opens no
artifact, re-runs no check, and never reads result.json. It reads one
<task_id>.trace.jsonl and reconstructs the M7 ScoredClaim from those bytes. A test
scores every committed fixture, writes its trace, reads it back, and asserts the
reconstruction EQUALS the original result, the three named rules, every per-check
signal, and the extracted claim. docs/PLAN.md section 11's "reports are generated from
traces" is now a property the build enforces, not a slogan. A run archived months ago,
whose papers and CSVs are long gone, still reports.

THE TRACE WAS NOT SELF-DESCRIBING, SO M9 CHANGED IT. RunTrace.to_jsonl() serializes the
event stream and nothing else, so a trace's run_id, task_id, and bundle_id -- real
fields on the model -- survived on disk only in the FILENAME, and scoring.claim recorded
five of the extracted claim's fields rather than all of them. A generator claiming to
"read the trace" would have been reading the trace plus a guess about the path.

SCHEMA_VERSION 1.2 -> 1.3. No model changed; the event contract did:
  - scoring.run   NEW, and first: run_id, task_id, bundle_id, schema_version.
  - scoring.claim now carries the whole claim, minus evidence_links (scoring.evidence
                  already records that list -- one fact, one place).
  - scoring.result no longer repeats schema_version.
The version was bumped although no model changed, because SCHEMA_VERSION is stamped into
every trace precisely so a reader can tell whether it understands the bytes. Readers
compare the MAJOR component: a 1.9 trace reads, a 2.0 trace is refused, and a pre-1.3
trace is refused WITH AN INSTRUCTION rather than guessed at from its filename.

REFUSING TO RENDER IS A FEATURE. Every object comes back through its pydantic model
(extra="forbid"). Twelve tests assert that a missing, empty, non-JSONL, truncated,
reordered, duplicated, foreign (sandbox.*), schema-violating, or future-major-version
trace raises ReportError naming the file -- rather than producing a plausible-looking
report built from garbage. No traceback reaches the user: a malformed trace is a fact
about the file, not a bug in the renderer.

ONE DOCUMENT, TWO SERIALIZERS. build_document() makes every content decision;
markdown.py and html.py make none. The formats cannot disagree about what a run
concluded, only about punctuation, and a test asserts they carry the same labels, check
ids, section titles, and limitations. Blocks carry plain text, never inline markup: a
serializer can only escape safely if it is not also handed markup to preserve. HTML is
one standalone file -- no stylesheet, no JS, no network fetch -- because an audit
artefact may be read years later from a copied directory.

A REPORT NEVER PRINTS ITS TASK'S GOLD OUTCOME, and cannot: a trace records what the
pipeline concluded, not what it should have. Gold agreement lives in summary.csv and
summary.json, where a wrong verdict and an honest refusal to decide are counted apart.
The index reports the gate a suite run already decided and points at those files; it
does not tally an accuracy, and says so.

Trace links are relative to where the report is written, so a run directory can be
copied, archived, or served with no broken link and no absolute path. Reports written
beside their traces are byte-identical across output directories -- the same guarantee
summary.csv carries (M8). Reports are named from the run_id recorded IN the trace, not
from its filename.

Tests: tests/test_reports.py (98 new); test_scoring.py +2 (the run event, the
whole-claim event); test_schemas.py updated for 1.3. 600 total, CPU-only and offline.
Docs: REPORTS.md (new), RESULTS (M9 section), README. Website: example-report
(rewritten around the real generated report), index, results, milestones, limitations.
No new dependencies.
```

## Files

**New**

- `src/scientific_claim_verifier/reports/__init__.py` — block model, `Document`,
  `build_document`, `build_index_document`.
- `src/scientific_claim_verifier/reports/reader.py` — `ReportInput`, `read_report`,
  `discover_traces`, `read_summary`, `order_of`, `ReportError`.
- `src/scientific_claim_verifier/reports/markdown.py` — `render_markdown`, `escape_cell`.
- `src/scientific_claim_verifier/reports/html.py` — `render_html`, `escape`, `STYLE`.
- `src/scientific_claim_verifier/reports/render.py` — `report_and_write`, `write_reports`,
  `href`, `ordered`, the `report` CLI.
- `scripts/04_generate_report.py`
- `tests/test_reports.py` (98 tests)
- `docs/REPORTS.md`
- `docs/milestones/09-reports.md`, `docs/commits/09-reports.md`,
  `docs/review_notes/09-reports-human-review.md`

**Changed**

- `src/scientific_claim_verifier/schemas.py` — `SCHEMA_VERSION` `1.2` → `1.3` (+ why).
- `src/scientific_claim_verifier/scoring/verdict.py` — `scoring.run` event;
  `scoring.claim` carries the whole claim; `scoring.result` drops `schema_version`;
  `SCORING_EVENT_KINDS`; docstring.
- `src/scientific_claim_verifier/cli.py` — `report` subcommand registered.
- `tests/test_scoring.py` (+2), `tests/test_schemas.py` (version).
- `README.md`, `docs/RESULTS.md`.
- `site/example-report.html` (rewritten), `site/index.html`, `site/results.html`,
  `site/milestones.html`, `site/limitations.html`.

## Not in this commit

- **Markdown → HTML conversion of report prose.** The HTML renderer walks the document
  tree, not the Markdown text. Two serializers over one model; no converter, no dependency.
- **Gold outcomes in reports.** Deliberate, and permanent. See `docs/REPORTS.md` §6.
- **Committed generated reports.** `results/reports/` stays gitignored. The website embeds
  the real output of `contradicted_f1` verbatim instead.
- **The `verify` schema-error path.** The M8 review asked whether
  `verify --task <schema-invalid.yaml>` handing the user a pydantic traceback (where
  `run-suite` reports it cleanly) belongs in "M9's cleanup". It is an M7 code path with
  nothing to do with reports; it is left for **M13 — Final cleanup**, and recorded again in
  this milestone's review notes so it is not lost.
