"""Milestone 6 — the reproducibility sandbox.

The claims this milestone makes about execution are exactly the ones pinned here:

- the script runs in a fresh temp directory it cannot escape upward from, and the
  directory is gone afterwards;
- the child's environment is an allowlist, not the parent's;
- the network guard denies and **records** socket calls — including one the script
  catches and hides;
- a guard that failed to install is detected, because ``site`` swallows the error;
- a timeout kills the script's whole process group, not just the script;
- resource limits are enforced by the kernel, before ``exec``;
- and the trace is byte-identical across runs, because the one volatile value in it
  (wall-clock duration) is opt-in.

Every script executed here is a few lines written by the test, run locally, offline.
Nothing reaches the network: the socket tests construct a socket (or are refused
before one exists), they never connect.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

from scientific_claim_verifier import checks, cli
from scientific_claim_verifier.artifacts import hashing, loader
from scientific_claim_verifier.sandbox import policy as P
from scientific_claim_verifier.sandbox import runner as R
from scientific_claim_verifier.sandbox import trace as T
from scientific_claim_verifier.schemas import CodeArtifact

REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = REPO_ROOT / "tasks"
ACCURACY_FIXTURE = REPO_ROOT / "data" / "fixtures" / "code" / "compute_accuracy.py"
ACCURACY_TASK = str(TASKS_DIR / "code_reproduction" / "recompute_accuracy.yaml")

HAS_RESOURCE = P.resource is not None
HAS_KILLPG = hasattr(os, "killpg")


def script(directory: Path, body: str, name: str = "s.py") -> Path:
    """Write a tiny script for the sandbox to run."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return path


def run(
    path: Path, timeout: float = 10.0, policy: P.SandboxPolicy | None = None
) -> R.ExecutionResult:
    return R.SandboxScriptRunner(policy).run(path, timeout)


def sandbox_dirs() -> set[str]:
    """Names of every sandbox temp directory currently on disk."""
    return {p.name for p in Path(tempfile.gettempdir()).glob(f"{P.WORKDIR_PREFIX}*")}


# ---------------------------------------------------------------------------
# Policy: a declarative, recorded description of the run's conditions
# ---------------------------------------------------------------------------


def test_truncate_is_the_one_shared_capture_helper() -> None:
    # M5's `checks.truncate` is a re-export: capping a child's output is M6's business.
    assert checks.truncate is P.truncate
    assert checks.MAX_CAPTURE_CHARS == P.MAX_CAPTURE_CHARS
    assert P.truncate("abc", 10) == "abc"
    assert "truncated, 50 chars" in P.truncate("x" * 50, 10)


def test_redact_replaces_the_sandbox_root_wherever_it_appears(tmp_path: Path) -> None:
    text = f"cwd={tmp_path}/work and file={tmp_path}/work/out.txt"
    redacted = P.redact(text, tmp_path)
    assert str(tmp_path) not in redacted
    assert redacted.count(P.REDACTED_PATH) == 2


def test_redact_also_replaces_the_resolved_form(tmp_path: Path) -> None:
    # The child reports its resolved cwd; on some platforms /tmp is a symlink.
    link = tmp_path / "link"
    link.symlink_to(tmp_path)
    assert P.redact(f"at {link.resolve()}", link) == f"at {P.REDACTED_PATH}"


def test_resource_limits_derive_the_cpu_limit_from_the_runs_timeout() -> None:
    limits = P.ResourceLimits()
    assert limits.resolve(10.0)["RLIMIT_CPU"] == 11
    assert limits.resolve(0.3)["RLIMIT_CPU"] == 2  # ceil(0.3) + 1
    assert P.ResourceLimits(cpu_seconds=5).resolve(10.0)["RLIMIT_CPU"] == 5


def test_a_none_limit_is_omitted_rather_than_set_to_a_sentinel() -> None:
    limits = P.ResourceLimits(address_space_bytes=None, open_files=None)
    assert set(limits.resolve(1.0)) == {"RLIMIT_CPU", "RLIMIT_FSIZE"}


def test_with_timeout_is_a_copy_and_moves_the_derived_cpu_limit() -> None:
    policy = P.SandboxPolicy()
    longer = policy.with_timeout(60.0)
    assert policy.timeout_seconds == P.DEFAULT_TIMEOUT_SECONDS
    assert longer.timeout_seconds == 60.0
    if HAS_RESOURCE:
        assert longer.resource_limits()["RLIMIT_CPU"] == 61


def test_disabling_limits_reports_none_applied_rather_than_pretending() -> None:
    assert P.SandboxPolicy(limits=None).resource_limits() == {}
    assert P.SandboxPolicy(limits=None).limit_applier() is None


def test_the_described_policy_is_machine_independent() -> None:
    described = P.SandboxPolicy().with_timeout(10.0).describe()
    rendered = json.dumps(described)
    assert str(REPO_ROOT) not in rendered
    assert sys.executable not in rendered
    assert tempfile.gettempdir() not in rendered
    assert described["network"] == "blocked"
    assert described["runner"] == "sandbox"
    # The honesty line is part of the record, not just the prose around it.
    assert "not a security boundary" in described["isolation"]


def test_the_described_policy_names_the_limits_it_will_actually_apply() -> None:
    described = P.SandboxPolicy().with_timeout(4.0).describe()
    if HAS_RESOURCE:
        assert described["resource_limits"]["RLIMIT_CPU"] == 5
    else:  # pragma: no cover - non-POSIX
        assert described["resource_limits"] == {}


def test_the_environment_is_an_allowlist_not_the_parents(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SCV_A_SECRET", "hunter2")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = P.SandboxPolicy().environment(
        home=tmp_path / "home",
        tmpdir=tmp_path / "tmp",
        bootstrap=tmp_path / "bootstrap",
        network_log=tmp_path / "net.log",
        marker=tmp_path / "ok",
    )
    assert "SCV_A_SECRET" not in env
    assert env["PATH"] == "/usr/bin"
    assert env["PYTHONHASHSEED"] == "0" and env["TZ"] == "UTC"
    assert env["HOME"].startswith(str(tmp_path)) and env["TMPDIR"].startswith(str(tmp_path))
    assert env[P.NETWORK_ENV] == "blocked" and P.NETWORK_LOG_ENV in env


def test_an_inherited_network_policy_passes_no_log_to_the_child(tmp_path: Path) -> None:
    env = P.SandboxPolicy(network=P.NetworkPolicy.INHERITED).environment(
        home=tmp_path, tmpdir=tmp_path, bootstrap=tmp_path,
        network_log=tmp_path / "net.log", marker=tmp_path / "ok",
    )
    assert env[P.NETWORK_ENV] == "inherited"
    assert P.NETWORK_LOG_ENV not in env


def test_write_bootstrap_plants_the_module_python_imports_at_startup(tmp_path: Path) -> None:
    written = P.write_bootstrap(tmp_path)
    assert written.name == P.BOOTSTRAP_MODULE == "sitecustomize.py"
    assert "NetworkBlocked" in written.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The runner: capture, temp dir, cleanup
# ---------------------------------------------------------------------------


def test_the_runner_executes_a_committed_fixture_and_records_portable_facts() -> None:
    result = run(ACCURACY_FIXTURE)
    assert result.ok and result.stdout.strip() == "accuracy=0.80"
    # Never the absolute interpreter path: a trace must not depend on the machine.
    assert result.command == ("python", "compute_accuracy.py")
    assert sys.executable not in result.command
    # The hash is of the bytes that actually ran, taken inside the sandbox.
    assert result.script_hash == hashing.hash_file(ACCURACY_FIXTURE)
    assert result.policy["runner"] == "sandbox"


def test_the_runner_captures_a_nonzero_exit_without_raising(tmp_path: Path) -> None:
    result = run(script(tmp_path, "import sys; sys.stderr.write('boom'); sys.exit(3)"))
    assert (result.exit_code, result.timed_out, result.ok) == (3, False, False)
    assert "boom" in result.stderr and result.signal is None


def test_the_runner_times_out_without_raising(tmp_path: Path) -> None:
    result = run(script(tmp_path, "import time; time.sleep(30)"), timeout=0.3)
    assert result.timed_out and result.exit_code is None and not result.ok


def test_a_missing_script_is_a_sandbox_error_not_a_result(tmp_path: Path) -> None:
    with pytest.raises(R.SandboxError, match="script not found"):
        run(tmp_path / "gone.py")


def test_the_temp_directory_is_removed_after_the_run(tmp_path: Path) -> None:
    before = sandbox_dirs()
    run(script(tmp_path, "print('done')"))
    assert sandbox_dirs() - before == set()


def test_keeping_the_workdir_is_opt_in_and_the_policy_says_so(tmp_path: Path) -> None:
    before = sandbox_dirs()
    result = run(script(tmp_path, "print('done')"), policy=P.SandboxPolicy(cleanup=False))
    kept = sandbox_dirs() - before
    try:
        assert len(kept) == 1
        assert "kept for inspection" in result.policy["working_directory"]
    finally:
        for name in kept:
            shutil.rmtree(Path(tempfile.gettempdir()) / name, ignore_errors=True)


def test_the_script_runs_in_an_empty_directory_and_cannot_see_the_repository(
    tmp_path: Path,
) -> None:
    result = run(
        script(
            tmp_path,
            """
            import os
            from pathlib import Path
            print("sees_repo=" + str(Path("pyproject.toml").exists()))
            print("listing=" + ",".join(sorted(os.listdir("."))))
            """,
        )
    )
    assert "sees_repo=False" in result.stdout
    # Only the script itself was copied in. A script needing a data file must embed it.
    assert "listing=s.py" in result.stdout


def test_the_child_cannot_read_the_parents_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SCV_A_SECRET", "hunter2")
    result = run(
        script(
            tmp_path,
            """
            import os
            print("secret=" + os.environ.get("SCV_A_SECRET", "absent"))
            print("hashseed=" + os.environ.get("PYTHONHASHSEED", "?"))
            print("tz=" + os.environ.get("TZ", "?"))
            """,
        )
    )
    assert "secret=absent" in result.stdout
    assert "hashseed=0" in result.stdout and "tz=UTC" in result.stdout


def test_the_sandbox_path_is_redacted_out_of_captured_output(tmp_path: Path) -> None:
    result = run(script(tmp_path, "import os; print('cwd=' + os.getcwd())"))
    assert P.REDACTED_PATH in result.stdout
    assert P.WORKDIR_PREFIX not in result.stdout


def test_files_the_script_writes_are_recorded_and_bytecode_is_not(tmp_path: Path) -> None:
    result = run(
        script(
            tmp_path,
            """
            from pathlib import Path
            Path("helper.py").write_text("VALUE = 1\\n")
            import helper
            Path("out.txt").write_text(str(helper.VALUE))
            """,
        )
    )
    assert result.ok
    # PYTHONDONTWRITEBYTECODE=1, so importing `helper` leaves no __pycache__ behind.
    assert result.files_written == ("helper.py", "out.txt")


def test_home_and_tmpdir_point_inside_the_sandbox(tmp_path: Path) -> None:
    result = run(
        script(
            tmp_path,
            """
            import os, tempfile
            print("home=" + os.environ["HOME"])
            print("tmp=" + tempfile.gettempdir())
            """,
        )
    )
    # Both were redacted, which means both were under the sandbox root.
    assert result.stdout.count(P.REDACTED_PATH) == 2


# ---------------------------------------------------------------------------
# The network guard
# ---------------------------------------------------------------------------


def test_a_socket_is_denied_and_the_attempt_is_recorded(tmp_path: Path) -> None:
    result = run(script(tmp_path, "import socket; socket.socket()"))
    assert not result.ok
    assert result.network_attempts == ("socket.socket",)
    assert "sandbox network policy 'blocked' denied socket.socket" in result.stderr


def test_an_attempt_the_script_swallows_still_reaches_the_record(tmp_path: Path) -> None:
    # The guard's exception can be caught; the log it writes first cannot be unwritten.
    result = run(
        script(
            tmp_path,
            """
            import socket
            try:
                socket.create_connection(("example.com", 80))
            except Exception:
                pass
            print("accuracy=0.80")
            """,
        )
    )
    assert result.ok and result.stdout.strip() == "accuracy=0.80"
    assert result.network_attempts == ("socket.create_connection",)


def test_urllib_still_imports_and_is_denied_where_it_connects(tmp_path: Path) -> None:
    # `ssl` runs `class SSLSocket(socket)` at import. A guard that replaced the socket
    # *class* with a function would break `import http.client` for code that never
    # touches the network, so the guard installs a raising subclass instead.
    result = run(
        script(
            tmp_path,
            """
            import urllib.request
            print("imported=True")
            urllib.request.urlopen("http://127.0.0.1:1/")
            """,
        )
    )
    assert "imported=True" in result.stdout
    assert result.network_attempts == ("socket.create_connection",)
    assert not result.ok


def test_dns_resolution_is_network_and_is_denied(tmp_path: Path) -> None:
    result = run(script(tmp_path, "import socket; socket.getaddrinfo('example.com', 80)"))
    assert result.network_attempts == ("socket.getaddrinfo",)


def test_a_raw_underscore_socket_import_is_denied_too(tmp_path: Path) -> None:
    result = run(script(tmp_path, "import _socket; _socket.socket()"))
    assert result.network_attempts == ("_socket.socket",)


def test_a_python_grandchild_inherits_the_guard_through_pythonpath(tmp_path: Path) -> None:
    # The bootstrap reaches any Python the script spawns, and the attempt lands in the
    # same log. A *non*-Python child (e.g. `curl`) is not guarded — see docs/SANDBOX.md.
    child = (
        "import socket\n"
        "try:\n"
        "    socket.socket()\n"
        "except Exception as exc:\n"
        "    print('guarded:', type(exc).__name__)\n"
    )
    body = (
        "import subprocess, sys\n"
        f"argv = [sys.executable, '-c', {child!r}]\n"
        "done = subprocess.run(argv, capture_output=True, text=True)\n"
        "print(done.stdout.strip())\n"
    )
    result = run(script(tmp_path, body))
    assert "guarded: NetworkBlocked" in result.stdout
    assert result.network_attempts == ("socket.socket",)


def test_files_written_records_new_files_and_not_modified_ones(tmp_path: Path) -> None:
    # A known limit: the snapshot is a set difference, so a script that overwrites a
    # file that already existed (including its own source) leaves no trace of it.
    result = run(script(tmp_path, "from pathlib import Path\nPath('s.py').write_text('# gone\\n')"))
    assert result.ok and result.files_written == ()


def test_an_inherited_policy_installs_no_guard(tmp_path: Path) -> None:
    # Constructing a socket opens no connection; nothing here touches the network.
    policy = P.SandboxPolicy(network=P.NetworkPolicy.INHERITED)
    result = run(
        script(tmp_path, "import socket; s = socket.socket(); print('made'); s.close()"),
        policy=policy,
    )
    assert result.ok and "made" in result.stdout
    assert result.network_attempts == ()
    assert result.policy["network"] == "inherited"
    assert result.policy["network_guard"] == "none"


def test_a_guard_that_failed_to_install_is_caught_rather_than_trusted(
    monkeypatch, tmp_path: Path
) -> None:
    # `site` prints and *swallows* an exception from sitecustomize, then carries on with
    # the network wide open. Without the marker check the trace would say "blocked".
    monkeypatch.setattr(P, "SITECUSTOMIZE_SOURCE", "raise RuntimeError('boom')\n")
    with pytest.raises(R.SandboxError, match="did not run in the child interpreter"):
        run(script(tmp_path, "print('accuracy=0.80')"))


def test_a_guard_that_applied_the_wrong_policy_is_caught(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        P,
        "SITECUSTOMIZE_SOURCE",
        "import os\nopen(os.environ['SCV_SANDBOX_MARKER'], 'w').write('inherited')\n",
    )
    with pytest.raises(R.SandboxError, match="applied network policy 'inherited'"):
        run(script(tmp_path, "print('ok')"))


# ---------------------------------------------------------------------------
# Timeout and resource limits: enforced by the OS, not by good manners
# ---------------------------------------------------------------------------


def _pid_from(marker: Path, deadline: float = 3.0) -> int:
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if marker.is_file() and marker.read_text().strip():
            return int(marker.read_text().strip())
        time.sleep(0.02)
    raise AssertionError(f"the grandchild never wrote {marker}")


def _is_reaped(pid: int, deadline: float = 3.0) -> bool:
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.02)
    with contextlib.suppress(ProcessLookupError):  # never leave a stray process behind
        os.kill(pid, 9)
    return False


@pytest.mark.skipif(not HAS_KILLPG, reason="process groups are POSIX only")
def test_a_timeout_kills_the_scripts_children_not_just_the_script(tmp_path: Path) -> None:
    # `subprocess.run(timeout=...)` would kill only the direct child, leaving a
    # grandchild alive and holding the output pipes open.
    marker = tmp_path / "grandchild.pid"
    grandchild = (
        "import os, time; "
        f"open({str(marker)!r}, 'w').write(str(os.getpid())); "
        "time.sleep(30)"
    )
    body = (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
        "time.sleep(30)\n"
    )
    result = run(script(tmp_path, body, name="spawner.py"), timeout=1.0)
    assert result.timed_out
    assert _is_reaped(_pid_from(marker)), "the script's child outlived the timeout"


@pytest.mark.skipif(not HAS_RESOURCE, reason="setrlimit is POSIX only")
def test_the_address_space_limit_stops_a_memory_hog(tmp_path: Path) -> None:
    # RLIMIT_AS makes the allocation fail immediately; no memory is ever touched.
    result = run(script(tmp_path, "x = bytearray(3 * 1024**3)"))
    assert not result.ok and "MemoryError" in result.stderr


@pytest.mark.skipif(not HAS_RESOURCE, reason="setrlimit is POSIX only")
def test_the_cpu_limit_stops_a_busy_loop_before_the_wall_clock_timeout(tmp_path: Path) -> None:
    policy = P.SandboxPolicy(limits=P.ResourceLimits(cpu_seconds=1))
    result = run(script(tmp_path, "while True:\n    pass\n"), timeout=30.0, policy=policy)
    # Killed by the kernel, not reaped by the parent's timeout: the two are distinct.
    assert not result.timed_out
    assert result.signal is not None and result.exit_code is not None and result.exit_code < 0


# ---------------------------------------------------------------------------
# ExecutionResult
# ---------------------------------------------------------------------------


def _result(**overrides) -> R.ExecutionResult:
    defaults = {
        "command": ("python", "s.py"),
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "timed_out": False,
    }
    return R.ExecutionResult(**{**defaults, **overrides})


def test_execution_result_reports_the_signal_that_killed_the_process() -> None:
    assert _result(exit_code=-9).signal == 9
    assert _result(exit_code=0).signal is None
    assert _result(exit_code=None, timed_out=True).signal is None


def test_result_to_dict_makes_timing_opt_in() -> None:
    result = _result(duration_seconds=0.5)
    assert "duration_seconds" not in R.result_to_dict(result)
    assert R.result_to_dict(result, include_timing=True)["duration_seconds"] == 0.5


# ---------------------------------------------------------------------------
# Running a task's code artifacts
# ---------------------------------------------------------------------------


def _task(*parts: str) -> loader.LoadedTask:
    return loader.load_task(TASKS_DIR.joinpath(*parts), REPO_ROOT)


def test_code_artifacts_selects_only_runnable_python() -> None:
    task = _task("code_reproduction", "recompute_accuracy.yaml")
    assert [c.artifact_id for c in R.code_artifacts(task)] == ["code_accuracy"]
    task.bundle.code_files.append(CodeArtifact(artifact_id="r_code", path="x.R", language="r"))
    task.bundle.code_files.append(CodeArtifact(artifact_id="no_path", language="python"))
    assert [c.artifact_id for c in R.code_artifacts(task)] == ["code_accuracy"]


def test_code_artifacts_rejects_an_unknown_id() -> None:
    with pytest.raises(R.SandboxError, match="no runnable python code artifact 'ghost'"):
        R.code_artifacts(_task("code_reproduction", "recompute_accuracy.yaml"), "ghost")


def test_run_artifact_honours_the_declared_timeout_and_not_the_declared_entrypoint() -> None:
    task = _task("code_reproduction", "recompute_accuracy.yaml")
    artifact = R.code_artifacts(task)[0]
    assert artifact.entrypoint == "python compute_accuracy.py"
    result = R.run_artifact(artifact, REPO_ROOT)
    # The entrypoint is declarative. The command comes from `path`, and the timeout
    # comes from the artifact (10s), not from the sandbox default alone.
    assert result.command == ("python", "compute_accuracy.py")
    assert result.policy["timeout_seconds"] == 10.0
    assert result.ok


def test_both_committed_code_fixtures_reproduce_their_reported_metric() -> None:
    for parts, expected in (
        (("code_reproduction", "recompute_accuracy.yaml"), "accuracy=0.80"),
        (("bioinformatics_claims", "gc_content.yaml"), "gc_content=0.50"),
    ):
        task = _task(*parts)
        result = R.run_artifact(R.code_artifacts(task)[0], REPO_ROOT)
        assert result.ok and result.stdout.strip() == expected
        assert result.network_attempts == () and result.files_written == ()


# ---------------------------------------------------------------------------
# The trace
# ---------------------------------------------------------------------------


def test_a_trace_records_the_policy_before_the_number() -> None:
    trace = T.record_execution(T.new_trace("r"), run(ACCURACY_FIXTURE), code_id="code_accuracy")
    kinds = [event.kind for event in trace.events]
    assert kinds == ["sandbox.policy", "sandbox.exec", "sandbox.output", "sandbox.result"]
    assert trace.events[0].data["policy"]["network"] == "blocked"
    assert trace.events[1].data["code_id"] == "code_accuracy"
    assert trace.events[2].data["stdout"].strip() == "accuracy=0.80"
    assert trace.events[3].data["ok"] is True


def test_timing_is_the_one_value_a_trace_omits_by_default() -> None:
    result = run(ACCURACY_FIXTURE)
    assert result.duration_seconds is not None
    plain = T.record_execution(T.new_trace("r"), result)
    timed = T.record_execution(T.new_trace("r"), result, include_timing=True)
    assert [e.kind for e in timed.events][-1] == "sandbox.timing"
    assert "sandbox.timing" not in [e.kind for e in plain.events]
    assert timed.events[-1].data["duration_seconds"] == result.duration_seconds


def test_the_trace_of_two_runs_of_one_script_is_byte_identical() -> None:
    first = T.record_execution(T.new_trace("r"), run(ACCURACY_FIXTURE)).to_jsonl()
    second = T.record_execution(T.new_trace("r"), run(ACCURACY_FIXTURE)).to_jsonl()
    assert first == second


def test_no_machine_specific_path_reaches_the_trace() -> None:
    jsonl = T.record_execution(T.new_trace("r"), run(ACCURACY_FIXTURE)).to_jsonl()
    assert str(REPO_ROOT) not in jsonl
    assert sys.executable not in jsonl
    assert P.WORKDIR_PREFIX not in jsonl


def test_outcome_message_distinguishes_exit_timeout_and_signal() -> None:
    policy = {"timeout_seconds": 2.0}
    assert T.outcome_message(_result(exit_code=3)) == "exited 3"
    assert T.outcome_message(_result(exit_code=-9)) == "killed by signal 9"
    timed = _result(exit_code=None, timed_out=True, policy=policy)
    assert T.outcome_message(timed) == "timed out after 2.0s; process group killed"


def test_write_and_read_trace_round_trip(tmp_path: Path) -> None:
    trace = T.record_execution(T.new_trace("r", task_id="t"), run(ACCURACY_FIXTURE))
    target = T.write_trace(trace, tmp_path / "nested" / "t.sandbox.jsonl")
    events = T.read_trace(target)
    assert [e["kind"] for e in events] == list(T.SANDBOX_EVENT_KINDS[:4])
    assert [e["seq"] for e in events] == [0, 1, 2, 3]


def test_an_empty_trace_writes_an_empty_file(tmp_path: Path) -> None:
    target = T.write_trace(T.new_trace("r"), tmp_path / "empty.jsonl")
    assert target.read_text(encoding="utf-8") == ""
    assert T.read_trace(target) == []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_run_sandbox_reports_the_policy_and_the_output(capsys) -> None:
    assert cli.main(["run-sandbox", "--task", ACCURACY_TASK]) == 0
    out = capsys.readouterr().out
    assert "sandbox execution" in out
    assert "accuracy=0.80" in out
    assert "network       : blocked" in out
    assert "not a security boundary" in out
    assert "Outcome         : exited 0" in out
    # Timing is volatile, so it is not printed unless asked for.
    assert "Duration" not in out


def test_cli_run_sandbox_json(capsys) -> None:
    assert cli.main(["run-sandbox", "--task", ACCURACY_TASK, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["task_id"] == "recompute_accuracy"
    execution = payload["executions"][0]
    assert execution["ok"] is True and execution["stdout"] == "accuracy=0.80\n"
    assert "duration_seconds" not in execution
    assert [event["kind"] for event in payload["trace"]] == list(T.SANDBOX_EVENT_KINDS[:4])


def test_cli_run_sandbox_writes_a_deterministic_trace(tmp_path: Path, capsys) -> None:
    target = tmp_path / "recompute_accuracy.sandbox.jsonl"
    assert cli.main(["run-sandbox", "--task", ACCURACY_TASK, "--out", str(tmp_path)]) == 0
    first = target.read_text(encoding="utf-8")
    assert cli.main(["run-sandbox", "--task", ACCURACY_TASK, "--out", str(tmp_path)]) == 0
    assert target.read_text(encoding="utf-8") == first
    assert "wrote" in capsys.readouterr().err


def test_cli_run_sandbox_with_timing(tmp_path: Path, capsys) -> None:
    args = ["run-sandbox", "--task", ACCURACY_TASK, "--out", str(tmp_path), "--with-timing"]
    assert cli.main(args) == 0
    assert "Duration" in capsys.readouterr().out
    events = T.read_trace(tmp_path / "recompute_accuracy.sandbox.jsonl")
    assert events[-1]["kind"] == "sandbox.timing"


def test_cli_run_sandbox_allow_network_records_that_it_did_not_block(capsys) -> None:
    assert cli.main(["run-sandbox", "--task", ACCURACY_TASK, "--allow-network", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["executions"][0]["policy"]["network"] == "inherited"


def test_cli_run_sandbox_timeout_flag_overrides_the_artifact(capsys) -> None:
    args = ["run-sandbox", "--task", ACCURACY_TASK, "--timeout", "2.5", "--json"]
    assert cli.main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["executions"][0]["policy"]["timeout_seconds"] == 2.5


def test_cli_run_sandbox_code_id_selects_one_artifact(capsys) -> None:
    args = ["run-sandbox", "--task", ACCURACY_TASK, "--code-id", "code_accuracy"]
    assert cli.main(args) == 0
    assert "code_accuracy" in capsys.readouterr().out


def test_cli_run_sandbox_fails_loudly_on_a_task_with_nothing_to_run(capsys) -> None:
    task = str(TASKS_DIR / "table_claims" / "contradicted_f1.yaml")
    assert cli.main(["run-sandbox", "--task", task]) == 1
    assert "declares no runnable code artifact" in capsys.readouterr().err


def test_cli_run_sandbox_unknown_code_id_returns_1(capsys) -> None:
    assert cli.main(["run-sandbox", "--task", ACCURACY_TASK, "--code-id", "ghost"]) == 1
    assert "no runnable python code artifact" in capsys.readouterr().err


def test_cli_run_sandbox_missing_task_returns_1(capsys) -> None:
    assert cli.main(["run-sandbox", "--task", str(TASKS_DIR / "nope.yaml")]) == 1
    assert "could not load task" in capsys.readouterr().err


def test_sandbox_module_entry_point_matches_the_cli(capsys) -> None:
    assert R.main(["--task", ACCURACY_TASK, "--json"]) == 0
    assert '"task_id": "recompute_accuracy"' in capsys.readouterr().out


def test_the_sandbox_cli_runs_without_an_editable_install() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "scientific_claim_verifier.cli", "run-sandbox", "--task",
         ACCURACY_TASK],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "accuracy=0.80" in completed.stdout
