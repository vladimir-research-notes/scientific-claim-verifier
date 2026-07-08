"""scientific-claim-verifier.

A CPU-first, offline, auditable system for verifying scientific claims against
papers, datasets, code artifacts, and reproducibility evidence. See
``docs/PLAN.md`` for the architecture and milestone plan.

Milestone 0 provides the runnable package scaffold: this package marker, a CLI
skeleton (:mod:`scientific_claim_verifier.cli`), an environment self-check
(:mod:`scientific_claim_verifier.envcheck`), and a schema stub
(:mod:`scientific_claim_verifier.schemas`). Subsystems land in later milestones.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
