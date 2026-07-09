# scientific-claim-verifier

A CPU-first system for **verifying scientific claims** against papers, datasets,
code artifacts, and reproducibility evidence — and producing an **auditable
report** backed by a JSONL trace.

> Given a claim and a bundle of scientific artifacts, extract the claim, link it
> to supporting evidence, run deterministic checks, attempt lightweight
> reproduction, classify failure modes, and report — keeping the extracted claim,
> the supporting text, the computed check, the inference, and the unverifiable
> parts visibly separate.

This is **not** a paper summarizer, **not** a learning demo, and **not** an
oracle of scientific truth. Verdicts are relative to the supplied artifacts. It
is a small but real reproducibility tool and benchmark platform. See
[`docs/PLAN.md`](docs/PLAN.md) for the full plan and
[`site/`](site/index.html) for the project website.

> **Build status:** Milestones 0–11 complete. The typed schema, the task format and its
> validator, rule-based claim extraction, the evidence linker, the deterministic
> verification checks, the reproducibility sandbox, scoring, the offline smoke suite, the
> trace-derived reports, the optional (disabled) LLM adapters, and the integration export
> contracts are in place: a claim can be extracted, linked to the exact cell/column/script
> that bears on it, checked against those artifacts, its script executed under a recorded
> policy, and the whole thing scored into a support label, a reproduction status, and a
> failure mode — with a JSONL trace at every step, an auditable Markdown/HTML report
> rendered back out of that trace, and five versioned exports rendered out of the same
> artifacts. **Eleven tasks run end to end on a CPU in ~1.5 s with zero wrong verdicts**,
> all eleven replay to the verdict they recorded, and all twelve CLI commands are live.
> This README is upgraded to portfolio quality in Milestone 12.

## Quickstart

```bash
# Optional: editable install (the only runtime dependency is pydantic)
pip install -e .

# Offline environment self-check (interpreter + library availability)
python3 scripts/00_check_environment.py     # or: claimverifier check-env

# CPU-only, offline tests (import the package straight from src/, no install needed)
python3 -m pytest -q

# The whole pipeline over every committed task: 11 claims, offline, ~1.5 s
python3 scripts/05_run_smoke_suite.py --out results/runs/   # or: claimverifier run-suite

# An auditable report per claim, rendered from the traces that run just wrote
python3 scripts/04_generate_report.py --run results/runs/smoke_suite --out results/reports/

# Export that run as replayable episodes, then replay them and gate on drift
python3 scripts/07_export_integrations.py --format episodes --run results/runs/smoke_suite --out ep.json
claimverifier replay --episodes ep.json
```

## Why not just summarize?

A summary tells you what a paper *says*. It does not tell you whether a specific
claim is *supported* by the paper's own artifacts, nor whether the underlying
computation *reproduces*. This project checks a claim through independent
evidence channels — text, tables, datasets, and code execution — and records
each one.

## Constraints

- CPU-only, offline, and free by default. Target: AWS `m5.2xlarge`. No GPU.
- No paid API in the default path. Optional LLM adapters are disabled by default
  and, if enabled, require dry-run, a response cache, a token/cost estimator, a
  hard max-cost guard, and explicit opt-in.
- Fixtures are small, synthetic or open, and committed. Tests never touch the
  network.
- Safety scope is strict — no clinical/medical advice, no wet-lab protocols, no
  dual-use biology, no real patient data. See [`docs/SAFETY.md`](docs/SAFETY.md)
  (and the [Safety page](site/safety.html)).

## Architecture

```
task (YAML/JSON)
  -> artifacts   load + content-hash paper / dataset / code
  -> claims      extract (rule-based / mock LLM) -> normalize
  -> evidence    link passages / tables / datasets / code refs
  -> checks      statistical · table recompute · figure recompute · code execution · consistency
  -> sandbox     temp dir · scrubbed env · timeout · rlimits · network guard · JSONL trace
  -> scoring     support label · reproducibility status · failure mode
  -> report      Markdown (+ optional HTML)  <-  JSONL trace
  -> export      runnable-tasks · evidence-records · benchmark · metrics · episodes
                                              <-  JSONL trace (+ replay)
```

## CLI

Live today:

```bash
claimverifier check-env
claimverifier version
claimverifier validate-fixtures tasks/
claimverifier extract-claims --task tasks/table_claims/accuracy_improvement.yaml --out results/runs/
claimverifier link-evidence  --task tasks/table_claims/accuracy_improvement.yaml --no-declared-source
claimverifier run-checks     --task tasks/table_claims/contradicted_f1.yaml
claimverifier run-sandbox    --task tasks/code_reproduction/recompute_accuracy.yaml --out results/runs/
claimverifier verify         --task tasks/ml_claims/synthetic_data_passage.yaml --out results/runs/
claimverifier run-suite      --suite tasks/smoke_suite.yaml --out results/runs/
claimverifier export        --format benchmark --run results/runs/smoke_suite
claimverifier replay        --episodes ep.json
```

`link-evidence` reports the ranked passage candidates, the emitted evidence links
with their locators (`row=A,col=accuracy`, `column=value`, `stdout`), and the rule
behind each. `--no-declared-source` ignores the task's authored
`claim.source_passage` and links passages blind — the setting under which
retrieval is actually worth measuring. See
[`docs/EVIDENCE_LINKING.md`](docs/EVIDENCE_LINKING.md).

`run-checks` reads each located artifact and computes: does the passage *assert*
the claim, is the value in that table cell, does the statistic recompute from the
CSV, does the script print what the claim says. It prints supporting text and
computed checks as separate blocks and **assigns no verdict** — the support label
is inferred from the checks by scoring. On `contradicted_f1` the passage check
passes and the table check fails, which is the point. See
[`docs/CHECKS.md`](docs/CHECKS.md).

`run-sandbox` executes a task's fixture scripts under a recorded policy — fresh temp
directory, environment scrubbed to an allowlist, closed stdin, POSIX resource limits,
a timeout that kills the whole process group, and an in-process guard that denies and
**records** `socket` calls — then writes a JSONL trace whose first event is the policy
itself. Those are reproducibility controls, not security controls: it runs trusted,
committed fixture scripts and is **not a sandbox for untrusted code**. See
[`docs/SANDBOX.md`](docs/SANDBOX.md).

`verify` is the one stage allowed to draw an inference. It reduces each check to what
it says about the *claim* — a check's `status` is a fact about the check, and one
status means more than one thing — then applies five ordered rules and **records which
rule fired and which checks it read**, into the report and a JSONL trace. Repeat
`--task` to score several and get an aggregate summary. It exits `0` on a
`contradicted` claim: finding a contradiction is the tool working. See
[`docs/SCORING.md`](docs/SCORING.md).

Over the eleven committed fixtures it recovers 10/11 support labels and 11/11
reproduction statuses — but the number to watch is **0 wrong verdicts**. Its one miss
(`synthetic_data_passage`) is a *refusal to decide*: the passage supports the claim in
a paraphrase, the lexical evidence check honestly returns `inconclusive`, and scoring
reports `unverifiable_from_artifacts` rather than guessing. See
[`docs/RESULTS.md`](docs/RESULTS.md).

`run-suite` runs every committed task end to end and writes a JSONL trace and a result
JSON per task plus `summary.csv`, `summary.json`, and `summary.txt`. **It is a gate, not
a scoreboard**, and the gate is asymmetric: any *wrong verdict* fails the run, while a
*conservative miss* — declining to decide where the gold outcome commits — fails only if
the set of them changed. The suite file names the standing misses and has no key for
wrong verdicts, so it cannot bless one. A change that raises label accuracy by turning a
claim the pipeline honestly declined to decide into one it decides *wrongly* has made the
tool worse, and a single accuracy number would have called it an improvement.

`report` renders each claim as Markdown (or standalone HTML) with the five audit channels
in numbered sections, plus a link to the JSONL trace it came from:

```bash
claimverifier report        --run results/runs/smoke_suite --out results/reports/
claimverifier report        --run results/runs/smoke_suite/contradicted_f1.trace.jsonl
```

**A report is a function of its trace.** The renderer imports no pipeline stage, opens no
artifact, re-runs no check, and never reads `result.json`; it reconstructs the scored
claim from the JSONL bytes, re-validating every object against the schema on the way in,
so a corrupt trace raises rather than rendering into a plausible-looking report. A run
archived months ago — whose papers and CSVs are long gone — still reports. A test scores
every committed fixture, writes its trace, reads it back, and asserts the reconstruction
*equals* the original, because a trace that cannot be turned back into the verdict it
recorded is not an audit record but a log. See [`docs/REPORTS.md`](docs/REPORTS.md).

`export` writes a run in one of five versioned, self-describing formats — shaped for a
code-agent runtime, an evidence store, a benchmark harness, an observability sink, and a
replay bench. **No external schema was consulted**, so nothing here claims compatibility
with any named project: each format is a proposed contract confined to one module, and a
test parses every module in the package to prove it imports nothing but the standard
library, `pydantic`, and this project. Like a report, an export is a function of committed
artifacts — sorted-key JSON, no wall clock, no absolute paths, byte-identical across two
exports and across two run directories.

`replay` is the one verb that re-runs anything, and it is where a contract stops being a
shape and becomes a claim that can be false. An `episodes` document pins the task file, each
artifact by content hash, the controls, the recorded verdict, and the SHA-256 of the trace.
Replay reports `reproduced`, `drifted`, `inputs_changed`, or `missing_task` — and only
`drifted` is a statement about the *pipeline*, because an edited CSV must never read as a
code regression. All eleven fixtures reproduce, byte-identical traces included (`--strict`).
Each of the four statuses is *injected* in the tests, because a gate that never fails proves
nothing when it passes. See [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md).

`run-checks` is deliberately not `verify`: it computes checks and stops, while `verify`
draws the inference the checks are forbidden to draw.

## Building the system (milestone runner)

The functional system is built one milestone at a time by an autonomous Claude
Code agent. Each milestone is a single `claude -p` run that reads
[`CLAUDE.md`](CLAUDE.md) and [`docs/PLAN.md`](docs/PLAN.md), implements exactly
one milestone, updates docs and the website, and commits locally (never pushes).

Requires an authenticated `claude` CLI, `python3`, and `git`.

```bash
# Run all milestones 0..13
./scripts/run_all_milestones_with_claude.sh

# Run a specific range (e.g. milestones 3 to 5)
./scripts/run_all_milestones_with_claude.sh 3 5

# Optional cost guard (stops between milestones at 80% of budget by default)
WEEKLY_BUDGET_USD=50 ./scripts/run_all_milestones_with_claude.sh

# Optional runaway guard: cap agent turns per milestone
MAX_TURNS=60 ./scripts/run_all_milestones_with_claude.sh
```

Between milestones the runner enforces guards: a new commit must exist, the tree
must be clean, `pytest` must pass, and (once present) fixtures must validate. It
stops on any failure so you can inspect.

### Permissions (no prompts, never dangerous)

Autonomous milestone runs need to proceed without interactive approvals, but
without ever enabling a dangerous "bypass everything" mode. Two mechanisms
combine:

- **`.claude/settings.json`** (committed, auditable) sets
  `defaultMode: acceptEdits` and an explicit command **allowlist** (`python3`,
  `pytest`, `ruff`, `git status/add/commit/...`, and common read-only shell
  tools). Its **deny list** blocks `git push`/`git remote`, `sudo`, `curl`/`wget`
  and other network tools, `rm`, `bash -c`/`eval`, and reads of secrets
  (`.env`, `~/.ssh`, `~/.aws`, `*.pem`/`*.key`). Bypass-permissions mode is
  disabled outright.
- **`CLAUDE_EXTRA_ARGS`** is appended to every `claude -p` call; it defaults to
  `--permission-mode acceptEdits`. Override with `CLAUDE_EXTRA_ARGS=""` to drop
  it, or set your own flags. It never includes `--dangerously-skip-permissions`.

Net effect: edits and the allowlisted commands run without prompts; anything
outside the allowlist (or on the deny list) is refused, not silently run. Because
`curl`/`wget` are denied, the milestone agent verifies the local site with
Python's standard-library HTTP client rather than `curl`. Personal, machine-local
overrides go in `.claude/settings.local.json` (gitignored).

## Project website

```bash
./scripts/serve_site.sh   # serves site/ at http://localhost:9002/index.html
```

Pages: Overview, Claim schema, Artifact bundles, Checks, Reproducibility,
Example report, Results, Milestones, Integrations, Limitations, Safety, Roadmap.

## Repository layout

```
src/scientific_claim_verifier/   package: artifacts, claims, evidence, checks,
                                 sandbox, scoring, reports, adapters, integrations,
                                 cli, schemas
tasks/                           verification tasks by family (YAML/JSON)
data/fixtures/                   small synthetic/open papers, datasets, code, expected
results/                         generated runs/reports/figures (mostly gitignored)
docs/                            PLAN + methodology/schema/checks/scoring/safety/...
scripts/                         pipeline scripts + milestone runner + serve-site
site/                            static multi-page website
tests/                           CPU-only offline tests
```

## License

MIT — see [`LICENSE`](LICENSE).
