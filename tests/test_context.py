"""Tests for helix/context.py."""

from helix.context import (
    build_brainstorm_context,
    build_execute_plan_context,
    build_execute_run_context,
    build_reflect_context,
)
from helix.models import SuccessEvaluation


def _setup_workspace(tmp_path):
    (tmp_path / "goal.md").write_text("# Goal\nOptimize val_bpb below 1.05")
    (tmp_path / "tree_search.md").write_text("# Research Tree\n\n1. [active] First run\n   idea: try X\n")
    (tmp_path / "master_agent.md").write_text("# Master Instructions\nThink strategically.")
    (tmp_path / "researcher_agent.md").write_text("# Researcher Instructions\nBe methodical.")
    run_dir = tmp_path / "runs" / "1"
    run_dir.mkdir(parents=True)
    (run_dir / "idea.md").write_text("# Idea\nTry approach X")
    (run_dir / "plan.md").write_text("# Plan\n1. Edit train.py\n2. Run evaluate.sh")
    (run_dir / "results.md").write_text("# Results\nval_bpb = 1.10")
    return tmp_path


class TestBuildBrainstormContext:
    def test_contains_goal_and_tree(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_brainstorm_context(ws)
        content = path.read_text()
        assert "Optimize val_bpb" in content
        assert "Research Tree" in content
        assert ".helix/brainstorm_selection.md" in content

    def test_includes_master_agent_instructions(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_brainstorm_context(ws)
        content = path.read_text()
        assert "## Human Agent Instructions" in content
        assert "# Master Instructions" in content
        assert "Think strategically." in content

    def test_creates_helix_dir(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_brainstorm_context(ws)
        assert path.parent.name == ".helix"
        assert path.exists()

    def test_mentions_web_search_as_optional(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_brainstorm_context(ws)
        content = path.read_text()
        assert "Web search" in content
        assert "optional" in content.lower()
        assert "Do **not** update `tree_search.md` during Brainstorm." in content
        assert "mode: child" in content
        assert "mode: top_level" in content

    def test_lists_reference_files_when_present(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        ref_dir = ws / "reference"
        ref_dir.mkdir()
        (ref_dir / "paper.pdf").write_text("fake pdf")
        (ref_dir / "notes.md").write_text("some notes")
        path = build_brainstorm_context(ws)
        content = path.read_text()
        assert "paper.pdf" in content
        assert "notes.md" in content
        assert "reference/" in content


class TestBuildExecutePlanContext:
    def test_contains_idea_and_goal(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_execute_plan_context(ws, "1")
        content = path.read_text()
        assert "Try approach X" in content
        assert "Optimize val_bpb" in content
        assert "plan.md" in content
        assert "Do **not** implement yet." in content

    def test_includes_researcher_agent_instructions(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_execute_plan_context(ws, "1")
        content = path.read_text()
        assert "## Human Agent Instructions" in content
        assert "# Researcher Instructions" in content
        assert "Be methodical." in content

    def test_writes_execute_plan_context_file(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_execute_plan_context(ws, "1")
        assert path.name == "context_execute_plan.md"


class TestBuildExecuteRunContext:
    def test_contains_plan_but_not_goal_or_idea(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_execute_run_context(ws, "1")
        content = path.read_text()
        assert "Edit train.py" in content
        assert "Run evaluate.sh" in content
        assert "Optimize val_bpb below 1.05" not in content
        assert "Try approach X" not in content
        assert "results.md" in content

    def test_includes_researcher_agent_instructions(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_execute_run_context(ws, "1")
        content = path.read_text()
        assert "## Human Agent Instructions" in content
        assert "# Researcher Instructions" in content
        assert "Be methodical." in content

    def test_writes_execute_run_context_file(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_execute_run_context(ws, "1")
        assert path.name == "context_execute_run.md"


class TestBuildReflectContext:
    def test_contains_goal_plan_results_and_tree(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_reflect_context(ws, "1")
        content = path.read_text()
        assert "Optimize val_bpb below 1.05" in content
        assert "Edit train.py" in content
        assert "val_bpb = 1.10" in content
        assert "Research Tree" in content
        assert "reflect.md" in content

    def test_includes_master_agent_instructions(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        path = build_reflect_context(ws, "1")
        content = path.read_text()
        assert "## Human Agent Instructions" in content
        assert "# Master Instructions" in content
        assert "Think strategically." in content

    def test_includes_success_check_summary(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        evaluation = SuccessEvaluation(
            passed=True,
            summary="All success criteria satisfied.",
        )
        path = build_reflect_context(ws, "1", success_evaluation=evaluation)
        content = path.read_text()
        assert "## Success Check" in content
        assert "All success criteria satisfied." in content
        assert "- Passed: yes" in content
