# Commit note — Milestone 12

**Commit message:** `M12: portfolio docs, and the gate that keeps them true`

## What this commit adds

- `docs/METHODOLOGY.md` — the design commitments behind the pipeline: the five audit
  channels, the stage contract (each stage cannot do the next stage's job), status-vs-signal,
  rule-based ordered inference, report-as-a-function-of-trace, the asymmetric gate,
  determinism as a precondition, and every method labelled a heuristic.
- `docs/LIMITATIONS.md` — the canonical limitations list, plus three gaps previously
  documented only in module docstrings: `figure_recompute` named but unimplemented; four
  vocabulary values unreachable end to end; a 1.3 trace carries none of the four controls.
- `docs/REPRODUCIBILITY.md` — environment, the command for every number in `RESULTS.md`,
  what is byte-reproducible and what is not, and a **machine-checked** table of fifteen
  headline numbers.
- `docs/PAPER_PATH.md` — the honest research path: three studies in dependency order, the
  metric argument and the counterweight that makes it honest, threats to validity, and the
  permanent non-goals.
- `tests/test_docs.py` (122 tests) — the documentation gate: the plan's promised documents
  exist (its map is parsed), all relative links in 59 Markdown docs and 12 site pages
  resolve, the docs invoke only real CLI verbs and every verb is documented, referenced
  scripts exist, milestone notes are complete and gap-free, no review note claims a review
  happened, and the fifteen headline numbers are **re-derived from a live suite run**.
- `README.md` — restructured to portfolio quality: problem, worked example (the contradiction
  the project exists for, and the claim the system refuses to decide), architecture with the
  stage contract, smoke-suite results, reproduction commands, CLI table, limitations, research
  path, milestone runner and permissions, doc index.
- `docs/RESULTS.md` — M12 section, status row, test table (878).
- `site/` — `index.html` (status), `milestones.html` (M12 done), `results.html`, `roadmap.html`
  (the research path, now written), `limitations.html`.

## Excluded (per operating principles)

No source change under `src/`: no verdict, check, rule, fixture, schema, or export moved, and
the smoke gate is unchanged. No new runtime or dev dependency. No network access, no paid API,
no secrets, no generated artifacts committed (`results/` stays gitignored).

## Verification at commit time

- `python3 -m pytest -q` → **878 passed** (756 prior + 122 new).
- `python3 -m ruff check .` → all checks passed.
- `python3 scripts/01_validate_fixtures.py` → 12 ok / VALID (unchanged).
- `python3 scripts/05_run_smoke_suite.py --out results/runs/` → gate **PASS**, exit 0 (unchanged).
- All 12 site pages + `style.css` fetched via `urllib` → 200, balanced tags, `<title>` present.
- The headline gate was checked for sensitivity: a doctored `wrong_verdicts` value is caught by
  the equality assertion, and a garbled table is caught by the completeness assertion. A gate
  that cannot fail proves nothing when it passes.
