Human review: M1 — Core schemas

TL;DR
Milestone 1 replaces the M0 schemas stub with the project's typed data model:
pydantic v2 models and StrEnum vocabularies for claims, artifact bundles,
evidence links, verification checks/results, run traces, and benchmark suites.
No verification logic — these are the contracts later milestones fill in. All
models forbid unknown fields; the bundle enforces unique IDs; RunTrace.to_jsonl()
is deterministic. 25 new tests (38 total). SCHEMA_VERSION 0-stub -> 1.0. Docs and
website updated to match, and docs/CLAIM_SCHEMA.md now exists.

What changed
- New: src/scientific_claim_verifier/schemas.py (full model layer, replacing the
  stub), tests/test_schemas.py (25 tests), docs/CLAIM_SCHEMA.md.
- Updated: site/claim-schema.html (status done; added baseline_value + units
  rows; link to docs/CLAIM_SCHEMA.md), site/artifact-bundles.html,
  site/reproducibility.html, site/checks.html (schema-now-typed notes),
  site/index.html (M1 status), site/milestones.html (M1 -> done), and this
  milestone's docs under docs/milestones and docs/commits.

What should be checked later
- Field surface vs. real fixtures: M2 will exercise these models against actual
  task YAML. Confirm the fields are sufficient and that extra="forbid" does not
  reject anything a legitimate task needs (add explicit fields if so, rather than
  loosening the config).
- Two fields (baseline_value, units) were added beyond docs/PLAN.md section 6's
  representative list because comparison/numeric checks need them; the site table
  and docs/CLAIM_SCHEMA.md were updated to match. Confirm this is the desired
  representation for comparison claims (from-value + to-value), vs. an alternative
  (e.g. a nested delta object).
- Table.rows alignment with Table.columns is intentionally NOT validated in the
  schema (deferred to the M5 table check). Confirm that is the right layer.
- CellValue excludes bool by design (bool is an int subclass and would be
  ambiguous in a numeric union). Confirm no fixture needs boolean cells.
- RunTrace.created_at is caller-supplied (never wall-clock) for determinism;
  confirm the pipeline wiring in later milestones populates it explicitly where a
  timestamp is wanted.

Technical risks
- Low. Data model only; no behavioral/verification code.
- pydantic v2 smart-union coercion for CellValue: int/float/str preserved through
  a JSON round-trip is covered by a test, but watch for surprising coercion if a
  future value type is added to the union.
- StrEnum requires Python 3.11+; the project targets 3.12 and pyproject floors at
  3.10 for the package metadata. The env check reports the interpreter; the
  schemas module itself needs >= 3.11. If 3.10 support is ever required, the
  enums would need the class X(str, Enum) form.

Commands to verify
- python3 -m pytest -q
- ruff check .
- python3 scripts/00_check_environment.py
- ./scripts/serve_site.sh   then load http://localhost:9002/claim-schema.html

Human feedback
<!-- Human will fill this later. -->
