# Claude Code instructions for this repository

`scientific-claim-verifier` is a serious, CPU-first research/engineering system
for **verifying scientific claims against papers, datasets, code artifacts, and
reproducibility evidence**. It is built milestone by milestone by an autonomous
Claude Code agent driven by `scripts/run_all_milestones_with_claude.sh`.

Read this file and `docs/PLAN.md` at the start of every milestone.

## Public framing

Given a claim and a bundle of scientific artifacts (paper snippets, tables,
figures metadata, datasets, code), the system extracts the claim, links it to
supporting evidence, runs deterministic checks, attempts lightweight
reproduction where possible, classifies failure modes, and emits an **auditable
report** with a JSONL trace.

This is **not** a paper summarizer and **not** a learning demo. It is a small
but real reproducibility tool and benchmark platform. Its purpose is to improve
**auditability** — to cleanly separate the extracted claim, the supporting text,
the computed check, the inference, and the parts that are unverifiable — not to
act as an authority on scientific truth.

## Operating principles

- Build one milestone at a time, in order (see `docs/PLAN.md`).
- Commit locally after each coherent milestone. **Do not push.**
- Do not wait for human review; create a review placeholder and continue.
- Keep default tests **CPU-only, offline, and free**. No internet in tests.
- No paid API calls in the default path. LLM adapters are optional, disabled by
  default, and any paid-API mode must have: dry-run, response cache, token/cost
  estimator, a hard max-cost guard, and explicit opt-in.
- Prefer deterministic, transparent, rule-based components first. Do not
  overclaim NLP or "AI" sophistication — heuristics are labelled as heuristics.
- Everything determinism-critical must avoid wall-clock/random nondeterminism in
  its core output (seed anything stochastic; sort for stable ordering).

## What must never be committed

Secrets, real credentials, `.env`, `*.key`/`*.pem`, `.claude/settings.local.json`,
virtualenvs, caches, `node_modules`, model weights, large datasets, large logs,
paid-API outputs, or private/real papers. Fixtures are **synthetic or open** and
small. See `.gitignore`.

## Safety and scientific scope

In scope: machine-learning benchmark claims, bioinformatics *toy* analyses,
statistical claims over small CSVs, simple ablation tables, reproduction of tiny
Python scripts/notebooks.

Out of scope, always: clinical decision-making, medical/treatment advice,
wet-lab protocol design or optimization, dual-use biological instructions, real
patient data, and real credential handling. See `docs/SAFETY.md`.

The report must always keep these separate and clearly labelled:
extracted claim · supporting text · computed check · inference · unverifiable
statement.

## Sandbox honesty

The code-execution layer runs **tiny, trusted fixture scripts** in a temp dir
with a timeout and captured stdout/stderr/exit-code. It is controlled fixture
execution, **not** an untrusted-code or exploit sandbox. Document this limitation
plainly wherever execution is described; never claim production-grade isolation.

## Quality bar

Every substantive claim in the repo must be backed by at least one of: a test, a
reproducible example task, a trace artifact, a result table, a documented
limitation, or an explicit non-goal. The repo should read clearly to a strong
senior engineer in 5 minutes and survive 30 minutes of technical questioning.

## Required behavior after each milestone

1. Run that milestone's validation commands (at least `python3 -m pytest -q`;
   plus fixture validation / smoke suite once those scripts exist).
2. Update the multi-page website under `site/` (statuses, new sections).
3. Update `docs/RESULTS.md` or the relevant docs if results changed.
4. Create/update `docs/milestones/NN-<slug>.md` (what/why/validation/status).
5. Create/update `docs/commits/NN-<slug>.md` (commit note).
6. Create/update `docs/review_notes/NN-<slug>-human-review.md` (placeholder;
   do not claim review happened).
7. Commit locally with a meaningful message. Do not push.
8. Print: milestone title, commit hash, tests run, website pages updated,
   review placeholder path, and the next milestone.

Stop only if continuing would risk secrets, paid API spend, data loss, or repo
corruption.

## Human review file structure

```
Human review: <milestone title>
TL;DR
What changed
What should be checked later
Technical risks
Commands to verify
Human feedback
<!-- Human will fill this later. -->
```

## Stack and layout

Python 3.12, `src/` layout (package `scientific_claim_verifier`, console script
`claimverifier`), `pytest`, `ruff`, `pydantic`, `typer` or `argparse`, `pandas`,
`numpy`, `scipy`/`statsmodels` only if needed, `matplotlib` for simple figures.
Traces are JSONL; task definitions are YAML/JSON; SQLite is optional for the
artifact index. Reports are Markdown (+ optional HTML). See `docs/PLAN.md` for
the full directory map.

## Website requirements

Multi-page static site under `site/` (plain HTML/CSS, no build step). Required
pages: `index.html` (Overview), `claim-schema.html`, `artifact-bundles.html`,
`checks.html`, `reproducibility.html`, `example-report.html`, `results.html`,
`limitations.html`, `safety.html`, `roadmap.html`, and `milestones.html`
(an explanation of every milestone and its status). Update the site every
milestone. Serve locally with `scripts/serve_site.sh` (port 9002).
