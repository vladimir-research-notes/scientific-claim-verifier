"""Run a tiny fixture script and read the metric it prints.

The code-reproduction channel: execute the committed script a claim refers to and
compare what it prints to what the claim says. Execution goes through the
:class:`~scientific_claim_verifier.sandbox.runner.ScriptRunner` protocol; the
implementation is the Milestone 6 sandbox.

Where the script actually runs
------------------------------
:class:`~scientific_claim_verifier.sandbox.runner.SandboxScriptRunner` copies the
script into a fresh temp directory, scrubs the environment down to an allowlist,
closes stdin, applies POSIX resource limits, installs an in-process guard that makes
``socket`` calls raise, runs it with a wall-clock timeout, and kills the whole process
group if that timeout fires. Those are **reproducibility** controls: they exist so
that a number a script prints came from the script's own contents rather than from
the machine it ran on. They are **not** a security boundary — the scripts are trusted,
committed, stdlib-only fixtures we wrote. See ``docs/SANDBOX.md``.

The ``entrypoint`` a task declares (``"python compute_accuracy.py"``) is recorded but
never parsed or executed; a task file must not be able to name a command to run. The
runner invokes the current interpreter on the artifact's declared ``path``.

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
The recorded command is ``("python", "<script name>")`` — never the absolute
interpreter path, which varies per machine and would make traces non-reproducible.
No duration is recorded here (timing is inherently unstable and belongs in the
sandbox trace, where it is opt-in). ``PYTHONHASHSEED=0`` and ``TZ=UTC`` are set for
the child by the sandbox policy, so a script iterating a set or printing a date
prints the same thing on every run.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..artifacts import loader
from ..sandbox.policy import DEFAULT_TIMEOUT_SECONDS
from ..sandbox.runner import ExecutionResult, SandboxError, SandboxScriptRunner, ScriptRunner
from ..schemas import (
    CheckStatus,
    CheckType,
    CodeArtifact,
    EvidenceLink,
    ScientificClaim,
    VerificationCheck,
)
from . import ErrorKind, truncate

# A metric line as the fixture scripts print it: ``accuracy=0.80``.
_METRIC_LINE_RE = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*=\s*(-?\d+(?:\.\d+)?)\s*$", re.MULTILINE)


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
    active = runner or SandboxScriptRunner()
    timeout = artifact.timeout_seconds or DEFAULT_TIMEOUT_SECONDS
    # Recorded up front so every outcome — including `skipped` — says what the bundle
    # asked this script to print. An execution that verified *nothing* is not evidence
    # for the claim, and scoring reads this to tell that case apart from a real match.
    declared = stdout_expectations(expected_outputs)
    inputs: dict = {
        "code_id": artifact.artifact_id,
        "path": artifact.path,
        "entrypoint": artifact.entrypoint,
        "language": artifact.language,
        "timeout_seconds": timeout,
        "content_hash": artifact.content_hash,
        "runner": active.name,
        "declared_expectations": declared,
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

    def failed(kind: ErrorKind, notes: str, **fields: object) -> VerificationCheck:
        inputs["error_kind"] = kind.value
        return outcome(CheckStatus.ERROR, notes, **fields)

    if not execute:
        return outcome(CheckStatus.SKIPPED, "execution disabled (--no-execute); script not run")
    if artifact.language != "python":
        return outcome(
            CheckStatus.SKIPPED, f"no runner for language {artifact.language!r}; script not run"
        )
    if artifact.path is None:
        return failed(
            ErrorKind.MISSING_CODE, f"code artifact {artifact.artifact_id!r} has no path"
        )

    try:
        script = loader.resolve_fixture_path(artifact.path, repo_root)
    except loader.TaskLoadError as exc:
        return failed(ErrorKind.MISSING_CODE, str(exc))
    if not script.is_file():
        return failed(ErrorKind.MISSING_CODE, f"script not found: {artifact.path}")

    try:
        result = active.run(script, timeout)
    except SandboxError as exc:
        # The sandbox could not enforce the policy it promised. Reporting the script's
        # output anyway would attribute a number to conditions that never held.
        return failed(ErrorKind.SANDBOX_FAILURE, f"sandbox failed: {exc}")

    inputs |= {
        "command": list(result.command),
        "exit_code": result.exit_code,
        "stdout": truncate(result.stdout),
        "stderr": truncate(result.stderr),
        "timed_out": result.timed_out,
    }
    # A script that reached for the network is not self-contained, whether or not it
    # then produced the right number. Recorded on every outcome below.
    tainted = ""
    if result.network_attempts:
        inputs["network_attempts"] = list(result.network_attempts)
        tainted = f"; the sandbox denied network access to {', '.join(result.network_attempts)}"

    if result.timed_out:
        return failed(
            ErrorKind.EXECUTION_TIMEOUT, f"script timed out after {timeout:g}s{tainted}"
        )
    if not result.ok:
        return failed(
            ErrorKind.NONZERO_EXIT,
            f"script exited {result.exit_code}; no observable was produced "
            f"(stderr: {truncate(result.stderr.strip(), 200) or 'empty'}){tainted}",
        )

    observable = parse_observable(result.stdout, claim.metrics)
    computed = observable[1] if observable else result.stdout.strip()
    if observable:
        inputs["observable"] = observable[0]

    missing = [text for text in declared if text not in result.stdout]
    if missing:
        return outcome(
            CheckStatus.FAIL,
            f"script ran cleanly but stdout lacks the declared expectation(s) {missing}{tainted}",
            computed_value=computed,
        )

    return outcome(
        CheckStatus.PASS,
        f"script exited 0 and printed the declared observable"
        f"{f' {declared}' if declared else ''}"
        f"{f'; parsed {observable[0]}={observable[1]:g}' if observable else ''}"
        f"{tainted}",
        computed_value=computed,
    )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "ExecutionResult",
    "SandboxError",
    "SandboxScriptRunner",
    "ScriptRunner",
    "code_execution_check",
    "parse_observable",
    "stdout_expectations",
]
