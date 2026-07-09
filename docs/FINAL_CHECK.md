# FINAL_CHECK — the definition of done, as a command (Milestone 13)

`docs/PLAN.md` §9 asks Milestone 13 to "run tests, lint, fixture validation, smoke suite,
report generation, `git status`; verify no secrets, private papers, large data, caches, or
paid-API outputs, and a clean tree."

That is a checklist. A person can run a checklist and report that it passed, and the
report is worth exactly as much as the person's memory. `CLAUDE.md` sets a higher bar than
that: *every substantive claim in the repo must be backed by a test, a reproducible
example task, a trace artifact, a result table, a documented limitation, or an explicit
non-goal.* "The repository is finished" is a substantive claim. So it is a program.

```bash
python3 scripts/08_final_check.py            # or: claimverifier final-check
python3 scripts/08_final_check.py --json     # the same report, machine-readable
python3 scripts/08_final_check.py --no-subprocess   # skip pytest + ruff; reports INCOMPLETE
```

Exit `0` only when every check passed **and** every check ran. Exit `1` on a failure or an
incomplete run. Exit `2` when the gate could not run at all — a verdict it refuses to give
rather than guess at.

## Seventeen checks, from two documents

`quality-gate` checks come from `docs/PLAN.md` §11, which says when the system is
finished. `hygiene` checks come from `CLAUDE.md`, which says what must never enter the
repository. They are different questions and the report keeps them apart.

| Check | Group | What it establishes |
| --- | --- | --- |
| `tests_pass` | quality-gate | `python3 -m pytest -q` exits 0 |
| `lint_is_clean` | quality-gate | `python3 -m ruff check .` exits 0 |
| `nothing_imports_a_network_client` | quality-gate | no audited module imports one, and none can hide one |
| `fixtures_validate` | quality-gate | every committed task and suite file validates |
| `smoke_suite_runs_offline` | quality-gate | ≥ 8 tasks end to end, and the suite gate passes |
| `reports_render_from_traces` | quality-gate | one report per claim, from JSONL traces alone |
| `dataset_statistic_recomputed` | quality-gate | ≥ 1 dataset statistic recomputed from its CSV |
| `table_claim_checked` | quality-gate | ≥ 1 table claim checked against its table |
| `code_reproduction_executed` | quality-gate | ≥ 1 fixture script executed in the sandbox |
| `docs_explain_the_system` | quality-gate | methodology, limitations, safety, reproduction |
| `default_path_needs_no_paid_api` | quality-gate | the api adapter is built unable to spend |
| `working_tree_is_clean` | quality-gate | `git status --porcelain` is empty |
| `no_forbidden_paths` | hygiene | no secret, cache, virtualenv, weight, or log is tracked |
| `no_oversized_files` | hygiene | no tracked file exceeds 256 KiB |
| `repository_stays_small` | hygiene | the tracked tree stays under 4 MiB |
| `no_secret_material` | hygiene | no tracked file contains a credential-shaped string |
| `no_paid_api_outputs` | hygiene | the only committed model responses are hand-authored |

The count is not maintained by hand. `final_checks` is one of the headline numbers in
[REPRODUCIBILITY.md](REPRODUCIBILITY.md) §2, re-derived from `final_check.CHECKS` on every
test run, so this table and the program cannot disagree about how many checks exist.

## Four decisions worth arguing with

**Hygiene is checked against what git tracks, not against the working directory.**
`.gitignore` governs what git will *add*. It says nothing about what is already committed,
and a rule written after the fact does not retract a file. The tracked set is the set that
can leak, so it is the set the gate reads — `git ls-files -z`, NUL-separated, because a
newline in a filename should not be able to hide a file from its own audit.

**A partial run is not a passing run.** `--no-subprocess` omits `tests_pass` and
`lint_is_clean`. The report then prints `INCOMPLETE` and exits non-zero, even when every
check that ran passed. A gate that skipped two checks and printed `PASS` would be worse
than no gate, because it would be believed.

**Nothing is exempt from the secret scan — least of all the scanner.** A scanner that
skips its own source is a scanner with a place to hide a key. `final_check.py` and
`tests/test_final_check.py` are scanned like every other tracked file. This works because
the eight patterns are *regexes*, and no regex here matches its own source text; the fake
credentials the tests use are assembled from fragments at run time, so they exist in
memory and never on disk. `test_the_secret_scanner_is_not_exempt_from_itself` asserts both
files are in the scanned set.

**`error` means "executed" for a script and "computed nothing" for a statistic.** The three
"at least one" checks look alike and are not. `dataset_statistic_recomputed` and
`table_claim_checked` accept `pass` or `fail` — a recomputation that *disagrees* with the
claim has still recomputed it, and `dataset_mean_overstated` and `contradicted_f1` are in
the suite precisely to disagree. `code_reproduction_executed` additionally accepts `error`,
because `unreproducible_accuracy` reads a `predictions.csv` the paper never released, exits
1, and *that is the sandbox working*. Only `skipped` means no process ever started.

## What the gate cannot do

Four limits, stated here and in the module's own docstring. Two of them are permanent.

1. **It cannot prove that nothing was pushed.** §11 asks for a clean tree *and* an unpushed
   history. The first is checkable from inside; the second is not. The gate reads the tree,
   contacts no remote, and inspects no remote ref — `CLAUDE.md`'s permission policy denies
   `git push` and `git remote` outright. Absence of a push is enforced by the sandbox the
   agent runs in, not by this file. A gate cannot certify the absence of an act it is
   forbidden to observe; it can only refuse to be the thing that performs it.

2. **It cannot decide that a fixture paper is synthetic.** "Fixtures are synthetic or open"
   is a judgment about provenance, and no program makes it. The gate checks the mechanical
   shadow — every committed file is small, none matches a credential pattern, and the only
   committed model responses regenerate byte-for-byte from committed source — and stops
   there. See [LIMITATIONS.md](LIMITATIONS.md).

3. **It sees imports, not behaviour.** `nothing_imports_a_network_client` parses the AST of
   all 87 modules under `src/`, `scripts/`, and `tests/`, and finds no network client. That
   is a claim about *import statements*. So the gate also refuses any dynamic-import
   mechanism — `importlib`, `__import__`, `exec`, `eval`, `compile` — that could hide one,
   unless the site is named in `DYNAMIC_IMPORT_ALLOWLIST` **with a reason**. Exactly one
   such site exists: `envcheck.py`, which probes whether the optional analysis libraries are
   installed, by name, from a committed list. Together the two facts bound the parent
   process. They say nothing about a child, and nothing about a syscall.

4. **The sandbox's child imports `socket` on purpose.** `sandbox/policy.py` ships
   `SITECUSTOMIZE_SOURCE`, a *string* of Python that the sandboxed child executes at startup
   in order to replace `socket`'s entry points with stubs that raise. An AST audit does not
   look inside string constants, and should not: the parent never runs that code. A
   substring scan would "find" `socket` there and be wrong about what it found. That guard
   is cooperative, not a security boundary, and [SANDBOX.md](SANDBOX.md) says so. This gate
   neither restates that claim nor strengthens it.

## Every check can fail, and is shown to

`tests/test_final_check.py` (120 tests) hands each check an input it must reject, and
asserts the rejection: a tracked `.env`, an oversized file, a planted credential, a tracked
response cache, a dirty porcelain, a failing validation report, a three-task suite, an
inapplicable suite gate, a `skipped` script, an empty trace directory, a malformed trace, a
deleted document, an emptied document, an orphaned document, a module importing `socket`,
an unlisted dynamic import, a stale allowlist entry, a priced vendor model, and an `httpx`
dependency in `pyproject.toml`.

The two checks that shell out are split into a subprocess call and a pure verdict on its
exit code, so `process_verdict` is tested the same way. `tests_pass` raises
`RecursionRefused` if called from inside `pytest`, and a test asserts that too — the gate
runs the test suite, the test suite does not run the gate.

Sensitivity is the property that matters. A gate that cannot fail proves nothing when it
passes; M8 established that for the suite gate, M11 for replay, M12 for the documentation
gate, and this is the same argument applied to the repository itself.

## What it found

Two things, on the milestone that introduced it.

`tests/test_adapters.py::test_no_adapter_module_imports_an_http_client` scans only
`adapters/*.py`, while the module docstring it substantiates says "no module **in this
package** imports one". The stronger claim was true; nothing checked it. It is checked now,
across `src/`, `scripts/`, and `tests/`, by parsing rather than by substring search.

Adding the `final-check` verb moved `cli_commands` from 12 to 13, and M12's documentation
gate failed until `docs/REPRODUCIBILITY.md` was updated. That is the M12 gate doing its job,
and it is the reason this one exists.
