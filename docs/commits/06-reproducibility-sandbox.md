# Commit note — M6 Reproducibility sandbox

## Commit message

```
M6: reproducibility sandbox (policy, runner, JSONL trace)

Add the sandbox/ package, which runs a fixture script under a recorded policy and
records what happened:
- sandbox/policy.py: SandboxPolicy + ResourceLimits + NetworkPolicy, the env
  allowlist, redact(), truncate(), and the sitecustomize bootstrap injected into
  the child
- sandbox/runner.py: ExecutionResult, the ScriptRunner protocol (moved from
  checks/), SandboxScriptRunner, SandboxError, and the `run-sandbox` CLI
- sandbox/trace.py: the four sandbox.* events, record_execution, write/read_trace

Enforced: fresh temp cwd (removed after), environment scrubbed to an allowlist,
closed stdin, PYTHONHASHSEED=0 / TZ=UTC, RLIMIT_CPU/AS/FSIZE/NOFILE applied before
exec, a wall-clock timeout that SIGKILLs the whole process group, and an in-process
socket guard. NOT enforced: process isolation, namespaces, seccomp, or the network
against code that means to bypass a monkey-patch. These are REPRODUCIBILITY controls
so that a script's number came from the script and not from the machine; they are
not a security boundary, and the policy record says so in every trace.

The guard records a denied call BEFORE raising, so an attempt a script catches still
reaches network_attempts. `site` swallows exceptions from sitecustomize, so the
bootstrap writes a marker naming the policy it applied and the runner raises
SandboxError without it -- refusing to report a number under conditions that never
held. The guard installs a raising SUBCLASS of socket.socket, not a function: ssl.py
runs `class SSLSocket(socket)` at import, and a callable guard turned
`import http.client` into a baffling TypeError.

Traces are byte-identical across runs: portable command, redacted sandbox path,
sorted lists, no absolute paths in the policy. Wall-clock duration is the one
volatile value, so it is opt-in (--with-timing).

Delete SubprocessScriptRunner; wire `claimverifier run-sandbox`; move truncate/
MAX_CAPTURE_CHARS to sandbox/policy.py (re-exported). Add tests/test_sandbox.py
(61 new, 346 total) and docs/SANDBOX.md; update CHECKS, RESULTS, SAFETY,
ARTIFACT_FORMAT, README, website (index, checks, reproducibility, results,
milestones, limitations), and milestone/commit/review notes.

M5 wrote code_execution against the ScriptRunner protocol; M6 replaced the
implementation and the check changed only its default runner and two lines that
record a denied network attempt. NO VERDICT MOVED: still 18 checks over 7 fixtures,
16 pass / 1 fail / 1 inconclusive. Both code fixtures reproduce under the policy.
```

## What this commit adds

- A sandbox that makes a reproduction result *mean* something: the script cannot see
  the repository, cannot read the host's environment, cannot silently reach the
  network, cannot outlive its timeout, and cannot exhaust the machine.
- A policy object that is recorded verbatim into the trace, ahead of the number —
  including the sentence `isolation: "none — controlled fixture execution, not a
  security boundary"`, so the machine-readable record is no more flattering than the
  prose.
- A network guard that **records before it refuses**, so a swallowed attempt still
  reaches the trace, and whose own installation is **verified** rather than assumed.
- A byte-reproducible JSONL trace, with wall-clock duration deliberately excluded.
- `claimverifier run-sandbox`, offline, with `--allow-network` (stop blocking, and
  record that we did), `--timeout`, `--code-id`, and `--with-timing`.

## Deliberately excluded (per the operating principles)

- **Any claim of isolation.** No namespace, no seccomp, no chroot, no user separation.
  The guard is a monkey-patch inside the child's own interpreter and `ctypes`, a raw
  syscall, or a reference captured before it installed all evade it. It catches
  accidents by trusted code; it does not contain hostile code. Said in the package
  docstring, `docs/SANDBOX.md`, `docs/CHECKS.md`, `docs/SAFETY.md`, the website, and
  the policy record itself.
- **Proxy environment variables.** `http_proxy` / `no_proxy` would deter nothing the
  socket guard does not already stop, and would imply a boundary that does not exist.
- **An authoritative `entrypoint`.** The M5 review asked. Parsing
  `"python compute_accuracy.py"` into a command would let a task file name an arbitrary
  program to run. It stays documentation; the runner invokes the current interpreter on
  the artifact's `path`, already confined to the repo by `resolve_fixture_path`.
- **Staging declared inputs.** Only the script is copied in. `CodeArtifact` has no
  `inputs` field, so a copier would be machinery for a caller that cannot exist yet.
  Named as untouched work; both fixtures embed their data.
- **Interpreter pinning.** The script runs under `sys.executable` and the trace does not
  record the version, so two machines can disagree. `failed_environment` exists in the
  vocabulary for exactly this. Documented, not silently ignored.
- **Timing in the deterministic trace.** Measured, printed with `--with-timing`, omitted
  otherwise. Recording it by default would make every trace differ from every other.
- **`RLIMIT_NPROC`.** It counts every process of the real UID, not the child's
  descendants; on a busy machine it fails for reasons unrelated to the script.
- **Keeping `SubprocessScriptRunner`.** A strictly weaker runner kept for fallback would
  be dead code. The sandbox degrades where `resource` is unavailable and reports that it
  did (`resource_limits: {}`), rather than claiming a limit it never set.
- **New dependencies.** `subprocess`, `tempfile`, `shutil`, `signal`, `resource`, `time`
  from the stdlib.

## Verification performed at commit time

- `python3 -m pytest -q` → 346 passed (285 prior + 61 new).
- `ruff check .` → all checks passed.
- `python3 scripts/01_validate_fixtures.py` → 7 ok, 0 failed, 0 warnings (exit 0).
- `python3 scripts/00_check_environment.py` → exit 0 (`READY`).
- `claimverifier run-checks` re-run over all seven tasks under the new runner → 18
  checks (16 pass, 1 fail, 1 inconclusive), identical to M5.
- `claimverifier run-sandbox` on both code tasks → exit 0, `accuracy=0.80` /
  `gc_content=0.50`, no network attempts, no files written; `--out` writes
  `<task_id>.sandbox.jsonl` under the gitignored `results/runs/`; two runs produce a
  byte-identical trace.
- `python3 -m scientific_claim_verifier.cli run-sandbox` → runs without an editable
  install (test-pinned as a subprocess).
- Static site served locally on port 9002; all 11 pages fetched via Python's `urllib`
  (no `curl`/`wget`, per the permission policy), HTML tag balance and internal links
  checked.
- `git status` clean after commit.
