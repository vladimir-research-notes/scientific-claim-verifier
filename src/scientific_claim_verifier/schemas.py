"""Typed data model for scientific-claim-verifier.

Milestone 1 replaces the Milestone 0 stub with the project's core schema: the
typed, validated objects every later subsystem reads and writes. Nothing here
performs verification — these are the *contracts*. Extraction (M3), evidence
linking (M4), checks (M5), the sandbox (M6), and scoring (M7) all produce and
consume these models, and reports (M9) render them.

Design goals:

- **Auditability.** The five things a report must keep visibly separate —
  extracted claim, supporting text, computed check, inference, and unverifiable
  statement — map onto distinct typed fields, never one opaque blob.
- **Strictness.** Models forbid unknown fields (``extra="forbid"``) so a typo in
  a task file fails loudly instead of being silently dropped.
- **Determinism.** No field is populated from the wall clock or an RNG at
  construction time. Timestamps (``RunTrace.created_at``) are optional and
  supplied by the caller, and ``RunTrace.to_jsonl`` sorts keys, so a trace's
  content is byte-reproducible.
- **Closed vocabularies.** Support labels, reproduction statuses, failure modes,
  claim types, and comparison operators are ``str`` enums whose values match the
  tables on the project website and ``docs/CLAIM_SCHEMA.md`` — docs and code
  cannot drift.

The vocabularies mirror ``docs/PLAN.md`` section 6 and the website
(``site/claim-schema.html``, ``site/reproducibility.html``, ``site/checks.html``).
"""

from __future__ import annotations

import json
from collections import Counter
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Bumped from the Milestone 0 placeholder ("0-stub") now that the real typed
# models exist. Written into every ``RunTrace`` so a trace records the schema it
# was produced under.
SCHEMA_VERSION = "1.0"

# A scalar cell / value as it may appear in a table, a computed result, or an
# expected output. ``None`` represents an absent cell. Booleans are intentionally
# excluded (scientific cells are numbers or strings). This is a real runtime
# ``UnionType`` (PEP 604), referenced by later annotations.
CellValue = int | float | str | None


# ---------------------------------------------------------------------------
# Closed vocabularies (str enums — values match the website tables and docs)
# ---------------------------------------------------------------------------


class ClaimType(StrEnum):
    """The kind of scientific claim, which selects the primary check."""

    DESCRIPTIVE = "descriptive_claim"
    NUMERIC = "numeric_claim"
    COMPARISON = "comparison_claim"
    TABLE = "table_claim"
    FIGURE = "figure_claim"
    DATASET = "dataset_claim"
    CODE_REPRODUCTION = "code_reproduction_claim"
    UNSUPPORTED_OR_CONTEXTUAL = "unsupported_or_contextual_claim"


class ComparisonOperator(StrEnum):
    """How an ``expected_value`` should be compared against the computed value."""

    EQ = "="
    GT = ">"
    LT = "<"
    GE = ">="
    LE = "<="
    APPROX = "~"


class SupportLabel(StrEnum):
    """Whether the artifacts back the claim. Relative to the supplied bundle."""

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNDERSPECIFIED = "underspecified"
    UNVERIFIABLE_FROM_ARTIFACTS = "unverifiable_from_artifacts"
    NOT_CHECKED = "not_checked"


class ReproductionStatus(StrEnum):
    """Whether the underlying computation reproduced."""

    REPRODUCED = "reproduced"
    APPROXIMATELY_REPRODUCED = "approximately_reproduced"
    FAILED_ENVIRONMENT = "failed_environment"
    FAILED_MISSING_DATA = "failed_missing_data"
    FAILED_MISSING_CODE = "failed_missing_code"
    FAILED_NUMERIC_MISMATCH = "failed_numeric_mismatch"
    NOT_APPLICABLE = "not_applicable"
    NOT_ATTEMPTED = "not_attempted"


class FailureMode(StrEnum):
    """Why a claim was not cleanly supported/reproduced. ``NONE`` = no failure."""

    NONE = "none"
    MISSING_EVIDENCE_LINK = "missing_evidence_link"
    PASSAGE_DOES_NOT_ASSERT = "passage_does_not_assert"
    TABLE_CELL_MISMATCH = "table_cell_mismatch"
    STATISTIC_MISMATCH = "statistic_mismatch"
    NUMERIC_OUT_OF_TOLERANCE = "numeric_out_of_tolerance"
    MISSING_DATA = "missing_data"
    MISSING_CODE = "missing_code"
    EXECUTION_ERROR = "execution_error"
    EXECUTION_TIMEOUT = "execution_timeout"
    UNDERSPECIFIED = "underspecified"
    OTHER = "other"


class EvidenceKind(StrEnum):
    """Which artifact an :class:`EvidenceLink` points at."""

    PASSAGE = "passage"
    TABLE = "table"
    FIGURE = "figure"
    DATASET = "dataset"
    CODE = "code"


class CheckType(StrEnum):
    """The deterministic check that produced a :class:`VerificationCheck`."""

    TABLE_VALUE = "table_value"
    DATASET_STATISTIC = "dataset_statistic"
    NUMERIC_TOLERANCE = "numeric_tolerance"
    COMPARISON = "comparison"
    EVIDENCE_PRESENCE = "evidence_presence"
    FIGURE_RECOMPUTE = "figure_recompute"
    CODE_EXECUTION = "code_execution"


class CheckStatus(StrEnum):
    """Outcome of a single check. ``ERROR`` = the check itself could not run."""

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Base model
# ---------------------------------------------------------------------------


class _Model(BaseModel):
    """Shared config: reject unknown fields so malformed input fails loudly."""

    model_config = ConfigDict(extra="forbid")


def _reject_duplicates(ids: list[str], label: str) -> None:
    """Raise ``ValueError`` if ``ids`` contains repeats (sorted for stability)."""
    dupes = sorted(value for value, count in Counter(ids).items() if count > 1)
    if dupes:
        raise ValueError(f"duplicate {label}: {', '.join(dupes)}")


# ---------------------------------------------------------------------------
# Artifact content (the evidence a claim is checked against)
# ---------------------------------------------------------------------------


class Passage(_Model):
    """A span of paper text with a stable ID that a claim can be linked to."""

    passage_id: str = Field(min_length=1)
    text: str
    section: str | None = None


class Table(_Model):
    """A structured table (results/ablation) referenced by table/figure claims.

    ``rows`` is row-major; each cell is a scalar or ``None`` for a missing cell.
    Row/column alignment is not enforced here — that is validated where a table
    check consumes it (Milestone 5).
    """

    table_id: str = Field(min_length=1)
    caption: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[CellValue]] = Field(default_factory=list)
    notes: str | None = None


class Figure(_Model):
    """Figure *metadata* and the data series behind it — never pixel data."""

    figure_id: str = Field(min_length=1)
    caption: str | None = None
    kind: str | None = None  # e.g. "bar", "line"
    series: dict[str, list[float]] = Field(default_factory=dict)
    notes: str | None = None


class PaperArtifact(_Model):
    """Paper text as ID-addressable passages. Content-hashed for provenance.

    ``content_hash`` is populated by the hashing helper in Milestone 2; it is
    optional here so a schema-only bundle is still valid.
    """

    artifact_id: str = Field(min_length=1)
    title: str | None = None
    passages: list[Passage] = Field(default_factory=list)
    content_hash: str | None = None
    source: str | None = None
    license: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def passage(self, passage_id: str) -> Passage | None:
        """Return the passage with ``passage_id``, or ``None`` if absent."""
        return next((p for p in self.passages if p.passage_id == passage_id), None)


class DatasetArtifact(_Model):
    """A small dataset (typically a committed CSV) for statistic recomputation.

    The rows are not inlined; ``path`` points at the fixture file loaded lazily
    by later milestones. ``columns`` / ``n_rows`` are *declared* shape hints and
    are cross-checked against the loaded data when a check runs (Milestone 5).
    """

    artifact_id: str = Field(min_length=1)
    path: str | None = None
    description: str | None = None
    columns: list[str] = Field(default_factory=list)
    n_rows: int | None = Field(default=None, ge=0)
    content_hash: str | None = None
    license: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CodeArtifact(_Model):
    """A tiny script executed in the controlled fixture sandbox (Milestone 6).

    ``entrypoint`` is the command used to run it (e.g. ``python eval.py``).
    ``timeout_seconds`` optionally overrides the sandbox default. This is
    controlled fixture execution, **not** an untrusted-code sandbox.
    """

    artifact_id: str = Field(min_length=1)
    path: str | None = None
    entrypoint: str | None = None
    language: str = "python"
    timeout_seconds: float | None = Field(default=None, gt=0)
    content_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Claims and bundles
# ---------------------------------------------------------------------------


class EvidenceLink(_Model):
    """A provenance link from a claim (or a check) to a specific artifact.

    ``locator`` names the exact position within the target (e.g. a table cell
    ``"row=B,col=F1"`` or a dataset column). ``quote`` is the exact supporting
    text. ``score`` is an optional relevance score in ``[0, 1]`` set by the
    evidence linker (Milestone 4).
    """

    kind: EvidenceKind
    target_id: str = Field(min_length=1)
    locator: str | None = None
    quote: str | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    notes: str | None = None


class ScientificClaim(_Model):
    """A claim as a typed, checkable object rather than free text.

    Numeric fields (``expected_value``, ``baseline_value``) are optional: a claim
    whose value could not be extracted is still a valid claim — it is scored as
    ``underspecified`` rather than rejected. ``baseline_value`` holds the "from"
    value of a comparison claim ("improves from 72 to 78").
    """

    claim_id: str = Field(min_length=1)
    claim_text: str = Field(min_length=1)
    normalized_claim: str | None = None
    source_document_id: str | None = None
    source_passage: str | None = None
    claim_type: ClaimType
    entities: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    expected_value: float | None = None
    baseline_value: float | None = None
    comparison_operator: ComparisonOperator | None = None
    units: str | None = None
    evidence_links: list[EvidenceLink] = Field(default_factory=list)


class ArtifactBundle(_Model):
    """The evidence a claim is checked against: papers, tables, figures,
    datasets, code, and expected outputs.

    Artifact IDs must be unique across ``papers``/``datasets``/``code_files``,
    and table/figure/passage IDs unique within their scope, so an
    :class:`EvidenceLink` resolves unambiguously. This invariant is enforced at
    construction.
    """

    bundle_id: str = Field(min_length=1)
    task_id: str | None = None
    papers: list[PaperArtifact] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)
    datasets: list[DatasetArtifact] = Field(default_factory=list)
    code_files: list[CodeArtifact] = Field(default_factory=list)
    expected_outputs: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_ids(self) -> ArtifactBundle:
        _reject_duplicates(
            [p.artifact_id for p in self.papers]
            + [d.artifact_id for d in self.datasets]
            + [c.artifact_id for c in self.code_files],
            "artifact_id",
        )
        _reject_duplicates([t.table_id for t in self.tables], "table_id")
        _reject_duplicates([f.figure_id for f in self.figures], "figure_id")
        for paper in self.papers:
            _reject_duplicates(
                [pp.passage_id for pp in paper.passages],
                f"passage_id in paper '{paper.artifact_id}'",
            )
        return self

    def paper(self, artifact_id: str) -> PaperArtifact | None:
        """Return the paper artifact with ``artifact_id``, or ``None``."""
        return next((p for p in self.papers if p.artifact_id == artifact_id), None)

    def dataset(self, artifact_id: str) -> DatasetArtifact | None:
        """Return the dataset artifact with ``artifact_id``, or ``None``."""
        return next((d for d in self.datasets if d.artifact_id == artifact_id), None)

    def code(self, artifact_id: str) -> CodeArtifact | None:
        """Return the code artifact with ``artifact_id``, or ``None``."""
        return next((c for c in self.code_files if c.artifact_id == artifact_id), None)

    def table(self, table_id: str) -> Table | None:
        """Return the table with ``table_id``, or ``None``."""
        return next((t for t in self.tables if t.table_id == table_id), None)

    def figure(self, figure_id: str) -> Figure | None:
        """Return the figure with ``figure_id``, or ``None``."""
        return next((f for f in self.figures if f.figure_id == figure_id), None)


# ---------------------------------------------------------------------------
# Checks and results
# ---------------------------------------------------------------------------


class VerificationCheck(_Model):
    """The record of one deterministic check.

    Carries everything needed to audit and regenerate the verdict: the inputs,
    the computed value, the expected value, the tolerance, the signed
    ``difference`` (computed − expected, where meaningful), the evidence used,
    and free-text notes. A check produces evidence; it does not, on its own,
    decide the claim's support label (that is scoring, Milestone 7).
    """

    check_id: str = Field(min_length=1)
    check_type: CheckType
    claim_id: str = Field(min_length=1)
    status: CheckStatus
    computed_value: CellValue = None
    expected_value: CellValue = None
    tolerance: float | None = Field(default=None, ge=0.0)
    difference: float | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceLink] = Field(default_factory=list)
    notes: str | None = None

    @property
    def ok(self) -> bool:
        """True only when the check passed."""
        return self.status is CheckStatus.PASS


class VerificationResult(_Model):
    """The per-claim verdict: the inference the pipeline draws from the checks.

    Keeps the support label, reproduction status, and (on failure) the failure
    mode explicitly separate, alongside the supporting passages, the checks that
    were run, stated limitations, and a link to the JSONL trace.
    """

    claim_id: str = Field(min_length=1)
    support_label: SupportLabel
    reproduction_status: ReproductionStatus = ReproductionStatus.NOT_APPLICABLE
    failure_mode: FailureMode = FailureMode.NONE
    evidence_passages: list[EvidenceLink] = Field(default_factory=list)
    computed_checks: list[VerificationCheck] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    limitations: list[str] = Field(default_factory=list)
    trace_path: str | None = None
    human_readable_summary: str | None = None


# ---------------------------------------------------------------------------
# Trace and suite
# ---------------------------------------------------------------------------


class TraceEvent(_Model):
    """One ordered event in a :class:`RunTrace`. Serialized as a JSONL line."""

    seq: int = Field(ge=0)
    kind: str = Field(min_length=1)
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class RunTrace(_Model):
    """The auditable record of a single claim-verification run.

    Holds the claim, the checks, the final result, and an ordered event stream
    that :meth:`to_jsonl` renders as the ``.jsonl`` trace file. ``created_at`` is
    an optional caller-supplied ISO-8601 string — it is never read from the wall
    clock here, so the trace's core content stays deterministic.
    """

    run_id: str = Field(min_length=1)
    schema_version: str = SCHEMA_VERSION
    task_id: str | None = None
    bundle_id: str | None = None
    claim: ScientificClaim | None = None
    checks: list[VerificationCheck] = Field(default_factory=list)
    result: VerificationResult | None = None
    events: list[TraceEvent] = Field(default_factory=list)
    created_at: str | None = None

    def add_event(self, kind: str, message: str | None = None, **data: Any) -> TraceEvent:
        """Append an event with an auto-incremented ``seq``; return it."""
        event = TraceEvent(seq=len(self.events), kind=kind, message=message, data=data)
        self.events.append(event)
        return event

    def to_jsonl(self) -> str:
        """Render the event stream as JSONL — one JSON object per line.

        Keys are sorted so the output is byte-stable across runs (the trace is a
        determinism-critical artifact) and enums render as their string values.
        """
        return "\n".join(
            json.dumps(event.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
            for event in self.events
        )


class BenchmarkSuite(_Model):
    """A named set of task references run together as a smoke/benchmark suite."""

    suite_id: str = Field(min_length=1)
    name: str | None = None
    description: str | None = None
    task_ids: list[str] = Field(default_factory=list)
    version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def size(self) -> int:
        """Number of tasks referenced by the suite."""
        return len(self.task_ids)


__all__ = [
    "SCHEMA_VERSION",
    "CellValue",
    # vocabularies
    "ClaimType",
    "ComparisonOperator",
    "SupportLabel",
    "ReproductionStatus",
    "FailureMode",
    "EvidenceKind",
    "CheckType",
    "CheckStatus",
    # artifact content
    "Passage",
    "Table",
    "Figure",
    "PaperArtifact",
    "DatasetArtifact",
    "CodeArtifact",
    # claims and bundles
    "EvidenceLink",
    "ScientificClaim",
    "ArtifactBundle",
    # checks and results
    "VerificationCheck",
    "VerificationResult",
    # trace and suite
    "TraceEvent",
    "RunTrace",
    "BenchmarkSuite",
]
