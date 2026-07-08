"""Passage evidence: exact lookup plus a keyword-overlap baseline.

Three channels, in decreasing order of certainty:

1. **Declared source.** The task's ``claim.source_passage`` names the passage the
   claim was authored from. This is *asserted provenance*, not a retrieval result,
   and the linker records it as such (:attr:`~..evidence.MatchMethod.DECLARED_SOURCE`)
   so a reader never mistakes it for something the system found.
2. **Exact text.** The claim's canonicalized text appears verbatim inside a
   passage's canonicalized text. Score ``1.0``.
3. **Keyword overlap.** A bag-of-words baseline over content tokens, scored with
   the **Dice coefficient** ``2·|C∩P| / (|C|+|P|)``. Every passage in the bundle is
   scored and ranked, so the report can show the runners-up alongside the winner.

Why Dice: it is symmetric, lies in ``[0, 1]``, and does not reward a passage
merely for being long (a containment score would rate an essay that happens to
mention every claim token as a perfect match). The verbatim case, where a long
passage really does state the claim, is already handled by channel 2.

**What this baseline cannot do.** It is bag-of-words. It has no model of
negation, morphology, or synonymy: *"the model is not trained on synthetic data"*
scores identically to the assertion, ``"trained"`` does not match ``"training"``,
and a paraphrase with no shared vocabulary scores zero. That is deliberate — this
module *retrieves* candidate evidence. Deciding whether a linked passage actually
**asserts** the claim is the ``evidence_presence`` check (Milestone 5). The score
is a retrieval confidence, never a probability that the claim is true.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..claims.normalization import canonical_text
from ..schemas import ArtifactBundle
from . import MatchMethod

# A passage scoring below this floor is not linked at all. It rejects passages
# with essentially no lexical overlap with the claim; it is emphatically **not** a
# support threshold (a passage can clear it and still contradict the claim).
MIN_PASSAGE_SCORE = 0.05

# A content token: a run of letters/digits, optionally continued through internal
# ".", "_", or "-". Keeps "sst-2", "72.0", "10-base", and "compute_accuracy.py"
# whole, and drops surrounding punctuation ("90%" -> "90", "SST-2," -> "sst-2").
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[._\-][a-z0-9]+)*")

# Sentence boundary: terminal punctuation followed by whitespace. Decimal points
# ("72.0") are safe because the "." is followed by a digit, not a space. Known
# limitation: an abbreviation such as "Fig. 1" splits.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Closed-class English function words, removed before scoring so overlap is driven
# by content. Deliberately excludes negation and quantifier words ("no", "not",
# "only", "all"), which carry claim-relevant meaning even in a bag of words.
STOPWORDS = frozenset(
    """
    a an and are as at be been being but by can did do does for from had has have
    he her his i if in into is it its of on or our out over per she so than that
    the their them then there these they this those to up upon us was we were
    what when where which while who will with would you your
    """.split()
)

# Passage match methods, best first. Used to break score ties deterministically.
_METHOD_RANK: dict[MatchMethod, int] = {
    MatchMethod.DECLARED_SOURCE: 0,
    MatchMethod.EXACT_TEXT: 1,
    MatchMethod.TOKEN_OVERLAP: 2,
}


@dataclass(frozen=True)
class PassageCandidate:
    """One passage scored against a claim, with the rule that matched it.

    ``score`` is the value written to the :class:`~scientific_claim_verifier.schemas.EvidenceLink`
    (``1.0`` for a declared or verbatim match, else the overlap score).
    ``overlap_score`` is *always* the raw Dice coefficient, so a declared-source
    link still shows how well the passage actually matches the claim's wording —
    a disagreement between the two is exactly what a reviewer wants to see.
    """

    paper_id: str
    passage_id: str
    section: str | None
    method: MatchMethod
    score: float
    overlap_score: float
    shared_tokens: tuple[str, ...]
    quote: str | None


def tokenize(text: str) -> list[str]:
    """Lowercase ``text`` and return its tokens, in order, punctuation stripped."""
    return _TOKEN_RE.findall(text.lower())


def content_tokens(text: str) -> set[str]:
    """Return the distinct non-stopword tokens of ``text``."""
    return {token for token in tokenize(text) if token not in STOPWORDS}


def dice(left: set[str], right: set[str]) -> float:
    """Dice coefficient ``2·|L∩R| / (|L|+|R|)``. Empty on either side gives ``0.0``."""
    total = len(left) + len(right)
    if total == 0:
        return 0.0
    return 2.0 * len(left & right) / total


def contains_claim(claim_text: str, passage_text: str) -> bool:
    """True if ``claim_text`` appears verbatim in ``passage_text``, modulo layout.

    Both sides are canonicalized (lowercased, internal whitespace collapsed,
    trailing period dropped) so that a passage wrapped across lines in a YAML
    fixture still matches a single-line claim.
    """
    return canonical_text(claim_text) in canonical_text(passage_text)


def split_sentences(text: str) -> list[str]:
    """Split ``text`` into sentences on terminal punctuation. Never returns blanks."""
    collapsed = re.sub(r"\s+", " ", text).strip()
    if not collapsed:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(collapsed) if part.strip()]


def best_sentence(claim_text: str, passage_text: str) -> str | None:
    """Return the sentence of ``passage_text`` that best overlaps ``claim_text``.

    Used as the link's ``quote`` — the "supporting text" a report shows. Ties go
    to the earlier sentence. Returns ``None`` for an empty passage.
    """
    sentences = split_sentences(passage_text)
    if not sentences:
        return None
    claim = content_tokens(claim_text)
    return max(sentences, key=lambda s: dice(claim, content_tokens(s)))


def rank_passages(
    claim_text: str,
    bundle: ArtifactBundle,
    declared_passage_id: str | None = None,
) -> list[PassageCandidate]:
    """Score and rank every passage in ``bundle`` against ``claim_text``.

    Pass ``declared_passage_id=None`` to run *blind* — using only what the linker
    can discover from the text. Ranked best-first by ``(score, method, overlap,
    passage_id)``; the ``passage_id`` tie-break makes the ordering total and
    therefore deterministic.
    """
    claim_tokens = content_tokens(claim_text)
    candidates: list[PassageCandidate] = []

    for paper in bundle.papers:
        for passage in paper.passages:
            passage_tokens = content_tokens(passage.text)
            overlap = dice(claim_tokens, passage_tokens)

            if declared_passage_id is not None and passage.passage_id == declared_passage_id:
                method, score = MatchMethod.DECLARED_SOURCE, 1.0
            elif contains_claim(claim_text, passage.text):
                method, score = MatchMethod.EXACT_TEXT, 1.0
            else:
                method, score = MatchMethod.TOKEN_OVERLAP, overlap

            candidates.append(
                PassageCandidate(
                    paper_id=paper.artifact_id,
                    passage_id=passage.passage_id,
                    section=passage.section,
                    method=method,
                    score=score,
                    overlap_score=overlap,
                    shared_tokens=tuple(sorted(claim_tokens & passage_tokens)),
                    quote=best_sentence(claim_text, passage.text),
                )
            )

    candidates.sort(
        key=lambda c: (-c.score, _METHOD_RANK[c.method], -c.overlap_score, c.passage_id)
    )
    return candidates


def select_passage(
    candidates: list[PassageCandidate], min_score: float = MIN_PASSAGE_SCORE
) -> PassageCandidate | None:
    """Return the best candidate, or ``None`` if even the best is below ``min_score``.

    Exactly one passage is linked. The full ranking stays available for the report
    and the trace, so the runners-up and their scores remain auditable.
    """
    if not candidates:
        return None
    best = candidates[0]
    return best if best.score >= min_score else None


__all__ = [
    "MIN_PASSAGE_SCORE",
    "STOPWORDS",
    "PassageCandidate",
    "tokenize",
    "content_tokens",
    "dice",
    "contains_claim",
    "split_sentences",
    "best_sentence",
    "rank_passages",
    "select_passage",
]
