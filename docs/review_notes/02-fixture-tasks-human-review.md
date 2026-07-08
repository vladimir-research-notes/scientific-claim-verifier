Human review: M2 — Fixture tasks & validation

TL;DR
Milestone 2 adds the on-disk task format and the code to load and validate it: a
content hasher, a task loader (task schema built on the M1 models, with strict
input/gold separation), and a directory-level fixture validator wired to both
`claimverifier validate-fixtures` and `scripts/01_validate_fixtures.py`. Six
small synthetic tasks and their fixtures are committed. No verification logic —
this milestone only loads and validates. 28 new tests (66 total). pyyaml is now
a dependency and `yaml` is required by the env check.

What changed
- New package: src/scientific_claim_verifier/artifacts/ (hashing.py, loader.py,
  validation.py, __init__.py).
- CLI: `validate-fixtures` verb added to cli.py.
- Script: scripts/01_validate_fixtures.py.
- Tasks: tasks/{table_claims,statistical_claims,ml_claims,code_reproduction,
  bioinformatics_claims}/*.yaml (six tasks).
- Fixtures: data/fixtures/datasets/measurements.csv,
  data/fixtures/code/{compute_accuracy.py,gc_content.py}.
- Tests: tests/test_hashing.py, tests/test_fixtures.py.
- Docs: docs/ARTIFACT_FORMAT.md (new), docs/milestones + docs/commits notes,
  data/README.md updated.
- Deps/env: pyyaml>=6 added to pyproject.toml; yaml moved to REQUIRED_LIBS in
  envcheck.py.
- Website: site/index.html, site/milestones.html, site/artifact-bundles.html.

What should be checked later
- Input/gold separation: the task `claim` block carries no numeric fields; gold
  extraction targets live in `expected.claim`. Confirm this is the representation
  M3's extractor should be scored against (vs. e.g. a single merged claim object
  with a mask of which fields are "given" vs "to-extract").
- The `family` label is free text (human-facing) and distinct from
  `claim.claim_type`. Confirm we don't want `family` constrained to an enum.
- Paper content hashing is over a canonical JSON of passages (id/section/text).
  Confirm that is the desired provenance basis for inlined papers (vs. hashing
  the raw task-file bytes, which would change whenever unrelated fields change).
- Fixture-path policy: absolute/`..`-escaping paths are errors; out-of-`data/
  fixtures` paths are warnings, not errors. Confirm warning (not error) is the
  right severity for out-of-tree-but-in-repo fixtures.
- Empty/nonexistent tasks dir currently validates as VALID (all() of no results
  is True) with a "nothing to validate" note. Confirm that is acceptable for the
  guard, or whether a missing directory should be an error.
- The two code fixtures are executed by nothing yet; the tasks declare expected
  stdout/values. Confirm the declared `expected_outputs` shape
  (`stdout_contains` + a named metric) is what the M6 sandbox / M5 checks will
  consume.

Technical risks
- Low. Loading/validation only; no verification, no code execution.
- The loader mutates the parsed bundle in place to set content hashes; a test
  guards that the caller's input dict is not mutated. Watch if load_task is ever
  called on a shared, already-constructed bundle object.
- CSV shape check uses the stdlib csv module and treats row 1 as header; it
  assumes a header row. All committed dataset fixtures have one. Datasets without
  a header would misreport n_rows.
- pyyaml is now a hard dependency and yaml is required by the env check; the
  default path uses yaml.safe_load only (no arbitrary object construction).

Commands to verify
- python3 -m pytest -q
- ruff check .
- python3 scripts/01_validate_fixtures.py
- claimverifier validate-fixtures            (after `pip install -e .`)
- python3 scripts/00_check_environment.py
- ./scripts/serve_site.sh   then load http://localhost:9002/artifact-bundles.html

Human feedback
<!-- Human will fill this later. -->
