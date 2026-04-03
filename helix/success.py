"""Parse and evaluate machine-checkable success criteria."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from helix.models import Criterion, SuccessCriteria, SuccessEvaluation

_SUCCESS_SECTION_RE = re.compile(
    r"^## Success Criteria\s*$\n(.*?)(?=^##\s|\Z)",
    re.MULTILINE | re.DOTALL,
)
_YAML_BLOCK_RE = re.compile(
    r"```(?:yaml|yml)\s*\n(.*?)\n```",
    re.DOTALL,
)


class SuccessCriteriaError(ValueError):
    """Raised when success criteria cannot be parsed or validated."""


def load_success_criteria(workspace: Path) -> SuccessCriteria:
    """Load and parse success criteria from workspace goal.md."""
    goal_path = workspace / "goal.md"
    if not goal_path.exists():
        raise SuccessCriteriaError(f"goal.md not found at {goal_path}")
    return parse_success_criteria(goal_path.read_text())


def parse_success_criteria(goal_text: str) -> SuccessCriteria:
    """Parse the fenced YAML block under the Success Criteria heading."""
    section_match = _SUCCESS_SECTION_RE.search(goal_text)
    if not section_match:
        raise SuccessCriteriaError("goal.md must contain a '## Success Criteria' section")

    section_text = section_match.group(1).strip()
    yaml_match = _YAML_BLOCK_RE.search(section_text)
    if not yaml_match:
        raise SuccessCriteriaError(
            "Success Criteria must include a fenced YAML block under '## Success Criteria'"
        )

    try:
        data = yaml.safe_load(yaml_match.group(1))
    except yaml.YAMLError as exc:
        raise SuccessCriteriaError(f"Invalid YAML in Success Criteria: {exc}") from exc

    if not isinstance(data, dict):
        raise SuccessCriteriaError("Success Criteria YAML must be a mapping")

    try:
        return SuccessCriteria.model_validate(data)
    except ValidationError as exc:
        raise SuccessCriteriaError(_format_validation_error(exc)) from exc


def evaluate_success(criteria: SuccessCriteria, metrics: dict[str, Any]) -> SuccessEvaluation:
    """Evaluate parsed success criteria against top-level JSON metrics."""
    passed_criteria: list[Criterion] = []
    failed_conditions: list[str] = []
    missing_metrics: list[str] = []

    for criterion in criteria.criteria:
        if criterion.metric not in metrics:
            missing_metrics.append(criterion.metric)
            continue

        actual = metrics[criterion.metric]
        passed, message = _evaluate_criterion(criterion, actual)
        if passed:
            passed_criteria.append(criterion)
        else:
            failed_conditions.append(message)

    if criteria.mode == "all":
        passed = len(passed_criteria) == len(criteria.criteria) and not missing_metrics
    else:
        passed = bool(passed_criteria)
        if passed:
            failed_conditions = []
            missing_metrics = []

    return SuccessEvaluation(
        passed=passed,
        failed_conditions=failed_conditions,
        missing_metrics=missing_metrics,
        summary=_build_summary(criteria.mode, passed, failed_conditions, missing_metrics),
    )


def _evaluate_criterion(criterion: Criterion, actual: Any) -> tuple[bool, str]:
    expected = criterion.value
    if criterion.op in {"<", "<=", ">", ">="}:
        if not _is_number(actual) or not _is_number(expected):
            return False, (
                f"{criterion.describe()} could not be evaluated as a numeric comparison "
                f"(actual: {actual!r})"
            )

        if criterion.op == "<":
            passed = actual < expected
        elif criterion.op == "<=":
            passed = actual <= expected
        elif criterion.op == ">":
            passed = actual > expected
        else:
            passed = actual >= expected
    else:
        if not _is_supported_equality_value(actual) or not _is_supported_equality_value(expected):
            return False, (
                f"{criterion.describe()} could not be evaluated as an equality comparison "
                f"(actual: {actual!r})"
            )

        if criterion.op == "==":
            passed = actual == expected
        else:
            passed = actual != expected

    if passed:
        return True, f"{criterion.describe()} satisfied (actual: {actual!r})"
    return False, f"{criterion.describe()} not satisfied (actual: {actual!r})"


def _build_summary(
    mode: str,
    passed: bool,
    failed_conditions: list[str],
    missing_metrics: list[str],
) -> str:
    if passed:
        if mode == "all":
            return "All success criteria satisfied."
        return "At least one success criterion satisfied."
    if missing_metrics:
        metrics_list = ", ".join(sorted(set(missing_metrics)))
        return f"Success criteria could not be fully evaluated; missing metrics: {metrics_list}."
    if failed_conditions:
        return "Success criteria were evaluated and not met."
    return "Success criteria were not met."


def _format_validation_error(exc: ValidationError) -> str:
    problems = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        problems.append(f"{location}: {error['msg']}")
    details = "; ".join(problems)
    return f"Invalid success criteria: {details}"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_supported_equality_value(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool))
