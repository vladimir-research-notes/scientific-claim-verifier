# M1 — Core schemas

## Summary

Replaces the Milestone 0 `schemas.py` stub with the project's typed core data
model: the `pydantic` v2 models that every later subsystem produces and consumes.
No verification logic yet — these are the **contracts**. Extraction (M3), evidence
linking (M4), checks (M5), the sandbox (M6), and scoring (M7) all read and write
these objects; reports (M9) render them.

The vocabularies are `StrEnum`s whose values match the tables already published
on the website and now in `docs/CLAIM_SCHEMA.md`, so documentation and code
cannot drift.

## Deliverables

- **`src/scientific_claim_verifier/schemas.py`** — full typed model layer,
  replacing the stub. `SCHEMA_VERSION` bumped `"0-stub"` → `"1.0"`.
  - **Vocabularies (`StrEnum`):** `ClaimType`, `ComparisonOperator`,
    `SupportLabel`, `ReproductionStatus`, `FailureMode`, `EvidenceKind`,
    `CheckType`, `CheckStatus`.
  - **Artifact content:** `Passage`, `Table`, `Figure`, `PaperArtifact`,
    `DatasetArtifact`, `CodeArtifact` (plus the `CellValue = int | float | str |
    None` cell alias).
  - **Claims & bundles:** `EvidenceLink`, `ScientificClaim`, `ArtifactBundle`.
  - **Checks & results:** `VerificationCheck`, `VerificationResult`.
  - **Trace & suite:** `TraceEvent`, `RunTrace`, `BenchmarkSuite`.
- **`tests/test_schemas.py`** — 25 unit tests (see Validation).
- **`docs/CLAIM_SCHEMA.md`** — canonical field-by-field reference, matching the
  module and the website.
- **Website:** `claim-schema.html`, `artifact-bundles.html`, `reproducibility.html`,
  `checks.html`, `index.html`, and `milestones.html` updated (M1 status, the two
  new claim fields, a link to `docs/CLAIM_SCHEMA.md`).

## Design decisions

- **`extra="forbid"` on every model.** An unknown field is a hard error, not a
  dropped key — a typo in a future task file fails loudly. Arbitrary extension
  data has explicit `metadata` / `inputs` dict fields.
- **`StrEnum` for closed vocabularies.** Members serialize to their string value
  in JSON (e.g. `"numeric_claim"`, not `"ClaimType.NUMERIC"`) and invalid values
  are rejected at validation time. `ruff`'s `UP042` also prefers `StrEnum` over
  `class X(str, Enum)` on the 3.12 target.
- **Determinism is a schema property, not just a runtime one.** Nothing is filled
  from the wall clock or an RNG at construction. `RunTrace.created_at` is an
  optional caller-supplied ISO-8601 string; `RunTrace.to_jsonl()` sorts keys so
  the trace is byte-reproducible. This directly serves the CLAUDE.md determinism
  rule.
- **Bundle integrity enforced at construction.** A `model_validator` rejects
  duplicate artifact IDs (across papers/datasets/code), duplicate table/figure
  IDs, and duplicate passage IDs within a paper, so an `EvidenceLink` always
  resolves to exactly one target. Messages are sorted for stable output.
- **Two fields beyond the original site table.** `baseline_value` (the "from"
  value of a comparison claim) and `units` were added because comparison and
  numeric checks need them; `claim-schema.html` and `docs/CLAIM_SCHEMA.md` were
  updated in the same milestone so the docs match the code.
- **Optional-first numeric fields.** A claim whose value was not extracted is
  still valid and is *scored* `underspecified` later — the schema never rejects
  an incompletely-known claim.
- **Datasets/code reference files, they do not inline them.** `DatasetArtifact`
  carries a `path` and declared shape hints; `CodeArtifact` carries a `path` and
  `entrypoint`. Loading/hashing/execution belong to M2/M5/M6.

## Validation

Commands run (CPU-only, offline):

| Command | Result |
| --- | --- |
| `python3 -m pytest -q` | 38 passed (13 from M0 + 25 new) |
| `ruff check .` | All checks passed |
| `python3 scripts/00_check_environment.py` | exit 0 — `READY` |

The new tests pin: enum vocabularies against the website tables; JSON round-trip
equality for claims and full traces; `extra="forbid"` rejection; empty-string and
invalid-enum rejection; bundle lookups and duplicate-ID rejection (artifact /
passage / table); `CellValue` type preservation (int/float/None) through a JSON
round-trip; `EvidenceLink.score` and `VerificationResult.confidence` bounds;
`RunTrace.add_event` seq incrementing; and `to_jsonl()` determinism (identical
across calls, key-sorted, insertion-ordered, parseable).

## Status

**Complete.** Next: **M2 — Fixture tasks & validation** (small committed tasks
across the task families plus `scripts/01_validate_fixtures.py`, which will parse
task bundles against these schemas).
