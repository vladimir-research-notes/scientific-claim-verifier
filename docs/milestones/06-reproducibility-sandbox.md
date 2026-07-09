# M6 — Reproducibility sandbox

## Summary

Introduces the `sandbox/` package: a fixture script now runs under a **recorded
policy** — a fresh temp working directory, an environment scrubbed to an allowlist,
closed stdin, POSIX resource limits applied before `exec`, a wall-clock timeout that
kills the whole process group, and an in-process guard that denies and *records*
`socket` calls — and every execution emits a JSONL trace whose first event is the
policy itself.

Four ideas carry the milestone.

**These are reproducibility controls, not security controls.** The temp directory,
the scrubbed environment, and the socket guard exist so that a reproduction result
*means* something: that the number a script printed came from the script's own
contents, and not from the machine, the shell, the clock, or the network. There is no
process isolation, no namespace, no seccomp filter, and the network guard lives inside
the child's own interpreter, so anything that wants to bypass it can. That is stated
in the package docstring, in `docs/SANDBOX.md`, in `docs/CHECKS.md`, in
`docs/SAFETY.md`, on the website, and — because a policy record should not be more
flattering than the prose around it — inside the policy object itself, which carries
`isolation: "none — controlled fixture execution, not a security boundary"` into every
trace.

**The guard records the attempt before it refuses it.** A script that catches the
guard's exception and carries on still leaves the denied call in `network_attempts`,
so a reproduction that reached for the network cannot look self-contained in the
trace. The `code_execution` check copies the attempts into its `inputs` and says so in
its notes, on every outcome.

**The guard's installation is verified, not assumed.** `site.execsitecustomize()`
catches *every* exception raised by `sitecustomize`, prints one line to stderr, and
lets the interpreter continue. A broken guard would therefore leave the network open
while the trace recorded `blocked`. So the bootstrap writes a marker file, last,
naming the policy it applied; the runner raises `SandboxError` if it is missing or
disagrees; and the check maps that to `error`, never to a verdict about the claim's
number, because the conditions that number would be attributed to never held.

**The protocol held.** M5 wrote `code_execution` against a `ScriptRunner` protocol and
shipped a bare `subprocess.run` behind it, promising that "a check written against
`ScriptRunner` needs no change when [M6] lands." M6 replaced the implementation and
the check's only edits were its default runner and two lines recording a denied
network attempt. **No verdict moved**: the check table is still 18 checks over 7
fixtures, 16 pass / 1 fail / 1 inconclusive.

## Deliverables

- **`src/scientific_claim_verifier/sandbox/`** (new package, per `docs/PLAN.md` §5):
  - `policy.py` — `SandboxPolicy`, `ResourceLimits`, `NetworkPolicy`, the
    environment allowlist, `redact`, `truncate`, and `SITECUSTOMIZE_SOURCE` (the
    bootstrap injected into the child).
  - `runner.py` — `ExecutionResult`, the `ScriptRunner` protocol (moved here from
    `checks/`), `SandboxScriptRunner`, `SandboxError`, and the `run-sandbox` CLI.
  - `trace.py` — the four `sandbox.*` events, `record_execution`, `write_trace`,
    `read_trace`.
- **`checks/code_execution.py`** — default runner is now the sandbox;
  `SubprocessScriptRunner` deleted; a `SandboxError` becomes `error`; denied network
  attempts reach `inputs` and `notes`. `ExecutionResult`/`ScriptRunner` re-exported
  so the module's public surface is unchanged.
- **`checks/__init__.py`** — `truncate` / `MAX_CAPTURE_CHARS` moved to
  `sandbox/policy.py` (capping a child's output is the sandbox's business) and
  re-exported.
- **CLI:** `claimverifier run-sandbox --task X [--out DIR] [--json] [--code-id ID]
  [--timeout S] [--allow-network] [--with-timing]`.
- **Tests:** `tests/test_sandbox.py` (61). Three low-level runner tests moved out of
  `tests/test_checks.py` and replaced by three that pin the new contract. 346 total.
- **Docs:** `docs/SANDBOX.md` (new); `CHECKS`, `RESULTS`, `SAFETY`, `ARTIFACT_FORMAT`,
  `README` updated.
- **Website:** `index`, `checks`, `reproducibility`, `results`, `milestones`,
  `limitations`.

## Design decisions

- **The network guard installs a raising *subclass*, not a raising function.** The
  first implementation replaced `socket.socket` with a function. `ssl.py` executes
  `class SSLSocket(socket)` at import time, so `import urllib.request` died with
  `TypeError: function() argument 'code' must be code, not str` — blocking the network
  by accident, in a way that would have confused anyone whose script merely imported
  `http.client`. With a raising subclass the import succeeds and the denial happens at
  `socket.create_connection`, where the connection is actually attempted. Both
  behaviours are test-pinned.
- **No proxy environment variables.** `http_proxy` / `no_proxy` would deter nothing the
  socket guard does not already stop, and their presence in the policy record would
  imply a boundary that does not exist.
- **Timing is opt-in.** Wall-clock duration is the one fact about an execution that
  cannot be reproduced. The runner measures it, `--with-timing` prints and records it,
  and the trace omits it otherwise — so two runs of one script produce byte-identical
  JSONL and a diff between runs stays a signal. This is `CLAUDE.md`'s determinism rule
  applied to the one place it bites.
- **The timeout kills the process *group*.** `subprocess.run(timeout=...)` kills only
  the direct child, leaving a grandchild alive and holding the output pipes open. The
  child is started with `start_new_session=True` and the group is `SIGKILL`ed as a
  unit. Test-pinned with a script that spawns a sleeping grandchild.
- **`RLIMIT_NPROC` is deliberately absent.** It counts every process owned by the real
  UID rather than the child's descendants, so on a busy machine it would fail for
  reasons unrelated to the script. `RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_FSIZE`, and
  `RLIMIT_NOFILE` are set (soft = hard) via `preexec_fn`, so the child cannot raise
  them back. `preexec_fn` is unsafe in a threaded parent; the CLI and the test suite
  are single-threaded, and the docstring says so.
- **The policy is recorded, and it is machine-independent.** `describe()` contains no
  absolute paths and nothing read from `os.environ` — only the *names* of the
  allowlisted variables. Where the platform has no `resource` module it reports
  `resource_limits: {}` rather than claiming a limit it did not set.
- **The sandbox root is redacted out of captured output.** A script printing its
  working directory, or a traceback naming the bootstrap module, would otherwise write
  a random temp path into the trace. Both the literal and the resolved form are
  replaced with `<sandbox>`.
- **`entrypoint` stays declarative.** The M5 review asked whether M6 should make it
  authoritative. No: parsing `"python compute_accuracy.py"` into a command would let a
  task file name an arbitrary program to run. The runner invokes the current
  interpreter on the artifact's declared `path`, which `resolve_fixture_path` has
  already confined to the repository. Documented as a non-goal and test-pinned.
- **`SubprocessScriptRunner` was deleted, not kept.** A strictly weaker runner retained
  "for environments without `resource`" would be dead code; the sandbox degrades on
  such a platform and reports that it did.
- **Only the script is copied in.** A script needing a data file must embed it, as both
  fixtures do. `CodeArtifact` has no `inputs` field to declare one with, so staging
  inputs would be speculative machinery for a caller that cannot exist yet. Named as
  untouched work in `docs/SANDBOX.md`.
- **No new dependencies.** `subprocess`, `tempfile`, `shutil`, `signal`, `resource`,
  `time` from the stdlib.

## Validation

Commands run (CPU-only, offline):

| Command | Result |
| --- | --- |
| `python3 -m pytest -q` | 346 passed (285 prior + 61 new) |
| `ruff check .` | All checks passed |
| `python3 scripts/01_validate_fixtures.py` | 7 ok, 0 failed, 0 warnings — VALID (exit 0) |
| `python3 scripts/00_check_environment.py` | exit 0 — `READY` |
| `claimverifier run-sandbox --task <task>` | text/JSON report + JSONL trace, exit 0 |
| `claimverifier run-checks --task <task>` | 18 checks over 7 fixtures — **unchanged** |
| site served on :9002, 11 pages fetched via `urllib` | 200, balanced HTML, no broken links |

### Sandbox reproduction over the committed code fixtures

| Task | Script | stdout | Exit | Network attempts | Files written |
| --- | --- | --- | --- | --- | --- |
| `recompute_accuracy` | `compute_accuracy.py` | `accuracy=0.80` | 0 | none | none |
| `gc_content` | `gc_content.py` | `gc_content=0.50` | 0 | none | none |

Two fixtures is not a reproducibility benchmark. Both scripts are stdlib-only, embed
their own data, and were written by the same agent as the sandbox that runs them. The
informative results are the guards, each pinned by a test that fires it: a script that
cannot see `pyproject.toml`; a parent environment variable that arrives `absent`; a
`socket.socket()` that raises and is recorded; an attempt that survives being caught;
a `sitecustomize` that raises being caught as `SandboxError` rather than silently
leaving the network open; a grandchild reaped with its parent's timeout;
`bytearray(3 GiB)` → `MemoryError`; `while True: pass` killed by signal at one
CPU-second with `timed_out=False`; and two runs of one script producing byte-identical
JSONL.

The tests additionally pin: the derived CPU limit (`ceil(timeout) + 1`) and its move
under `with_timeout`; a disabled limit reported as absent rather than as a sentinel;
`describe()` holding no absolute path, no `sys.executable`, and no temp dir; the
environment allowlist and the `inherited` policy passing no log path; `redact` covering
the resolved form of a symlinked root; `PYTHONDONTWRITEBYTECODE` leaving no
`__pycache__` in `files_written`; `HOME`/`TMPDIR` landing inside the sandbox; DNS and a
bare `_socket` import both denied; `urllib` still importable under the guard; a **Python
grandchild inheriting the guard** through `PYTHONPATH` (a non-Python one does not — see
`docs/SANDBOX.md`); `files_written` missing an *overwritten* file, pinned as a known
limit; the `signal` property; `result_to_dict` timing opt-in; artifact selection and the
unknown `--code-id` error; the four trace events and their order; `write_trace` /
`read_trace` round-tripping and an empty trace writing an empty file; and eleven CLI
paths including the module entry point without an editable install.

## Status

**Complete.** Next: **M7 — Scoring & failure modes** (support-label assignment,
reproducibility status, failure-mode classification, aggregate summary, per-claim
results), which reads the checks this milestone's sandbox now feeds and draws the
inference none of them is allowed to draw.
