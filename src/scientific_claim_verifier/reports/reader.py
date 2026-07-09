"""Reading a scored claim back out of its JSONL trace.

Milestone 9. ``docs/PLAN.md`` §11 requires that *reports are generated from traces*, and
this module is where that requirement is either honoured or quietly broken. It is
honoured: :func:`read_report` takes one ``<task_id>.trace.jsonl`` and returns everything
a report renders. It does not open the task file, the paper, the CSV, or the script; it
does not import the extractor, the linker, the checks, or the sandbox; it re-runs
nothing.

That constraint is the point rather than an optimisation. A trace that cannot be turned
back into the verdict it recorded is not an audit record — it is a log. So the reader
reconstructs the Milestone 7 object graph exactly: the
:class:`~scientific_claim_verifier.schemas.VerificationResult`, the three named
:class:`~scientific_claim_verifier.scoring.Rule` s, the per-check
:class:`~scientific_claim_verifier.scoring.CheckSignal` s, and the
:class:`~scientific_claim_verifier.scoring.failure_modes.Cause` s. A test scores every
committed fixture, writes its trace, reads it back, and asserts the reconstruction equals
the original. If a future milestone records a fact in the result but not in the trace,
that test fails — which is the only way this property stays true.

Re-validation, not deserialization
----------------------------------
Every object comes back through its pydantic model (``extra="forbid"``), so a trace with
a misspelled field or an out-of-range score raises here rather than rendering into a
plausible-looking report. Enum values are parsed against the closed vocabularies. A
corrupt trace is a loud failure, and the message names the file.

Versioning
----------
A trace states the :data:`~scientific_claim_verifier.schemas.SCHEMA_VERSION` it was
written under. The reader accepts any trace of the same **major** version — within a
major, event data only grows — and refuses the rest by name. Traces written before
schema 1.3 carry no ``scoring.run`` event, so they cannot say what run they describe;
they are refused with an instruction rather than guessed at from the filename.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..sandbox.trace import read_trace
from ..schemas import (
    SCHEMA_VERSION,
    CheckType,
    EvidenceKind,
    EvidenceLink,
    FailureMode,
    ReproductionStatus,
    ScientificClaim,
    SupportLabel,
    VerificationCheck,
    VerificationResult,
)
from ..scoring import CheckSignal, Rule, Signal
from ..scoring.failure_modes import Cause
from ..scoring.verdict import SCORING_EVENT_KINDS, ScoredClaim

#: How the suite and ``verify --out`` name a scoring trace. A sandbox trace
#: (``*.sandbox.jsonl``) records one execution, not one verdict, and is not a report input.
TRACE_SUFFIX = ".trace.jsonl"

#: The name of the aggregate a suite run leaves beside its traces. Optional: the index
#: reads it when present and says nothing about a gate when it is absent.
SUMMARY_JSON = "summary.json"

#: Event kinds that must appear exactly once in a scoring trace.
REQUIRED_EVENT_KINDS = tuple(kind for kind in SCORING_EVENT_KINDS if kind != "scoring.check")


class ReportError(Exception):
    """Raised when a trace cannot be read, validated, or understood."""


@dataclass(frozen=True)
class ReportInput:
    """One scored claim, recovered from one trace. Everything a report renders.

    ``scored`` is the reconstructed Milestone 7 :class:`ScoredClaim`; the properties
    below are conveniences over it, so a renderer never reaches through two objects.
    """

    run_id: str
    task_id: str | None
    bundle_id: str | None
    schema_version: str
    claim: ScientificClaim
    scored: ScoredClaim
    causes: tuple[Cause, ...]
    trace_path: Path
    n_events: int

    @property
    def result(self) -> VerificationResult:
        return self.scored.result

    @property
    def signals(self) -> tuple[CheckSignal, ...]:
        return self.scored.signals

    @property
    def support_rule(self) -> Rule:
        return self.scored.support_rule

    @property
    def reproduction_rule(self) -> Rule:
        return self.scored.reproduction_rule

    @property
    def failure_rule(self) -> Rule:
        return self.scored.failure_rule


# ---------------------------------------------------------------------------
# Parsing helpers — each raises ReportError naming the trace
# ---------------------------------------------------------------------------


def _major(version: str) -> str:
    return version.split(".", 1)[0]


def _rule(data: dict[str, Any]) -> Rule:
    """Rebuild the named inference step an event recorded."""
    return Rule(
        name=str(data["rule"]),
        because=str(data["because"]),
        check_ids=tuple(str(check_id) for check_id in data.get("check_ids", ())),
    )


def _signal(check: VerificationCheck, data: dict[str, Any]) -> CheckSignal:
    """Rebuild what one check said about the claim, as scoring reduced it."""
    return CheckSignal(
        check_id=check.check_id,
        check_type=check.check_type,
        status=check.status,
        signal=Signal(data["signal"]),
        because=str(data["signal_because"]),
    )


def _evidence_passages(checks: Iterable[VerificationCheck]) -> list[EvidenceLink]:
    """The passage links that back this verdict — derived exactly as ``scoring.score`` does.

    Not read from ``scoring.evidence``: that event records everything the *linker*
    retrieved, while the result records the passages an ``evidence_presence`` check
    actually consulted. Reconstructing it the same way is what makes the round trip exact.
    """
    return [
        link
        for check in checks
        if check.check_type is CheckType.EVIDENCE_PRESENCE
        for link in check.evidence
        if link.kind is EvidenceKind.PASSAGE
    ]


def _index_events(events: list[dict[str, Any]], path: Path) -> dict[str, dict[str, Any]]:
    """Check the stream's shape and return the singleton events by kind."""
    if [event.get("seq") for event in events] != list(range(len(events))):
        raise ReportError(f"{path}: trace events are missing or out of order")

    kinds = [str(event.get("kind", "")) for event in events]
    unknown = sorted(set(kinds) - set(SCORING_EVENT_KINDS))
    if unknown:
        raise ReportError(f"{path}: not a scoring trace — unexpected event(s) {unknown}")
    if "scoring.run" not in kinds:
        raise ReportError(
            f"{path}: no 'scoring.run' event — this trace predates schema 1.3 and cannot "
            "say which run it describes. Regenerate it with `claimverifier verify --out`."
        )

    by_kind: dict[str, dict[str, Any]] = {}
    for kind, event in zip(kinds, events, strict=True):
        if kind == "scoring.check":
            continue
        if kind in by_kind:
            raise ReportError(f"{path}: duplicate {kind!r} event")
        by_kind[kind] = event
    missing = sorted(set(REQUIRED_EVENT_KINDS) - set(by_kind))
    if missing:
        raise ReportError(f"{path}: incomplete trace — missing event(s) {missing}")
    return by_kind


def _build(events: list[dict[str, Any]], path: Path) -> ReportInput:
    """Reconstruct a scored claim from a validated event stream."""
    by_kind = _index_events(events, path)

    run = by_kind["scoring.run"]["data"]
    version = str(run["schema_version"])
    if _major(version) != _major(SCHEMA_VERSION):
        raise ReportError(
            f"{path}: trace schema {version} is not readable by this build "
            f"(schema {SCHEMA_VERSION}); regenerate the run"
        )

    retrieved = by_kind["scoring.evidence"]["data"]["links"]
    links = [EvidenceLink.model_validate(item) for item in retrieved]
    claim = ScientificClaim.model_validate(
        {**by_kind["scoring.claim"]["data"]["claim"], "evidence_links": links}
    )

    # One event carries one check *and* what that check said about the claim, so the two
    # are read together and cannot be paired with each other's neighbours. Event order is
    # the check order `checks/verification.py` fixed, and `_index_events` has already
    # rejected a stream whose `seq`s are not contiguous.
    checks: list[VerificationCheck] = []
    signals: list[CheckSignal] = []
    for event in (e for e in events if e["kind"] == "scoring.check"):
        check = VerificationCheck.model_validate(event["data"]["check"])
        checks.append(check)
        signals.append(_signal(check, event["data"]))

    support = by_kind["scoring.support"]["data"]
    reproduction = by_kind["scoring.reproduction"]["data"]
    failure = by_kind["scoring.failure"]["data"]
    outcome = by_kind["scoring.result"]["data"]

    result = VerificationResult(
        claim_id=str(outcome["claim_id"]),
        support_label=SupportLabel(support["support_label"]),
        reproduction_status=ReproductionStatus(reproduction["reproduction_status"]),
        failure_mode=FailureMode(failure["failure_mode"]),
        evidence_passages=_evidence_passages(checks),
        computed_checks=checks,
        confidence=outcome["confidence"],
        limitations=list(outcome["limitations"]),
        trace_path=str(path),
        human_readable_summary=by_kind["scoring.result"].get("message"),
    )
    scored = ScoredClaim(
        result=result,
        support_rule=_rule(support),
        reproduction_rule=_rule(reproduction),
        failure_rule=_rule(failure),
        signals=tuple(signals),
    )
    return ReportInput(
        run_id=str(run["run_id"]),
        task_id=run.get("task_id"),
        bundle_id=run.get("bundle_id"),
        schema_version=version,
        claim=claim,
        scored=scored,
        causes=tuple(
            Cause(FailureMode(c["failure_mode"]), str(c["check_id"]), str(c["because"]))
            for c in failure.get("causes", ())
        ),
        trace_path=path,
        n_events=len(events),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def read_report(path: str | Path) -> ReportInput:
    """Read one scoring trace and reconstruct the claim, checks, rules, and verdict.

    Raises :class:`ReportError` — never a bare ``KeyError``, ``ValidationError``, or
    ``JSONDecodeError`` — for any unreadable, malformed, incomplete, or wrong-version
    trace, with the offending file named.
    """
    trace = Path(path)
    try:
        events = read_trace(trace)
    except OSError as exc:
        raise ReportError(f"{trace}: cannot read trace: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReportError(f"{trace}: not JSONL: {exc}") from exc

    if not events:
        raise ReportError(f"{trace}: empty trace")
    try:
        return _build(events, trace)
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ReportError(f"{trace}: malformed trace: {exc}") from exc


def discover_traces(run_dir: str | Path) -> list[Path]:
    """Every scoring trace directly under ``run_dir``, sorted by filename.

    Sandbox traces (``*.sandbox.jsonl``) are not scoring traces and are not returned.
    """
    return sorted(Path(run_dir).glob(f"*{TRACE_SUFFIX}"))


def read_summary(run_dir: str | Path) -> dict[str, Any] | None:
    """The suite aggregate beside a run's traces, or ``None`` if there is none.

    Used only to title and gate the *index*; a per-claim report never reads it. An
    unreadable or non-object ``summary.json`` is treated as absent rather than fatal —
    the reports it would decorate are all still valid.
    """
    path = Path(run_dir) / SUMMARY_JSON
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return summary if isinstance(summary, dict) else None


def order_of(run_dir: str | Path, summary: dict[str, Any] | None) -> list[str]:
    """The run ids a suite ran, in its declared order. Empty when there is no summary.

    A suite orders its tasks by evidence channel, not alphabetically, and the index reads
    better in that order. Callers fall back to filename order for anything left over.
    """
    tasks = (summary or {}).get("tasks")
    if not isinstance(tasks, list):
        return []
    named = (t.get("task_id") for t in tasks if isinstance(t, dict))
    return [task_id for task_id in named if isinstance(task_id, str)]


__all__ = [
    "REQUIRED_EVENT_KINDS",
    "SUMMARY_JSON",
    "TRACE_SUFFIX",
    "ReportError",
    "ReportInput",
    "discover_traces",
    "order_of",
    "read_report",
    "read_summary",
]
