#!/usr/bin/env python3
"""Fixture script: compute classification accuracy over a tiny embedded set.

A trusted, harmless, offline fixture for the code-reproduction task family. It
takes no arguments, imports nothing beyond the standard library, reads no files
or network, and prints one deterministic metric line:

    accuracy=0.80

The predictions and gold labels are embedded so the script is fully
self-contained and reproducible. It exists to be executed by the controlled
fixture sandbox in a later milestone — it is *not* untrusted code.
"""

from __future__ import annotations

# Model predictions and gold labels for a 10-example toy set (8 correct).
PREDICTIONS = [1, 0, 1, 1, 0, 1, 0, 0, 1, 1]
GOLD_LABELS = [1, 0, 1, 0, 0, 1, 1, 0, 1, 1]


def accuracy(predictions: list[int], gold: list[int]) -> float:
    """Fraction of positions where prediction and gold agree."""
    correct = sum(p == g for p, g in zip(predictions, gold, strict=True))
    return correct / len(gold)


def main() -> None:
    print(f"accuracy={accuracy(PREDICTIONS, GOLD_LABELS):.2f}")


if __name__ == "__main__":
    main()
