"""``scv.episodes`` — a claim verification as a controllable, replayable unit.

The consumer role: a control benchmark that wants to re-run a recorded unit of work and
ask whether it still does the same thing. This is the one format with an **import**
direction, and it is where the contract stops being a shape and starts being a claim that
can be false. :func:`replay` re-runs an episode and says whether the pipeline still
reaches the verdict the episode recorded.

An episode pins four things
---------------------------
=================  ===========================================================
``task``           which task, repo-relative, and the hash of the task file
``inputs``         every artifact of its bundle, by ``artifact_id`` and hash
``controls``       the knobs that can move a verdict
``recorded``       the verdict the pipeline reached, and its confidence
=================  ===========================================================

plus ``trace_content_hash``: the SHA-256 of the trace the run wrote. Traces are
byte-stable across re-runs and output directories (Milestone 8), so that digest is a real
pin rather than a courtesy.

The four replay outcomes are not interchangeable
------------------------------------------------
==================  =========================================================
``reproduced``      same inputs, same verdict
``drifted``         same inputs, **different verdict** — the pipeline changed
``inputs_changed``  a fixture, a paper, or the task file is not the bytes the
                    episode recorded, so the verdict is not comparable and no
                    re-run is attempted
``missing_task``    the task file is gone
==================  =========================================================

Only ``drifted`` is a statement about the *pipeline*. Collapsing the other three into
"failed" would let an edited CSV read as a code regression, which is precisely the
mistake a replay harness exists to prevent. :func:`gate` therefore fails a replay on any
status other than ``reproduced``, but the rendered report says which.

Verdict equality is the gate; the trace digest is stricter
-----------------------------------------------------------
``trace_digest_matches`` is reported for every replayed episode and gated only under
``--strict``. Reword one ``because`` string in the scoring rules and every trace's bytes
change while every verdict stands; that is a fact worth seeing and not, on its own, a
regression. The same asymmetry the smoke suite draws between a wrong verdict and a
conservative miss (``docs/SCORING.md``) applies here.

What a 1.3 trace does not record
--------------------------------
A trace records what the pipeline *computed*, not how an operator *invoked* it. None of
the four ``controls`` appears in it. ``execute`` is recovered from the one artifact that
does record it — a suite ``summary.json``'s ``suite.scripts_executed`` — and
:func:`build` **refuses** to export if the operator's declared ``--no-execute`` disagrees
with it. The other three are taken from the operator's flags and default to the
pipeline's defaults. A wrongly declared control does not silently lie: replaying it
reports ``drifted`` and names the field. Recording the controls in the trace (a schema
1.4 event) would remove the assumption entirely; see ``docs/INTEGRATIONS.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field, ValidationError

from ..artifacts import hashing, loader
from ..reports.reader import TRACE_SUFFIX
from ..scoring.verdict import verify_task
from .envelope import IntegrationError, _Model, read
from .records import (
    CODE,
    DATASET,
    PAPER,
    ArtifactRef,
    Controls,
    ExportContext,
    Verdict,
    repo_relative,
)
from .run import LoadedRun, load_run, require_suite, run_dir_of, task_id_of

#: The format this module writes, and the version of its contract.
FORMAT = "scv.episodes"
VERSION = "1.0"

#: The consumer role this format is shaped for.
CONSUMER = "agent-control-bench"

#: What a replay concluded. Only ``DRIFTED`` is a statement about the pipeline.
REPRODUCED = "reproduced"
DRIFTED = "drifted"
INPUTS_CHANGED = "inputs_changed"
MISSING_TASK = "missing_task"
REPLAY_STATUSES = (REPRODUCED, DRIFTED, INPUTS_CHANGED, MISSING_TASK)


class TaskRef(_Model):
    """Which task an episode replays, and the exact bytes of its definition."""

    task_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    family: str = Field(min_length=1)
    title: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)


class Episode(_Model):
    """One claim verification, recorded so it can be run again and compared."""

    episode_id: str = Field(min_length=1)
    task: TaskRef
    controls: Controls
    inputs: list[ArtifactRef] = Field(default_factory=list)
    recorded: Verdict
    trace: str = Field(min_length=1)
    trace_content_hash: str = Field(min_length=1)


class Payload(_Model):
    """Every episode in a run, in the run's declared order."""

    episodes: list[Episode] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def artifact_refs(task: loader.LoadedTask) -> list[ArtifactRef]:
    """Every content-hashed artifact of a task's bundle, papers included.

    A paper has no ``path``: its passages are inlined in the task file, and its hash is
    taken over that text. Pinning it anyway means an edited passage is caught even though
    no file beside the task file changed.
    """
    bundle = task.bundle
    refs: list[ArtifactRef] = []
    groups = ((PAPER, bundle.papers), (DATASET, bundle.datasets), (CODE, bundle.code_files))
    for kind, artifacts in groups:
        for artifact in artifacts:
            if artifact.content_hash is None:
                continue
            path = getattr(artifact, "path", None)
            refs.append(
                ArtifactRef(
                    artifact_id=artifact.artifact_id,
                    kind=kind,
                    path=Path(path).as_posix() if path else None,
                    content_hash=artifact.content_hash,
                )
            )
    return refs


def controls_for(run: LoadedRun, declared: Controls) -> Controls:
    """The controls the run was made under, cross-checked where an artifact records them.

    A suite ``summary.json`` records ``scripts_executed``. If it disagrees with the
    operator's ``--no-execute``, the export is refused: an episode whose ``execute`` is
    wrong replays a different experiment.
    """
    suite = run.suite or {}
    if "scripts_executed" not in suite:
        return declared
    executed = bool(suite["scripts_executed"])
    if executed != declared.execute:
        fix = "drop --no-execute" if executed else "pass --no-execute"
        raise IntegrationError(
            f"{run.run_dir}: summary.json says the fixture scripts were "
            f"{'executed' if executed else 'not executed'}, but this export declares "
            f"execute={declared.execute}. An episode whose controls misdescribe the run "
            f"replays a different experiment — {fix} to match it"
        )
    return Controls(
        execute=executed,
        use_declared_source=declared.use_declared_source,
        abs_tol=declared.abs_tol,
        rel_tol=declared.rel_tol,
    )


def build(ctx: ExportContext) -> Payload:
    """Every claim in a run, as a replayable episode. Reads the run *and* its task files."""
    run = load_run(run_dir_of(ctx))
    require_suite(run)
    controls = controls_for(run, ctx.controls)

    tasks_dir = ctx.tasks_dir or (ctx.repo_root / "tasks")
    try:
        index = loader.index_tasks(tasks_dir)
    except loader.SuiteLoadError as exc:
        raise IntegrationError(f"{tasks_dir}: cannot index tasks: {exc}") from exc

    episodes: list[Episode] = []
    for report in run.reports:
        task_id = task_id_of(report)
        task_path = index.get(task_id)
        if task_path is None:
            raise IntegrationError(
                f"{run.run_dir}: the run has a trace for {task_id!r}, but no task under "
                f"{tasks_dir}/ declares that task_id. An episode must name a task that exists"
            )
        try:
            task = loader.load_task(task_path, ctx.repo_root)
        except (loader.TaskLoadError, OSError) as exc:
            raise IntegrationError(f"{task_path}: cannot load task: {exc}") from exc

        episodes.append(
            Episode(
                episode_id=task_id,
                task=TaskRef(
                    task_id=task.spec.task_id,
                    path=repo_relative(task_path, ctx.repo_root),
                    family=task.spec.family,
                    title=task.spec.title,
                    content_hash=hashing.hash_file(task_path),
                ),
                controls=controls,
                inputs=artifact_refs(task),
                recorded=Verdict.of(report.result),
                trace=report.trace_path.name,
                trace_content_hash=hashing.hash_file(report.trace_path),
            )
        )
    return Payload(episodes=episodes)


# ---------------------------------------------------------------------------
# Import: reading episodes back, and replaying them
# ---------------------------------------------------------------------------


def load_episodes(path: str | Path) -> tuple[Episode, ...]:
    """Read an episodes document, refusing anything that is not one of ours."""
    envelope = read(path, expect=FORMAT, expect_version=VERSION)
    try:
        return tuple(Payload.model_validate(envelope.payload).episodes)
    except ValidationError as exc:
        raise IntegrationError(f"{path}: malformed {FORMAT} payload: {exc}") from exc


@dataclass(frozen=True)
class ReplayOutcome:
    """What replaying one episode concluded, and everything the conclusion rests on."""

    episode_id: str
    status: str
    diffs: tuple[str, ...] = ()
    trace_digest_matches: bool | None = None

    @property
    def ok(self) -> bool:
        """The verdict is the one the episode recorded. Says nothing about the bytes."""
        return self.status == REPRODUCED

    def to_dict(self) -> dict[str, object]:
        return {
            "episode_id": self.episode_id,
            "status": self.status,
            "diffs": list(self.diffs),
            "trace_digest_matches": self.trace_digest_matches,
        }


def _input_diffs(episode: Episode, task: loader.LoadedTask) -> list[str]:
    """How the task's artifacts differ from the bytes the episode pinned."""
    diffs: list[str] = []
    recorded = {ref.artifact_id: ref for ref in episode.inputs}
    for artifact_id, ref in sorted(recorded.items()):
        found = task.content_hashes.get(artifact_id)
        if found is None:
            diffs.append(f"artifact {artifact_id!r} is no longer in the bundle")
        elif found != ref.content_hash:
            diffs.append(
                f"artifact {artifact_id!r} changed: recorded {ref.content_hash}, found {found}"
            )
    for artifact_id in sorted(set(task.content_hashes) - set(recorded)):
        diffs.append(f"artifact {artifact_id!r} was added to the bundle after this episode")
    return diffs


def _verdict_diffs(recorded: Verdict, replayed: Verdict) -> list[str]:
    """Field-by-field disagreement between the recorded verdict and the replayed one."""
    diffs = [
        f"{field}: recorded {getattr(recorded, field).value}, "
        f"replayed {getattr(replayed, field).value}"
        for field in ("support_label", "reproduction_status", "failure_mode")
        if getattr(recorded, field) is not getattr(replayed, field)
    ]
    if recorded.confidence != replayed.confidence:
        diffs.append(
            f"confidence: recorded {recorded.confidence}, replayed {replayed.confidence}"
        )
    return diffs


def replay_episode(episode: Episode, *, repo_root: str | Path | None = None) -> ReplayOutcome:
    """Re-run one episode under its recorded controls and compare.

    This is the only function in the package that drives the pipeline — every export is a
    function of artifacts already on disk. Under ``execute=True`` it runs the task's
    fixture scripts, in the controlled sandbox, exactly as the original run did.
    """
    root = Path(repo_root) if repo_root is not None else loader.find_repo_root(Path.cwd())
    task_path = root / episode.task.path
    if not task_path.is_file():
        return ReplayOutcome(
            episode.episode_id,
            MISSING_TASK,
            (f"task file not found: {episode.task.path}",),
        )

    diffs: list[str] = []
    found_hash = hashing.hash_file(task_path)
    if found_hash != episode.task.content_hash:
        diffs.append(
            f"task file {episode.task.path} changed: recorded "
            f"{episode.task.content_hash}, found {found_hash}"
        )
    try:
        task = loader.load_task(task_path, root)
    except (loader.TaskLoadError, ValidationError, OSError) as exc:
        return ReplayOutcome(
            episode.episode_id, INPUTS_CHANGED, (*diffs, f"task no longer loads: {exc}")
        )

    diffs += _input_diffs(episode, task)
    if diffs:
        return ReplayOutcome(episode.episode_id, INPUTS_CHANGED, tuple(diffs))

    controls = episode.controls
    with tempfile.TemporaryDirectory(prefix="scv-replay-") as tmp:
        _task, _claim, scored = verify_task(
            task_path,
            out_dir=tmp,
            repo_root=root,
            execute=controls.execute,
            use_declared_source=controls.use_declared_source,
            abs_tol=controls.abs_tol,
            rel_tol=controls.rel_tol,
        )
        trace = Path(tmp) / f"{task.spec.task_id}{TRACE_SUFFIX}"
        digest_matches = hashing.hash_file(trace) == episode.trace_content_hash

    replayed = Verdict.of(scored.result)
    verdict_diffs = _verdict_diffs(episode.recorded, replayed)
    status = REPRODUCED if not verdict_diffs else DRIFTED
    return ReplayOutcome(episode.episode_id, status, tuple(verdict_diffs), digest_matches)


def replay(
    episodes: tuple[Episode, ...] | list[Episode],
    *,
    repo_root: str | Path | None = None,
) -> tuple[ReplayOutcome, ...]:
    """Replay every episode, in order."""
    return tuple(replay_episode(episode, repo_root=repo_root) for episode in episodes)


def gate(outcomes: tuple[ReplayOutcome, ...], *, strict: bool = False) -> bool:
    """Did the replay pass? Verdict equality always; trace bytes only under ``strict``."""
    if not all(outcome.ok for outcome in outcomes):
        return False
    if strict:
        return all(outcome.trace_digest_matches for outcome in outcomes)
    return True


# ---------------------------------------------------------------------------
# Rendering and CLI
# ---------------------------------------------------------------------------

_MARK = {REPRODUCED: "ok  ", DRIFTED: "DRIFT", INPUTS_CHANGED: "input", MISSING_TASK: "gone "}


def render_replay(outcomes: tuple[ReplayOutcome, ...], *, strict: bool = False) -> str:
    """Render the replay: one line per episode, then the gate and why it decided."""
    passed = gate(outcomes, strict=strict)
    digests = [o for o in outcomes if o.trace_digest_matches is False]

    lines = [
        "scientific-claim-verifier — episode replay",
        "=" * 41,
        f"Episodes        : {len(outcomes)}",
        f"Gate            : {'verdict + trace bytes (--strict)' if strict else 'verdict only'}",
        "",
        "Per-episode status (recorded verdict vs. replayed):",
    ]
    for outcome in outcomes:
        mark = _MARK[outcome.status]
        lines.append(f"  [{mark:<5}] {outcome.episode_id:<24} {outcome.status}")
        for diff in outcome.diffs:
            lines.append(f"{'':<11}- {diff}")

    lines += ["", f"Reproduced      : {sum(1 for o in outcomes if o.ok)}/{len(outcomes)}"]
    if digests:
        lines += [
            f"Trace bytes     : {len(digests)} episode(s) reached the recorded verdict by a "
            "different trace",
            "  " + ", ".join(o.episode_id for o in digests),
            "  (a reworded rule changes a trace's bytes without changing its verdict; this is",
            "   gated only under --strict)",
        ]
    lines += ["", f"Result          : {'PASS' if passed else 'FAIL'}"]
    if not passed:
        lines.append(
            "  Only `drifted` is a statement about the pipeline. `inputs_changed` means a "
            "fixture,\n  a paper, or the task file is not the bytes this episode recorded."
        )
    return "\n".join(lines)


def replay_and_report(
    episodes_path: str | Path,
    *,
    repo_root: str | Path | None = None,
    as_json: bool = False,
    strict: bool = False,
    enforce_gate: bool = True,
) -> int:
    """Load an episodes document, replay it, report. Returns a process exit code."""
    try:
        loaded = load_episodes(episodes_path)
    except IntegrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not loaded:
        print(f"error: {episodes_path}: no episodes to replay", file=sys.stderr)
        return 1

    outcomes = replay(loaded, repo_root=repo_root)
    passed = gate(outcomes, strict=strict)

    if as_json:
        document = {
            "episodes": [outcome.to_dict() for outcome in outcomes],
            "strict": strict,
            "ok": passed,
        }
        print(json.dumps(document, indent=2, sort_keys=True))
    else:
        print(render_replay(outcomes, strict=strict))
    return 0 if passed or not enforce_gate else 1


def add_replay_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the ``replay`` flags. Shared by the CLI and any script."""
    parser.add_argument(
        "--episodes",
        required=True,
        metavar="PATH",
        help=f"An {FORMAT} document, as written by `claimverifier export --format episodes`.",
    )
    parser.add_argument(
        "--repo-root",
        metavar="DIR",
        default=None,
        help="Resolve each episode's task path against DIR (default: this repository).",
    )
    parser.add_argument("--json", action="store_true", help="Print the replay result as JSON.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also require each replayed trace to be byte-identical to the recorded one.",
    )
    parser.add_argument(
        "--no-gate",
        action="store_true",
        help="Report drift but always exit 0 (the gate is on by default).",
    )


def run_cli(argv: list[str]) -> int:
    """Parse ``replay`` arguments and run. Shared by the CLI and any script."""
    parser = argparse.ArgumentParser(
        prog="claimverifier replay",
        description="Re-run recorded episodes and check the pipeline still agrees with them.",
    )
    add_replay_arguments(parser)
    args = parser.parse_args(argv)
    return replay_and_report(
        args.episodes,
        repo_root=args.repo_root,
        as_json=args.json,
        strict=args.strict,
        enforce_gate=not args.no_gate,
    )


def main(argv: list[str] | None = None) -> int:
    return run_cli(argv if argv is not None else sys.argv[1:])


__all__ = [
    "CONSUMER",
    "DRIFTED",
    "FORMAT",
    "INPUTS_CHANGED",
    "MISSING_TASK",
    "REPLAY_STATUSES",
    "REPRODUCED",
    "TRACE_SUFFIX",
    "VERSION",
    "Episode",
    "Payload",
    "ReplayOutcome",
    "TaskRef",
    "add_replay_arguments",
    "artifact_refs",
    "build",
    "controls_for",
    "gate",
    "load_episodes",
    "main",
    "render_replay",
    "replay",
    "replay_and_report",
    "replay_episode",
    "run_cli",
]
