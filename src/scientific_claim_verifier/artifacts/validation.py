"""Fixture validation: check every task and suite under ``tasks/`` against the schema.

This is the engine behind ``claimverifier validate-fixtures`` and
``scripts/01_validate_fixtures.py`` (Milestone 2; suites added in Milestone 8). For
each file it accumulates *all* problems rather than stopping at the first, so a single
run tells you everything wrong with a fixture. Two severities:

- **errors** — the task is invalid: unparseable, fails the schema, references a
  missing/out-of-tree fixture file, a dataset whose CSV shape disagrees with its
  declared shape, or an evidence link / source passage that resolves to nothing.
  A suite is invalid if it fails the schema or names a ``task_id`` that no task
  under ``tasks/`` declares.
- **warnings** — the file loads but something is worth flagging: a fixture file
  outside ``data/fixtures``, a filename that does not match its ``task_id`` /
  ``suite_id``, or a code-reproduction task with no expected value to score against.

A run is *green* (exit 0) when no file has an error. Warnings never fail the run.
Purely local and offline: it reads task files and small committed fixtures only.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from .. import schemas as S
from . import loader

DEFAULT_TASKS_DIR = "tasks"

# What a validated file turned out to be. Recorded so the report can say so.
TASK = "task"
SUITE = "suite"

# Claim types for which the pipeline will attempt a reproduction; used to warn
# when such a task ships without an expected value to score against.
_REPRODUCIBLE_TYPES = {S.ClaimType.CODE_REPRODUCTION, S.ClaimType.DATASET}


@dataclass
class TaskValidation:
    """The validation outcome for a single task or suite file."""

    path: Path
    task_id: str | None = None
    kind: str = TASK
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the file has no errors (warnings are allowed)."""
        return not self.errors


@dataclass
class ValidationReport:
    """The aggregate outcome across a directory of task and suite files."""

    tasks_dir: Path
    results: list[TaskValidation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def n_ok(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def n_failed(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    @property
    def n_warnings(self) -> int:
        return sum(len(r.warnings) for r in self.results)

    @property
    def n_tasks(self) -> int:
        return sum(1 for r in self.results if r.kind == TASK)

    @property
    def n_suites(self) -> int:
        return sum(1 for r in self.results if r.kind == SUITE)


# ---------------------------------------------------------------------------
# Per-task checks
# ---------------------------------------------------------------------------


def _resolve_evidence(bundle: S.ArtifactBundle, link: S.EvidenceLink) -> bool:
    """True if ``link``'s ``target_id`` resolves to an artifact in ``bundle``."""
    if link.kind is S.EvidenceKind.PASSAGE:
        return any(p.passage(link.target_id) is not None for p in bundle.papers)
    if link.kind is S.EvidenceKind.TABLE:
        return bundle.table(link.target_id) is not None
    if link.kind is S.EvidenceKind.FIGURE:
        return bundle.figure(link.target_id) is not None
    if link.kind is S.EvidenceKind.DATASET:
        return bundle.dataset(link.target_id) is not None
    if link.kind is S.EvidenceKind.CODE:
        return bundle.code(link.target_id) is not None
    return False


def _check_loaded_spec(
    spec: loader.TaskSpec, path: Path, repo_root: Path, result: TaskValidation
) -> None:
    """Run the semantic checks that require a validated ``TaskSpec``."""
    bundle = spec.artifacts

    # Filename should match the task_id (soft convention, aids navigation).
    if path.stem != spec.task_id:
        result.warnings.append(
            f"filename stem {path.stem!r} does not match task_id {spec.task_id!r}"
        )

    # Dataset/code fixture files: exist, stay in-tree, and (warn) live under
    # data/fixtures. Datasets additionally have their CSV shape cross-checked.
    for artifact in (*bundle.datasets, *bundle.code_files):
        if artifact.path is None:
            continue
        if not loader.is_under_fixture_root(artifact.path):
            result.warnings.append(
                f"fixture path {artifact.path!r} is not under {loader.FIXTURE_ROOT}/"
            )
        try:
            resolved = loader.resolve_fixture_path(artifact.path, repo_root)
        except loader.TaskLoadError as exc:
            result.errors.append(str(exc))
            continue
        if not resolved.is_file():
            result.errors.append(f"fixture file not found: {artifact.path}")
            continue
        if isinstance(artifact, S.DatasetArtifact) and resolved.suffix.lower() == ".csv":
            for problem in loader.check_csv_shape(
                resolved, artifact.columns, artifact.n_rows
            ):
                result.errors.append(f"dataset {artifact.artifact_id!r}: {problem}")

    # The claim's declared source passage must resolve to a real passage.
    if spec.claim.source_passage is not None:
        found = any(
            p.passage(spec.claim.source_passage) is not None for p in bundle.papers
        )
        if not found:
            result.errors.append(
                f"claim.source_passage {spec.claim.source_passage!r} is not a passage "
                "in any paper"
            )

    # The claim's declared source document must resolve to a real paper.
    if spec.claim.source_document_id is not None and bundle.paper(
        spec.claim.source_document_id
    ) is None:
        result.errors.append(
            f"claim.source_document_id {spec.claim.source_document_id!r} is not a paper"
        )

    # Every gold evidence link must resolve to an artifact in the bundle.
    for i, link in enumerate(spec.expected.evidence):
        if not _resolve_evidence(bundle, link):
            result.errors.append(
                f"expected.evidence[{i}] ({link.kind.value} {link.target_id!r}) "
                "does not resolve to any artifact"
            )

    # A reproducible claim should carry an expected value to score against.
    if spec.claim.claim_type in _REPRODUCIBLE_TYPES:
        has_expected = (
            spec.expected.claim.expected_value is not None
            or bool(bundle.expected_outputs)
        )
        if not has_expected:
            result.warnings.append(
                f"{spec.claim.claim_type.value} has no expected value "
                "(expected.claim.expected_value or artifacts.expected_outputs)"
            )


def validate_task_file(path: str | Path, repo_root: str | Path) -> TaskValidation:
    """Validate one task file, collecting every problem found."""
    task_path = Path(path)
    root = Path(repo_root)
    result = TaskValidation(path=task_path)

    try:
        text = task_path.read_text(encoding="utf-8")
    except OSError as exc:
        result.errors.append(f"cannot read file: {exc}")
        return result

    try:
        data = loader.parse_task_data(text, is_json=task_path.suffix.lower() == ".json")
    except loader.TaskLoadError as exc:
        result.errors.append(str(exc))
        return result
    except Exception as exc:  # yaml/json parse errors
        result.errors.append(f"parse error: {exc}")
        return result

    if isinstance(data, dict):
        result.task_id = data.get("task_id")

    try:
        spec = loader.TaskSpec.model_validate(data)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(part) for part in err["loc"])
            result.errors.append(f"schema: {loc}: {err['msg']}")
        return result

    result.task_id = spec.task_id
    _check_loaded_spec(spec, task_path, root, result)
    return result


def validate_suite_file(path: str | Path, tasks_dir: str | Path) -> TaskValidation:
    """Validate one suite file: its schema, its filename, and that its tasks exist."""
    suite_path = Path(path)
    result = TaskValidation(path=suite_path, kind=SUITE)

    try:
        text = suite_path.read_text(encoding="utf-8")
    except OSError as exc:
        result.errors.append(f"cannot read file: {exc}")
        return result

    try:
        data = loader.parse_task_data(text, is_json=suite_path.suffix.lower() == ".json")
    except Exception as exc:  # yaml/json parse errors, non-mapping documents
        result.errors.append(f"parse error: {exc}")
        return result

    result.task_id = data.get("suite_id") if isinstance(data, dict) else None

    try:
        spec = loader.SuiteSpec.model_validate(data)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(part) for part in err["loc"])
            result.errors.append(f"schema: {loc}: {err['msg']}")
        return result

    result.task_id = spec.suite_id
    if suite_path.stem != spec.suite_id:
        result.warnings.append(
            f"filename stem {suite_path.stem!r} does not match suite_id {spec.suite_id!r}"
        )

    try:
        index = loader.index_tasks(tasks_dir)
    except loader.SuiteLoadError as exc:
        result.errors.append(str(exc))
        return result

    for task_id in spec.task_ids:
        if task_id not in index:
            result.errors.append(
                f"task_ids: {task_id!r} matches no task under {Path(tasks_dir)}/"
            )
    return result


def validate_tasks(
    tasks_dir: str | Path = DEFAULT_TASKS_DIR, repo_root: str | Path | None = None
) -> ValidationReport:
    """Validate every task and suite under ``tasks_dir`` and return an aggregate report."""
    base = Path(tasks_dir)
    root = Path(repo_root) if repo_root is not None else loader.find_repo_root(base)
    report = ValidationReport(tasks_dir=base)

    task_files, suite_files = loader.discover_documents(base)
    for task_file in task_files:
        report.results.append(validate_task_file(task_file, root))
    for suite_file in suite_files:
        report.results.append(validate_suite_file(suite_file, base))
    return report


# ---------------------------------------------------------------------------
# Rendering + CLI entry point
# ---------------------------------------------------------------------------


def format_report(report: ValidationReport) -> str:
    """Render a validation report as a plain-text block."""
    lines = [
        "scientific-claim-verifier — fixture validation",
        "=" * 46,
        f"Tasks dir : {report.tasks_dir}",
    ]
    if not report.results:
        lines.append("")
        lines.append(f"No task files found under {report.tasks_dir}/ (nothing to validate).")
        return "\n".join(lines)

    lines.append("")
    for res in report.results:
        flag = "ok  " if res.ok else "FAIL"
        suffix = " (suite)" if res.kind == SUITE else ""
        lines.append(f"[{flag}] {res.path}{suffix}")
        for err in res.errors:
            lines.append(f"        error:   {err}")
        for warn in res.warnings:
            lines.append(f"        warning: {warn}")

    lines.append("")
    lines.append(
        f"Summary   : {report.n_ok} ok, {report.n_failed} failed, "
        f"{report.n_warnings} warning(s) across {report.n_tasks} task(s) "
        f"and {report.n_suites} suite(s)."
    )
    lines.append(f"Overall   : {'VALID' if report.ok else 'INVALID'}")
    return "\n".join(lines)


def run(argv: list[str] | None = None) -> int:
    """Validate fixtures and print the report; return 0 if valid, 1 otherwise."""
    args = list(argv) if argv is not None else []
    tasks_dir = args[0] if args else DEFAULT_TASKS_DIR
    report = validate_tasks(tasks_dir)
    print(format_report(report))
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    return run(argv if argv is not None else sys.argv[1:])


__all__ = [
    "DEFAULT_TASKS_DIR",
    "TASK",
    "SUITE",
    "TaskValidation",
    "ValidationReport",
    "validate_task_file",
    "validate_suite_file",
    "validate_tasks",
    "format_report",
    "run",
    "main",
]
