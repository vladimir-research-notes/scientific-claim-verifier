"""Milestone 8 — the offline smoke suite (CPU-only, offline).

Three things are pinned here:

1. **The suite file is real.** It parses, it names every committed task, and it names
   nothing that does not exist. `validate-fixtures` catches a broken one.
2. **The suite passes its own gate**, with no wrong verdicts and exactly the standing
   conservative miss it declares — and the gate genuinely *fails* when a regression is
   injected, so a passing gate means something.
3. **The artifacts are what they claim to be**: byte-identical traces, `summary.csv`,
   and `summary.json` across two runs into different directories.

The suite executes three committed, stdlib-only fixture scripts as child processes.
That is local, harmless, and offline; nothing here touches the network.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from scientific_claim_verifier import cli, suite
from scientific_claim_verifier import schemas as S
from scientific_claim_verifier.artifacts import loader, validation
from scientific_claim_verifier.scoring.summary import TaskOutcome, summarize

REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = REPO_ROOT / "tasks"
SUITE_PATH = TASKS_DIR / "smoke_suite.yaml"

# The quality gate in docs/PLAN.md §11: the smoke suite runs 8–15 tasks end to end.
MIN_SUITE_TASKS = 8
MAX_SUITE_TASKS = 15

# The one task whose gold support label the pipeline does not recover, because its
# lexical evidence check declines to decide rather than guessing. See docs/SCORING.md.
STANDING_MISS = "synthetic_data_passage"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load() -> loader.LoadedSuite:
    return loader.load_suite(SUITE_PATH)


def run(out_dir: Path | None = None, **kw: object) -> suite.SuiteRun:
    return suite.run_suite(load(), out_dir=out_dir, repo_root=REPO_ROOT, **kw)  # type: ignore[arg-type]


def outcome(
    task_id: str,
    predicted: S.SupportLabel,
    gold: S.SupportLabel,
) -> TaskOutcome:
    """A minimal outcome, for building synthetic runs the real fixtures cannot produce."""
    return TaskOutcome(
        task_id=task_id,
        claim_id=f"c_{task_id}",
        predicted_support=predicted,
        predicted_reproduction=S.ReproductionStatus.NOT_APPLICABLE,
        predicted_failure=S.FailureMode.NONE,
        gold_support=gold,
        gold_reproduction=S.ReproductionStatus.NOT_APPLICABLE,
        gold_failure=S.FailureMode.NONE,
    )


def synthetic_run(outcomes: list[TaskOutcome], declared_misses: list[str]) -> suite.SuiteRun:
    """A `SuiteRun` assembled from outcomes alone, to exercise :func:`suite.gate`."""
    spec = loader.SuiteSpec(
        suite_id="synthetic",
        task_ids=[o.task_id for o in outcomes],
        expected=loader.SuiteExpectation(conservative_misses=declared_misses),
    )
    records = tuple(
        suite.SuiteRecord(
            task_id=o.task_id,
            family="synthetic",
            claim_type="numeric_claim",
            scored=None,  # type: ignore[arg-type]  # `gate` reads only the outcomes
            outcome=o,
        )
        for o in outcomes
    )
    return suite.SuiteRun(spec=spec, records=records, summary=summarize(outcomes))


def digests(directory: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir())
    }


# ---------------------------------------------------------------------------
# Telling suites and tasks apart
# ---------------------------------------------------------------------------


def test_suite_documents_are_recognised_by_their_suite_id_key() -> None:
    assert loader.is_suite_document({"suite_id": "s", "task_ids": ["t"]})
    assert not loader.is_suite_document({"task_id": "t"})


def test_discovery_partitions_tasks_from_suites() -> None:
    tasks, suites = loader.discover_documents(TASKS_DIR)
    assert SUITE_PATH in suites
    assert SUITE_PATH not in tasks
    assert len(suites) == 1
    # Every remaining file loads as a task, which is what the other milestones assume.
    assert all(loader.load_task(path, REPO_ROOT) for path in tasks)


def test_an_unparseable_file_is_classified_as_a_task_so_validation_reports_it(
    tmp_path: Path,
) -> None:
    # Silently skipping it as "not a task" would hide the error.
    (tmp_path / "broken.yaml").write_text("task_id: [unterminated\n", encoding="utf-8")
    tasks, suites = loader.discover_documents(tmp_path)
    assert [p.name for p in tasks] == ["broken.yaml"] and suites == []

    report = validation.validate_tasks(tmp_path, REPO_ROOT)
    assert not report.ok
    assert "parse error" in report.results[0].errors[0]


def test_index_tasks_maps_every_task_id_and_skips_the_suite() -> None:
    index = loader.index_tasks(TASKS_DIR)
    assert "smoke_suite" not in index
    assert index["dataset_std"].name == "dataset_std.yaml"
    for task_id, path in index.items():
        assert loader.load_task(path, REPO_ROOT).spec.task_id == task_id


def test_index_tasks_rejects_a_duplicate_task_id(tmp_path: Path) -> None:
    body = "task_id: dup\n"
    (tmp_path / "a.yaml").write_text(body, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(body, encoding="utf-8")
    with pytest.raises(loader.SuiteLoadError, match="duplicate task_id"):
        loader.index_tasks(tmp_path)


# ---------------------------------------------------------------------------
# The suite file
# ---------------------------------------------------------------------------


def test_the_committed_suite_loads_and_resolves_every_task() -> None:
    loaded = load()
    assert loaded.suite_id == "smoke_suite"
    assert loaded.size == len(loaded.spec.task_ids)
    assert all(path.is_file() for path in loaded.task_paths)


def test_the_suite_meets_the_plan_s_size_gate() -> None:
    # docs/PLAN.md §11: "the smoke suite runs fully offline with >= 8 tasks end to end".
    assert MIN_SUITE_TASKS <= load().size <= MAX_SUITE_TASKS


def test_the_suite_runs_every_committed_task() -> None:
    # A task nobody runs is a task nobody maintains.
    assert set(load().spec.task_ids) == set(loader.index_tasks(TASKS_DIR))


def test_the_suite_exposes_the_milestone_1_benchmark_suite_model() -> None:
    benchmark = load().spec.benchmark_suite
    assert isinstance(benchmark, S.BenchmarkSuite)
    assert benchmark.suite_id == "smoke_suite"
    assert benchmark.size == load().size


def test_a_suite_may_not_repeat_a_task_id() -> None:
    with pytest.raises(ValidationError, match="duplicate task_id"):
        loader.SuiteSpec(suite_id="s", task_ids=["a", "b", "a"])


def test_a_suite_may_not_declare_a_miss_for_a_task_it_does_not_run() -> None:
    with pytest.raises(ValidationError, match="not in the suite"):
        loader.SuiteSpec(
            suite_id="s",
            task_ids=["a"],
            expected=loader.SuiteExpectation(conservative_misses=["b"]),
        )


def test_loading_a_task_file_as_a_suite_fails_loudly() -> None:
    with pytest.raises(loader.SuiteLoadError, match="is not a suite"):
        loader.load_suite(TASKS_DIR / "statistical_claims" / "dataset_mean.yaml")


def test_a_suite_naming_an_unknown_task_fails_to_load(tmp_path: Path) -> None:
    (tmp_path / "s.yaml").write_text("suite_id: s\ntask_ids: [nope]\n", encoding="utf-8")
    with pytest.raises(loader.SuiteLoadError, match="nope"):
        loader.load_suite(tmp_path / "s.yaml", tasks_dir=tmp_path)


def test_validate_fixtures_checks_the_suite_and_its_task_references(tmp_path: Path) -> None:
    good = validation.validate_suite_file(SUITE_PATH, TASKS_DIR)
    assert good.ok and good.kind == validation.SUITE and good.task_id == "smoke_suite"

    (tmp_path / "smoke_suite.yaml").write_text(
        "suite_id: smoke_suite\ntask_ids: [ghost]\n", encoding="utf-8"
    )
    bad = validation.validate_suite_file(tmp_path / "smoke_suite.yaml", tmp_path)
    assert not bad.ok
    assert "ghost" in bad.errors[0]


def test_the_repository_fixtures_and_suite_all_validate() -> None:
    report = validation.validate_tasks(TASKS_DIR, REPO_ROOT)
    assert report.ok, {str(r.path): r.errors for r in report.results if not r.ok}
    assert report.n_suites == 1
    assert report.n_tasks >= MIN_SUITE_TASKS
    assert "(suite)" in validation.format_report(report)


# ---------------------------------------------------------------------------
# Running the suite
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def suite_run() -> suite.SuiteRun:
    """One real end-to-end run, shared: it executes three fixture scripts."""
    return run()


def test_the_suite_runs_its_tasks_in_declared_order(suite_run: suite.SuiteRun) -> None:
    assert [r.task_id for r in suite_run.records] == list(suite_run.spec.task_ids)


def test_the_committed_suite_passes_its_own_gate(suite_run: suite.SuiteRun) -> None:
    # The headline result. Every part of it is a separate assertion, because
    # "the gate passed" would still pass if the gate checked nothing.
    decision = suite.gate(suite_run)
    assert decision.applicable
    assert decision.ok, decision.problems
    assert suite_run.summary.wrong_verdicts == ()
    assert suite_run.summary.conservative_misses == (STANDING_MISS,)
    n = suite_run.n_tasks
    assert suite_run.summary.support_agreement == n - 1
    assert suite_run.summary.reproduction_agreement == n
    assert suite_run.summary.failure_agreement == n - 1


def test_the_suite_exercises_every_evidence_channel(suite_run: suite.SuiteRun) -> None:
    checks = [c for r in suite_run.records for c in r.scored.result.computed_checks]
    kinds = {c.check_type for c in checks}
    assert S.CheckType.EVIDENCE_PRESENCE in kinds
    assert S.CheckType.TABLE_VALUE in kinds
    assert S.CheckType.DATASET_STATISTIC in kinds
    assert S.CheckType.CODE_EXECUTION in kinds
    # ... and every check status, including the three that decide nothing.
    assert {c.status for c in checks} == set(S.CheckStatus)


def test_the_suite_reaches_the_verdicts_no_single_fixture_could(
    suite_run: suite.SuiteRun,
) -> None:
    # The point of enlarging the fixture set in M8: labels and statuses that the
    # original seven tasks never produced now have a task each.
    by_id = {r.task_id: r for r in suite_run.records}
    assert by_id["dataset_std"].outcome.predicted_reproduction is (
        S.ReproductionStatus.APPROXIMATELY_REPRODUCED
    )
    assert by_id["dataset_mean_overstated"].outcome.predicted_reproduction is (
        S.ReproductionStatus.FAILED_NUMERIC_MISMATCH
    )
    assert by_id["unreproducible_accuracy"].outcome.predicted_support is (
        S.SupportLabel.PARTIALLY_SUPPORTED
    )
    assert by_id["negated_training_data"].outcome.predicted_failure is (
        S.FailureMode.PASSAGE_DOES_NOT_ASSERT
    )


def test_a_script_that_will_not_run_refutes_nothing(suite_run: suite.SuiteRun) -> None:
    # `failed_environment`, never `failed_numeric_mismatch`: no number disagreed,
    # because no number exists. The claim keeps the support its text gives it.
    record = next(r for r in suite_run.records if r.task_id == "unreproducible_accuracy")
    result = record.scored.result
    assert result.reproduction_status is S.ReproductionStatus.FAILED_ENVIRONMENT
    assert result.support_label is not S.SupportLabel.CONTRADICTED
    numeric = next(
        c for c in result.computed_checks if c.check_type is S.CheckType.NUMERIC_TOLERANCE
    )
    assert numeric.status is S.CheckStatus.SKIPPED


def test_no_execute_disables_the_gate_rather_than_blaming_the_pipeline() -> None:
    # Skipping the scripts turns three supported claims into partially_supported ones.
    # Those are not regressions, and the gate must not call them wrong verdicts.
    without = run(execute=False)
    assert without.summary.wrong_verdicts  # the raw comparison does shift
    decision = suite.gate(without)
    assert not decision.applicable
    assert decision.ok and decision.problems == ()
    assert "NOT APPLICABLE" in suite.render_suite(without, decision)


# ---------------------------------------------------------------------------
# The gate itself: it must fail when it should
# ---------------------------------------------------------------------------


def test_gate_fails_on_a_wrong_verdict() -> None:
    bad = synthetic_run(
        [outcome("a", S.SupportLabel.SUPPORTED, S.SupportLabel.CONTRADICTED)],
        declared_misses=[],
    )
    decision = suite.gate(bad)
    assert not decision.ok
    assert "wrong verdict: a" in decision.problems[0]


def test_gate_fails_on_a_new_conservative_miss() -> None:
    shy = synthetic_run(
        [outcome("a", S.SupportLabel.UNVERIFIABLE_FROM_ARTIFACTS, S.SupportLabel.SUPPORTED)],
        declared_misses=[],
    )
    decision = suite.gate(shy)
    assert not decision.ok
    assert "new conservative miss: a" in decision.problems[0]


def test_gate_fails_when_a_declared_miss_is_no_longer_missing() -> None:
    # A stale expectation is a lie about the pipeline, so it fails too.
    fixed = synthetic_run(
        [outcome("a", S.SupportLabel.SUPPORTED, S.SupportLabel.SUPPORTED)],
        declared_misses=["a"],
    )
    decision = suite.gate(fixed)
    assert not decision.ok
    assert "stale conservative miss: a" in decision.problems[0]


def test_gate_passes_when_the_declared_miss_is_exactly_the_observed_one() -> None:
    ok = synthetic_run(
        [
            outcome("a", S.SupportLabel.UNVERIFIABLE_FROM_ARTIFACTS, S.SupportLabel.SUPPORTED),
            outcome("b", S.SupportLabel.CONTRADICTED, S.SupportLabel.CONTRADICTED),
        ],
        declared_misses=["a"],
    )
    assert suite.gate(ok).ok


def test_a_contradicted_claim_is_not_a_failure() -> None:
    # Finding a contradiction is the tool working. `contradicted_f1` must not fail a run.
    found = synthetic_run(
        [outcome("a", S.SupportLabel.CONTRADICTED, S.SupportLabel.CONTRADICTED)],
        declared_misses=[],
    )
    assert suite.gate(found).ok


def test_the_suite_file_cannot_bless_a_wrong_verdict() -> None:
    # There is no key for it. Adding one would be the single most damaging change
    # possible to this harness, so the schema refuses the field outright.
    with pytest.raises(ValidationError):
        loader.SuiteExpectation(wrong_verdicts=["anything"])  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


def test_run_writes_a_trace_and_a_result_for_every_task(tmp_path: Path) -> None:
    written = run(tmp_path)
    suite.write_artifacts(written)
    for record in written.records:
        assert (tmp_path / f"{record.task_id}.trace.jsonl").is_file()
        assert (tmp_path / f"{record.task_id}.result.json").is_file()
    for name in (suite.SUMMARY_JSON, suite.SUMMARY_CSV, suite.SUMMARY_TXT):
        assert (tmp_path / name).is_file()


def test_summary_csv_has_one_row_per_task_and_no_absolute_paths(
    suite_run: suite.SuiteRun, tmp_path: Path
) -> None:
    written = run(tmp_path)
    rows = list(csv.DictReader(io.StringIO(suite.summary_csv(written))))
    assert len(rows) == written.n_tasks
    assert list(rows[0]) == list(suite.SUMMARY_CSV_COLUMNS)
    assert [r["task_id"] for r in rows] == list(written.spec.task_ids)
    for row in rows:
        assert row["trace"] == f"{row['task_id']}.trace.jsonl"
        assert not row["trace"].startswith("/")
    miss = next(r for r in rows if r["task_id"] == STANDING_MISS)
    assert miss["support_outcome"] == suite.CONSERVATIVE_MISS
    assert miss["confidence"] == "0.000000"
    assert all(r["support_outcome"] != suite.WRONG_VERDICT for r in rows)


def test_summary_csv_check_counts_agree_with_the_recorded_checks(
    suite_run: suite.SuiteRun,
) -> None:
    for record in suite_run.records:
        row = suite.summary_row(record)
        assert row["n_checks"] == len(record.scored.result.computed_checks)
        assert row["n_checks"] == sum(record.check_counts.values())


def test_summary_json_carries_the_suite_the_gate_and_the_aggregate(
    suite_run: suite.SuiteRun,
) -> None:
    payload = suite.suite_to_dict(suite_run)
    assert json.dumps(payload)  # JSON-ready, no enums left behind
    assert payload["suite"]["n_tasks"] == suite_run.n_tasks
    assert payload["suite"]["scripts_executed"] is True
    assert payload["gate"] == {"ok": True, "applicable": True, "problems": []}
    assert payload["summary"]["wrong_verdicts"] == []
    # `summary.tasks` and `tasks` describe the same tasks and join on task_id.
    assert [t["task_id"] for t in payload["tasks"]] == [
        t["task_id"] for t in payload["summary"]["tasks"]
    ]


def test_summary_txt_is_the_report_that_was_printed(tmp_path: Path) -> None:
    written = run(tmp_path)
    suite.write_artifacts(written)
    body = (tmp_path / suite.SUMMARY_TXT).read_text(encoding="utf-8")
    assert body == suite.render_suite(written) + "\n"
    assert "Gate            : PASS" in body


def test_no_artifacts_are_written_without_an_output_directory(suite_run: suite.SuiteRun) -> None:
    assert suite.write_artifacts(suite_run) == []
    assert all(record.trace_name is None for record in suite_run.records)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_two_runs_produce_byte_identical_traces_and_summaries(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    for target in (first, second):
        written = run(target)
        suite.write_artifacts(written)

    left, right = digests(first), digests(second)
    assert set(left) == set(right)

    stable = [n for n in left if n.endswith(".trace.jsonl")] + [
        suite.SUMMARY_CSV,
        suite.SUMMARY_JSON,
    ]
    for name in stable:
        assert left[name] == right[name], f"{name} is not byte-reproducible"

    # The two that legitimately differ do so in exactly one field: the path they name.
    assert left[suite.SUMMARY_TXT] != right[suite.SUMMARY_TXT]
    for name in (n for n in left if n.endswith(".result.json")):
        a = json.loads((first / name).read_text(encoding="utf-8"))
        b = json.loads((second / name).read_text(encoding="utf-8"))
        assert a["result"].pop("trace_path") != b["result"].pop("trace_path")
        assert a == b


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_run_suite_passes_and_writes_artifacts(tmp_path: Path, capsys) -> None:
    code = cli.main(["run-suite", "--suite", str(SUITE_PATH), "--out", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Gate            : PASS" in out
    assert (tmp_path / "smoke_suite" / suite.SUMMARY_CSV).is_file()


def test_cli_run_suite_json_is_machine_readable(capsys) -> None:
    assert cli.main(["run-suite", "--json", "--suite", str(SUITE_PATH)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["gate"]["ok"] is True
    assert payload["suite"]["suite_id"] == "smoke_suite"


def test_the_default_suite_is_the_one_the_plan_advertises() -> None:
    # docs/PLAN.md §10: `claimverifier run-suite --suite tasks/smoke_suite.yaml`.
    assert suite.DEFAULT_SUITE == "tasks/smoke_suite.yaml"
    assert (REPO_ROOT / suite.DEFAULT_SUITE) == SUITE_PATH


def test_cli_run_suite_reports_a_missing_suite_file(tmp_path: Path, capsys) -> None:
    assert cli.main(["run-suite", "--suite", str(tmp_path / "absent.yaml")]) == 1
    assert "could not load suite" in capsys.readouterr().err


def test_cli_run_suite_reports_a_schema_error_rather_than_raising(tmp_path: Path, capsys) -> None:
    # A `wrong_verdicts` key is a fact about the file, not a bug in the runner: the CLI
    # must print what is wrong and exit 1, never hand the user a pydantic traceback.
    broken = tmp_path / "broken.yaml"
    broken.write_text(
        "suite_id: broken\ntask_ids: [dataset_mean]\nexpected:\n  wrong_verdicts: [dataset_mean]\n",
        encoding="utf-8",
    )
    assert cli.main(["run-suite", "--suite", str(broken), "--tasks-dir", str(TASKS_DIR)]) == 1
    err = capsys.readouterr().err
    assert "could not load suite" in err
    assert "wrong_verdicts" in err


def test_cli_run_suite_reports_an_unknown_task_id(tmp_path: Path, capsys) -> None:
    broken = tmp_path / "ghosts.yaml"
    broken.write_text("suite_id: ghosts\ntask_ids: [ghost_task]\n", encoding="utf-8")
    assert cli.main(["run-suite", "--suite", str(broken), "--tasks-dir", str(TASKS_DIR)]) == 1
    assert "ghost_task" in capsys.readouterr().err


def test_cli_no_gate_reports_regressions_without_failing(tmp_path: Path, capsys) -> None:
    # A suite of one task whose gold outcome the pipeline cannot meet: the gate should
    # fail it, and `--no-gate` should report the same thing and exit 0 anyway.
    broken = tmp_path / "broken_suite.yaml"
    broken.write_text(
        "suite_id: broken_suite\ntask_ids: [synthetic_data_passage]\n", encoding="utf-8"
    )
    args = ["run-suite", "--suite", str(broken), "--tasks-dir", str(TASKS_DIR)]
    assert cli.main(args) == 1
    assert "new conservative miss: synthetic_data_passage" in capsys.readouterr().out
    assert cli.main([*args, "--no-gate"]) == 0


def test_the_script_entry_point_runs_the_suite() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "05_run_smoke_suite.py")],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    assert "Gate            : PASS" in result.stdout


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


def test_support_outcome_classifies_the_three_ways_a_task_can_land() -> None:
    def outcome_of(predicted: S.SupportLabel, gold: S.SupportLabel) -> str:
        record = synthetic_run([outcome("a", predicted, gold)], []).records[0]
        return record.support_outcome

    supported, contradicted = S.SupportLabel.SUPPORTED, S.SupportLabel.CONTRADICTED
    unverifiable = S.SupportLabel.UNVERIFIABLE_FROM_ARTIFACTS
    assert outcome_of(supported, supported) == suite.MATCH
    assert outcome_of(unverifiable, supported) == suite.CONSERVATIVE_MISS
    assert outcome_of(supported, contradicted) == suite.WRONG_VERDICT


def test_fully_matches_requires_all_three_fields(suite_run: suite.SuiteRun) -> None:
    by_id = {r.task_id: r for r in suite_run.records}
    assert by_id["dataset_mean"].fully_matches
    # The standing miss matches on reproduction but not on support or failure mode.
    miss = by_id[STANDING_MISS]
    assert not miss.fully_matches
    assert miss.outcome.reproduction_matches

    # A record differing only in failure mode is not a full match either.
    shifted = replace(
        miss, outcome=replace(miss.outcome, gold_support=miss.outcome.predicted_support)
    )
    assert not shifted.fully_matches
