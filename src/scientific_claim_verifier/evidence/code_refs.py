"""Code evidence: which script a reproduction claim refers to, and what to observe.

Two resolution rules, in order:

1. **By filename.** The claim names a ``.py`` file that matches a code artifact's
   basename (*"Running compute_accuracy.py reports an accuracy of 0.80"*).
2. **Sole artifact.** The claim is a ``code_reproduction_claim`` and the bundle
   holds exactly one code file (*"The synthetic sequence has a GC content of
   0.50"* names no script, but only one script could produce it).

If neither holds — several scripts, no filename — the linker emits **no** code
link. A reproduction claim with no resolvable script is a real, reportable state
(``failed_missing_code`` in Milestone 7), not something to paper over by picking
the first artifact.

The **observable** is read from the bundle, not guessed: when
``expected_outputs`` declares a ``stdout*`` key, the locator is ``stdout``. A
bundle that declares no observable produces a link with no locator, and the check
that consumes it must say what it compared.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas import ArtifactBundle, ClaimType, ScientificClaim
from . import MatchMethod


@dataclass(frozen=True)
class CodeMatch:
    """A code artifact linked to a claim, with the observable to compare against."""

    artifact_id: str
    locator: str | None
    method: MatchMethod


def stdout_locator(bundle: ArtifactBundle) -> str | None:
    """``"stdout"`` when the bundle declares a stdout expectation, else ``None``."""
    declares_stdout = any(str(key).startswith("stdout") for key in bundle.expected_outputs)
    return "stdout" if declares_stdout else None


def link_code(
    claim: ScientificClaim, bundle: ArtifactBundle, referenced_code_ids: list[str]
) -> list[CodeMatch]:
    """Link ``claim`` to the code artifact(s) it refers to.

    ``referenced_code_ids`` are the bundle artifact ids the extractor resolved
    from ``.py`` filenames in the claim text (already deduplicated of unresolved
    mentions).
    """
    locator = stdout_locator(bundle)

    matches: list[CodeMatch] = []
    seen: set[str] = set()
    for artifact_id in referenced_code_ids:
        if artifact_id in seen:
            continue
        seen.add(artifact_id)
        matches.append(CodeMatch(artifact_id, locator, MatchMethod.CODE_FILENAME))
    if matches:
        return matches

    if claim.claim_type is ClaimType.CODE_REPRODUCTION and len(bundle.code_files) == 1:
        return [CodeMatch(bundle.code_files[0].artifact_id, locator, MatchMethod.CODE_SOLE)]
    return []


__all__ = ["CodeMatch", "stdout_locator", "link_code"]
