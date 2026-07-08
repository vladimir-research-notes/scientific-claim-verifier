# ARTIFACT_FORMAT — the task file format

Canonical reference for the on-disk **task** format introduced in **Milestone 2**
and the fixture-validation contract. Tasks live under `tasks/` as YAML
(`.yaml`/`.yml`) or JSON; their referenced fixture files live under
`data/fixtures/`. The loader and validator are in
[`src/scientific_claim_verifier/artifacts/`](../src/scientific_claim_verifier/artifacts/)
(`hashing.py`, `loader.py`, `validation.py`).

A task is the unit the pipeline runs on: a **claim**, the **bundle of artifacts**
it is checked against, and a **gold** record of what the answer should be. The
gold record is used to *score* later milestones — it is never fed to them as
input.

## Input / gold separation

The most important design rule: **the task's `claim` block is the claim as
authored — nothing more.** It holds the id, the text, the type, and where the
claim comes from. It deliberately carries **no** extracted numeric fields.

The values a correct extractor should recover (`expected_value`,
`baseline_value`, `metrics`, `comparison_operator`, …) live in `expected.claim`
as the *gold* target. So loading a task supplies the pipeline's input and,
separately, the yardstick — loading never leaks the answer to the extraction
milestone (M3).

## Top-level fields

| Field | Type | Meaning |
| --- | --- | --- |
| `task_id` | `str` (non-empty) | Stable task identifier; should match the filename stem. |
| `family` | `str` (non-empty) | Human-facing grouping label (e.g. `numeric_table`). |
| `title` | `str` (non-empty) | One-line description. |
| `description` | `str \| None` | Longer prose description. |
| `claim` | `ClaimInput` | The claim as authored (input). |
| `artifacts` | `ArtifactBundle` | The evidence bundle (Milestone 1 schema). |
| `expected` | `TaskExpectation` | The gold outcome + gold extraction (for scoring). |
| `notes` | `str \| None` | Author notes. |

All models are strict (`extra="forbid"`): an unknown key is a hard error.

### `claim` — `ClaimInput`

| Field | Type | Meaning |
| --- | --- | --- |
| `claim_id` | `str` (non-empty) | Claim identifier. |
| `claim_text` | `str` (non-empty) | The claim as written. |
| `claim_type` | `ClaimType` | Selects the primary check. |
| `source_document_id` | `str \| None` | Paper artifact the claim is drawn from. |
| `source_passage` | `str \| None` | Passage ID that asserts the claim. |

### `artifacts` — `ArtifactBundle`

Exactly the Milestone 1 [`ArtifactBundle`](CLAIM_SCHEMA.md#artifactbundle):
`papers`, `tables`, `figures`, `datasets`, `code_files`, `expected_outputs`,
`metadata`. Its unique-ID integrity check runs on every fixture. Datasets and
code reference files by repo-relative `path`; papers, tables, and figures are
inlined. `content_hash` fields are left empty in the file and **populated by the
loader** (see below).

### `expected` — `TaskExpectation`

| Field | Type | Meaning |
| --- | --- | --- |
| `support_label` | `SupportLabel` | Gold support label. |
| `reproduction_status` | `ReproductionStatus` | Gold reproduction status (default `not_applicable`). |
| `failure_mode` | `FailureMode` | Gold failure mode (default `none`). |
| `claim` | `GoldClaim` | Gold extraction target (all fields optional). |
| `evidence` | `list[EvidenceLink]` | Evidence links a correct linker should surface. |

`GoldClaim` mirrors the extractable fields of `ScientificClaim`:
`normalized_claim`, `entities`, `metrics`, `datasets`, `conditions`,
`expected_value`, `baseline_value`, `comparison_operator`, `units`.

## Content hashing

`artifacts/hashing.py` produces deterministic `"sha256:<hexdigest>"` hashes.
`load_task` populates `content_hash` on every artifact:

- **datasets / code** — over the referenced file's bytes (`hash_file`);
- **papers** — over a canonical JSON of their passages (`hash_text`), since a
  paper's content is inlined in the task file.

The hash is recorded so a report can state which bytes a verdict was computed
against, and a re-run against changed artifacts is detectable. Hashing is
byte-stable: the same artifact always yields the same string.

## Validation

`claimverifier validate-fixtures [tasks_dir]` and `scripts/01_validate_fixtures.py`
validate every task under `tasks/` (default), accumulating *all* problems per
task. Two severities:

**Errors** (the task is invalid; run exits non-zero):

- the file does not parse, or is not a top-level mapping;
- it fails the schema (unknown field, bad enum, empty required string,
  duplicate artifact/table/figure/passage ID);
- a dataset/code `path` is absolute, escapes the repository, or does not exist;
- a dataset's declared `columns`/`n_rows` disagree with its CSV;
- a gold `evidence` link, `claim.source_passage`, or `claim.source_document_id`
  resolves to nothing in the bundle.

**Warnings** (the task loads; flagged but not failed):

- a fixture file lives outside `data/fixtures/`;
- the filename stem does not match `task_id`;
- a reproducible claim (code-reproduction / dataset) ships with no expected
  value to score against.

Fixture path safety: paths must be relative and resolve inside the repository.
Absolute paths and `..` escapes are rejected, so a task can only reference small
committed fixtures.

## Committed fixtures (Milestone 2)

Six tasks across the families in `docs/PLAN.md` §7, all synthetic and small:

| Task | Family | Claim type | Gold label |
| --- | --- | --- | --- |
| `table_claims/accuracy_improvement` | numeric_table | `comparison_claim` | `supported` |
| `statistical_claims/dataset_mean` | dataset_statistic | `dataset_claim` | `supported` (reproduced) |
| `ml_claims/synthetic_data_passage` | evidence_passage | `descriptive_claim` | `supported` |
| `ml_claims/underspecified_split` | underspecified | `numeric_claim` | `underspecified` |
| `code_reproduction/recompute_accuracy` | code_reproduction | `code_reproduction_claim` | `supported` (reproduced) |
| `bioinformatics_claims/gc_content` | bioinformatics | `code_reproduction_claim` | `supported` (reproduced) |

The dataset fixture (`data/fixtures/datasets/measurements.csv`, 12 rows, mean
3.4) and the two code fixtures (`compute_accuracy.py` → `accuracy=0.80`,
`gc_content.py` → `gc_content=0.50`) are trusted, stdlib-only, offline, and
deterministic. Execution of the code fixtures is deferred to the reproducibility
sandbox milestone; Milestone 2 only references and hashes them.

## Status

**Milestone 2 complete.** The loader, hasher, and validator are covered by
`tests/test_fixtures.py` and `tests/test_hashing.py`. Extraction (M3), evidence
linking (M4), checks (M5), the sandbox (M6), and scoring (M7) consume these
loaded tasks in their own milestones.
