# scientific-claim-verifier

A CPU-first system for **verifying scientific claims** against papers, datasets, code
artifacts, and reproducibility evidence — and producing an **auditable report** backed by
a JSONL trace.

> Given a claim and a bundle of scientific artifacts, extract the claim, link it to
> supporting evidence, run deterministic checks, attempt lightweight reproduction,
> classify failure modes, and report — keeping the extracted claim, the supporting text,
> the computed check, the inference, and the unverifiable parts visibly separate.

Eleven tasks run end to end on one CPU in ~1.5 s, offline and free, with **zero wrong
verdicts**. All eleven replay to the verdict they recorded, byte-identical traces
included. 878 tests, no network, no paid API.

This is **not** a paper summarizer, **not** a learning demo, and **not** an oracle of
scientific truth. Verdicts are relative to the supplied artifacts. It is a small but real
reproducibility tool and benchmark platform.

---

## The problem

A summary tells you what a paper *says*. It does not tell you whether a specific claim is
*supported* by the paper's own artifacts, nor whether the underlying computation
*reproduces*.

So this system does not summarize a claim. It **checks** it, through independent evidence
channels, and refuses to collapse them into one opaque verdict. Every report keeps five
things separate and labelled:

| Channel | What it is |
| --- | --- |
| **Extracted claim** | the typed fields a rule read out of a sentence |
| **Supporting text** | the passages and artifacts retrieved for it |
| **Computed check** | a fact about one artifact, computed deterministically |
| **Inference** | the support label, and the named rule that produced it |
| **Unverifiable** | what these artifacts could **not** settle, and why |

That separation is not a presentation choice. It is enforced by the module graph: the
linker cannot decide support, the checks cannot assign a label, and the report imports no
pipeline stage at all.

## Quickstart

```bash
# Optional: editable install (runtime deps are pydantic and pyyaml — that is the list)
pip install -e .

# CPU-only, offline tests (import the package straight from src/, no install needed)
python3 -m pytest -q                                        # 878 passed

# The whole pipeline over every committed task: 11 claims, offline, ~1.5 s
python3 scripts/05_run_smoke_suite.py --out results/runs/   # or: claimverifier run-suite

# An auditable report per claim, rendered from the traces that run just wrote
python3 scripts/04_generate_report.py --run results/runs/smoke_suite --out results/reports/

# Export that run as replayable episodes, then replay them and gate on drift
python3 scripts/07_export_integrations.py --format episodes --run results/runs/smoke_suite --out ep.json
claimverifier replay --episodes ep.json --strict            # 11/11 reproduced
```

## The worked example

The fixture the project exists for. A paper's abstract asserts a number its own results
table denies.

**Step 1 — the checks compute facts, and assign no verdict.**

```
$ claimverifier run-checks --task tasks/table_claims/contradicted_f1.yaml

Claim           : c_contradicted_f1 (numeric_claim)
Text            : Method B reaches an F1 score of 91.0 on MNLI.

Supporting text (retrieved evidence; whether it *asserts* the claim is checked below):
  "Method B reaches an F1 score of 91.0 on MNLI."

Computed checks (each reads an artifact; none of them decides the verdict):
  [pass] evidence_presence  p_claim         the passage states the claim verbatim
  [fail] table_value        t_mnli[col=f1]  claimed 91 is absent from column 'f1'
                                            (nearest 86 at row B; |difference| = 5 > tolerance 0.05)

Summary         : 2 check(s) — 1 pass, 1 fail

Inference       : NOT produced by this stage.
```

Both checks are correct. A system that collapsed them into one verdict would destroy the
only interesting fact about the claim: **the paper contradicts its own table.** The
tolerance of `0.05` was not chosen either — the claim wrote `91.0`, to one decimal place,
so anything rounding to 91.0 would have matched.

**Step 2 — `verify` is the one stage allowed to draw an inference, and it names its rule.**

```
support_label       : contradicted
  rule              : artifacts_refute [c_contradicted_f1.table_value.1]
  because           : the table does not hold the claimed value
reproduction_status : not_applicable
failure_mode        : table_cell_mismatch
confidence          : 1.00 (share of checks that reached a verdict; not a probability)
```

The report still shows the passage that asserts the claim, in a different section. The
whole trace is nine JSONL events, and the verdict is the last one — a trace read top to
bottom is the argument in the order it was made.

### The claim the system refuses to decide

```
$ claimverifier verify --task tasks/ml_claims/synthetic_data_passage.yaml

Claim           : The model is trained only on synthetic data.

Supporting text (retrieved evidence):
  "All experiments use synthetic data generated by our pipeline; no real corpora
   were used at any stage of training."

Computed checks (what each artifact says about the claim):
  [inconclusive] evidence_presence  p_data  -> undecided

Inference (drawn from the checks above; each rule names the checks it read):
  support_label       : unverifiable_from_artifacts
    rule              : nothing_decided [c_synthetic_data.evidence_presence.1]
    because           : no check reached a verdict: a lexical check cannot decide
                        whether the passage asserts the claim (40% token coverage,
                        missing ['model', 'only', 'trained'])
  failure_mode        : evidence_undecidable
  confidence          : 0.00

Task gold       : supported [MISS] / not_applicable [ok ] / none [MISS]
```

The passage *does* support the claim — a human reads the paraphrase instantly. A
bag-of-words rule cannot, so it says `inconclusive`, and scoring maps that to
`unverifiable_from_artifacts`, **never `contradicted`**. The report marks its own miss.
Reporting `fail` there would have manufactured a contradiction out of a checker's own
ignorance.

This is the honest cost of a transparent method, and it is the number to watch: a stronger
evidence checker is measured by whether it can move this claim to `pass` **without** moving
`contradicted_f1`'s passage check off `pass`.

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

Each stage is **structurally incapable of doing the next stage's job**:

| Stage | May conclude | May **not** conclude |
| --- | --- | --- |
| `evidence` | this passage is *about* the claim | whether it *supports* the claim |
| `checks` | this artifact holds (or does not hold) this value | what that means for the claim |
| `sandbox` | this script exited N and printed this | whether N is the right answer |
| `scoring` | the support label, naming its rule and checks | anything the checks did not record |
| `report` | what the trace says | anything not in the trace |

So a check's **status** is a fact about the check, while its **signal** is what the check
says about the *claim* — and one status means more than one thing. An `evidence_presence`
check that fails because the passage never *mentions* the claim signals `undecided`, not
`refutes`: **silence is not refutation.** See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## Results

Eleven tasks, end to end, offline, in ~1.5 s. The full tables — per-field extraction, strict
link recovery, every check, every rule — are in [`docs/RESULTS.md`](docs/RESULTS.md).

| | |
| --- | --- |
| Tasks | 11 (`docs/PLAN.md` §11 asks for ≥ 8) |
| Checks run | 26 — 20 pass, 3 fail, 1 inconclusive, 1 error, 1 skipped |
| Scripts executed | 3, in the controlled sandbox |
| Gold agreement | support **10/11** · reproduction **11/11** · failure mode **10/11** |
| Evidence links | strict **21/21** recovered, **0** spurious |
| **Wrong verdicts** | **0** |
| Conservative misses | 1 (`synthetic_data_passage`), declared in the suite file |
| Episode replay | 11/11 reproduced, byte-identical traces (`--strict`) |
| **Gate** | **PASS** (exit 0) |

### The suite is a gate, not a scoreboard

`run-suite` exits non-zero when the pipeline **regresses**, and the definition of regression
is deliberately asymmetric:

- Any **wrong verdict** — a committal support label the task's gold outcome disagrees with —
  fails the run. `tasks/smoke_suite.yaml` has no key that could declare one acceptable, so a
  suite file can never bless one.
- A **conservative miss** — declining to decide where the gold outcome commits — fails the run
  *only if the set of them changed*. The suite file names the standing misses; a new one is a
  regression, and a fixed one must be removed rather than left to rot.

> A change that raises label accuracy by turning a claim the pipeline honestly declined to
> decide into one it decides *wrongly* has made the tool worse — and a single accuracy number
> would have called it an improvement.

The gate is tested by *injecting* each failure in turn — a wrong verdict, a new miss, a stale
declared miss — and asserting it fails. A gate that never fails proves nothing when it passes.
A suite full of `contradicted` claims exits **0**: finding a contradiction is the tool working.

**These fixtures are a regression harness, not a benchmark.** They are hand-authored and
synthetic, and their gold outcomes were written alongside the rules that score them. 10/11 does
not mean scientific claim verification is 91% solved. See [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) §4.

## Reproducing every number

Every number in this repository is reproducible offline on one CPU, with the command shown
beside it in [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md) — which also carries a table
of headline numbers that **a test re-derives from a live suite run**, so a document that drifts
from the code fails the build.

```bash
python3 -m pytest -q                        # 878 tests, CPU-only, offline
python3 -m ruff check .                     # lint
python3 scripts/01_validate_fixtures.py     # 11 tasks + 1 suite valid
python3 scripts/05_run_smoke_suite.py       # the gate; exit 0
```

## CLI

All twelve commands are live; the CLI contract in `docs/PLAN.md` §10 is complete.

| Command | What it does |
| --- | --- |
| `check-env` · `version` | offline interpreter + library self-check |
| `validate-fixtures` | validate every task and the suite under `tasks/` |
| `extract-claims` | typed fields, the rules that fired, and a gold comparison |
| `link-evidence` | ranked passage candidates, emitted links, and the rule behind each |
| `run-checks` | compute checks against the located artifacts — **no verdict** |
| `run-sandbox` | execute a task's fixture scripts under a recorded policy |
| `verify` | the one stage that draws an inference, naming its rule |
| `run-suite` | all 11 tasks end to end; the regression gate |
| `report` | render a claim as Markdown/HTML **from its trace alone** |
| `export` | one of five versioned, self-describing formats |
| `replay` | re-run recorded episodes and gate on drift |

A few that repay explanation:

**`link-evidence --no-declared-source`** ignores the task's authored `claim.source_passage` and
links passages blind — the setting under which retrieval is actually worth measuring. See
[`docs/EVIDENCE_LINKING.md`](docs/EVIDENCE_LINKING.md).

**`run-sandbox`** runs fixture scripts in a fresh temp directory, environment scrubbed to an
allowlist, stdin closed, POSIX resource limits applied, a timeout that kills the whole process
group, and an in-process guard that denies and **records** `socket` calls — then writes a JSONL
trace whose first event is the policy itself. Those are *reproducibility* controls, not security
controls: it runs trusted, committed fixture scripts and is **not a sandbox for untrusted code**.
See [`docs/SANDBOX.md`](docs/SANDBOX.md).

**`report`** — a report is a function of its trace. The renderer imports no pipeline stage, opens
no artifact, re-runs no check, and never reads `result.json`; it reconstructs the scored claim
from the JSONL bytes, re-validating every object against the schema on the way in, so a corrupt
trace raises rather than rendering into a plausible-looking report. A run archived months ago —
whose papers and CSVs are long gone — still reports. A test scores every committed fixture, writes
its trace, reads it back, and asserts the reconstruction *equals* the original, because a trace
that cannot be turned back into the verdict it recorded is not an audit record but a log. See
[`docs/REPORTS.md`](docs/REPORTS.md).

**`export`** writes a run in one of five versioned formats — shaped for a code-agent runtime, an
evidence store, a benchmark harness, an observability sink, and a replay bench. **No external
schema was consulted**, so nothing here claims compatibility with any named project: each format
is a proposed contract confined to one module, and a test parses every module in the package to
prove it imports nothing but the standard library, `pydantic`, and this project.

**`replay`** is the one verb that re-runs anything, and it is where a contract stops being a shape
and becomes a claim that can be false. An episode pins the task file, each artifact by content
hash, the controls, the recorded verdict, and the SHA-256 of the trace. Replay reports
`reproduced`, `drifted`, `inputs_changed`, or `missing_task` — and only `drifted` is a statement
about the *pipeline*, because an edited CSV must never read as a code regression. Each of the four
statuses is *injected* in the tests. See [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md).

`verify` exits `0` on a `contradicted` claim: finding a contradiction is the tool working.

## Constraints

- CPU-only, offline, and free by default. Target: AWS `m5.2xlarge`. No GPU.
- No paid API in the default path. Optional LLM adapters are disabled by default and, if enabled,
  require dry-run, a response cache, a token/cost estimator, a hard max-cost guard, and explicit
  opt-in. The paid path is inert **by construction**: a live call requires four independent acts,
  and the repo ships neither a price table nor an HTTP transport. See [`docs/ADAPTERS.md`](docs/ADAPTERS.md).
- Fixtures are small, synthetic or open, and committed. Tests never touch the network.
- Safety scope is strict — no clinical/medical advice, no wet-lab protocols, no dual-use biology,
  no real patient data. See [`docs/SAFETY.md`](docs/SAFETY.md).

## Limitations

The full list is [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md). The five that matter most:

1. **Verdicts are relative to the artifacts.** `supported` means the bundle backs the claim, not
   that the claim is true in the world.
2. **The methods are labelled heuristics.** Extraction is regexes plus closed lexicons; linking is
   bag-of-words with no model of morphology, synonymy, or negation; `evidence_presence` decides
   assertion lexically and returns `inconclusive` on a paraphrase rather than guessing.
3. **The sandbox is not a security boundary.** No namespace, no seccomp filter, no user separation;
   the network guard is Python-level and cannot see `ctypes`, a raw syscall, or a non-Python
   subprocess. It catches accidental network use by trusted code. It does not contain adversaries.
4. **The fixtures are a regression harness.** Eleven hand-authored synthetic tasks whose gold
   outcomes were written alongside the rules that score them. Not a held-out set.
5. **`confidence` is not a probability.** It is the share of a claim's checks that reached a
   verdict — decidedness — and is calibrated against nothing.

Also stated plainly: `figure_recompute` is a named `CheckType` with **no implementation and no
fixture**; four vocabulary values are unreachable end to end and pinned by unit tests instead; and
a schema-1.3 trace records what the pipeline computed, not how an operator invoked it.

## Future research path

[`docs/PAPER_PATH.md`](docs/PAPER_PATH.md) sets out what would have to be true before any of these
numbers were a claim about the world rather than a claim about this repository. In short: this is a
**systems and auditability contribution**, not an NLP result. The instrument is finished enough to
be pointed at something; the paper is the corpus, the baselines, and the ablation — not the
instrument.

The transferable argument is about evaluation design:

> For verification systems, an evaluation that cannot distinguish *asserting something false* from
> *declining to assert* will systematically select for models that guess.

The honest counterweight, stated in the same document: a metric that only punishes wrong verdicts is
gameable by silence, so `wrong_verdicts` and `conservative_misses` must always be reported together,
and never summed.

## Building the system (milestone runner)

The functional system is built one milestone at a time by an autonomous Claude Code agent. Each
milestone is a single `claude -p` run that reads [`CLAUDE.md`](CLAUDE.md) and
[`docs/PLAN.md`](docs/PLAN.md), implements exactly one milestone, updates docs and the website, and
commits locally (never pushes). Requires an authenticated `claude` CLI, `python3`, and `git`.

```bash
./scripts/run_all_milestones_with_claude.sh          # all milestones 0..13
./scripts/run_all_milestones_with_claude.sh 3 5      # a specific range
WEEKLY_BUDGET_USD=50 ./scripts/run_all_milestones_with_claude.sh   # optional cost guard
MAX_TURNS=60 ./scripts/run_all_milestones_with_claude.sh           # optional runaway guard
```

Between milestones the runner enforces guards: a new commit must exist, the tree must be clean,
`pytest` must pass, and fixtures must validate. It stops on any failure so you can inspect.

### Permissions (no prompts, never dangerous)

Autonomous runs need to proceed without interactive approvals, but without ever enabling a dangerous
"bypass everything" mode. Two mechanisms combine:

- **`.claude/settings.json`** (committed, auditable) sets `defaultMode: acceptEdits` and an explicit
  command **allowlist** (`python3`, `pytest`, `ruff`, `git status/add/commit/...`, and common
  read-only shell tools). Its **deny list** blocks `git push`/`git remote`, `sudo`, `curl`/`wget` and
  other network tools, `rm`, `bash -c`/`eval`, and reads of secrets (`.env`, `~/.ssh`, `~/.aws`,
  `*.pem`/`*.key`). Bypass-permissions mode is disabled outright.
- **`CLAUDE_EXTRA_ARGS`** is appended to every `claude -p` call; it defaults to
  `--permission-mode acceptEdits` and never includes `--dangerously-skip-permissions`.

Net effect: edits and the allowlisted commands run without prompts; anything outside the allowlist
(or on the deny list) is refused, not silently run. Because `curl`/`wget` are denied, the milestone
agent verifies the local site with Python's standard-library HTTP client. Personal, machine-local
overrides go in `.claude/settings.local.json` (gitignored).

## Project website

```bash
./scripts/serve_site.sh   # serves site/ at http://localhost:9002/index.html
```

Pages: Overview, Claim schema, Artifact bundles, Checks, Reproducibility, Example report, Results,
Milestones, Integrations, Limitations, Safety, Roadmap.

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

## Documentation

| Document | What it covers |
| --- | --- |
| [`docs/PLAN.md`](docs/PLAN.md) | the build plan, architecture, and milestone contract |
| [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) | the design commitments, and what each stage may not conclude |
| [`docs/CLAIM_SCHEMA.md`](docs/CLAIM_SCHEMA.md) · [`docs/ARTIFACT_FORMAT.md`](docs/ARTIFACT_FORMAT.md) | the typed data model |
| [`docs/EXTRACTION.md`](docs/EXTRACTION.md) · [`docs/EVIDENCE_LINKING.md`](docs/EVIDENCE_LINKING.md) | every extraction and linking rule, and its limits |
| [`docs/CHECKS.md`](docs/CHECKS.md) · [`docs/SANDBOX.md`](docs/SANDBOX.md) | the deterministic checks; what execution enforces |
| [`docs/SCORING.md`](docs/SCORING.md) · [`docs/REPORTS.md`](docs/REPORTS.md) | the rule table; the trace → report contract |
| [`docs/ADAPTERS.md`](docs/ADAPTERS.md) · [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md) | the disabled LLM adapters; the five export contracts |
| [`docs/RESULTS.md`](docs/RESULTS.md) | every measured number, and how to read it |
| [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md) | how to re-derive all of them offline |
| [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) · [`docs/SAFETY.md`](docs/SAFETY.md) | what it cannot do; the permanent scope contract |
| [`docs/PAPER_PATH.md`](docs/PAPER_PATH.md) | what would have to be true to publish any of it |

## License

MIT — see [`LICENSE`](LICENSE).
