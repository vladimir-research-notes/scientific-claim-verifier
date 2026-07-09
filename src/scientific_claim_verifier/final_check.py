"""Milestone 13 — the definition of done, executed rather than asserted.

``docs/PLAN.md`` §11 lists the conditions under which this repository is finished.
``CLAUDE.md`` lists what must never enter it. Both are prose, and prose does not fail a
build. A final milestone whose output is a person reporting that they read the prose,
ran the commands, and were satisfied leaves behind nothing a later reader can re-run —
which is what this repository's own quality bar forbids: *every substantive claim must be
backed by a test, a reproducible example, a trace, a result table, a documented
limitation, or an explicit non-goal.*

So the definition of done is a program. ``claimverifier final-check`` runs the checks in
:data:`CHECKS`, prints one line per check, and exits non-zero if any of them fails **or if
any of them did not run**. It is the move Milestone 8 made on the suite and Milestone 12
made on the docs: the claim and the artifact that substantiates it are the same object.

Two groups, from two documents
------------------------------
``quality-gate`` checks come from ``docs/PLAN.md`` §11 — is the system finished?
``hygiene`` checks come from ``CLAUDE.md`` — did anything enter the repository that never
should have? Hygiene is checked against **what git tracks**, not against the working
directory. ``.gitignore`` governs what git will *add*; it says nothing about what is
already committed, and a rule written after the fact does not retract a file. The tracked
set is the set that matters, so it is the one the gate reads.

Every check is sensitive
------------------------
A gate that cannot fail proves nothing when it passes. Each check is a function of data a
test can fabricate — a list of paths, a size table, a decoded file, a suite run — so
``tests/test_final_check.py`` hands each one an input it must reject, and asserts that it
does. The two checks that shell out (``pytest``, ``ruff``) are split into a subprocess
call and a pure verdict on its exit code, and the pure half is tested the same way.

Nothing is exempt from the scan it performs, the secret scanner least of all: the fake
credentials in its tests are assembled at run time from fragments, so no committed file —
not this module, not its test — contains a string the scanner would match. Excluding a
file from a secret scan is how a secret survives one.

What this gate cannot do
------------------------
1. **It cannot prove that nothing was pushed.** ``docs/PLAN.md`` §11 asks for a clean tree
   *and* an unpushed history. The first is checkable; the second is not, from inside. The
   gate reads the tree, contacts no remote, and inspects no remote ref — ``CLAUDE.md``'s
   permission policy denies ``git push`` and ``git remote`` outright. Absence of a push is
   enforced by the sandbox the agent runs in, not by this file.
2. **It cannot decide that a fixture paper is synthetic.** "Fixtures are synthetic or open"
   is a judgment about provenance that no program makes. The gate checks the mechanical
   shadow of it — every committed file is small, none matches a credential pattern, and
   the only committed model responses regenerate byte-for-byte from committed source — and
   stops there. ``docs/LIMITATIONS.md`` says so where a reader will look.
3. **It sees imports, not behaviour.** :func:`nothing_imports_a_network_client` parses the
   AST of every module under ``src/``, ``scripts/``, and ``tests/`` and finds no network
   client. That is a claim about *import statements*, so the gate also refuses any
   dynamic-import mechanism (``importlib``, ``__import__``, ``exec``, ``eval``,
   ``compile``) that could hide one, unless the site is named in
   :data:`DYNAMIC_IMPORT_ALLOWLIST` with a reason. Exactly one such site exists. Together
   those two facts bound the process; they say nothing about a child, and nothing about a
   syscall.
4. **The sandbox's child imports ``socket`` on purpose.**
   :data:`~scientific_claim_verifier.sandbox.policy.SITECUSTOMIZE_SOURCE` is a *string* of
   Python that the sandboxed child runs at startup, in order to replace ``socket``'s entry
   points with stubs that raise. An AST audit of this package does not see inside that
   string, and should not: the parent never runs it. That guard is cooperative, and
   ``docs/SANDBOX.md`` says so. This gate neither restates that claim nor strengthens it.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import suite
from .adapters import RECORDED_MODEL, build_adapter, cost, fixtures, recorded_llm
from .artifacts import loader, validation
from .reports import reader, render
from .schemas import CheckStatus, CheckType, VerificationCheck

# ---------------------------------------------------------------------------
# Groups, and the documents that require them
# ---------------------------------------------------------------------------

#: A condition from ``docs/PLAN.md`` §11 — "the repo is complete only when all hold".
GATE = "quality-gate"

#: A rule from ``CLAUDE.md`` — "what must never be committed".
HYGIENE = "hygiene"

PLAN = "docs/PLAN.md §11"
PLAN_M13 = "docs/PLAN.md §9 (M13)"
CLAUDE = "CLAUDE.md"

# ---------------------------------------------------------------------------
# Thresholds. Each is a tripwire, not a target: the repository sits far below every
# one of them, and a milestone that approaches one has changed what this repo is.
# ---------------------------------------------------------------------------

#: ``docs/PLAN.md`` §11: "the smoke suite runs fully offline with >= 8 tasks end to end".
MIN_SUITE_TASKS = 8

#: No single tracked file may exceed this. The largest today is ``docs/RESULTS.md``.
MAX_FILE_BYTES = 256 * 1024

#: Nor may the tracked tree as a whole. A checkout is source, small fixtures, and prose.
MAX_TRACKED_BYTES = 4 * 1024 * 1024

#: A document that "explains" something cannot be checked. Its length can, as a floor.
MIN_DOC_CHARS = 1500

#: Seconds allowed to each shelled-out command. ``pytest`` is the slow one (~25 s).
GIT_TIMEOUT = 30.0
LINT_TIMEOUT = 300.0
TEST_TIMEOUT = 1800.0

# ---------------------------------------------------------------------------
# Hygiene rules (CLAUDE.md, "What must never be committed")
# ---------------------------------------------------------------------------

#: Path components that must not appear anywhere in a tracked path, and why.
FORBIDDEN_SEGMENTS: dict[str, str] = {
    "__pycache__": "bytecode cache",
    ".pytest_cache": "test cache",
    ".ruff_cache": "lint cache",
    ".mypy_cache": "type-checker cache",
    ".venv": "virtualenv",
    "venv": "virtualenv",
    "node_modules": "node dependencies",
    "site-packages": "installed dependencies",
    ".eggs": "packaging cache",
}

#: Globs matched against a tracked path from the right (``PurePosixPath.match``), and why.
FORBIDDEN_GLOBS: tuple[tuple[str, str], ...] = (
    (".env", "environment file"),
    (".env.*", "environment file"),
    ("*.key", "private key"),
    ("*.pem", "PEM-encoded key or certificate"),
    ("*.p12", "PKCS#12 key store"),
    ("*.pfx", "PKCS#12 key store"),
    ("id_rsa", "SSH private key"),
    ("id_dsa", "SSH private key"),
    ("id_ecdsa", "SSH private key"),
    ("id_ed25519", "SSH private key"),
    ("secrets.*", "secrets file"),
    (".claude/settings.local.json", "personal permission overrides"),
    ("*.pyc", "compiled bytecode"),
    ("*.log", "log file"),
    ("*.bin", "model weights"),
    ("*.pt", "model weights"),
    ("*.onnx", "model weights"),
    ("*.gguf", "model weights"),
    ("*.safetensors", "model weights"),
    ("*.h5", "model weights"),
    ("*.ckpt", "model weights"),
    ("*.parquet", "large dataset"),
    ("*.cache.json", "LLM response cache"),
)

#: Tracked paths under these prefixes are runtime output, never source.
FORBIDDEN_PREFIXES: tuple[tuple[str, str], ...] = (
    ("results/cache/", "LLM response cache"),
    ("logs/", "run logs"),
)

#: High-signal credential shapes. Each is a *regex*, and no regex here matches its own
#: source text, so this module is scanned like every other file rather than exempted.
SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    ("aws-access-key-id", r"AKIA[0-9A-Z]{16}"),
    ("private-key-block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("anthropic-api-key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("openai-api-key", r"sk-[A-Za-z0-9]{32,}"),
    ("github-token", r"gh[pousr]_[A-Za-z0-9]{36}"),
    ("google-api-key", r"AIza[0-9A-Za-z_\-]{35}"),
    ("slack-token", r"xox[baprs]-[0-9A-Za-z\-]{10,}"),
    (
        "assigned-credential",
        r"""(?i)\b(?:password|passwd|api_key|apikey|secret_key)\s*[:=]\s*['"][^'"\s]{8,}['"]""",
    ),
)

# ---------------------------------------------------------------------------
# Static-audit rules (PLAN §11: "CPU-only and offline", "no paid API")
# ---------------------------------------------------------------------------

#: Top-level modules that speak a network protocol. ``html`` is not one of them, and
#: neither is ``subprocess``: the sandbox runs children by design (Milestone 6), and its
#: network policy is a separate, cooperative guard documented in ``docs/SANDBOX.md``.
NETWORK_MODULES: frozenset[str] = frozenset(
    {
        "socket",
        "_socket",
        "ssl",
        "http",
        "urllib",
        "urllib3",
        "requests",
        "httpx",
        "aiohttp",
        "ftplib",
        "poplib",
        "imaplib",
        "smtplib",
        "telnetlib",
        "xmlrpc",
        "webbrowser",
    }
)

#: Calls that can import a module the AST audit cannot see. Every occurrence in an
#: audited directory must be named in :data:`DYNAMIC_IMPORT_ALLOWLIST`.
DYNAMIC_IMPORT_CALLS: frozenset[str] = frozenset(
    {"exec", "eval", "compile", "__import__", "importlib.import_module", "importlib.__import__"}
)

#: The dynamic-import sites this repository knowingly ships, and why each is admissible.
#: A new one fails the gate until a human writes its reason here.
DYNAMIC_IMPORT_ALLOWLIST: dict[str, str] = {
    "src/scientific_claim_verifier/envcheck.py": (
        "probes whether the optional analysis libraries are installed, by name, from a "
        "committed list; it can import nothing a reader cannot see in that list"
    ),
}

#: HTTP clients that must not be declared as dependencies.
HTTP_CLIENT_PACKAGES: tuple[str, ...] = ("requests", "httpx", "aiohttp", "urllib3")

#: The four subjects ``docs/PLAN.md`` §11 requires the documentation to explain.
REQUIRED_DOCS: dict[str, str] = {
    "METHODOLOGY.md": "methodology",
    "LIMITATIONS.md": "limitations",
    "SAFETY.md": "safety",
    "REPRODUCIBILITY.md": "reproduction",
}

#: Directories whose ``*.py`` files are audited: what a user runs, and what ``pytest``
#: imports. Fixture scripts under ``data/`` are inputs to the sandbox, not the pipeline.
AUDITED_DIRS: tuple[str, ...] = ("src", "scripts", "tests")

#: A ``code_execution`` check in this state means the sandbox never started a process.
NOT_EXECUTED = CheckStatus.SKIPPED

#: A check in one of these states ran to a computed answer. ``inconclusive`` means the
#: method could not decide, ``skipped`` that it never ran, and ``error`` that the subject
#: failed — which for a recomputation means no number was produced.
COMPUTED: tuple[CheckStatus, ...] = (CheckStatus.PASS, CheckStatus.FAIL)

#: The environment variable ``pytest`` sets in every test process. Its presence is how
#: :func:`tests_pass` knows it is about to recurse into itself.
PYTEST_MARKER = "PYTEST_CURRENT_TEST"


class RecursionRefused(RuntimeError):
    """Raised when the gate is asked to run ``pytest`` from inside ``pytest``."""


class GitUnavailable(RuntimeError):
    """Raised when git cannot answer a question the hygiene checks need answered."""


# ---------------------------------------------------------------------------
# The registry. A check that is not declared here cannot report an outcome.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckSpec:
    """One declared check: what it is called, which document demands it, what it means."""

    name: str
    group: str
    requirement: str
    summary: str
    shells_out: bool = False


CHECKS: tuple[CheckSpec, ...] = (
    # docs/PLAN.md §11, in the order the plan lists its bullets.
    CheckSpec("tests_pass", GATE, PLAN, "`python3 -m pytest -q` exits 0", shells_out=True),
    CheckSpec(
        "lint_is_clean", GATE, PLAN_M13, "`python3 -m ruff check .` exits 0", shells_out=True
    ),
    CheckSpec(
        "nothing_imports_a_network_client",
        GATE,
        PLAN,
        "no audited module imports a network client, and none can hide one",
    ),
    CheckSpec("fixtures_validate", GATE, PLAN, "every committed task and suite file validates"),
    CheckSpec(
        "smoke_suite_runs_offline",
        GATE,
        PLAN,
        f"the suite runs >= {MIN_SUITE_TASKS} tasks end to end and its gate passes",
    ),
    CheckSpec(
        "reports_render_from_traces",
        GATE,
        PLAN,
        "one report per claim is rendered from the run's JSONL traces alone",
    ),
    CheckSpec(
        "dataset_statistic_recomputed",
        GATE,
        PLAN,
        "at least one dataset-statistic claim is recomputed from its CSV",
    ),
    CheckSpec(
        "table_claim_checked", GATE, PLAN, "at least one table claim is checked against its table"
    ),
    CheckSpec(
        "code_reproduction_executed",
        GATE,
        PLAN,
        "at least one fixture script is executed in the sandbox",
    ),
    CheckSpec(
        "docs_explain_the_system",
        GATE,
        PLAN,
        "methodology, limitations, safety, and reproduction are documented and reachable",
    ),
    CheckSpec(
        "default_path_needs_no_paid_api",
        GATE,
        PLAN,
        "the api adapter is built disabled, dry-run, unpriced, and transport-less",
    ),
    CheckSpec("working_tree_is_clean", GATE, PLAN, "`git status --porcelain` is empty"),
    # CLAUDE.md, "What must never be committed".
    CheckSpec(
        "no_forbidden_paths",
        HYGIENE,
        CLAUDE,
        "no secret, credential, cache, virtualenv, weight, or log file is tracked",
    ),
    CheckSpec(
        "no_oversized_files",
        HYGIENE,
        CLAUDE,
        f"no tracked file exceeds {MAX_FILE_BYTES // 1024} KiB",
    ),
    CheckSpec(
        "repository_stays_small",
        HYGIENE,
        CLAUDE,
        f"the tracked tree stays under {MAX_TRACKED_BYTES // (1024 * 1024)} MiB",
    ),
    CheckSpec(
        "no_secret_material",
        HYGIENE,
        CLAUDE,
        "no tracked file contains a string shaped like a credential",
    ),
    CheckSpec(
        "no_paid_api_outputs",
        HYGIENE,
        CLAUDE,
        "the only committed model responses are hand-authored and regenerate byte-for-byte",
    ),
)

#: Name -> spec. Consulted by :func:`_outcome`, so the registry is load-bearing rather
#: than decorative: a check that forgets to declare itself cannot report anything.
SPECS: dict[str, CheckSpec] = {spec.name: spec for spec in CHECKS}

#: Name -> position, so a report reads in the order the plan argues.
ORDER: dict[str, int] = {spec.name: i for i, spec in enumerate(CHECKS)}


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckOutcome:
    """What one check found. ``evidence`` names the offenders; a count alone explains nothing."""

    name: str
    group: str
    requirement: str
    ok: bool
    detail: str
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "group": self.group,
            "requirement": self.requirement,
            "ok": self.ok,
            "detail": self.detail,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class FinalCheckReport:
    """Every outcome of one run of the gate.

    ``ok`` requires both that nothing failed **and** that nothing was skipped. A partial
    run is not a passing run: ``--no-subprocess`` omits two checks, and a report that
    omitted them while printing ``PASS`` would be the exact failure this module exists to
    prevent.
    """

    outcomes: tuple[CheckOutcome, ...] = ()
    repo_root: Path | None = None

    @property
    def failures(self) -> tuple[CheckOutcome, ...]:
        return tuple(o for o in self.outcomes if not o.ok)

    @property
    def ran(self) -> frozenset[str]:
        return frozenset(o.name for o in self.outcomes)

    @property
    def not_run(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in CHECKS if spec.name not in self.ran)

    @property
    def complete(self) -> bool:
        """True when every declared check produced an outcome."""
        return not self.not_run

    @property
    def all_passed(self) -> bool:
        """True when nothing that ran failed. Says nothing about what did not run."""
        return not self.failures

    @property
    def ok(self) -> bool:
        return self.all_passed and self.complete

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "complete": self.complete,
            "all_passed": self.all_passed,
            "n_checks": len(self.outcomes),
            "n_declared": len(CHECKS),
            "not_run": list(self.not_run),
            "outcomes": [o.to_dict() for o in self.outcomes],
        }


def _outcome(name: str, ok: bool, detail: str, evidence: Iterable[str] = ()) -> CheckOutcome:
    """Build an outcome for a **declared** check. An undeclared name raises ``KeyError``."""
    spec = SPECS[name]
    return CheckOutcome(
        name=name,
        group=spec.group,
        requirement=spec.requirement,
        ok=ok,
        detail=detail,
        evidence=tuple(evidence),
    )


# ---------------------------------------------------------------------------
# Reading the repository: the questions only git can answer
# ---------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    """Run a read-only git command in ``root``. Raises :class:`GitUnavailable` on failure."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - environment
        raise GitUnavailable(f"git {' '.join(args)} could not run: {exc}") from exc
    if proc.returncode != 0:
        raise GitUnavailable(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def tracked_files(root: Path) -> tuple[str, ...]:
    """Every path git tracks, sorted. NUL-separated, so a newline in a filename cannot lie."""
    return tuple(sorted(p for p in _git(root, "ls-files", "-z").split("\0") if p))


def working_tree_status(root: Path) -> str:
    """``git status --porcelain``: empty exactly when the tree is clean."""
    return _git(root, "status", "--porcelain")


def tracked_sizes(root: Path, tracked: Sequence[str]) -> dict[str, int]:
    """Byte size of every tracked path that exists on disk."""
    sizes: dict[str, int] = {}
    for path in tracked:
        target = root / path
        if target.is_file():
            sizes[path] = target.stat().st_size
    return sizes


def tracked_texts(
    root: Path, tracked: Sequence[str], sizes: Mapping[str, int] | None = None
) -> dict[str, str]:
    """Decode every tracked file that is text. Binary files are skipped, not guessed at.

    A file too large to be source is skipped too: :func:`no_oversized_files` has already
    reported it, and scanning it again would only slow the gate down.
    """
    texts: dict[str, str] = {}
    for path in tracked:
        if sizes is not None and sizes.get(path, 0) > MAX_FILE_BYTES:
            continue
        target = root / path
        if not target.is_file():
            continue
        data = target.read_bytes()
        if b"\x00" in data[:8192]:
            continue
        texts[path] = data.decode("utf-8", errors="replace")
    return texts


# ---------------------------------------------------------------------------
# Hygiene checks (CLAUDE.md)
# ---------------------------------------------------------------------------


def forbidden_reason(path: str) -> str | None:
    """Why ``path`` must not be tracked, or ``None`` if it may be."""
    pure = PurePosixPath(path)
    for segment in pure.parts:
        if segment in FORBIDDEN_SEGMENTS:
            return FORBIDDEN_SEGMENTS[segment]
    for prefix, why in FORBIDDEN_PREFIXES:
        if path.startswith(prefix):
            return why
    for glob, why in FORBIDDEN_GLOBS:
        if pure.match(glob):
            return why
    return None


def no_forbidden_paths(tracked: Sequence[str]) -> CheckOutcome:
    """No tracked path is a secret, a credential, a cache, a virtualenv, a weight, or a log."""
    offenders = [f"{path} ({why})" for path in tracked if (why := forbidden_reason(path))]
    return _outcome(
        "no_forbidden_paths",
        ok=not offenders,
        detail=(
            f"{len(tracked)} tracked path(s), none forbidden"
            if not offenders
            else f"{len(offenders)} tracked path(s) must never be committed"
        ),
        evidence=offenders,
    )


def no_oversized_files(sizes: Mapping[str, int]) -> CheckOutcome:
    """No tracked file exceeds :data:`MAX_FILE_BYTES`."""
    offenders = [
        f"{path} ({size // 1024} KiB)"
        for path, size in sorted(sizes.items(), key=lambda kv: -kv[1])
        if size > MAX_FILE_BYTES
    ]
    largest = max(sizes.values(), default=0)
    return _outcome(
        "no_oversized_files",
        ok=not offenders,
        detail=f"largest tracked file is {largest // 1024} KiB, limit {MAX_FILE_BYTES // 1024} KiB",
        evidence=offenders,
    )


def repository_stays_small(sizes: Mapping[str, int]) -> CheckOutcome:
    """The tracked tree as a whole stays under :data:`MAX_TRACKED_BYTES`."""
    total = sum(sizes.values())
    ok = total <= MAX_TRACKED_BYTES
    return _outcome(
        "repository_stays_small",
        ok=ok,
        detail=(
            f"{total // 1024} KiB tracked across {len(sizes)} file(s), "
            f"limit {MAX_TRACKED_BYTES // 1024} KiB"
        ),
        evidence=() if ok else (f"the tracked tree is {total // 1024} KiB",),
    )


def scan_for_secrets(name: str, text: str) -> list[str]:
    """Every credential-shaped match in ``text``, as ``path:line: pattern``."""
    hits: list[str] = []
    for pattern_name, pattern in SECRET_PATTERNS:
        for match in re.finditer(pattern, text):
            line = text.count("\n", 0, match.start()) + 1
            hits.append(f"{name}:{line}: {pattern_name}")
    return hits


def no_secret_material(texts: Mapping[str, str]) -> CheckOutcome:
    """No tracked text file contains a string shaped like a credential.

    Shape, not truth. This finds things that *look* like keys. It cannot find a secret
    that looks like prose, and it will flag a fake key committed as an example. Both are
    the right failure: a repository with a plausible credential in it should stop the
    build and be read by a person.
    """
    offenders = [
        hit for name, text in sorted(texts.items()) for hit in scan_for_secrets(name, text)
    ]
    return _outcome(
        "no_secret_material",
        ok=not offenders,
        detail=(
            f"{len(texts)} tracked text file(s) scanned against "
            f"{len(SECRET_PATTERNS)} credential pattern(s)"
        ),
        evidence=offenders,
    )


def no_paid_api_outputs(root: Path, tracked: Sequence[str]) -> CheckOutcome:
    """The only committed model responses are hand-authored, and provably so.

    Three facts, each independently checkable. No response-cache file is tracked. The
    recordings file regenerates **byte for byte** from the constants in
    :mod:`~scientific_claim_verifier.adapters.fixtures` plus the current prompt template,
    so it cannot be a captured API response unless the capture is in the source too. And
    every recording names :data:`~scientific_claim_verifier.adapters.base.RECORDED_MODEL`,
    which is fictitious, so the file cannot imply that a vendor produced it.
    """
    problems: list[str] = [
        f"{path}: a response cache is tracked"
        for path in tracked
        if path.startswith("results/cache/") or ".cache.json" in path
    ]

    recordings = root / "data" / "fixtures" / "llm" / "extraction_recordings.json"
    if not recordings.is_file():
        problems.append(f"{recordings.name}: the committed recordings file is missing")
        return _outcome(
            "no_paid_api_outputs", ok=False, detail="recordings absent", evidence=problems
        )

    problems.extend(fixtures.check(recordings, tasks_dir=root / "tasks"))
    models = {rec.request.model for rec in recorded_llm.read_recordings(recordings)}
    problems.extend(
        f"a recording names a model other than the fictitious one: {model!r}"
        for model in sorted(models - {RECORDED_MODEL})
    )

    return _outcome(
        "no_paid_api_outputs",
        ok=not problems,
        detail=(
            f"{len(models)} recorded model(s), all {RECORDED_MODEL!r}; the recordings "
            "regenerate byte-for-byte from committed source"
        ),
        evidence=problems,
    )


# ---------------------------------------------------------------------------
# Quality gates (docs/PLAN.md §11)
# ---------------------------------------------------------------------------


def working_tree_is_clean(porcelain: str) -> CheckOutcome:
    """The tree has no staged, unstaged, or untracked change.

    The plan's bullet reads "working tree is clean; nothing is pushed". Only the first
    clause is checkable from here — see this module's docstring, limitation 1.
    """
    dirty = [line for line in porcelain.splitlines() if line.strip()]
    return _outcome(
        "working_tree_is_clean",
        ok=not dirty,
        detail=(
            "nothing to commit; push state is not checkable from inside"
            if not dirty
            else f"{len(dirty)} uncommitted change(s)"
        ),
        evidence=dirty,
    )


def process_verdict(name: str, command: str, returncode: int, output: str) -> CheckOutcome:
    """The pure half of a shelled-out check: an exit code, and the tail of what it said."""
    ok = returncode == 0
    tail = [line for line in output.strip().splitlines() if line.strip()][-6:]
    return _outcome(
        name, ok=ok, detail=f"`{command}` exited {returncode}", evidence=() if ok else tail
    )


def _shell_out(
    name: str, argv: Sequence[str], label: str, root: Path, timeout: float
) -> CheckOutcome:
    """Run ``argv`` in ``root`` and turn its exit code into an outcome."""
    try:
        proc = subprocess.run(
            list(argv), cwd=str(root), capture_output=True, text=True, timeout=timeout, check=False
        )
    except FileNotFoundError:  # pragma: no cover - environment
        return _outcome(name, ok=False, detail=f"`{label}` is not installed", evidence=(label,))
    except subprocess.TimeoutExpired:  # pragma: no cover - environment
        return _outcome(name, ok=False, detail=f"`{label}` timed out after {timeout:.0f}s")
    return process_verdict(name, label, proc.returncode, proc.stdout + proc.stderr)


def tests_pass(root: Path) -> CheckOutcome:
    """``pytest`` exits 0. Refuses to run inside ``pytest``, where it would not terminate."""
    if PYTEST_MARKER in os.environ:
        raise RecursionRefused(
            "tests_pass() would spawn pytest from inside pytest. Call "
            "run_checks(subprocess_checks=False) from a test; the gate runs the suite itself."
        )
    argv = [sys.executable, "-m", "pytest", "-q"]
    return _shell_out("tests_pass", argv, "python3 -m pytest -q", root, TEST_TIMEOUT)


def lint_is_clean(root: Path) -> CheckOutcome:
    """``ruff check .`` exits 0."""
    argv = [sys.executable, "-m", "ruff", "check", "."]
    return _shell_out("lint_is_clean", argv, "python3 -m ruff check .", root, LINT_TIMEOUT)


def fixtures_validate(report: validation.ValidationReport) -> CheckOutcome:
    """Every committed task and suite file validates, and there is at least one of them."""
    offenders = [f"{r.path}: {'; '.join(r.errors)}" for r in report.results if not r.ok]
    return _outcome(
        "fixtures_validate",
        ok=report.ok and bool(report.results),
        detail=(
            f"{report.n_ok} ok, {report.n_failed} failed across "
            f"{report.n_tasks} task(s) and {report.n_suites} suite(s)"
        ),
        evidence=offenders or (() if report.results else ("no task files were found",)),
    )


def smoke_suite_runs_offline(run: suite.SuiteRun, verdict: suite.Gate) -> CheckOutcome:
    """The suite runs at least :data:`MIN_SUITE_TASKS` tasks end to end, and its gate passes.

    Two conditions, one outcome, because either alone misleads: eleven tasks whose gate
    fails is a broken pipeline, and a passing gate over three tasks is not a suite.
    """
    problems = list(verdict.problems)
    if run.n_tasks < MIN_SUITE_TASKS:
        problems.append(f"the suite ran {run.n_tasks} task(s); the plan requires {MIN_SUITE_TASKS}")
    if not verdict.applicable:
        problems.append("the run skipped execution, so its gate decided nothing")
    return _outcome(
        "smoke_suite_runs_offline",
        ok=not problems,
        detail=(
            f"{run.n_tasks} task(s) end to end, gate {'PASS' if verdict.ok else 'FAIL'}, "
            f"{len(run.summary.wrong_verdicts)} wrong verdict(s)"
        ),
        evidence=problems,
    )


def _of_type(checks: Iterable[VerificationCheck], kind: CheckType) -> list[VerificationCheck]:
    return [c for c in checks if c.check_type is kind]


def dataset_statistic_recomputed(checks: Sequence[VerificationCheck]) -> CheckOutcome:
    """At least one ``dataset_statistic`` check reached a computed answer.

    ``pass`` and ``fail`` both count: a recomputation that *disagrees* with the claim has
    still recomputed it, and ``dataset_mean_overstated`` is in the suite precisely to be
    disagreed with. ``skipped`` and ``error`` do not count — no number was produced.
    """
    found = [c for c in _of_type(checks, CheckType.DATASET_STATISTIC) if c.status in COMPUTED]
    return _outcome(
        "dataset_statistic_recomputed",
        ok=bool(found),
        detail=f"{len(found)} dataset statistic(s) recomputed from committed CSVs",
        evidence=() if found else ("no dataset_statistic check reached pass or fail",),
    )


def table_claim_checked(checks: Sequence[VerificationCheck]) -> CheckOutcome:
    """At least one ``table_value`` check reached a computed answer. As above for ``fail``."""
    found = [c for c in _of_type(checks, CheckType.TABLE_VALUE) if c.status in COMPUTED]
    return _outcome(
        "table_claim_checked",
        ok=bool(found),
        detail=f"{len(found)} table value(s) checked against committed tables",
        evidence=() if found else ("no table_value check reached pass or fail",),
    )


def code_reproduction_executed(checks: Sequence[VerificationCheck]) -> CheckOutcome:
    """At least one fixture script was executed in the sandbox.

    Here ``error`` **does** count, and the difference from the two checks above is the
    point. A recomputation that errored computed nothing. A script that ran and exited
    non-zero *was executed*: ``unreproducible_accuracy`` reads a file the paper never
    released, exits 1, and its ``error`` status is the sandbox working exactly as designed.
    Only ``skipped`` means that no process ever started.
    """
    ran = [c for c in _of_type(checks, CheckType.CODE_EXECUTION) if c.status is not NOT_EXECUTED]
    reproduced = [c for c in ran if c.status is CheckStatus.PASS]
    return _outcome(
        "code_reproduction_executed",
        ok=bool(ran),
        detail=(
            f"{len(ran)} fixture script(s) executed in the sandbox, {len(reproduced)} reproduced"
        ),
        evidence=() if ran else ("every code_execution check was skipped",),
    )


def reports_render_from_traces(run_dir: Path, out_dir: Path) -> CheckOutcome:
    """One report per claim, rendered from the run's JSONL traces and nothing else.

    The renderer is handed a directory of traces, not a pipeline. If a report can be
    produced this way, the trace is self-describing — the property Milestone 9 exists to
    establish, and the reason a report can outlive the artifacts it describes.
    """
    traces = render.trace_paths(run_dir)
    if not traces:
        return _outcome(
            "reports_render_from_traces",
            ok=False,
            detail="no traces were found",
            evidence=(str(run_dir),),
        )
    try:
        reports = [reader.read_report(path) for path in traces]
        written = render.write_reports(reports, out_dir, run_dir=run_dir, fmt=render.MARKDOWN)
    except reader.ReportError as exc:
        return _outcome(
            "reports_render_from_traces",
            ok=False,
            detail="a trace would not render",
            evidence=(str(exc),),
        )

    expected = len(traces) + 1  # one report per claim, plus the index
    ok = len(written) == expected and all(p.is_file() and p.stat().st_size > 0 for p in written)
    return _outcome(
        "reports_render_from_traces",
        ok=ok,
        detail=f"{len(reports)} report(s) + index rendered from {len(traces)} trace(s)",
        evidence=() if ok else (f"expected {expected} files, wrote {len(written)}",),
    )


def docs_explain_the_system(root: Path) -> CheckOutcome:
    """The four subjects the plan names are documented, non-trivial, and linked from the README.

    "Explains" is a judgment no test can make. Existence, a length floor, and a path from
    the README are its mechanical shadow: enough to catch a document that was deleted,
    emptied, or orphaned, and honest about being nothing more than that.
    """
    readme = (root / "README.md").read_text(encoding="utf-8")
    problems: list[str] = []
    for name, subject in sorted(REQUIRED_DOCS.items()):
        path = root / "docs" / name
        if not path.is_file():
            problems.append(f"{subject}: docs/{name} does not exist")
            continue
        chars = len(path.read_text(encoding="utf-8"))
        if chars < MIN_DOC_CHARS:
            problems.append(
                f"{subject}: docs/{name} is {chars} chars, under a {MIN_DOC_CHARS} floor"
            )
        if f"docs/{name}" not in readme:
            problems.append(f"{subject}: docs/{name} is not linked from the README")
    subjects = ", ".join(sorted(REQUIRED_DOCS.values()))
    return _outcome(
        "docs_explain_the_system",
        ok=not problems,
        detail=f"{len(REQUIRED_DOCS)} required document(s): {subjects}",
        evidence=problems,
    )


# ---------------------------------------------------------------------------
# The static audit
# ---------------------------------------------------------------------------


def _dotted_call(node: ast.Call) -> str | None:
    """The dotted name of a call's target: ``exec``, ``importlib.import_module``, ..."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    parts: list[str] = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
        return ".".join(reversed(parts))
    return None


def audit_module(source: str) -> tuple[set[str], set[str]]:
    """``(network modules imported, dynamic-import calls made)`` for one module's source.

    Import statements only. A name inside a string constant is not an import — which is
    why :data:`~scientific_claim_verifier.sandbox.policy.SITECUSTOMIZE_SOURCE`, a string of
    code the *sandboxed child* runs to disable ``socket``, is correctly invisible here.
    Dynamic-import calls come back alongside, because they are the one way a module could
    import something these statements do not show.
    """
    tree = ast.parse(source)
    imported: set[str] = set()
    dynamic: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module)
        elif isinstance(node, ast.Call):
            name = _dotted_call(node)
            if name in DYNAMIC_IMPORT_CALLS:
                dynamic.add(name)
    network = {name for name in imported if name.split(".")[0] in NETWORK_MODULES}
    return network, dynamic


def audited_sources(root: Path) -> list[Path]:
    """Every ``*.py`` file under :data:`AUDITED_DIRS`, sorted."""
    return sorted(p for name in AUDITED_DIRS for p in (root / name).rglob("*.py"))


def nothing_imports_a_network_client(root: Path) -> CheckOutcome:
    """No audited module imports a network client, and none can hide one behind a dynamic import."""
    sources = audited_sources(root)
    problems: list[str] = []
    dynamic_sites = 0

    for path in sources:
        rel = path.relative_to(root).as_posix()
        network, dynamic = audit_module(path.read_text(encoding="utf-8"))
        problems.extend(f"{rel}: imports {name}" for name in sorted(network))
        if dynamic:
            dynamic_sites += 1
            if rel not in DYNAMIC_IMPORT_ALLOWLIST:
                problems.extend(
                    f"{rel}: calls {name}, which can import a module this audit cannot see. "
                    "Add it to DYNAMIC_IMPORT_ALLOWLIST with a reason, or remove it."
                    for name in sorted(dynamic)
                )

    present = {p.relative_to(root).as_posix() for p in sources}
    problems.extend(
        f"{rel}: allowlisted for dynamic imports, but no such module exists"
        for rel in sorted(set(DYNAMIC_IMPORT_ALLOWLIST) - present)
    )

    return _outcome(
        "nothing_imports_a_network_client",
        ok=not problems,
        detail=(
            f"{len(sources)} module(s) audited across {'/, '.join(AUDITED_DIRS)}/, "
            f"0 network imports, {dynamic_sites} allowlisted dynamic-import site(s)"
        ),
        evidence=problems,
    )


def default_path_needs_no_paid_api(root: Path) -> CheckOutcome:
    """The paid adapter is built disabled, dry-run, unpriced, and without a transport.

    Four independent refusals, and the two facts underneath them: no vendor model carries
    a price, so nothing can be costed; no HTTP client is declared, so nothing could be
    sent. Constructing the adapter here is safe by that same argument — it is a stub.
    """
    problems: list[str] = []

    adapter = build_adapter("api")
    if adapter.enabled:
        problems.append("build_adapter('api') returned an enabled adapter")
    if not adapter.dry_run:
        problems.append("build_adapter('api') returned an adapter that is not in dry-run")
    if adapter.transport is not None:
        problems.append("build_adapter('api') returned an adapter with a transport")
    if adapter.guard.max_usd != 0.0:
        problems.append(f"the default cost guard admits ${adapter.guard.max_usd}")
    if adapter.opted_in():
        problems.append("the adapter reports itself opted in under the ambient environment")

    problems.extend(
        f"a model carries a non-zero price: {model!r}"
        for model, price in sorted(cost.price_table().items())
        if price.prompt_usd_per_1k or price.completion_usd_per_1k
    )

    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8").lower()
    declared = pyproject.split("dependencies", 1)[-1].split("[project.scripts]", 1)[0]
    problems.extend(
        f"pyproject.toml declares an HTTP client: {client}"
        for client in HTTP_CLIENT_PACKAGES
        if client in declared
    )

    return _outcome(
        "default_path_needs_no_paid_api",
        ok=not problems,
        detail=(
            f"api adapter disabled, dry-run, transport-less, ${adapter.guard.max_usd:.2f} guard; "
            f"{len(cost.price_table())} model(s) priced, all free"
        ),
        evidence=problems,
    )


# ---------------------------------------------------------------------------
# Running them all
# ---------------------------------------------------------------------------


def run_checks(
    repo_root: str | Path | None = None,
    *,
    subprocess_checks: bool = True,
) -> FinalCheckReport:
    """Run the gate. Returns every outcome, in the order :data:`CHECKS` declares them.

    ``subprocess_checks=False`` omits ``tests_pass`` and ``lint_is_clean``, which is how a
    test calls this without recursing into its own runner. The resulting report can be
    ``all_passed`` but is never ``ok``, because two declared checks did not run.

    The suite runs into a temporary directory and its reports are rendered there, so the
    gate reads the repository and writes nothing back into it.
    """
    if subprocess_checks and PYTEST_MARKER in os.environ:
        raise RecursionRefused(
            "run_checks(subprocess_checks=True) would spawn pytest from inside pytest. "
            "Pass subprocess_checks=False; the gate still runs the suite itself."
        )

    root = Path(repo_root) if repo_root is not None else loader.find_repo_root(Path(__file__))
    outcomes: list[CheckOutcome] = []

    tracked = tracked_files(root)
    sizes = tracked_sizes(root, tracked)
    outcomes.append(no_forbidden_paths(tracked))
    outcomes.append(no_oversized_files(sizes))
    outcomes.append(repository_stays_small(sizes))
    outcomes.append(no_secret_material(tracked_texts(root, tracked, sizes)))
    outcomes.append(no_paid_api_outputs(root, tracked))
    outcomes.append(working_tree_is_clean(working_tree_status(root)))

    outcomes.append(fixtures_validate(validation.validate_tasks(root / "tasks", repo_root=root)))
    outcomes.append(docs_explain_the_system(root))
    outcomes.append(nothing_imports_a_network_client(root))
    outcomes.append(default_path_needs_no_paid_api(root))

    with tempfile.TemporaryDirectory(prefix="scv-final-check-") as tmp:
        run_dir = Path(tmp) / "run"
        loaded = loader.load_suite(root / suite.DEFAULT_SUITE)
        run = suite.run_suite(loaded, out_dir=run_dir, repo_root=root)
        verdict = suite.gate(run)
        checks = [c for record in run.records for c in record.scored.result.computed_checks]

        outcomes.append(smoke_suite_runs_offline(run, verdict))
        outcomes.append(reports_render_from_traces(run_dir, Path(tmp) / "reports"))
        outcomes.append(dataset_statistic_recomputed(checks))
        outcomes.append(table_claim_checked(checks))
        outcomes.append(code_reproduction_executed(checks))

    if subprocess_checks:
        outcomes.append(lint_is_clean(root))
        outcomes.append(tests_pass(root))

    outcomes.sort(key=lambda outcome: ORDER[outcome.name])
    return FinalCheckReport(outcomes=tuple(outcomes), repo_root=root)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_MARK = {True: "pass", False: "FAIL"}

#: Evidence lines printed per failing check before the list is elided.
MAX_EVIDENCE_LINES = 8

_TITLES = ((GATE, "Quality gates — docs/PLAN.md §11"), (HYGIENE, "Hygiene — CLAUDE.md"))


def format_report(report: FinalCheckReport) -> str:
    """Render a report as a plain-text block, grouped by the document that demands each check."""
    lines = [
        "scientific-claim-verifier — final check",
        "=" * 46,
        f"Repo root : {report.repo_root}",
        "",
    ]
    for group, title in _TITLES:
        lines.append(title)
        lines.append("-" * len(title))
        for outcome in (o for o in report.outcomes if o.group == group):
            lines.append(f"  [{_MARK[outcome.ok]}] {outcome.name}")
            lines.append(f"         {outcome.detail}")
            lines.extend(f"         - {item}" for item in outcome.evidence[:MAX_EVIDENCE_LINES])
            if len(outcome.evidence) > MAX_EVIDENCE_LINES:
                lines.append(f"         - (+{len(outcome.evidence) - MAX_EVIDENCE_LINES} more)")
        lines.append("")

    if report.not_run:
        lines.append(f"Not run   : {', '.join(report.not_run)}")
    lines.append(
        f"Checks    : {len(report.outcomes)}/{len(CHECKS)} run, {len(report.failures)} failed"
    )

    if report.ok:
        lines.append("Overall   : PASS")
        lines.append("  Every condition in docs/PLAN.md §11 holds, and nothing CLAUDE.md forbids")
        lines.append("  is tracked. Push state is not checkable from here; see final_check.py.")
    elif not report.complete:
        lines.append("Overall   : INCOMPLETE — a partial run is not a passing run")
    else:
        lines.append("Overall   : FAIL")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def add_final_check_arguments(parser: argparse.ArgumentParser) -> None:
    """Arguments for ``claimverifier final-check``."""
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository to check (default: the one this package was imported from).",
    )
    parser.add_argument(
        "--no-subprocess",
        action="store_true",
        help="Skip the checks that shell out (pytest, ruff). The run is then INCOMPLETE.",
    )
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")


def check_and_report(
    *,
    repo_root: str | Path | None = None,
    subprocess_checks: bool = True,
    as_json: bool = False,
) -> int:
    """Run the gate, print it, and return the process exit code."""
    try:
        report = run_checks(repo_root, subprocess_checks=subprocess_checks)
    except (GitUnavailable, RecursionRefused) as exc:
        print(f"final-check could not run: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report.to_dict(), indent=2) if as_json else format_report(report))
    return 0 if report.ok else 1


def run_cli(argv: list[str]) -> int:
    """Run the gate and print it. Exit 0 only on a complete, fully passing run."""
    parser = argparse.ArgumentParser(
        prog="claimverifier final-check",
        description="Check every condition in docs/PLAN.md §11 and CLAUDE.md (offline).",
    )
    add_final_check_arguments(parser)
    args = parser.parse_args(argv)
    return check_and_report(
        repo_root=args.repo_root, subprocess_checks=not args.no_subprocess, as_json=args.json
    )


def main(argv: list[str] | None = None) -> int:
    return run_cli(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
