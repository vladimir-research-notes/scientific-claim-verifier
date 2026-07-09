# Fixture data

Small, **synthetic or open** artifacts used to exercise the verification checks.
Everything here is committed and intended to run fully offline.

```
fixtures/
  datasets/    small CSVs for statistic recomputation
  code/        tiny Python scripts computing a reported metric
```

Paper snippets and expected/gold values are held **inline in the task files**
under `tasks/` (see `docs/ARTIFACT_FORMAT.md`), so only file-backed artifacts —
datasets and code — live here. Standalone `papers/` and `expected/` directories
will be added if a fixture ever outgrows inlining.

## Committed fixtures

| Fixture | Added | What it is |
| --- | --- | --- |
| `datasets/measurements.csv` | M2 | 12 synthetic scalar measurements (mean 3.4, pstdev 1.1299) |
| `code/compute_accuracy.py` | M2 | prints `accuracy=0.80` (trusted, stdlib-only) |
| `code/gc_content.py` | M2 | prints `gc_content=0.50` (toy bioinformatics) |
| `code/reproduce_from_predictions.py` | M8 | exits 1: its input `predictions.csv` was never released |

`measurements.csv` backs three tasks, which read three different things out of it:
`dataset_mean` reproduces its mean exactly, `dataset_std` lands *inside* the claim's
tolerance without landing on it (`approximately_reproduced`), and
`dataset_mean_overstated` is refuted by it.

`reproduce_from_predictions.py` is the only fixture that fails on purpose. It is a
complete, working script whose data the paper never shipped — the most ordinary
reproducibility failure there is. It exists so the pipeline has to distinguish a script
that *will not run* (`failed_environment`) from one that runs and prints the wrong
number (`failed_numeric_mismatch`), which are different facts about a claim.

## Rules

- No private or real papers; no real patient data; no credentials.
- No large datasets, model weights, or binary blobs (see repo `.gitignore`).
- Keep each fixture small enough to read and reason about by hand.
- Every fixture is referenced by at least one task under `tasks/` and validated
  by `scripts/01_validate_fixtures.py` / `claimverifier validate-fixtures`.
