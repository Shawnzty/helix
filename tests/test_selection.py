"""Tests for helix/selection.py."""

import pytest

from helix.runs import parse_tree_search
from helix.selection import (
    BrainstormSelectionError,
    parse_brainstorm_selection_text,
    validate_branch_selection,
)


SAMPLE_TREE = """# Research Tree

1. [dead-end] Old idea
   idea: test
   result: test
   reflect: test

2. [active] Better branch
   idea: test
   result: test
   reflect: test
"""


def _selection_text(header: str, body: str = "# Idea\nTry this next.\n") -> str:
    return f"---\n{header}---\n\n{body}"


class TestParseBrainstormSelection:
    def test_valid_child_selection(self):
        selection, body = parse_brainstorm_selection_text(
            _selection_text(
                'mode: child\nparent: "2"\ntitle: "Tune the active branch"\nrationale: "Promising"\n'
            )
        )
        assert selection.mode == "child"
        assert selection.parent == "2"
        assert "Try this next" in body

    def test_valid_top_level_selection(self):
        selection, body = parse_brainstorm_selection_text(
            _selection_text('mode: top_level\ntitle: "Start fresh"\n')
        )
        assert selection.mode == "top_level"
        assert selection.parent is None
        assert body.startswith("# Idea")

    def test_missing_yaml_header(self):
        with pytest.raises(BrainstormSelectionError, match="must start with YAML front matter"):
            parse_brainstorm_selection_text("# Idea\nNo front matter")

    def test_malformed_yaml(self):
        with pytest.raises(BrainstormSelectionError, match="Invalid YAML"):
            parse_brainstorm_selection_text(_selection_text("mode: [child\n"))


class TestValidateBranchSelection:
    def test_nonexistent_parent(self, tmp_path):
        (tmp_path / "tree_search.md").write_text(SAMPLE_TREE)
        nodes = parse_tree_search(tmp_path)
        selection, _ = parse_brainstorm_selection_text(
            _selection_text('mode: child\nparent: "9"\ntitle: "Missing parent"\n')
        )
        with pytest.raises(BrainstormSelectionError, match="does not exist"):
            validate_branch_selection(selection, nodes)

    def test_dead_end_parent_rejected(self, tmp_path):
        (tmp_path / "tree_search.md").write_text(SAMPLE_TREE)
        nodes = parse_tree_search(tmp_path)
        selection, _ = parse_brainstorm_selection_text(
            _selection_text('mode: child\nparent: "1"\ntitle: "Retry dead end"\n')
        )
        with pytest.raises(BrainstormSelectionError, match="marked \\[dead-end\\]"):
            validate_branch_selection(selection, nodes)
