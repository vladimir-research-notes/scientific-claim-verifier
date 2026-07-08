"""Milestone 2 — fixture task loading and validation tests (CPU-only, offline).

Exercises the M1 schema against the *real* committed task fixtures (they must all
validate), the input/gold separation, deterministic content hashing, and the
validator's ability to catch broken tasks (missing files, dangling evidence, bad
CSV shape, path escapes, unknown fields).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from scientific_claim_verifier import cli
from scientific_claim_verifier import schemas as S
from scientific_claim_verifier.artifacts import loader, validation

REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = REPO_ROOT / "tasks"


# ---------------------------------------------------------------------------
# The committed fixtures: all valid, covering every required family
# ---------------------------------------------------------------------------


def test_all_committed_fixtures_validate() -> None:
    report = validation.validate_tasks(TASKS_DIR, REPO_ROOT)
    assert report.results, "expected committed task fixtures"
    # Surface any error text in the assertion message for easy debugging.
    failures = {str(r.path): r.errors for r in report.results if not r.ok}
    assert report.ok, f"fixtures failed validation: {failures}"
    assert report.n_failed == 0


def test_required_task_families_present() -> None:
    files = loader.discover_task_files(TASKS_DIR)
    tasks = [loader.load_task(f, REPO_ROOT) for f in files]
    families = {t.spec.family for t in tasks}
    claim_types = {t.spec.claim.claim_type for t in tasks}
    labels = {t.spec.expected.support_label for t in tasks}

    # The five families named in docs/PLAN.md §9 (+ a bioinformatics toy).
    assert {
        "numeric_table",
        "dataset_statistic",
        "evidence_passage",
        "code_reproduction",
        "underspecified",
    } <= families
    assert S.ClaimType.CODE_REPRODUCTION in claim_types
    assert S.ClaimType.DATASET in claim_types
    assert S.SupportLabel.UNDERSPECIFIED in labels


def test_at_least_one_dataset_and_one_code_fixture() -> None:
    files = loader.discover_task_files(TASKS_DIR)
    tasks = [loader.load_task(f, REPO_ROOT) for f in files]
    assert any(t.bundle.datasets for t in tasks)
    assert any(t.bundle.code_files for t in tasks)


# ---------------------------------------------------------------------------
# Loading: hashing + input/gold separation
# ---------------------------------------------------------------------------


def test_load_task_populates_content_hashes() -> None:
    task = loader.load_task(TASKS_DIR / "statistical_claims" / "dataset_mean.yaml", REPO_ROOT)
    ds = task.bundle.dataset("ds_measurements")
    assert ds is not None and ds.content_hash is not None
    assert ds.content_hash.startswith("sha256:")
    # Papers are inlined; they get a hash too, over their passage content.
    paper = task.bundle.paper("paper_measurements")
    assert paper is not None and paper.content_hash is not None
    assert task.content_hashes["ds_measurements"] == ds.content_hash


def test_load_task_hashes_are_deterministic() -> None:
    path = TASKS_DIR / "code_reproduction" / "recompute_accuracy.yaml"
    a = loader.load_task(path, REPO_ROOT)
    b = loader.load_task(path, REPO_ROOT)
    assert a.content_hashes == b.content_hashes


def test_input_claim_carries_no_gold_fields() -> None:
    # The input claim is the pipeline's input; the extraction targets live in
    # expected.claim and must NOT leak into the input.
    task = loader.load_task(TASKS_DIR / "table_claims" / "accuracy_improvement.yaml", REPO_ROOT)
    claim = task.input_claim
    assert claim.claim_id == "c_accuracy_improvement"
    assert claim.claim_type is S.ClaimType.COMPARISON
    assert claim.expected_value is None
    assert claim.baseline_value is None
    assert claim.metrics == []
    # The gold values, by contrast, are populated.
    gold = task.spec.expected.claim
    assert gold.expected_value == 78.0
    assert gold.baseline_value == 72.0
    assert gold.comparison_operator is S.ComparisonOperator.GT


def test_repo_root_autodetected_from_task_path() -> None:
    # load_task with no repo_root walks up to the pyproject.toml marker.
    task = loader.load_task(TASKS_DIR / "bioinformatics_claims" / "gc_content.yaml")
    assert task.bundle.code("code_gc").content_hash is not None


# ---------------------------------------------------------------------------
# CSV shape helper
# ---------------------------------------------------------------------------


def test_read_csv_shape() -> None:
    columns, n_rows = loader.read_csv_shape(
        REPO_ROOT / "data" / "fixtures" / "datasets" / "measurements.csv"
    )
    assert columns == ["sample_id", "value"]
    assert n_rows == 12


# ---------------------------------------------------------------------------
# Validator catches broken tasks
# ---------------------------------------------------------------------------


def _base_task() -> dict[str, Any]:
    """A minimal task that validates cleanly; broken cases mutate a copy."""
    return {
        "task_id": "tmp_task",
        "family": "test",
        "title": "temporary task",
        "claim": {
            "claim_id": "c",
            "claim_text": "The set has a mean of 3.4.",
            "claim_type": "dataset_claim",
            "source_document_id": "paper",
            "source_passage": "p1",
        },
        "artifacts": {
            "bundle_id": "b",
            "papers": [
                {"artifact_id": "paper", "passages": [{"passage_id": "p1", "text": "t"}]}
            ],
            "datasets": [
                {
                    "artifact_id": "ds",
                    "path": "data/fixtures/datasets/measurements.csv",
                    "columns": ["sample_id", "value"],
                    "n_rows": 12,
                }
            ],
        },
        "expected": {
            "support_label": "supported",
            "reproduction_status": "reproduced",
            "claim": {"expected_value": 3.4},
            "evidence": [{"kind": "dataset", "target_id": "ds"}],
        },
    }


def _write_and_validate(tmp_path: Path, data: dict[str, Any], name: str = "tmp_task.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return validation.validate_task_file(path, REPO_ROOT)


def test_base_task_is_valid(tmp_path) -> None:
    res = _write_and_validate(tmp_path, _base_task())
    assert res.ok, res.errors
    assert res.warnings == []


def test_missing_fixture_file_is_error(tmp_path) -> None:
    data = _base_task()
    data["artifacts"]["datasets"][0]["path"] = "data/fixtures/datasets/nope.csv"
    res = _write_and_validate(tmp_path, data)
    assert not res.ok
    assert any("not found" in e for e in res.errors)


def test_declared_csv_shape_mismatch_is_error(tmp_path) -> None:
    data = _base_task()
    data["artifacts"]["datasets"][0]["n_rows"] = 99
    res = _write_and_validate(tmp_path, data)
    assert not res.ok
    assert any("n_rows" in e for e in res.errors)


def test_dangling_evidence_link_is_error(tmp_path) -> None:
    data = _base_task()
    data["expected"]["evidence"] = [{"kind": "passage", "target_id": "ghost"}]
    res = _write_and_validate(tmp_path, data)
    assert not res.ok
    assert any("does not resolve" in e for e in res.errors)


def test_unresolved_source_passage_is_error(tmp_path) -> None:
    data = _base_task()
    data["claim"]["source_passage"] = "ghost"
    res = _write_and_validate(tmp_path, data)
    assert not res.ok
    assert any("source_passage" in e for e in res.errors)


def test_absolute_fixture_path_is_error(tmp_path) -> None:
    data = _base_task()
    data["artifacts"]["datasets"][0]["path"] = "/etc/hosts"
    res = _write_and_validate(tmp_path, data)
    assert not res.ok
    assert any("absolute" in e for e in res.errors)


def test_path_escape_is_error(tmp_path) -> None:
    data = _base_task()
    data["artifacts"]["datasets"][0]["path"] = "../../../../etc/passwd"
    res = _write_and_validate(tmp_path, data)
    assert not res.ok
    assert any("escapes" in e for e in res.errors)


def test_unknown_field_is_schema_error(tmp_path) -> None:
    data = _base_task()
    data["bogus_top_level"] = 1
    res = _write_and_validate(tmp_path, data)
    assert not res.ok
    assert any(e.startswith("schema:") for e in res.errors)


def test_duplicate_artifact_id_is_schema_error(tmp_path) -> None:
    # The M1 ArtifactBundle integrity validator must fire through the loader too.
    data = _base_task()
    data["artifacts"]["code_files"] = [{"artifact_id": "ds", "path": "x.py"}]
    res = _write_and_validate(tmp_path, data)
    assert not res.ok
    assert any("duplicate artifact_id" in e for e in res.errors)


def test_filename_task_id_mismatch_is_warning(tmp_path) -> None:
    res = _write_and_validate(tmp_path, _base_task(), name="different_name.yaml")
    assert res.ok  # a warning, not an error
    assert any("does not match task_id" in w for w in res.warnings)


def test_fixture_outside_data_dir_is_warning(tmp_path) -> None:
    data = _base_task()
    # An existing, in-tree file that is not under data/fixtures/.
    data["artifacts"]["datasets"][0] = {"artifact_id": "ds", "path": "pyproject.toml"}
    res = _write_and_validate(tmp_path, data)
    assert res.ok
    assert any("not under" in w for w in res.warnings)


def test_reproducible_claim_without_expected_value_warns(tmp_path) -> None:
    data = _base_task()
    data["claim"]["claim_type"] = "code_reproduction_claim"
    data["expected"]["claim"] = {}
    data["artifacts"].pop("expected_outputs", None)
    res = _write_and_validate(tmp_path, data)
    assert res.ok
    assert any("no expected value" in w for w in res.warnings)


# ---------------------------------------------------------------------------
# CLI / script entry points
# ---------------------------------------------------------------------------


def test_cli_validate_fixtures_returns_zero(capsys) -> None:
    code = cli.main(["validate-fixtures", str(TASKS_DIR)])
    out = capsys.readouterr().out
    assert code == 0
    assert "VALID" in out


def test_validation_run_reports_invalid_on_broken_dir(tmp_path, capsys) -> None:
    (tmp_path / "broken.yaml").write_text("task_id: x\nnot: valid\n", encoding="utf-8")
    code = validation.run([str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "INVALID" in out


def test_validate_task_file_does_not_mutate_input_dict(tmp_path) -> None:
    # Guard against the loader hashing step mutating a caller-shared structure.
    data = _base_task()
    snapshot = copy.deepcopy(data)
    _write_and_validate(tmp_path, data)
    assert data == snapshot
