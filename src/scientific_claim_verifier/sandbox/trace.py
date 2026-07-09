"""The trace record: one sandboxed execution, as an ordered JSONL event stream.

Milestone 6. A verdict a reader cannot re-derive is an opinion. The trace is what
makes a reproduction result auditable: it names the policy the script ran under, the
bytes that ran, what came back, and how the process ended — in that order, because a
number means nothing without the conditions that produced it.

Four events per execution, always in this order:

============================  ==============================================
``sandbox.policy``            The full :meth:`SandboxPolicy.describe` snapshot.
``sandbox.exec``              Command, script name, content hash, artifact id.
``sandbox.output``            Captured stdout and stderr, truncated, redacted.
``sandbox.result``            Exit code, signal, timeout, network attempts,
                              files written.
============================  ==============================================

A fifth, ``sandbox.timing``, is appended **only** when the caller asks for it.

Why timing is opt-in
--------------------
``RunTrace.to_jsonl`` sorts keys so a trace is byte-reproducible, and ``CLAUDE.md``
requires determinism-critical output to avoid the wall clock. Wall-clock duration is
the one fact about an execution that cannot be reproduced — recording it by default
would make every trace differ from every other, and the diff between two runs would
stop being a signal. So the runner measures it, the report prints it on request, and
the trace omits it unless ``include_timing=True``. Nothing else in an event comes
from the clock, an RNG, or an absolute path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..schemas import RunTrace

if TYPE_CHECKING:  # avoids a cycle: `runner` imports this module at runtime.
    from .runner import ExecutionResult

#: Every event kind this module emits, in emission order.
SANDBOX_EVENT_KINDS = (
    "sandbox.policy",
    "sandbox.exec",
    "sandbox.output",
    "sandbox.result",
    "sandbox.timing",
)

# Stated on the policy event of every trace, so an auditor reading only the JSONL
# still learns what kind of execution this was.
POLICY_MESSAGE = "controlled fixture execution under a recorded policy — not a security boundary"

TIMING_MESSAGE = "wall-clock duration — volatile; omitted from the trace unless requested"


def new_trace(run_id: str, *, task_id: str | None = None, bundle_id: str | None = None) -> RunTrace:
    """An empty :class:`~scientific_claim_verifier.schemas.RunTrace` for a sandbox run.

    ``created_at`` is left unset: the trace's content is deterministic, and a caller
    that wants a timestamp supplies one.
    """
    return RunTrace(run_id=run_id, task_id=task_id, bundle_id=bundle_id)


def outcome_message(result: ExecutionResult) -> str:
    """A stable, human-readable summary of how the process ended."""
    if result.timed_out:
        return f"timed out after {result.policy.get('timeout_seconds')}s; process group killed"
    if result.signal is not None:
        return f"killed by signal {result.signal}"
    return f"exited {result.exit_code}"


def record_execution(
    trace: RunTrace,
    result: ExecutionResult,
    *,
    code_id: str | None = None,
    include_timing: bool = False,
) -> RunTrace:
    """Append one execution's events to ``trace`` (mutated in place) and return it."""
    trace.add_event("sandbox.policy", POLICY_MESSAGE, policy=dict(result.policy))
    trace.add_event(
        "sandbox.exec",
        " ".join(result.command),
        command=list(result.command),
        script=result.script,
        script_hash=result.script_hash,
        code_id=code_id,
    )
    trace.add_event(
        "sandbox.output",
        "captured stdout/stderr; sandbox paths redacted, output truncated to the policy cap",
        stdout=result.stdout,
        stderr=result.stderr,
    )
    trace.add_event(
        "sandbox.result",
        outcome_message(result),
        exit_code=result.exit_code,
        signal=result.signal,
        timed_out=result.timed_out,
        ok=result.ok,
        network_attempts=list(result.network_attempts),
        files_written=list(result.files_written),
    )
    if include_timing:
        trace.add_event("sandbox.timing", TIMING_MESSAGE, duration_seconds=result.duration_seconds)
    return trace


def write_trace(trace: RunTrace, path: str | Path) -> Path:
    """Write ``trace``'s events as JSONL to ``path``, creating parent directories."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = trace.to_jsonl()
    target.write_text(f"{body}\n" if body else "", encoding="utf-8")
    return target


def read_trace(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSONL trace back into a list of event dicts, in order."""
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


__all__ = [
    "POLICY_MESSAGE",
    "SANDBOX_EVENT_KINDS",
    "TIMING_MESSAGE",
    "new_trace",
    "outcome_message",
    "read_trace",
    "record_execution",
    "write_trace",
]
