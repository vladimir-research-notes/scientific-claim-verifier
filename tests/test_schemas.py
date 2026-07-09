"""Milestone 1 — core schema unit tests (CPU-only, offline).

These tests pin the closed vocabularies (so docs and code cannot drift), the
strictness contract (unknown fields rejected), the bundle-integrity invariants,
and the determinism of the JSONL trace serialization.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from scientific_claim_verifier import schemas as S

# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------


def test_schema_version_is_real() -> None:
    # The Milestone 0 stub used "0-stub"; M1 shipped "1.0"; M5 bumped to "1.1" when it
    # added CheckStatus.INCONCLUSIVE, and M7 to "1.2" for FailureMode.EVIDENCE_UNDECIDABLE
    # (both additive changes — every 1.0 document stays valid). M9 bumped to "1.3" for the
    # self-describing scoring trace: no model changed, but a 1.2 trace does not satisfy a
    # 1.3 reader, which is what the version string is for.
    assert S.SCHEMA_VERSION == "1.3"
    assert "stub" not in S.SCHEMA_VERSION


def test_check_status_distinguishes_cannot_decide_from_disagrees() -> None:
    # `inconclusive` exists so a transparent check that genuinely cannot tell never
    # has to masquerade as `fail`. See checks/consistency.py.
    assert {s.value for s in S.CheckStatus} == {
        "pass",
        "fail",
        "inconclusive",
        "error",
        "skipped",
    }
    assert not S.VerificationCheck(
        check_id="c.evidence_presence.1",
        check_type=S.CheckType.EVIDENCE_PRESENCE,
        claim_id="c",
        status=S.CheckStatus.INCONCLUSIVE,
    ).ok


def test_claim_type_values() -> None:
    assert {t.value for t in S.ClaimType} == {
        "descriptive_claim",
        "numeric_claim",
        "comparison_claim",
        "table_claim",
        "figure_claim",
        "dataset_claim",
        "code_reproduction_claim",
        "unsupported_or_contextual_claim",
    }


def test_support_label_values_match_site() -> None:
    assert {label.value for label in S.SupportLabel} == {
        "supported",
        "contradicted",
        "partially_supported",
        "underspecified",
        "unverifiable_from_artifacts",
        "not_checked",
    }


def test_reproduction_status_values_match_site() -> None:
    assert {s.value for s in S.ReproductionStatus} == {
        "reproduced",
        "approximately_reproduced",
        "failed_environment",
        "failed_missing_data",
        "failed_missing_code",
        "failed_numeric_mismatch",
        "not_applicable",
        "not_attempted",
    }


def test_comparison_operator_symbols() -> None:
    assert {op.value for op in S.ComparisonOperator} == {"=", ">", "<", ">=", "<=", "~"}


def test_failure_mode_has_none_sentinel() -> None:
    assert S.FailureMode.NONE.value == "none"
    # A representative real failure mode is present.
    assert "numeric_out_of_tolerance" in {m.value for m in S.FailureMode}


def test_str_enum_serializes_to_value() -> None:
    # str-enums must render as their string value in JSON, not "ClaimType.NUMERIC".
    claim = _numeric_claim()
    dumped = json.loads(claim.model_dump_json())
    assert dumped["claim_type"] == "numeric_claim"


# ---------------------------------------------------------------------------
# Construction, strictness, round-trip
# ---------------------------------------------------------------------------


def _numeric_claim() -> S.ScientificClaim:
    return S.ScientificClaim(
        claim_id="c1",
        claim_text="Accuracy is 78%.",
        claim_type=S.ClaimType.NUMERIC,
        metrics=["accuracy"],
        expected_value=78.0,
        comparison_operator=S.ComparisonOperator.EQ,
        units="%",
    )


def test_claim_round_trip_json() -> None:
    claim = _numeric_claim()
    restored = S.ScientificClaim.model_validate_json(claim.model_dump_json())
    assert restored == claim
    assert restored.comparison_operator is S.ComparisonOperator.EQ


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        S.ScientificClaim(
            claim_id="c1",
            claim_text="x",
            claim_type=S.ClaimType.NUMERIC,
            typo_field=1,  # type: ignore[call-arg]
        )


def test_empty_required_strings_rejected() -> None:
    with pytest.raises(ValidationError):
        S.ScientificClaim(claim_id="", claim_text="x", claim_type=S.ClaimType.NUMERIC)


def test_invalid_enum_value_rejected() -> None:
    with pytest.raises(ValidationError):
        S.ScientificClaim(
            claim_id="c1",
            claim_text="x",
            claim_type="not_a_real_type",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Artifact bundle: integrity and lookups
# ---------------------------------------------------------------------------


def _bundle() -> S.ArtifactBundle:
    return S.ArtifactBundle(
        bundle_id="b1",
        task_id="t1",
        papers=[
            S.PaperArtifact(
                artifact_id="paper1",
                passages=[
                    S.Passage(passage_id="p1", text="Method A reaches 78% accuracy."),
                    S.Passage(passage_id="p2", text="Trained on synthetic data."),
                ],
            )
        ],
        tables=[
            S.Table(
                table_id="tbl1",
                columns=["method", "accuracy"],
                rows=[["A", 78.0], ["B", None]],
            )
        ],
        datasets=[S.DatasetArtifact(artifact_id="ds1", path="data/fixtures/datasets/d.csv")],
        code_files=[
            S.CodeArtifact(artifact_id="code1", path="eval.py", entrypoint="python eval.py")
        ],
    )


def test_bundle_lookups() -> None:
    bundle = _bundle()
    assert bundle.paper("paper1") is not None
    assert bundle.dataset("ds1") is not None
    assert bundle.code("code1") is not None
    assert bundle.table("tbl1") is not None
    assert bundle.paper("nope") is None
    assert bundle.figure("nope") is None
    assert bundle.paper("paper1").passage("p2").text == "Trained on synthetic data."
    assert bundle.paper("paper1").passage("missing") is None


def test_bundle_rejects_duplicate_artifact_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate artifact_id"):
        S.ArtifactBundle(
            bundle_id="b1",
            papers=[S.PaperArtifact(artifact_id="dup")],
            datasets=[S.DatasetArtifact(artifact_id="dup")],
        )


def test_bundle_rejects_duplicate_passage_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate passage_id"):
        S.ArtifactBundle(
            bundle_id="b1",
            papers=[
                S.PaperArtifact(
                    artifact_id="paper1",
                    passages=[
                        S.Passage(passage_id="p1", text="one"),
                        S.Passage(passage_id="p1", text="two"),
                    ],
                )
            ],
        )


def test_bundle_rejects_duplicate_table_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate table_id"):
        S.ArtifactBundle(
            bundle_id="b1",
            tables=[S.Table(table_id="t"), S.Table(table_id="t")],
        )


def test_table_cell_types_preserved() -> None:
    # int stays int, float stays float, None stays None through a JSON round-trip.
    table = S.Table(
        table_id="t", columns=["n", "x", "label"], rows=[[120, 3.4, "ok"], [0, 0.0, None]]
    )
    restored = S.Table.model_validate_json(table.model_dump_json())
    assert restored.rows[0] == [120, 3.4, "ok"]
    assert isinstance(restored.rows[0][0], int)
    assert isinstance(restored.rows[0][1], float)
    assert restored.rows[1][2] is None


# ---------------------------------------------------------------------------
# Evidence links, checks, results
# ---------------------------------------------------------------------------


def test_evidence_link_score_bounds() -> None:
    S.EvidenceLink(kind=S.EvidenceKind.PASSAGE, target_id="p1", score=0.5)
    with pytest.raises(ValidationError):
        S.EvidenceLink(kind=S.EvidenceKind.PASSAGE, target_id="p1", score=1.5)


def test_verification_check_ok_property() -> None:
    passed = S.VerificationCheck(
        check_id="chk1",
        check_type=S.CheckType.NUMERIC_TOLERANCE,
        claim_id="c1",
        status=S.CheckStatus.PASS,
        computed_value=78.0,
        expected_value=78.0,
        tolerance=0.5,
        difference=0.0,
    )
    failed = passed.model_copy(update={"status": S.CheckStatus.FAIL})
    assert passed.ok is True
    assert failed.ok is False


def test_verification_result_defaults_and_confidence_bounds() -> None:
    result = S.VerificationResult(claim_id="c1", support_label=S.SupportLabel.SUPPORTED)
    # Sensible defaults so a descriptive claim needs no explicit repro fields.
    assert result.reproduction_status is S.ReproductionStatus.NOT_APPLICABLE
    assert result.failure_mode is S.FailureMode.NONE
    with pytest.raises(ValidationError):
        S.VerificationResult(
            claim_id="c1", support_label=S.SupportLabel.SUPPORTED, confidence=2.0
        )


# ---------------------------------------------------------------------------
# RunTrace: event stream + deterministic JSONL
# ---------------------------------------------------------------------------


def test_run_trace_add_event_increments_seq() -> None:
    trace = S.RunTrace(run_id="run1")
    e0 = trace.add_event("load_artifacts", "loaded bundle", bundle_id="b1")
    e1 = trace.add_event("extract_claim", n=1)
    assert (e0.seq, e1.seq) == (0, 1)
    assert e0.data == {"bundle_id": "b1"}
    assert trace.schema_version == S.SCHEMA_VERSION


def test_run_trace_to_jsonl_is_deterministic_and_parseable() -> None:
    trace = S.RunTrace(run_id="run1")
    trace.add_event("b_second", z=1, a=2)
    trace.add_event("a_first", m=3)

    first = trace.to_jsonl()
    second = trace.to_jsonl()
    assert first == second  # no wall-clock / RNG in the output

    lines = first.splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    # Event order is insertion order (seq), not sorted by kind.
    assert [p["kind"] for p in parsed] == ["b_second", "a_first"]
    # Keys within each line are sorted for byte-stability.
    assert list(parsed[0].keys()) == sorted(parsed[0].keys())


def test_run_trace_created_at_is_optional_and_not_autofilled() -> None:
    # Determinism: no timestamp is invented at construction time.
    assert S.RunTrace(run_id="run1").created_at is None


def test_run_trace_full_round_trip() -> None:
    trace = S.RunTrace(
        run_id="run1",
        task_id="t1",
        bundle_id="b1",
        claim=_numeric_claim(),
        result=S.VerificationResult(claim_id="c1", support_label=S.SupportLabel.SUPPORTED),
    )
    trace.add_event("score", label="supported")
    restored = S.RunTrace.model_validate_json(trace.model_dump_json())
    assert restored == trace


# ---------------------------------------------------------------------------
# BenchmarkSuite
# ---------------------------------------------------------------------------


def test_benchmark_suite_size() -> None:
    suite = S.BenchmarkSuite(suite_id="smoke", task_ids=["t1", "t2", "t3"])
    assert suite.size == 3
    assert S.BenchmarkSuite(suite_id="empty").size == 0


def test_all_exports_are_importable() -> None:
    for name in S.__all__:
        assert hasattr(S, name), name
