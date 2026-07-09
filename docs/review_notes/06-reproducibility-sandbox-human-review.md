Human review: M6 — Reproducibility sandbox

TL;DR
Milestone 6 adds the `sandbox/` package (`policy`, `runner`, `trace`): a fixture
script now runs under a recorded policy — fresh temp working directory, environment
scrubbed to an allowlist, closed stdin, `RLIMIT_CPU/AS/FSIZE/NOFILE` applied before
`exec`, a wall-clock timeout that SIGKILLs the whole process group, and an in-process
guard that denies and *records* `socket` calls — and every execution emits a JSONL
trace whose first event is the policy itself. Four decisions carry it. (1) These are
**reproducibility** controls, not security controls; there is no isolation, and the
policy object carries that sentence into every trace rather than leaving it in the
prose. (2) The guard **records an attempt before refusing it**, so a script that
catches the exception still cannot look self-contained. (3) The guard's installation is
**verified**, not assumed — `site` swallows exceptions from `sitecustomize`, so a
broken guard would leave the network open while the trace said `blocked`; a missing
marker is now a `SandboxError`, and the check reports `error` rather than attributing a
number to conditions that never held. (4) The `ScriptRunner` protocol M5 introduced
held: `code_execution` changed only its default runner and two lines recording a denied
attempt, and **no verdict moved** (still 18 checks over 7 fixtures: 16 pass, 1 fail,
1 inconclusive). Wall-clock duration is the one value the trace omits by default, so two
runs of a script produce byte-identical JSONL. 61 new tests (346 total). No new
dependencies.

What changed
- New package: src/scientific_claim_verifier/sandbox/ (policy.py with SandboxPolicy,
  ResourceLimits, NetworkPolicy, the env allowlist, redact(), truncate(), and the
  sitecustomize bootstrap source; runner.py with ExecutionResult, the ScriptRunner
  protocol, SandboxScriptRunner, SandboxError, and the `run-sandbox` CLI; trace.py with
  the four sandbox.* events, record_execution, write_trace, read_trace).
- checks/code_execution.py: `SubprocessScriptRunner` **deleted**; the default runner is
  now SandboxScriptRunner; `ExecutionResult`/`ScriptRunner` moved to sandbox/runner.py
  and re-exported; a SandboxError becomes `error`; denied network attempts reach the
  check's `inputs.network_attempts` and its notes on every outcome.
- checks/__init__.py: `truncate` / `MAX_CAPTURE_CHARS` moved to sandbox/policy.py
  (capping a child's captured output is the sandbox's concern) and re-exported, so
  `checks.truncate` still resolves. This makes checks/ import sandbox/.
- CLI: `run-sandbox --task X [--out DIR] [--json] [--code-id ID] [--timeout S]
  [--allow-network] [--with-timing]`. No numbered script: docs/PLAN.md reserves
  scripts/04_ for report generation.
- Tests: tests/test_sandbox.py (61). Three low-level `SubprocessScriptRunner` tests were
  removed from tests/test_checks.py (that behaviour now lives in test_sandbox.py) and
  replaced by three pinning the new contract: the default runner is the sandbox, a
  SandboxError is `error`, a denied network attempt is recorded.
- Docs: docs/SANDBOX.md (new); CHECKS, RESULTS, SAFETY, ARTIFACT_FORMAT, README updated.
- Website: index, checks, reproducibility, results, milestones, limitations.

What should be checked later
- **The network guard is Python-level, and the docs now say so in a table.** It covers
  the script, its imports, and (via PYTHONPATH) any *Python* subprocess it spawns —
  test-pinned. It does **not** cover `ctypes`, a raw syscall, or a **non-Python**
  subprocess: `subprocess.run(["/usr/bin/curl", …])` needs no PATH and has its own
  interpreter. Removing PATH from the allowlist would not close that. Confirm that a
  cooperative guard which catches accidents and records them is worth having, versus the
  risk that "no-network policy" in docs/PLAN.md §9 reads as a stronger promise than what
  was built. The alternative (network namespace / seccomp) is the isolation this layer
  explicitly does not provide.
- `preexec_fn` applies the rlimits. CPython documents it as unsafe in a multi-threaded
  parent, and it raises in subinterpreters. The CLI and pytest are single-threaded.
  Confirm acceptable, or move the limits into the sitecustomize bootstrap (thread-safe,
  but applied *after* interpreter startup, so RLIMIT_AS would not cover startup and the
  child could in principle skip it with `-S`).
- The rlimits are set with soft == hard, unclamped. On a host whose *hard* limit is
  already below a requested value, `setrlimit` raises and the whole run fails loudly
  rather than recording a limit it did not apply. That was the deliberate choice (a
  clamped value would also make `describe()` machine-dependent, breaking cross-machine
  trace reproducibility). Confirm; typical hard limits (NOFILE 1048576 here, AS/CPU/FSIZE
  unlimited) are far above the requested ones, so it has never fired.
- `RLIMIT_AS` is 2 GiB. Nothing today needs more, but a future numpy/pandas fixture might.
- `_verify_bootstrap` is **skipped when the run timed out**, because a SIGKILL mid-flight
  makes the marker meaningless. That means a timed-out run's `network_attempts` are read
  from a log written by a guard we did not verify. In practice a timeout fires long after
  interpreter startup. Confirm the reasoning, or find a way to verify that does not
  create a footgun for callers passing a timeout shorter than interpreter startup.
- The marker file and the network log live inside the sandbox root, reachable by absolute
  path. A script deleting the marker makes the run fail closed (verified by hand);
  truncating the log would silently hide an attempt. Trusted fixtures do neither, and a
  script that would is outside this layer's threat model — but the trace would look clean.
- `files_written` is a set difference over the work dir, so it records only files that did
  not exist before. A script that **overwrites** an existing file (including its own
  source) leaves no record. Test-pinned as a known limit. Confirm that is the wanted
  semantics rather than hashing the tree before and after.
- Nothing pins the interpreter. The script runs under `sys.executable`, and the trace does
  not record the Python version, so two machines can produce different numbers from the
  same recorded policy. `ReproductionStatus.FAILED_ENVIRONMENT` exists for this. Consider
  recording `sys.version_info` in the policy event — it would be one more machine-specific
  value in a record that currently has none, which is why it was not done.
- Captured output is verbatim apart from the sandbox root, so a **failing** script's
  traceback embeds the host's stdlib paths (`/usr/lib/python3.12/...`). Traces of failing
  runs are therefore reproducible per machine, not across machines. Redacting the
  traceback would be worse. Confirm the trade.
- stdout and stderr are captured on separate pipes, so their interleaving is lost. Fixture
  scripts print one line. Confirm no later milestone needs the merged stream.
- Output is decoded as UTF-8 with `errors="replace"`. A script emitting other bytes gets
  replacement characters recorded as if they were its output, silently.
- `checks/` now imports `sandbox/` (for `truncate` and the runner). That matches the
  architecture diagram in docs/PLAN.md §5, where checks call into the sandbox. Confirm the
  layering, and that re-exporting `truncate` from `checks/__init__` is preferable to two
  copies of a three-line function.
- `--allow-network` exists and switches the policy to `inherited` (no guard installed; the
  trace records `network: inherited`). Confirm the CLI should be able to turn the guard
  off at all, given that no committed fixture needs it and the flag's only current use is
  a test.
- `entrypoint` stays declarative — the M5 review asked whether M6 should make it
  authoritative, and the answer is no (a task file must not name a command to run). It is
  recorded, hashed alongside the script, and never parsed. Test-pinned. Confirm the
  contract, and that `ArtifactBundle` validation should perhaps *reject* an entrypoint
  that disagrees with `path` rather than silently ignoring it.
- The sandbox copies only the script. `CodeArtifact` has no `inputs` field, so a
  data-reading fixture cannot exist yet; this is a behaviour change from M5, whose runner
  used `cwd=script.parent` and could have read `data/fixtures/...` relatively. No fixture
  did. Confirm that staging declared inputs belongs to the milestone that adds task family
  3 (figure/table reproduction) rather than here.
- `SubprocessScriptRunner` was deleted rather than kept as a fallback. On a platform
  without `resource` the sandbox still runs and reports `resource_limits: {}`. Confirm
  that degrading-and-reporting beats keeping a second runner.
- The trace is a `RunTrace` with only the four `sandbox.*` events; `claim`, `checks`, and
  `result` are unset. M6 owns the sandbox slice; the end-to-end run trace is M8/M9's.
  Confirm the file name (`<task_id>.sandbox.jsonl`) will not collide with theirs.
- Two tests are wall-clock-dependent: the CPU-limit test burns ~1 CPU-second and the
  process-group test waits ~1 s for its timeout. Both assert something was *killed*, so a
  slow machine makes them more likely to pass, not less. The process-group test also reads
  a grandchild's PID and polls `os.kill(pid, 0)`; PID reuse within its 3-second deadline is
  the theoretical failure mode.
- `ExecutionResult.policy` is annotated `Mapping[str, Any]` but defaults to a real `dict`
  on a frozen dataclass, so it is mutable in practice. Nothing mutates it.
- `run-sandbox` is a per-stage verb beyond docs/PLAN.md §10, on the same reasoning as M4's
  `link-evidence` and M5's `run-checks`. Confirm the growing CLI surface is wanted.

Technical risks
- **Concentrated where it was last milestone, and now better contained.** This layer
  executes code. It is pointed only at two trusted, committed, stdlib-only fixture scripts
  and at a handful of scripts the tests write themselves. It is **not a security
  boundary**: no namespace, no seccomp, no chroot, no user separation. The code, the
  package docstring, docs/SANDBOX.md, docs/CHECKS.md, docs/SAFETY.md, the website, and the
  policy record itself all say so. Do not point it at untrusted code.
- The socket tests never connect to anything: they either construct a socket (an fd, no
  I/O) or are refused before one exists. `urlopen("http://127.0.0.1:1/")` raises inside the
  guard, before a socket is created. The suite remains fully offline.
- The one genuinely new failure mode is `SandboxError`: the runner refuses to return a
  result when it cannot prove the policy was enforced. The check maps it to `error`. Verify
  that no later milestone (M7 scoring) treats `error` as evidence *against* a claim.
- Path resolution for scripts still goes through the M2 `resolve_fixture_path`, which
  rejects absolute paths and `..` escapes, so a task file cannot make the sandbox execute a
  file outside the repository.
- Determinism is enforced against the machine and test-pinned: portable command, redacted
  sandbox path, sorted lists, no absolute paths in `describe()`, no wall clock in the
  trace. The one crack is a failing script's traceback (stdlib paths), noted above.
- The compounding overfitting risk from M3–M5 applies again in a new form: the fixture
  scripts, the sandbox that runs them, and the tests that check the guards were all written
  by the same agent. Two passing fixtures is a consistency check, not a reproducibility
  benchmark, and RESULTS.md, SANDBOX.md, and the website all say so. The guard tests are
  more informative than the passes, which is why they are the ones tabulated.
- `--out` writes under `results/runs/`, which is gitignored; nothing generated is committed.

Commands to verify
- python3 -m pytest -q
- python3 -m pytest tests/test_sandbox.py -q
- ruff check .
- python3 scripts/01_validate_fixtures.py
- claimverifier run-sandbox --task tasks/code_reproduction/recompute_accuracy.yaml   (after `pip install -e .`)
- claimverifier run-sandbox --task tasks/bioinformatics_claims/gc_content.yaml --json
- claimverifier run-sandbox --task tasks/code_reproduction/recompute_accuracy.yaml --out results/runs/
      (run twice; the two .sandbox.jsonl files must be byte-identical)
- claimverifier run-sandbox --task tasks/code_reproduction/recompute_accuracy.yaml --with-timing
- claimverifier run-sandbox --task tasks/table_claims/contradicted_f1.yaml    (exits 1: nothing to run)
- claimverifier run-checks  --task tasks/code_reproduction/recompute_accuracy.yaml
      (the code_execution check must still pass, now via the sandbox)
- ./scripts/serve_site.sh   then load http://localhost:9002/reproducibility.html and limitations.html

Human feedback
<!-- Human will fill this later. -->
