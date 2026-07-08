"""Milestone 3 — rule-based claim extraction tests (CPU-only, offline).

Two layers:

1. **Unit tests** for each sub-extractor on small crafted inputs — these pin the
   *rules* (number parsing that ignores ``SST-2``, the from/to shape, the metric
   lexicon, dataset/entity/condition heuristics, the units rule, reference
   resolution, and the operator precedence), independently of any fixture.
2. **Integration tests** running the extractor over the real committed fixtures
   and scoring against each task's gold extraction target — including the one
   deliberate, documented miss (a free-form semantic condition a transparent rule
   set does not attempt to guess).
"""

from __future__ import annotations

from pathlib import Path

from scientific_claim_verifier import cli
from scientific_claim_verifier import schemas as S
from scientific_claim_verifier.artifacts import loader
from scientific_claim_verifier.claims import extraction, normalization
from scientific_claim_verifier.claims.extraction import RuleBasedClaimExtractor

REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = REPO_ROOT / "tasks"

Op = S.ComparisonOperator
CT = S.ClaimType


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


def test_extract_numbers_basic_and_percent() -> None:
    nums = extraction.extract_numbers("from 72.0 to 78.0 (that is 90% of the target)")
    assert [n.value for n in nums] == [72.0, 78.0, 90.0]
    assert nums[2].is_percent is True
    assert nums[0].is_percent is False


def test_extract_numbers_ignores_identifier_digits() -> None:
    # The "2" in SST-2, the "10" in CIFAR-10, and the "2" in eval2.py are part of
    # names, not standalone numbers. Only 78.0 is a number here.
    nums = extraction.extract_numbers("Method A hits 78.0 on SST-2 and CIFAR-10 via eval2.py")
    assert [n.value for n in nums] == [78.0]


def test_extract_numbers_handles_negative() -> None:
    nums = extraction.extract_numbers("the delta is -5 points")
    assert [n.value for n in nums] == [-5.0]


def test_find_from_to() -> None:
    assert extraction.find_from_to("improves from 72.0 to 78.0") == (72.0, 78.0)
    assert extraction.find_from_to("accuracy is 90%") == (None, None)


def test_detect_count() -> None:
    nums = extraction.extract_numbers("12 samples with a mean value of 3.4")
    assert extraction.detect_count("12 samples with a mean value of 3.4", nums) == 12
    nums2 = extraction.extract_numbers("a mean value of 3.4")
    assert extraction.detect_count("a mean value of 3.4", nums2) is None


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_metric_lexicon_hits() -> None:
    assert extraction.extract_metrics("accuracy and F1 score improved") == ["accuracy", "f1"]
    assert extraction.extract_metrics("a GC content of 0.5") == ["gc_content"]
    assert extraction.extract_metrics("mean of the values") == ["mean"]


def test_metric_count_nouns_map_to_count() -> None:
    assert extraction.extract_metrics("120 samples") == ["count"]
    assert extraction.extract_metrics("the dataset has 30 instances") == ["count"]


def test_metric_lexicon_first_appearance_order() -> None:
    # "samples" (count) precedes "mean" in the text; order follows the text.
    assert extraction.extract_metrics("12 samples with a mean value") == ["count", "mean"]


def test_metric_word_boundaries() -> None:
    # "meaning" must not match the "mean" metric.
    assert extraction.extract_metrics("the meaning of the result") == []


# ---------------------------------------------------------------------------
# Datasets and entities
# ---------------------------------------------------------------------------


def test_extract_datasets_known_name_and_phrase() -> None:
    assert extraction.extract_datasets("evaluated on SST-2") == ["SST-2"]
    assert extraction.extract_datasets("the measurements dataset has 12 rows") == ["measurements"]


def test_extract_datasets_none_without_trigger() -> None:
    # "synthetic data" has no dataset/known-name trigger — do not guess a dataset.
    assert extraction.extract_datasets("trained only on synthetic data") == []


def test_extract_entities_method_and_roles() -> None:
    assert extraction.extract_entities("Method A beats the baseline") == ["Method A", "baseline"]
    assert extraction.extract_entities("the model is trained") == ["model"]


def test_extract_entities_conservative_on_lowercase_method() -> None:
    # A bare lowercase "the method" is not tagged as an entity.
    assert extraction.extract_entities("the method reaches 90% accuracy") == []


# ---------------------------------------------------------------------------
# Operator precedence
# ---------------------------------------------------------------------------


def test_operator_from_to_direction() -> None:
    assert extraction.detect_operator("from 72 to 78", CT.COMPARISON, 72.0, 78.0) is Op.GT
    assert extraction.detect_operator("from 78 to 72", CT.COMPARISON, 78.0, 72.0) is Op.LT


def test_operator_verbs() -> None:
    assert extraction.detect_operator("A improves over B", CT.COMPARISON, None, None) is Op.GT
    assert extraction.detect_operator("A reduces the error", CT.COMPARISON, None, None) is Op.LT


def test_operator_verbs_match_on_word_boundaries() -> None:
    # Substring matching would fire "gain" inside "against" and "drop" inside
    # "dropout". Neither is a comparison; a descriptive claim gets no operator.
    against = extraction.detect_operator("evaluated against a rival", CT.DESCRIPTIVE, None, None)
    dropout = extraction.detect_operator("trained with dropout", CT.DESCRIPTIVE, None, None)
    assert against is None
    assert dropout is None


def test_operator_from_to_overrides_verb() -> None:
    # The numbers win over the verb: "drops from 78 to 72" is still Y < X.
    op = extraction.detect_operator("accuracy drops from 78 to 72", CT.COMPARISON, 78.0, 72.0)
    assert op is Op.LT


def test_operator_claim_type_defaults() -> None:
    assert extraction.detect_operator("mean is 3.4", CT.DATASET, None, 3.4) is Op.APPROX
    assert extraction.detect_operator("prints 0.8", CT.CODE_REPRODUCTION, None, 0.8) is Op.APPROX
    assert extraction.detect_operator("accuracy is 90", CT.NUMERIC, None, 90.0) is Op.EQ
    plain = extraction.detect_operator("trained on synthetic data", CT.DESCRIPTIVE, None, None)
    assert plain is None


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


def test_units_percent_sign() -> None:
    assert extraction.extract_units("reaches 90% accuracy", ["accuracy"], 90.0) == "%"


def test_units_zero_to_hundred_scale_heuristic() -> None:
    # No "%" sign, but an accuracy value > 1 is read as a percentage.
    assert extraction.extract_units("accuracy from 72 to 78", ["accuracy"], 78.0) == "%"


def test_units_fraction_scale_has_no_percent() -> None:
    # accuracy 0.80 (0–1 scale) and gc_content 0.50 are unitless.
    assert extraction.extract_units("accuracy of 0.80", ["accuracy"], 0.80) is None
    assert extraction.extract_units("gc content of 0.50", ["gc_content"], 0.50) is None


# ---------------------------------------------------------------------------
# References + normalization
# ---------------------------------------------------------------------------


def test_extract_references_resolves_code_file() -> None:
    task = loader.load_task(TASKS_DIR / "code_reproduction" / "recompute_accuracy.yaml", REPO_ROOT)
    refs = extraction.extract_references(task.input_claim.claim_text, task.bundle)
    code_refs = [r for r in refs if r.kind is S.EvidenceKind.CODE]
    assert len(code_refs) == 1
    assert code_refs[0].mention == "compute_accuracy.py"
    assert code_refs[0].target_id == "code_accuracy"


def test_extract_references_table_mention_unresolved() -> None:
    bundle = S.ArtifactBundle(bundle_id="b")
    refs = extraction.extract_references("as shown in Table 1", bundle)
    assert any(r.kind is S.EvidenceKind.TABLE and r.target_id is None for r in refs)


def test_normalize_shapes() -> None:
    comp = S.ScientificClaim(
        claim_id="c", claim_text="x", claim_type=CT.COMPARISON,
        metrics=["accuracy"], baseline_value=72.0, expected_value=78.0,
        comparison_operator=Op.GT, units="%",
    )
    assert normalization.normalize(comp) == "accuracy: 72 -> 78 (>) %"

    single = S.ScientificClaim(
        claim_id="c", claim_text="x", claim_type=CT.DATASET,
        metrics=["count", "mean"], expected_value=3.4, comparison_operator=Op.APPROX,
    )
    assert normalization.normalize(single) == "mean ~ 3.4"

    descriptive = S.ScientificClaim(
        claim_id="c", claim_text="The model is trained only on synthetic data.",
        claim_type=CT.DESCRIPTIVE,
    )
    assert normalization.normalize(descriptive) == "the model is trained only on synthetic data"


# ---------------------------------------------------------------------------
# Extractor: purity + determinism
# ---------------------------------------------------------------------------


def test_extractor_does_not_mutate_input_claim() -> None:
    task = loader.load_task(TASKS_DIR / "table_claims" / "accuracy_improvement.yaml", REPO_ROOT)
    input_claim = task.input_claim
    RuleBasedClaimExtractor().extract(input_claim, task.bundle)
    # The input claim must remain the bare, gold-free object it started as.
    assert input_claim.expected_value is None
    assert input_claim.metrics == []
    assert input_claim.comparison_operator is None
    assert input_claim.normalized_claim is None


def test_extractor_is_deterministic() -> None:
    task = loader.load_task(TASKS_DIR / "table_claims" / "accuracy_improvement.yaml", REPO_ROOT)
    a = RuleBasedClaimExtractor().extract(task.input_claim, task.bundle)
    b = RuleBasedClaimExtractor().extract(task.input_claim, task.bundle)
    assert a.claim.model_dump() == b.claim.model_dump()
    assert a.rules_fired == b.rules_fired


# ---------------------------------------------------------------------------
# Integration over the committed fixtures + scoring
# ---------------------------------------------------------------------------


def _extract_all() -> dict[str, tuple[extraction.Extraction, loader.GoldClaim]]:
    out: dict[str, tuple[extraction.Extraction, loader.GoldClaim]] = {}
    extractor = RuleBasedClaimExtractor()
    for path in loader.discover_task_files(TASKS_DIR):
        task = loader.load_task(path, REPO_ROOT)
        out[task.spec.task_id] = (
            extractor.extract(task.input_claim, task.bundle),
            task.spec.expected.claim,
        )
    return out


def test_reliable_fields_match_gold_on_every_fixture() -> None:
    # The reliable channels (numbers, operator, metrics, datasets, units, and the
    # conservative entity lexicon) must match gold on ALL committed fixtures.
    reliable = ("expected_value", "baseline_value", "comparison_operator", "units",
                "metrics", "datasets", "entities")
    for task_id, (ext, gold) in _extract_all().items():
        score = extraction.score_extraction(ext.claim, gold)
        for name in reliable:
            assert score.fields[name], f"{task_id}: field {name} mismatch"


def test_aggregate_extraction_scores() -> None:
    scores = [extraction.score_extraction(ext.claim, gold) for ext, gold in _extract_all().values()]
    agg = extraction.aggregate_scores(scores)
    # Seven fields recovered on all six fixtures; conditions on five (see below).
    assert agg["expected_value"] == (6, 6)
    assert agg["comparison_operator"] == (6, 6)
    assert agg["metrics"] == (6, 6)
    assert agg["datasets"] == (6, 6)
    assert agg["units"] == (6, 6)
    assert agg["entities"] == (6, 6)
    assert agg["conditions"] == (5, 6)


def test_documented_condition_miss_is_the_semantic_one() -> None:
    # The single miss is the free-form semantic condition on the descriptive task;
    # a transparent rule set only recovers sample-count conditions. This is an
    # honest limitation, not a bug — see docs/EXTRACTION.md.
    ext, gold = _extract_all()["synthetic_data_passage"]
    score = extraction.score_extraction(ext.claim, gold)
    assert score.fields["conditions"] is False
    assert ext.claim.conditions == []
    assert gold.conditions == ["synthetic data only"]


def test_count_condition_recovered() -> None:
    ext, _ = _extract_all()["dataset_mean"]
    assert ext.claim.conditions == ["n = 12"]
    assert "count" in ext.claim.metrics


def test_comparison_fixture_full_extraction() -> None:
    ext, _ = _extract_all()["accuracy_improvement"]
    claim = ext.claim
    assert claim.baseline_value == 72.0
    assert claim.expected_value == 78.0
    assert claim.comparison_operator is Op.GT
    assert claim.units == "%"
    assert set(claim.metrics) == {"accuracy"}
    assert set(claim.datasets) == {"SST-2"}
    assert set(claim.entities) == {"Method A", "baseline"}


# ---------------------------------------------------------------------------
# CLI / script entry points
# ---------------------------------------------------------------------------


def test_cli_extract_claims_text_report(capsys) -> None:
    # The flag name follows the CLI contract in docs/PLAN.md §10.
    code = cli.main(
        ["extract-claims", "--task", str(TASKS_DIR / "statistical_claims" / "dataset_mean.yaml")]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "rule-based claim extraction" in out
    assert "mean ~ 3.4" in out
    assert "8/8 scored fields match" in out


def test_cli_extract_claims_json(capsys) -> None:
    code = cli.main(
        ["extract-claims", "--task", str(TASKS_DIR / "ml_claims" / "underspecified_split.yaml"),
         "--json"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert '"expected_value": 90.0' in out
    assert '"comparison_operator": "="' in out


def test_cli_extract_claims_writes_out_file(tmp_path, capsys) -> None:
    code = cli.main(
        ["extract-claims", "--task", str(TASKS_DIR / "bioinformatics_claims" / "gc_content.yaml"),
         "--out", str(tmp_path)]
    )
    capsys.readouterr()
    assert code == 0
    written = tmp_path / "gc_content.extraction.json"
    assert written.is_file()
    assert "gc_content" in written.read_text(encoding="utf-8")


def test_cli_extract_claims_missing_task_errors(capsys) -> None:
    code = cli.main(["extract-claims", "--task", str(TASKS_DIR / "does_not_exist.yaml")])
    err = capsys.readouterr().err
    assert code == 1
    assert "could not load task" in err


def test_script_run_cli_matches_contract_flags(tmp_path, capsys) -> None:
    # scripts/02_extract_claims.py delegates to extraction.main -> run_cli.
    code = extraction.main(
        ["--task", str(TASKS_DIR / "code_reproduction" / "recompute_accuracy.yaml"),
         "--out", str(tmp_path)]
    )
    capsys.readouterr()
    assert code == 0
    assert (tmp_path / "recompute_accuracy.extraction.json").is_file()
