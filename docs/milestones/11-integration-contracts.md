# Milestone 11 — Integration contracts

## Summary

An `integrations/` package: **five versioned, self-describing export formats**, one per
consumer role named in `docs/PLAN.md` §9, plus a strict reader and a replay loop. Reachable
via `claimverifier export` and `claimverifier replay`. No module in the package imports
anything outside the standard library, `pydantic`, and this project — and a test proves it.

**No external schema was consulted.** None of the five named systems was read, imported, or
run, so this milestone does not claim compatibility with any of them and does not use the
word. What it claims is *containment*: each format is a proposed contract confined to one
~200-line module, and adapting one to a real consumer is that module plus a
`format_version` bump.

## Deliverables

- `src/scientific_claim_verifier/integrations/` —
  `envelope.py` (the five-field header, canonical JSON, the strict reader),
  `records.py` (`Verdict`, `Controls`, `ArtifactRef`, `Provenance`, `ExportContext`,
  `repo_relative`), `run.py` (`LoadedRun`, gold/suite requirements, `check_agreement`),
  `runnable_tasks.py`, `evidence_records.py`, `benchmark.py`, `metrics.py`, `episodes.py`
  (export **and** `replay`), `export.py` (the CLI), `__init__.py` (`REGISTRY`,
  `export_document`, `format_schema`).
- CLI: `claimverifier export --format {runnable-tasks,evidence-records,benchmark,metrics,episodes}`
  with `--list`, `--schema`, `--run`, `--tasks`, `--suite`, `--out`, `--hide-gold`, and the
  four control flags; `claimverifier replay --episodes PATH [--strict] [--json] [--no-gate]`.
- `scripts/07_export_integrations.py`.
- `tests/test_integrations.py` — 86 tests.
- `docs/INTEGRATIONS.md`; `docs/RESULTS.md` M11 section; website (`integrations.html`, new;
  plus `index`, `milestones`, `roadmap`, and the nav on every page).
- `.gitignore`: `results/exports/`.

## Validation

- `python3 -m pytest -q` → **756 passed** (670 prior + 86 new).
- `python3 -m ruff check .` → all checks passed.
- `python3 scripts/01_validate_fixtures.py` → 12 ok / VALID (unchanged).
- `python3 scripts/05_run_smoke_suite.py` → gate PASS (unchanged; nothing on the default
  path changed).
- `claimverifier export --format <each of five> --run results/runs/smoke_suite` → exit 0,
  and each document re-reads through its own strict reader.
- `claimverifier replay --episodes ep.json --strict` → **11/11 reproduced**, every trace
  byte-identical, exit 0.
- All 12 site pages fetched via `urllib` (200, balanced HTML).

## Notes / decisions

- **The honesty claim is the design.** "Compatible import/export formats" for five repos
  nobody in this session has read cannot be delivered honestly as adapters. It can be
  delivered as contracts shaped for a consumer *role*, with the non-dependency **checked**
  (`test_integration_modules_import_only_stdlib_pydantic_and_this_project` parses every
  module's AST) rather than asserted in prose.
- **An export is a function of committed artifacts**, inheriting M9's property: no export
  re-runs the pipeline, and a test deletes `tasks/` to prove three of the five do not even
  read it. `replay` is the sole exception, and exists to re-run.
- **The benchmark declares its metric.** `wrong_verdicts`, lower is better — not accuracy,
  which would reward a version that guessed on the pipeline's one honest refusal. `outcome`
  is computed with the same `TaskOutcome` object `suite.gate()` reads, so the export and the
  gate cannot diverge. A run whose `summary.json` and traces disagree is refused, not scored.
- **`metrics` has a fixed key space** — all 40 metrics on every run, covering every value of
  every closed vocabulary, zero-valued when unseen. A key that appears between two runs is a
  key a diff tool must guess about. Only six metrics declare a direction; `checks_fail` is
  `neutral` because a suite of contradicted claims *should* fail checks.
- **`evidence-records` omits `VerificationCheck.inputs`** — a free-form bag that holds
  captured stdout for `code_execution`. A contract cannot carry a field whose shape is set
  by whichever check wrote it. A test asserts the fixture stdout `accuracy=0.80` appears in
  no record.
- **Four replay statuses, not two.** Only `drifted` blames the pipeline; `inputs_changed` and
  `missing_task` blame the working tree. Each of the four is injected in the tests. Verdict
  equality gates; the trace digest is the stricter signal, reported always and gated under
  `--strict` — the same asymmetry M8 drew between a wrong verdict and a conservative miss.
- **A gap left open, deliberately.** A 1.3 trace records what the pipeline computed, not how
  it was invoked, so it carries none of the four controls. `episodes` recovers `execute` from
  a suite `summary.json` and **refuses** when the operator's `--no-execute` contradicts it;
  the other three are declared by the operator. Closing this needs a `scoring.controls` event
  and schema 1.4 — a trace change, which belongs to the milestone that needs it, not to this
  one. Recorded in `docs/INTEGRATIONS.md` and the review note.
- **Two CLI verbs beyond `docs/PLAN.md` §10**, as `link-evidence`/`run-checks`/`run-sandbox`
  already are. §10's contract remains complete and unchanged.

## Status

Complete. Next: Milestone 12 — Portfolio report.
