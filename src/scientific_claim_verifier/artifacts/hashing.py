"""Deterministic content hashing for artifact provenance.

Every ``PaperArtifact``, ``DatasetArtifact``, and ``CodeArtifact`` carries an
optional ``content_hash`` (typed in Milestone 1). Milestone 2 populates it here.
A hash is recorded in the trace so a report can state exactly which bytes a
verdict was computed against, and a re-run against changed artifacts is
detectable.

The hash is SHA-256 over the raw bytes, rendered as ``"sha256:<hexdigest>"``.
It is fully deterministic — no wall clock, no salt, no randomness — so a given
artifact always hashes to the same string. Text is hashed as its UTF-8 encoding.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

#: Algorithm label prefixing every hash, e.g. ``sha256:ab12…``.
HASH_ALGORITHM = "sha256"


def hash_bytes(data: bytes) -> str:
    """Return ``"sha256:<hexdigest>"`` for ``data``."""
    return f"{HASH_ALGORITHM}:{hashlib.sha256(data).hexdigest()}"


def hash_text(text: str) -> str:
    """Return the content hash of ``text`` (encoded as UTF-8)."""
    return hash_bytes(text.encode("utf-8"))


def hash_file(path: str | Path) -> str:
    """Return the content hash of the file at ``path``.

    Reads in fixed-size chunks so the helper does not depend on file size; the
    fixtures are tiny, but the streaming read keeps the function honest.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"{HASH_ALGORITHM}:{digest.hexdigest()}"


__all__ = ["HASH_ALGORITHM", "hash_bytes", "hash_text", "hash_file"]
