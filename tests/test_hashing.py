"""Milestone 2 — content hashing tests (CPU-only, offline)."""

from __future__ import annotations

from scientific_claim_verifier.artifacts import hashing


def test_hash_bytes_format() -> None:
    h = hashing.hash_bytes(b"abc")
    algo, _, hexdigest = h.partition(":")
    assert algo == "sha256"
    assert len(hexdigest) == 64
    assert all(c in "0123456789abcdef" for c in hexdigest)


def test_hash_bytes_known_vector() -> None:
    # SHA-256 of the empty input is a fixed, well-known digest.
    empty = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert hashing.hash_bytes(b"") == f"sha256:{empty}"


def test_hash_text_matches_utf8_bytes() -> None:
    assert hashing.hash_text("héllo") == hashing.hash_bytes("héllo".encode())


def test_hash_is_deterministic_and_content_sensitive() -> None:
    assert hashing.hash_text("x") == hashing.hash_text("x")
    assert hashing.hash_text("x") != hashing.hash_text("y")


def test_hash_file_matches_bytes(tmp_path) -> None:
    payload = b"line1\nline2\n"
    f = tmp_path / "sample.txt"
    f.write_bytes(payload)
    assert hashing.hash_file(f) == hashing.hash_bytes(payload)
