Human review: Milestone 13 — Final cleanup

TL;DR
`docs/PLAN.md` §9 asks the last milestone to run the commands and confirm the repository is
clean. Doing only that would have left behind a sentence, and `CLAUDE.md` forbids sentences as
evidence: every substantive claim needs a test, an example, a trace, a result table, a
documented limitation, or an explicit non-goal. "This repository is finished" is a substantive
claim, so it is now a program — `claimverifier final-check` / `python3 scripts/08_final_check.py`
— running seventeen checks and exiting 0 only when all of them pass **and** all of them ran.

Twelve `quality-gate` checks come from `docs/PLAN.md` §11; five `hygiene` checks come from
`CLAUDE.md`'s "what must never be committed", and read `git ls-files` rather than the working
directory, because `.gitignore` says nothing about what is already committed.

The gate found two things on the day it was written. `tests/test_adapters.py` checked only
`adapters/*.py` for HTTP-client imports while its docstring claimed the whole package; the new
AST audit covers all 87 modules under `src/`, `scripts/`, and `tests/`, and refuses the dynamic
imports that could evade it (one allowlisted site, `envcheck.py`, with a written reason). And
adding one CLI verb moved `cli_commands` from 12 to 13, which broke M12's documentation gate
until the doc was updated — the M12 gate working.

1004 tests; ruff clean; fixtures valid; smoke gate PASS and byte-for-byte unchanged. **Nothing
on the default path changed** — no verdict, check, rule, fixture, schema, or export moved.

What changed
- New: `src/scientific_claim_verifier/final_check.py`, `scripts/08_final_check.py`,
  `tests/test_final_check.py` (120 tests), `docs/FINAL_CHECK.md`.
- New CLI verb `final-check` (`--json`, `--no-subprocess`), wired into `cli.py`.
- `docs/LIMITATIONS.md`: new §8 on what the gate cannot check; §7's transport claim widened
  from `adapters/` to the whole audited path. Old §8 (permanent non-goals) is now §9.
- `docs/RESULTS.md`: M13 section, status row, headline mini-table, test table (1004: 120 new
  tests in `test_final_check.py`, and 6 more as the M12 docs gate parametrized over new files).
- `docs/REPRODUCIBILITY.md`: `cli_commands` 12 → 13, new `final_checks` row.
- `tests/test_docs.py`: `final_checks` added to the machine-derived headline numbers.
- `README.md`, and five website pages (`index`, `milestones`, `results`, `limitations`, `roadmap`).

What should be checked later
- **Is seventeen the right decomposition?** `no_oversized_files` and `repository_stays_small`
  could be one check; `smoke_suite_runs_offline` deliberately fuses two conditions (task count
  and gate verdict) into one outcome because either alone misleads. A reviewer may split or
  merge differently. The count is not load-bearing — but it *is* in the machine-checked headline
  table as `final_checks`, so changing it changes a documented number, on purpose.
- **Are the thresholds right?** 256 KiB per file (actual max: ~60 KiB, `docs/RESULTS.md`) and
  4 MiB across the tree (actual: ~1.8 MiB). They are tripwires with ~4× and ~2.2× headroom.
  `docs/RESULTS.md` grows every milestone and is the file that will hit the per-file limit first.
- **Are the eight credential patterns the right eight?** They are shape-matchers: they cannot
  find a secret that looks like prose, and they *will* flag a fake key committed as an example.
  Both are argued to be the right failure. `assigned-credential` is the only heuristic one
  (`password|passwd|api_key|apikey|secret_key` followed by `=` or `:` and a quoted 8+ char
  value); it found no false positive across 192 tracked files, but it is the pattern most likely
  to produce one later. Note the scanner is **not** exempt from itself — please confirm that
  argument holds, since it is the reason no exclusion list exists.
- **Is `nothing_imports_a_network_client` sound, or merely reassuring?** It parses import
  statements and refuses `importlib`/`__import__`/`exec`/`eval`/`compile` outside an allowlist.
  It cannot see `getattr(builtins, "__imp" + "ort__")`, a C extension, or a subprocess. The
  claim it licenses is narrow — *the parent process imports no network client and has no
  mechanism to hide one* — and `docs/FINAL_CHECK.md` states exactly that and no more.
- **`code_reproduction_executed` counts an `error` as success.** `unreproducible_accuracy` exits
  1 by design and the sandbox executed it, which is what §11 asks. But `error` would also be the
  status if the *runner* failed rather than the script. Distinguishing the two would mean reading
  the sandbox trace rather than the check status. Is the current reading too generous?
- **The working tree's verdict is not asserted by the test suite**, only by the script — because
  whether the tree is clean depends on when `pytest` ran. A reviewer may want a marked test that
  runs only in CI.
- The `docs_explain_the_system` check tests existence, a 1,500-character floor, and a link from
  the README. It cannot tell whether a document explains anything. It is labelled a "mechanical
  shadow" in both the code and the doc; a reviewer may think a floor that weak is worse than none.

Technical risks
- **The gate shells out.** `git` (twice), `ruff`, and `pytest`. `tests_pass` raises
  `RecursionRefused` when `PYTEST_CURRENT_TEST` is set, and `run_checks` refuses the same at the
  top, so a test cannot spawn its own runner. `check_and_report` catches the refusal and returns
  exit **2** — neither pass nor fail. If a future test calls `run_checks()` with defaults, it
  gets a loud exception rather than a hang. That is the intended behaviour, and it is asserted.
- **`_outcome` raises `KeyError` for an undeclared check name.** Deliberate: the registry is
  load-bearing, and a check that never announced itself must not be able to report a result. It
  does mean a typo in a check name is a crash rather than a lint error.
- **The gate runs the suite twice in the test process** (once for `live_report`, once for the
  report-rendering test), executing three fixture scripts each time. ~3.5 s for
  `tests/test_final_check.py`; the whole run is ~27 s. Offline and harmless, but it means a
  repository-hygiene test depends on the sandbox.
- **`no_secret_material` reads every tracked text file.** 192 files, ~1.8 MB, eight regexes. If
  the repository ever tracks a large generated file, `no_oversized_files` fires first and
  `tracked_texts` skips it, so the scan cannot become quadratic in a file it already rejected.
- **Two checks depend on private-ish internals.** `default_path_needs_no_paid_api` reads
  `adapter.enabled` / `.dry_run` / `.transport` / `.guard.max_usd`, and the `pyproject.toml`
  parse is a string split on `dependencies`, not a TOML parse. A restructured `pyproject.toml`
  could silently narrow what the check reads. The TOML parse would be one stdlib import away
  (`tomllib`) and was not taken — a reviewer may reasonably ask why not.
- No source behaviour changed, so the risk of regression is nil. The risk is that the gate
  **overclaims** — that a reader takes "17 checks pass" for "the verdicts are correct". The
  docs say four times, in four places, that it means nothing of the sort.

Commands to verify
- `python3 scripts/08_final_check.py`                     # 17/17, exit 0 (needs a clean tree)
- `python3 scripts/08_final_check.py --json`              # the same, machine-readable
- `python3 scripts/08_final_check.py --no-subprocess`     # INCOMPLETE, exit 1 — by design
- `python3 -m pytest -q`                                  # 1004 passed
- `python3 -m pytest tests/test_final_check.py -q`        # 120, the sensitivity suite
- `python3 -m ruff check .`
- `python3 scripts/01_validate_fixtures.py`               # 12 ok / VALID
- `python3 scripts/05_run_smoke_suite.py --out results/runs/`   # gate PASS, exit 0
- `./scripts/serve_site.sh`                               # then read Results and Limitations
- Sensitivity check: `touch scratch.txt` and re-run `scripts/08_final_check.py` — it must fail
  on `working_tree_is_clean` and name the file. Then add `import socket` to any module under
  `src/` and re-run — it must fail on `nothing_imports_a_network_client` and name the module.

Human feedback
<!-- Human will fill this later. -->
