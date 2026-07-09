# CLAIM_SCHEMA — the core data model

Canonical, field-by-field reference for the typed models introduced in
**Milestone 1**. The models live in
[`src/scientific_claim_verifier/schemas.py`](../src/scientific_claim_verifier/schemas.py)
and are the contract every later subsystem produces and consumes. This document
is written to match that module; the vocabularies are also mirrored on the
website (`site/claim-schema.html`, `site/reproducibility.html`,
`site/checks.html`) so docs and code cannot drift.

The models are [`pydantic`](https://docs.pydantic.dev) v2 `BaseModel`s. They share
one config choice: **`extra="forbid"`** — an unknown field is a hard validation
error, not a silently dropped key, so a typo in a task file fails loudly.

`SCHEMA_VERSION = "1.2"` is stamped into every `RunTrace`. Version `1.1`
(Milestone 5) added `CheckStatus.INCONCLUSIVE`; version `1.2` (Milestone 7) added
`FailureMode.EVIDENCE_UNDECIDABLE`, the failure mode that status had no way to map
onto. Both are additive changes, so every `1.0` document remains valid.

## Design principles

- **Auditability.** The five things a report must keep visibly separate map onto
  distinct fields: the **extracted claim** (`ScientificClaim`), the **supporting
  text** (`EvidenceLink` → `Passage`), the **computed check**
  (`VerificationCheck`), the **inference** (`VerificationResult.support_label` /
  `reproduction_status`), and the **unverifiable statement**
  (`SupportLabel.unverifiable_from_artifacts`, `VerificationResult.limitations`).
- **Determinism.** No field is filled from the wall clock or an RNG at
  construction. `RunTrace.created_at` is an optional caller-supplied ISO-8601
  string, and `RunTrace.to_jsonl()` sorts keys, so a trace is byte-reproducible.
- **Closed vocabularies.** Claim types, comparison operators, support labels,
  reproduction statuses, failure modes, evidence kinds, check types, and check
  statuses are `StrEnum`s. Invalid values are rejected at validation time.
- **Optional over strict.** A claim whose numeric value could not be extracted is
  still valid — it is *scored* `underspecified`, never rejected. The schema
  models what the pipeline knows, including "not yet known".

## Vocabularies (enums)

### `ClaimType`

| Value | Example | Primary check |
| --- | --- | --- |
| `descriptive_claim` | "The method is trained on synthetic data." | evidence presence |
| `numeric_claim` | "Accuracy is 78%." | numeric tolerance |
| `comparison_claim` | "A improves accuracy from 72% to 78%." | comparison |
| `table_claim` | "Row B, column F1 is 0.81." | table recompute / lookup |
| `figure_claim` | "The bar for group C is highest." | figure/table recompute |
| `dataset_claim` | "The dataset has 120 samples, mean 3.4." | dataset statistic recompute |
| `code_reproduction_claim` | "Running eval.py yields 0.78." | code execution |
| `unsupported_or_contextual_claim` | "This is the best approach in the literature." | flagged unverifiable / contextual |

### `ComparisonOperator`

`=`, `>`, `<`, `>=`, `<=`, `~` (approximate). Interpreted by numeric/comparison
checks in Milestone 5.

### `SupportLabel` — is the claim backed by the artifacts?

`supported` · `contradicted` · `partially_supported` · `underspecified` ·
`unverifiable_from_artifacts` · `not_checked`. Verdicts are **relative to the
supplied bundle**, not a universal truth.

### `ReproductionStatus` — did the computation reproduce?

`reproduced` · `approximately_reproduced` · `failed_environment` ·
`failed_missing_data` · `failed_missing_code` · `failed_numeric_mismatch` ·
`not_applicable` · `not_attempted`.

### `FailureMode` — if not clean, why?

`none` (sentinel: no failure) · `missing_evidence_link` ·
`passage_does_not_assert` · `evidence_undecidable` · `table_cell_mismatch` ·
`statistic_mismatch` · `numeric_out_of_tolerance` · `missing_data` · `missing_code` ·
`execution_error` · `execution_timeout` · `underspecified` · `other`.

`evidence_undecidable` and `passage_does_not_assert` are deliberately distinct. The
first says *the checker could not tell*; the second says *the passage does not say it*.
Reporting the second when only the first is known would turn the checker's own
ignorance into a fact about the paper. Assignment rules: `docs/SCORING.md`.

### `EvidenceKind`

`passage` · `table` · `figure` · `dataset` · `code`.

### `CheckType`

`table_value` · `dataset_statistic` · `numeric_tolerance` · `comparison` ·
`evidence_presence` · `figure_recompute` · `code_execution`.

### `CheckStatus`

`pass` · `fail` · `inconclusive` · `error` · `skipped`.

The four non-`pass` values are deliberately distinct, because they mean different
things to scoring (M7):

| Value | Meaning |
| --- | --- |
| `fail` | The check ran and the artifacts **disagree** with the claim. |
| `inconclusive` | The check ran and its **method cannot decide** — e.g. a bag-of-words evidence check faced with a paraphrase. Maps onto `unverifiable_from_artifacts`, never `contradicted`. |
| `error` | The check itself could not run (missing file, dangling link, non-numeric cell, script crash). |
| `skipped` | The check did not apply (nothing was located to look at). |

Collapsing `inconclusive` into `fail` would manufacture contradictions out of the
checker's own ignorance. See `docs/CHECKS.md`.

## Models

### `ScientificClaim`

A claim as a typed, checkable object rather than free text.

| Field | Type | Meaning |
| --- | --- | --- |
| `claim_id` | `str` (non-empty) | Stable identifier within a task. |
| `claim_text` | `str` (non-empty) | The claim as written. |
| `normalized_claim` | `str \| None` | Canonicalized form for matching (filled by extraction, M3). |
| `source_document_id` | `str \| None` | Which paper artifact the claim comes from. |
| `source_passage` | `str \| None` | Passage ID/span asserting the claim. |
| `claim_type` | `ClaimType` | Selects the primary check. |
| `entities` | `list[str]` | Methods, models, or objects referenced. |
| `metrics` | `list[str]` | Named metrics (accuracy, F1, mean, count, …). |
| `datasets` | `list[str]` | Referenced dataset IDs. |
| `conditions` | `list[str]` | Stated conditions/qualifiers (split, seed, subset). |
| `expected_value` | `float \| None` | The asserted numeric value. |
| `baseline_value` | `float \| None` | The "from" value of a comparison ("from 72 to 78"). |
| `comparison_operator` | `ComparisonOperator \| None` | How to compare computed vs expected. |
| `units` | `str \| None` | Units of the value (e.g. `%`), when stated. |
| `evidence_links` | `list[EvidenceLink]` | Links to passages, tables, datasets, or code. |

### `EvidenceLink`

A provenance link from a claim (or a check) to a specific artifact position.

| Field | Type | Meaning |
| --- | --- | --- |
| `kind` | `EvidenceKind` | Which artifact type is pointed at. |
| `target_id` | `str` (non-empty) | Passage / table / figure / dataset / code ID. |
| `locator` | `str \| None` | Exact position (e.g. `row=B,col=F1`, a column name). |
| `quote` | `str \| None` | The exact supporting text. |
| `score` | `float \| None` in `[0, 1]` | Relevance score from the linker (M4). |
| `notes` | `str \| None` | Free-text provenance notes. |

### Artifact content

`ArtifactBundle` is the evidence a claim is checked against. Its content types:

- **`Passage`** — `passage_id`, `text`, optional `section`. An ID-addressable
  span of paper text.
- **`Table`** — `table_id`, optional `caption`, `columns: list[str]`,
  `rows: list[list[CellValue]]` (row-major; `CellValue` is `int | float | str |
  None`, `None` = missing cell), optional `notes`. Row/column alignment is
  validated where a check consumes the table (M5), not here.
- **`Figure`** — `figure_id`, optional `caption`/`kind`, `series: dict[str,
  list[float]]` (the data behind the figure, **not** pixels), optional `notes`.
- **`PaperArtifact`** — `artifact_id`, optional `title`, `passages:
  list[Passage]`, optional `content_hash`/`source`/`license`, `metadata`.
  Helper: `paper.passage(passage_id)`.
- **`DatasetArtifact`** — `artifact_id`, optional `path` (to a committed CSV,
  loaded lazily by later milestones), `description`, declared `columns`/`n_rows`
  (shape hints cross-checked at check time), optional `content_hash`/`license`,
  `metadata`. Rows are **not** inlined.
- **`CodeArtifact`** — `artifact_id`, optional `path`, `entrypoint` (e.g.
  `python eval.py`), `language` (default `python`), optional `timeout_seconds`
  (`> 0`), optional `content_hash`, `metadata`. Executed in the controlled
  fixture sandbox (M6) — **not** an untrusted-code sandbox.

`content_hash` fields are optional here and populated by the hashing helper in
Milestone 2.

### `ArtifactBundle`

| Field | Type | Meaning |
| --- | --- | --- |
| `bundle_id` | `str` (non-empty) | Stable bundle identifier. |
| `task_id` | `str \| None` | The task this bundle belongs to. |
| `papers` | `list[PaperArtifact]` | Paper snippets. |
| `tables` | `list[Table]` | Structured tables. |
| `figures` | `list[Figure]` | Figure metadata + data series. |
| `datasets` | `list[DatasetArtifact]` | Small datasets. |
| `code_files` | `list[CodeArtifact]` | Tiny scripts. |
| `expected_outputs` | `dict[str, Any]` | Ground-truth values for scoring reproduction. |
| `metadata` | `dict[str, Any]` | Task ID, provenance, licence, notes. |

**Integrity invariant (enforced at construction).** Artifact IDs are unique
across `papers`/`datasets`/`code_files`; `table_id`s and `figure_id`s are unique;
and `passage_id`s are unique within each paper. A duplicate raises
`ValidationError` with a sorted, named message (e.g. `duplicate artifact_id: dup`)
so an `EvidenceLink` always resolves unambiguously.

**Lookups.** `bundle.paper(id)`, `.dataset(id)`, `.code(id)`, `.table(id)`,
`.figure(id)` each return the matching artifact or `None`.

### `VerificationCheck`

The record of one deterministic check — everything needed to audit and regenerate
the verdict. A check produces *evidence*; it does not decide the support label on
its own (that is scoring, M7).

| Field | Type | Meaning |
| --- | --- | --- |
| `check_id` | `str` (non-empty) | Identifier within a run. |
| `check_type` | `CheckType` | Which check ran. |
| `claim_id` | `str` (non-empty) | The claim under check. |
| `status` | `CheckStatus` | Outcome. `.ok` is a convenience for `status == pass`. |
| `computed_value` | `CellValue` | What the check computed. |
| `expected_value` | `CellValue` | What the claim asserted. |
| `tolerance` | `float \| None` (`>= 0`) | Applied tolerance, when numeric. |
| `difference` | `float \| None` | Signed `computed − expected`, where meaningful. |
| `inputs` | `dict[str, Any]` | Inputs fed in (targets, artifact hashes, …). |
| `evidence` | `list[EvidenceLink]` | Evidence the check consumed. |
| `notes` | `str \| None` | Free-text explanation. |

### `VerificationResult`

The per-claim inference the pipeline draws from the checks.

| Field | Type | Meaning |
| --- | --- | --- |
| `claim_id` | `str` (non-empty) | The claim. |
| `support_label` | `SupportLabel` | Is the claim backed? |
| `reproduction_status` | `ReproductionStatus` | Did the computation reproduce? Default `not_applicable`. |
| `failure_mode` | `FailureMode` | If not clean, why? Default `none`. |
| `evidence_passages` | `list[EvidenceLink]` | Supporting passages. |
| `computed_checks` | `list[VerificationCheck]` | The checks that were run. |
| `confidence` | `float \| None` in `[0, 1]` | Optional confidence. |
| `limitations` | `list[str]` | What could **not** be settled, and why. |
| `trace_path` | `str \| None` | Path to the JSONL trace. |
| `human_readable_summary` | `str \| None` | Prose summary for the report. |

### `RunTrace` and `TraceEvent`

The auditable record of a single verification run.

- **`TraceEvent`** — `seq: int (>= 0)`, `kind: str` (non-empty), optional
  `message`, `data: dict[str, Any]`. One JSONL line.
- **`RunTrace`** — `run_id`, `schema_version` (defaults to `SCHEMA_VERSION`),
  optional `task_id`/`bundle_id`/`claim`/`result`, `checks: list[VerificationCheck]`,
  `events: list[TraceEvent]`, optional `created_at` (caller-supplied ISO-8601).
  - `add_event(kind, message=None, **data)` appends an event with an
    auto-incremented `seq` and returns it.
  - `to_jsonl()` renders the event stream as JSONL — one JSON object per line,
    **keys sorted** for byte-stability, enums rendered as their string values.

### `BenchmarkSuite`

`suite_id`, optional `name`/`description`/`version`, `task_ids: list[str]`,
`metadata`. `.size` returns the number of task references. Drives the smoke suite
(M8).

## Status

**Milestone 1 complete.** The models, their vocabularies, and their invariants
are covered by `tests/test_schemas.py`. Every model is now populated by a real
subsystem: extraction (M3), linking (M4), checks (M5), sandbox (M6), and scoring
(M7), which fills `VerificationResult` and writes the `RunTrace`. `BenchmarkSuite`
awaits the smoke suite (M8).
