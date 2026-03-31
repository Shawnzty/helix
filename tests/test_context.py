"""Tests for helix/context.py."""

from helix.context import (
    build_brainstorm_context,
    build_execute_context,
    build_reflect_context,
    generate_agent_md,
)


def _setup_workspace(tmp_path):
    (tmp_path / "goal.md").write_text("# Goal\nOptimize val_bpb below 1.05")
    (tmp_path / "tree_search.md").write_text("# Research Tree\n\n1. [active] First run\n   idea: try X\n")
    run_dir = tmp_path / "runs" / "1"
    run_dir.mkdir(parents=True)
    (run_dir / "idea.md").write_text("# Idea\nTry approach X")
    (run_dir / "results.md").write_text("# Results\nval_bpb = 1.10")
    return tmp_path


class TestBuildBrainstormContext:
    def test_contains_goal_and_tree(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_brainstorm_context(ws, "2")
        content = path.read_text()
        assert "Optimize val_bpb" in content
        assert "Research Tree" in content
        assert "runs/2/idea.md" in content

    def test_creates_helix_dir(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_brainstorm_context(ws, "2")
        assert path.parent.name == ".helix"
        assert path.exists()


class TestBuildExecuteContext:
    def test_contains_idea_and_plan_instruction(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_execute_context(ws, "1")
        content = path.read_text()
        assert "Try approach X" in content
        assert "plan.md" in content
        assert "MANDATORY" in content

    def test_contains_goal(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_execute_context(ws, "1")
        content = path.read_text()
        assert "Optimize val_bpb" in content


class TestBuildReflectContext:
    def test_contains_results_and_tree(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_reflect_context(ws, "1")
        content = path.read_text()
        assert "val_bpb = 1.10" in content
        assert "Research Tree" in content
        assert "reflect.md" in content


class TestGenerateAgentMd:
    def test_creates_claude_and_agents_md(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        generate_agent_md(ws)
        assert (ws / "CLAUDE.md").exists()
        assert (ws / "AGENTS.md").exists()
        content = (ws / "CLAUDE.md").read_text()
        assert "Optimize val_bpb" in content
