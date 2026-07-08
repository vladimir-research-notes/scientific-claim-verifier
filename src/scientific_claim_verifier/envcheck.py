"""Environment self-check for scientific-claim-verifier.

Reports the Python interpreter, the platform, and whether the libraries the
pipeline relies on are importable. This is a purely local, offline check: it
imports modules and reads version attributes; it never touches the network.

The check *passes* when the interpreter meets the minimum version and every
**required** library imports. Data-analysis libraries are **optional** at this
stage — they land with the milestones that first use them (see ``docs/PLAN.md``),
so a missing optional library is reported, not treated as a failure.
"""

from __future__ import annotations

import importlib
import platform
import sys
from dataclasses import dataclass, field

# Interpreter policy. The floor is 3.11 (the typed schema uses ``enum.StrEnum``,
# new in 3.11); the project targets 3.12.
MIN_PYTHON: tuple[int, int] = (3, 11)
RECOMMENDED_PYTHON: tuple[int, int] = (3, 12)

# (import name, purpose). Required libraries must import for the check to pass.
REQUIRED_LIBS: list[tuple[str, str]] = [
    ("pydantic", "typed data model / schema validation (Milestone 1)"),
    ("yaml", "task & fixture parsing (Milestone 2)"),
]

# Optional libraries are informational at this stage; they arrive with the
# milestones that first need them and must not fail the check when absent.
OPTIONAL_LIBS: list[tuple[str, str]] = [
    ("numpy", "numeric tolerance / array checks (Milestone 5)"),
    ("pandas", "table & dataset-statistic recomputation (Milestones 5+)"),
    ("scipy", "statistical checks — only if needed (Milestone 5)"),
    ("matplotlib", "figure recomputation (Milestone 5)"),
]


@dataclass
class LibStatus:
    """Import status of a single library."""

    name: str
    purpose: str
    required: bool
    found: bool
    version: str | None = None


@dataclass
class EnvReport:
    """Structured result of an environment check."""

    python_version: str
    python_ok: bool
    python_recommended: bool
    implementation: str
    platform_name: str
    machine: str
    executable: str
    libs: list[LibStatus] = field(default_factory=list)

    @property
    def required_ok(self) -> bool:
        return all(lib.found for lib in self.libs if lib.required)

    @property
    def ok(self) -> bool:
        """True when the interpreter floor is met and all required libs import."""
        return self.python_ok and self.required_ok


def _probe(name: str, purpose: str, required: bool) -> LibStatus:
    """Attempt to import ``name`` and record its version (offline)."""
    try:
        module = importlib.import_module(name)
    except Exception:
        return LibStatus(name=name, purpose=purpose, required=required, found=False)
    version = getattr(module, "__version__", None)
    return LibStatus(
        name=name,
        purpose=purpose,
        required=required,
        found=True,
        version=str(version) if version is not None else None,
    )


def check_environment() -> EnvReport:
    """Inspect the running interpreter and library availability."""
    info = sys.version_info
    python_ok = (info.major, info.minor) >= MIN_PYTHON
    python_recommended = (info.major, info.minor) >= RECOMMENDED_PYTHON

    libs = [_probe(name, purpose, required=True) for name, purpose in REQUIRED_LIBS]
    libs += [_probe(name, purpose, required=False) for name, purpose in OPTIONAL_LIBS]

    return EnvReport(
        python_version=platform.python_version(),
        python_ok=python_ok,
        python_recommended=python_recommended,
        implementation=platform.python_implementation(),
        platform_name=platform.platform(),
        machine=platform.machine(),
        executable=sys.executable,
        libs=libs,
    )


def format_report(report: EnvReport) -> str:
    """Render an ``EnvReport`` as a plain-text block."""
    py_flag = "OK" if report.python_ok else "TOO OLD"
    rec = ""
    if not report.python_recommended:
        rec = f"  (target: {RECOMMENDED_PYTHON[0]}.{RECOMMENDED_PYTHON[1]}+)"
    lines: list[str] = [
        "scientific-claim-verifier — environment check",
        "=" * 46,
        f"Python        : {report.python_version}  [{py_flag}]{rec}",
        f"Implementation: {report.implementation}",
        f"Platform      : {report.platform_name}",
        f"Machine       : {report.machine}",
        f"Executable    : {report.executable}",
        "",
        "Libraries (required):",
    ]

    def _fmt(lib: LibStatus) -> str:
        mark = "ok  " if lib.found else "MISS"
        ver = f" {lib.version}" if lib.version else ""
        state = f"{mark}{ver}"
        return f"  [{state:>10}] {lib.name:<12} {lib.purpose}"

    for lib in report.libs:
        if lib.required:
            lines.append(_fmt(lib))
    lines.append("")
    lines.append("Libraries (optional — land with later milestones):")
    for lib in report.libs:
        if not lib.required:
            lines.append(_fmt(lib))

    lines.append("")
    lines.append("Posture       : CPU-only, offline, no paid API required.")
    lines.append(f"Overall       : {'READY' if report.ok else 'NOT READY'}")
    if not report.ok:
        if not report.python_ok:
            lines.append(
                f"  - Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required."
            )
        missing = [lib.name for lib in report.libs if lib.required and not lib.found]
        if missing:
            lines.append(
                "  - Missing required libraries: "
                + ", ".join(missing)
                + "  (install with: pip install -e .)"
            )
    return "\n".join(lines)


def run(argv: list[str] | None = None) -> int:
    """Print the environment report; return 0 if ready, 1 otherwise."""
    report = check_environment()
    print(format_report(report))
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
