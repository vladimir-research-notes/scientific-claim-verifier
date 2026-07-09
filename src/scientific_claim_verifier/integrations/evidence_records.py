"""``scv.evidence-records`` — a verification result as a structured evidence record.

The consumer role: an evidence store that keeps what is known about a claim, and can
later be asked *why* it believes it. So the record is not a verdict with a citation
stapled to it. It is the five channels ``CLAUDE.md`` requires the report to keep apart,
as five sibling keys that a store cannot merge without noticing:

===================  ======================================================
``claim``            the extracted claim — typed fields, not a sentence
``evidence``         the supporting text, quoted, with its locator
``checks``           each computed check: value, expected, tolerance, status
``verdict``          the inference, three labels wide, never one score
``unverifiable``     what this verdict does *not* settle
===================  ======================================================

``rules`` sits beside them: the named inference step behind each of the verdict's three
fields, and the ``check_id``s it read. A store that keeps the rule can answer "why does
this say ``contradicted``?" by lookup. One that keeps only the label cannot, and a
verdict a reader cannot re-derive is an opinion.

What is deliberately *not* exported
-----------------------------------
``VerificationCheck.inputs`` — the per-check debugging bag whose keys vary by check type
and which, for ``code_execution``, holds captured stdout and stderr. It is in the trace,
where it belongs, and the trace is named in ``provenance``. A stable contract cannot
carry a field whose shape is defined by whichever check happened to write it, and an
evidence store is the last place that should accidentally start holding process output.
"""

from __future__ import annotations

from pydantic import Field

from ..reports.reader import ReportInput
from ..schemas import CellValue, EvidenceLink
from .envelope import _Model
from .records import ExportContext, Provenance, Verdict
from .run import load_run, run_dir_of, task_id_of

#: The format this module writes, and the version of its contract.
FORMAT = "scv.evidence-records"
VERSION = "1.0"

#: The consumer role this format is shaped for.
CONSUMER = "BioScientist OS"

#: The verdict fields, and the rule that decided each. Order is the order they are drawn.
RULE_FIELDS = ("support_label", "reproduction_status", "failure_mode")


class ClaimRecord(_Model):
    """The extracted claim, as typed fields.

    Spelled out rather than reusing
    :class:`~scientific_claim_verifier.schemas.ScientificClaim` on purpose: an export is a
    contract, and a contract that is defined as "whatever the internal model happens to
    hold" changes whenever the internal model does, silently and without a version bump.
    """

    claim_id: str = Field(min_length=1)
    claim_text: str = Field(min_length=1)
    normalized_claim: str | None = None
    claim_type: str = Field(min_length=1)
    source_document_id: str | None = None
    source_passage: str | None = None
    entities: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    expected_value: float | None = None
    baseline_value: float | None = None
    comparison_operator: str | None = None
    units: str | None = None


class EvidenceRef(_Model):
    """A pointer at the exact place in an artifact that bears on the claim."""

    kind: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    locator: str | None = None
    quote: str | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)


class EvidenceBlock(_Model):
    """The supporting text, and the wider set of artifact links the claim resolved to.

    ``supporting_text`` holds the passages an ``evidence_presence`` check actually read —
    the quoted text a reader is entitled to see. ``artifact_links`` holds everything the
    linker retrieved, including the table cells and dataset columns the numeric checks
    consulted. The first is a subset of the second by construction.
    """

    supporting_text: list[EvidenceRef] = Field(default_factory=list)
    artifact_links: list[EvidenceRef] = Field(default_factory=list)


class CheckRecord(_Model):
    """One computed check, and what it said about the claim.

    ``signal`` is the Milestone 7 reduction: a check's ``status`` is a fact about the
    *check*, and one status can mean more than one thing about the *claim*. Both are
    exported, because a consumer that sees only ``fail`` cannot tell a table cell that
    refutes a claim from a passage that merely fails to mention it.
    """

    check_id: str = Field(min_length=1)
    check_type: str = Field(min_length=1)
    status: str = Field(min_length=1)
    signal: str = Field(min_length=1)
    because: str = Field(min_length=1)
    computed_value: CellValue = None
    expected_value: CellValue = None
    tolerance: float | None = Field(default=None, ge=0.0)
    difference: float | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


class RuleRecord(_Model):
    """The named inference step behind one field of the verdict."""

    field: str = Field(min_length=1)
    rule: str = Field(min_length=1)
    because: str = Field(min_length=1)
    check_ids: list[str] = Field(default_factory=list)


class EvidenceRecord(_Model):
    """Everything known about one claim, with the audit channels kept apart."""

    record_id: str = Field(min_length=1)
    claim: ClaimRecord
    evidence: EvidenceBlock
    checks: list[CheckRecord] = Field(default_factory=list)
    verdict: Verdict
    rules: list[RuleRecord] = Field(default_factory=list)
    unverifiable: list[str] = Field(default_factory=list)
    summary: str | None = None
    provenance: Provenance


class Payload(_Model):
    """Every claim in a run, in the run's declared order."""

    records: list[EvidenceRecord] = Field(default_factory=list)


def _evidence_ref(link: EvidenceLink) -> EvidenceRef:
    """Project an :class:`~scientific_claim_verifier.schemas.EvidenceLink` onto the contract."""
    return EvidenceRef(
        kind=link.kind.value,
        target_id=link.target_id,
        locator=link.locator,
        quote=link.quote,
        score=link.score,
    )


def claim_record(report: ReportInput) -> ClaimRecord:
    """The extracted claim, field by field."""
    claim = report.claim
    operator = claim.comparison_operator
    return ClaimRecord(
        claim_id=claim.claim_id,
        claim_text=claim.claim_text.strip(),
        normalized_claim=claim.normalized_claim,
        claim_type=claim.claim_type.value,
        source_document_id=claim.source_document_id,
        source_passage=claim.source_passage,
        entities=list(claim.entities),
        metrics=list(claim.metrics),
        datasets=list(claim.datasets),
        conditions=list(claim.conditions),
        expected_value=claim.expected_value,
        baseline_value=claim.baseline_value,
        comparison_operator=operator.value if operator is not None else None,
        units=claim.units,
    )


def check_records(report: ReportInput) -> list[CheckRecord]:
    """Each check beside the signal scoring reduced it to. Check order is preserved."""
    return [
        CheckRecord(
            check_id=check.check_id,
            check_type=check.check_type.value,
            status=check.status.value,
            signal=signal.signal.value,
            because=signal.because,
            computed_value=check.computed_value,
            expected_value=check.expected_value,
            tolerance=check.tolerance,
            difference=check.difference,
            evidence=[_evidence_ref(link) for link in check.evidence],
        )
        for check, signal in zip(report.result.computed_checks, report.signals, strict=True)
    ]


def rule_records(report: ReportInput) -> list[RuleRecord]:
    """The three named rules that produced the three fields of the verdict."""
    rules = (report.support_rule, report.reproduction_rule, report.failure_rule)
    return [
        RuleRecord(
            field=field,
            rule=rule.name,
            because=rule.because,
            check_ids=list(rule.check_ids),
        )
        for field, rule in zip(RULE_FIELDS, rules, strict=True)
    ]


def record_for(report: ReportInput) -> EvidenceRecord:
    """One claim's evidence record, derived from its trace alone."""
    result = report.result
    return EvidenceRecord(
        record_id=f"{report.run_id}:{result.claim_id}",
        claim=claim_record(report),
        evidence=EvidenceBlock(
            supporting_text=[_evidence_ref(link) for link in result.evidence_passages],
            artifact_links=[_evidence_ref(link) for link in report.claim.evidence_links],
        ),
        checks=check_records(report),
        verdict=Verdict.of(result),
        rules=rule_records(report),
        unverifiable=list(result.limitations),
        summary=result.human_readable_summary,
        provenance=Provenance(
            run_id=report.run_id,
            task_id=task_id_of(report),
            bundle_id=report.bundle_id,
            trace=report.trace_path.name,
            trace_schema_version=report.schema_version,
        ),
    )


def build(ctx: ExportContext) -> Payload:
    """Every claim in a run, as an evidence record. Reads traces; re-runs nothing."""
    run = load_run(run_dir_of(ctx))
    return Payload(records=[record_for(report) for report in run.reports])


__all__ = [
    "CONSUMER",
    "FORMAT",
    "RULE_FIELDS",
    "VERSION",
    "CheckRecord",
    "ClaimRecord",
    "EvidenceBlock",
    "EvidenceRecord",
    "EvidenceRef",
    "Payload",
    "RuleRecord",
    "build",
    "check_records",
    "claim_record",
    "record_for",
    "rule_records",
]
