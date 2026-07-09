"""Run a tiny fixture script and read the metric it prints.

The code-reproduction channel: execute the committed script a claim refers to and
compare what it prints to what the claim says. Execution goes through the
:class:`ScriptRunner` protocol; this milestone ships one implementation.

What this executor is, precisely
--------------------------------
:class:`SubprocessScriptRunner` runs ``python <script>`` as a child process with a
wall-clock timeout, ``stdin`` closed, and stdout/stderr/exit-code captured. That is
all. It does **not** copy the script to a temp directory, scrub the environment,
restrict the filesystem, or block the network. It is not a security boundary of any
kind, and the scripts it runs are trusted, committed, stdlib-only fixtures that we
wrote. Milestone 6 adds the temp working directory, the no-network policy, and the
trace record **behind this same protocol** — a check written against
:class:`ScriptRunner` needs no change when it lands.

Execution failure is not numeric disagreement
----------------------------------------------
A script that will not run tells you nothing about the claim's number, so a
timeout, a non-zero exit, or a missing file is ``error`` — the check could not
run — never ``fail``. A script that runs cleanly but omits the observable the
bundle declared is ``fail``. Whether the number it printed *matches* the claim is a
separate ``numeric_tolerance`` check, because ``failed_environment`` and
``failed_numeric_mismatch`` are different reproduction outcomes and a report must
be able to tell them apart.

Determinism
-----------
The recorded command is ``("python", "<repo-relative script path>")`` — never the
absolute interpreter path, which varies per machine and would make traces
non-reproducible. No duration is recorded here (timing is inherently unstable);
Milestone 6's trace is where wall-clock facts belong. The child inherits the
environment except for ``PYTHONHASHSEED=0``, set so that a script iterating a set
prints the same order on every run.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..artifacts import loader
from ..schemas import (
    CheckStatus,
    CheckType,
    CodeArtifact,
    EvidenceLink,
    ScientificClaim,
    VerificationCheck,
)
from . import truncate

# Applied when a code artifact declares no ``timeout_seconds``.
DEFAULT_TIMEOUT_SECONDS = 10.0

# A metric line as the fixture scripts print it: ``accuracy=0.80``.
_METRIC_LINE_RE = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*=\s*(-?\d+(?:\.\d+)?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ExecutionResult:
    """What running a script produced. ``exit_code`` is ``None`` when it timed out."""

    command: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool

    @property
    def ok(self) -> bool:
        """True when the script ran to completion and exited zero."""
        return not self.timed_out and self.exit_code == 0


class ScriptRunner(Protocol):
    """Executes a script and captures its output. Milestone 6 hardens the implementation."""

    name: str

    def run(self, script: Path, timeout: float) -> ExecutionResult:
        """Run ``script``, returning its captured output. Never raises on script failure."""
        ...


class SubprocessScriptRunner:
    """The interim runner: a bare child process with a timeout. See the module docstring."""

    name = "subprocess"

    def run(self, script: Path, timeout: float) -> ExecutionResult:
        # `sys.executable` is used to run under the same interpreter as the tests,
        # but is recorded as "python" so the trace is machine-independent.
        interpreter = sys.executable or "python3"
        command = (interpreter, str(script))
        environment = {**os.environ, "PYTHONHASHSEED": "0"}
        try:
            completed = subprocess.run(  # noqa: S603 — trusted, committed fixture script
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=script.parent,
                stdin=subprocess.DEVNULL,
                env=environment,
                check=False,
            )
        except subprocess.TimeoutExpired as expired:
            return ExecutionResult(
                command=("python", script.name),
                exit_code=None,
                stdout=_decode(expired.stdout),
                stderr=_decode(expired.stderr),
                timed_out=True,
            )
        return ExecutionResult(
            command=("python", script.name),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
        )


def _decode(captured: str | bytes | None) -> str:
    """Normalize the partial output a timeout hands back."""
    if captured is None:
        return ""
    return captured if isinstance(captured, str) else captured.decode("utf-8", "replace")


def parse_observable(stdout: str, metrics: list[str]) -> tuple[str, float] | None:
    """Find the ``name=value`` metric line the claim is about, as ``(name, value)``.

    Prefers a line whose name is one of the claim's ``metrics``; falls back to the
    sole metric line when there is exactly one. Returns ``None`` when the script
    printed several unrelated metric lines — picking one would be a guess.
    """
    lines = [(m.group(1), float(m.group(2))) for m in _METRIC_LINE_RE.finditer(stdout)]
    if not lines:
        return None
    wanted = {metric.lower() for metric in metrics}
    for name, value in lines:
        if name.lower() in wanted:
            return name, value
    return lines[0] if len(lines) == 1 else None


def stdout_expectations(expected_outputs: dict) -> list[str]:
    """The declared ``stdout*`` substrings a run must contain, in key order."""
    return [
        str(value)
        for key, value in sorted(expected_outputs.items())
        if str(key).startswith("stdout")
    ]


def code_execution_check(
    check_id: str,
    claim: ScientificClaim,
    artifact: CodeArtifact,
    link: EvidenceLink,
    expected_outputs: dict,
    repo_root: Path,
    runner: ScriptRunner | None = None,
    execute: bool = True,
) -> VerificationCheck:
    """Execute the linked fixture script and check it produced the declared observable.

    Set ``execute=False`` to record a ``skipped`` check without running anything —
    the escape hatch for an environment where running child processes is unwanted.
    """
    active = runner or SubprocessScriptRunner()
    timeout = artifact.timeout_seconds or DEFAULT_TIMEOUT_SECONDS
    inputs: dict = {
        "code_id": artifact.artifact_id,
        "path": artifact.path,
        "entrypoint": artifact.entrypoint,
        "language": artifact.language,
        "timeout_seconds": timeout,
        "content_hash": artifact.content_hash,
        "runner": active.name,
    }

    def outcome(status: CheckStatus, notes: str, **fields: object) -> VerificationCheck:
        return VerificationCheck(
            check_id=check_id,
            check_type=CheckType.CODE_EXECUTION,
            claim_id=claim.claim_id,
            status=status,
            inputs=inputs,
            evidence=[link],
            notes=notes,
            **fields,  # type: ignore[arg-type]
        )

    if not execute:
        return outcome(CheckStatus.SKIPPED, "execution disabled (--no-execute); script not run")
    if artifact.language != "python":
        return outcome(
            CheckStatus.SKIPPED, f"no runner for language {artifact.language!r}; script not run"
        )
    if artifact.path is None:
        return outcome(CheckStatus.ERROR, f"code artifact {artifact.artifact_id!r} has no path")

    try:
        script = loader.resolve_fixture_path(artifact.path, repo_root)
    except loader.TaskLoadError as exc:
        return outcome(CheckStatus.ERROR, str(exc))
    if not script.is_file():
        return outcome(CheckStatus.ERROR, f"script not found: {artifact.path}")

    result = active.run(script, timeout)
    inputs |= {
        "command": list(result.command),
        "exit_code": result.exit_code,
        "stdout": truncate(result.stdout),
        "stderr": truncate(result.stderr),
        "timed_out": result.timed_out,
    }

    if result.timed_out:
        return outcome(CheckStatus.ERROR, f"script timed out after {timeout:g}s")
    if not result.ok:
        return outcome(
            CheckStatus.ERROR,
            f"script exited {result.exit_code}; no observable was produced "
            f"(stderr: {truncate(result.stderr.strip(), 200) or 'empty'})",
        )

    observable = parse_observable(result.stdout, claim.metrics)
    computed = observable[1] if observable else result.stdout.strip()
    if observable:
        inputs["observable"] = observable[0]

    missing = [text for text in stdout_expectations(expected_outputs) if text not in result.stdout]
    if missing:
        return outcome(
            CheckStatus.FAIL,
            f"script ran cleanly but stdout lacks the declared expectation(s) {missing}",
            computed_value=computed,
        )

    declared = stdout_expectations(expected_outputs)
    return outcome(
        CheckStatus.PASS,
        f"script exited 0 and printed the declared observable"
        f"{f' {declared}' if declared else ''}"
        f"{f'; parsed {observable[0]}={observable[1]:g}' if observable else ''}",
        computed_value=computed,
    )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "ExecutionResult",
    "ScriptRunner",
    "SubprocessScriptRunner",
    "parse_observable",
    "stdout_expectations",
    "code_execution_check",
]
