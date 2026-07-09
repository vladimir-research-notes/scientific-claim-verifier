"""The records more than one export format shares.

Five formats leave this package, aimed at five different consumers. Three of them state
a verdict, three of them name an artifact, and two of them record how a run was invoked.
If each spelled those the same idea differently, a consumer joining two exports would
have to know all five formats to know they agreed. So the shared vocabulary lives here,
once, and a test asserts the formats use it rather than re-inventing it.

:class:`Verdict` is the important one. It is the three-part inference Milestone 7 draws —
support label, reproduction status, failure mode — plus the ``confidence`` that says how
much of the claim the artifacts could decide. It is **never** flattened to a single
score, in any export, because the whole system exists to keep those apart.

:class:`ExportContext` is the other shared type: the inputs an exporter is handed. Every
format takes the same context and uses the part of it that it needs, so the CLI can
validate a request (*"this format needs a run directory"*) without knowing what any
format does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import Field

from ..schemas import FailureMode, ReproductionStatus, SupportLabel, VerificationResult
from .envelope import IntegrationError, _Model

#: The three artifact kinds a bundle can content-hash. Passages live inside a paper, so a
#: paper's hash covers them; tables and figures are inlined in the task file.
PAPER = "paper"
DATASET = "dataset"
CODE = "code"
ARTIFACT_KINDS = (PAPER, DATASET, CODE)


class Verdict(_Model):
    """The three-part inference about one claim, and how much of it was decidable.

    ``confidence`` is the share of the claim's checks that reached a ``pass``/``fail``
    verdict. It is **not** a probability that the label is correct, and it is not
    calibrated against anything. ``None`` on a gold verdict, which no pipeline computed.
    """

    support_label: SupportLabel
    reproduction_status: ReproductionStatus
    failure_mode: FailureMode
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @classmethod
    def of(cls, result: VerificationResult) -> Verdict:
        """The verdict a scored claim reached."""
        return cls(
            support_label=result.support_label,
            reproduction_status=result.reproduction_status,
            failure_mode=result.failure_mode,
            confidence=result.confidence,
        )

    @property
    def triple(self) -> tuple[SupportLabel, ReproductionStatus, FailureMode]:
        """The three labelled fields, without the confidence. What "same verdict" means."""
        return (self.support_label, self.reproduction_status, self.failure_mode)


class Controls(_Model):
    """The knobs that change a verdict, as ``verify_task`` accepts them.

    An episode is replayable only if every knob that can move the verdict is recorded.
    These four are exactly the verdict-affecting parameters of
    :func:`~scientific_claim_verifier.scoring.verdict.verify_task`; ``repo_root`` and the
    injectable script runner are environment, not experiment.

    A 1.3 trace records **none** of them — it records what the pipeline computed, not how
    an operator invoked it — so ``episodes`` cross-checks ``execute`` against the one
    artifact that does record it (a suite ``summary.json``) and takes the rest from the
    exporting operator. See ``docs/INTEGRATIONS.md``.
    """

    execute: bool = True
    use_declared_source: bool = True
    abs_tol: float | None = Field(default=None, ge=0.0)
    rel_tol: float | None = Field(default=None, ge=0.0)


class ArtifactRef(_Model):
    """One content-hashed artifact of a bundle, pinned by the bytes it had.

    ``path`` is repo-relative, or ``None`` for a paper (whose passages are inlined in the
    task file, and whose ``content_hash`` is taken over that text).
    """

    artifact_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    path: str | None = None
    content_hash: str = Field(min_length=1)


class Provenance(_Model):
    """Where a record came from: which run, which task, which trace, which schema.

    ``trace`` is a bare filename, resolved against the run directory the export was made
    from. It is never an absolute path — an export that named the machine that produced
    it would not survive being copied.
    """

    run_id: str = Field(min_length=1)
    task_id: str | None = None
    bundle_id: str | None = None
    trace: str = Field(min_length=1)
    trace_schema_version: str = Field(min_length=1)


@dataclass(frozen=True)
class ExportContext:
    """What an exporter is given. Which fields it needs is declared by the registry.

    ``controls`` describes the run ``run_dir`` holds — the operator states it, because a
    1.3 trace does not record it (see :class:`Controls`). It is ignored by the formats
    that do not describe a run's invocation.
    """

    repo_root: Path
    run_dir: Path | None = None
    tasks_dir: Path | None = None
    suite_path: Path | None = None
    hide_gold: bool = False
    controls: Controls = field(default_factory=Controls)


def repo_relative(path: str | Path, root: str | Path) -> str:
    """``path`` relative to ``root``, POSIX-style. Raises if it escapes ``root``.

    Every path in every export goes through here. An export must be portable, and a
    document carrying ``/home/someone/checkout/tasks/x.yaml`` is a document about one
    machine.
    """
    resolved = Path(path).resolve()
    base = Path(root).resolve()
    try:
        return resolved.relative_to(base).as_posix()
    except ValueError as exc:
        raise IntegrationError(f"{path} is outside the repository root {base}") from exc


__all__ = [
    "ARTIFACT_KINDS",
    "CODE",
    "DATASET",
    "PAPER",
    "ArtifactRef",
    "Controls",
    "ExportContext",
    "Provenance",
    "Verdict",
    "repo_relative",
]
