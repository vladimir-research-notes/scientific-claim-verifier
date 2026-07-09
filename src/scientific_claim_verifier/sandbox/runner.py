"""Running a fixture script under the policy, and recording exactly what happened.

Milestone 6. :class:`SandboxScriptRunner` implements the :class:`ScriptRunner`
protocol that Milestone 5's ``code_execution`` check already calls through, so the
check needed no change when the real runner landed — only its default.

One run, start to finish
------------------------
1. Make a fresh temp root with ``work/``, ``home/``, ``tmp/``, ``bootstrap/``.
2. Copy the script into ``work/`` and hash the bytes that will actually execute.
3. Plant the bootstrap module (the network guard) in ``bootstrap/``.
4. Start ``python <script>`` with ``cwd=work/``, stdin closed, a scrubbed
   environment, resource limits applied before ``exec``, and its own session so the
   whole process group can be killed as a unit.
5. On timeout, kill the process group — not just the direct child.
6. Verify the guard installed, collect network attempts and files written, redact
   the temp path out of the captured output, and return an :class:`ExecutionResult`.
7. Remove the temp root.

Every one of those is a *reproducibility* control, not a security control. See
:mod:`scientific_claim_verifier.sandbox.policy` and ``docs/SANDBOX.md``.

Determinism
-----------
Everything recorded is machine-independent. The command is ``("python", "s.py")``,
never ``sys.executable``. Captured output has the sandbox root replaced with
``<sandbox>``. ``files_written`` and ``network_attempts`` are sorted. The wall-clock
``duration_seconds`` is measured because a reader wants it, and is kept **out of the
trace by default** because it is the one value that cannot be reproduced.

The ``entrypoint`` a task declares (``"python compute_accuracy.py"``) is documentation.
It is never parsed or executed: a task file must not be able to name a command to run.
The runner always invokes the current interpreter on the artifact's declared ``path``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..artifacts import hashing, loader
from ..artifacts.loader import LoadedTask
from ..schemas import CodeArtifact
from . import policy as policy_module
from . import trace as trace_module
from .policy import DEFAULT_POLICY, DEFAULT_TIMEOUT_SECONDS, NetworkPolicy, SandboxPolicy, redact

# Filenames inside the sandbox root. Never seen by the fixture script's own code —
# only by the bootstrap module, which is told about them through the environment.
NETWORK_LOG_FILENAME = "network.log"
MARKER_FILENAME = "bootstrap.ok"

# Grace period for reaping a process group after SIGKILL, before falling back to
# killing the direct child alone.
KILL_GRACE_SECONDS = 5.0


class SandboxError(RuntimeError):
    """Raised when the sandbox itself failed — never when the *script* failed.

    A script that crashes, times out, or prints nothing is a normal result. A missing
    bootstrap marker, meaning the network guard silently did not install, is not: it
    would make the trace claim a policy that was never applied.
    """


@dataclass(frozen=True)
class ExecutionResult:
    """The record of one execution: what ran, what it produced, under what policy.

    ``exit_code`` is ``None`` when the run timed out, and negative when the process
    was killed by a signal (``-9`` for ``SIGKILL``, ``-24`` for the CPU limit).
    """

    command: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    script: str = ""
    script_hash: str | None = None
    network_attempts: tuple[str, ...] = ()
    files_written: tuple[str, ...] = ()
    policy: Mapping[str, Any] = field(default_factory=dict)
    duration_seconds: float | None = None

    @property
    def ok(self) -> bool:
        """True when the script ran to completion and exited zero."""
        return not self.timed_out and self.exit_code == 0

    @property
    def signal(self) -> int | None:
        """The signal number that killed the process, or ``None``."""
        if self.exit_code is None or self.exit_code >= 0:
            return None
        return -self.exit_code


class ScriptRunner(Protocol):
    """Executes a script and captures its output. Never raises on *script* failure."""

    name: str

    def run(self, script: Path, timeout: float) -> ExecutionResult:
        """Run ``script`` with a wall-clock ``timeout``, returning what it produced."""
        ...


class SandboxScriptRunner:
    """Runs a trusted fixture script under a :class:`SandboxPolicy`."""

    name = "sandbox"

    def __init__(self, policy: SandboxPolicy | None = None) -> None:
        self.policy = policy or DEFAULT_POLICY

    def run(self, script: Path, timeout: float) -> ExecutionResult:
        """Execute ``script`` in a fresh temp directory; always clean up after."""
        script = Path(script)
        if not script.is_file():
            raise SandboxError(f"script not found: {script}")
        policy = self.policy.with_timeout(timeout)
        root = Path(tempfile.mkdtemp(prefix=policy_module.WORKDIR_PREFIX))
        try:
            return self._execute(script, root, policy)
        finally:
            if policy.cleanup:
                shutil.rmtree(root, ignore_errors=True)

    def _execute(self, script: Path, root: Path, policy: SandboxPolicy) -> ExecutionResult:
        work, home, tmpdir, bootstrap = (root / n for n in ("work", "home", "tmp", "bootstrap"))
        for directory in (work, home, tmpdir, bootstrap):
            directory.mkdir()

        target = work / script.name
        shutil.copyfile(script, target)
        policy_module.write_bootstrap(bootstrap)

        network_log = root / NETWORK_LOG_FILENAME
        marker = root / MARKER_FILENAME
        environment = policy.environment(
            home=home, tmpdir=tmpdir, bootstrap=bootstrap, network_log=network_log, marker=marker
        )
        before = _files_under(work)

        # `sys.executable` runs the script under the same interpreter as its caller,
        # but is recorded as "python" so the trace does not depend on the machine.
        interpreter = sys.executable or "python3"
        started = time.monotonic()
        process = subprocess.Popen(  # noqa: S603 — trusted, committed fixture script
            [interpreter, script.name],
            cwd=work,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,  # its own process group, so a timeout kills the tree
            preexec_fn=policy.limit_applier(),  # noqa: PLW1509 — single-threaded parent
        )
        try:
            stdout, stderr = process.communicate(timeout=policy.timeout_seconds)
            timed_out = False
        except subprocess.TimeoutExpired:
            stdout, stderr = _kill_and_drain(process)
            timed_out = True
        duration = time.monotonic() - started

        # A timeout kills the child mid-flight, so the marker is only meaningful for a
        # run that reached its own conclusion.
        if not timed_out:
            _verify_bootstrap(marker, policy)

        return ExecutionResult(
            command=("python", script.name),
            exit_code=None if timed_out else process.returncode,
            stdout=policy.clip(redact(stdout, root)),
            stderr=policy.clip(redact(stderr, root)),
            timed_out=timed_out,
            script=script.name,
            script_hash=hashing.hash_file(target),
            network_attempts=_network_attempts(network_log),
            files_written=tuple(sorted(_files_under(work) - before)),
            policy=policy.describe(),
            duration_seconds=round(duration, 3),
        )


# ---------------------------------------------------------------------------
# Runner internals
# ---------------------------------------------------------------------------


def _kill_and_drain(process: subprocess.Popen[str]) -> tuple[str, str]:
    """SIGKILL the child's whole process group, then collect whatever it printed."""
    _kill_process_group(process)
    try:
        return process.communicate(timeout=KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:  # pragma: no cover - a survivor holds the pipes
        process.kill()
        return process.communicate()


def _kill_process_group(process: subprocess.Popen[str]) -> None:
    """Kill the process group, so a script's own children die with it.

    ``subprocess.run(timeout=...)`` kills only the direct child, which would leave a
    grandchild running and holding the output pipes open. The child was started with
    ``start_new_session=True``, so its pgid is its own pid and the group is exactly
    the script and its descendants.
    """
    killpg, getpgid = getattr(os, "killpg", None), getattr(os, "getpgid", None)
    if killpg is not None and getpgid is not None:
        try:
            killpg(getpgid(process.pid), signal.SIGKILL)
            return
        except OSError:  # already reaped, or no permission
            pass
    process.kill()  # pragma: no cover - non-POSIX fallback


def _verify_bootstrap(marker: Path, policy: SandboxPolicy) -> None:
    """Confirm the child's bootstrap ran and applied the policy we asked for.

    ``site.execsitecustomize`` catches every exception raised by ``sitecustomize``,
    prints one line to stderr, and lets the interpreter continue. Without this check a
    broken guard would leave the network open while the trace recorded ``blocked``.
    """
    if not marker.is_file():
        raise SandboxError(
            f"the sandbox bootstrap ({policy_module.BOOTSTRAP_MODULE}) did not run in the "
            f"child interpreter, so the '{policy.network.value}' network policy was not "
            "applied; refusing to report a result under a policy that was not enforced"
        )
    applied = marker.read_text(encoding="utf-8").strip()
    if applied != policy.network.value:
        raise SandboxError(
            f"the sandbox bootstrap applied network policy {applied!r}, "
            f"but the policy in force is {policy.network.value!r}"
        )


def _network_attempts(network_log: Path) -> tuple[str, ...]:
    """The distinct ``socket`` calls the guard denied, sorted for a stable record.

    The log survives a script that *catches* the guard's exception, so a swallowed
    network attempt still reaches the trace.
    """
    if not network_log.is_file():
        return ()
    lines = network_log.read_text(encoding="utf-8", errors="replace").splitlines()
    return tuple(sorted({line.strip() for line in lines if line.strip()}))


def _files_under(directory: Path) -> set[str]:
    """Relative paths of every file under ``directory`` (sorted by the caller)."""
    return {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}


# ---------------------------------------------------------------------------
# Running a task's code artifacts
# ---------------------------------------------------------------------------


def code_artifacts(task: LoadedTask, code_id: str | None = None) -> list[CodeArtifact]:
    """The task's executable code artifacts, or just the one named by ``code_id``."""
    artifacts = [c for c in task.bundle.code_files if c.language == "python" and c.path]
    if code_id is None:
        return artifacts
    selected = [c for c in artifacts if c.artifact_id == code_id]
    if not selected:
        raise SandboxError(f"task declares no runnable python code artifact {code_id!r}")
    return selected


def run_artifact(
    artifact: CodeArtifact,
    repo_root: Path,
    *,
    policy: SandboxPolicy | None = None,
    timeout: float | None = None,
) -> ExecutionResult:
    """Resolve a code artifact's script and run it. ``timeout`` overrides the artifact's."""
    if artifact.path is None:  # pragma: no cover - filtered by `code_artifacts`
        raise SandboxError(f"code artifact {artifact.artifact_id!r} has no path")
    script = loader.resolve_fixture_path(artifact.path, repo_root)
    effective = timeout or artifact.timeout_seconds or DEFAULT_TIMEOUT_SECONDS
    return SandboxScriptRunner(policy).run(script, effective)


def result_to_dict(result: ExecutionResult, *, include_timing: bool = False) -> dict[str, Any]:
    """Serialize an execution to a JSON-ready dict. Timing is opt-in (it is volatile)."""
    payload: dict[str, Any] = {
        "command": list(result.command),
        "script": result.script,
        "script_hash": result.script_hash,
        "exit_code": result.exit_code,
        "signal": result.signal,
        "timed_out": result.timed_out,
        "ok": result.ok,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "network_attempts": list(result.network_attempts),
        "files_written": list(result.files_written),
        "policy": dict(result.policy),
    }
    if include_timing:
        payload["duration_seconds"] = result.duration_seconds
    return payload


# ---------------------------------------------------------------------------
# Rendering + CLI entry points
# ---------------------------------------------------------------------------


def _outcome(result: ExecutionResult) -> str:
    """One line naming how the process ended."""
    if result.timed_out:
        return f"timed out after {result.policy.get('timeout_seconds')}s (process group killed)"
    if result.signal is not None:
        return f"killed by signal {result.signal} (a resource limit, or an external kill)"
    return f"exited {result.exit_code}"


def _block(label: str, text: str) -> list[str]:
    """A captured-output block, indented, with an explicit marker when empty."""
    if not text.strip():
        return [f"{label}:", "  (empty)"]
    return [f"{label}:", *(f"  {line}" for line in text.rstrip("\n").splitlines())]


def render_execution(
    task: LoadedTask, artifact: CodeArtifact, result: ExecutionResult, *, with_timing: bool = False
) -> str:
    """Render one sandboxed execution, policy first: the conditions come before the number."""
    described = dict(result.policy)
    limits = described.get("resource_limits") or {}
    lines = [
        "scientific-claim-verifier — sandbox execution",
        "=" * 45,
        f"Task            : {task.spec.task_id}",
        f"Code artifact   : {artifact.artifact_id} ({artifact.path})",
        f"Content hash    : {result.script_hash}",
        f"Command         : {' '.join(result.command)}",
        "",
        "Policy (recorded verbatim into the trace):",
        f"  timeout       : {described.get('timeout_seconds')}s",
        f"  network       : {described.get('network')} — {described.get('network_guard')}",
        f"  working dir   : {described.get('working_directory')}",
        f"  stdin         : {described.get('stdin')}",
        f"  env allowlist : {', '.join(described.get('env_allowlist', []))}",
        "  env overrides : "
        + ", ".join(f"{k}={v}" for k, v in sorted(described.get("env_overrides", {}).items())),
        "  rlimits       : "
        + (", ".join(f"{k}={v}" for k, v in sorted(limits.items())) or "none (unavailable)"),
        f"  isolation     : {described.get('isolation')}",
        "",
        f"Outcome         : {_outcome(result)}",
        f"Network attempts: {', '.join(result.network_attempts) or 'none'}",
        f"Files written   : {', '.join(result.files_written) or 'none'}",
        "",
        *_block("stdout", result.stdout),
        *_block("stderr", result.stderr),
    ]
    if with_timing:
        lines += [
            "",
            f"Duration        : {result.duration_seconds}s "
            "(volatile — recorded in the trace only because --with-timing was given)",
        ]
    return "\n".join(lines)


def sandbox_and_report(
    task_path: str | Path,
    out_dir: str | Path | None = None,
    as_json: bool = False,
    code_id: str | None = None,
    timeout: float | None = None,
    allow_network: bool = False,
    with_timing: bool = False,
    repo_root: str | Path | None = None,
) -> int:
    """Load a task, run its code artifacts in the sandbox, print a report, write a trace.

    Returns 0 when every script was executed (whatever it did), 1 when the task could
    not be loaded, declares nothing runnable, or the sandbox itself failed. A script
    that crashes is a *result*, not a CLI error — the report shows it and exits 0.
    """
    try:
        task = loader.load_task(task_path, repo_root)
    except (loader.TaskLoadError, OSError) as exc:
        print(f"error: could not load task {task_path}: {exc}", file=sys.stderr)
        return 1

    root = Path(repo_root) if repo_root is not None else loader.find_repo_root(task.path.parent)
    network = NetworkPolicy.INHERITED if allow_network else NetworkPolicy.BLOCKED
    policy = SandboxPolicy(network=network)

    try:
        artifacts = code_artifacts(task, code_id)
        if not artifacts:
            raise SandboxError(f"task {task.spec.task_id!r} declares no runnable code artifact")
        executions = [
            (artifact, run_artifact(artifact, root, policy=policy, timeout=timeout))
            for artifact in artifacts
        ]
    except SandboxError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    trace = trace_module.new_trace(
        f"sandbox-{task.spec.task_id}",
        task_id=task.spec.task_id,
        bundle_id=task.bundle.bundle_id,
    )
    for artifact, result in executions:
        trace_module.record_execution(
            trace, result, code_id=artifact.artifact_id, include_timing=with_timing
        )

    if as_json:
        payload = {
            "task_id": task.spec.task_id,
            "executions": [
                result_to_dict(result, include_timing=with_timing) for _, result in executions
            ],
            "trace": [event.model_dump(mode="json") for event in trace.events],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            "\n\n".join(
                render_execution(task, artifact, result, with_timing=with_timing)
                for artifact, result in executions
            )
        )

    if out_dir is not None:
        path = Path(out_dir) / f"{task.spec.task_id}.sandbox.jsonl"
        print(f"\nwrote {trace_module.write_trace(trace, path)}", file=sys.stderr)
    return 0


def add_sandbox_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``run-sandbox`` flags."""
    parser.add_argument("--task", required=True, metavar="PATH", help="Path to a task YAML/JSON.")
    parser.add_argument(
        "--code-id", metavar="ID", default=None, help="Run only this code artifact."
    )
    parser.add_argument(
        "--out",
        metavar="DIR",
        default=None,
        help="Write <task_id>.sandbox.jsonl to this directory.",
    )
    parser.add_argument("--json", action="store_true", help="Print the execution(s) as JSON.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        metavar="S",
        help="Wall-clock timeout, overriding the artifact's declared timeout_seconds.",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Do not install the in-process socket guard. The child then has whatever "
        "network access the host grants it; the trace records that it was not blocked.",
    )
    parser.add_argument(
        "--with-timing",
        action="store_true",
        help="Record the wall-clock duration. Excluded by default: it is the one value "
        "that makes a trace non-reproducible.",
    )


def run_cli(argv: list[str]) -> int:
    """Parse ``run-sandbox`` arguments and run. Shared by the CLI and the script."""
    parser = argparse.ArgumentParser(
        prog="claimverifier run-sandbox",
        description="Execute a task's fixture scripts in the controlled sandbox (offline).",
    )
    add_sandbox_arguments(parser)
    args = parser.parse_args(argv)
    return sandbox_and_report(
        args.task,
        out_dir=args.out,
        as_json=args.json,
        code_id=args.code_id,
        timeout=args.timeout,
        allow_network=args.allow_network,
        with_timing=args.with_timing,
    )


def main(argv: list[str] | None = None) -> int:
    return run_cli(argv if argv is not None else sys.argv[1:])


__all__ = [
    "KILL_GRACE_SECONDS",
    "MARKER_FILENAME",
    "NETWORK_LOG_FILENAME",
    "ExecutionResult",
    "SandboxError",
    "SandboxScriptRunner",
    "ScriptRunner",
    "add_sandbox_arguments",
    "code_artifacts",
    "main",
    "render_execution",
    "result_to_dict",
    "run_artifact",
    "run_cli",
    "sandbox_and_report",
]
