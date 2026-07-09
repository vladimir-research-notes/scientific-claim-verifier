# Commit note — Milestone 11

**Commit message:** `M11: integration contracts (five exports, one replay, no external dependency)`

## What this commit adds

- `src/scientific_claim_verifier/integrations/` — `envelope.py` (self-describing header,
  canonical JSON, strict reader), `records.py` (the shared `Verdict`/`Controls`/
  `ArtifactRef`/`Provenance` vocabulary and `ExportContext`), `run.py` (`LoadedRun`, gold and
  suite preconditions, trace↔summary agreement check), and five format modules:
  `runnable_tasks.py`, `evidence_records.py`, `benchmark.py`, `metrics.py`, `episodes.py`.
  `export.py` holds the `export` CLI; `episodes.py` holds `replay`. `__init__.py` is the
  registry (`REGISTRY`, `export_document`, `format_schema`).
- CLI wiring: `claimverifier export` and `claimverifier replay` (`cli.py`).
- `scripts/07_export_integrations.py`.
- `tests/test_integrations.py` (86 tests); `docs/INTEGRATIONS.md`; `docs/RESULTS.md` M11
  section; `site/integrations.html` (new page) plus nav on all 12 pages and updates to
  `index.html`, `milestones.html`, `roadmap.html`; README; milestone/commit/review notes.
- `.gitignore`: `results/exports/`.

## Excluded (per operating principles)

No dependency on any of the five named systems — nothing was read, imported, or run, and no
compatibility is claimed. No new runtime dependency. No network access, no paid API, no
schema bump (a 1.3 trace is read unchanged). Generated documents under `results/exports/`
are gitignored; nothing under `results/` is committed.

## Verification at commit time

- `python3 -m pytest -q` → 756 passed.
- `python3 -m ruff check .` → all checks passed.
- `python3 scripts/01_validate_fixtures.py` → 12 ok / VALID; `05_run_smoke_suite.py` → gate PASS.
- All five formats export from the committed smoke run, re-read through their own strict
  reader, and contain no absolute path.
- `claimverifier replay --episodes ep.json --strict` → 11/11 reproduced, traces byte-identical.
- All 12 site pages fetched via `urllib` (200, balanced HTML).
