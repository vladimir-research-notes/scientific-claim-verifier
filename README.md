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

> **Build status:** Milestone 0 complete — the runnable package scaffold
> (`scientific_claim_verifier`, the `claimverifier` CLI, and an offline
> environment self-check) is in place on top of the bootstrap layer. The
> verification subsystems are built milestone by milestone — see below. This
> README is upgraded to portfolio quality in Milestone 12.

## Quickstart

```bash
# Optional: editable install (the only runtime dependency is pydantic)
pip install -e .

# Offline environment self-check (interpreter + library availability)
python3 scripts/00_check_environment.py     # or: claimverifier check-env

# CPU-only, offline tests (import the package straight from src/, no install needed)
python3 -m pytest -q
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
  -> sandbox     temp dir · timeout · no-network policy · stdout/stderr/exit capture
  -> scoring     support label · reproducibility status · failure mode
  -> report      Markdown (+ optional HTML)  <-  JSONL trace
```

## CLI

Live today:

```bash
claimverifier check-env
claimverifier version
claimverifier validate-fixtures tasks/
claimverifier extract-claims --task tasks/table_claims/accuracy_improvement.yaml --out results/runs/
claimverifier link-evidence  --task tasks/table_claims/accuracy_improvement.yaml --no-declared-source
```

`link-evidence` reports the ranked passage candidates, the emitted evidence links
with their locators (`row=A,col=accuracy`, `column=value`, `stdout`), and the rule
behind each. `--no-declared-source` ignores the task's authored
`claim.source_passage` and links passages blind — the setting under which
retrieval is actually worth measuring. See
[`docs/EVIDENCE_LINKING.md`](docs/EVIDENCE_LINKING.md).

Target (each lands with its subsystem — see the milestones):

```bash
claimverifier verify        --task tasks/table_claims/accuracy_improvement.yaml --out results/runs/
claimverifier run-suite     --suite tasks/smoke_suite.yaml --out results/runs/
claimverifier report        --run results/runs/<run_id> --out results/reports/<run_id>.md
```

An unimplemented command fails loudly rather than pretending to work.

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
Example report, Results, Milestones, Limitations, Safety, Roadmap.

## Repository layout

```
src/scientific_claim_verifier/   package: artifacts, claims, evidence, checks,
                                 sandbox, scoring, reports, adapters, cli, schemas
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
