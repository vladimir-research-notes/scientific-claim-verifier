"""Milestone 5 — the deterministic verification checks.

Unit tests per check on synthetic bundles, then integration over every committed
fixture. The pinned behaviours are the ones the design decisions rest on:

- tolerance is the claim's *reported precision*, not a constant;
- a column check passes when the value is present, and records the ambiguity;
- a column check fails when the value is absent, and records the nearest cell;
- an evidence check that cannot decide says ``inconclusive``, never ``fail``;
- a script that will not run is ``error``, never ``fail``.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scientific_claim_verifier import checks, cli
from scientific_claim_verifier.artifacts import loader
from scientific_claim_verifier.checks import (
    code_execution,
    consistency,
    statistical,
    table_recompute,
    verification,
)
from scientific_claim_verifier.evidence import locators
from scientific_claim_verifier.sandbox import runner as runner_module
from scientific_claim_verifier.schemas import (
    ArtifactBundle,
    CheckStatus,
    CheckType,
    ClaimType,
    CodeArtifact,
    ComparisonOperator,
    DatasetArtifact,
    EvidenceKind,
    EvidenceLink,
    PaperArtifact,
    Passage,
    ScientificClaim,
    Table,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = REPO_ROOT / "tasks"

ST = CheckStatus
CT = CheckType


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def make_claim(text: str, claim_type: ClaimType = ClaimType.NUMERIC, **fields) -> ScientificClaim:
    return ScientificClaim(
        claim_id="c_test", claim_text=text, claim_type=claim_type, **fields
    )


def table_link(table_id: str, locator: str | None = None) -> EvidenceLink:
    return EvidenceLink(kind=EvidenceKind.TABLE, target_id=table_id, locator=locator)


ACCURACY_TABLE = Table(
    table_id="t",
    columns=["method", "accuracy"],
    rows=[["baseline", 72.0], ["A", 78.0]],
)


def check_table(claim: ScientificClaim, table: Table, locator: str | None = None):
    """Run the table check against ``table`` with a link carrying ``locator``."""
    return table_recompute.table_value_check(
        "id", claim, table, table_link(table.table_id, locator)
    )


def load_fixture(*parts: str) -> loader.LoadedTask:
    return loader.load_task(TASKS_DIR.joinpath(*parts), REPO_ROOT)


# ---------------------------------------------------------------------------
# Tolerance: derived from how the claim was written
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("78", 0), ("78.0", 1), ("0.80", 2), ("90%", 0), ("3.4", 1), ("-5", 0)],
)
def test_decimal_places_of_a_number_as_written(raw: str, expected: int) -> None:
    assert checks.decimal_places(raw) == expected


@pytest.mark.parametrize(
    ("text", "value", "abs_tol"),
    [
        ("a mean value of 3.4", 3.4, 0.05),
        ("an accuracy of 0.80", 0.8, 0.005),
        ("reaches 90% accuracy", 90.0, 0.5),
        ("from 72.0 to 78.0", 78.0, 0.05),
        ("exactly 12 samples", 12.0, 0.5),
    ],
)
def test_reported_precision_is_half_the_last_decimal_place(
    text: str, value: float, abs_tol: float
) -> None:
    # "3.4" asserts only that the quantity rounds to 3.4, so 0.05 is what the claim
    # actually says — not a magic constant chosen to make fixtures pass.
    tolerance = checks.reported_precision_tolerance(text, value)
    assert tolerance is not None
    assert tolerance.abs_tol == pytest.approx(abs_tol)


def test_reported_precision_is_none_when_the_value_is_not_in_the_text() -> None:
    assert checks.reported_precision_tolerance("the model is good", 3.4) is None


def test_resolve_tolerance_precedence() -> None:
    claim = make_claim("a mean value of 3.4")
    override = checks.Tolerance(abs_tol=9.0)
    assert checks.resolve_tolerance(claim, 3.4, override=override) is override
    assert checks.resolve_tolerance(claim, 3.4, exact=True) == checks.EXACT
    assert checks.resolve_tolerance(claim, 3.4).abs_tol == pytest.approx(0.05)
    # No number in the text to read a precision from -> float noise, not a guess.
    assert checks.resolve_tolerance(make_claim("no numbers"), 3.4) == checks.FLOAT_NOISE


def test_tolerance_threshold_takes_the_looser_of_absolute_and_relative() -> None:
    tolerance = checks.Tolerance(abs_tol=0.05, rel_tol=0.01)
    assert tolerance.threshold(1.0) == pytest.approx(0.05)
    assert tolerance.threshold(100.0) == pytest.approx(1.0)


def test_compare_records_signed_difference_and_the_applied_threshold() -> None:
    result = checks.compare(86.0, 91.0, checks.Tolerance(abs_tol=0.05))
    assert (result.difference, result.threshold, result.within) == (-5.0, 0.05, False)


def test_compare_rounds_float_noise_out_of_the_record() -> None:
    # 40.8 / 12 is 3.4000000000000004 in IEEE-754; the trace should read 3.4.
    assert checks.compare(40.8 / 12, 3.4, checks.EXACT).computed == 3.4


@pytest.mark.parametrize(
    ("operator", "observed", "reference", "holds"),
    [
        (ComparisonOperator.GT, 78.0, 72.0, True),
        (ComparisonOperator.GT, 72.0, 78.0, False),
        (ComparisonOperator.GT, 72.02, 72.0, False),  # gap below tolerance is not a gain
        (ComparisonOperator.LT, 72.0, 78.0, True),
        (ComparisonOperator.EQ, 72.02, 72.0, True),
        (ComparisonOperator.APPROX, 72.5, 72.0, False),
        (ComparisonOperator.GE, 72.0, 72.0, True),
        (ComparisonOperator.LE, 72.0, 72.0, True),
    ],
)
def test_operator_holds(
    operator: ComparisonOperator, observed: float, reference: float, holds: bool
) -> None:
    assert checks.operator_holds(operator, observed, reference, 0.05) is holds


def test_operator_holds_rejects_an_unknown_operator() -> None:
    with pytest.raises(ValueError, match="unhandled comparison operator"):
        checks.operator_holds("??", 1.0, 0.0, 0.0)  # type: ignore[arg-type]


def test_check_id_is_stable_and_readable() -> None:
    assert checks.check_id("c_x", CT.DATASET_STATISTIC, 2) == "c_x.dataset_statistic.2"


def test_truncate_marks_the_elision() -> None:
    assert checks.truncate("abc", 10) == "abc"
    clipped = checks.truncate("x" * 50, 10)
    assert clipped.startswith("x" * 10) and "truncated, 50 chars" in clipped


# ---------------------------------------------------------------------------
# Locators: one grammar, written by M4 and read by M5
# ---------------------------------------------------------------------------


def test_locator_round_trips_through_the_formatters() -> None:
    assert locators.parse(locators.table_cell("A", "accuracy")).row == "A"
    assert locators.parse(locators.table_cell("A", "accuracy")).col == "accuracy"
    assert locators.parse(locators.table_column("f1")).col == "f1"
    assert locators.parse(locators.dataset_column("value")).column == "value"
    assert locators.parse(locators.figure_series("accuracy")).series == "accuracy"
    assert locators.parse(locators.STDOUT).is_stdout


def test_locator_empty_and_unknown_keys() -> None:
    assert locators.parse(None).is_empty and locators.parse("").is_empty
    # Unknown keys are preserved, not rejected: a check that cannot read one declines.
    parsed = locators.parse("page=3,line=7")
    assert parsed.parts == {"page": "3", "line": "7"}
    assert parsed.row is None and parsed.col is None


def test_locator_tolerates_whitespace_and_blank_segments() -> None:
    assert locators.parse(" row=A , col=accuracy ,").parts == {"row": "A", "col": "accuracy"}


# ---------------------------------------------------------------------------
# Table value check
# ---------------------------------------------------------------------------


def test_column_index_matches_exactly_then_normalized() -> None:
    table = Table(table_id="t", columns=["Method", "F1 Score"], rows=[["A", 1.0]])
    assert table_recompute.column_index(table, "F1 Score") == 1
    assert table_recompute.column_index(table, "f1_score") == 1
    assert table_recompute.column_index(table, "auc") is None


def test_numeric_column_drops_non_numeric_cells_and_keys_unlabelled_rows() -> None:
    table = Table(table_id="t", columns=["a", "b"], rows=[[1.0, 2.0], [3.0, "n/a"]])
    # No all-string column, so no row label: values stay addressable by position.
    assert table_recompute.numeric_column(table, 1) == [("#0", 2.0)]


def test_cell_check_passes_and_names_the_claim_field_it_matched() -> None:
    claim = make_claim(
        "Method A improves accuracy from 72.0 to 78.0",
        ClaimType.COMPARISON,
        expected_value=78.0,
        baseline_value=72.0,
    )
    check = check_table(claim, ACCURACY_TABLE, "row=baseline,col=accuracy")
    assert check.status is ST.PASS
    assert check.computed_value == 72.0
    # The cell stands for the *baseline*, and the pairing is recorded, not implied.
    assert check.inputs["claim_field"] == "baseline_value"
    assert check.tolerance == pytest.approx(0.05)


def test_cell_check_fails_outside_the_reported_precision() -> None:
    claim = make_claim("accuracy of 78.0", expected_value=78.0)
    table = Table(table_id="t", columns=["method", "accuracy"], rows=[["A", 78.4]])
    check = check_table(claim, table, "row=A,col=accuracy")
    assert check.status is ST.FAIL
    assert check.difference == pytest.approx(0.4)


def test_column_check_passes_and_records_the_ambiguity_when_the_claim_names_no_row() -> None:
    claim = make_claim("The method reaches 90% accuracy.", expected_value=90.0)
    table = Table(table_id="t", columns=["split", "accuracy"], rows=[["dev", 90.0], ["test", 82.0]])
    check = check_table(claim, table, "col=accuracy")
    assert check.status is ST.PASS
    assert check.computed_value == 90.0
    # The signal M7 needs to say `underspecified` rather than `supported`.
    assert check.inputs["matching_rows"] == ["dev"]
    assert check.inputs["n_rows"] == 2
    assert check.inputs["row_named"] is False


def test_column_check_fails_and_records_the_nearest_cell_when_the_value_is_absent() -> None:
    claim = make_claim("an F1 score of 91.0", expected_value=91.0)
    table = Table(table_id="t", columns=["method", "f1"], rows=[["baseline", 84.0], ["B", 86.0]])
    check = check_table(claim, table, "col=f1")
    assert check.status is ST.FAIL
    assert check.computed_value == 86.0
    assert check.inputs["nearest_row"] == "B"
    assert check.inputs["matching_rows"] == []
    assert check.difference == pytest.approx(-5.0)


def test_table_check_skips_a_link_with_no_column_and_errors_on_an_unknown_one() -> None:
    claim = make_claim("accuracy of 78.0", expected_value=78.0)
    assert check_table(claim, ACCURACY_TABLE).status is ST.SKIPPED
    assert check_table(claim, ACCURACY_TABLE, "col=auc").status is ST.ERROR


def test_table_check_errors_on_an_unknown_row_or_a_non_numeric_cell() -> None:
    claim = make_claim("accuracy of 78.0", expected_value=78.0)
    assert check_table(claim, ACCURACY_TABLE, "row=Z,col=accuracy").status is ST.ERROR
    text_cell = Table(table_id="t", columns=["method", "accuracy"], rows=[["A", "n/a"]])
    assert check_table(claim, text_cell, "row=A,col=accuracy").status is ST.ERROR


def test_table_check_skips_a_claim_with_no_number() -> None:
    claim = make_claim("the method is good", ClaimType.DESCRIPTIVE)
    assert check_table(claim, ACCURACY_TABLE, "col=accuracy").status is ST.SKIPPED


# ---------------------------------------------------------------------------
# Dataset statistics
# ---------------------------------------------------------------------------


def test_statistics_are_computed_with_the_stdlib() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert statistical.compute_statistic("count", values) == 4.0
    assert statistical.compute_statistic("mean", values) == 2.5
    assert statistical.compute_statistic("median", values) == 2.5
    assert statistical.compute_statistic("sum", values) == 10.0
    assert statistical.compute_statistic("min", values) == 1.0
    assert statistical.compute_statistic("max", values) == 4.0
    # Both deviations are named, so no ddof convention is hidden.
    assert statistical.compute_statistic("std", values) == pytest.approx(1.118033988)
    assert statistical.compute_statistic("std_sample", values) == pytest.approx(1.290994449)


def test_compute_statistic_rejects_the_unknown_and_the_undefined() -> None:
    with pytest.raises(KeyError):
        statistical.compute_statistic("correlation", [1.0])
    with pytest.raises(ValueError, match="at least 2"):
        statistical.compute_statistic("std_sample", [1.0])


def test_primary_statistic_prefers_a_real_statistic_over_the_count() -> None:
    claim = make_claim("12 samples with a mean value of 3.4", metrics=["mean", "count"])
    assert statistical.primary_statistic(claim) == "mean"
    assert statistical.primary_statistic(make_claim("x", metrics=["count"])) == "count"
    assert statistical.primary_statistic(make_claim("x", metrics=["gc_content"])) is None


def test_count_condition_reads_the_extractor_notation() -> None:
    assert statistical.count_condition(make_claim("x", conditions=["n = 12"])) == 12
    assert statistical.count_condition(make_claim("x", conditions=["synthetic only"])) is None


def test_read_numeric_column_refuses_to_silently_drop_a_bad_row(tmp_path: Path) -> None:
    csv = tmp_path / "d.csv"
    csv.write_text("id,value\ns1,1.0\ns2,oops\n", encoding="utf-8")
    with pytest.raises(ValueError, match="row 2 of column 'value' is not numeric"):
        statistical.read_numeric_column(csv, "value")


def test_read_csv_column_rejects_a_missing_column(tmp_path: Path) -> None:
    csv = tmp_path / "d.csv"
    csv.write_text("id,value\ns1,1.0\n", encoding="utf-8")
    with pytest.raises(loader.TaskLoadError, match="not in CSV header"):
        loader.read_csv_column(csv, "nope")


def _measurements() -> DatasetArtifact:
    return DatasetArtifact(
        artifact_id="ds",
        path="data/fixtures/datasets/measurements.csv",
        columns=["sample_id", "value"],
    )


def _dataset_link(locator: str | None = "column=value") -> EvidenceLink:
    return EvidenceLink(kind=EvidenceKind.DATASET, target_id="ds", locator=locator)


def test_dataset_statistic_recomputes_the_mean_from_the_committed_csv() -> None:
    claim = make_claim("a mean value of 3.4", ClaimType.DATASET, expected_value=3.4)
    check = statistical.dataset_statistic_check(
        "id", claim, _measurements(), _dataset_link(), "mean", 3.4, REPO_ROOT
    )
    assert check.status is ST.PASS
    assert check.computed_value == 3.4  # 40.8 / 12, rounded out of float noise
    assert check.inputs["n_values"] == 12


def test_dataset_count_is_compared_exactly() -> None:
    claim = make_claim("12 samples", ClaimType.DATASET, expected_value=12.0)
    check = statistical.dataset_statistic_check(
        "id", claim, _measurements(), _dataset_link(), "count", 12.0, REPO_ROOT
    )
    assert check.status is ST.PASS
    assert check.tolerance == 0.0


def test_dataset_statistic_skips_when_the_linker_declined_to_name_a_column() -> None:
    # An ambiguous dataset is underspecification, not an error.
    claim = make_claim("a mean value of 3.4", ClaimType.DATASET, expected_value=3.4)
    check = statistical.dataset_statistic_check(
        "id", claim, _measurements(), _dataset_link(None), "mean", 3.4, REPO_ROOT
    )
    assert check.status is ST.SKIPPED


def test_dataset_statistic_records_the_value_when_the_claim_states_none() -> None:
    claim = make_claim("the mean is reported", ClaimType.DATASET)
    check = statistical.dataset_statistic_check(
        "id", claim, _measurements(), _dataset_link(), "mean", None, REPO_ROOT
    )
    assert check.status is ST.SKIPPED
    assert check.computed_value == 3.4


def test_dataset_statistic_errors_on_a_missing_file_or_column() -> None:
    claim = make_claim("a mean value of 3.4", ClaimType.DATASET, expected_value=3.4)
    gone = DatasetArtifact(artifact_id="ds", path="data/fixtures/datasets/nope.csv")
    assert (
        statistical.dataset_statistic_check(
            "id", claim, gone, _dataset_link(), "mean", 3.4, REPO_ROOT
        ).status
        is ST.ERROR
    )
    bad_column = statistical.dataset_statistic_check(
        "id", claim, _measurements(), _dataset_link("column=nope"), "mean", 3.4, REPO_ROOT
    )
    assert bad_column.status is ST.ERROR


def test_dataset_statistic_errors_when_the_artifact_declares_no_path() -> None:
    claim = make_claim("a mean value of 3.4", ClaimType.DATASET, expected_value=3.4)
    check = statistical.dataset_statistic_check(
        "id", claim, DatasetArtifact(artifact_id="ds"), _dataset_link(), "mean", 3.4, REPO_ROOT
    )
    assert check.status is ST.ERROR


def test_numeric_tolerance_skips_rather_than_fails_when_nothing_was_produced() -> None:
    claim = make_claim("an accuracy of 0.80", expected_value=0.8)
    check = statistical.numeric_tolerance_check("id", claim, None, "stdout", [])
    # No number disagreed, because no number exists.
    assert check.status is ST.SKIPPED


def test_numeric_tolerance_passes_within_the_claims_reported_precision() -> None:
    claim = make_claim("an accuracy of 0.80", expected_value=0.8)
    assert statistical.numeric_tolerance_check("id", claim, 0.804, "stdout", []).status is ST.PASS
    assert statistical.numeric_tolerance_check("id", claim, 0.81, "stdout", []).status is ST.FAIL


def test_numeric_tolerance_skips_when_the_claim_states_no_value() -> None:
    claim = make_claim("the script prints an accuracy", ClaimType.CODE_REPRODUCTION)
    assert statistical.numeric_tolerance_check("id", claim, 0.8, "stdout", []).status is ST.SKIPPED


# ---------------------------------------------------------------------------
# Evidence presence: five assertion levels, only two of them `pass`
# ---------------------------------------------------------------------------


def test_negation_cues_survive_stopword_removal() -> None:
    assert consistency.negation_cues("no real corpora were used") == ("no",)
    assert consistency.negation_cues("the model is trained") == ()


def test_assertion_verbatim() -> None:
    presence = consistency.assess_presence(
        "The method reaches 90% accuracy.", "The method reaches 90% accuracy."
    )
    assert presence.assertion is consistency.Assertion.VERBATIM
    assert consistency.asserts_claim(presence)


def test_assertion_token_subsumed() -> None:
    presence = consistency.assess_presence(
        "The synthetic sequence has a GC content of 0.50.",
        "For the synthetic 10-base sequence, 5 of 10 bases are G or C, "
        "giving a GC content of 0.50.",
    )
    assert presence.assertion is consistency.Assertion.TOKEN_SUBSUMED
    assert presence.coverage == 1.0


def test_assertion_polarity_mismatch_flips_a_would_be_pass_to_fail() -> None:
    presence = consistency.assess_presence(
        "The model is trained on synthetic data.",
        "The model is not trained on synthetic data.",
    )
    assert presence.assertion is consistency.Assertion.POLARITY_MISMATCH
    assert presence.sentence_cues == ("not",) and presence.claim_cues == ()


def test_assertion_partial_overlap_is_the_honest_verdict_on_a_paraphrase() -> None:
    # The passage DOES support the claim, and a bag-of-words rule cannot know that:
    # "trained" != "training", and "only" != "no real corpora were used".
    presence = consistency.assess_presence(
        "The model is trained only on synthetic data.",
        "All experiments use synthetic data generated by our pipeline; "
        "no real corpora were used at any stage of training.",
    )
    assert presence.assertion is consistency.Assertion.PARTIAL_OVERLAP
    assert presence.missing_tokens == ("model", "only", "trained")
    assert presence.coverage == pytest.approx(0.4)
    assert not consistency.asserts_claim(presence)


def test_assertion_absent() -> None:
    presence = consistency.assess_presence("Accuracy is 90.0.", "Bananas ripen quickly.")
    assert presence.assertion is consistency.Assertion.ABSENT


def test_polarity_is_judged_on_the_quoting_sentence_not_the_whole_passage() -> None:
    # The paper negates something *else* in a neighbouring sentence.
    presence = consistency.assess_presence(
        "The model is trained on synthetic data.",
        "No GPU was used. The model is trained on synthetic data.",
    )
    assert presence.assertion is consistency.Assertion.VERBATIM


def _passage_link(passage_id: str = "p") -> EvidenceLink:
    return EvidenceLink(kind=EvidenceKind.PASSAGE, target_id=passage_id)


def test_evidence_presence_status_mapping() -> None:
    claim = make_claim("The method reaches 90% accuracy.")
    verbatim = Passage(passage_id="p", text="The method reaches 90% accuracy.")
    exact = consistency.evidence_presence_check("id", claim, _passage_link(), verbatim)
    assert exact.status is ST.PASS and exact.computed_value == "verbatim"

    partial = Passage(passage_id="p", text="The method reaches high accuracy.")
    vague = consistency.evidence_presence_check("id", claim, _passage_link(), partial)
    # It cannot decide, so it does not pretend to. `inconclusive`, never `fail`.
    assert vague.status is ST.INCONCLUSIVE
    assert vague.inputs["missing_tokens"] == ["90"]


def test_evidence_presence_skips_without_a_link_and_errors_on_a_dangling_one() -> None:
    claim = make_claim("The method reaches 90% accuracy.")
    assert consistency.evidence_presence_check("id", claim, None, None).status is ST.SKIPPED
    dangling = consistency.evidence_presence_check("id", claim, _passage_link("ghost"), None)
    assert dangling.status is ST.ERROR


# ---------------------------------------------------------------------------
# Comparison check
# ---------------------------------------------------------------------------


def _comparison_claim() -> ScientificClaim:
    return make_claim(
        "Method A improves accuracy from 72.0 to 78.0",
        ClaimType.COMPARISON,
        expected_value=78.0,
        baseline_value=72.0,
        comparison_operator=ComparisonOperator.GT,
    )


def test_comparison_check_verifies_the_relation_between_the_observed_values() -> None:
    check = consistency.comparison_check("id", _comparison_claim(), 72.0, 78.0, [])
    assert check.status is ST.PASS
    assert check.computed_value == 6.0 and check.expected_value == 6.0


def test_comparison_check_fails_when_the_artifacts_reverse_the_claimed_direction() -> None:
    check = consistency.comparison_check("id", _comparison_claim(), 78.0, 72.0, [])
    assert check.status is ST.FAIL
    assert check.computed_value == -6.0


def test_comparison_check_records_a_delta_disagreement_without_failing_on_it() -> None:
    # The direction holds; the magnitude does not match the claim. Each cell's
    # magnitude is already checked by table_value, so this check reports and passes.
    check = consistency.comparison_check("id", _comparison_claim(), 72.0, 75.0, [])
    assert check.status is ST.PASS
    assert check.difference == pytest.approx(-3.0)


def test_comparison_check_skips_without_both_sides() -> None:
    one_sided = consistency.comparison_check("id", _comparison_claim(), None, 78.0, [])
    assert one_sided.status is ST.SKIPPED
    plain = make_claim("accuracy of 78.0", expected_value=78.0)
    assert consistency.comparison_check("id", plain, 72.0, 78.0, []).status is ST.SKIPPED


# ---------------------------------------------------------------------------
# Code execution
# ---------------------------------------------------------------------------


def test_parse_observable_prefers_the_claims_metric() -> None:
    stdout = "loss=0.10\naccuracy=0.80\n"
    assert code_execution.parse_observable(stdout, ["accuracy"]) == ("accuracy", 0.8)
    # Several unrelated metric lines and no claim metric: picking one would be a guess.
    assert code_execution.parse_observable(stdout, []) is None
    assert code_execution.parse_observable("gc_content=0.50\n", []) == ("gc_content", 0.5)
    assert code_execution.parse_observable("nothing to see", ["accuracy"]) is None


def test_stdout_expectations_reads_the_bundles_declared_substrings() -> None:
    declared = {"stdout_contains": "a=1", "accuracy": 1.0}
    assert code_execution.stdout_expectations(declared) == ["a=1"]


def _script(tmp_path: Path, body: str) -> tuple[CodeArtifact, EvidenceLink]:
    (tmp_path / "s.py").write_text(textwrap.dedent(body), encoding="utf-8")
    artifact = CodeArtifact(artifact_id="code", path="s.py", entrypoint="python s.py")
    return artifact, EvidenceLink(kind=EvidenceKind.CODE, target_id="code", locator="stdout")


class FakeRunner:
    """A ScriptRunner that returns a canned result, so failure paths need no real script."""

    name = "fake"

    def __init__(self, result: code_execution.ExecutionResult) -> None:
        self.result = result

    def run(self, script: Path, timeout: float) -> code_execution.ExecutionResult:
        return self.result


def _result(**kw) -> code_execution.ExecutionResult:
    defaults = {
        "command": ("python", "s.py"),
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "timed_out": False,
    }
    return code_execution.ExecutionResult(**{**defaults, **kw})


def test_the_default_runner_is_the_milestone_6_sandbox() -> None:
    # The check was written against the `ScriptRunner` protocol, so M6 swapped the
    # implementation without touching the check. Low-level runner behaviour (temp dir,
    # env scrubbing, network guard, process-group kill) is pinned in test_sandbox.py.
    assert code_execution.SandboxScriptRunner is runner_module.SandboxScriptRunner
    assert code_execution.SandboxScriptRunner.name == "sandbox"


def test_code_execution_reports_a_sandbox_failure_as_error_not_a_verdict(tmp_path: Path) -> None:
    # If the sandbox could not enforce the policy it promised, attributing the script's
    # number to those conditions would be a lie. The check errors instead.
    class BrokenRunner:
        name = "broken"

        def run(self, script: Path, timeout: float) -> code_execution.ExecutionResult:
            raise code_execution.SandboxError("bootstrap did not run")

    artifact, link = _script(tmp_path, "print('accuracy=0.80')")
    check = code_execution.code_execution_check(
        "id", make_claim("x", ClaimType.CODE_REPRODUCTION), artifact, link, {}, tmp_path,
        runner=BrokenRunner(),
    )
    assert check.status is ST.ERROR and "sandbox failed" in (check.notes or "")


def test_code_execution_records_a_denied_network_attempt(tmp_path: Path) -> None:
    # A script that reached for the network is not self-contained, even if it then
    # printed the right number. The attempt reaches the check's record and its notes.
    artifact, link = _script(tmp_path, "pass")
    check = code_execution.code_execution_check(
        "id", make_claim("x", ClaimType.CODE_REPRODUCTION), artifact, link, {}, tmp_path,
        runner=FakeRunner(_result(stdout="accuracy=0.80\n", network_attempts=("socket.socket",))),
    )
    assert check.status is ST.PASS
    assert check.inputs["network_attempts"] == ["socket.socket"]
    assert "denied network access" in (check.notes or "")


def test_code_execution_runs_a_real_fixture_script_and_parses_the_metric() -> None:
    claim = make_claim(
        "Running compute_accuracy.py reports an accuracy of 0.80.",
        ClaimType.CODE_REPRODUCTION,
        metrics=["accuracy"],
        expected_value=0.8,
    )
    artifact = CodeArtifact(artifact_id="code", path="data/fixtures/code/compute_accuracy.py")
    link = EvidenceLink(kind=EvidenceKind.CODE, target_id="code", locator="stdout")
    check = code_execution.code_execution_check(
        "id", claim, artifact, link, {"stdout_contains": "accuracy=0.80"}, REPO_ROOT
    )
    assert check.status is ST.PASS
    assert check.computed_value == 0.8
    assert check.inputs["exit_code"] == 0 and check.inputs["observable"] == "accuracy"
    assert check.inputs["runner"] == "sandbox"
    # The declared entrypoint is documentation; the command derives from `path`.
    assert check.inputs["command"] == ["python", "compute_accuracy.py"]


def test_code_execution_treats_a_crash_as_error_not_failure(tmp_path: Path) -> None:
    # A script that will not run says nothing about the claim's number.
    artifact, link = _script(tmp_path, "raise SystemExit(2)")
    check = code_execution.code_execution_check(
        "id", make_claim("x", ClaimType.CODE_REPRODUCTION), artifact, link, {}, tmp_path,
        runner=FakeRunner(_result(exit_code=2, stderr="Traceback")),
    )
    assert check.status is ST.ERROR
    assert "exited 2" in (check.notes or "")


def test_code_execution_treats_a_timeout_as_error(tmp_path: Path) -> None:
    artifact, link = _script(tmp_path, "pass")
    check = code_execution.code_execution_check(
        "id", make_claim("x", ClaimType.CODE_REPRODUCTION), artifact, link, {}, tmp_path,
        runner=FakeRunner(_result(exit_code=None, timed_out=True)),
    )
    assert check.status is ST.ERROR and "timed out" in (check.notes or "")


def test_code_execution_fails_when_a_clean_run_omits_the_observable(tmp_path: Path) -> None:
    artifact, link = _script(tmp_path, "pass")
    check = code_execution.code_execution_check(
        "id",
        make_claim("x", ClaimType.CODE_REPRODUCTION),
        artifact,
        link,
        {"stdout_contains": "accuracy=0.80"},
        tmp_path,
        runner=FakeRunner(_result(stdout="hello\n")),
    )
    assert check.status is ST.FAIL


def test_code_execution_skips_when_disabled_or_unsupported(tmp_path: Path) -> None:
    artifact, link = _script(tmp_path, "pass")
    claim = make_claim("x", ClaimType.CODE_REPRODUCTION)
    off = code_execution.code_execution_check(
        "id", claim, artifact, link, {}, tmp_path, execute=False
    )
    assert off.status is ST.SKIPPED

    other = artifact.model_copy(update={"language": "r"})
    unsupported = code_execution.code_execution_check("id", claim, other, link, {}, tmp_path)
    assert unsupported.status is ST.SKIPPED


def test_code_execution_errors_on_a_missing_script(tmp_path: Path) -> None:
    artifact = CodeArtifact(artifact_id="code", path="gone.py")
    link = EvidenceLink(kind=EvidenceKind.CODE, target_id="code", locator="stdout")
    check = code_execution.code_execution_check(
        "id", make_claim("x", ClaimType.CODE_REPRODUCTION), artifact, link, {}, tmp_path
    )
    assert check.status is ST.ERROR and "not found" in (check.notes or "")


def test_code_execution_records_the_timeout_it_applied() -> None:
    claim = make_claim("gc content of 0.50", ClaimType.CODE_REPRODUCTION, metrics=["gc_content"])
    artifact = CodeArtifact(artifact_id="code", path="data/fixtures/code/gc_content.py")
    link = EvidenceLink(kind=EvidenceKind.CODE, target_id="code", locator="stdout")
    default = code_execution.code_execution_check("id", claim, artifact, link, {}, REPO_ROOT)
    assert default.inputs["timeout_seconds"] == code_execution.DEFAULT_TIMEOUT_SECONDS

    declared = artifact.model_copy(update={"timeout_seconds": 2.5})
    check = code_execution.code_execution_check("id", claim, declared, link, {}, REPO_ROOT)
    assert check.inputs["timeout_seconds"] == 2.5


# ---------------------------------------------------------------------------
# The runner: dispatch, ordering, dangling links
# ---------------------------------------------------------------------------


def _bundle_with_table() -> ArtifactBundle:
    return ArtifactBundle(
        bundle_id="b",
        papers=[PaperArtifact(artifact_id="paper", passages=[Passage(passage_id="p", text="hi")])],
        tables=[ACCURACY_TABLE],
    )


def test_run_checks_reports_a_dangling_link_as_an_error() -> None:
    claim = make_claim("accuracy of 78.0", expected_value=78.0)
    links = [table_link("ghost", "col=accuracy")]
    run = verification.run_checks(claim, _bundle_with_table(), links, repo_root=REPO_ROOT)
    table = run.of_type(CT.TABLE_VALUE)[0]
    assert table.status is ST.ERROR and "does not resolve" in (table.notes or "")


def test_run_checks_emits_no_comparison_for_a_claim_that_asserts_no_relation() -> None:
    claim = make_claim("accuracy of 78.0", expected_value=78.0)
    run = verification.run_checks(claim, _bundle_with_table(), [], repo_root=REPO_ROOT)
    assert run.of_type(CT.COMPARISON) == []


def test_run_checks_skips_a_dataset_whose_statistic_it_cannot_name() -> None:
    bundle = ArtifactBundle(bundle_id="b", datasets=[_measurements()])
    claim = make_claim("the gc content is 0.5", ClaimType.DATASET, metrics=["gc_content"])
    run = verification.run_checks(claim, bundle, [_dataset_link()], repo_root=REPO_ROOT)
    statistic = run.of_type(CT.DATASET_STATISTIC)[0]
    assert statistic.status is ST.SKIPPED and "names no statistic" in (statistic.notes or "")


def test_run_checks_orders_checks_by_type_regardless_of_link_order() -> None:
    claim = make_claim("accuracy of 78.0", expected_value=78.0)
    links = [table_link("t", "col=accuracy"), _passage_link("p")]
    run = verification.run_checks(claim, _bundle_with_table(), links, repo_root=REPO_ROOT)
    assert [c.check_type for c in run.checks] == [CT.EVIDENCE_PRESENCE, CT.TABLE_VALUE]


def test_check_ids_are_unique_and_numbered_per_type() -> None:
    run = _run_task(load_fixture("statistical_claims", "dataset_mean.yaml"))
    ids = [check.check_id for check in run.checks]
    assert len(ids) == len(set(ids))
    assert "c_dataset_mean.dataset_statistic.2" in ids


def test_counts_cover_every_status() -> None:
    run = verification.CheckRun(claim=make_claim("x"))
    assert set(run.counts) == {"pass", "fail", "inconclusive", "error", "skipped"}


def test_find_passage_searches_every_paper() -> None:
    bundle = _bundle_with_table()
    assert verification.find_passage(bundle, "p") is not None
    assert verification.find_passage(bundle, "ghost") is None


# ---------------------------------------------------------------------------
# Integration over the committed fixtures
# ---------------------------------------------------------------------------


def _run_task(task: loader.LoadedTask, execute: bool = True) -> verification.CheckRun:
    from scientific_claim_verifier.claims.extraction import RuleBasedClaimExtractor
    from scientific_claim_verifier.claims.linking import EvidenceLinker

    extraction = RuleBasedClaimExtractor().extract(task.input_claim, task.bundle)
    linking = EvidenceLinker(use_declared_source=False).link(extraction.claim, task.bundle)
    return verification.run_checks(
        linking.claim, task.bundle, linking.links, repo_root=REPO_ROOT, execute=execute
    )


# The measured outcome of this milestone, task by task (see docs/RESULTS.md).
EXPECTED_CHECKS: dict[str, list[tuple[CheckType, CheckStatus]]] = {
    "accuracy_improvement": [
        (CT.EVIDENCE_PRESENCE, ST.PASS),
        (CT.TABLE_VALUE, ST.PASS),
        (CT.TABLE_VALUE, ST.PASS),
        (CT.COMPARISON, ST.PASS),
    ],
    "contradicted_f1": [(CT.EVIDENCE_PRESENCE, ST.PASS), (CT.TABLE_VALUE, ST.FAIL)],
    "dataset_mean": [
        (CT.EVIDENCE_PRESENCE, ST.PASS),
        (CT.DATASET_STATISTIC, ST.PASS),
        (CT.DATASET_STATISTIC, ST.PASS),
    ],
    "gc_content": [
        (CT.EVIDENCE_PRESENCE, ST.PASS),
        (CT.CODE_EXECUTION, ST.PASS),
        (CT.NUMERIC_TOLERANCE, ST.PASS),
    ],
    "recompute_accuracy": [
        (CT.EVIDENCE_PRESENCE, ST.PASS),
        (CT.CODE_EXECUTION, ST.PASS),
        (CT.NUMERIC_TOLERANCE, ST.PASS),
    ],
    "synthetic_data_passage": [(CT.EVIDENCE_PRESENCE, ST.INCONCLUSIVE)],
    "underspecified_split": [(CT.EVIDENCE_PRESENCE, ST.PASS), (CT.TABLE_VALUE, ST.PASS)],
}


@pytest.mark.parametrize("task_id", sorted(EXPECTED_CHECKS))
def test_every_fixture_produces_the_expected_checks(task_id: str) -> None:
    path = next(p for p in loader.discover_task_files(TASKS_DIR) if p.stem == task_id)
    run = _run_task(loader.load_task(path, REPO_ROOT))
    assert [(c.check_type, c.status) for c in run.checks] == EXPECTED_CHECKS[task_id]


def test_the_contradiction_fixture_shows_text_and_table_disagreeing() -> None:
    """The whole point of the project, in one task: the paper says 91.0, the table says 86.0."""
    task = load_fixture("table_claims", "contradicted_f1.yaml")
    run = _run_task(task)
    presence = run.of_type(CT.EVIDENCE_PRESENCE)[0]
    table = run.of_type(CT.TABLE_VALUE)[0]
    assert presence.status is ST.PASS and presence.computed_value == "verbatim"
    assert table.status is ST.FAIL and table.computed_value == 86.0
    # Neither check decides; scoring (M7) reads both and says `contradicted`.
    assert task.spec.expected.support_label.value == "contradicted"


def test_the_paraphrase_fixture_is_inconclusive_not_failed() -> None:
    """Gold says `supported`; a bag-of-words check cannot confirm it, and says so.

    This is the milestone's most informative result. Marking it `fail` would
    manufacture a contradiction out of the checker's own ignorance.
    """
    task = load_fixture("ml_claims", "synthetic_data_passage.yaml")
    run = _run_task(task)
    assert [c.status for c in run.checks] == [ST.INCONCLUSIVE]
    assert task.spec.expected.support_label.value == "supported"


def test_underspecified_and_contradicted_share_a_locator_but_not_a_verdict() -> None:
    """Both link `col=…`; only the ambiguity signal in `inputs` tells them apart."""
    under = _run_task(load_fixture("ml_claims", "underspecified_split.yaml"))
    contra = _run_task(load_fixture("table_claims", "contradicted_f1.yaml"))
    under_table = under.of_type(CT.TABLE_VALUE)[0]
    contra_table = contra.of_type(CT.TABLE_VALUE)[0]
    assert under_table.status is ST.PASS and under_table.inputs["matching_rows"] == ["dev"]
    assert contra_table.status is ST.FAIL and contra_table.inputs["matching_rows"] == []


def test_no_execute_skips_the_script_and_the_number_that_depends_on_it() -> None:
    task = load_fixture("bioinformatics_claims", "gc_content.yaml")
    run = _run_task(task, execute=False)
    assert run.of_type(CT.CODE_EXECUTION)[0].status is ST.SKIPPED
    assert run.of_type(CT.NUMERIC_TOLERANCE)[0].status is ST.SKIPPED


def test_checks_are_deterministic_across_runs() -> None:
    task = load_fixture("code_reproduction", "recompute_accuracy.yaml")
    first = verification.checks_to_dict(_run_task(task))
    second = verification.checks_to_dict(_run_task(task))
    assert first == second


def test_run_checks_does_not_mutate_the_claim() -> None:
    task = load_fixture("table_claims", "accuracy_improvement.yaml")
    claim = task.input_claim
    before = claim.model_dump()
    verification.run_checks(claim, task.bundle, [], repo_root=REPO_ROOT)
    assert claim.model_dump() == before


def test_every_check_records_its_evidence_and_a_note() -> None:
    for path in loader.discover_task_files(TASKS_DIR):
        run = _run_task(loader.load_task(path, REPO_ROOT))
        for check in run.checks:
            assert check.notes
            assert check.claim_id == run.claim.claim_id
            if check.status in (ST.PASS, ST.FAIL):
                assert check.evidence, f"{check.check_id} decided without citing evidence"


def test_a_numeric_check_always_records_the_tolerance_it_applied() -> None:
    numeric = (CT.TABLE_VALUE, CT.DATASET_STATISTIC, CT.NUMERIC_TOLERANCE, CT.COMPARISON)
    for path in loader.discover_task_files(TASKS_DIR):
        run = _run_task(loader.load_task(path, REPO_ROOT))
        for check in run.checks:
            if check.check_type in numeric and check.status in (ST.PASS, ST.FAIL):
                assert check.tolerance is not None, check.check_id
                assert check.difference is not None, check.check_id


# ---------------------------------------------------------------------------
# Tolerance overrides: per task and per run
# ---------------------------------------------------------------------------


_TOLERANCE_TASK = textwrap.dedent(
    """
    task_id: loose
    family: numeric_table
    title: "Tolerance override"
    claim:
      claim_id: c_loose
      claim_text: "The method reaches 90.0 accuracy."
      claim_type: numeric_claim
      source_passage: p
    artifacts:
      bundle_id: b_loose
      papers:
        - artifact_id: paper
          passages:
            - passage_id: p
              text: "The method reaches 90.0 accuracy."
      tables:
        - table_id: t
          columns: [split, accuracy]
          rows:
            - [dev, 90.4]
    expected:
      support_label: supported
    """
).strip()


def _tolerance_task(tmp_path: Path, tolerance_block: str) -> Path:
    """A self-contained table task (no fixture files) whose cell is 0.4 off the claim."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "loose.yaml"
    path.write_text(f"{_TOLERANCE_TASK}\n{tolerance_block}\n", encoding="utf-8")
    return path


def _table_status(path: Path, **kw) -> CheckStatus:
    task = loader.load_task(path, path.parent)
    run = verification.run_checks(
        task.input_claim.model_copy(update={"expected_value": 90.0, "metrics": ["accuracy"]}),
        task.bundle,
        [table_link("t", "col=accuracy")],
        repo_root=path.parent,
        override=verification.resolve_override(task, kw.get("abs_tol"), kw.get("rel_tol")),
    )
    return run.of_type(CT.TABLE_VALUE)[0].status


def test_reported_precision_fails_a_cell_the_task_tolerance_accepts(tmp_path: Path) -> None:
    strict = _tolerance_task(tmp_path / "a", "")
    assert _table_status(strict) is ST.FAIL  # |90.4 - 90.0| = 0.4 > 0.05
    loose = _tolerance_task(tmp_path / "b", "tolerance:\n  abs_tol: 0.5")
    assert _table_status(loose) is ST.PASS


def test_a_cli_tolerance_flag_overrides_the_task_file(tmp_path: Path) -> None:
    loose = _tolerance_task(tmp_path / "c", "tolerance:\n  abs_tol: 0.5")
    assert _table_status(loose, abs_tol=0.001) is ST.FAIL
    strict = _tolerance_task(tmp_path / "d", "")
    assert _table_status(strict, rel_tol=0.01) is ST.PASS  # 1% of 90 = 0.9


# ---------------------------------------------------------------------------
# CLI / script entry points
# ---------------------------------------------------------------------------

_TASK = str(TASKS_DIR / "table_claims" / "contradicted_f1.yaml")


def test_cli_run_checks_text_report(capsys) -> None:
    assert cli.main(["run-checks", "--task", _TASK]) == 0
    out = capsys.readouterr().out
    assert "verification checks" in out
    assert "[fail] table_value" in out
    # The report must never imply it reached a verdict.
    assert "NOT produced by this stage" in out


def test_cli_run_checks_json(capsys) -> None:
    import json

    assert cli.main(["run-checks", "--task", _TASK, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["task_id"] == "contradicted_f1"
    assert payload["counts"] == {"pass": 1, "fail": 1, "inconclusive": 0, "error": 0, "skipped": 0}
    assert payload["checks"][1]["status"] == "fail"


def test_cli_run_checks_writes_out_file(tmp_path: Path, capsys) -> None:
    code = cli.main(["run-checks", "--task", _TASK, "--out", str(tmp_path)])
    assert code == 0
    written = tmp_path / "contradicted_f1.checks.json"
    assert written.is_file()
    assert "wrote" in capsys.readouterr().err


def test_cli_run_checks_no_execute(capsys) -> None:
    task = str(TASKS_DIR / "code_reproduction" / "recompute_accuracy.yaml")
    assert cli.main(["run-checks", "--task", task, "--no-execute"]) == 0
    assert "execution disabled" in capsys.readouterr().out


def test_cli_run_checks_abs_tol_flips_the_contradiction(capsys) -> None:
    assert cli.main(["run-checks", "--task", _TASK, "--abs-tol", "10"]) == 0
    out = capsys.readouterr().out
    assert "[pass] table_value" in out


def test_cli_run_checks_blind_passage_linking(capsys) -> None:
    assert cli.main(["run-checks", "--task", _TASK, "--no-declared-source"]) == 0
    assert "[pass] evidence_presence" in capsys.readouterr().out


def test_cli_run_checks_missing_task_returns_1(capsys) -> None:
    assert cli.main(["run-checks", "--task", str(TASKS_DIR / "nope.yaml")]) == 1
    assert "could not load task" in capsys.readouterr().err


def test_script_entry_point_matches_the_cli(capsys) -> None:
    assert verification.main(["--task", _TASK, "--json"]) == 0
    assert '"task_id": "contradicted_f1"' in capsys.readouterr().out


def test_numbered_script_runs_standalone() -> None:
    # scripts/03_run_checks.py must work without an editable install.
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "03_run_checks.py"), "--task", _TASK],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0
    assert "verification checks" in completed.stdout
