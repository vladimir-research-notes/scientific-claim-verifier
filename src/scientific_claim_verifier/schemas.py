"""Typed data model for scientific-claim-verifier (stub).

This module is intentionally a stub at Milestone 0. The full typed schema is
defined in Milestone 1 (see ``docs/PLAN.md`` section 6):

- ``ScientificClaim`` and its claim-type vocabulary
- ``ArtifactBundle`` with ``PaperArtifact`` / ``DatasetArtifact`` / ``CodeArtifact``
- ``EvidenceLink``, ``VerificationCheck``, ``VerificationResult``
- the ``SupportLabel`` / ``ReproductionStatus`` / ``FailureMode`` vocabularies
- ``RunTrace`` and ``BenchmarkSuite``

Keeping it empty here honours the "one milestone at a time" contract and keeps
the Milestone 0 package import-light: the ``pydantic`` dependency is not imported
until the models actually land.
"""

from __future__ import annotations

# Placeholder schema version. Bumped to a real, meaningful version string when
# the typed models are introduced in Milestone 1.
SCHEMA_VERSION = "0-stub"

__all__ = ["SCHEMA_VERSION"]
