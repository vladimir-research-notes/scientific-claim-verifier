"""Milestone 7 — scoring: support labels, reproduction status, failure modes.

Unit tests per classifier on synthetic checks, then integration over every committed
fixture. The pinned behaviours are the ones the design rests on:

- a check's ``status`` is about the check; its :class:`Signal` is about the claim, and
  one status maps to more than one signal;
- an ``inconclusive`` evidence check yields ``unverifiable_from_artifacts`` and
  ``evidence_undecidable`` — **never** ``contradicted`` or ``passage_does_not_assert``;
- an evidence check that finds the claim *absent* refutes nothing;
- a passing column lookup with the row unnamed is ``underspecified``, not ``supported``;
- a script that will not run is a reproduction failure, never a numeric disagreement;
- refutation outranks ambiguity, which outranks support;
- reading a table cell is not a reproduction;
- over the committed fixtures the pipeline makes **zero wrong verdicts**, and its one
  miss is a refusal to decide.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scientific_claim_verifier import cli, scoring
from scientific_claim_verifier.artifacts import loader
from scientific_claim_verifier.checks import ErrorKind
from scientific_claim_verifier.sandbox.trace import read_trace
from scientific_claim_verifier.schemas import (
    CheckStatus,
    CheckType,
    EvidenceKind,
    EvidenceLink,
    FailureMode,
    ReproductionStatus,
    SupportLabel,
    VerificationCheck,
)
from scientific_claim_verifier.scoring import Signal, failure_modes, reproducibility, summary
from scientific_claim_verifier.scoring import support_labels as sl
from scientific_claim_verifier.scoring import verdict as V

REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = REPO_ROOT / "tasks"

ST = CheckStatus
CT = CheckType
SLB = SupportLabel
RS = ReproductionStatus
FM = FailureMode

# Every committed fixture, by the path `verify` takes. Kept in step with
# `tasks/smoke_suite.yaml`, which runs the same set (see tests/test_suite.py).
FIXTURES = {
    "accuracy_improvement": "table_claims/accuracy_improvement.yaml",
    "contradicted_f1": "table_claims/contradicted_f1.yaml",
    "dataset_mean": "statistical_claims/dataset_mean.yaml",
    "dataset_mean_overstated": "statistical_claims/dataset_mean_overstated.yaml",
    "dataset_std": "statistical_claims/dataset_std.yaml",
    "gc_content": "bioinformatics_claims/gc_content.yaml",
    "negated_training_data": "ml_claims/negated_training_data.yaml",
    "recompute_accuracy": "code_reproduction/recompute_accuracy.yaml",
    "synthetic_data_passage": "ml_claims/synthetic_data_passage.yaml",
    "underspecified_split": "ml_claims/underspecified_split.yaml",
    "unreproducible_accuracy": "code_reproduction/unreproducible_accuracy.yaml",
}


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def chk(
    check_type: CheckType,
    status: CheckStatus,
    *,
    check_id: str | None = None,
    difference: float | None = None,
    **inputs,
) -> VerificationCheck:
    """A `VerificationCheck` with just the fields scoring reads."""
    return VerificationCheck(
        check_id=check_id or f"c.{check_type.value}.1",
        check_type=check_type,
        claim_id="c",
        status=status,
        difference=difference,
        inputs=inputs,
        notes="(synthetic)",
    )


def evidence(status: CheckStatus, assertion: str | None = None, **inputs) -> VerificationCheck:
    check = chk(CT.EVIDENCE_PRESENCE, status, assertion=assertion, **inputs)
    return check.model_copy(
        update={
            "evidence": [EvidenceLink(kind=EvidenceKind.PASSAGE, target_id="p", quote="q")],
        }
    )


def signal_of(check: VerificationCheck) -> Signal:
    return scoring.signal_for(check).signal


def verify(name: str, **kw):
    """Run the full pipeline over a committed fixture."""
    return V.verify_task(TASKS_DIR / FIXTURES[name], repo_root=REPO_ROOT, **kw)


# ---------------------------------------------------------------------------
# Signals: one status, more than one meaning
# ---------------------------------------------------------------------------


def test_evidence_pass_supports() -> None:
    assert signal_of(evidence(ST.PASS, "verbatim")) is Signal.SUPPORTS
    assert signal_of(evidence(ST.PASS, "token_subsumed")) is Signal.SUPPORTS


def test_evidence_polarity_mismatch_refutes_but_absence_does_not() -> None:
    # Both are `fail`. Only one is evidence *against* the claim: a passage that negates
    # the claim refutes it, while a passage that never mentions it says nothing at all.
    assert signal_of(evidence(ST.FAIL, "polarity_mismatch")) is Signal.REFUTES
    assert signal_of(evidence(ST.FAIL, "absent")) is Signal.UNDECIDED


def test_evidence_inconclusive_is_undecided_and_quotes_what_it_saw() -> None:
    check = evidence(ST.INCONCLUSIVE, "partial_overlap", coverage=0.4, missing_tokens=["only"])
    reduced = scoring.signal_for(check)
    assert reduced.signal is Signal.UNDECIDED
    assert "40% token coverage" in reduced.because and "only" in reduced.because


def test_evidence_inconclusive_without_coverage_still_explains_itself() -> None:
    reduced = scoring.signal_for(evidence(ST.INCONCLUSIVE, "partial_overlap"))
    assert reduced.signal is Signal.UNDECIDED
    assert "cannot decide" in reduced.because


def test_evidence_skipped_and_errored_are_undecided() -> None:
    assert signal_of(evidence(ST.SKIPPED)) is Signal.UNDECIDED
    dangling = evidence(ST.ERROR, error_kind=ErrorKind.MISSING_PASSAGE.value)
    reduced = scoring.signal_for(dangling)
    assert reduced.signal is Signal.UNDECIDED and "missing_passage" in reduced.because


def test_table_cell_lookup_supports_but_an_ambiguous_column_does_not() -> None:
    # Same status (`pass`), same check type; only `inputs` tells them apart.
    cell = chk(CT.TABLE_VALUE, ST.PASS, row="A", column="accuracy")
    assert signal_of(cell) is Signal.SUPPORTS

    column = chk(CT.TABLE_VALUE, ST.PASS, row_named=False, n_rows=2, matching_rows=["dev"])
    assert signal_of(column) is Signal.AMBIGUOUS


def test_a_single_row_column_offers_no_choice_so_it_is_not_ambiguous() -> None:
    column = chk(CT.TABLE_VALUE, ST.PASS, row_named=False, n_rows=1, matching_rows=["dev"])
    assert signal_of(column) is Signal.SUPPORTS


def test_table_fail_refutes_and_table_error_decides_nothing() -> None:
    assert signal_of(chk(CT.TABLE_VALUE, ST.FAIL, row_named=False, n_rows=2)) is Signal.REFUTES
    assert signal_of(chk(CT.TABLE_VALUE, ST.ERROR)) is Signal.UNDECIDED
    assert signal_of(chk(CT.TABLE_VALUE, ST.SKIPPED)) is Signal.UNDECIDED


def test_exit_zero_alone_is_not_evidence_for_a_number() -> None:
    # The script ran, but the bundle declared no expected output. Nothing was verified.
    bare = chk(CT.CODE_EXECUTION, ST.PASS, declared_expectations=[])
    assert signal_of(bare) is Signal.UNDECIDED

    verified = chk(CT.CODE_EXECUTION, ST.PASS, declared_expectations=["accuracy=0.80"])
    assert signal_of(verified) is Signal.SUPPORTS


def test_code_execution_fail_refutes_and_error_decides_nothing() -> None:
    assert signal_of(chk(CT.CODE_EXECUTION, ST.FAIL)) is Signal.REFUTES
    assert signal_of(chk(CT.CODE_EXECUTION, ST.ERROR)) is Signal.UNDECIDED
    assert signal_of(chk(CT.CODE_EXECUTION, ST.SKIPPED)) is Signal.UNDECIDED


@pytest.mark.parametrize(
    "check_type", [CT.DATASET_STATISTIC, CT.NUMERIC_TOLERANCE, CT.COMPARISON, CT.FIGURE_RECOMPUTE]
)
def test_value_checks_have_exactly_two_verdicts(check_type: CheckType) -> None:
    assert signal_of(chk(check_type, ST.PASS)) is Signal.SUPPORTS
    assert signal_of(chk(check_type, ST.FAIL)) is Signal.REFUTES
    assert signal_of(chk(check_type, ST.SKIPPED)) is Signal.UNDECIDED
    assert signal_of(chk(check_type, ST.ERROR)) is Signal.UNDECIDED


def test_decidedness_counts_only_pass_and_fail() -> None:
    assert scoring.decidedness([]) == 0.0
    assert scoring.decidedness([chk(CT.TABLE_VALUE, ST.PASS)]) == 1.0
    assert scoring.decidedness([evidence(ST.INCONCLUSIVE, "partial_overlap")]) == 0.0
    mixed = [chk(CT.TABLE_VALUE, ST.PASS), chk(CT.COMPARISON, ST.ERROR)]
    assert scoring.decidedness(mixed) == 0.5


def test_of_signal_preserves_check_order() -> None:
    checks = [
        chk(CT.TABLE_VALUE, ST.PASS, check_id="a"),
        chk(CT.COMPARISON, ST.PASS, check_id="b"),
    ]
    picked = scoring.of_signal(scoring.signals(checks), Signal.SUPPORTS)
    assert [item.check_id for item in picked] == ["a", "b"]


# ---------------------------------------------------------------------------
# Support labels: the rule table and its ordering
# ---------------------------------------------------------------------------


def test_no_checks_is_not_checked() -> None:
    label, rule = sl.classify_support([])
    assert label is SLB.NOT_CHECKED and rule.name == "no_checks"


def test_refutation_beats_ambiguity() -> None:
    # A value absent from a column is contradicted whether or not the claim also
    # omitted the row.
    checks = [
        chk(CT.TABLE_VALUE, ST.PASS, check_id="amb", row_named=False, n_rows=2),
        chk(CT.DATASET_STATISTIC, ST.FAIL, check_id="ref"),
    ]
    label, rule = sl.classify_support(checks)
    assert label is SLB.CONTRADICTED
    assert rule.name == "artifacts_refute" and rule.check_ids == ("ref",)


def test_ambiguity_beats_support() -> None:
    checks = [
        evidence(ST.PASS, "verbatim"),
        chk(CT.TABLE_VALUE, ST.PASS, check_id="amb", row_named=False, n_rows=2),
    ]
    label, rule = sl.classify_support(checks)
    assert label is SLB.UNDERSPECIFIED
    assert rule.name == "claim_ambiguous" and rule.check_ids == ("amb",)


def test_supported_requires_every_check_to_reach_a_verdict() -> None:
    label, rule = sl.classify_support([evidence(ST.PASS, "verbatim"), chk(CT.COMPARISON, ST.PASS)])
    assert label is SLB.SUPPORTED and rule.name == "all_checks_support"


def test_support_plus_an_undecided_check_is_only_partial() -> None:
    checks = [evidence(ST.PASS, "verbatim"), chk(CT.DATASET_STATISTIC, ST.ERROR)]
    label, rule = sl.classify_support(checks)
    assert label is SLB.PARTIALLY_SUPPORTED and rule.name == "some_checks_support"


def test_nothing_decided_is_unverifiable_never_contradicted() -> None:
    # The heart of the milestone: a checker that cannot decide has learned nothing
    # about the claim. Its ignorance is not evidence against the paper.
    label, rule = sl.classify_support([evidence(ST.INCONCLUSIVE, "partial_overlap")])
    assert label is SLB.UNVERIFIABLE_FROM_ARTIFACTS
    assert rule.name == "nothing_decided"


def test_an_absent_passage_alone_is_unverifiable_not_contradicted() -> None:
    label, _ = sl.classify_support([evidence(ST.FAIL, "absent")])
    assert label is SLB.UNVERIFIABLE_FROM_ARTIFACTS


# ---------------------------------------------------------------------------
# Reproduction status
# ---------------------------------------------------------------------------


def test_reading_a_table_cell_is_not_a_reproduction() -> None:
    checks = [evidence(ST.PASS, "verbatim"), chk(CT.TABLE_VALUE, ST.PASS, row="A")]
    status, rule = reproducibility.classify_reproduction(checks)
    assert status is RS.NOT_APPLICABLE and rule.name == "no_reproduction_channel"


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (ErrorKind.MISSING_CODE, RS.FAILED_MISSING_CODE),
        (ErrorKind.DANGLING_LINK, RS.FAILED_MISSING_CODE),
        (ErrorKind.EXECUTION_TIMEOUT, RS.FAILED_ENVIRONMENT),
        (ErrorKind.NONZERO_EXIT, RS.FAILED_ENVIRONMENT),
        (ErrorKind.SANDBOX_FAILURE, RS.FAILED_ENVIRONMENT),
    ],
)
def test_an_execution_error_is_a_reproduction_failure_not_a_mismatch(
    kind: ErrorKind, expected: ReproductionStatus
) -> None:
    checks = [chk(CT.CODE_EXECUTION, ST.ERROR, error_kind=kind.value)]
    status, rule = reproducibility.classify_reproduction(checks)
    assert status is expected and rule.name == "code_execution"


def test_an_unrecognised_execution_error_degrades_to_failed_environment() -> None:
    status, _ = reproducibility.classify_reproduction([chk(CT.CODE_EXECUTION, ST.ERROR)])
    assert status is RS.FAILED_ENVIRONMENT


def test_a_script_not_run_is_not_attempted() -> None:
    status, _ = reproducibility.classify_reproduction([chk(CT.CODE_EXECUTION, ST.SKIPPED)])
    assert status is RS.NOT_ATTEMPTED


def test_a_script_that_omits_the_declared_output_is_a_numeric_mismatch() -> None:
    status, _ = reproducibility.classify_reproduction([chk(CT.CODE_EXECUTION, ST.FAIL)])
    assert status is RS.FAILED_NUMERIC_MISMATCH


def test_exact_and_approximate_reproduction_are_distinguished() -> None:
    passing = chk(CT.CODE_EXECUTION, ST.PASS, declared_expectations=["accuracy=0.80"])
    exact = [passing, chk(CT.NUMERIC_TOLERANCE, ST.PASS, difference=0.0)]
    assert reproducibility.classify_reproduction(exact)[0] is RS.REPRODUCED

    near = [passing, chk(CT.NUMERIC_TOLERANCE, ST.PASS, difference=0.004)]
    status, rule = reproducibility.classify_reproduction(near)
    assert status is RS.APPROXIMATELY_REPRODUCED and "off by 0.004" in rule.because

    wrong = [passing, chk(CT.NUMERIC_TOLERANCE, ST.FAIL, difference=5.0)]
    assert reproducibility.classify_reproduction(wrong)[0] is RS.FAILED_NUMERIC_MISMATCH


def test_a_script_with_nothing_to_compare_against_reproduces_nothing() -> None:
    bare = [chk(CT.CODE_EXECUTION, ST.PASS, declared_expectations=[])]
    status, rule = reproducibility.classify_reproduction(bare)
    assert status is RS.NOT_ATTEMPTED
    assert "declared anything to compare its output against" in rule.because

    declared = [chk(CT.CODE_EXECUTION, ST.PASS, declared_expectations=["gc_content=0.50"])]
    assert reproducibility.classify_reproduction(declared)[0] is RS.REPRODUCED


@pytest.mark.parametrize(
    "kind", [ErrorKind.MISSING_DATA, ErrorKind.UNREADABLE_DATA, ErrorKind.DANGLING_LINK]
)
def test_a_dataset_error_is_failed_missing_data(kind: ErrorKind) -> None:
    checks = [chk(CT.DATASET_STATISTIC, ST.ERROR, error_kind=kind.value)]
    status, rule = reproducibility.classify_reproduction(checks)
    assert status is RS.FAILED_MISSING_DATA and rule.name == "dataset_recomputation"


def test_dataset_recomputation_statuses() -> None:
    assert (
        reproducibility.classify_reproduction([chk(CT.DATASET_STATISTIC, ST.FAIL)])[0]
        is RS.FAILED_NUMERIC_MISMATCH
    )
    assert (
        reproducibility.classify_reproduction([chk(CT.DATASET_STATISTIC, ST.SKIPPED)])[0]
        is RS.NOT_ATTEMPTED
    )
    exact = [chk(CT.DATASET_STATISTIC, ST.PASS, difference=0.0)]
    assert reproducibility.classify_reproduction(exact)[0] is RS.REPRODUCED
    near = [chk(CT.DATASET_STATISTIC, ST.PASS, difference=0.01)]
    assert reproducibility.classify_reproduction(near)[0] is RS.APPROXIMATELY_REPRODUCED


def test_a_passing_check_with_no_recorded_difference_counts_as_approximate() -> None:
    # The conservative direction: `approximately_reproduced` claims less.
    checks = [chk(CT.DATASET_STATISTIC, ST.PASS, difference=None)]
    assert reproducibility.classify_reproduction(checks)[0] is RS.APPROXIMATELY_REPRODUCED


def test_when_both_channels_run_the_worst_one_wins() -> None:
    # A script that reproduced does not excuse a dataset that went missing.
    checks = [
        chk(CT.CODE_EXECUTION, ST.PASS, declared_expectations=["x"]),
        chk(CT.NUMERIC_TOLERANCE, ST.PASS, difference=0.0),
        chk(CT.DATASET_STATISTIC, ST.ERROR, error_kind=ErrorKind.MISSING_DATA.value),
    ]
    status, rule = reproducibility.classify_reproduction(checks)
    assert status is RS.FAILED_MISSING_DATA
    # The channel that produced the winning status is the one that explains it.
    assert rule.name == "dataset_recomputation"


def test_worst_orders_by_severity_and_treats_no_channel_as_not_applicable() -> None:
    assert reproducibility.worst([]) is RS.NOT_APPLICABLE
    assert reproducibility.worst([RS.REPRODUCED, RS.NOT_ATTEMPTED]) is RS.NOT_ATTEMPTED
    assert (
        reproducibility.worst([RS.FAILED_NUMERIC_MISMATCH, RS.FAILED_ENVIRONMENT])
        is RS.FAILED_ENVIRONMENT
    )
    assert set(reproducibility.SEVERITY) == set(RS) - {RS.NOT_APPLICABLE}


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("check_type", "expected"),
    [
        (CT.TABLE_VALUE, FM.TABLE_CELL_MISMATCH),
        (CT.DATASET_STATISTIC, FM.STATISTIC_MISMATCH),
        (CT.NUMERIC_TOLERANCE, FM.NUMERIC_OUT_OF_TOLERANCE),
        (CT.COMPARISON, FM.NUMERIC_OUT_OF_TOLERANCE),
        (CT.CODE_EXECUTION, FM.OTHER),
    ],
)
def test_a_refuting_check_names_its_failure_mode(
    check_type: CheckType, expected: FailureMode
) -> None:
    mode, _ = failure_modes.classify_failure(
        [chk(check_type, ST.FAIL)], SLB.CONTRADICTED, RS.NOT_APPLICABLE
    )
    assert mode is expected


def test_a_negating_passage_is_passage_does_not_assert() -> None:
    mode, _ = failure_modes.classify_failure(
        [evidence(ST.FAIL, "polarity_mismatch")], SLB.CONTRADICTED, RS.NOT_APPLICABLE
    )
    assert mode is FM.PASSAGE_DOES_NOT_ASSERT


def test_an_undecidable_passage_is_not_a_passage_that_does_not_assert() -> None:
    # The distinction `FailureMode.EVIDENCE_UNDECIDABLE` was added to express. Reporting
    # `passage_does_not_assert` here would publish the checker's ignorance as a fact
    # about the paper.
    mode, rule = failure_modes.classify_failure(
        [evidence(ST.INCONCLUSIVE, "partial_overlap", coverage=0.4, missing_tokens=["only"])],
        SLB.UNVERIFIABLE_FROM_ARTIFACTS,
        RS.NOT_APPLICABLE,
    )
    assert mode is FM.EVIDENCE_UNDECIDABLE
    assert mode is not FM.PASSAGE_DOES_NOT_ASSERT
    assert rule.name == "cause:evidence_undecidable"


def test_a_silent_passage_does_not_assert_the_claim() -> None:
    mode, _ = failure_modes.classify_failure(
        [evidence(ST.FAIL, "absent")], SLB.UNVERIFIABLE_FROM_ARTIFACTS, RS.NOT_APPLICABLE
    )
    assert mode is FM.PASSAGE_DOES_NOT_ASSERT


def test_no_passage_linked_is_a_missing_evidence_link() -> None:
    mode, _ = failure_modes.classify_failure(
        [evidence(ST.SKIPPED)], SLB.UNVERIFIABLE_FROM_ARTIFACTS, RS.NOT_APPLICABLE
    )
    assert mode is FM.MISSING_EVIDENCE_LINK


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (ErrorKind.DANGLING_LINK, FM.MISSING_EVIDENCE_LINK),
        (ErrorKind.MISSING_DATA, FM.MISSING_DATA),
        (ErrorKind.UNREADABLE_DATA, FM.MISSING_DATA),
        (ErrorKind.MISSING_CODE, FM.MISSING_CODE),
        (ErrorKind.EXECUTION_TIMEOUT, FM.EXECUTION_TIMEOUT),
        (ErrorKind.NONZERO_EXIT, FM.EXECUTION_ERROR),
        (ErrorKind.SANDBOX_FAILURE, FM.EXECUTION_ERROR),
        (ErrorKind.MISSING_COLUMN, FM.OTHER),
    ],
)
def test_an_errored_check_maps_its_error_kind_onto_a_failure_mode(
    kind: ErrorKind, expected: FailureMode
) -> None:
    checks = [chk(CT.DATASET_STATISTIC, ST.ERROR, error_kind=kind.value)]
    mode, _ = failure_modes.classify_failure(checks, SLB.PARTIALLY_SUPPORTED, RS.NOT_APPLICABLE)
    assert mode is expected


def test_ambiguity_is_underspecification() -> None:
    checks = [chk(CT.TABLE_VALUE, ST.PASS, row_named=False, n_rows=2)]
    mode, _ = failure_modes.classify_failure(checks, SLB.UNDERSPECIFIED, RS.NOT_APPLICABLE)
    assert mode is FM.UNDERSPECIFIED


def test_the_most_concrete_refutation_wins_and_the_rest_survive_as_context() -> None:
    checks = [
        evidence(ST.INCONCLUSIVE, "partial_overlap"),
        chk(CT.TABLE_VALUE, ST.FAIL, check_id="tv"),
    ]
    mode, rule = failure_modes.classify_failure(checks, SLB.CONTRADICTED, RS.NOT_APPLICABLE)
    assert mode is FM.TABLE_CELL_MISMATCH
    assert "evidence_undecidable" in rule.because  # the other cause is named, not dropped
    assert set(rule.check_ids) == {"c.evidence_presence.1", "tv"}


def test_causes_lists_every_reason_not_just_the_winner() -> None:
    checks = [
        evidence(ST.INCONCLUSIVE, "partial_overlap"),
        chk(CT.TABLE_VALUE, ST.FAIL),
        chk(CT.DATASET_STATISTIC, ST.ERROR, error_kind=ErrorKind.MISSING_DATA.value),
    ]
    modes = [cause.mode for cause in failure_modes.causes(checks)]
    assert modes == [FM.EVIDENCE_UNDECIDABLE, FM.TABLE_CELL_MISMATCH, FM.MISSING_DATA]


def test_a_clean_verdict_has_no_failure_mode() -> None:
    checks = [evidence(ST.PASS, "verbatim"), chk(CT.DATASET_STATISTIC, ST.PASS, difference=0.0)]
    mode, rule = failure_modes.classify_failure(checks, SLB.SUPPORTED, RS.REPRODUCED)
    assert mode is FM.NONE and rule.name == "clean"


def test_a_supported_claim_whose_computation_failed_still_reports_the_failure() -> None:
    checks = [
        evidence(ST.PASS, "verbatim"),
        chk(CT.CODE_EXECUTION, ST.ERROR, error_kind=ErrorKind.EXECUTION_TIMEOUT.value),
    ]
    mode, _ = failure_modes.classify_failure(checks, SLB.SUPPORTED, RS.FAILED_ENVIRONMENT)
    assert mode is FM.EXECUTION_TIMEOUT


def test_a_skipped_check_is_a_limitation_not_a_failure() -> None:
    # `--no-execute`, or a claim that states no value: nothing was attempted, so
    # nothing broke. The reproduction status carries `not_attempted` instead.
    checks = [evidence(ST.PASS, "verbatim"), chk(CT.CODE_EXECUTION, ST.SKIPPED)]
    mode, rule = failure_modes.classify_failure(checks, SLB.PARTIALLY_SUPPORTED, RS.NOT_ATTEMPTED)
    assert mode is FM.NONE and rule.name == "no_failure_named"


def test_mode_priority_covers_every_mode_a_cause_can_produce() -> None:
    assert set(failure_modes.MODE_PRIORITY) == set(FM) - {FM.NONE}


def test_limitations_are_derived_from_checks_and_name_the_sandbox_caveat() -> None:
    checks = [
        evidence(ST.INCONCLUSIVE, "partial_overlap"),
        chk(CT.CODE_EXECUTION, ST.PASS, declared_expectations=["x"]),
    ]
    stated = failure_modes.limitations(checks)
    assert any(line.startswith("evidence_presence:") for line in stated)
    assert any("not a security boundary" in line for line in stated)


def test_a_clean_code_claim_still_carries_the_sandbox_limitation() -> None:
    # True of the verdict whether or not the verdict was favourable.
    checks = [chk(CT.CODE_EXECUTION, ST.PASS, declared_expectations=["x"])]
    assert any("not a security boundary" in line for line in failure_modes.limitations(checks))


# ---------------------------------------------------------------------------
# The assembled result and its trace
# ---------------------------------------------------------------------------


def test_score_populates_the_result_and_its_audit_fields() -> None:
    _, claim, scored = verify("contradicted_f1")
    result = scored.result
    assert result.claim_id == "c_contradicted_f1"
    assert scored.verdict == (SLB.CONTRADICTED, RS.NOT_APPLICABLE, FM.TABLE_CELL_MISMATCH)
    assert result.confidence == 1.0
    assert [link.target_id for link in result.evidence_passages] == ["p_claim"]
    assert len(result.computed_checks) == 2
    assert result.trace_path is None  # nothing written without --out
    assert "is contradicted by the supplied artifacts" in (result.human_readable_summary or "")
    assert claim.claim_id == result.claim_id


def test_the_summary_sentence_reads_as_english_for_every_label() -> None:
    # "is unverifiable_from_artifacts by the supplied artifacts" is not a sentence.
    assert set(V._VERDICT_PHRASE) == set(SLB)
    _, _, scored = verify("synthetic_data_passage")
    assert "cannot be verified from the supplied artifacts" in (
        scored.result.human_readable_summary or ""
    )


def test_the_trace_holds_every_stage_in_order() -> None:
    _, claim, scored = verify("contradicted_f1")
    trace = V.build_trace(scored, claim, run_id="r", task_id="t", bundle_id="b")
    kinds = [event.kind for event in trace.events]
    assert kinds == [
        "scoring.claim",
        "scoring.evidence",
        "scoring.check",
        "scoring.check",
        "scoring.support",
        "scoring.reproduction",
        "scoring.failure",
        "scoring.result",
    ]
    assert set(kinds) <= set(V.SCORING_EVENT_KINDS)
    assert trace.schema_version == "1.2"
    assert [event.seq for event in trace.events] == list(range(len(trace.events)))


def test_the_trace_records_the_rule_that_produced_each_inference() -> None:
    _, claim, scored = verify("underspecified_split")
    trace = V.build_trace(scored, claim, run_id="r")
    events = {event.kind: event for event in trace.events}
    support = events["scoring.support"]
    assert support.data["support_label"] == "underspecified"
    assert support.data["rule"] == "claim_ambiguous"
    assert support.data["check_ids"] == [scored.result.computed_checks[1].check_id]
    assert events["scoring.failure"].data["failure_mode"] == "underspecified"
    assert events["scoring.reproduction"].data["rule"] == "no_reproduction_channel"


def test_two_runs_of_one_task_produce_byte_identical_traces() -> None:
    def render(name: str) -> str:
        _, claim, scored = verify(name)
        return V.build_trace(scored, claim, run_id=name, task_id=name).to_jsonl()

    # Includes a task whose script actually executes, so the sandbox cannot leak a
    # temp path or a duration into the record.
    assert render("recompute_accuracy") == render("recompute_accuracy")
    assert render("dataset_mean") == render("dataset_mean")


def test_result_to_dict_carries_the_rules_signals_and_causes() -> None:
    _, _, scored = verify("contradicted_f1")
    payload = V.result_to_dict(scored, task_id="contradicted_f1")
    assert payload["task_id"] == "contradicted_f1"
    assert payload["rules"]["support"]["rule"] == "artifacts_refute"
    assert [s["signal"] for s in payload["signals"]] == ["supports", "refutes"]
    assert payload["causes"][0]["failure_mode"] == "table_cell_mismatch"
    json.dumps(payload)  # JSON-ready, no enums left behind


# ---------------------------------------------------------------------------
# Integration: the committed fixtures, verdict by verdict
# ---------------------------------------------------------------------------

EXPECTED_VERDICTS = {
    "accuracy_improvement": (SLB.SUPPORTED, RS.NOT_APPLICABLE, FM.NONE),
    "contradicted_f1": (SLB.CONTRADICTED, RS.NOT_APPLICABLE, FM.TABLE_CELL_MISMATCH),
    "dataset_mean": (SLB.SUPPORTED, RS.REPRODUCED, FM.NONE),
    # Recomputation refutes the claimed mean: contradiction through the dataset
    # channel, where `contradicted_f1` reaches it through a table cell.
    "dataset_mean_overstated": (
        SLB.CONTRADICTED,
        RS.FAILED_NUMERIC_MISMATCH,
        FM.STATISTIC_MISMATCH,
    ),
    # pstdev = 1.1298967…, inside the ±0.05 the claim's one decimal place admits but
    # not on it: the one fixture separating `reproduced` from its approximate cousin.
    "dataset_std": (SLB.SUPPORTED, RS.APPROXIMATELY_REPRODUCED, FM.NONE),
    "gc_content": (SLB.SUPPORTED, RS.REPRODUCED, FM.NONE),
    # The passage carries every token of the claim and negates it.
    "negated_training_data": (
        SLB.CONTRADICTED,
        RS.NOT_APPLICABLE,
        FM.PASSAGE_DOES_NOT_ASSERT,
    ),
    "recompute_accuracy": (SLB.SUPPORTED, RS.REPRODUCED, FM.NONE),
    "synthetic_data_passage": (
        SLB.UNVERIFIABLE_FROM_ARTIFACTS,
        RS.NOT_APPLICABLE,
        FM.EVIDENCE_UNDECIDABLE,
    ),
    "underspecified_split": (SLB.UNDERSPECIFIED, RS.NOT_APPLICABLE, FM.UNDERSPECIFIED),
    # The script will not run, so nothing is learned about its number. The text still
    # supports the claim, and a script that cannot run refutes nothing.
    "unreproducible_accuracy": (
        SLB.PARTIALLY_SUPPORTED,
        RS.FAILED_ENVIRONMENT,
        FM.EXECUTION_ERROR,
    ),
}


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_every_fixture_scores_to_its_pinned_verdict(name: str) -> None:
    _, _, scored = verify(name)
    assert scored.verdict == EXPECTED_VERDICTS[name]


def test_the_contradiction_fixture_keeps_both_channels_visible() -> None:
    # The paper's own sentence asserts the claim; its table refutes it. A verdict that
    # hid either fact would destroy the only interesting thing about the claim.
    _, _, scored = verify("contradicted_f1")
    by_type = {s.check_type: s for s in scored.signals}
    assert by_type[CT.EVIDENCE_PRESENCE].signal is Signal.SUPPORTS
    assert by_type[CT.TABLE_VALUE].signal is Signal.REFUTES
    assert scored.result.support_label is SLB.CONTRADICTED


def test_the_paraphrase_fixture_declines_to_decide_rather_than_guessing() -> None:
    _, _, scored = verify("synthetic_data_passage")
    assert scored.result.support_label is SLB.UNVERIFIABLE_FROM_ARTIFACTS
    assert scored.result.support_label is not SLB.CONTRADICTED
    assert scored.result.failure_mode is FM.EVIDENCE_UNDECIDABLE
    assert scored.result.confidence == 0.0  # nothing was decided, and it says so
    assert scored.result.limitations


def test_no_execute_reports_not_attempted_rather_than_a_failure() -> None:
    _, _, scored = verify("gc_content", execute=False)
    assert scored.result.reproduction_status is RS.NOT_ATTEMPTED
    assert scored.result.failure_mode is FM.NONE  # nothing was attempted, so nothing broke
    assert scored.result.support_label is SLB.PARTIALLY_SUPPORTED


def test_verify_writes_a_result_and_a_trace(tmp_path: Path) -> None:
    task, _, scored = verify("dataset_mean", out_dir=tmp_path)
    result_path = tmp_path / "dataset_mean.result.json"
    trace_path = tmp_path / "dataset_mean.trace.jsonl"
    assert result_path.is_file() and trace_path.is_file()
    assert scored.result.trace_path == str(trace_path)

    payload = json.loads(result_path.read_text())
    assert payload["result"]["support_label"] == "supported"
    events = read_trace(trace_path)
    assert events[0]["kind"] == "scoring.claim"
    assert events[-1]["data"]["confidence"] == 1.0
    assert task.spec.task_id == "dataset_mean"


def test_a_missing_task_raises_rather_than_scoring_nothing() -> None:
    with pytest.raises((loader.TaskLoadError, OSError)):
        V.verify_task(TASKS_DIR / "nope.yaml", repo_root=REPO_ROOT)


# ---------------------------------------------------------------------------
# Aggregate summary
# ---------------------------------------------------------------------------


def outcome(task_id: str, predicted: SupportLabel, gold: SupportLabel) -> summary.TaskOutcome:
    return summary.TaskOutcome(
        task_id=task_id,
        claim_id=f"c_{task_id}",
        predicted_support=predicted,
        predicted_reproduction=RS.NOT_APPLICABLE,
        predicted_failure=FM.NONE,
        gold_support=gold,
        gold_reproduction=RS.NOT_APPLICABLE,
        gold_failure=FM.NONE,
    )


def test_declining_to_decide_is_a_conservative_miss_not_a_wrong_verdict() -> None:
    shy = outcome("shy", SLB.UNVERIFIABLE_FROM_ARTIFACTS, SLB.SUPPORTED)
    assert shy.is_conservative_miss and not shy.is_wrong_verdict


def test_asserting_a_label_gold_disagrees_with_is_a_wrong_verdict() -> None:
    for predicted in (SLB.SUPPORTED, SLB.UNDERSPECIFIED, SLB.PARTIALLY_SUPPORTED):
        wrong = outcome("wrong", predicted, SLB.CONTRADICTED)
        assert wrong.is_wrong_verdict and not wrong.is_conservative_miss


def test_an_agreement_is_neither_kind_of_miss() -> None:
    hit = outcome("hit", SLB.SUPPORTED, SLB.SUPPORTED)
    assert not hit.is_wrong_verdict and not hit.is_conservative_miss


def test_declining_where_gold_also_declines_is_an_agreement() -> None:
    both = outcome("both", SLB.UNVERIFIABLE_FROM_ARTIFACTS, SLB.UNVERIFIABLE_FROM_ARTIFACTS)
    assert both.support_matches and not both.is_conservative_miss


def test_summary_counts_and_agreement() -> None:
    result = summary.summarize(
        [
            outcome("a", SLB.SUPPORTED, SLB.SUPPORTED),
            outcome("b", SLB.CONTRADICTED, SLB.CONTRADICTED),
            outcome("c", SLB.UNVERIFIABLE_FROM_ARTIFACTS, SLB.SUPPORTED),
            outcome("d", SLB.SUPPORTED, SLB.CONTRADICTED),
        ]
    )
    assert result.n_tasks == 4
    assert result.support_agreement == 2
    assert result.reproduction_agreement == 4 and result.failure_agreement == 4
    assert result.conservative_misses == ("c",)
    assert result.wrong_verdicts == ("d",)
    # Counts are sorted by value, so the record is stable.
    assert list(result.support_counts) == [
        "contradicted",
        "supported",
        "unverifiable_from_artifacts",
    ]
    assert result.support_counts["supported"] == 2

    rendered = summary.render_summary(result)
    assert "[MISS] d" in rendered and "[shy ] c" in rendered
    json.dumps(summary.summary_to_dict(result))


def test_the_committed_fixtures_produce_no_wrong_verdicts() -> None:
    # The number to watch. A change that raises label accuracy by turning a
    # conservative miss into a wrong verdict has made the tool worse.
    outcomes = []
    for name in sorted(FIXTURES):
        task, _, scored = verify(name)
        outcomes.append(V.outcome_of(task, scored))
    result = summary.summarize(outcomes)
    n = len(FIXTURES)

    assert result.n_tasks == n
    assert result.wrong_verdicts == ()
    assert result.conservative_misses == ("synthetic_data_passage",)
    assert result.support_agreement == n - 1
    assert result.reproduction_agreement == n
    assert result.failure_agreement == n - 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def task_arg(name: str) -> str:
    return str(TASKS_DIR / FIXTURES[name])


def test_cli_verify_prints_the_five_audit_channels(capsys) -> None:
    assert cli.main(["verify", "--task", task_arg("contradicted_f1")]) == 0
    out = capsys.readouterr().out
    for heading in ("Supporting text", "Computed checks", "Inference", "Unverifiable"):
        assert heading in out
    assert "support_label       : contradicted" in out
    assert "Task gold       : contradicted [ok ]" in out


def test_cli_verify_exits_zero_on_a_contradicted_claim(capsys) -> None:
    # Finding a contradiction is the tool working, not failing.
    assert cli.main(["verify", "--task", task_arg("contradicted_f1")]) == 0
    capsys.readouterr()


def test_cli_verify_exits_one_on_an_unloadable_task(capsys) -> None:
    assert cli.main(["verify", "--task", str(TASKS_DIR / "nope.yaml")]) == 1
    assert "could not load task" in capsys.readouterr().err


def test_cli_verify_json_is_parseable(capsys) -> None:
    assert cli.main(["verify", "--task", task_arg("dataset_mean"), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["result"]["reproduction_status"] == "reproduced"
    assert "summary" not in payload  # a single task needs no aggregate


def test_cli_verify_summarizes_several_tasks(capsys) -> None:
    argv = ["verify", "--task", task_arg("dataset_mean"), "--task", task_arg("contradicted_f1")]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "aggregate summary" in out and "Tasks scored        : 2" in out

    assert cli.main([*argv, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["n_tasks"] == 2
    assert payload["summary"]["wrong_verdicts"] == []


def test_cli_verify_writes_artifacts_and_a_summary(tmp_path: Path, capsys) -> None:
    argv = [
        "verify",
        "--task", task_arg("dataset_mean"),
        "--task", task_arg("underspecified_split"),
        "--out", str(tmp_path),
    ]
    assert cli.main(argv) == 0
    capsys.readouterr()
    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == [
        "dataset_mean.result.json",
        "dataset_mean.trace.jsonl",
        "summary.json",
        "underspecified_split.result.json",
        "underspecified_split.trace.jsonl",
    ]
    aggregate = json.loads((tmp_path / "summary.json").read_text())
    assert aggregate["gold_agreement"]["support_label"] == 2


def test_cli_verify_no_execute_does_not_run_the_script(capsys) -> None:
    assert cli.main(["verify", "--task", task_arg("gc_content"), "--no-execute"]) == 0
    out = capsys.readouterr().out
    assert "reproduction_status : not_attempted" in out


def test_verify_module_entry_point(capsys) -> None:
    assert V.main(["--task", task_arg("accuracy_improvement")]) == 0
    assert "support_label       : supported" in capsys.readouterr().out


def test_cli_help_advertises_verify(capsys) -> None:
    assert cli.main([]) == 0
    assert "verify" in capsys.readouterr().out
