"""Milestone 0 — environment self-check tests (CPU-only, offline)."""

from __future__ import annotations

from scientific_claim_verifier import envcheck


def test_check_environment_reports_python_ok() -> None:
    report = envcheck.check_environment()
    # Tests run on the supported interpreter, so the floor must be met.
    assert report.python_ok
    assert report.python_version
    assert report.machine


def test_required_libraries_present() -> None:
    report = envcheck.check_environment()
    required = [lib for lib in report.libs if lib.required]
    assert required, "expected at least one required library"
    assert all(lib.found for lib in required)
    # pydantic is a declared dependency and must therefore be importable.
    assert any(lib.name == "pydantic" and lib.found for lib in report.libs)


def test_report_is_ready_and_formats() -> None:
    report = envcheck.check_environment()
    assert report.ok  # required libs present + python floor met
    text = envcheck.format_report(report)
    assert "environment check" in text
    assert "Python" in text
    assert "READY" in text


def test_run_returns_zero_when_ready(capsys) -> None:
    code = envcheck.run()
    out = capsys.readouterr().out
    assert code == 0
    assert "Overall" in out
