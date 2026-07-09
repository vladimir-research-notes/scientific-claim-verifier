# Milestone 13 — Final cleanup

## Summary

`docs/PLAN.md` §9 asks the last milestone to run tests, lint, fixture validation, the smoke
suite, report generation, and `git status`; to verify that no secrets, private papers, large
data, caches, or paid-API outputs are committed; and to confirm a clean tree.

That is a checklist, and a checklist is only worth the memory of whoever ran it. `CLAUDE.md`
sets a higher bar: *every substantive claim in the repo must be backed by a test, a
reproducible example task, a trace artifact, a result table, a documented limitation, or an
explicit non-goal.* **"This repository is finished" is a substantive claim.** So M13's
deliverable is not a report saying the commands were run. It is the command:

```bash
python3 scripts/08_final_check.py     # or: claimverifier final-check
```

Seventeen checks, two groups, one exit code. Exit `0` only when every check passed **and**
every check ran.

**Nothing on the default path changed.** No verdict, check, rule, fixture, schema, or export
moved. The smoke gate is unchanged, and it should be.

## Deliverables

- `src/scientific_claim_verifier/final_check.py` (new) — twelve `quality-gate` checks from
  `docs/PLAN.md` §11 and five `hygiene` checks from `CLAUDE.md`, a registry that a check must
  declare itself in before it can report an outcome, and a report whose `ok` requires
  completeness as well as success.
- `scripts/08_final_check.py` (new) — the thin wrapper, matching the other seven scripts.
- `claimverifier final-check` (new verb) — the thirteenth and last, and the only one whose
  subject is the repository rather than a claim.
- `tests/test_final_check.py` (new, 120 tests) — one rejected input per check.
- `docs/FINAL_CHECK.md` (new) — the seventeen checks, four decisions worth arguing with, and
  the four things the gate cannot do.
- `docs/LIMITATIONS.md` — new §8 (the gate bounds the repository, not the world); §7's
  transport claim widened from `adapters/` to the whole audited path.
- `docs/RESULTS.md` — M13 section, status row, headline mini-table, test table (1004).
- `docs/REPRODUCIBILITY.md` — `cli_commands` 12 → 13, new `final_checks` row, reproduce block.
- `tests/test_docs.py` — `final_checks` added to the machine-derived headline numbers.
- Website: `index.html` (status, CLI), `milestones.html` (M13 done), `results.html` (the gate,
  and what it does not measure), `limitations.html` (its four limits), `roadmap.html` (the build
  plan is finished, and checked).

## Validation

- `python3 -m pytest -q` → **1004 passed** (878 prior + 126 new).
- `python3 -m ruff check .` → all checks passed.
- `python3 scripts/01_validate_fixtures.py` → 12 ok / VALID (unchanged).
- `python3 scripts/05_run_smoke_suite.py --out results/runs/` → gate **PASS**, exit 0 (unchanged).
- `python3 scripts/04_generate_report.py --run results/runs/smoke_suite` → 11 reports + index.
- `python3 scripts/08_final_check.py` → **17/17 pass**, exit 0, run after the commit.
- All 12 site pages + `style.css` fetched via `urllib` → 200, balanced tags, `<title>` present.

## What the gate found

Two things, on the milestone that introduced it. A gate that finds nothing on the day it is
written was written to find nothing.

**A test was narrower than the docstring it substantiated.**
`tests/test_adapters.py::test_no_adapter_module_imports_an_http_client` scans `adapters/*.py`
for the substring `import <client>`. The docstring it supports says *no module in this
package* imports one. The stronger claim was true and unchecked.
`nothing_imports_a_network_client` now parses the AST of all 87 modules under `src/`,
`scripts/`, and `tests/`.

Parsing rather than grepping is what makes the audit correct, not merely broader.
`sandbox/policy.py` contains the text `import socket` inside `SITECUSTOMIZE_SOURCE` — a
*string* of Python that the sandboxed child executes at startup precisely in order to disable
`socket`. A substring scan flags it and is wrong about what it found. An AST walk does not,
because the parent never imports it. `test_audit_module_ignores_a_network_name_inside_a_string`
pins that distinction so a future "improvement" to a faster substring scan fails.

An import audit is only as good as its evasion story, so the same check refuses `importlib`,
`__import__`, `exec`, `eval`, and `compile` anywhere on the audited path unless the site is in
`DYNAMIC_IMPORT_ALLOWLIST` **with a written reason**. Exactly one is: `envcheck.py`, which
probes for the optional analysis libraries by name from a committed list. A stale allowlist
entry — one naming a module that no longer exists — is itself a failure, because an exemption
nobody is reading is an exemption nobody is checking.

**Adding one CLI verb broke the M12 documentation gate**, exactly as designed. `cli_commands`
moved from 12 to 13, and `test_reproducibility_headline_numbers_match_the_live_pipeline`
failed until `docs/REPRODUCIBILITY.md` was updated. A gate whose failure is inconvenient is a
gate that works.

## Notes / decisions

- **Hygiene is checked against what git tracks, not the working directory.** `.gitignore`
  governs what git will *add*; it says nothing about what is already committed, and a rule
  written after the fact does not retract a file. The tracked set is the set that can leak, so
  it is the set the gate reads — via `git ls-files -z`, NUL-separated, because a newline in a
  filename should not be able to hide a file from its own audit.

- **A partial run is not a passing run.** `--no-subprocess` omits `tests_pass` and
  `lint_is_clean`. The report then prints `INCOMPLETE` and exits non-zero *even when every
  check that ran passed*. A gate that skipped two checks and printed `PASS` would be worse than
  no gate, because it would be believed. `FinalCheckReport.ok` is `all_passed and complete`,
  and three tests pin that conjunction.

- **Nothing is exempt from the secret scan, least of all the scanner.** A scanner that skips
  its own source is a scanner with a place to hide a key. `final_check.py` and
  `tests/test_final_check.py` are scanned like every other tracked file. This is possible
  because the eight patterns are *regexes* and no regex here matches its own source text
  (`AKIA[0-9A-Z]{16}` does not match the literal `AKIA[0-9A-Z]{16}`), and because the fake
  credentials the tests use are assembled from fragments at run time, existing in memory and
  never on disk. `test_the_secret_scanner_is_not_exempt_from_itself` asserts both files are in
  the scanned set.

- **`error` means "executed" for a script and "computed nothing" for a statistic.** The three
  "at least one" checks look like the same function with a different argument, and are not.
  `dataset_statistic_recomputed` and `table_claim_checked` accept `pass` or `fail` — a
  recomputation that *disagrees* with the claim has still recomputed it, and
  `dataset_mean_overstated` and `contradicted_f1` exist to disagree. `code_reproduction_executed`
  additionally accepts `error`, because `unreproducible_accuracy` reads a `predictions.csv` the
  paper never released, exits 1, and that is the sandbox working. Only `skipped` means no
  process ever started. Three tests pin the asymmetry.

- **The registry is load-bearing.** `_outcome()` looks its caller's name up in `SPECS` and
  raises `KeyError` on a name that was never declared, so a check cannot report a result it did
  not announce. The converse is pinned too:
  `test_a_real_run_produces_exactly_the_checks_the_registry_declares` enumerates a live run
  against the registry, so neither can drift from the other.

- **`final_checks` was added to the machine-checked headline table** rather than written into
  `docs/FINAL_CHECK.md` by hand. `len(final_check.CHECKS)` is re-derived on every test run, so
  the document and the program cannot disagree about how many checks exist. The test count
  stays out of the table, for the reason M12 gave: a test asserting how many tests exist is
  self-referential and rots on contact with its own success.

- **The gate refuses to run `pytest` inside `pytest`.** `run_checks(subprocess_checks=True)`
  and `tests_pass()` both raise `RecursionRefused` when `PYTEST_CURRENT_TEST` is set. Tests
  call `run_checks(subprocess_checks=False)`; the shelled-out checks are split into a
  subprocess call and a pure verdict on its exit code, so `process_verdict` is tested to
  destruction without spawning anything. `check_and_report` catches the refusal and returns
  exit **2** — neither pass nor fail, because a gate that could not run must not report a verdict.

- **The working tree's cleanliness is asserted by the script, not by the test suite.** Whether
  the tree is clean is a fact about the moment `pytest` ran, not about the code under test; a
  test pinning it would fail whenever a file was open in an editor. `test_final_check.py`
  asserts that `working_tree_is_clean` *ran* and that every other live check *passed*. The
  verdict itself belongs to `scripts/08_final_check.py`, which is the last command before a
  milestone commits.

- **What the gate cannot do is written down twice** — in `docs/FINAL_CHECK.md` and in the
  module's own docstring — because the second is the one a reader of the code will find. Two of
  the four limits are permanent: it cannot prove that nothing was pushed (a gate cannot certify
  the absence of an act it is forbidden to observe; `CLAUDE.md` denies `git push` and
  `git remote`, and the sandbox, not this file, is what enforces that), and it cannot decide
  that a fixture paper is synthetic (a judgment about provenance, of which the gate checks only
  the mechanical shadow: small, credential-free, and byte-reproducible from committed source).

- **Thresholds are tripwires, not targets.** 256 KiB per tracked file against an actual maximum
  of ~60 KiB; 4 MiB across the tree against an actual ~1.8 MiB. A milestone that approaches
  either has changed what this repository is, which is the only thing the number is there to say.

## Status

Complete. This is the last milestone in `docs/PLAN.md` §9. The repository satisfies every
condition in §11 that can be checked from inside it, and names the two that cannot.
