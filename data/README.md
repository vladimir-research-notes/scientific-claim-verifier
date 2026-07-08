# Fixture data

Small, **synthetic or open** artifacts used to exercise the verification checks.
Everything here is committed and intended to run fully offline.

```
fixtures/
  papers/      paper snippets / passages (with stable passage IDs)
  datasets/    small CSVs for statistic recomputation
  code/        tiny Python scripts computing a reported metric
  expected/    ground-truth values for scoring
```

## Rules

- No private or real papers; no real patient data; no credentials.
- No large datasets, model weights, or binary blobs (see repo `.gitignore`).
- Keep each fixture small enough to read and reason about by hand.
- Every fixture is referenced by at least one task under `tasks/` and validated
  by `scripts/01_validate_fixtures.py` (from Milestone 2).

Fixtures are populated starting in Milestone 2.
