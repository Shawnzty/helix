"""Tests for helix/success.py."""

import pytest

from helix.success import SuccessCriteriaError, evaluate_success, parse_success_criteria


def _goal_with_criteria(criteria_block: str) -> str:
    return (
        "# Goal\n"
        "Optimize the system.\n\n"
        "## Success Criteria\n\n"
        "```yaml\n"
        f"{criteria_block}"
        "```\n"
    )


class TestParseSuccessCriteria:
    def test_parse_valid_all(self):
        criteria = parse_success_criteria(
            _goal_with_criteria(
                "all:\n"
                "  - metric: val_bpb\n"
                "    op: \"<\"\n"
                "    value: 1.05\n"
            )
        )
        assert criteria.mode == "all"
        assert criteria.criteria[0].metric == "val_bpb"

    def test_parse_valid_any(self):
        criteria = parse_success_criteria(
            _goal_with_criteria(
                "any:\n"
                "  - metric: accuracy\n"
                "    op: \">=\"\n"
                "    value: 0.95\n"
                "  - metric: pass_rate\n"
                "    op: \"==\"\n"
                "    value: true\n"
            )
        )
        assert criteria.mode == "any"
        assert len(criteria.criteria) == 2

    def test_missing_yaml_block(self):
        goal_text = (
            "# Goal\n"
            "Optimize the system.\n\n"
            "## Success Criteria\n\n"
            "val_bpb < 1.05\n"
        )
        with pytest.raises(SuccessCriteriaError, match="fenced YAML block"):
            parse_success_criteria(goal_text)

    def test_malformed_yaml(self):
        with pytest.raises(SuccessCriteriaError, match="Invalid YAML"):
            parse_success_criteria(
                _goal_with_criteria(
                    "all:\n"
                    "  - metric: val_bpb\n"
                    "    op: \"<\"\n"
                    "    value: [1.05\n"
                )
            )

    def test_unsupported_operator(self):
        with pytest.raises(SuccessCriteriaError, match="unsupported operator"):
            parse_success_criteria(
                _goal_with_criteria(
                    "all:\n"
                    "  - metric: val_bpb\n"
                    "    op: approx\n"
                    "    value: 1.05\n"
                )
            )


class TestEvaluateSuccess:
    def test_numeric_threshold_pass(self):
        criteria = parse_success_criteria(
            _goal_with_criteria(
                "all:\n"
                "  - metric: val_bpb\n"
                "    op: \"<\"\n"
                "    value: 1.05\n"
            )
        )
        evaluation = evaluate_success(criteria, {"val_bpb": 1.01})
        assert evaluation.passed is True
        assert evaluation.summary == "All success criteria satisfied."

    def test_numeric_threshold_fail(self):
        criteria = parse_success_criteria(
            _goal_with_criteria(
                "all:\n"
                "  - metric: val_bpb\n"
                "    op: \"<\"\n"
                "    value: 1.05\n"
            )
        )
        evaluation = evaluate_success(criteria, {"val_bpb": 1.10})
        assert evaluation.passed is False
        assert evaluation.missing_metrics == []
        assert "not satisfied" in evaluation.failed_conditions[0]

    def test_boolean_equality_pass(self):
        criteria = parse_success_criteria(
            _goal_with_criteria(
                "all:\n"
                "  - metric: tests_passed\n"
                "    op: \"==\"\n"
                "    value: true\n"
            )
        )
        evaluation = evaluate_success(criteria, {"tests_passed": True})
        assert evaluation.passed is True

    def test_string_equality_fail(self):
        criteria = parse_success_criteria(
            _goal_with_criteria(
                "all:\n"
                "  - metric: status\n"
                "    op: \"==\"\n"
                "    value: success\n"
            )
        )
        evaluation = evaluate_success(criteria, {"status": "failed"})
        assert evaluation.passed is False
        assert "status ==" in evaluation.failed_conditions[0]

    def test_missing_metric(self):
        criteria = parse_success_criteria(
            _goal_with_criteria(
                "all:\n"
                "  - metric: val_bpb\n"
                "    op: \"<\"\n"
                "    value: 1.05\n"
            )
        )
        evaluation = evaluate_success(criteria, {})
        assert evaluation.passed is False
        assert evaluation.missing_metrics == ["val_bpb"]
        assert "missing metrics" in evaluation.summary.lower()

    def test_wrong_type_for_numeric_comparison(self):
        criteria = parse_success_criteria(
            _goal_with_criteria(
                "all:\n"
                "  - metric: train_time_seconds\n"
                "    op: \"<=\"\n"
                "    value: 300\n"
            )
        )
        evaluation = evaluate_success(criteria, {"train_time_seconds": "fast"})
        assert evaluation.passed is False
        assert "numeric comparison" in evaluation.failed_conditions[0]
