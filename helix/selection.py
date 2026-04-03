"""Parse and validate master-driven branch selection."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from helix.models import BranchSelection
from helix.runs import get_node_by_number, is_dead_end

BRAINSTORM_SELECTION_FILE = "brainstorm_selection.md"

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


class BrainstormSelectionError(ValueError):
    """Raised when the staged brainstorm selection is missing or invalid."""


def get_brainstorm_selection_path(workspace: Path) -> Path:
    return workspace / ".helix" / BRAINSTORM_SELECTION_FILE


def parse_brainstorm_selection(path: Path) -> tuple[BranchSelection, str]:
    """Parse the staged brainstorm file into a selection and markdown body."""
    if not path.exists():
        raise BrainstormSelectionError(f"Staged brainstorm file not found: {path}")
    return parse_brainstorm_selection_text(path.read_text(), source=str(path))


def parse_brainstorm_selection_text(text: str, source: str = "brainstorm output") -> tuple[BranchSelection, str]:
    """Parse front matter and body from staged brainstorm markdown."""
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        raise BrainstormSelectionError(
            f"{source} must start with YAML front matter delimited by '---'"
        )

    raw_header, body = match.groups()
    try:
        data = yaml.safe_load(raw_header)
    except yaml.YAMLError as exc:
        raise BrainstormSelectionError(f"Invalid YAML in {source}: {exc}") from exc

    if not isinstance(data, dict):
        raise BrainstormSelectionError(f"YAML header in {source} must be a mapping")

    try:
        selection = BranchSelection.model_validate(data)
    except ValidationError as exc:
        raise BrainstormSelectionError(_format_validation_error(exc, source)) from exc

    body = body.strip()
    if not body:
        raise BrainstormSelectionError(f"{source} must include an idea writeup after the YAML header")

    return selection, body


def validate_branch_selection(selection: BranchSelection, nodes: list) -> None:
    """Validate a parsed selection against the current research tree."""
    if selection.mode == "top_level":
        return

    assert selection.parent is not None
    parent = get_node_by_number(nodes, selection.parent)
    if parent is None:
        raise BrainstormSelectionError(f"Selected parent '{selection.parent}' does not exist in tree_search.md")
    if is_dead_end(parent):
        raise BrainstormSelectionError(f"Selected parent '{selection.parent}' is marked [dead-end]")


def _format_validation_error(exc: ValidationError, source: str) -> str:
    problems = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        problems.append(f"{location}: {error['msg']}")
    details = "; ".join(problems)
    return f"Invalid selection header in {source}: {details}"
