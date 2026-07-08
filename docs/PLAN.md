# PLAN — scientific-claim-verifier

Build plan, architecture, and contract for a CPU-first system that verifies
scientific claims against papers, datasets, code artifacts, and reproducibility
evidence. This document is the source of truth for the milestone runner and is
read at the start of every milestone.

---

## 1. Research question

> How can we build **auditable** systems that verify scientific claims by
> connecting text evidence, data artifacts, code execution, and reproducibility
> outcomes — rather than relying on opaque summary?

A summary tells you what a paper *says*. It does not tell you whether a specific
claim is *supported* by the paper's own artifacts, nor whether the underlying
computation *reproduces*. This project treats a claim as something to be checked
through multiple evidence channels, each of which is recorded and inspectable.

## 2. Core idea

Every claim is evaluated through independent evidence channels:

1. Does the claim appear in the paper text?
2. Which exact passage supports it?
3. Is the claim tied to a table, figure, dataset, or code artifact?
4. Can the relevant computation be reproduced or approximated from artifacts?
5. If not, why not (failure mode)?
6. Is the claim supported, contradicted, partially supported, underspecified, or
   unverifiable from the given artifacts?
7. Can the system emit a trace a human can audit end to end?

The system never collapses these into one opaque verdict. The report keeps the
**extracted claim**, the **supporting text**, the **computed check**, the
**inference**, and any **unverifiable statement** visibly separate.

## 3. Scope

### In scope (fixture domains)

- Machine-learning benchmark claims (accuracy/F1 deltas, ablation tables).
- Bioinformatics *toy* analyses (e.g. GC-content, counts over synthetic FASTA/CSV).
- Statistical claims over small committed CSVs (count, mean, std, correlation).
- Simple ablation / results tables.
- Reproduction of tiny Python scripts computing a reported metric.

All fixtures are **synthetic or open**, small, and committed.

### Out of scope (permanent non-goals)

- Clinical decision-making or medical/treatment advice.
- Wet-lab protocol design or optimization.
- Dual-use biological instructions.
- Real patient data or private/real papers.
- Real credential handling or a production-grade untrusted-code sandbox.
- A universal oracle of "scientific truth." Verdicts are **relative to the
  supplied artifacts**, nothing more.

See `docs/SAFETY.md`.

## 4. Hardware & budget contract

- Primary target: CPU-only AWS `m5.2xlarge`. No GPU.
- Runs fully offline against small committed fixtures. Tests never touch the
  network.
- No paid API required anywhere in the default path.
- Optional LLM/API adapters are disabled by default. Any paid-API mode must
  provide: **dry-run**, **response cache**, **token/cost estimator**, **hard
  max-cost guard**, and **explicit opt-in**.

## 5. Architecture

```
                         ┌─────────────────────────────────────────┐
   task (YAML/JSON)  ──▶  │  artifacts/  load + hash paper/data/code │
                         └─────────────────────────────────────────┘
                                          │  ArtifactBundle
                                          ▼
   ┌───────────────┐   claims/     ┌───────────────┐   evidence/
   │  extraction   │──────────────▶│  normalization │──────────────▶ linking
   │ (rule-based / │   ScientificClaim              │   passages/tables/
   │  mock LLM)    │                                │   datasets/code_refs
   └───────────────┘                                └───────────────┘
                                          │  claim + EvidenceLinks
                                          ▼
                         ┌─────────────────────────────────────────┐
   checks/               │ statistical · table_recompute ·         │
                         │ figure_recompute · code_execution ·     │  VerificationCheck[]
                         │ consistency                              │
                         └─────────────────────────────────────────┘
                                          │        ▲
                                          │        │ trace (JSONL)
                                          ▼        │
                         ┌─────────────────────────────────────────┐
   sandbox/              │ runner (temp dir, timeout, no-net policy,│
                         │ stdout/stderr/exit capture) + trace      │
                         └─────────────────────────────────────────┘
                                          │
                                          ▼
   scoring/              support_labels · reproducibility · failure_modes
                                          │  VerificationResult
                                          ▼
   reports/              markdown (+ optional html)  ◀── RunTrace
```

Package layout (`src/scientific_claim_verifier/`):

```
__init__.py            schemas.py            cli.py            (console script: claimverifier)
artifacts/  loader.py  paper_bundle.py  dataset_bundle.py  code_bundle.py  hashing.py
claims/     extraction.py  normalization.py  linking.py
evidence/   passages.py  tables.py  figures.py  datasets.py  code_refs.py
checks/     statistical.py  table_recompute.py  figure_recompute.py  code_execution.py  consistency.py
sandbox/    runner.py  policy.py  trace.py
scoring/    support_labels.py  reproducibility.py  failure_modes.py
reports/    markdown.py  html.py
adapters/   mock_llm.py  recorded_llm.py  api_stub.py
```

Repository layout:

```
tasks/       ml_claims/ bioinformatics_claims/ statistical_claims/ table_claims/ code_reproduction/
data/fixtures/  papers/ datasets/ code/ expected/
results/     runs/ reports/ processed/ figures/     (generated; mostly gitignored)
docs/        PLAN.md METHODOLOGY.md CLAIM_SCHEMA.md ARTIFACT_FORMAT.md CHECKS.md
             SCORING.md RESULTS.md LIMITATIONS.md SAFETY.md REPRODUCIBILITY.md
             PAPER_PATH.md  milestones/ commits/ review_notes/ prompts/
scripts/     00_check_environment.py 01_validate_fixtures.py 02_extract_claims.py
             03_run_checks.py 04_generate_report.py 05_run_smoke_suite.py
             run_all_milestones_with_claude.sh  serve_site.sh
site/        static multi-page website
tests/
```

## 6. Core data model

### 6.1 ScientificClaim

```
claim_id · claim_text · normalized_claim · source_document_id · source_passage
claim_type · entities · metrics · datasets · conditions
expected_value · comparison_operator · evidence_links
```

Claim types:

```
descriptive_claim · numeric_claim · comparison_claim · table_claim
figure_claim · dataset_claim · code_reproduction_claim
unsupported_or_contextual_claim
```

### 6.2 ArtifactBundle

```
paper_text_or_snippets · tables · figures_metadata · datasets · code_files
expected_outputs · metadata
```

Component artifacts: `PaperArtifact`, `DatasetArtifact`, `CodeArtifact`, each
content-hashed for provenance.

### 6.3 VerificationResult

```
claim_id · support_label · evidence_passages · computed_checks
reproduction_status · failure_mode · confidence · limitations
trace_path · human_readable_summary
```

Support labels:

```
supported · contradicted · partially_supported · underspecified
unverifiable_from_artifacts · not_checked
```

Reproducibility statuses:

```
reproduced · approximately_reproduced · failed_environment · failed_missing_data
failed_missing_code · failed_numeric_mismatch · not_applicable · not_attempted
```

Full field definitions live in `docs/CLAIM_SCHEMA.md`, `docs/ARTIFACT_FORMAT.md`,
`docs/CHECKS.md`, and `docs/SCORING.md` (created in their milestones).

## 7. Task families

1. **Numeric table claim** — "Method A improves accuracy from 72% to 78%"; check
   against a table fixture. Scored on field extraction, comparison, support label.
2. **Dataset statistic claim** — "120 samples, mean 3.4"; recompute count/mean/std
   from a CSV within tolerance. Scored on recomputation and tolerance handling.
3. **Figure/table reproduction** — regenerate a summary table or figure from data
   and compare key values; save the generated artifact and a diff summary.
4. **Code reproduction** — execute a tiny script in the controlled sandbox with a
   timeout; compare output to expected; classify failure mode.
5. **Evidence passage linking** — link a claim to exact source passages; rank
   candidates; penalize unsupported claims; record provenance.
6. **Contradiction / underspecification** — detect overstated or condition-omitting
   claims and label `partially_supported` / `underspecified`. Explanation quality is
   judged by deterministic expected fields, **not** LLM grading.

## 8. Agent / LLM policy

Version 1 is non-LLM or mock-LLM by default:

- `RuleBasedClaimExtractor` — transparent baseline for numeric/comparison claims.
- `RecordedLLMAdapter` — replays committed fixture outputs (deterministic).
- `MockLLMAdapter` — deterministic test adapter.
- `ApiAdapterStub` — interface only, disabled by default, cost-guarded.

Real paid API is optional future work only.

## 9. Milestones

The runner (`scripts/run_all_milestones_with_claude.sh`) executes exactly one of
these per `claude -p` invocation and commits after each.

- **M0 — Scaffold & project contract.** `pyproject.toml`, package skeleton
  (`__init__`, `cli`, `schemas` stub), `scripts/00_check_environment.py`, first
  tests, README. (Orchestration layer — this PLAN, `CLAUDE.md`, prompts, runner,
  website skeleton — is bootstrapped before M0.)
- **M1 — Core schemas.** Typed `pydantic` models: `ScientificClaim`,
  `ArtifactBundle`, `PaperArtifact`, `DatasetArtifact`, `CodeArtifact`,
  `EvidenceLink`, `VerificationCheck`, `VerificationResult`, `ReproductionStatus`,
  `SupportLabel`, `FailureMode`, `RunTrace`, `BenchmarkSuite`. Unit tests.
- **M2 — Fixture tasks & validation.** Small committed tasks (numeric table,
  dataset statistic, evidence passage, code reproduction, underspecified) + a
  fixture validation script (`01_validate_fixtures.py`).
- **M3 — Rule-based claim extraction.** Transparent extractors for numeric values,
  comparison phrases, metric names, dataset/table references, passage IDs. Tests
  against expected extracted claims. No overclaimed NLP.
- **M4 — Evidence linker.** Exact passage lookup, keyword-overlap baseline, table
  and dataset ID matching, provenance records. Tests.
- **M5 — Verification checks.** Deterministic checks: table value, dataset
  statistic recomputation, numeric tolerance, comparison, evidence presence, and a
  code-execution check for tiny scripts.
- **M6 — Reproducibility sandbox.** Controlled execution: temp dir, timeout,
  stdout/stderr/exit capture, no-network policy, trace record. Tests with harmless
  fixture scripts.
- **M7 — Scoring & failure modes.** Support-label assignment, reproducibility
  status, failure-mode classification, aggregate summary, per-claim results.
- **M8 — Smoke suite.** 8–15 tasks run fully offline. Save run traces, results,
  summary CSV/JSON, and reports.
- **M9 — Reports.** Markdown (+ optional HTML) reports: input/extracted claim,
  evidence, checks, support label, reproducibility status, failure mode,
  limitations, trace link.
- **M10 — Optional adapters.** `RecordedLLMAdapter`, `MockLLMAdapter`,
  `ApiAdapterStub` with cost guard. Disabled by default; no paid API required.
- **M11 — Integration contracts.** Compatible import/export formats for the
  code-agent runtime, BioScientist OS, BioAgentBench, LLM regression/observability,
  and agent-control-bench. No dependency on those repos.
- **M12 — Portfolio report.** README and docs to portfolio quality: problem,
  architecture, worked example, smoke-suite results, reproduction commands,
  limitations, future research path.
- **M13 — Final cleanup.** Run tests, lint, fixture validation, smoke suite,
  report generation, `git status`. Verify no secrets/private papers/large
  data/caches/paid-API outputs and a clean tree. Commit.

Each milestone additionally: updates the website, writes its milestone/commit/
review notes, and commits locally (never pushes).

## 10. CLI surface (target)

```bash
claimverifier check-env
claimverifier validate-fixtures tasks/
claimverifier extract-claims --task tasks/table_claims/basic_accuracy_claim.yaml --out results/runs/
claimverifier verify        --task tasks/table_claims/basic_accuracy_claim.yaml --out results/runs/
claimverifier run-suite     --suite tasks/smoke_suite.yaml --out results/runs/
claimverifier report        --run results/runs/<run_id> --out results/reports/<run_id>.md
```

## 11. Quality gates (definition of done)

The repo is complete only when **all** hold:

- Tests pass (`python3 -m pytest -q`), CPU-only and offline.
- Fixtures validate (`claimverifier validate-fixtures` / `scripts/01_validate_fixtures.py`).
- The smoke suite runs fully offline with **≥ 8** claim-verification tasks
  end to end.
- Reports are generated from traces.
- At least one dataset-statistic claim is recomputed.
- At least one table claim is checked.
- At least one code-reproduction task is executed safely in the sandbox.
- Docs explain methodology, limitations, safety, and reproduction.
- No paid API is needed anywhere in the default path.
- Working tree is clean; nothing is pushed.

## 12. Commit discipline

Commit after each coherent milestone. Do not push. Keep commits meaningful and
scoped (no giant formatting-only commits). Keep public docs professional and
research-oriented — precise and technical, never a learning diary. Label any
heuristic or approximate method clearly as such.
