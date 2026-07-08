#!/usr/bin/env python3
"""Fixture script: compute the GC content of a short embedded DNA sequence.

A trusted, harmless, offline fixture for a *toy* bioinformatics claim. GC content
is the fraction of bases that are guanine (G) or cytosine (C). The script takes
no arguments, imports nothing beyond the standard library, reads no files or
network, and prints one deterministic metric line:

    gc_content=0.50

This is a toy computation over a synthetic sequence, well within the project's
in-scope bioinformatics analyses (see docs/SAFETY.md) — not a wet-lab protocol.
"""

from __future__ import annotations

# Synthetic 10-base sequence; 5 of 10 bases are G or C (GC content = 0.50).
SEQUENCE = "ACGCACGTAT"


def gc_content(sequence: str) -> float:
    """Fraction of bases in ``sequence`` that are G or C (case-insensitive)."""
    gc = sum(1 for base in sequence.upper() if base in {"G", "C"})
    return gc / len(sequence)


def main() -> None:
    print(f"gc_content={gc_content(SEQUENCE):.2f}")


if __name__ == "__main__":
    main()
