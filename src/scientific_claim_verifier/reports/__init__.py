"""What a verification report contains, independent of how it is rendered.

Milestone 9. The report is the artifact ``CLAUDE.md`` describes as *auditable*: it keeps
the five channels visibly separate, and it never collapses them into one opaque verdict.
The sections are numbered because the separation is the product:

======  ==========================================================================
``§1``  **extracted claim** — the typed fields the heuristic extractor recovered
``§2``  **supporting text** — the passages the linker retrieved, quoted
``§3``  **computed check** — what each artifact says, check by check
``§4``  **inference** — the three labels, each with the rule that produced it
``§5``  **unverifiable** — what this verdict does *not* settle
``§6``  **trace** — the bytes all of the above was read back from
======  ==========================================================================

A verdict is not a summary of the checks; it is an inference *from* them, and §3 and §4
are separate so a reader can disagree with the second without losing the first.

One document, two serializers
-----------------------------
:func:`build_document` makes every content decision — what a report says, in what order.
:mod:`.markdown` and :mod:`.html` make none: they walk the same :class:`Document` and
emit text. So the two formats cannot drift in *content*, only in punctuation, and a test
asserts they carry the same labels, the same check ids, and the same limitations.

Blocks carry **plain text**, never inline markup. A serializer escapes for its own
format (``|`` in a Markdown cell, ``&`` in HTML), which it can only do safely if it is
not also being handed markup to preserve. :class:`Link` exists because a link is the one
piece of inline structure a report genuinely needs, and it is a block (or a cell), not a
substring.

Determinism
-----------
Nothing here reads the wall clock, an RNG, or the filesystem. A document is a pure
function of a :class:`~scientific_claim_verifier.reports.reader.ReportInput` and the
``trace_href`` the caller resolved, so two renders of one trace are byte-identical — and
so are two renders of the *same claim scored in two different directories*, provided the
report sits beside its trace.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..schemas import CellValue, EvidenceKind, EvidenceLink, ScientificClaim, VerificationCheck

if TYPE_CHECKING:  # `reader` imports the schema, not this module: no cycle either way.
    from .reader import ReportInput

#: Printed wherever a field has no value. An empty cell reads as an oversight.
DASH = "—"

#: What ``confidence`` is, stated wherever it is printed. It is decidedness — the share
#: of a claim's checks that reached a verdict — and it is not calibrated against anything.
CONFIDENCE_CAVEAT = (
    "the share of this claim's checks that reached a pass/fail verdict. It is not a "
    "probability that the label is correct, and it is not calibrated against anything"
)


# ---------------------------------------------------------------------------
# Blocks — plain text, no inline markup
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Link:
    """A hyperlink. The only inline structure a report may carry, and it is a value."""

    label: str
    href: str


#: A table cell: plain text, or a link.
Cell = str | Link


@dataclass(frozen=True)
class Paragraph:
    """A run of prose."""

    text: str


@dataclass(frozen=True)
class Quote:
    """Text quoted verbatim from an artifact — a passage, or the claim sentence."""

    text: str


@dataclass(frozen=True)
class Bullets:
    """An unordered list. An item may contain ``\\n``; renderers indent continuations."""

    items: tuple[str, ...]


@dataclass(frozen=True)
class Table:
    """A table whose every row is as wide as its header. Enforced at construction."""

    columns: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]

    def __post_init__(self) -> None:
        for index, row in enumerate(self.rows):
            if len(row) != len(self.columns):
                raise ValueError(
                    f"row {index} has {len(row)} cell(s), header has {len(self.columns)}"
                )


@dataclass(frozen=True)
class Code:
    """A preformatted block: a shell command, or literal output."""

    text: str


Block = Paragraph | Quote | Bullets | Table | Code | Link


@dataclass(frozen=True)
class Section:
    """A numbered report section: one of the audit channels."""

    title: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class Document:
    """A whole report: a title, a lede, ordered sections, and a footer."""

    title: str
    lede: str
    sections: tuple[Section, ...]
    footer: str


# ---------------------------------------------------------------------------
# Formatting helpers (pure, total — every one of them handles ``None``)
# ---------------------------------------------------------------------------


def text_of(value: CellValue | Any) -> str:
    """Render a scalar for display. ``None`` becomes :data:`DASH`, never ``"None"``."""
    return DASH if value is None else str(value)


def list_of(values: list[str]) -> str:
    """Render a list field. Empty becomes :data:`DASH` — an extractor found nothing."""
    return ", ".join(values) if values else DASH


def target_of(check: VerificationCheck) -> str:
    """The artifact a check read, as ``target_id`` or ``target_id[locator]``."""
    if not check.evidence:
        return DASH
    link = check.evidence[0]
    return f"{link.target_id}[{link.locator}]" if link.locator else link.target_id


def describe_link(link: EvidenceLink) -> str:
    """One evidence link's provenance: what it points at, how well, and why."""
    where = f"{link.kind.value} {link.target_id}"
    if link.locator:
        where += f" [{link.locator}]"
    parts = [where]
    if link.score is not None:
        parts.append(f"score {link.score:.3f}")
    if link.notes:
        parts.append(link.notes)
    return " · ".join(parts)


def _claim_fields(claim: ScientificClaim) -> tuple[tuple[Cell, ...], ...]:
    """The extracted claim as ``(field, value)`` rows, in a fixed order."""
    operator = claim.comparison_operator.value if claim.comparison_operator else None
    fields: list[tuple[str, str]] = [
        ("normalized_claim", text_of(claim.normalized_claim)),
        ("claim_type", claim.claim_type.value),
        ("expected_value", text_of(claim.expected_value)),
        ("baseline_value", text_of(claim.baseline_value)),
        ("comparison_operator", text_of(operator)),
        ("units", text_of(claim.units)),
        ("metrics", list_of(claim.metrics)),
        ("datasets", list_of(claim.datasets)),
        ("entities", list_of(claim.entities)),
        ("conditions", list_of(claim.conditions)),
        ("source_document_id", text_of(claim.source_document_id)),
        ("source_passage", text_of(claim.source_passage)),
    ]
    return tuple((name, value) for name, value in fields)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _header_blocks(report: ReportInput) -> tuple[Block, ...]:
    result = report.result
    return (
        Table(
            columns=("Field", "Value"),
            rows=(
                ("task", text_of(report.task_id)),
                ("claim", result.claim_id),
                ("support_label", result.support_label.value),
                ("reproduction_status", result.reproduction_status.value),
                ("failure_mode", result.failure_mode.value),
                ("confidence", f"{result.confidence or 0.0:.2f}"),
                ("bundle", text_of(report.bundle_id)),
                ("schema_version", report.schema_version),
            ),
        ),
    )


def _claim_section(report: ReportInput) -> Section:
    return Section(
        "1. Extracted claim",
        (
            Paragraph(
                "The typed fields a rule-based extractor recovered from the claim "
                "sentence. Extraction is a transparent heuristic — regular expressions "
                "and small closed lexicons, not a language model — and an empty field "
                "means the extractor found nothing rather than that nothing is there. "
                "See docs/EXTRACTION.md."
            ),
            Quote(report.claim.claim_text.strip()),
            Table(columns=("Field", "Value"), rows=_claim_fields(report.claim)),
        ),
    )


def _evidence_section(report: ReportInput) -> Section:
    blocks: list[Block] = [
        Paragraph(
            "The passages the evidence linker retrieved for this claim. Retrieval is "
            "not support: that a passage was retrieved says nothing about whether it "
            "asserts the claim. Section 3 is where that is checked."
        )
    ]
    passages = report.result.evidence_passages
    if not passages:
        blocks.append(Paragraph("(no passage was linked to this claim)"))
    for link in passages:
        if link.quote:
            blocks.append(Quote(link.quote))
        blocks.append(Bullets((describe_link(link),)))

    others = [
        link for link in report.claim.evidence_links if link.kind is not EvidenceKind.PASSAGE
    ]
    if others:
        blocks.append(Paragraph("Other artifacts linked to this claim:"))
        blocks.append(Bullets(tuple(describe_link(link) for link in others)))
    return Section("2. Supporting text (retrieved evidence)", tuple(blocks))


def _checks_section(report: ReportInput) -> Section:
    checks = report.result.computed_checks
    if not checks:
        return Section(
            "3. Computed checks",
            (Paragraph("(no check ran against this claim)"),),
        )

    rows = tuple(
        (
            check.status.value,
            check.check_type.value,
            target_of(check),
            text_of(check.computed_value),
            text_of(check.expected_value),
            text_of(check.tolerance),
            signal.signal.value,
        )
        for check, signal in zip(checks, report.signals, strict=True)
    )
    detail = tuple(
        f"{check.check_id} ({check.status.value} → {signal.signal.value})\n"
        f"check: {check.notes or DASH}\n"
        f"signal: {signal.because}"
        for check, signal in zip(checks, report.signals, strict=True)
    )
    return Section(
        "3. Computed checks",
        (
            Paragraph(
                "Each check reads one artifact and records what it found. A check "
                "produces evidence; it does not decide the claim's support label — that "
                "inference is section 4. A check's status is a fact about the check; its "
                "signal is what the check says about the claim, and the two differ: an "
                "evidence check that fails because the passage never mentions the claim "
                "refutes nothing. See docs/CHECKS.md and docs/SCORING.md."
            ),
            Table(
                columns=(
                    "Status",
                    "Check",
                    "Target",
                    "Computed",
                    "Expected",
                    "Tolerance",
                    "Signal",
                ),
                rows=rows,
            ),
            Bullets(detail),
        ),
    )


def _inference_section(report: ReportInput) -> Section:
    result = report.result
    verdicts = (
        ("support_label", result.support_label.value, report.support_rule),
        ("reproduction_status", result.reproduction_status.value, report.reproduction_rule),
        ("failure_mode", result.failure_mode.value, report.failure_rule),
    )
    items = tuple(
        f"{field}: {value}\n"
        f"rule: {rule.name} [{', '.join(rule.check_ids) or 'no checks'}]\n"
        f"because: {rule.because}"
        for field, value, rule in verdicts
    )
    blocks: list[Block] = [
        Paragraph(
            "A verdict is not a summary of the checks; it is an inference from them. "
            "Each rule names itself and the check ids it read, so the verdict can be "
            "re-derived without re-reading the code."
        ),
        Bullets(items),
    ]
    if len(report.causes) > 1:
        blocks.append(
            Paragraph(
                "Every reason this claim is not clean. The failure mode above is the "
                "highest-priority one; the rest survive as limitations:"
            )
        )
        blocks.append(
            Bullets(
                tuple(
                    f"{cause.mode.value} ({cause.check_id}): {cause.because}"
                    for cause in report.causes
                )
            )
        )
    blocks.append(
        Paragraph(f"confidence {result.confidence or 0.0:.2f} — {CONFIDENCE_CAVEAT}.")
    )
    return Section("4. Inference", tuple(blocks))


def _limitations_section(report: ReportInput) -> Section:
    limitations = report.result.limitations
    blocks: tuple[Block, ...] = (
        Paragraph("What this verdict does not settle, and why."),
        Bullets(tuple(limitations))
        if limitations
        else Paragraph("(none — every check reached a verdict)"),
    )
    return Section("5. Unverifiable from these artifacts", blocks)


def _trace_section(report: ReportInput, trace_href: str) -> Section:
    return Section(
        "6. Trace",
        (
            Paragraph(
                "This report was rendered from the trace below and from nothing else: "
                "no task file was read, no artifact re-opened, no check re-run. Every "
                "number, quote, rule, and limitation above was recovered from these "
                "bytes and re-validated against the schema."
            ),
            Link(trace_href.rsplit("/", 1)[-1], trace_href),
            Paragraph(
                f"{report.n_events} JSONL events, schema {report.schema_version}. Keys "
                "are sorted and nothing is read from the wall clock, so two runs of one "
                "task produce byte-identical traces — including tasks whose fixture "
                "script actually executes."
            ),
            Code(f"claimverifier report --run {trace_href}"),
        ),
    )


def build_document(report: ReportInput, *, trace_href: str) -> Document:
    """Assemble the report for one scored claim. Pure; ``trace_href`` is the caller's."""
    title = f"Verification report — {report.task_id or report.run_id}"
    return Document(
        title=title,
        lede=report.result.human_readable_summary or "",
        sections=(
            Section("", _header_blocks(report)),
            _claim_section(report),
            _evidence_section(report),
            _checks_section(report),
            _inference_section(report),
            _limitations_section(report),
            _trace_section(report, trace_href),
        ),
        footer=(
            "Generated by `claimverifier report` from the JSONL trace named above. "
            "Deterministic: no timestamps, no wall clock, no random seeds. Verdicts are "
            "relative to the supplied artifacts and to nothing else."
        ),
    )


# ---------------------------------------------------------------------------
# The index over a run directory
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IndexEntry:
    """One row of the index: a scored claim, and where its report and trace live."""

    report: ReportInput
    report_href: str
    trace_href: str


def _gate_line(summary: dict[str, Any]) -> str | None:
    """One sentence about the suite that produced this directory, or ``None``.

    Read from ``summary.json`` when the run directory has one. A directory of loose
    traces has no gate, and the index says nothing rather than inventing one.
    """
    suite = summary.get("suite") or {}
    gate = summary.get("gate") or {}
    suite_id = suite.get("suite_id")
    if not isinstance(suite_id, str):
        return None

    name = f" ({suite['name']})" if suite.get("name") else ""
    version = f" v{suite['version']}" if suite.get("version") else ""
    if not gate.get("applicable", True):
        verdict = "gate NOT APPLICABLE — the fixture scripts were not executed"
    else:
        verdict = "gate PASS" if gate.get("ok") else "gate FAIL"
    return f"Suite {suite_id}{name}{version} — {verdict}."


def build_index_document(
    entries: tuple[IndexEntry, ...],
    *,
    run_name: str,
    summary: dict[str, Any] | None = None,
) -> Document:
    """Assemble the index over a directory of reports. Deterministic in ``entries`` order."""
    rows: tuple[tuple[Cell, ...], ...] = tuple(
        (
            Link(entry.report.task_id or entry.report.run_id, entry.report_href),
            entry.report.result.support_label.value,
            entry.report.result.reproduction_status.value,
            entry.report.result.failure_mode.value,
            f"{entry.report.result.confidence or 0.0:.2f}",
            Link("trace", entry.trace_href),
        )
        for entry in entries
    )
    counts = Counter(entry.report.result.support_label.value for entry in entries)
    tally = tuple(f"{count} {label}" for label, count in sorted(counts.items()))

    blocks: list[Block] = []
    gate = _gate_line(summary) if summary else None
    if gate:
        blocks.append(Paragraph(gate))
    blocks += [
        Table(
            columns=(
                "Task",
                "Support label",
                "Reproduction",
                "Failure mode",
                "Confidence",
                "Trace",
            ),
            rows=rows,
        ),
        Paragraph("Support labels across this run:"),
        Bullets(tally or (DASH,)),
        Paragraph(
            "These counts describe one run over hand-authored synthetic fixtures. They "
            "are not a benchmark result, and this index is not a scoreboard: it reports "
            "what the pipeline concluded, not whether the conclusions are right. The "
            "comparison against each task's gold outcome lives in summary.csv and "
            "summary.json beside these reports, where the two kinds of miss — a wrong "
            "verdict and an honest refusal to decide — are kept apart."
        ),
    ]
    return Document(
        title=f"Verification reports — {run_name}",
        lede=(
            f"{len(entries)} claim(s), each rendered from its own JSONL trace. "
            f"Confidence is {CONFIDENCE_CAVEAT}."
        ),
        sections=(Section("", tuple(blocks)),),
        footer=(
            "Generated by `claimverifier report`. Deterministic: no timestamps, no wall "
            "clock, no random seeds."
        ),
    )


__all__ = [
    "CONFIDENCE_CAVEAT",
    "DASH",
    "Block",
    "Bullets",
    "Cell",
    "Code",
    "Document",
    "IndexEntry",
    "Link",
    "Paragraph",
    "Quote",
    "Section",
    "Table",
    "build_document",
    "build_index_document",
    "describe_link",
    "list_of",
    "target_of",
    "text_of",
]
