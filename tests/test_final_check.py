"""Milestone 13 — the gate is tested the way the gate tests the repository.

`src/scientific_claim_verifier/final_check.py` turns `docs/PLAN.md` §11 and `CLAUDE.md`'s
"what must never be committed" into seventeen checks with an exit code. A gate is worth
exactly what its failures are worth, so every check here is fed an input it **must**
reject, and the rejection is asserted. The same discipline M8 applied to the suite gate,
M11 to replay, and M12 to the documentation gate: a check that cannot fail proves nothing
when it passes.

Three things this module is careful about.

**The fake credentials are assembled at run time.** `FAKE_SECRETS` concatenates fragments,
so no committed file contains a string the secret scanner would match — not this test, and
not the scanner's own source. Both are scanned like every other tracked file, and
`test_the_secret_scanner_is_not_exempt_from_itself` asserts they are. Excluding a file
from a secret scan is how a secret survives one.

**The live gate is asserted on everything except the working tree.** Whether the tree is
clean is a fact about the moment `pytest` ran, not about the code under test; a test that
pinned it would fail every time someone edited a file. `working_tree_is_clean` is
therefore asserted to *run*, not to pass. The script is where that verdict lives.

**Nothing here shells out to `pytest`.** `run_checks(subprocess_checks=False)` is the only
form a test may call, and `final_check` raises `RecursionRefused` if a test forgets —
which is itself asserted below.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from scientific_claim_verifier import final_check, suite
from scientific_claim_verifier.adapters import cost
from scientific_claim_verifier.artifacts import validation
from scientific_claim_verifier.final_check import (
    CHECKS,
    GATE,
    HYGIENE,
    SPECS,
    CheckOutcome,
    FinalCheckReport,
    GitUnavailable,
    RecursionRefused,
)
from scientific_claim_verifier.schemas import CheckStatus, CheckType, VerificationCheck

REPO_ROOT = Path(__file__).resolve().parents[1]

#: One string per credential pattern, built from fragments so that this file cannot
#: match the scanner it exercises. Each value is what a real leak would look like.
FAKE_SECRETS: dict[str, str] = {
    "aws-access-key-id": "AKIA" + "Q7WERTYUIOPASDFG",
    "private-key-block": "-----BEGIN " + "RSA PRIVATE KEY-----",
    "anthropic-api-key": "sk-" + "ant-" + "A" * 24,
    "openai-api-key": "sk-" + "B" * 36,
    "github-token": "ghp" + "_" + "c" * 36,
    "google-api-key": "AIza" + "D" * 35,
    "slack-token": "xox" + "b-" + "1234567890" + "-abcdef",
    "assigned-credential": "api_key" + " = " + '"' + "s3cr3t-value" + '"',
}


def a_check(kind: CheckType, status: CheckStatus, n: int = 0) -> VerificationCheck:
    """A minimal check record. Only the type and status matter to the gate."""
    return VerificationCheck(check_id=f"chk_{n}", check_type=kind, claim_id="c_x", status=status)


def an_outcome(name: str, ok: bool = True) -> CheckOutcome:
    spec = SPECS[name]
    return CheckOutcome(name=name, group=spec.group, requirement=spec.requirement, ok=ok, detail="")


@pytest.fixture(scope="module")
def live_report() -> FinalCheckReport:
    """One real run of the gate over this repository, minus the two that shell out."""
    return final_check.run_checks(REPO_ROOT, subprocess_checks=False)


# ---------------------------------------------------------------------------
# The registry is load-bearing
# ---------------------------------------------------------------------------


def test_every_declared_check_is_uniquely_named_and_belongs_to_a_known_group() -> None:
    names = [spec.name for spec in CHECKS]
    assert len(names) == len(set(names)), "two checks share a name"
    assert {spec.group for spec in CHECKS} == {GATE, HYGIENE}
    assert len(SPECS) == len(CHECKS)


def test_an_undeclared_check_cannot_report_an_outcome() -> None:
    """The registry is not decorative: `_outcome` looks its caller up, and fails if absent."""
    with pytest.raises(KeyError):
        final_check._outcome("a_check_nobody_declared", ok=True, detail="")


def test_exactly_two_checks_declare_that_they_shell_out() -> None:
    shelling = {spec.name for spec in CHECKS if spec.shells_out}
    assert shelling == {"tests_pass", "lint_is_clean"}


def test_a_real_run_produces_exactly_the_checks_the_registry_declares(
    live_report: FinalCheckReport,
) -> None:
    """The registry and the implementation cannot drift: a run enumerates both."""
    assert live_report.ran == frozenset(SPECS) - {"tests_pass", "lint_is_clean"}
    assert live_report.not_run == ("tests_pass", "lint_is_clean")


def test_the_report_reads_in_the_order_the_plan_argues(live_report: FinalCheckReport) -> None:
    positions = [final_check.ORDER[o.name] for o in live_report.outcomes]
    assert positions == sorted(positions)


# ---------------------------------------------------------------------------
# A partial run is not a passing run
# ---------------------------------------------------------------------------


def test_a_complete_run_with_no_failures_is_ok() -> None:
    report = FinalCheckReport(outcomes=tuple(an_outcome(spec.name) for spec in CHECKS))
    assert report.complete and report.all_passed and report.ok


def test_a_partial_run_is_never_ok_even_when_nothing_failed(live_report: FinalCheckReport) -> None:
    """`--no-subprocess` omits two checks. Printing PASS then would be the failure this
    module exists to prevent, so `ok` requires completeness as well as success."""
    assert live_report.all_passed or live_report.failures  # either way, it ran
    assert not live_report.complete
    assert not live_report.ok


def test_a_complete_run_with_one_failure_is_not_ok() -> None:
    outcomes = [an_outcome(spec.name) for spec in CHECKS]
    outcomes[3] = an_outcome(CHECKS[3].name, ok=False)
    report = FinalCheckReport(outcomes=tuple(outcomes))
    assert report.complete and not report.all_passed and not report.ok


def test_an_incomplete_report_says_so_rather_than_passing() -> None:
    report = FinalCheckReport(outcomes=(an_outcome(CHECKS[0].name),), repo_root=REPO_ROOT)
    text = final_check.format_report(report)
    assert "INCOMPLETE" in text
    assert "Overall   : PASS" not in text


def test_a_report_round_trips_through_json(live_report: FinalCheckReport) -> None:
    payload = json.loads(json.dumps(live_report.to_dict()))
    assert payload["n_declared"] == len(CHECKS)
    assert payload["ok"] is False  # partial
    assert {o["name"] for o in payload["outcomes"]} == set(live_report.ran)


def test_format_report_names_every_check_that_ran(live_report: FinalCheckReport) -> None:
    text = final_check.format_report(live_report)
    for name in live_report.ran:
        assert name in text


# ---------------------------------------------------------------------------
# Hygiene: forbidden paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "deploy/prod.key",
        "certs/server.pem",
        "keys/client.p12",
        "home/id_rsa",
        "secrets.yaml",
        ".claude/settings.local.json",
        "src/__pycache__/cli.cpython-312.pyc",
        ".venv/lib/x.py",
        "node_modules/left-pad/index.js",
        "models/weights.safetensors",
        "checkpoints/model.ckpt",
        "data/big.parquet",
        "logs/run.log",
        "results/cache/llm/abc.json",
        "results/runs/x.cache.json",
    ],
)
def test_forbidden_reason_rejects_a_path_that_must_never_be_committed(path: str) -> None:
    assert final_check.forbidden_reason(path) is not None
    assert not final_check.no_forbidden_paths([path]).ok


@pytest.mark.parametrize(
    "path",
    [
        "src/scientific_claim_verifier/cli.py",
        ".claude/settings.json",
        "data/fixtures/datasets/measurements.csv",
        "docs/PLAN.md",
        "site/index.html",
        "tasks/smoke_suite.yaml",
    ],
)
def test_forbidden_reason_admits_a_path_this_repository_tracks(path: str) -> None:
    assert final_check.forbidden_reason(path) is None


def test_no_forbidden_paths_admits_this_repository() -> None:
    assert final_check.no_forbidden_paths(final_check.tracked_files(REPO_ROOT)).ok


def test_the_committed_permission_allowlist_is_not_mistaken_for_the_local_override() -> None:
    """`.claude/settings.json` is committed on purpose; only `settings.local.json` is not."""
    assert final_check.forbidden_reason(".claude/settings.json") is None
    assert final_check.forbidden_reason(".claude/settings.local.json") is not None


# ---------------------------------------------------------------------------
# Hygiene: size
# ---------------------------------------------------------------------------


def test_no_oversized_files_rejects_a_file_over_the_limit() -> None:
    outcome = final_check.no_oversized_files({"data/huge.csv": final_check.MAX_FILE_BYTES + 1})
    assert not outcome.ok
    assert "data/huge.csv" in outcome.evidence[0]


def test_no_oversized_files_admits_a_file_exactly_at_the_limit() -> None:
    assert final_check.no_oversized_files({"a": final_check.MAX_FILE_BYTES}).ok


def test_repository_stays_small_rejects_a_tree_over_the_limit() -> None:
    sizes = {f"f{i}": final_check.MAX_FILE_BYTES for i in range(20)}
    assert sum(sizes.values()) > final_check.MAX_TRACKED_BYTES
    assert not final_check.repository_stays_small(sizes).ok


def test_this_repository_is_far_below_both_limits() -> None:
    tracked = final_check.tracked_files(REPO_ROOT)
    sizes = final_check.tracked_sizes(REPO_ROOT, tracked)
    assert final_check.no_oversized_files(sizes).ok
    assert final_check.repository_stays_small(sizes).ok
    assert sum(sizes.values()) < final_check.MAX_TRACKED_BYTES // 2


# ---------------------------------------------------------------------------
# Hygiene: secrets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pattern_name", sorted(FAKE_SECRETS))
def test_the_scanner_finds_every_credential_shape_it_declares(pattern_name: str) -> None:
    hits = final_check.scan_for_secrets("planted.txt", FAKE_SECRETS[pattern_name])
    assert any(hit.endswith(pattern_name) for hit in hits), f"{pattern_name} went undetected"


def test_every_declared_pattern_has_a_fixture() -> None:
    """A pattern nobody tests is a pattern that may not work."""
    assert set(FAKE_SECRETS) == {name for name, _ in final_check.SECRET_PATTERNS}


def test_the_scanner_reports_the_line_a_credential_is_on() -> None:
    text = "clean\nclean\n" + FAKE_SECRETS["aws-access-key-id"] + "\n"
    assert final_check.scan_for_secrets("f.py", text) == ["f.py:3: aws-access-key-id"]


def test_no_secret_material_rejects_a_planted_credential() -> None:
    outcome = final_check.no_secret_material({"config/prod.py": FAKE_SECRETS["openai-api-key"]})
    assert not outcome.ok
    assert outcome.evidence == ("config/prod.py:1: openai-api-key",)


def test_no_secret_material_admits_prose_that_merely_mentions_keys() -> None:
    prose = "Set SCV_ENABLE_PAID_API=1 to opt in. Never commit an api key or a token."
    assert final_check.no_secret_material({"docs/ADAPTERS.md": prose}).ok


def test_no_committed_file_contains_a_string_shaped_like_a_credential() -> None:
    tracked = final_check.tracked_files(REPO_ROOT)
    texts = final_check.tracked_texts(REPO_ROOT, tracked)
    outcome = final_check.no_secret_material(texts)
    assert outcome.ok, f"credential-shaped strings are committed: {outcome.evidence}"


def test_the_secret_scanner_is_not_exempt_from_itself() -> None:
    """The scanner and this test are scanned like every other tracked file.

    If this fails because either file is untracked, `git add` it — the property being
    asserted is about the committed tree, which is the only tree that can leak.
    """
    texts = final_check.tracked_texts(REPO_ROOT, final_check.tracked_files(REPO_ROOT))
    assert "src/scientific_claim_verifier/final_check.py" in texts
    assert "tests/test_final_check.py" in texts


def test_tracked_texts_skips_a_file_too_large_to_be_source(tmp_path: Path) -> None:
    (tmp_path / "big.csv").write_text("x")
    sizes = {"big.csv": final_check.MAX_FILE_BYTES + 1}
    assert final_check.tracked_texts(tmp_path, ["big.csv"], sizes) == {}


def test_tracked_texts_skips_a_binary_file(tmp_path: Path) -> None:
    (tmp_path / "blob").write_bytes(b"MZ\x00\x00payload")
    assert final_check.tracked_texts(tmp_path, ["blob"]) == {}


# ---------------------------------------------------------------------------
# Hygiene: paid-API outputs
# ---------------------------------------------------------------------------


def test_no_paid_api_outputs_admits_this_repository() -> None:
    tracked = final_check.tracked_files(REPO_ROOT)
    outcome = final_check.no_paid_api_outputs(REPO_ROOT, tracked)
    assert outcome.ok, outcome.evidence
    assert "recorded-fixture-v1" in outcome.detail


@pytest.mark.parametrize("path", ["results/cache/llm/deadbeef.json", "results/runs/x.cache.json"])
def test_no_paid_api_outputs_rejects_a_tracked_response_cache(path: str) -> None:
    outcome = final_check.no_paid_api_outputs(REPO_ROOT, [path])
    assert not outcome.ok
    assert any(path in item for item in outcome.evidence)


def test_no_paid_api_outputs_rejects_a_repository_with_no_recordings(tmp_path: Path) -> None:
    outcome = final_check.no_paid_api_outputs(tmp_path, [])
    assert not outcome.ok


# ---------------------------------------------------------------------------
# The working tree, and the two checks that shell out
# ---------------------------------------------------------------------------


def test_working_tree_is_clean_accepts_an_empty_porcelain() -> None:
    outcome = final_check.working_tree_is_clean("")
    assert outcome.ok
    assert "push state is not checkable" in outcome.detail


def test_working_tree_is_clean_rejects_a_dirty_porcelain() -> None:
    outcome = final_check.working_tree_is_clean(" M src/a.py\n?? b.txt\n")
    assert not outcome.ok
    assert outcome.evidence == (" M src/a.py", "?? b.txt")


def test_the_live_working_tree_check_runs_but_its_verdict_is_not_a_property_of_the_code(
    live_report: FinalCheckReport,
) -> None:
    """Whether the tree is clean depends on when pytest ran. That it was *asked* does not."""
    assert "working_tree_is_clean" in live_report.ran


def test_process_verdict_accepts_a_zero_exit() -> None:
    outcome = final_check.process_verdict("lint_is_clean", "ruff check .", 0, "All checks passed!")
    assert outcome.ok and outcome.evidence == ()


def test_process_verdict_rejects_a_non_zero_exit_and_keeps_the_tail() -> None:
    output = "\n".join(f"line {i}" for i in range(20))
    outcome = final_check.process_verdict("tests_pass", "pytest -q", 1, output)
    assert not outcome.ok
    assert outcome.evidence == tuple(f"line {i}" for i in range(14, 20))
    assert "exited 1" in outcome.detail


def test_tests_pass_refuses_to_spawn_pytest_from_inside_pytest() -> None:
    with pytest.raises(RecursionRefused):
        final_check.tests_pass(REPO_ROOT)


def test_run_checks_refuses_the_subprocess_checks_from_inside_pytest() -> None:
    with pytest.raises(RecursionRefused):
        final_check.run_checks(REPO_ROOT)


def test_check_and_report_exits_2_when_the_gate_cannot_run(capsys) -> None:
    """A gate that could not run must not report a verdict. Exit 2 is neither pass nor fail."""
    assert final_check.check_and_report(repo_root=REPO_ROOT, subprocess_checks=True) == 2
    assert "final-check could not run" in capsys.readouterr().err


def test_git_helpers_refuse_a_directory_that_is_not_a_repository(tmp_path: Path) -> None:
    with pytest.raises(GitUnavailable):
        final_check.tracked_files(tmp_path)


def test_tracked_files_are_sorted_and_non_empty() -> None:
    tracked = final_check.tracked_files(REPO_ROOT)
    assert tracked and list(tracked) == sorted(tracked)
    assert "pyproject.toml" in tracked


# ---------------------------------------------------------------------------
# Quality gates: fixtures, suite, checks, reports
# ---------------------------------------------------------------------------


def test_fixtures_validate_admits_this_repository() -> None:
    report = validation.validate_tasks(REPO_ROOT / "tasks", repo_root=REPO_ROOT)
    assert final_check.fixtures_validate(report).ok


def test_fixtures_validate_rejects_a_failing_task() -> None:
    report = validation.ValidationReport(tasks_dir=Path("tasks"))
    report.results.append(
        validation.TaskValidation(path=Path("tasks/x.yaml"), errors=["bundle_id is missing"])
    )
    outcome = final_check.fixtures_validate(report)
    assert not outcome.ok
    assert "bundle_id is missing" in outcome.evidence[0]


def test_fixtures_validate_rejects_a_directory_with_no_tasks() -> None:
    outcome = final_check.fixtures_validate(validation.ValidationReport(tasks_dir=Path("tasks")))
    assert not outcome.ok
    assert outcome.evidence == ("no task files were found",)


@pytest.fixture(scope="module")
def suite_run() -> suite.SuiteRun:
    from scientific_claim_verifier.artifacts import loader

    return suite.run_suite(loader.load_suite(REPO_ROOT / suite.DEFAULT_SUITE), repo_root=REPO_ROOT)


def test_smoke_suite_runs_offline_admits_the_committed_suite(suite_run: suite.SuiteRun) -> None:
    outcome = final_check.smoke_suite_runs_offline(suite_run, suite.gate(suite_run))
    assert outcome.ok
    assert suite_run.n_tasks >= final_check.MIN_SUITE_TASKS


def test_smoke_suite_runs_offline_rejects_a_suite_that_is_too_short(
    suite_run: suite.SuiteRun,
) -> None:
    short = dataclasses.replace(suite_run, records=suite_run.records[:3])
    outcome = final_check.smoke_suite_runs_offline(short, suite.Gate(ok=True))
    assert not outcome.ok
    assert "the plan requires" in outcome.evidence[0]


def test_smoke_suite_runs_offline_rejects_a_failing_gate(suite_run: suite.SuiteRun) -> None:
    failing = suite.Gate(ok=False, problems=("wrong verdict: dataset_mean",))
    outcome = final_check.smoke_suite_runs_offline(suite_run, failing)
    assert not outcome.ok
    assert outcome.evidence == ("wrong verdict: dataset_mean",)


def test_smoke_suite_runs_offline_rejects_a_run_that_skipped_execution(
    suite_run: suite.SuiteRun,
) -> None:
    """`--no-execute` makes the gate inapplicable, and an inapplicable gate decides nothing."""
    outcome = final_check.smoke_suite_runs_offline(suite_run, suite.Gate(ok=True, applicable=False))
    assert not outcome.ok


@pytest.mark.parametrize("status", [CheckStatus.PASS, CheckStatus.FAIL])
def test_dataset_statistic_recomputed_accepts_a_pass_and_a_fail(status: CheckStatus) -> None:
    checks = [a_check(CheckType.DATASET_STATISTIC, status)]
    assert final_check.dataset_statistic_recomputed(checks).ok


@pytest.mark.parametrize(
    "status", [CheckStatus.SKIPPED, CheckStatus.ERROR, CheckStatus.INCONCLUSIVE]
)
def test_dataset_statistic_recomputed_rejects_a_statistic_that_computed_nothing(
    status: CheckStatus,
) -> None:
    checks = [a_check(CheckType.DATASET_STATISTIC, status)]
    assert not final_check.dataset_statistic_recomputed(checks).ok


def test_dataset_statistic_recomputed_rejects_a_run_with_no_statistic_at_all() -> None:
    checks = [a_check(CheckType.TABLE_VALUE, CheckStatus.PASS)]
    assert not final_check.dataset_statistic_recomputed(checks).ok


def test_table_claim_checked_accepts_a_contradicted_table_value() -> None:
    """A table check that *fails* has still checked the table. `contradicted_f1` is the case."""
    assert final_check.table_claim_checked([a_check(CheckType.TABLE_VALUE, CheckStatus.FAIL)]).ok


def test_table_claim_checked_rejects_a_run_with_no_table_value() -> None:
    assert not final_check.table_claim_checked([a_check(CheckType.COMPARISON, CheckStatus.PASS)]).ok


def test_code_reproduction_counts_a_script_that_ran_and_errored() -> None:
    """`unreproducible_accuracy` exits 1 by design: the sandbox executed it, which is the ask.

    This is the one place `error` means success, and the reason the three "at least one"
    checks are not the same function with a different argument.
    """
    checks = [a_check(CheckType.CODE_EXECUTION, CheckStatus.ERROR)]
    outcome = final_check.code_reproduction_executed(checks)
    assert outcome.ok
    assert "0 reproduced" in outcome.detail


def test_code_reproduction_rejects_a_run_in_which_no_script_started() -> None:
    checks = [a_check(CheckType.CODE_EXECUTION, CheckStatus.SKIPPED)]
    outcome = final_check.code_reproduction_executed(checks)
    assert not outcome.ok
    assert outcome.evidence == ("every code_execution check was skipped",)


def test_the_three_at_least_one_checks_agree_with_the_live_suite(suite_run: suite.SuiteRun) -> None:
    checks = [c for record in suite_run.records for c in record.scored.result.computed_checks]
    assert final_check.dataset_statistic_recomputed(checks).ok
    assert final_check.table_claim_checked(checks).ok
    assert final_check.code_reproduction_executed(checks).ok


def test_reports_render_from_traces_rejects_a_directory_with_no_traces(tmp_path: Path) -> None:
    outcome = final_check.reports_render_from_traces(tmp_path, tmp_path / "out")
    assert not outcome.ok
    assert outcome.detail == "no traces were found"


def test_reports_render_from_traces_rejects_a_malformed_trace(tmp_path: Path) -> None:
    (tmp_path / "broken.trace.jsonl").write_text('{"kind": "not-a-scoring-event"}\n')
    outcome = final_check.reports_render_from_traces(tmp_path, tmp_path / "out")
    assert not outcome.ok
    assert outcome.detail == "a trace would not render"


def test_reports_render_from_traces_renders_the_live_suite(tmp_path: Path) -> None:
    from scientific_claim_verifier.artifacts import loader

    run_dir = tmp_path / "run"
    loaded = loader.load_suite(REPO_ROOT / suite.DEFAULT_SUITE)
    run = suite.run_suite(loaded, out_dir=run_dir, repo_root=REPO_ROOT)
    outcome = final_check.reports_render_from_traces(run_dir, tmp_path / "reports")
    assert outcome.ok
    assert f"{run.n_tasks} report(s)" in outcome.detail


# ---------------------------------------------------------------------------
# Quality gates: the documentation floor
# ---------------------------------------------------------------------------


def _doc_tree(root: Path) -> None:
    """A minimal repository that satisfies `docs_explain_the_system`."""
    (root / "docs").mkdir(parents=True, exist_ok=True)
    body = "prose. " * final_check.MIN_DOC_CHARS
    for name in final_check.REQUIRED_DOCS:
        (root / "docs" / name).write_text(body, encoding="utf-8")
    links = "\n".join(f"See [x](docs/{name})" for name in final_check.REQUIRED_DOCS)
    (root / "README.md").write_text(links, encoding="utf-8")


def test_docs_explain_the_system_admits_this_repository() -> None:
    outcome = final_check.docs_explain_the_system(REPO_ROOT)
    assert outcome.ok, outcome.evidence


def test_docs_explain_the_system_admits_a_minimal_tree(tmp_path: Path) -> None:
    _doc_tree(tmp_path)
    assert final_check.docs_explain_the_system(tmp_path).ok


def test_docs_explain_the_system_rejects_a_deleted_document(tmp_path: Path) -> None:
    _doc_tree(tmp_path)
    (tmp_path / "docs" / "SAFETY.md").unlink()
    outcome = final_check.docs_explain_the_system(tmp_path)
    assert not outcome.ok
    assert "safety: docs/SAFETY.md does not exist" in outcome.evidence


def test_docs_explain_the_system_rejects_an_emptied_document(tmp_path: Path) -> None:
    _doc_tree(tmp_path)
    (tmp_path / "docs" / "LIMITATIONS.md").write_text("TODO", encoding="utf-8")
    outcome = final_check.docs_explain_the_system(tmp_path)
    assert not outcome.ok
    assert any("under a" in item for item in outcome.evidence)


def test_docs_explain_the_system_rejects_an_orphaned_document(tmp_path: Path) -> None:
    _doc_tree(tmp_path)
    (tmp_path / "README.md").write_text("nothing links anywhere", encoding="utf-8")
    outcome = final_check.docs_explain_the_system(tmp_path)
    assert not outcome.ok
    assert len(outcome.evidence) == len(final_check.REQUIRED_DOCS)


# ---------------------------------------------------------------------------
# Quality gates: the static audit
# ---------------------------------------------------------------------------


def test_audit_module_finds_a_network_import() -> None:
    network, dynamic = final_check.audit_module("import socket\n")
    assert network == {"socket"} and dynamic == set()


def test_audit_module_finds_a_network_import_written_as_from() -> None:
    network, _ = final_check.audit_module("from urllib.request import urlopen\n")
    assert network == {"urllib.request"}


def test_audit_module_ignores_a_network_name_inside_a_string() -> None:
    """The sandbox bootstrap is a *string* of code the child runs to disable `socket`.

    The parent never imports it, so an AST audit must not see it — and a substring scan,
    which would, is the wrong tool. See `sandbox/policy.py::SITECUSTOMIZE_SOURCE`.
    """
    source = 'BOOTSTRAP = """\nimport socket\nsocket.socket = None\n"""\n'
    network, dynamic = final_check.audit_module(source)
    assert network == set() and dynamic == set()


def test_audit_module_ignores_a_relative_import_of_a_similar_name() -> None:
    network, _ = final_check.audit_module("from .http import render\n")
    assert network == set()


def test_audit_module_does_not_confuse_html_for_http() -> None:
    network, _ = final_check.audit_module("import html\nfrom html import escape\n")
    assert network == set()


@pytest.mark.parametrize(
    "source",
    [
        "import importlib\nimportlib.import_module('socket')\n",
        "exec('import socket')\n",
        "eval('__import__(\"socket\")')\n",
        "__import__('socket')\n",
        "compile('import socket', '<s>', 'exec')\n",
    ],
)
def test_audit_module_finds_every_way_to_hide_an_import(source: str) -> None:
    _, dynamic = final_check.audit_module(source)
    assert dynamic, f"a dynamic import slipped past the audit: {source!r}"


def test_audit_module_does_not_flag_an_attribute_call_that_merely_resembles_one() -> None:
    _, dynamic = final_check.audit_module("import re\nre.compile('x')\n")
    assert dynamic == set()


def test_nothing_imports_a_network_client_admits_this_repository() -> None:
    outcome = final_check.nothing_imports_a_network_client(REPO_ROOT)
    assert outcome.ok, outcome.evidence
    assert "0 network imports" in outcome.detail


def test_the_only_allowlisted_dynamic_import_is_the_environment_probe() -> None:
    """Pinned deliberately. A second entry is a decision, and should read like one."""
    assert list(final_check.DYNAMIC_IMPORT_ALLOWLIST) == [
        "src/scientific_claim_verifier/envcheck.py"
    ]
    for reason in final_check.DYNAMIC_IMPORT_ALLOWLIST.values():
        assert len(reason) > 40, "an allowlist entry must carry a reason, not a shrug"


def test_every_allowlisted_module_exists() -> None:
    for rel in final_check.DYNAMIC_IMPORT_ALLOWLIST:
        assert (REPO_ROOT / rel).is_file()


def _audited_tree(root: Path, source: str, name: str = "mod.py") -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / name).write_text(source, encoding="utf-8")


def test_nothing_imports_a_network_client_rejects_a_module_that_imports_socket(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(final_check, "DYNAMIC_IMPORT_ALLOWLIST", {})
    _audited_tree(tmp_path, "import socket\n")
    outcome = final_check.nothing_imports_a_network_client(tmp_path)
    assert not outcome.ok
    assert outcome.evidence == ("src/mod.py: imports socket",)


def test_nothing_imports_a_network_client_rejects_an_unlisted_dynamic_import(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(final_check, "DYNAMIC_IMPORT_ALLOWLIST", {})
    _audited_tree(tmp_path, "import importlib\nm = importlib.import_module('json')\n")
    outcome = final_check.nothing_imports_a_network_client(tmp_path)
    assert not outcome.ok
    assert "DYNAMIC_IMPORT_ALLOWLIST" in outcome.evidence[0]


def test_nothing_imports_a_network_client_admits_a_listed_dynamic_import(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(final_check, "DYNAMIC_IMPORT_ALLOWLIST", {"src/mod.py": "reason"})
    _audited_tree(tmp_path, "import importlib\nm = importlib.import_module('json')\n")
    assert final_check.nothing_imports_a_network_client(tmp_path).ok


def test_nothing_imports_a_network_client_rejects_a_stale_allowlist_entry(
    tmp_path: Path, monkeypatch
) -> None:
    """An allowlist that outlives its module is an exemption nobody is reading."""
    monkeypatch.setattr(final_check, "DYNAMIC_IMPORT_ALLOWLIST", {"src/gone.py": "reason"})
    _audited_tree(tmp_path, "x = 1\n")
    outcome = final_check.nothing_imports_a_network_client(tmp_path)
    assert not outcome.ok
    assert "no such module exists" in outcome.evidence[0]


# ---------------------------------------------------------------------------
# Quality gates: the paid API stays unreachable
# ---------------------------------------------------------------------------


def test_default_path_needs_no_paid_api_admits_this_repository() -> None:
    outcome = final_check.default_path_needs_no_paid_api(REPO_ROOT)
    assert outcome.ok, outcome.evidence
    assert "$0.00 guard" in outcome.detail


def test_default_path_needs_no_paid_api_rejects_a_priced_model() -> None:
    """An unpriced model is an uncallable one. Pricing one is how that stops being true."""
    cost.register_price("vendor-model-x", cost.ModelPrice(0.003, 0.015))
    try:
        outcome = final_check.default_path_needs_no_paid_api(REPO_ROOT)
        assert not outcome.ok
        assert any("vendor-model-x" in item for item in outcome.evidence)
    finally:
        cost.unregister_price("vendor-model-x")


def test_default_path_needs_no_paid_api_rejects_a_declared_http_client(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["pydantic>=2", "httpx>=0.27"]\n', encoding="utf-8"
    )
    outcome = final_check.default_path_needs_no_paid_api(tmp_path)
    assert not outcome.ok
    assert any("httpx" in item for item in outcome.evidence)


def test_the_price_table_prices_only_models_that_never_leave_the_process() -> None:
    for model, price in cost.price_table().items():
        assert price.prompt_usd_per_1k == 0.0 and price.completion_usd_per_1k == 0.0, model


# ---------------------------------------------------------------------------
# The live gate
# ---------------------------------------------------------------------------


def test_every_live_check_but_the_working_tree_passes(live_report: FinalCheckReport) -> None:
    """The repository satisfies its own definition of done.

    `working_tree_is_clean` is excluded on purpose: its verdict depends on whether a file
    was open in an editor when `pytest` ran, not on the code being tested. The script
    (`python3 scripts/08_final_check.py`) is where that verdict counts, and it is the last
    command run before a milestone commits.
    """
    failures = [o.name for o in live_report.failures if o.name != "working_tree_is_clean"]
    assert not failures, f"the repository fails its own gate: {failures}"


def test_the_cli_exposes_the_gate() -> None:
    import argparse

    from scientific_claim_verifier import cli

    parser = cli.build_parser()
    subparsers = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert "final-check" in subparsers[0].choices
