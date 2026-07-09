"""Integration contracts: five export formats, one strict reader, no external dependency.

Milestone 11. ``docs/PLAN.md`` asks for "compatible import/export formats for the
code-agent runtime, BioScientist OS, BioAgentBench, LLM regression/observability, and
agent-control-bench — without depending on those repos."

What this package is, stated precisely
--------------------------------------
**No external schema was consulted.** None of those five systems was read, imported, or
run. This package therefore cannot and does not claim *compatibility* with any of them.
What it defines is five **proposed contracts**, each shaped for the consumer *role* the
plan names, each versioned, each derived from artifacts this repository actually produces,
and each validated by a strict reader that refuses a document it does not recognise. If a
named repo turns out to want different keys, the change is confined to one module of ~200
lines and a ``format_version`` bump; nothing else in the pipeline knows these formats
exist. That is the property worth having, and it is the only one being claimed.

The five formats
----------------
=======================  =====================================  ==============
``runnable-tasks``       code-agent runtime                     ``tasks/``
``evidence-records``     BioScientist OS                        a run's traces
``benchmark``            BioAgentBench                          run + gold
``metrics``              LLM regression / observability          run + gold
``episodes``             agent-control-bench                    run + ``tasks/``
=======================  =====================================  ==============

Four properties hold across all five
------------------------------------
1. **An export is a function of committed artifacts.** Nothing here re-runs the
   pipeline — the traces are the record, exactly as Milestone 9 established for reports.
   The single exception is :func:`~.episodes.replay`, which exists to re-run.
2. **An export is deterministic.** Canonical JSON, sorted keys, no wall clock, no RNG.
   Exporting a run twice produces byte-identical files, which is what makes a diff mean
   something.
3. **An export is portable.** Every path is repo-relative and every trace is named by its
   filename. A document that carried ``/home/someone/checkout`` would be a document about
   one machine. A test walks every export and fails on an absolute path.
4. **An export is self-describing.** :class:`~.envelope.Envelope` states the format, the
   contract version, the producer, and the trace schema the payload came from. A consumer
   that asks for one format and is handed another is told so, by name.

And the dependency claim is checked, not asserted: a test parses every module in this
package and fails if it imports anything but the standard library, ``pydantic``, and this
project.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from . import benchmark, episodes, evidence_records, metrics, runnable_tasks
from .envelope import (
    Envelope,
    EnvelopeError,
    IntegrationError,
    dumps,
    loads,
    read,
    wrap,
    write,
)
from .records import ArtifactRef, Controls, ExportContext, Provenance, Verdict
from .run import LoadedRun, load_run

#: What an exporter needs supplied. The CLI validates a request against this before
#: building anything, so "this format needs a run directory" is an error, not a traceback.
NEEDS_RUN = "run"
NEEDS_TASKS = "tasks"


@dataclass(frozen=True)
class FormatSpec:
    """One export format: its identity, its consumer role, and what it reads."""

    name: str
    format: str
    version: str
    consumer: str
    needs: tuple[str, ...]
    summary: str
    payload_model: type[BaseModel]
    build: Callable[[ExportContext], BaseModel]


#: Every format, keyed by its CLI name. The order is the order of ``docs/PLAN.md`` §9.
REGISTRY: dict[str, FormatSpec] = {
    "runnable-tasks": FormatSpec(
        name="runnable-tasks",
        format=runnable_tasks.FORMAT,
        version=runnable_tasks.VERSION,
        consumer=runnable_tasks.CONSUMER,
        needs=(NEEDS_TASKS,),
        summary="Each task as a runnable unit: argv, hashed input files, success criterion.",
        payload_model=runnable_tasks.Payload,
        build=runnable_tasks.build,
    ),
    "evidence-records": FormatSpec(
        name="evidence-records",
        format=evidence_records.FORMAT,
        version=evidence_records.VERSION,
        consumer=evidence_records.CONSUMER,
        needs=(NEEDS_RUN,),
        summary="Each claim as an evidence record, with the five audit channels apart.",
        payload_model=evidence_records.Payload,
        build=evidence_records.build,
    ),
    "benchmark": FormatSpec(
        name="benchmark",
        format=benchmark.FORMAT,
        version=benchmark.VERSION,
        consumer=benchmark.CONSUMER,
        needs=(NEEDS_RUN,),
        summary="The suite as a benchmark: per-task predicted vs. gold, and the metric to use.",
        payload_model=benchmark.Payload,
        build=benchmark.build,
    ),
    "metrics": FormatSpec(
        name="metrics",
        format=metrics.FORMAT,
        version=metrics.VERSION,
        consumer=metrics.CONSUMER,
        needs=(NEEDS_RUN,),
        summary="A run as labelled scalars, with a fixed key space so two runs can be diffed.",
        payload_model=metrics.Payload,
        build=metrics.build,
    ),
    "episodes": FormatSpec(
        name="episodes",
        format=episodes.FORMAT,
        version=episodes.VERSION,
        consumer=episodes.CONSUMER,
        needs=(NEEDS_RUN, NEEDS_TASKS),
        summary="Each verification as a replayable episode: pinned inputs, controls, verdict.",
        payload_model=episodes.Payload,
        build=episodes.build,
    ),
}

#: The ``--format`` values the CLI accepts, in registry order.
FORMAT_NAMES: tuple[str, ...] = tuple(REGISTRY)


def spec_for(name: str) -> FormatSpec:
    """The format named ``name``. Raises :class:`IntegrationError` for an unknown one."""
    try:
        return REGISTRY[name]
    except KeyError:
        raise IntegrationError(
            f"unknown export format {name!r}; known formats: {', '.join(FORMAT_NAMES)}"
        ) from None


def export_document(name: str, ctx: ExportContext) -> Envelope:
    """Build one export, wrapped in the envelope that describes it."""
    spec = spec_for(name)
    return wrap(spec.format, spec.version, spec.build(ctx))


def format_schema(name: str) -> dict[str, Any]:
    """The JSON Schema of a format's envelope and payload.

    Derived from the pydantic models that write and validate the document, so a published
    schema cannot drift from the code that honours it.
    """
    spec = spec_for(name)
    return {
        "format": spec.format,
        "format_version": spec.version,
        "consumer": spec.consumer,
        "envelope": Envelope.model_json_schema(),
        "payload": spec.payload_model.model_json_schema(),
    }


__all__ = [
    "FORMAT_NAMES",
    "NEEDS_RUN",
    "NEEDS_TASKS",
    "REGISTRY",
    "ArtifactRef",
    "Controls",
    "Envelope",
    "EnvelopeError",
    "ExportContext",
    "FormatSpec",
    "IntegrationError",
    "LoadedRun",
    "Provenance",
    "Verdict",
    "benchmark",
    "dumps",
    "episodes",
    "evidence_records",
    "export_document",
    "format_schema",
    "load_run",
    "loads",
    "metrics",
    "read",
    "runnable_tasks",
    "spec_for",
    "wrap",
    "write",
]
