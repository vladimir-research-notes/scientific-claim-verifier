# Commit note — Milestone 13

**Commit message:** `M13: the definition of done, as a command`

## What this commit adds

- `src/scientific_claim_verifier/final_check.py` — seventeen checks with an exit code:
  twelve `quality-gate` checks from `docs/PLAN.md` §11 (tests, lint, no network client
  imported, fixtures valid, suite ≥ 8 tasks and gating, reports rendered from traces alone,
  a dataset statistic recomputed, a table claim checked, a script executed in the sandbox,
  the four required documents present and linked, the paid adapter unable to spend, a clean
  tree) and five `hygiene` checks from `CLAUDE.md` (no forbidden path, no oversized file, a
  small tree, no credential-shaped string, no paid-API output).
- `scripts/08_final_check.py` — the wrapper, matching the other seven scripts.
- `claimverifier final-check` — the thirteenth CLI verb, with `--json` and `--no-subprocess`.
- `tests/test_final_check.py` (120 tests) — one rejected input per check: a tracked `.env`,
  an oversized file, a planted credential, a tracked response cache, a dirty porcelain, a
  failing validation report, a three-task suite, an inapplicable suite gate, a `skipped`
  script, an empty trace directory, a malformed trace, a deleted / emptied / orphaned
  document, a module importing `socket`, an unlisted dynamic import, a stale allowlist entry,
  a priced vendor model, and an `httpx` dependency in `pyproject.toml`.
- `docs/FINAL_CHECK.md` — the seventeen checks, four decisions worth arguing with, and the
  four things the gate cannot do.
- `docs/LIMITATIONS.md` — new §8 (the gate bounds the repository, not the world); §7's
  "no transport" claim widened from `adapters/` to all 87 audited modules.
- `docs/RESULTS.md` — M13 section, status row, headline mini-table, test table (1004).
- `docs/REPRODUCIBILITY.md` — `cli_commands` 12 → 13 and a new `final_checks` row, both
  re-derived from the live pipeline by `tests/test_docs.py`.
- `tests/test_docs.py` — `final_checks` added to `live_numbers`.
- `README.md` — the gate in the quickstart, the CLI table, and the doc index.
- `site/` — `index.html`, `milestones.html`, `results.html`, `limitations.html`, `roadmap.html`.

## What it found

`tests/test_adapters.py::test_no_adapter_module_imports_an_http_client` scans only
`adapters/*.py`, by substring, while the docstring it substantiates says *no module in this
package* imports an HTTP client. The stronger claim was true and unchecked; the new AST audit
checks it across all 87 modules of `src/`, `scripts/`, and `tests/`, and additionally refuses
any dynamic-import mechanism that could hide one (exactly one site is allowlisted, with a reason).

Adding the `final-check` verb moved `cli_commands` from 12 to 13 and broke M12's documentation
gate until `docs/REPRODUCIBILITY.md` was updated. That is the M12 gate working.

## Excluded (per operating principles)

No change to any verdict, check, rule, fixture, schema, export, or trace format; the smoke
gate is byte-for-byte unchanged. No new runtime or dev dependency (`final_check.py` imports
only the standard library and this package). No network access, no paid API, no secrets, no
generated artifacts committed — `results/` stays gitignored, and the gate runs the suite into
a temporary directory so that checking the repository cannot modify it.

## Verification at commit time

- `python3 -m pytest -q` → **1004 passed** (878 prior + 126 new).
- `python3 -m ruff check .` → all checks passed.
- `python3 scripts/01_validate_fixtures.py` → 12 ok / VALID (unchanged).
- `python3 scripts/05_run_smoke_suite.py --out results/runs/` → gate **PASS**, exit 0 (unchanged).
- `python3 scripts/04_generate_report.py --run results/runs/smoke_suite` → 11 reports + index.
- `python3 scripts/08_final_check.py` → **17/17 pass**, exit 0 (run after the commit, on a
  clean tree; `working_tree_is_clean` cannot pass before one).
- All 12 site pages + `style.css` fetched via `urllib` → 200, balanced tags, `<title>` present.
- Sensitivity: every check was fed an input it must reject, and rejected it. The gate was also
  observed failing for real — `working_tree_is_clean` was red on every pre-commit run of this
  milestone, which is the only way to know the check is wired to anything.
