"""Milestone 0 — CLI skeleton tests (CPU-only, offline)."""

from __future__ import annotations

import pytest

from scientific_claim_verifier import __version__, cli


def test_parser_prog_name() -> None:
    parser = cli.build_parser()
    assert parser.prog == "claimverifier"


def test_version_command(capsys) -> None:
    code = cli.main(["version"])
    out = capsys.readouterr().out.strip()
    assert code == 0
    assert out == __version__


def test_version_flag_exits_zero(capsys) -> None:
    # argparse's `--version` action prints and raises SystemExit(0).
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_check_env_command_ready(capsys) -> None:
    code = cli.main(["check-env"])
    out = capsys.readouterr().out
    assert code == 0
    assert "environment check" in out


def test_no_command_prints_help(capsys) -> None:
    code = cli.main([])
    out = capsys.readouterr().out
    assert code == 0
    assert "check-env" in out
    assert "usage" in out.lower()


def test_unknown_command_errors() -> None:
    # Unimplemented verbs must fail loudly rather than silently no-op.
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["verify"])
    assert excinfo.value.code != 0
