"""Tests for helix/models.py."""

from helix.models import RunState, TreeNode


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
