"""``scv.runnable-tasks`` — a verification task as a unit a code-agent runtime can run.

The consumer role: a runtime that materialises files in a working directory, runs a
command, and decides whether the command succeeded. This format gives it exactly that,
and nothing it would have to interpret:

- ``argv`` — the command, as a list. No shell, no quoting, no ``&&``.
- ``files`` — every file the command reads, repo-relative and content-hashed. Papers are
  not listed: their passages are **inlined in the task file**, so the task file's own
  hash covers them.
- ``expected`` — the success criterion.
- ``controls`` — the flags ``argv`` already encodes, restated as data, so a runtime can
  vary one without parsing a command line.

The trace contract
------------------
``docs/PLAN.md`` asks this format to "export traces in a compatible JSONL shape". The
trace *is* JSONL, and it already has the shape; what a consumer lacks is a written
guarantee about it. :class:`TraceContract` states the five properties Milestones 6–9 made
true — one JSON object per line, sorted keys, contiguous ``seq``, no wall clock, and the
same bytes from run to run — and names the event kinds a stream may contain. Those are
claims about a real artifact rather than an aspiration, so ``tests/test_integrations.py``
re-derives every one of them from a trace this repo actually produced.

Gold
----
``expected.verdict`` is the task's **hand-authored gold outcome**. It is the success
criterion a *runtime* checks, and it must never be shown to a system being asked to solve
the task. ``--hide-gold`` drops it and leaves ``exit_code`` alone.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from ..artifacts import hashing, loader
from ..schemas import SCHEMA_VERSION
from ..scoring.verdict import SCORING_EVENT_KINDS
from .envelope import IntegrationError, _Model
from .records import CODE, DATASET, Controls, ExportContext, Verdict, repo_relative

#: The format this module writes, and the version of its contract.
FORMAT = "scv.runnable-tasks"
VERSION = "1.0"

#: The consumer role this format is shaped for.
CONSUMER = "code-agent runtime"

#: Roles a listed file plays. ``task`` is the task definition itself.
TASK = "task"
FILE_ROLES = (TASK, DATASET, CODE)

#: Where a trace lands, in terms of the ``--out`` directory the runtime supplies.
TRACE_PATH_TEMPLATE = "<out>/<task_id>.trace.jsonl"

#: JSONL, one JSON object per line.
TRACE_MEDIA_TYPE = "application/x-ndjson"

#: What a consumer may rely on about a trace. Each is asserted against a real trace in
#: ``tests/test_integrations.py``; a guarantee nobody checks is a comment.
TRACE_GUARANTEES = (
    "one JSON object per line, UTF-8, newline-separated",
    "object keys are sorted within every line",
    "every line carries a contiguous `seq`, starting at 0",
    "every line's `kind` is one of `event_kinds`",
    "no value is read from the wall clock or an RNG",
    "the bytes are identical across re-runs and across output directories",
)


class FileRef(_Model):
    """One file the command reads, pinned by its bytes."""

    path: str = Field(min_length=1)
    role: str = Field(min_length=1)
    artifact_id: str | None = None
    content_hash: str = Field(min_length=1)


class Expected(_Model):
    """The success criterion. ``verdict`` is gold, and is absent under ``--hide-gold``."""

    exit_code: int = 0
    verdict: Verdict | None = None


class TraceContract(_Model):
    """What the command leaves behind, and what a consumer may rely on about it."""

    path_template: str
    media_type: str
    schema_version: str
    event_kinds: list[str]
    guarantees: list[str]


class RunnableTask(_Model):
    """One verification task, as something to run."""

    task_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str | None = None
    claim_id: str = Field(min_length=1)
    claim_text: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    argv: list[str] = Field(min_length=1)
    workdir: str = "."
    files: list[FileRef] = Field(default_factory=list)
    controls: Controls = Field(default_factory=Controls)
    expected: Expected = Field(default_factory=Expected)


class Payload(_Model):
    """Every runnable task, in the order the suite declares (or filename order)."""

    tasks: list[RunnableTask] = Field(default_factory=list)
    trace: TraceContract


def instruction_for(task: loader.LoadedTask) -> str:
    """The natural-language instruction for one task. A pure function of the task file."""
    spec = task.spec
    return (
        f"Verify the claim {spec.claim.claim_id!r} — "
        f"{spec.claim.claim_text.strip()} — against the artifacts bundled with task "
        f"{spec.task_id!r}, using the offline claimverifier pipeline. Report the support "
        "label, the reproduction status, and the failure mode. Do not fetch anything from "
        "the network; every artifact the claim needs is committed in this repository."
    )


def argv_for(task_path: str, controls: Controls) -> list[str]:
    """The command that verifies one task. The runtime appends ``--out DIR`` for a trace."""
    argv = ["claimverifier", "verify", "--task", task_path]
    if not controls.execute:
        argv.append("--no-execute")
    if not controls.use_declared_source:
        argv.append("--no-declared-source")
    if controls.abs_tol is not None:
        argv += ["--abs-tol", repr(controls.abs_tol)]
    if controls.rel_tol is not None:
        argv += ["--rel-tol", repr(controls.rel_tol)]
    return argv


def files_of(task: loader.LoadedTask, task_path: str, root: Path) -> list[FileRef]:
    """The task file and every fixture file it references, content-hashed.

    Papers carry no ``path``: their passages are inlined in the task file, which is
    listed, so the paper's bytes are covered by the task file's hash.
    """
    files = [
        FileRef(path=task_path, role=TASK, content_hash=hashing.hash_file(root / task_path))
    ]
    for kind, artifacts in (
        (DATASET, task.bundle.datasets),
        (CODE, task.bundle.code_files),
    ):
        for artifact in artifacts:
            if artifact.path is None or artifact.content_hash is None:
                continue
            files.append(
                FileRef(
                    path=Path(artifact.path).as_posix(),
                    role=kind,
                    artifact_id=artifact.artifact_id,
                    content_hash=artifact.content_hash,
                )
            )
    return files


def task_paths(ctx: ExportContext) -> list[Path]:
    """The task files to export, in the suite's declared order when a suite is named."""
    tasks_dir = ctx.tasks_dir or (ctx.repo_root / "tasks")
    if ctx.suite_path is None:
        return loader.discover_task_files(tasks_dir)
    try:
        return loader.load_suite(ctx.suite_path, tasks_dir).task_paths
    except (loader.SuiteLoadError, loader.TaskLoadError, OSError) as exc:
        raise IntegrationError(f"{ctx.suite_path}: cannot load suite: {exc}") from exc


def trace_contract() -> TraceContract:
    """The JSONL guarantee, as this build makes it."""
    return TraceContract(
        path_template=TRACE_PATH_TEMPLATE,
        media_type=TRACE_MEDIA_TYPE,
        schema_version=SCHEMA_VERSION,
        event_kinds=list(SCORING_EVENT_KINDS),
        guarantees=list(TRACE_GUARANTEES),
    )


def build(ctx: ExportContext) -> Payload:
    """Render every task under ``tasks_dir`` as a runnable unit."""
    tasks: list[RunnableTask] = []
    for path in task_paths(ctx):
        try:
            task = loader.load_task(path, ctx.repo_root)
        except (loader.TaskLoadError, OSError) as exc:
            raise IntegrationError(f"{path}: cannot load task: {exc}") from exc

        spec = task.spec
        relative = repo_relative(path, ctx.repo_root)
        expected = Expected(exit_code=0)
        if not ctx.hide_gold:
            expected = Expected(
                exit_code=0,
                verdict=Verdict(
                    support_label=spec.expected.support_label,
                    reproduction_status=spec.expected.reproduction_status,
                    failure_mode=spec.expected.failure_mode,
                ),
            )
        tasks.append(
            RunnableTask(
                task_id=spec.task_id,
                family=spec.family,
                title=spec.title,
                description=spec.description,
                claim_id=spec.claim.claim_id,
                claim_text=spec.claim.claim_text.strip(),
                instruction=instruction_for(task),
                argv=argv_for(relative, ctx.controls),
                files=files_of(task, relative, ctx.repo_root),
                controls=ctx.controls,
                expected=expected,
            )
        )
    return Payload(tasks=tasks, trace=trace_contract())


__all__ = [
    "CONSUMER",
    "FILE_ROLES",
    "FORMAT",
    "TASK",
    "TRACE_GUARANTEES",
    "TRACE_MEDIA_TYPE",
    "TRACE_PATH_TEMPLATE",
    "VERSION",
    "Expected",
    "FileRef",
    "Payload",
    "RunnableTask",
    "TraceContract",
    "argv_for",
    "build",
    "files_of",
    "instruction_for",
    "task_paths",
    "trace_contract",
]
