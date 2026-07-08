"""Artifact handling: content hashing, task loading, and fixture validation.

Milestone 2 introduces the on-disk *task* format and the machinery that turns a
task file into the typed objects defined in
:mod:`scientific_claim_verifier.schemas`:

- :mod:`scientific_claim_verifier.artifacts.hashing` — deterministic
  ``sha256:`` content hashes for provenance.
- :mod:`scientific_claim_verifier.artifacts.loader` — the task-file schema
  (``TaskSpec`` and friends) and :func:`~.loader.load_task`, which parses a task,
  resolves and hashes its referenced fixture files, and returns a validated
  :class:`~.loader.LoadedTask`.
- :mod:`scientific_claim_verifier.artifacts.validation` — directory-level
  fixture validation and the report rendered by ``claimverifier
  validate-fixtures`` / ``scripts/01_validate_fixtures.py``.

Nothing here extracts, links, checks, or executes anything — those subsystems
land in later milestones. This layer only *loads and validates* fixtures.
"""

from __future__ import annotations

__all__: list[str] = []
