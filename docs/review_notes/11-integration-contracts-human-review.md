Human review: Milestone 11 — Integration contracts

TL;DR
Five versioned, self-describing export formats under `integrations/`, one per consumer role
named in `docs/PLAN.md` §9, reachable via `claimverifier export`. `episodes` is the import
direction: `claimverifier replay` re-runs each recorded episode and reports `reproduced`,
`drifted`, `inputs_changed`, or `missing_task`. All eleven committed fixtures replay to the
verdict they recorded, with byte-identical traces (`--strict` passes). 86 new tests; 756
total; ruff clean; smoke gate unchanged (nothing on the default path changed).

**No external schema was consulted.** None of the five named systems (code-agent runtime,
BioScientist OS, BioAgentBench, LLM regression/observability, agent-control-bench) was read,
imported, or run. The word "compatible" from the plan is not used anywhere in the code or
docs as a claim about those projects. These are proposed contracts shaped for a consumer
*role*; the non-dependency is checked by a test that parses every module's AST, not asserted
in prose. Please push on this framing if you think it still overreaches.

What changed
- Added `src/scientific_claim_verifier/integrations/` (10 modules): `envelope.py`,
  `records.py`, `run.py`, `runnable_tasks.py`, `evidence_records.py`, `benchmark.py`,
  `metrics.py`, `episodes.py`, `export.py`, `__init__.py`.
- Added `claimverifier export` and `claimverifier replay` (edits to `cli.py`) and
  `scripts/07_export_integrations.py`.
- Added `tests/test_integrations.py`, `docs/INTEGRATIONS.md`, the `docs/RESULTS.md` M11
  section, `site/integrations.html`, and website/nav/README updates.
- `.gitignore` now excludes `results/exports/`.
- **No existing module's behaviour changed.** The only edits to pre-existing source are the
  two `cli.py` subcommand registrations and their dispatch.

What should be checked later
- **The controls gap (the one real assumption).** A schema-1.3 trace records what the
  pipeline *computed*, not how an operator *invoked* it, so it carries none of `execute`,
  `use_declared_source`, `abs_tol`, `rel_tol`. `export --format episodes` recovers `execute`
  from a suite `summary.json`'s `suite.scripts_executed` and **refuses** if the operator's
  `--no-execute` disagrees; the other three are taken from the operator's flags and default
  to the pipeline's defaults. A wrongly declared control does not silently lie — replay
  reports `drifted` and names the field — but the honest fix is a `scoring.controls` event
  and `SCHEMA_VERSION` 1.4. That is a trace change and was deliberately left to whichever
  milestone needs it. **This is the first thing to review.**
- Whether `benchmark`, `metrics`, and `episodes` requiring a `run-suite` run (rather than a
  multi-task `verify --out`) is the right trade. It buys a fixed label key space for
  `metrics` and a real `gate` block for `benchmark`, at the cost of refusing a run some users
  might reasonably produce. `evidence-records` needs only traces and works on an archived run.
- Whether `evidence-records` should carry `VerificationCheck.inputs` after all. It is
  currently omitted on purpose (free-form keys per check type; holds captured stdout for
  `code_execution`), and a test pins that the fixture stdout `accuracy=0.80` appears in no
  record. A consumer that wants it must read the trace, which `provenance` names.
- Whether `--strict` should be the default for `replay`. Today verdict equality gates and the
  trace digest is reported but not gated, by analogy with M8's wrong-verdict/conservative-miss
  asymmetry. All eleven fixtures currently pass `--strict` anyway, so flipping the default
  would cost nothing today and would start failing the moment anyone rewords a `because`
  string.
- `metrics.compare()` is a library function with tests and a documented snippet, but is not
  reachable from the CLI. Deliberate (a third verb for a diff felt like scope creep); worth
  revisiting if a regression harness actually wants it.
- The `episodes` replay re-runs the pipeline over all eleven fixtures, which is the most
  expensive thing in the test suite (~0.3 s here, three fixture scripts executed). It is one
  module-scoped fixture; if CI time matters, it could be marked.

Technical risks
- Low for the default path: no new runtime dependency, no network, no paid API, no schema
  change, and no pipeline stage imports `integrations`. `pytest`, `ruff`, fixture validation,
  and the smoke gate are all unchanged.
- The load-bearing safety property is a test, not a convention:
  `test_integration_modules_import_only_stdlib_pydantic_and_this_project` walks every module's
  imports, and `test_no_integration_module_imports_the_repo_it_is_shaped_for` blocks the five
  names specifically. If a future change adds a dependency, both fail loudly.
- `check_agreement` refuses a run directory whose `summary.json` and traces disagree. This is
  strict by design (such a directory holds artifacts from two runs), but it means a user who
  hand-edits `summary.json` gets an error rather than a document. The message says why.
- The trace-contract guarantees in `runnable-tasks` are *claims about a real artifact*, and a
  test re-derives each one from a trace the repo produced (one object per line, sorted keys,
  contiguous `seq`, kinds within the declared set). If a later milestone changes the trace
  writer, that test fails rather than the contract quietly becoming false.

Commands to verify
- `python3 -m pytest tests/test_integrations.py -q`
- `claimverifier export --list`
- `claimverifier export --format benchmark --schema`
- `claimverifier run-suite --out results/runs/`
- `claimverifier export --format episodes --run results/runs/smoke_suite --out ep.json`
- `claimverifier replay --episodes ep.json --strict`   # 11/11 reproduced, exit 0
- `claimverifier export --format episodes --run results/runs/smoke_suite --no-execute`  # exit 1

Human feedback
<!-- Human will fill this later. -->
