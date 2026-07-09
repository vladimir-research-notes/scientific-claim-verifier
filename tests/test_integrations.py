"""Milestone 11 — integration contracts (CPU-only, offline, no external dependency).

These tests hold the export layer to the four promises its package docstring makes, and
to the one honesty claim that matters most.

- **No dependency on the named repos, checked rather than asserted.** Every module under
  ``integrations/`` is parsed and its imports enumerated: standard library, ``pydantic``,
  and this project. Nothing else.
- **An export is a function of committed artifacts.** ``evidence-records``, ``benchmark``,
  and ``metrics`` are built from traces (and, for gold, the summary those traces were
  written beside). Deleting the task files does not change them.
- **An export is deterministic and portable.** Two exports are byte-identical, and no
  document contains an absolute path.
- **An export is self-describing, and the reader is strict.** A document of the wrong
  format, or of a later major version, is refused by name.
- **The loop closes.** The 11 committed fixtures export as episodes, replay, and reproduce
  their recorded verdicts — byte-for-byte identical traces included. Then each replay
  failure mode is *injected* and shown to be caught: an edited fixture, an edited task
  file, a deleted task, a doctored verdict.

The ``benchmark`` format's declared primary metric is ``wrong_verdicts`` (lower is
better), not accuracy, and ``bucket`` is computed by the same ``TaskOutcome`` code the
suite gate reads — a test asserts the two cannot diverge.
"""

from __future__ import annotations

import ast
import json
import shutil
import sys
from pathlib import Path

import pytest

from scientific_claim_verifier import __version__, cli
from scientific_claim_verifier import integrations as I
from scientific_claim_verifier.artifacts import loader
from scientific_claim_verifier.integrations import (
    benchmark as bench_mod,
)
from scientific_claim_verifier.integrations import (
    envelope as env_mod,
)
from scientific_claim_verifier.integrations import (
    episodes as ep_mod,
)
from scientific_claim_verifier.integrations import (
    evidence_records as ev_mod,
)
from scientific_claim_verifier.integrations import (
    export as export_mod,
)
from scientific_claim_verifier.integrations import (
    metrics as metrics_mod,
)
from scientific_claim_verifier.integrations import (
    run as run_mod,
)
from scientific_claim_verifier.integrations import (
    runnable_tasks as rt_mod,
)
from scientific_claim_verifier.integrations.records import Controls, ExportContext, Verdict
from scientific_claim_verifier.sandbox.trace import read_trace
from scientific_claim_verifier.schemas import (
    SCHEMA_VERSION,
    CheckStatus,
    FailureMode,
    ReproductionStatus,
    SupportLabel,
)
from scientific_claim_verifier.scoring.verdict import SCORING_EVENT_KINDS
from scientific_claim_verifier.suite import CONSERVATIVE_MISS, MATCH, WRONG_VERDICT

REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = REPO_ROOT / "tasks"
SUITE_PATH = TASKS_DIR / "smoke_suite.yaml"
PACKAGE_DIR = REPO_ROOT / "src" / "scientific_claim_verifier" / "integrations"

#: The eleven committed fixtures, in the suite's declared order.
SUITE_TASK_IDS = (
    "synthetic_data_passage",
    "negated_training_data",
    "accuracy_improvement",
    "contradicted_f1",
    "underspecified_split",
    "dataset_mean",
    "dataset_std",
    "dataset_mean_overstated",
    "recompute_accuracy",
    "gc_content",
    "unreproducible_accuracy",
)

#: Every format the registry declares.
ALL_FORMATS = ("runnable-tasks", "evidence-records", "benchmark", "metrics", "episodes")

#: Formats built from a run directory.
RUN_FORMATS = ("evidence-records", "benchmark", "metrics", "episodes")


# ---------------------------------------------------------------------------
# Fixtures: one real suite run, shared. It executes three fixture scripts.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real ``run-suite`` run: eleven traces, eleven result JSONs, and a summary."""
    from scientific_claim_verifier import suite as suite_mod

    out = tmp_path_factory.mktemp("runs") / "smoke_suite"
    loaded = loader.load_suite(SUITE_PATH, TASKS_DIR)
    run = suite_mod.run_suite(loaded, out_dir=out, repo_root=REPO_ROOT)
    suite_mod.write_artifacts(run)
    return out


@pytest.fixture(scope="module")
def ctx(run_dir: Path) -> ExportContext:
    return ExportContext(repo_root=REPO_ROOT, run_dir=run_dir, tasks_dir=TASKS_DIR)


@pytest.fixture(scope="module")
def documents(ctx: ExportContext) -> dict[str, env_mod.Envelope]:
    """Every format, exported once from the shared run."""
    return {name: I.export_document(name, ctx) for name in ALL_FORMATS}


def payload_of(documents: dict[str, env_mod.Envelope], name: str) -> dict:
    return documents[name].payload


def strings_in(value: object) -> list[str]:
    """Every string anywhere in a JSON-ish structure, keys included."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (*strings_in(k), *strings_in(v))]
    if isinstance(value, list):
        return [s for item in value for s in strings_in(item)]
    return []


# ---------------------------------------------------------------------------
# The dependency claim — checked, not asserted
# ---------------------------------------------------------------------------

#: The only third-party package this layer may import.
ALLOWED_THIRD_PARTY = {"pydantic"}

#: Names that would betray a dependency on a system these formats are merely *shaped* for.
FORBIDDEN_ROOTS = {
    "bioagentbench",
    "bioscientist",
    "agent_control_bench",
    "agentcontrolbench",
    "code_agent",
    "codeagent",
}


def import_roots(path: Path) -> set[str]:
    """The top-level module of every absolute import in a source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_integration_modules_import_only_stdlib_pydantic_and_this_project() -> None:
    stdlib = set(sys.stdlib_module_names)
    ours = {"scientific_claim_verifier"}
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        extra = import_roots(path) - stdlib - ALLOWED_THIRD_PARTY - ours
        assert not extra, f"{path.name} imports {sorted(extra)}"


def test_no_integration_module_imports_the_repo_it_is_shaped_for() -> None:
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        roots = {root.lower() for root in import_roots(path)}
        assert not (roots & FORBIDDEN_ROOTS), f"{path.name} imports a named external repo"


def test_the_package_docstring_refuses_to_claim_compatibility() -> None:
    doc = I.__doc__ or ""
    assert "No external schema was consulted" in doc
    assert "proposed contracts" in doc


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_the_registry_declares_five_formats_one_per_consumer_role() -> None:
    assert I.FORMAT_NAMES == ALL_FORMATS
    consumers = [spec.consumer for spec in I.REGISTRY.values()]
    assert len(set(consumers)) == 5


def test_every_format_is_namespaced_and_version_one() -> None:
    for name, spec in I.REGISTRY.items():
        assert spec.format == f"{env_mod.FORMAT_PREFIX}{name}"
        assert spec.version == "1.0"


def test_every_format_declares_what_it_reads() -> None:
    assert I.REGISTRY["runnable-tasks"].needs == (I.NEEDS_TASKS,)
    assert I.REGISTRY["evidence-records"].needs == (I.NEEDS_RUN,)
    assert I.REGISTRY["benchmark"].needs == (I.NEEDS_RUN,)
    assert I.REGISTRY["metrics"].needs == (I.NEEDS_RUN,)
    assert I.REGISTRY["episodes"].needs == (I.NEEDS_RUN, I.NEEDS_TASKS)


def test_an_unknown_format_names_the_known_ones() -> None:
    with pytest.raises(I.IntegrationError, match="unknown export format"):
        I.spec_for("prometheus")


def test_a_formats_json_schema_comes_from_the_model_that_validates_it() -> None:
    schema = I.format_schema("metrics")
    assert schema["format"] == metrics_mod.FORMAT
    assert sorted(schema["payload"]["properties"]) == ["labels", "metrics"]
    assert "payload" in schema["envelope"]["properties"]


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------


def test_every_document_carries_the_header_a_consumer_needs(
    documents: dict[str, env_mod.Envelope],
) -> None:
    for name, envelope in documents.items():
        spec = I.REGISTRY[name]
        assert envelope.format == spec.format
        assert envelope.format_version == spec.version
        assert envelope.producer == env_mod.PRODUCER
        assert envelope.producer_version == __version__
        assert envelope.trace_schema_version == SCHEMA_VERSION


def test_an_envelope_round_trips_through_canonical_json(
    documents: dict[str, env_mod.Envelope],
) -> None:
    for envelope in documents.values():
        assert env_mod.loads(env_mod.dumps(envelope)) == envelope


def test_dumps_sorts_keys_and_ends_with_one_newline(
    documents: dict[str, env_mod.Envelope],
) -> None:
    text = env_mod.dumps(documents["metrics"])
    assert text.endswith("}\n")
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"


def test_the_reader_refuses_a_document_of_another_format(
    documents: dict[str, env_mod.Envelope],
) -> None:
    text = env_mod.dumps(documents["metrics"])
    with pytest.raises(env_mod.EnvelopeError, match="expected format 'scv.benchmark'"):
        env_mod.loads(text, expect=bench_mod.FORMAT)


def test_the_reader_refuses_a_later_major_version_but_reads_a_later_minor(
    documents: dict[str, env_mod.Envelope],
) -> None:
    document = json.loads(env_mod.dumps(documents["episodes"]))

    document["format_version"] = "2.0"
    with pytest.raises(env_mod.EnvelopeError, match="cannot be read safely"):
        env_mod.loads(json.dumps(document), expect=ep_mod.FORMAT, expect_version="1.0")

    document["format_version"] = "1.9"
    assert env_mod.loads(
        json.dumps(document), expect=ep_mod.FORMAT, expect_version="1.0"
    ).format_version == "1.9"


@pytest.mark.parametrize(
    "text, match",
    [
        ("not json at all", "not JSON"),
        ("[1, 2, 3]", "must be a JSON object"),
        ('{"format": "scv.metrics"}', "not an export envelope"),
    ],
)
def test_a_malformed_document_raises_envelope_error_not_a_bare_exception(
    text: str, match: str
) -> None:
    with pytest.raises(env_mod.EnvelopeError, match=match):
        env_mod.loads(text)


def test_an_unknown_header_field_is_an_error_not_a_shrug() -> None:
    text = json.dumps(
        {
            "format": "scv.metrics",
            "format_version": "1.0",
            "producer": "x",
            "producer_version": "1",
            "trace_schema_version": "1.3",
            "payload": {},
            "extra": "surprise",
        }
    )
    with pytest.raises(env_mod.EnvelopeError, match="not an export envelope"):
        env_mod.loads(text)


def test_read_names_the_file_it_could_not_read(tmp_path: Path) -> None:
    with pytest.raises(env_mod.EnvelopeError, match="cannot read export"):
        env_mod.read(tmp_path / "absent.json")


# ---------------------------------------------------------------------------
# The four properties that hold across every format
# ---------------------------------------------------------------------------


def test_exporting_twice_produces_identical_bytes(ctx: ExportContext) -> None:
    for name in ALL_FORMATS:
        first = env_mod.dumps(I.export_document(name, ctx))
        second = env_mod.dumps(I.export_document(name, ctx))
        assert first == second, name


def test_no_export_contains_an_absolute_path(documents: dict[str, env_mod.Envelope]) -> None:
    root = str(REPO_ROOT)
    for name, envelope in documents.items():
        for text in strings_in(envelope.model_dump(mode="json")):
            assert root not in text, f"{name} leaks the repository root"
            assert not text.startswith("/"), f"{name} carries an absolute path: {text!r}"


def test_an_export_is_independent_of_the_directory_the_run_was_written_to(
    run_dir: Path, tmp_path: Path
) -> None:
    """The one label naming the run is the directory's *name*, never its path."""
    elsewhere = tmp_path / "elsewhere" / run_dir.name
    shutil.copytree(run_dir, elsewhere)
    here = ExportContext(repo_root=REPO_ROOT, run_dir=run_dir, tasks_dir=TASKS_DIR)
    there = ExportContext(repo_root=REPO_ROOT, run_dir=elsewhere, tasks_dir=TASKS_DIR)
    for name in RUN_FORMATS:
        assert env_mod.dumps(I.export_document(name, here)) == env_mod.dumps(
            I.export_document(name, there)
        ), name


def test_trace_derived_exports_do_not_read_the_task_files(
    run_dir: Path, tmp_path: Path
) -> None:
    """``evidence-records``, ``benchmark``, and ``metrics`` are functions of the run alone."""
    empty = tmp_path / "no-tasks"
    empty.mkdir()
    ctx = ExportContext(repo_root=REPO_ROOT, run_dir=run_dir, tasks_dir=empty)
    for name in ("evidence-records", "benchmark", "metrics"):
        assert I.export_document(name, ctx).payload, name


def test_episodes_is_the_one_run_format_that_needs_the_task_files(
    run_dir: Path, tmp_path: Path
) -> None:
    empty = tmp_path / "no-tasks"
    empty.mkdir()
    ctx = ExportContext(repo_root=REPO_ROOT, run_dir=run_dir, tasks_dir=empty)
    with pytest.raises(I.IntegrationError, match="no task under"):
        I.export_document("episodes", ctx)


# ---------------------------------------------------------------------------
# The shared verdict record
# ---------------------------------------------------------------------------


def test_every_format_that_states_a_verdict_spells_it_the_same_way(
    documents: dict[str, env_mod.Envelope],
) -> None:
    keys = sorted(Verdict.model_fields)
    evidence = payload_of(documents, "evidence-records")["records"][0]["verdict"]
    record = payload_of(documents, "benchmark")["records"][0]
    episode = payload_of(documents, "episodes")["episodes"][0]["recorded"]
    runnable = payload_of(documents, "runnable-tasks")["tasks"][0]["expected"]["verdict"]
    for spelling in (evidence, record["predicted"], record["gold"], episode, runnable):
        assert sorted(spelling) == keys


def test_a_verdict_is_never_collapsed_to_one_score(
    documents: dict[str, env_mod.Envelope],
) -> None:
    record = payload_of(documents, "benchmark")["records"][0]["predicted"]
    assert {"support_label", "reproduction_status", "failure_mode"} <= set(record)
    assert "score" not in record


def test_a_gold_verdict_carries_no_confidence(documents: dict[str, env_mod.Envelope]) -> None:
    for record in payload_of(documents, "benchmark")["records"]:
        assert record["gold"]["confidence"] is None
        assert record["predicted"]["confidence"] is not None


# ---------------------------------------------------------------------------
# runnable-tasks — code-agent runtime
# ---------------------------------------------------------------------------


def test_runnable_tasks_exports_every_committed_task(
    documents: dict[str, env_mod.Envelope],
) -> None:
    tasks = payload_of(documents, "runnable-tasks")["tasks"]
    exported = {task["task_id"] for task in tasks}
    assert exported == set(SUITE_TASK_IDS)


def test_a_suite_file_selects_and_orders_the_runnable_tasks() -> None:
    ctx = ExportContext(repo_root=REPO_ROOT, tasks_dir=TASKS_DIR, suite_path=SUITE_PATH)
    tasks = rt_mod.build(ctx).tasks
    assert [task.task_id for task in tasks] == list(SUITE_TASK_IDS)


def test_the_exported_argv_actually_verifies_the_task(
    documents: dict[str, env_mod.Envelope], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The command in the document is the command that works, not a plausible one."""
    tasks = payload_of(documents, "runnable-tasks")["tasks"]
    task = next(t for t in tasks if t["task_id"] == "contradicted_f1")
    monkeypatch.chdir(REPO_ROOT)

    assert task["argv"][0] == "claimverifier"
    exit_code = cli.main([*task["argv"][1:], "--out", str(tmp_path)])
    assert exit_code == task["expected"]["exit_code"] == 0
    assert (tmp_path / "contradicted_f1.trace.jsonl").is_file()


def test_argv_encodes_the_controls_it_declares() -> None:
    controls = Controls(execute=False, use_declared_source=False, abs_tol=0.5, rel_tol=0.01)
    argv = rt_mod.argv_for("tasks/x.yaml", controls)
    assert argv[:4] == ["claimverifier", "verify", "--task", "tasks/x.yaml"]
    assert "--no-execute" in argv and "--no-declared-source" in argv
    assert argv[argv.index("--abs-tol") + 1] == "0.5"
    assert argv[argv.index("--rel-tol") + 1] == "0.01"


def test_hide_gold_removes_the_answer_and_keeps_the_success_criterion() -> None:
    ctx = ExportContext(repo_root=REPO_ROOT, tasks_dir=TASKS_DIR, hide_gold=True)
    for task in rt_mod.build(ctx).tasks:
        assert task.expected.verdict is None
        assert task.expected.exit_code == 0


def test_the_default_export_carries_gold_so_a_runtime_can_score_it(
    documents: dict[str, env_mod.Envelope],
) -> None:
    tasks = payload_of(documents, "runnable-tasks")["tasks"]
    task = next(t for t in tasks if t["task_id"] == "contradicted_f1")
    assert task["expected"]["verdict"]["support_label"] == "contradicted"


def test_a_runnable_task_lists_the_task_file_and_every_fixture_it_reads(
    documents: dict[str, env_mod.Envelope],
) -> None:
    tasks = {t["task_id"]: t for t in payload_of(documents, "runnable-tasks")["tasks"]}

    code_task = tasks["recompute_accuracy"]
    roles = [f["role"] for f in code_task["files"]]
    assert roles.count(rt_mod.TASK) == 1
    assert "code" in roles

    paths = [f["path"] for f in code_task["files"]]
    assert "tasks/code_reproduction/recompute_accuracy.yaml" in paths
    assert all(not p.startswith("/") for p in paths)


def test_a_papers_bytes_are_covered_by_the_task_file_it_is_inlined_in(
    documents: dict[str, env_mod.Envelope],
) -> None:
    """No file entry is a paper: a paper has no file. Its hash lives in ``episodes``."""
    for task in payload_of(documents, "runnable-tasks")["tasks"]:
        assert {f["role"] for f in task["files"]} <= set(rt_mod.FILE_ROLES)
        assert "paper" not in {f["role"] for f in task["files"]}


def test_every_listed_file_hash_matches_the_file_on_disk(
    documents: dict[str, env_mod.Envelope],
) -> None:
    from scientific_claim_verifier.artifacts import hashing

    for task in payload_of(documents, "runnable-tasks")["tasks"]:
        for entry in task["files"]:
            assert hashing.hash_file(REPO_ROOT / entry["path"]) == entry["content_hash"]


def test_the_instruction_is_deterministic_and_names_the_claim() -> None:
    task = loader.load_task(TASKS_DIR / "table_claims" / "contradicted_f1.yaml", REPO_ROOT)
    first = rt_mod.instruction_for(task)
    assert first == rt_mod.instruction_for(task)
    assert "c_contradicted_f1" in first
    assert "Do not fetch anything from the network" in first


# ---------------------------------------------------------------------------
# The trace contract, checked against a real trace
# ---------------------------------------------------------------------------


def test_the_declared_trace_contract_holds_for_a_trace_this_repo_wrote(
    documents: dict[str, env_mod.Envelope], run_dir: Path
) -> None:
    contract = payload_of(documents, "runnable-tasks")["trace"]
    assert contract["media_type"] == "application/x-ndjson"
    assert contract["schema_version"] == SCHEMA_VERSION
    assert contract["event_kinds"] == list(SCORING_EVENT_KINDS)

    path = run_dir / "contradicted_f1.trace.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()

    # "one JSON object per line", "keys are sorted within every line"
    events = []
    for line in lines:
        event = json.loads(line)
        assert isinstance(event, dict)
        assert line == json.dumps(event, sort_keys=True, ensure_ascii=False)
        events.append(event)

    # "contiguous seq, starting at 0", "every kind is one of event_kinds"
    assert [event["seq"] for event in events] == list(range(len(events)))
    assert {event["kind"] for event in events} <= set(contract["event_kinds"])
    assert events == read_trace(path)


def test_the_trace_contract_names_every_event_kind_the_pipeline_emits(run_dir: Path) -> None:
    declared = set(rt_mod.trace_contract().event_kinds)
    emitted = {
        event["kind"]
        for trace in sorted(run_dir.glob("*.trace.jsonl"))
        for event in read_trace(trace)
    }
    assert emitted <= declared
    assert emitted, "the run wrote no events"


# ---------------------------------------------------------------------------
# evidence-records — BioScientist OS
# ---------------------------------------------------------------------------


def test_an_evidence_record_keeps_the_five_audit_channels_apart(
    documents: dict[str, env_mod.Envelope],
) -> None:
    record = payload_of(documents, "evidence-records")["records"][0]
    assert {"claim", "evidence", "checks", "verdict", "unverifiable"} <= set(record)
    assert set(record["evidence"]) == {"supporting_text", "artifact_links"}


def test_a_record_exists_for_every_claim_in_the_run(
    documents: dict[str, env_mod.Envelope],
) -> None:
    records = payload_of(documents, "evidence-records")["records"]
    assert len(records) == len(SUITE_TASK_IDS)
    assert [r["provenance"]["task_id"] for r in records] == list(SUITE_TASK_IDS)


def test_a_record_never_carries_a_checks_free_form_inputs_bag(
    documents: dict[str, env_mod.Envelope],
) -> None:
    """``code_execution`` records stdout in ``inputs``. An evidence store must not hold it."""
    for record in payload_of(documents, "evidence-records")["records"]:
        for check in record["checks"]:
            assert "inputs" not in check
            assert "stdout" not in check
    text = json.dumps(payload_of(documents, "evidence-records"))
    assert "accuracy=0.80" not in text


def test_a_record_keeps_the_named_rule_behind_each_verdict_field(
    documents: dict[str, env_mod.Envelope],
) -> None:
    record = next(
        r
        for r in payload_of(documents, "evidence-records")["records"]
        if r["provenance"]["task_id"] == "contradicted_f1"
    )
    fields = [rule["field"] for rule in record["rules"]]
    assert fields == list(ev_mod.RULE_FIELDS)
    support = record["rules"][0]
    assert support["rule"] and support["because"] and support["check_ids"]


def test_the_contradicted_fixture_exports_a_passage_that_asserts_and_a_table_that_refutes(
    documents: dict[str, env_mod.Envelope],
) -> None:
    """The fixture that exists to prove the channels must not merge. They do not."""
    record = next(
        r
        for r in payload_of(documents, "evidence-records")["records"]
        if r["provenance"]["task_id"] == "contradicted_f1"
    )
    signals = {
        check["check_type"]: (check["status"], check["signal"]) for check in record["checks"]
    }
    assert signals["evidence_presence"] == ("pass", "supports")
    assert signals["table_value"] == ("fail", "refutes")
    assert record["verdict"]["support_label"] == "contradicted"
    assert record["evidence"]["supporting_text"][0]["quote"]


def test_a_record_names_the_trace_it_came_from_by_filename(
    documents: dict[str, env_mod.Envelope],
) -> None:
    for record in payload_of(documents, "evidence-records")["records"]:
        provenance = record["provenance"]
        assert provenance["trace"] == f"{provenance['task_id']}.trace.jsonl"
        assert provenance["trace_schema_version"] == SCHEMA_VERSION


def test_the_undecided_claim_exports_its_limitations_rather_than_a_contradiction(
    documents: dict[str, env_mod.Envelope],
) -> None:
    record = next(
        r
        for r in payload_of(documents, "evidence-records")["records"]
        if r["provenance"]["task_id"] == "synthetic_data_passage"
    )
    assert record["verdict"]["support_label"] == "unverifiable_from_artifacts"
    assert record["verdict"]["confidence"] == 0.0
    assert record["unverifiable"]
    assert "contradicted" not in json.dumps(record["verdict"])


# ---------------------------------------------------------------------------
# benchmark — BioAgentBench
# ---------------------------------------------------------------------------


def test_the_benchmark_declares_wrong_verdicts_as_its_primary_metric(
    documents: dict[str, env_mod.Envelope],
) -> None:
    scoring = payload_of(documents, "benchmark")["scoring"]
    assert scoring["primary_metric"] == "wrong_verdicts"
    assert scoring["primary_metric_direction"] == "lower_is_better"
    assert scoring["secondary_metric"] == "conservative_misses"
    assert scoring["protocol"] == "exact_match_per_field"
    assert scoring["outcomes"] == [MATCH, CONSERVATIVE_MISS, WRONG_VERDICT]
    assert "Do not sum them" in scoring["notes"]


def test_the_committed_fixtures_export_zero_wrong_verdicts_and_one_conservative_miss(
    documents: dict[str, env_mod.Envelope],
) -> None:
    records = payload_of(documents, "benchmark")["records"]
    buckets = [record["outcome"] for record in records]
    assert buckets.count(WRONG_VERDICT) == 0
    assert buckets.count(CONSERVATIVE_MISS) == 1
    miss = next(r for r in records if r["outcome"] == CONSERVATIVE_MISS)
    assert miss["task_id"] == "synthetic_data_passage"


def test_the_exported_bucket_is_the_one_the_suite_gate_uses() -> None:
    """Not re-implemented: same ``TaskOutcome``, so the export and the gate cannot differ."""
    gold = Verdict(
        support_label=SupportLabel.SUPPORTED,
        reproduction_status=ReproductionStatus.NOT_APPLICABLE,
        failure_mode=FailureMode.NONE,
    )
    shy = Verdict(
        support_label=SupportLabel.UNVERIFIABLE_FROM_ARTIFACTS,
        reproduction_status=ReproductionStatus.NOT_APPLICABLE,
        failure_mode=FailureMode.NONE,
    )
    wrong = Verdict(
        support_label=SupportLabel.CONTRADICTED,
        reproduction_status=ReproductionStatus.NOT_APPLICABLE,
        failure_mode=FailureMode.NONE,
    )
    assert bench_mod.bucket(bench_mod.outcome_of(gold, gold, "t", "c")) == MATCH
    assert bench_mod.bucket(bench_mod.outcome_of(shy, gold, "t", "c")) == CONSERVATIVE_MISS
    assert bench_mod.bucket(bench_mod.outcome_of(wrong, gold, "t", "c")) == WRONG_VERDICT


def test_the_benchmark_carries_the_suites_own_gate_verbatim(
    documents: dict[str, env_mod.Envelope], run_dir: Path
) -> None:
    payload = payload_of(documents, "benchmark")
    recorded = json.loads((run_dir / "summary.json").read_text())["gate"]
    assert payload["gate"] == {
        "ok": recorded["ok"],
        "applicable": recorded["applicable"],
        "problems": recorded["problems"],
    }
    assert payload["suite"]["suite_id"] == "smoke_suite"
    assert payload["suite"]["n_tasks"] == 11
    assert payload["suite"]["scripts_executed"] is True


def test_every_benchmark_record_agrees_with_its_trace(
    documents: dict[str, env_mod.Envelope], run_dir: Path
) -> None:
    from scientific_claim_verifier.reports.reader import read_report

    for record in payload_of(documents, "benchmark")["records"]:
        report = read_report(run_dir / record["trace"])
        assert record["predicted"]["support_label"] == report.result.support_label.value
        assert record["claim_id"] == report.result.claim_id
        counts = record["check_counts"]
        assert sum(counts.values()) == len(report.result.computed_checks)
        assert sorted(counts) == sorted(status.value for status in CheckStatus)


def test_a_run_whose_summary_and_traces_disagree_is_refused_not_scored(
    run_dir: Path, tmp_path: Path
) -> None:
    doctored = tmp_path / "doctored"
    shutil.copytree(run_dir, doctored)
    summary = doctored / "summary.json"
    document = json.loads(summary.read_text())
    document["summary"]["tasks"][1]["predicted"]["support_label"] = "supported"
    summary.write_text(json.dumps(document), encoding="utf-8")

    ctx = ExportContext(repo_root=REPO_ROOT, run_dir=doctored, tasks_dir=TASKS_DIR)
    with pytest.raises(I.IntegrationError, match="disagree about"):
        I.export_document("benchmark", ctx)


def test_a_run_with_no_gold_is_refused_with_the_command_that_makes_one(
    run_dir: Path, tmp_path: Path
) -> None:
    traces_only = tmp_path / "traces-only"
    traces_only.mkdir()
    for trace in run_dir.glob("*.trace.jsonl"):
        shutil.copy(trace, traces_only)

    ctx = ExportContext(repo_root=REPO_ROOT, run_dir=traces_only, tasks_dir=TASKS_DIR)
    for name in ("benchmark", "metrics", "episodes"):
        with pytest.raises(I.IntegrationError, match="run-suite"):
            I.export_document(name, ctx)

    # ...but a format that needs only traces still works on the same directory.
    assert I.export_document("evidence-records", ctx).payload["records"]


def test_an_empty_or_missing_run_directory_is_named(tmp_path: Path) -> None:
    with pytest.raises(I.IntegrationError, match="no such run directory"):
        run_mod.load_run(tmp_path / "nope")
    with pytest.raises(I.IntegrationError, match="no .*trace"):
        run_mod.load_run(tmp_path)


# ---------------------------------------------------------------------------
# metrics — LLM regression / observability
# ---------------------------------------------------------------------------


def test_the_metric_key_space_covers_every_value_of_every_closed_vocabulary() -> None:
    names = set(metrics_mod.METRIC_NAMES)
    for prefix, vocabulary in (
        (metrics_mod.SUPPORT_PREFIX, SupportLabel),
        (metrics_mod.REPRODUCTION_PREFIX, ReproductionStatus),
        (metrics_mod.FAILURE_PREFIX, FailureMode),
    ):
        for value in vocabulary:
            assert f"{prefix}{value.value}" in names, f"no metric for {value!r}"
    for status in CheckStatus:
        assert f"checks_{status.value}" in names


def test_every_declared_metric_is_emitted_even_when_the_run_never_saw_it(
    documents: dict[str, env_mod.Envelope],
) -> None:
    metrics = payload_of(documents, "metrics")["metrics"]
    assert [metric["name"] for metric in metrics] == list(metrics_mod.METRIC_NAMES)
    unseen = next(m for m in metrics if m["name"] == "support_not_checked")
    assert unseen["value"] == 0.0


def test_the_labels_are_the_same_keys_in_every_run(
    documents: dict[str, env_mod.Envelope],
) -> None:
    labels = payload_of(documents, "metrics")["labels"]
    assert tuple(sorted(labels)) == metrics_mod.LABEL_NAMES
    assert labels["run"] == "smoke_suite"
    assert labels["suite_id"] == "smoke_suite"
    assert labels["scripts_executed"] == "true"
    assert all(isinstance(value, str) for value in labels.values())


def test_only_the_metrics_with_a_good_direction_declare_one(
    documents: dict[str, env_mod.Envelope],
) -> None:
    directions = {m["name"]: m["direction"] for m in payload_of(documents, "metrics")["metrics"]}
    assert directions["wrong_verdicts"] == metrics_mod.LOWER_IS_BETTER
    assert directions["conservative_misses"] == metrics_mod.LOWER_IS_BETTER
    assert directions["checks_error"] == metrics_mod.LOWER_IS_BETTER
    assert directions["gold_support_agreement"] == metrics_mod.HIGHER_IS_BETTER
    # A suite of contradicted claims *should* produce failing checks.
    assert directions["checks_fail"] == metrics_mod.NEUTRAL
    assert directions["support_contradicted"] == metrics_mod.NEUTRAL


def test_the_committed_run_measures_what_the_suite_reports(
    documents: dict[str, env_mod.Envelope],
) -> None:
    values = {m["name"]: m["value"] for m in payload_of(documents, "metrics")["metrics"]}
    assert values["tasks"] == 11
    assert values["wrong_verdicts"] == 0
    assert values["conservative_misses"] == 1
    assert values["gold_support_agreement"] == 10
    assert values["gold_reproduction_agreement"] == 11
    assert values["checks_total"] == sum(
        values[f"checks_{status.value}"] for status in CheckStatus
    )


def test_compare_flags_a_regression_only_where_a_direction_says_so(
    documents: dict[str, env_mod.Envelope],
) -> None:
    baseline = metrics_mod.payload_of(documents["metrics"])
    candidate = metrics_mod.Payload.model_validate(payload_of(documents, "metrics"))
    assert metrics_mod.regressions(metrics_mod.compare(baseline, baseline)) == ()

    for metric in candidate.metrics:
        if metric.name == "wrong_verdicts":
            metric.value = 2.0
        if metric.name == "checks_fail":
            metric.value += 5.0

    deltas = {d.name: d for d in metrics_mod.compare(baseline, candidate)}
    assert deltas["wrong_verdicts"].regression and deltas["wrong_verdicts"].delta == 2.0
    assert deltas["checks_fail"].changed and not deltas["checks_fail"].regression
    assert [d.name for d in metrics_mod.regressions(tuple(deltas.values()))] == ["wrong_verdicts"]


def test_a_conservative_miss_turning_into_a_wrong_verdict_reads_as_a_regression(
    documents: dict[str, env_mod.Envelope],
) -> None:
    """The scenario the whole project is arranged to catch, seen through the metrics."""
    baseline = metrics_mod.payload_of(documents["metrics"])
    candidate = metrics_mod.Payload.model_validate(payload_of(documents, "metrics"))
    for metric in candidate.metrics:
        if metric.name == "conservative_misses":
            metric.value = 0.0
        if metric.name == "wrong_verdicts":
            metric.value = 1.0
        if metric.name == "gold_support_agreement":
            metric.value = 10.0  # unchanged: accuracy would call this a wash

    regressed = {d.name for d in metrics_mod.regressions(metrics_mod.compare(baseline, candidate))}
    assert regressed == {"wrong_verdicts"}


def test_compare_refuses_two_documents_that_measure_different_things(
    documents: dict[str, env_mod.Envelope],
) -> None:
    baseline = metrics_mod.payload_of(documents["metrics"])
    candidate = metrics_mod.Payload.model_validate(payload_of(documents, "metrics"))
    candidate.metrics.pop()
    with pytest.raises(I.IntegrationError, match="different metrics"):
        metrics_mod.compare(baseline, candidate)


def test_payload_of_refuses_an_envelope_of_another_format(
    documents: dict[str, env_mod.Envelope],
) -> None:
    with pytest.raises(I.IntegrationError, match="expected scv.metrics"):
        metrics_mod.payload_of(documents["benchmark"])


# ---------------------------------------------------------------------------
# episodes — agent-control-bench. The import direction.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def episodes_file(documents: dict[str, env_mod.Envelope], tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("exports") / "episodes.json"
    return env_mod.write(documents["episodes"], path)


def test_an_episode_pins_the_task_the_inputs_the_controls_and_the_verdict(
    documents: dict[str, env_mod.Envelope],
) -> None:
    episode = next(
        e
        for e in payload_of(documents, "episodes")["episodes"]
        if e["episode_id"] == "recompute_accuracy"
    )
    assert episode["task"]["path"] == "tasks/code_reproduction/recompute_accuracy.yaml"
    assert episode["task"]["content_hash"].startswith("sha256:")
    assert episode["controls"] == {
        "execute": True,
        "use_declared_source": True,
        "abs_tol": None,
        "rel_tol": None,
    }
    assert episode["recorded"]["reproduction_status"] == "reproduced"
    assert episode["trace_content_hash"].startswith("sha256:")

    kinds = {ref["kind"] for ref in episode["inputs"]}
    assert "code" in kinds and "paper" in kinds
    paper = next(ref for ref in episode["inputs"] if ref["kind"] == "paper")
    assert paper["path"] is None and paper["content_hash"].startswith("sha256:")


def test_exporting_episodes_refuses_to_misdescribe_how_the_run_was_invoked(
    run_dir: Path,
) -> None:
    """The one control an artifact records is checked, not assumed."""
    ctx = ExportContext(
        repo_root=REPO_ROOT,
        run_dir=run_dir,
        tasks_dir=TASKS_DIR,
        controls=Controls(execute=False),
    )
    with pytest.raises(I.IntegrationError, match="replays a different experiment"):
        I.export_document("episodes", ctx)


def test_load_episodes_refuses_a_document_that_is_not_episodes(
    documents: dict[str, env_mod.Envelope], tmp_path: Path
) -> None:
    path = env_mod.write(documents["benchmark"], tmp_path / "not-episodes.json")
    with pytest.raises(I.IntegrationError, match="expected format 'scv.episodes'"):
        ep_mod.load_episodes(path)


def test_every_committed_fixture_replays_to_the_verdict_it_recorded(
    episodes_file: Path,
) -> None:
    """The loop closes: export → replay → same verdict, and the same trace bytes."""
    episodes = ep_mod.load_episodes(episodes_file)
    assert [e.episode_id for e in episodes] == list(SUITE_TASK_IDS)

    outcomes = ep_mod.replay(episodes, repo_root=REPO_ROOT)
    assert all(outcome.status == ep_mod.REPRODUCED for outcome in outcomes)
    assert all(outcome.diffs == () for outcome in outcomes)
    assert all(outcome.trace_digest_matches for outcome in outcomes)
    assert ep_mod.gate(outcomes) and ep_mod.gate(outcomes, strict=True)


def test_a_changed_fixture_is_inputs_changed_and_never_drift(episodes_file: Path) -> None:
    """An edited CSV must not read as a code regression. It is the reason the two differ."""
    episodes = ep_mod.load_episodes(episodes_file)
    episode = next(e for e in episodes if e.episode_id == "dataset_mean")
    tampered = episode.model_copy(deep=True)
    tampered.inputs[-1].content_hash = "sha256:" + "0" * 64

    outcome = ep_mod.replay_episode(tampered, repo_root=REPO_ROOT)
    assert outcome.status == ep_mod.INPUTS_CHANGED
    assert not outcome.ok
    assert any("changed: recorded" in diff for diff in outcome.diffs)
    assert outcome.trace_digest_matches is None  # no re-run was attempted


def test_an_edited_task_file_is_inputs_changed(episodes_file: Path) -> None:
    episodes = ep_mod.load_episodes(episodes_file)
    tampered = episodes[0].model_copy(deep=True)
    tampered.task.content_hash = "sha256:" + "1" * 64

    outcome = ep_mod.replay_episode(tampered, repo_root=REPO_ROOT)
    assert outcome.status == ep_mod.INPUTS_CHANGED
    assert any("task file" in diff for diff in outcome.diffs)


def test_an_added_artifact_is_inputs_changed(episodes_file: Path) -> None:
    episodes = ep_mod.load_episodes(episodes_file)
    episode = next(e for e in episodes if e.episode_id == "dataset_mean")
    tampered = episode.model_copy(deep=True)
    dropped = tampered.inputs.pop()

    outcome = ep_mod.replay_episode(tampered, repo_root=REPO_ROOT)
    assert outcome.status == ep_mod.INPUTS_CHANGED
    assert any(dropped.artifact_id in diff and "added" in diff for diff in outcome.diffs)


def test_a_missing_task_is_missing_task_not_drift(episodes_file: Path) -> None:
    episodes = ep_mod.load_episodes(episodes_file)
    tampered = episodes[0].model_copy(deep=True)
    tampered.task.path = "tasks/ml_claims/deleted.yaml"

    outcome = ep_mod.replay_episode(tampered, repo_root=REPO_ROOT)
    assert outcome.status == ep_mod.MISSING_TASK
    assert outcome.diffs == ("task file not found: tasks/ml_claims/deleted.yaml",)


def test_a_doctored_verdict_is_drift_and_names_the_field(episodes_file: Path) -> None:
    episodes = ep_mod.load_episodes(episodes_file)
    episode = next(e for e in episodes if e.episode_id == "contradicted_f1")
    tampered = episode.model_copy(deep=True)
    tampered.recorded.support_label = SupportLabel.SUPPORTED

    outcome = ep_mod.replay_episode(tampered, repo_root=REPO_ROOT)
    assert outcome.status == ep_mod.DRIFTED
    assert outcome.diffs == ("support_label: recorded supported, replayed contradicted",)
    assert outcome.trace_digest_matches is True  # the run itself was unchanged
    assert not ep_mod.gate((outcome,))


def test_a_changed_trace_digest_alone_is_reported_but_gated_only_under_strict(
    episodes_file: Path,
) -> None:
    """A reworded rule changes a trace's bytes without changing its verdict."""
    episodes = ep_mod.load_episodes(episodes_file)
    episode = next(e for e in episodes if e.episode_id == "gc_content")
    tampered = episode.model_copy(deep=True)
    tampered.trace_content_hash = "sha256:" + "2" * 64

    outcome = ep_mod.replay_episode(tampered, repo_root=REPO_ROOT)
    assert outcome.status == ep_mod.REPRODUCED and outcome.ok
    assert outcome.trace_digest_matches is False
    assert ep_mod.gate((outcome,)) is True
    assert ep_mod.gate((outcome,), strict=True) is False


def test_the_replay_report_says_which_failure_it_saw(episodes_file: Path) -> None:
    episodes = ep_mod.load_episodes(episodes_file)
    outcomes = ep_mod.replay(episodes[:1], repo_root=REPO_ROOT)
    text = ep_mod.render_replay(outcomes)
    assert "Result          : PASS" in text
    assert "Reproduced      : 1/1" in text

    drifted = ep_mod.ReplayOutcome("x", ep_mod.DRIFTED, ("support_label: ...",), True)
    text = ep_mod.render_replay((drifted,))
    assert "Result          : FAIL" in text
    assert "Only `drifted` is a statement about the pipeline" in text


def test_replay_statuses_are_the_four_the_module_declares() -> None:
    assert ep_mod.REPLAY_STATUSES == ("reproduced", "drifted", "inputs_changed", "missing_task")


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------


def test_export_list_names_every_format_and_refuses_to_claim_compatibility(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert export_mod.main(["--list"]) == 0
    out = capsys.readouterr().out
    for name in ALL_FORMATS:
        assert name in out
    assert "No external schema was consulted" in out


def test_export_schema_prints_json_a_consumer_can_read(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert export_mod.main(["--format", "benchmark", "--schema"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["format"] == "scv.benchmark"
    assert schema["consumer"] == "BioAgentBench"


def test_export_without_a_format_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert export_mod.main([]) == 1
    assert "--format is required" in capsys.readouterr().err


def test_a_run_based_format_without_a_run_names_the_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in RUN_FORMATS:
        assert export_mod.main(["--format", name]) == 1
        assert "--run DIR" in capsys.readouterr().err


def test_export_writes_the_document_and_prints_where(
    run_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    out = tmp_path / "nested" / "benchmark.json"
    argv = ["export", "--format", "benchmark", "--run", str(run_dir), "--out", str(out)]
    assert cli.main(argv) == 0
    assert "wrote" in capsys.readouterr().out
    assert env_mod.read(out, expect=bench_mod.FORMAT, expect_version="1.0")


def test_export_prints_to_stdout_when_no_out_is_given(
    run_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    assert cli.main(["export", "--format", "metrics", "--run", str(run_dir)]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["format"] == "scv.metrics"


def test_replay_from_the_cli_gates_on_drift_and_can_be_told_not_to(
    episodes_file: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    assert cli.main(["replay", "--episodes", str(episodes_file)]) == 0
    assert "Result          : PASS" in capsys.readouterr().out

    document = json.loads(episodes_file.read_text())
    document["payload"]["episodes"][0]["recorded"]["support_label"] = "supported"
    doctored = episodes_file.parent / "doctored.json"
    doctored.write_text(json.dumps(document), encoding="utf-8")

    assert cli.main(["replay", "--episodes", str(doctored)]) == 1
    assert "Result          : FAIL" in capsys.readouterr().out
    assert cli.main(["replay", "--episodes", str(doctored), "--no-gate"]) == 0


def test_replay_json_reports_every_episode(
    episodes_file: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    assert cli.main(["replay", "--episodes", str(episodes_file), "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["ok"] is True
    assert len(document["episodes"]) == len(SUITE_TASK_IDS)
    assert {e["status"] for e in document["episodes"]} == {"reproduced"}


def test_replay_names_a_file_that_is_not_an_episodes_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert ep_mod.main(["--episodes", str(bad)]) == 1
    assert "not an export envelope" in capsys.readouterr().err


def test_the_cli_advertises_the_two_new_verbs() -> None:
    parser = cli.build_parser()
    assert parser.parse_args(["export", "--list"]).command == "export"
    assert parser.parse_args(["replay", "--episodes", "e.json"]).command == "replay"


# ---------------------------------------------------------------------------
# Documentation and the website cannot silently drift from the registry
# ---------------------------------------------------------------------------


def test_every_format_is_documented_where_a_consumer_would_look() -> None:
    doc = (REPO_ROOT / "docs" / "INTEGRATIONS.md").read_text(encoding="utf-8")
    page = (REPO_ROOT / "site" / "integrations.html").read_text(encoding="utf-8")
    for spec in I.REGISTRY.values():
        assert spec.format in doc, f"{spec.format} is undocumented"
        assert spec.format in page, f"{spec.format} is missing from the website"
        assert spec.consumer in doc


def test_the_docs_state_the_limitation_rather_than_claiming_compatibility() -> None:
    doc = (REPO_ROOT / "docs" / "INTEGRATIONS.md").read_text(encoding="utf-8")
    assert "No external schema was consulted" in doc
