# SANDBOX — controlled fixture execution

Milestone 6. The code-reproduction channel (`docs/CHECKS.md`) has to *run* a script.
This document says exactly what "sandbox" means in this repository, what it
enforces, what it does not, and why the distinction is worth a page.

Reach it with:

```bash
claimverifier run-sandbox --task tasks/code_reproduction/recompute_accuracy.yaml
claimverifier run-sandbox --task <task.yaml> [--out DIR] [--json] [--with-timing]
                          [--code-id ID] [--timeout S] [--allow-network]
```

## It is not a security boundary

> The code-execution layer runs **tiny, trusted fixture scripts** committed to this
> repository. There is no process isolation, no namespace, no seccomp filter, no
> chroot, and no user separation. The network guard runs *inside* the child's own
> interpreter and can be bypassed by any code that wants to. **Do not run untrusted
> code through it.**

That warning is not boilerplate hedging; it follows from the design. Everything
below is a **reproducibility** control. Its purpose is to make a reproduction result
*mean* something: that the number a script printed came from the script's own
contents, and not from the machine, the shell, the clock, or the network. A control
that stops an honest script from accidentally depending on its environment does not
have to stop a hostile script from lying, and this one does not.

## What is enforced

| Control | Mechanism | What it buys |
| --- | --- | --- |
| Fresh working directory | script copied into an empty temp dir, `cwd` set to it, dir removed after | the script cannot read a repository file it never declared |
| Scrubbed environment | allowlist (`LANG`, `LC_ALL`, `LC_CTYPE`, `PATH`, `SYSTEMROOT`) | no token, proxy, or `PYTHONPATH` from the host reaches the child |
| Deterministic environment | `PYTHONHASHSEED=0`, `TZ=UTC`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONNOUSERSITE=1` | set iteration order, dates, and imports are stable |
| Closed stdin | `stdin=DEVNULL` | the child cannot block waiting for input |
| Wall-clock timeout | parent-side, then `killpg(SIGKILL)` | a script that spawned children does not outlive it |
| CPU seconds | `RLIMIT_CPU` = `ceil(timeout) + 1` | a busy loop is stopped by the kernel |
| Address space | `RLIMIT_AS` = 2 GiB | a memory hog fails allocation instead of the machine |
| File size | `RLIMIT_FSIZE` = 8 MiB | a runaway write cannot fill the disk |
| Open files | `RLIMIT_NOFILE` = 256 | a descriptor leak is bounded |
| Network guard | in-process `socket` monkey-patch | accidental network use raises **and is recorded** |

Limits are applied by `preexec_fn`, i.e. in the forked child **before `exec`**, with
soft and hard set equal, so the child cannot raise them back. `RLIMIT_NPROC` is
deliberately absent: it counts every process owned by the real UID rather than the
child's descendants, so on a busy machine it would fail for reasons unrelated to the
script.

Resource limits are POSIX-only. On a platform without `resource`, the policy reports
`resource_limits: {}` rather than claiming a limit it did not set.

## What is not enforced

- **Process isolation.** The child is an ordinary subprocess owned by the same user.
- **Filesystem confinement.** `cwd` is a temp dir, but nothing stops an absolute path.
- **The network, against code that means it.** See below.

We deliberately do **not** set `http_proxy` / `no_proxy`. They deter nothing the
socket guard does not already stop, and their presence in the policy record would
imply a boundary that does not exist.

## The network guard, precisely

At interpreter startup the sandbox plants a `sitecustomize` module on the child's
`PYTHONPATH`. When the policy is `blocked`, it replaces:

| Name | Replaced by |
| --- | --- |
| `socket.socket`, `_socket.socket` | a **subclass** that raises on construction |
| `socket.create_connection`, `socket.create_server` | a raising function |
| `socket.getaddrinfo`, `socket.gethostbyname` | a raising function (DNS is network) |

Two details matter.

**The socket types are replaced by subclasses, not by functions.** `ssl.py` executes
`class SSLSocket(socket)` at import time. A guard that were merely *callable* would
turn `import http.client` into a baffling `TypeError` for code that never touches the
network. With a raising subclass, `import urllib.request` succeeds and the denial
happens where the connection is actually attempted.

**Every attempt is recorded before it is refused.** The guard appends the call name to
a log file, then raises. A script that catches the exception and carries on still
leaves the attempt in `network_attempts`, so a reproduction that reached for the
network cannot look self-contained in the trace. The `code_execution` check copies the
attempts into its `inputs` and says so in its notes.

**It is cooperative, Python-level, and bypassable.** Be precise about the reach:

| Case | Guarded? | Why |
| --- | --- | --- |
| `socket`, `urllib`, `http.client` in the script | yes | the entry points are patched |
| a Python subprocess the script spawns | **yes** | `PYTHONPATH` carries the bootstrap to the grandchild, and its attempts land in the same log |
| `ctypes`, a raw syscall, a pre-captured `_socket.socket` | no | nothing is patched at that level |
| a **non-Python** subprocess (`curl`, `wget`, any binary) | **no** | the guard lives in a Python interpreter; another program has its own |

The last row is the honest limit of a "no-network policy" implemented this way, and no
choice of environment variable fixes it: `subprocess.run(["/usr/bin/curl", …])` needs
no `PATH`. What *does* still apply to such a child is the process-group kill on timeout
and the inherited resource limits. Blocking it for real would need a network namespace
or a seccomp filter — i.e. the isolation this layer explicitly does not provide.

So: the guard catches *accidents* by trusted code, and records them. It does not
contain adversaries, and nothing in this repository claims it does.

### Verifying the guard rather than assuming it

`site.execsitecustomize()` catches every exception raised by `sitecustomize`, prints
one line to stderr, and lets the interpreter continue. A broken guard would therefore
leave the network open while the trace recorded `blocked`.

So the bootstrap writes a marker file, last, naming the policy it applied. The runner
refuses to return a result if that marker is missing or disagrees, raising
`SandboxError`. The `code_execution` check maps a `SandboxError` to `error` — never to
a verdict about the claim's number, because the conditions the number would be
attributed to never held.

`--allow-network` switches the policy to `inherited`: no guard is installed, and the
trace records `network: inherited`. It does not *grant* access; it stops blocking.

## The trace

Every execution produces four events, in this order, written as JSONL:

```jsonl
{"data": {"policy": {"env_allowlist": [...], "isolation": "none — controlled fixture execution, not a security boundary", "network": "blocked", "resource_limits": {"RLIMIT_AS": 2147483648, "RLIMIT_CPU": 11, ...}, "runner": "sandbox", "timeout_seconds": 10.0, ...}}, "kind": "sandbox.policy", "message": "controlled fixture execution under a recorded policy — not a security boundary", "seq": 0}
{"data": {"code_id": "code_accuracy", "command": ["python", "compute_accuracy.py"], "script": "compute_accuracy.py", "script_hash": "sha256:9bc64b75db9d…"}, "kind": "sandbox.exec", "message": "python compute_accuracy.py", "seq": 1}
{"data": {"stderr": "", "stdout": "accuracy=0.80\n"}, "kind": "sandbox.output", "message": "captured stdout/stderr; sandbox paths redacted, output truncated to the policy cap", "seq": 2}
{"data": {"exit_code": 0, "files_written": [], "network_attempts": [], "ok": true, "signal": null, "timed_out": false}, "kind": "sandbox.result", "message": "exited 0", "seq": 3}
```

(Keys are sorted; the `policy` object and the hash are abridged here. A fifth event,
`sandbox.timing`, is appended only with `--with-timing`.)

The policy comes **first**, before the number. A metric without the conditions that
produced it is not a result.

### Determinism

Two runs of the same script produce byte-identical JSONL, and it is test-pinned:

- the command is recorded as `("python", "compute_accuracy.py")`, never `sys.executable`;
- the sandbox root is a random temp path, so it is replaced with `<sandbox>` in all
  captured output before recording;
- `files_written` and `network_attempts` are sorted;
- the policy record contains no absolute paths and nothing read from `os.environ`;
- `RunTrace.to_jsonl` sorts keys.

**Wall-clock duration is the exception, and it is opt-in.** The runner measures it
because a reader wants it, the report prints it with `--with-timing`, and the trace
omits it otherwise — recording it by default would make every trace differ from every
other, and a diff between two runs would stop being a signal.

**Known limit.** Captured output is recorded verbatim apart from the sandbox root. A
*failing* script's traceback therefore embeds the host's stdlib paths
(`/usr/lib/python3.12/...`). Traces of failing runs are reproducible per machine, not
across machines. Redacting the traceback would be worse: an auditor needs it intact.

## Deliberate non-goals

- **`entrypoint` is never executed.** A task file declares
  `entrypoint: "python compute_accuracy.py"`, and it is recorded, and it is
  documentation. Parsing it into a command would let a task file name an arbitrary
  program to run. The runner always invokes the current interpreter on the artifact's
  declared `path`, which `resolve_fixture_path` has already confined to the repository.
- **Only the script is copied in.** A script that needs a data file must embed it, as
  both committed fixtures do. Staging declared inputs is real work for the task
  families that need it (`docs/PLAN.md` §7, family 3), not a hole to paper over. The
  `CodeArtifact` schema has no `inputs` field to declare them with.
- **No interpreter pinning.** The script runs under `sys.executable`. Two machines with
  different Python versions can disagree, and the trace does not currently record the
  version. `failed_environment` exists in the vocabulary for exactly this.
- **No output-stream interleaving.** stdout and stderr are captured on separate pipes,
  so their relative order is lost. Fixture scripts print one line to stdout.
- **`files_written` is a set difference.** It lists files that did not exist before the
  run. A script that *overwrites* an existing file — including its own source — leaves
  no record of it. Test-pinned as a known limit rather than left to be discovered.
- **The bookkeeping files live in the sandbox root**, which the script can reach by
  absolute path. Deleting the marker makes the run fail closed (`SandboxError`);
  truncating the network log would hide an attempt. Trusted fixtures do neither, and a
  script that would is outside this layer's threat model anyway.

## Where this sits

```
checks/code_execution.py   ScriptRunner protocol  ─┐
                                                   ├─▶ sandbox/runner.py  SandboxScriptRunner
                                                   │        sandbox/policy.py   what is enforced
                                                   │        sandbox/trace.py    what is recorded
scoring/ (M7)  ◀── VerificationCheck ◀─────────────┘
```

Milestone 5 wrote its `code_execution` check against the `ScriptRunner` protocol and
shipped a bare subprocess behind it, promising that "a check written against
`ScriptRunner` needs no change when [M6] lands." That held: M6 replaced the
implementation and the check's only edits were its default runner and two lines that
record a denied network attempt. `SubprocessScriptRunner` is gone — a strictly weaker
runner kept for nostalgia is dead code.

The sandbox reports what a process did. It decides nothing about the claim: the check
reads the report, and scoring (M7) draws the inference.
