"""The execution policy: exactly what the sandbox enforces, and what it does not.

A :class:`SandboxPolicy` is a declarative, hashable description of the conditions a
fixture script runs under. The runner reads it, applies it, and records
:meth:`SandboxPolicy.describe` verbatim into the trace — so the report states the
conditions a number was produced under rather than leaving them implicit.

What is enforced
----------------
=========================  ===================================================
Fresh working directory    The script is copied into an empty temp dir and run
                           with that as ``cwd``. It cannot see the repository,
                           so it cannot silently read a fixture it did not
                           declare. The directory is removed afterwards.
Scrubbed environment       The child starts from an **allowlist**
                           (:data:`ENV_ALLOWLIST`), not from ``os.environ``. A
                           script cannot pick up a token, a proxy setting, or a
                           ``PYTHONPATH`` from the machine and record it as a
                           scientific result.
Deterministic environment  ``PYTHONHASHSEED=0``, ``TZ=UTC``,
                           ``PYTHONDONTWRITEBYTECODE=1``, ``PYTHONNOUSERSITE=1``.
Closed stdin               The child cannot block waiting for input.
Wall-clock timeout         Enforced by the parent, which then kills the whole
                           **process group** — a script that spawned children
                           does not outlive its own timeout.
Resource limits            POSIX ``setrlimit`` for CPU seconds, address space,
                           file size, and open files. Applied before ``exec``,
                           so the child cannot raise them back.
Network guard              An in-process guard (:data:`SITECUSTOMIZE_SOURCE`)
                           makes ``socket`` calls raise, and logs every attempt.
=========================  ===================================================

What is **not** enforced
------------------------
There is no process isolation, no namespace, no seccomp filter, no chroot, no user
separation. The network guard is *cooperative*: it monkey-patches ``socket`` inside
the child's own interpreter, so code that reaches past it — raw syscalls, ``ctypes``,
a reference to ``_socket.socket`` captured before the guard installed — is not
stopped. It catches **accidental** network use by trusted code and records it; it
does not contain hostile code.

We deliberately do not set ``http_proxy``/``no_proxy`` variables. They would deter
nothing the socket guard does not already stop, and their presence would imply a
boundary that does not exist.

The guard's integrity is verified rather than assumed: ``site`` swallows exceptions
raised from ``sitecustomize`` and continues, so a broken guard would silently permit
the network. The bootstrap therefore writes a marker file naming the policy it
applied, and :mod:`~scientific_claim_verifier.sandbox.runner` refuses to return a
result if that marker is missing or disagrees.

Determinism
-----------
:meth:`SandboxPolicy.describe` contains no absolute paths and no machine-specific
values, so it is byte-identical across runs and machines. The sandbox root is a
random temp path, so anything the child prints is passed through :func:`redact`
before being recorded.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

try:  # POSIX only; the limits are skipped (and reported as skipped) elsewhere.
    import resource
except ModuleNotFoundError:  # pragma: no cover - Windows
    resource = None  # type: ignore[assignment]

# Applied when a code artifact declares no ``timeout_seconds``.
DEFAULT_TIMEOUT_SECONDS = 10.0

# Longest stdout/stderr excerpt kept in a check's ``inputs`` or a trace event.
# Fixture scripts print one line; the cap bounds the record if one ever does not.
MAX_CAPTURE_CHARS = 2000

# Prefix of the temp directory a run is executed in. Named so a stray directory is
# traceable back to this project.
WORKDIR_PREFIX = "scv-sandbox-"

# Every occurrence of the sandbox root in captured output is replaced with this, so
# a random temp path never reaches a trace. See :func:`redact`.
REDACTED_PATH = "<sandbox>"

# The bootstrap module planted on the child's ``PYTHONPATH``. The name is fixed by
# CPython: ``site`` imports ``sitecustomize`` at interpreter startup if it is
# importable.
BOOTSTRAP_MODULE = "sitecustomize.py"

# Environment variables read by the bootstrap module.
NETWORK_ENV = "SCV_SANDBOX_NETWORK"
NETWORK_LOG_ENV = "SCV_SANDBOX_NETWORK_LOG"
MARKER_ENV = "SCV_SANDBOX_MARKER"

# The only parent environment variables the child inherits. ``PATH`` is kept because
# a script that shells out to a tool would otherwise fail for a confusing reason;
# nothing else is passed through. Locale variables keep text decoding predictable.
ENV_ALLOWLIST = ("LANG", "LC_ALL", "LC_CTYPE", "PATH", "SYSTEMROOT")

# Set unconditionally on the child. Every one of these is a determinism measure, not
# an isolation measure: a script that iterates a set, prints a timestamp, or imports
# from the user site-packages would otherwise produce machine-dependent output that
# the trace would faithfully record as a scientific fact.
ENV_OVERRIDES = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONNOUSERSITE": "1",
    "TZ": "UTC",
}


class NetworkPolicy(StrEnum):
    """Whether the in-process network guard is installed in the child."""

    #: ``socket`` calls raise and are logged. The default.
    BLOCKED = "blocked"
    #: No guard. The child has whatever network access the host grants it.
    INHERITED = "inherited"


# ---------------------------------------------------------------------------
# The bootstrap module injected into the child interpreter
# ---------------------------------------------------------------------------

#: Source of the ``sitecustomize`` module planted on the child's ``PYTHONPATH``.
#:
#: It runs at interpreter startup, before the fixture script. Two jobs: install the
#: network guard when the policy asks for it, and write the marker file that proves
#: it ran (``site`` prints and *swallows* exceptions raised here, so its absence is
#: the only way the parent can tell that the guard did not install).
SITECUSTOMIZE_SOURCE = r'''"""Sandbox bootstrap, injected by scientific-claim-verifier.

Runs at interpreter startup in the sandboxed child. The network guard is
COOPERATIVE and in-process: it replaces `socket` entry points so they record the
attempt and raise. It is not a security boundary — code that bypasses `socket`
(ctypes, raw syscalls, a reference captured before this module ran) bypasses the
guard. Its purpose is to catch accidental network use by trusted fixture code, and
to make sure a reproduction that reached the network cannot look self-contained in
the trace.

`socket.socket` is replaced by a *subclass* that raises on construction, not by a
function. `ssl` executes `class SSLSocket(socket)` at import time, so a guard that
were merely callable would turn `import http.client` into a baffling TypeError for
code that never touches the network.
"""

import importlib
import os

_POLICY = os.environ.get("SCV_SANDBOX_NETWORK", "inherited")
_LOG = os.environ.get("SCV_SANDBOX_NETWORK_LOG")
_MARKER = os.environ.get("SCV_SANDBOX_MARKER")

# Functions replaced by a raising stub.
_BLOCKED_FUNCTIONS = (
    ("socket", "create_connection"),
    ("socket", "create_server"),
    ("socket", "getaddrinfo"),
    ("socket", "gethostbyname"),
)

# Socket types replaced by a raising subclass. `_socket.socket` is included so a
# fresh `import _socket` is denied too.
_BLOCKED_TYPES = (
    ("socket", "socket"),
    ("_socket", "socket"),
)


class NetworkBlocked(RuntimeError):
    """Raised in the sandboxed child when code attempts network access."""


def _deny(name):
    """Record the attempt, then refuse it. The log outlives a caught exception."""
    if _LOG:
        with open(_LOG, "a", encoding="utf-8") as handle:
            handle.write(name + "\n")
    raise NetworkBlocked("sandbox network policy 'blocked' denied " + name)


def _blocked_function(name):
    def blocked(*_args, **_kwargs):
        _deny(name)

    return blocked


def _blocked_type(name, original):
    class BlockedSocket(original):
        def __init__(self, *_args, **_kwargs):
            _deny(name)

    BlockedSocket.__name__ = original.__name__
    BlockedSocket.__qualname__ = original.__qualname__
    return BlockedSocket


def _install():
    for module_name, attribute in _BLOCKED_FUNCTIONS + _BLOCKED_TYPES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        original = getattr(module, attribute, None)
        if original is None:
            continue
        name = module_name + "." + attribute
        replacement = (
            _blocked_type(name, original)
            if isinstance(original, type)
            else _blocked_function(name)
        )
        setattr(module, attribute, replacement)


if _POLICY == "blocked":
    _install()

# Written last: its existence is the parent's proof that the guard installed.
if _MARKER:
    with open(_MARKER, "w", encoding="utf-8") as handle:
        handle.write(_POLICY)
'''


def write_bootstrap(directory: Path) -> Path:
    """Write :data:`SITECUSTOMIZE_SOURCE` into ``directory``; return the file path."""
    path = directory / BOOTSTRAP_MODULE
    path.write_text(SITECUSTOMIZE_SOURCE, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Output handling
# ---------------------------------------------------------------------------


def truncate(text: str, limit: int = MAX_CAPTURE_CHARS) -> str:
    """Clip captured output, marking the elision so nothing looks complete when it is not."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"… [truncated, {len(text)} chars total]"


def redact(text: str, *paths: Path) -> str:
    """Replace every occurrence of ``paths`` in ``text`` with :data:`REDACTED_PATH`.

    The sandbox root is a random temp path. A script printing its working directory,
    or a traceback naming the bootstrap module, would otherwise write a value into
    the trace that differs on every run. Both the literal and the resolved form of
    each path are replaced, longest first, because ``/tmp`` is a symlink on some
    platforms and the child reports the resolved form.
    """
    candidates = {str(path) for path in paths} | {str(path.resolve()) for path in paths}
    for raw in sorted((c for c in candidates if c), key=len, reverse=True):
        text = text.replace(raw, REDACTED_PATH)
    return text


# ---------------------------------------------------------------------------
# Resource limits
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceLimits:
    """POSIX ``setrlimit`` values applied to the child before ``exec``.

    Defaults are generous enough that no honest fixture script notices them, and
    tight enough that a runaway one is stopped by the kernel rather than by luck.
    ``None`` disables an individual limit.

    ``cpu_seconds`` defaults to ``ceil(timeout) + 1``: the wall-clock timeout should
    normally fire first, and the CPU limit is the backstop for a process the parent
    somehow fails to reap.

    Number of processes (``RLIMIT_NPROC``) is deliberately **not** limited: it counts
    every process owned by the real UID, not just the child's descendants, so on a
    busy machine it would fail for reasons that have nothing to do with the script.
    """

    cpu_seconds: int | None = None  # None -> derived from the run's timeout
    address_space_bytes: int | None = 2 * 1024**3
    file_size_bytes: int | None = 8 * 1024**2
    open_files: int | None = 256

    def resolve(self, timeout: float) -> dict[str, int]:
        """The ``RLIMIT_*`` values to apply for a run with this ``timeout``."""
        requested = {
            "RLIMIT_AS": self.address_space_bytes,
            "RLIMIT_CPU": (
                self.cpu_seconds if self.cpu_seconds is not None else math.ceil(timeout) + 1
            ),
            "RLIMIT_FSIZE": self.file_size_bytes,
            "RLIMIT_NOFILE": self.open_files,
        }
        return {name: value for name, value in requested.items() if value is not None}


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SandboxPolicy:
    """The conditions one script runs under. Immutable, hashable, and recorded."""

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    network: NetworkPolicy = NetworkPolicy.BLOCKED
    limits: ResourceLimits | None = field(default_factory=ResourceLimits)
    env_allowlist: tuple[str, ...] = ENV_ALLOWLIST
    max_capture_chars: int = MAX_CAPTURE_CHARS
    cleanup: bool = True

    def with_timeout(self, timeout: float) -> SandboxPolicy:
        """A copy of this policy whose timeout is ``timeout``."""
        return replace(self, timeout_seconds=timeout)

    def clip(self, text: str) -> str:
        """Truncate captured output to this policy's cap."""
        return truncate(text, self.max_capture_chars)

    def resource_limits(self) -> dict[str, int]:
        """The ``RLIMIT_*`` values this policy will actually apply.

        Empty when the platform has no ``resource`` module, or when limits are
        disabled. Only limits this interpreter knows about are reported, so the
        recorded policy never claims a limit that was not set.
        """
        if resource is None or self.limits is None:
            return {}
        resolved = self.limits.resolve(self.timeout_seconds)
        return {name: value for name, value in resolved.items() if hasattr(resource, name)}

    def limit_applier(self) -> Callable[[], None] | None:
        """A ``preexec_fn`` that applies the limits, or ``None`` if there are none.

        Runs in the forked child before ``exec``. Soft and hard limits are both set,
        so the child cannot raise them back. If the host's *hard* limit is already
        below a requested value, ``setrlimit`` raises and the run fails loudly —
        preferable to recording a limit that was never applied.

        **Caveat.** ``preexec_fn`` is not safe to use in a multi-threaded parent
        (CPython's own warning). The CLI and the test suite are single-threaded.
        """
        limits = self.resource_limits()
        if not limits or resource is None:
            return None

        def apply() -> None:
            for name, value in limits.items():
                resource.setrlimit(getattr(resource, name), (value, value))

        return apply

    def environment(
        self, *, home: Path, tmpdir: Path, bootstrap: Path, network_log: Path, marker: Path
    ) -> dict[str, str]:
        """Build the child's environment: allowlist, then the sandbox's own variables.

        ``HOME`` and ``TMPDIR`` point inside the sandbox root, so a script that
        writes a cache or a temp file leaves the machine untouched and its output is
        captured by the ``files_written`` snapshot.
        """
        env = {name: os.environ[name] for name in self.env_allowlist if name in os.environ}
        env.update(ENV_OVERRIDES)
        env["HOME"] = str(home)
        env["TMPDIR"] = str(tmpdir)
        env["PYTHONPATH"] = str(bootstrap)
        env[NETWORK_ENV] = self.network.value
        env[MARKER_ENV] = str(marker)
        if self.network is NetworkPolicy.BLOCKED:
            env[NETWORK_LOG_ENV] = str(network_log)
        return env

    def describe(self) -> dict[str, Any]:
        """A JSON-safe, machine-independent snapshot recorded into the trace.

        Contains no absolute paths and nothing read from ``os.environ``, so two runs
        of the same script on different machines describe the same policy.
        """
        return {
            "runner": "sandbox",
            "timeout_seconds": self.timeout_seconds,
            "network": self.network.value,
            "network_guard": (
                "in-process socket guard; cooperative, bypassable, not a boundary"
                if self.network is NetworkPolicy.BLOCKED
                else "none"
            ),
            "working_directory": (
                "fresh temp dir, removed after the run"
                if self.cleanup
                else "fresh temp dir, kept for inspection"
            ),
            "stdin": "closed",
            "captured": ["stdout", "stderr", "exit_code"],
            "env_allowlist": sorted(self.env_allowlist),
            "env_overrides": dict(sorted(ENV_OVERRIDES.items())),
            "resource_limits": dict(sorted(self.resource_limits().items())),
            "process_group": "killed on timeout",
            "isolation": "none — controlled fixture execution, not a security boundary",
        }


#: The policy used when a caller supplies none: block the network, limit resources,
#: clean up afterwards.
DEFAULT_POLICY = SandboxPolicy()


__all__ = [
    "BOOTSTRAP_MODULE",
    "DEFAULT_POLICY",
    "DEFAULT_TIMEOUT_SECONDS",
    "ENV_ALLOWLIST",
    "ENV_OVERRIDES",
    "MARKER_ENV",
    "MAX_CAPTURE_CHARS",
    "NETWORK_ENV",
    "NETWORK_LOG_ENV",
    "REDACTED_PATH",
    "SITECUSTOMIZE_SOURCE",
    "WORKDIR_PREFIX",
    "NetworkPolicy",
    "ResourceLimits",
    "SandboxPolicy",
    "redact",
    "truncate",
    "write_bootstrap",
]
