"""The on-disk task format and its loader.

A *task* is the unit the pipeline runs on: a claim plus the bundle of artifacts
it will be checked against, plus a *gold* record of what the answer should be
(used to score later milestones, never fed to them as input). Tasks live under
``tasks/`` as YAML (``.yaml``/``.yml``) or JSON; their referenced fixture files
live under ``data/fixtures/``.

This module defines the task schema (:class:`TaskSpec` and friends, all built on
the Milestone 1 models so the fixtures exercise the real contract) and
:func:`load_task`, which parses a task file, resolves and content-hashes its
referenced dataset/code files, and returns a validated :class:`LoadedTask`.

Input / gold separation
------------------------
The task's ``claim`` block is the claim *as authored* — id, text, type, and
where it comes from. It deliberately holds **no** extracted numeric fields: the
values an extractor should recover (``expected_value``, ``metrics``, …) live in
``expected.claim`` as the *gold* target. So loading a task never leaks the
answer to the extraction milestone (M3); it only supplies the input and,
separately, the yardstick.

Nothing here verifies a claim — loading and hashing only.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .. import schemas as S
from . import hashing

# File extensions recognised as task definitions.
TASK_SUFFIXES = (".yaml", ".yml", ".json")

# Fixture files must live under this repo-relative directory. Enforced so a task
# can only reference small committed fixtures, never arbitrary paths on disk.
FIXTURE_ROOT = "data/fixtures"


class TaskLoadError(Exception):
    """Raised when a task file cannot be parsed, resolved, or hashed."""


# ---------------------------------------------------------------------------
# Task-file schema (strict, like the Milestone 1 models)
# ---------------------------------------------------------------------------


class _TaskModel(BaseModel):
    """Shared config: reject unknown fields so a typo in a task fails loudly."""

    model_config = ConfigDict(extra="forbid")


class ClaimInput(_TaskModel):
    """The claim *as authored* — the pipeline's input, with no gold fields.

    Numeric/derived fields (``expected_value``, ``metrics``, operator, …) are
    intentionally absent: recovering them is the extractor's job (M3), and the
    targets live in :class:`GoldClaim`. ``source_passage`` names the passage ID
    that asserts the claim, when the author knows it.
    """

    claim_id: str = Field(min_length=1)
    claim_text: str = Field(min_length=1)
    claim_type: S.ClaimType
    source_document_id: str | None = None
    source_passage: str | None = None


class GoldClaim(_TaskModel):
    """The gold extraction target for a claim: what a correct extractor recovers.

    All fields are optional — a task may specify only what it wants scored. This
    is scoring ground truth (M3/M7), never pipeline input.
    """

    normalized_claim: str | None = None
    entities: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    expected_value: float | None = None
    baseline_value: float | None = None
    comparison_operator: S.ComparisonOperator | None = None
    units: str | None = None


class TaskTolerance(_TaskModel):
    """An explicit numeric tolerance for a task's checks (Milestone 5).

    Optional. When absent, a check derives its tolerance from the *reported
    precision* of the claim's own number — a value written ``3.4`` admits any
    computed value that rounds to ``3.4``. Set this only when a task needs a
    tolerance the claim's wording does not imply, and say why in ``notes``.

    The effective threshold applied to ``|computed − expected|`` is
    ``max(abs_tol, rel_tol · |expected|)``.
    """

    abs_tol: float = Field(default=0.0, ge=0.0)
    rel_tol: float = Field(default=0.0, ge=0.0)


class TaskExpectation(_TaskModel):
    """The gold verification outcome, used to score the pipeline in later runs.

    Holds the expected support label, reproduction status, and failure mode, the
    gold extraction target (:class:`GoldClaim`), and the evidence links a correct
    linker should surface. Reproduction/failure default to the "nothing to
    reproduce / no failure" sentinels so a descriptive task need not state them.
    """

    support_label: S.SupportLabel
    reproduction_status: S.ReproductionStatus = S.ReproductionStatus.NOT_APPLICABLE
    failure_mode: S.FailureMode = S.FailureMode.NONE
    claim: GoldClaim = Field(default_factory=GoldClaim)
    evidence: list[S.EvidenceLink] = Field(default_factory=list)


class TaskSpec(_TaskModel):
    """A complete task definition as parsed from a YAML/JSON file.

    ``artifacts`` reuses the Milestone 1 :class:`~scientific_claim_verifier.schemas.ArtifactBundle`
    (so its unique-ID integrity check runs on every fixture). ``family`` is a
    human-facing grouping label (e.g. ``"numeric_table"``); the machine-relevant
    kind is ``claim.claim_type``.
    """

    task_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str | None = None
    claim: ClaimInput
    artifacts: S.ArtifactBundle
    expected: TaskExpectation
    tolerance: TaskTolerance | None = None
    notes: str | None = None


@dataclass
class LoadedTask:
    """A parsed, resolved, content-hashed task ready for the pipeline.

    ``spec.artifacts`` is the bundle with ``content_hash`` populated on every
    paper/dataset/code artifact. ``content_hashes`` maps ``artifact_id`` to its
    hash for quick trace recording.
    """

    path: Path
    spec: TaskSpec
    content_hashes: dict[str, str] = field(default_factory=dict)

    @property
    def bundle(self) -> S.ArtifactBundle:
        """The artifact bundle (with content hashes populated)."""
        return self.spec.artifacts

    @property
    def input_claim(self) -> S.ScientificClaim:
        """The claim as the pipeline receives it — no gold fields populated."""
        c = self.spec.claim
        return S.ScientificClaim(
            claim_id=c.claim_id,
            claim_text=c.claim_text,
            claim_type=c.claim_type,
            source_document_id=c.source_document_id,
            source_passage=c.source_passage,
        )


# ---------------------------------------------------------------------------
# Repo/path resolution (kept safe: fixtures only, never arbitrary paths)
# ---------------------------------------------------------------------------


def find_repo_root(start: str | Path) -> Path:
    """Walk upward from ``start`` to the directory containing ``pyproject.toml``.

    Falls back to ``start`` (resolved) if no marker is found, so callers always
    get a concrete directory.
    """
    start_path = Path(start).resolve()
    for candidate in (start_path, *start_path.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return start_path


def resolve_fixture_path(rel_path: str, repo_root: Path) -> Path:
    """Resolve a task-declared fixture ``rel_path`` against ``repo_root``, safely.

    Rejects absolute paths and any path that escapes ``repo_root`` (e.g. via
    ``..``). Returns the resolved absolute path; it is *not* required to exist
    here (existence is checked by the caller so a clearer error can be raised).
    """
    candidate = Path(rel_path)
    if candidate.is_absolute():
        raise TaskLoadError(f"fixture path must be relative, got absolute: {rel_path!r}")
    resolved = (repo_root / candidate).resolve()
    root = repo_root.resolve()
    if root != resolved and root not in resolved.parents:
        raise TaskLoadError(f"fixture path escapes the repository: {rel_path!r}")
    return resolved


def is_under_fixture_root(rel_path: str) -> bool:
    """True if ``rel_path`` (repo-relative) lives under ``data/fixtures``."""
    parts = Path(rel_path).parts
    expected = Path(FIXTURE_ROOT).parts
    return parts[: len(expected)] == expected


# ---------------------------------------------------------------------------
# Parsing and CSV shape checks
# ---------------------------------------------------------------------------


def parse_task_data(text: str, *, is_json: bool) -> dict[str, Any]:
    """Parse task ``text`` (YAML or JSON) into a mapping. Raises on non-mappings."""
    data = json.loads(text) if is_json else yaml.safe_load(text)
    if not isinstance(data, dict):
        raise TaskLoadError("task file must contain a top-level mapping")
    return data


def read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """Return ``(header_columns, data_rows)`` for a CSV fixture, as raw strings.

    Uses the stdlib ``csv`` module (no pandas dependency). The first row is the
    header; remaining non-empty rows are data. Headers are stripped of surrounding
    whitespace; cells are returned verbatim so a check can report exactly what the
    file contained.
    """
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.reader(handle) if row]
    if not rows:
        return [], []
    header, *data = rows
    return [col.strip() for col in header], data


def read_csv_shape(path: Path) -> tuple[list[str], int]:
    """Return ``(header_columns, data_row_count)`` for a CSV fixture."""
    columns, data = read_csv_rows(path)
    return columns, len(data)


def read_csv_column(path: Path, column: str) -> list[str]:
    """Return the raw cells of ``column``, top to bottom.

    Raises :class:`TaskLoadError` if the column is absent from the header. A row
    too short to reach the column yields ``""`` rather than dropping silently, so
    a ragged CSV surfaces as a conversion error in the caller instead of a
    quietly shortened sample.
    """
    columns, data = read_csv_rows(path)
    if column not in columns:
        raise TaskLoadError(f"column {column!r} not in CSV header {columns}")
    index = columns.index(column)
    return [row[index] if index < len(row) else "" for row in data]


def check_csv_shape(
    path: Path, declared_columns: list[str], declared_n_rows: int | None
) -> list[str]:
    """Cross-check a dataset's declared shape against the actual CSV.

    Returns a list of human-readable problems (empty if the shape matches). The
    declared ``columns``/``n_rows`` are the schema's shape *hints*; this is where
    Milestone 2 confirms the fixture actually matches them.
    """
    problems: list[str] = []
    columns, n_rows = read_csv_shape(path)
    if declared_columns and columns != declared_columns:
        problems.append(
            f"declared columns {declared_columns} != CSV header {columns}"
        )
    if declared_n_rows is not None and declared_n_rows != n_rows:
        problems.append(
            f"declared n_rows {declared_n_rows} != CSV data rows {n_rows}"
        )
    return problems


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_task(path: str | Path, repo_root: str | Path | None = None) -> LoadedTask:
    """Parse, validate, resolve, and content-hash the task at ``path``.

    Populates ``content_hash`` on every paper, dataset, and code artifact
    (papers over their passage text; datasets/code over their file bytes) and
    returns a :class:`LoadedTask`. Raises :class:`TaskLoadError` (parse/resolve
    problems) or ``pydantic.ValidationError`` (schema problems). For collecting
    *all* problems across a directory without stopping at the first, use
    :mod:`scientific_claim_verifier.artifacts.validation`.
    """
    task_path = Path(path)
    root = find_repo_root(task_path.parent) if repo_root is None else Path(repo_root)

    text = task_path.read_text(encoding="utf-8")
    data = parse_task_data(text, is_json=task_path.suffix.lower() == ".json")
    spec = TaskSpec.model_validate(data)

    content_hashes: dict[str, str] = {}

    # Papers are inlined in the task file; hash their passage content.
    for paper in spec.artifacts.papers:
        payload = json.dumps(
            [[p.passage_id, p.section, p.text] for p in paper.passages],
            sort_keys=True,
            ensure_ascii=False,
        )
        paper.content_hash = hashing.hash_text(payload)
        content_hashes[paper.artifact_id] = paper.content_hash

    # Datasets and code reference committed fixture files; hash the bytes.
    for artifact in (*spec.artifacts.datasets, *spec.artifacts.code_files):
        if artifact.path is None:
            continue
        resolved = resolve_fixture_path(artifact.path, root)
        if not resolved.is_file():
            raise TaskLoadError(f"fixture file not found: {artifact.path}")
        artifact.content_hash = hashing.hash_file(resolved)
        content_hashes[artifact.artifact_id] = artifact.content_hash

    return LoadedTask(path=task_path, spec=spec, content_hashes=content_hashes)


def discover_task_files(tasks_dir: str | Path) -> list[Path]:
    """Return every task file under ``tasks_dir``, sorted for stable ordering."""
    base = Path(tasks_dir)
    files = [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in TASK_SUFFIXES]
    return sorted(files)


__all__ = [
    "TASK_SUFFIXES",
    "FIXTURE_ROOT",
    "TaskLoadError",
    "ClaimInput",
    "GoldClaim",
    "TaskExpectation",
    "TaskTolerance",
    "TaskSpec",
    "LoadedTask",
    "find_repo_root",
    "resolve_fixture_path",
    "is_under_fixture_root",
    "parse_task_data",
    "read_csv_rows",
    "read_csv_shape",
    "read_csv_column",
    "check_csv_shape",
    "load_task",
    "discover_task_files",
]
