"""Milestone 0 — package scaffold smoke tests (CPU-only, offline)."""

from __future__ import annotations

import re

import scientific_claim_verifier
from scientific_claim_verifier import schemas


def test_version_is_semverish() -> None:
    version = scientific_claim_verifier.__version__
    assert isinstance(version, str)
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version


def test_schemas_stub_importable() -> None:
    # The stub must import without pulling in the (not-yet-used) model layer.
    assert isinstance(schemas.SCHEMA_VERSION, str)
    assert schemas.SCHEMA_VERSION


def test_public_modules_import() -> None:
    from scientific_claim_verifier import cli, envcheck

    assert callable(cli.main)
    assert callable(envcheck.check_environment)
