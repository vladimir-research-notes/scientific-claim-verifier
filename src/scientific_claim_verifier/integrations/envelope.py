"""The envelope every integration export is wrapped in.

Milestone 11. An export that does not say what it is cannot be consumed safely: a
consumer that guesses a document's shape from its filename will one day read a
``metrics`` file as a ``benchmark`` file and report a number that means nothing. So every
document this package writes is one JSON object with a fixed five-field header and a
typed ``payload``:

=========================  ===================================================
``format``                 ``scv.<name>`` — namespaced, so it cannot collide
``format_version``         the *contract's* version, not the project's
``producer``               who wrote it
``producer_version``       which build wrote it
``trace_schema_version``   the :data:`~scientific_claim_verifier.schemas.SCHEMA_VERSION`
                           of the traces the payload was derived from
=========================  ===================================================

:func:`loads` is the whole reason the header exists. A caller states the format and the
version it can handle, and a document that is not that format — or is a *later major
version* of it — is refused **by name** rather than parsed into a plausible-looking
object. Within a major version, payload fields only ever grow, so a 1.0 reader may read a
1.4 document (ignoring keys it does not know); across a major, it may not.

Determinism
-----------
:func:`dumps` sorts keys and reads neither the wall clock nor an RNG, so exporting the
same run twice produces byte-identical files. That is what makes an export diffable, and
a diffable export is the only kind a regression tool can use.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .. import __version__
from ..schemas import SCHEMA_VERSION

#: The ``producer`` of every document this package writes.
PRODUCER = "scientific-claim-verifier"

#: Prefix on every ``format`` string, so a document of ours is never mistaken for
#: someone else's document that happens to share a name.
FORMAT_PREFIX = "scv."

#: What a consumer should serve these documents as. Payloads are single JSON objects;
#: the JSONL *trace* they reference is ``application/x-ndjson`` (see ``runnable_tasks``).
MEDIA_TYPE = "application/json"


class IntegrationError(Exception):
    """Raised when an export cannot be built, read, or trusted."""


class EnvelopeError(IntegrationError):
    """Raised when a document is not the envelope the caller asked for."""


class _Model(BaseModel):
    """Shared config for every export record: unknown fields are an error.

    An export is a *contract*. A consumer that silently drops a field it does not
    recognise, and a producer that silently accepts one it never declared, are the two
    ways a contract rots without anyone noticing.
    """

    model_config = ConfigDict(extra="forbid")


class Envelope(_Model):
    """A self-describing export document: a header, and a payload."""

    format: str = Field(min_length=1)
    format_version: str = Field(min_length=1)
    producer: str = Field(min_length=1)
    producer_version: str = Field(min_length=1)
    trace_schema_version: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


def major(version: str) -> str:
    """The major component of a dotted version string."""
    return version.split(".", 1)[0]


def wrap(fmt: str, version: str, payload: BaseModel) -> Envelope:
    """Wrap a typed payload in the header that describes it."""
    return Envelope(
        format=fmt,
        format_version=version,
        producer=PRODUCER,
        producer_version=__version__,
        trace_schema_version=SCHEMA_VERSION,
        payload=payload.model_dump(mode="json"),
    )


def dumps(envelope: Envelope) -> str:
    """Render an envelope as canonical JSON: sorted keys, one trailing newline."""
    document = envelope.model_dump(mode="json")
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def loads(
    text: str,
    *,
    expect: str | None = None,
    expect_version: str | None = None,
) -> Envelope:
    """Parse and validate an export document.

    ``expect`` pins the ``format``; ``expect_version`` pins the **major** version the
    caller can read. Raises :class:`EnvelopeError` — never a bare ``JSONDecodeError`` or
    ``ValidationError`` — for anything it will not vouch for.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EnvelopeError(f"not JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise EnvelopeError("an export document must be a JSON object")
    try:
        envelope = Envelope.model_validate(document)
    except ValidationError as exc:
        raise EnvelopeError(f"not an export envelope: {exc}") from exc

    if expect is not None and envelope.format != expect:
        raise EnvelopeError(f"expected format {expect!r}, got {envelope.format!r}")
    if expect_version is not None and major(envelope.format_version) != major(expect_version):
        raise EnvelopeError(
            f"{envelope.format}: document is version {envelope.format_version}, and this "
            f"build reads major version {major(expect_version)}.x — payload fields only "
            "grow within a major version, so this one cannot be read safely"
        )
    return envelope


def read(
    path: str | Path,
    *,
    expect: str | None = None,
    expect_version: str | None = None,
) -> Envelope:
    """Read an export document from disk. Raises :class:`EnvelopeError`, naming the file."""
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise EnvelopeError(f"{target}: cannot read export: {exc}") from exc
    try:
        return loads(text, expect=expect, expect_version=expect_version)
    except EnvelopeError as exc:
        raise EnvelopeError(f"{target}: {exc}") from exc


def write(envelope: Envelope, path: str | Path) -> Path:
    """Write an envelope to ``path`` as canonical JSON. Returns the path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dumps(envelope), encoding="utf-8")
    return target


__all__ = [
    "FORMAT_PREFIX",
    "MEDIA_TYPE",
    "PRODUCER",
    "Envelope",
    "EnvelopeError",
    "IntegrationError",
    "dumps",
    "loads",
    "major",
    "read",
    "wrap",
    "write",
]
