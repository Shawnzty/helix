"""Tests for helix/models.py."""

import pytest

from helix.models import BranchSelection, RunState, SetupDraft, TreeNode, WorkspaceAudit, WorkspaceFileAudit


class TestRunState:
    def test_id_to_tree_number(self):
        assert RunState.id_to_tree_number("2_1_1") == "2.1.1"
        assert RunState.id_to_tree_number("3") == "3"

    def test_tree_number_to_id(self):
        assert RunState.tree_number_to_id("2.1.1") == "2_1_1"
        assert RunState.tree_number_to_id("3") == "3"

    def test_parent_from_id(self):
        assert RunState.parent_from_id("2_1_1") == "2_1"
        assert RunState.parent_from_id("2_1") == "2"
        assert RunState.parent_from_id("2") is None

    def test_round_trip(self):
        tree_num = "3.2.1"
        run_id = RunState.tree_number_to_id(tree_num)
        assert RunState.id_to_tree_number(run_id) == tree_num


class TestTreeNode:
    def test_basic_node(self):
        node = TreeNode(number="1", status="active", title="Test", depth=0)
        assert node.number == "1"
        assert node.children == []


class TestBranchSelection:
    def test_child_requires_parent(self):
        with pytest.raises(ValueError, match="requires a parent"):
            BranchSelection(mode="child", title="Test")

    def test_top_level_forbids_parent(self):
        with pytest.raises(ValueError, match="must not include a parent"):
            BranchSelection(mode="top_level", parent="1", title="Test")

    def test_valid_child_selection(self):
        selection = BranchSelection(mode="child", parent="2.1", title="Tune warmup")
        assert selection.parent == "2.1"


class TestWorkspaceAudit:
    def test_initialized_requires_all_core_files_valid(self):
        audit = WorkspaceAudit(files=[
            WorkspaceFileAudit(path="goal.md", required=True, status="valid"),
            WorkspaceFileAudit(path="master_agent.md", required=True, status="valid"),
            WorkspaceFileAudit(path="researcher_agent.md", required=True, status="valid"),
            WorkspaceFileAudit(path="helix.toml", required=True, status="valid"),
            WorkspaceFileAudit(path="tree_search.md", required=True, status="valid"),
        ])
        assert audit.is_initialized() is True

    def test_missing_core_file_breaks_initialization(self):
        audit = WorkspaceAudit(files=[
            WorkspaceFileAudit(path="goal.md", required=True, status="valid"),
            WorkspaceFileAudit(path="master_agent.md", required=True, status="missing"),
        ])
        assert audit.is_initialized() is False


class TestSetupDraft:
    def test_follow_up_requires_questions(self):
        with pytest.raises(ValueError, match="follow-up questions are required"):
            SetupDraft(summary="Need more info", needs_follow_up=True)

    def test_complete_draft_requires_files(self):
        with pytest.raises(ValueError, match="missing required files"):
            SetupDraft(summary="Incomplete", needs_follow_up=False)

    def test_valid_complete_draft(self):
        draft = SetupDraft(
            summary="Done",
            goal_md="# Goal",
            master_agent_md="# Master",
            researcher_agent_md="# Researcher",
        )
        assert draft.needs_follow_up is False
