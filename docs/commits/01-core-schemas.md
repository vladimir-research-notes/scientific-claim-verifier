# Commit note — M1 Core schemas

## Commit message

```
M1: typed core schemas (pydantic models + vocabularies)

Replace the Milestone 0 schemas stub with the project's typed data model:
- vocabularies (StrEnum): ClaimType, ComparisonOperator, SupportLabel,
  ReproductionStatus, FailureMode, EvidenceKind, CheckType, CheckStatus
- artifact content: Passage, Table, Figure, PaperArtifact, DatasetArtifact,
  CodeArtifact (+ CellValue cell alias)
- claims/bundles: EvidenceLink, ScientificClaim, ArtifactBundle
  (unique-ID integrity validator; typed lookups)
- checks/results: VerificationCheck, VerificationResult
- trace/suite: TraceEvent, RunTrace (deterministic to_jsonl), BenchmarkSuite
All models forbid unknown fields; SCHEMA_VERSION 0-stub -> 1.0.
Add tests/test_schemas.py (25 tests) and docs/CLAIM_SCHEMA.md; update website
(claim-schema, artifact-bundles, reproducibility, checks, index, milestones);
add milestone/commit/review notes.
```

## What this commit adds

- The typed contract layer every later subsystem produces and consumes, with
  closed `StrEnum` vocabularies matching the website tables and
  `docs/CLAIM_SCHEMA.md`.
- Strictness (`extra="forbid"`) and a bundle-integrity validator (unique
  artifact/table/figure/passage IDs) so evidence links resolve unambiguously.
- Determinism guarantees: no wall-clock/RNG at construction; `RunTrace.to_jsonl()`
  is key-sorted and byte-stable.
- 25 unit tests and the canonical `docs/CLAIM_SCHEMA.md`.

## Deliberately excluded (per the operating principles)

- Extraction, linking, checks, sandbox, scoring, reports — later milestones. This
  milestone is data model only; nothing here verifies a claim.
- Loading/hashing of dataset and code files — `DatasetArtifact`/`CodeArtifact`
  reference files by `path`; loaders and `content_hash` land in M2.
- numpy/pandas/scipy as hard dependencies — still added when first used (M5).

## Verification performed at commit time

- `python3 -m pytest -q` → 38 passed (13 from M0 + 25 new).
- `ruff check .` → all checks passed.
- `python3 scripts/00_check_environment.py` → exit 0 (`READY`).
- Static site served locally on port 9002; pages fetched via Python's `urllib`
  (no `curl`/`wget`, per the permission policy).
- `git status` clean after commit.
