#!/usr/bin/env python3
"""Fixture script: a reproduction attempt that fails because its input is absent.

A trusted, harmless, offline fixture for the *failed* code-reproduction path. Unlike
`compute_accuracy.py`, this script does not embed its data: it recomputes accuracy
from a `predictions.csv` the paper never released. The artifact bundle therefore
cannot ship it, the script cannot find it, and the run exits non-zero having printed
no metric.

That is the point. It is the most common reproducibility failure there is — the code
is public, the data is not — and it exercises the distinction the schema draws
between a script that *will not run* (`failed_environment` / `execution_error`) and
one that runs and prints the wrong number (`failed_numeric_mismatch`). A checker that
conflated the two would report a contradiction where it has no evidence at all.

The missing input is detected explicitly rather than left to raise, so the captured
stderr is one stable line instead of an interpreter-version-dependent traceback.
Restore `predictions.csv` beside the script and it computes and prints
`accuracy=<value>` like any other fixture.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

# Resolved relative to the working directory, which the sandbox makes a fresh temp
# dir holding only this script. The file is absent by construction.
INPUT_PATH = Path("predictions.csv")

# The columns the script expects, in a two-column `prediction,gold` CSV of integers.
PREDICTION_COLUMN = "prediction"
GOLD_COLUMN = "gold"


def load_pairs(path: Path) -> list[tuple[int, int]]:
    """Read `(prediction, gold)` integer pairs from a two-column CSV."""
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            (int(row[PREDICTION_COLUMN]), int(row[GOLD_COLUMN]))
            for row in csv.DictReader(handle)
        ]


def accuracy(pairs: list[tuple[int, int]]) -> float:
    """Fraction of pairs where prediction and gold agree."""
    return sum(p == g for p, g in pairs) / len(pairs)


def main() -> None:
    if not INPUT_PATH.is_file():
        print(
            f"error: required input {INPUT_PATH} not found; "
            "the predictions were never released with the paper",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(f"accuracy={accuracy(load_pairs(INPUT_PATH)):.2f}")


if __name__ == "__main__":
    main()
