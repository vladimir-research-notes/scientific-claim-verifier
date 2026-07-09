"""The recorded adapter: replay committed fixture responses, or fail loudly.

Milestone 10, and ``docs/PLAN.md`` §8's ``RecordedLLMAdapter``. It holds a table of
``fingerprint -> response`` built from a committed JSON file, and answers a request by
looking it up.

**It never falls back to a live call.** A miss raises :class:`RecordingNotFound`. This
is the single property that makes the adapter safe to leave enabled: a replay adapter
that quietly reached for the network on a miss would defeat every guarantee in
``CLAUDE.md`` at exactly the moment nobody was watching — when a prompt changed and the
recordings stopped matching. Missing a recording is an error, not a reason to spend money.

**The recordings are synthetic.** They are hand-authored JSON in the shape a model
would return, and no API produced them. The model they name, ``recorded-fixture-v1``, is
fictitious for that reason: writing a real vendor model name into a committed fixture
would assert something false about where the bytes came from. See
``data/fixtures/llm/README.md``.

**A recording is keyed by the request, so a changed prompt invalidates it.** The
fingerprint covers the system message, the prompt, the model, the temperature, and
``max_tokens``. Edit the prompt template in
:mod:`scientific_claim_verifier.claims.llm_extraction` and every recording misses at
once, loudly. That is the intended failure: the alternative — matching on a task id and
replaying an answer to a question that was never asked — would let a stale fixture
silently certify a prompt it never saw. ``scripts/06_record_llm_fixtures.py`` rebuilds
the stored requests from the current template, and ``--check`` (which
``tests/test_adapters.py`` also runs) fails the build when they have drifted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from ..artifacts.loader import find_repo_root
from .base import RECORDED_MODEL, AdapterError, LLMAdapter, LLMRequest, LLMResponse, TokenUsage

#: Written into the fixture file so a reader can identify the format.
RECORDINGS_FORMAT = "scv-llm-recordings-v1"

#: Repo-relative home of the committed recordings.
RECORDINGS_RELPATH = Path("data/fixtures/llm/extraction_recordings.json")


class RecordingsError(AdapterError):
    """Raised when a recordings file cannot be parsed or is internally inconsistent."""


class RecordingNotFound(AdapterError):
    """Raised when no committed recording answers this exact request."""


def default_recordings_path() -> Path:
    """The committed recordings file, resolved against the repository root."""
    return find_repo_root(Path(__file__)) / RECORDINGS_RELPATH


@dataclass(frozen=True)
class Recording:
    """One request and the response committed for it.

    ``label`` is a human handle (the task id it was authored for). It plays no part in
    lookup — :meth:`~scientific_claim_verifier.adapters.base.LLMRequest.fingerprint`
    does — but it is what ``scripts/06_record_llm_fixtures.py`` uses to rebuild the
    stored request when the prompt template changes.
    """

    label: str
    request: LLMRequest
    text: str
    usage: TokenUsage
    notes: str | None = None

    @property
    def fingerprint(self) -> str:
        """The request fingerprint this recording answers."""
        return self.request.fingerprint()

    def to_dict(self) -> dict[str, Any]:
        """A JSON-safe, stably-ordered view for the fixture file."""
        return {
            "label": self.label,
            "notes": self.notes,
            "request": self.request.payload(),
            "response": {
                "text": self.text,
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Recording:
        """Rebuild a recording from its fixture-file form. Raises on a bad shape."""
        try:
            request = LLMRequest(**data["request"])
            response = data["response"]
            usage = TokenUsage(
                prompt_tokens=int(response["prompt_tokens"]),
                completion_tokens=int(response["completion_tokens"]),
            )
            return cls(
                label=str(data["label"]),
                request=request,
                text=str(response["text"]),
                usage=usage,
                notes=data.get("notes"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RecordingsError(f"malformed recording: {exc}") from exc


def read_recordings(path: str | Path) -> list[Recording]:
    """Parse a recordings file into :class:`Recording` objects, in file order."""
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecordingsError(f"could not read recordings {target}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("format") != RECORDINGS_FORMAT:
        raise RecordingsError(
            f"{target} is not a {RECORDINGS_FORMAT} document (check its 'format' key)"
        )
    entries = payload.get("recordings")
    if not isinstance(entries, list):
        raise RecordingsError(f"{target}: 'recordings' must be a list")
    return [Recording.from_dict(entry) for entry in entries]


def render_recordings(recordings: list[Recording], *, notes: str | None = None) -> str:
    """Serialize ``recordings`` to the fixture file's exact bytes.

    Sorted keys and a fixed indent, so the committed file is byte-reproducible and
    ``scripts/06_record_llm_fixtures.py --check`` can compare against it directly rather
    than re-parsing and comparing object graphs.
    """
    payload = {
        "format": RECORDINGS_FORMAT,
        "notes": notes,
        "recordings": [recording.to_dict() for recording in recordings],
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_recordings(
    path: str | Path, recordings: list[Recording], *, notes: str | None = None
) -> Path:
    """Write ``recordings`` to ``path`` as a fixture file. Deterministic byte output."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_recordings(recordings, notes=notes), encoding="utf-8")
    return target


class RecordedLLMAdapter(LLMAdapter):
    """Replays committed responses. Deterministic, free, and offline by construction."""

    name: ClassVar[str] = "recorded"
    spends_money: ClassVar[bool] = False

    def __init__(self, recordings: list[Recording], *, source: str | None = None) -> None:
        self._source = source
        self._by_fingerprint: dict[str, Recording] = {}
        for recording in recordings:
            existing = self._by_fingerprint.get(recording.fingerprint)
            if existing is not None:
                raise RecordingsError(
                    f"two recordings answer the same request "
                    f"({existing.label!r} and {recording.label!r}); a replay must be unambiguous"
                )
            self._by_fingerprint[recording.fingerprint] = recording
        self.calls = 0

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> RecordedLLMAdapter:
        """Load the committed recordings (or those at ``path``)."""
        target = Path(path) if path is not None else default_recordings_path()
        return cls(read_recordings(target), source=str(target))

    @property
    def default_model(self) -> str:
        return RECORDED_MODEL

    @property
    def labels(self) -> tuple[str, ...]:
        """Every recording's label, sorted. For display and for tests."""
        return tuple(sorted(r.label for r in self._by_fingerprint.values()))

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Replay the recording for ``request``, or raise :class:`RecordingNotFound`."""
        self.calls += 1
        fingerprint = request.fingerprint()
        recording = self._by_fingerprint.get(fingerprint)
        if recording is None:
            raise RecordingNotFound(
                f"no committed recording answers request {fingerprint[:12]}… for model "
                f"{request.model!r}. The recorded adapter never falls back to a live call. "
                f"If the prompt template changed, rebuild the fixtures with "
                f"`python3 scripts/06_record_llm_fixtures.py --write`. "
                f"Known recordings: {', '.join(self.labels) or '(none)'}."
            )
        return LLMResponse(
            text=recording.text,
            model=request.model,
            adapter=self.name,
            usage=recording.usage,
        )

    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "calls": self.calls,
            "source": self._source,
            "recordings": len(self._by_fingerprint),
            "labels": list(self.labels),
            "provenance": "hand-authored synthetic fixtures; no API produced them",
        }


__all__ = [
    "RECORDINGS_FORMAT",
    "RECORDINGS_RELPATH",
    "Recording",
    "RecordedLLMAdapter",
    "RecordingNotFound",
    "RecordingsError",
    "default_recordings_path",
    "read_recordings",
    "render_recordings",
    "write_recordings",
]
