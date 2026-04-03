"""Tests for helix/loop.py."""

from unittest.mock import patch

from helix.config import AgentConfig, GlobalConfig, WorkspaceConfig
from helix.loop import HelixLoop
from helix.models import AgentRun


def _setup_workspace(tmp_path, with_instructions: bool = True):
    """Create a minimal workspace for loop testing."""
    (tmp_path / "goal.md").write_text(
        "# Goal\n"
        "Test goal\n\n"
        "## Success Criteria\n\n"
        "```yaml\n"
        "all:\n"
        "  - metric: val\n"
        "    op: \"<\"\n"
        "    value: 0.5\n"
        "```\n"
    )
    (tmp_path / "tree_search.md").write_text("# Research Tree\n\n")
    (tmp_path / ".helix").mkdir(exist_ok=True)
    if with_instructions:
        (tmp_path / "master_agent.md").write_text("# Master Instructions\nGuide the research.")
        (tmp_path / "researcher_agent.md").write_text("# Researcher Instructions\nExecute carefully.")
    return tmp_path


def _configs():
    global_cfg = GlobalConfig(defaults={"agent_timeout_seconds": 60})
    workspace_cfg = WorkspaceConfig(agents=[
        AgentConfig(name="master", role="master", cli="claude"),
        AgentConfig(name="researcher", role="researcher", cli="codex"),
    ])
    return global_cfg, workspace_cfg


def _write_brainstorm_selection(workspace, header: str, body: str = "# Idea\nTry X\n"):
    path = workspace / ".helix" / "brainstorm_selection.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{header}---\n\n{body}")


class TestHelixLoop:
    @patch("helix.loop.spawn_agent")
    def test_single_run(self, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path)
        global_cfg, workspace_cfg = _configs()

        def side_effect(agent, ctx, log_dir, timeout=3600):
            if agent.role == "master" and ctx.name == "context_brainstorm.md":
                log_dir.mkdir(parents=True, exist_ok=True)
                (log_dir / "stdout.log").write_text("brainstorm")
                _write_brainstorm_selection(ws, 'mode: top_level\ntitle: "Try X"\n')
            elif agent.role == "researcher" and ctx.name == "context_execute_plan.md":
                run_dir = ws / "runs" / "1"
                (run_dir / "plan.md").write_text("# Plan\nDo X")
            elif agent.role == "researcher" and ctx.name == "context_execute_run.md":
                run_dir = ws / "runs" / "1"
                (run_dir / "results.md").write_text('# Results\n```json\n{"val": 1.0}\n```\n')
            elif agent.role == "master" and ctx.name == "context_reflect.md":
                run_dir = ws / "runs" / "1"
                (run_dir / "reflect.md").write_text("# Reflect\nX worked")
            return AgentRun(stdout="ok", stderr="", exit_code=0, duration_seconds=1.0)

        mock_spawn.side_effect = side_effect

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=1)

        assert mock_spawn.call_count == 4
        assert not (ws / "CLAUDE.md").exists()
        assert not (ws / "AGENTS.md").exists()
        assert (ws / "runs" / "1" / "idea.md").exists()
        assert (ws / "runs" / "1" / "idea.md").read_text().startswith("---\nmode: top_level")
        assert (ws / "runs" / "1" / "logs" / "brainstorm" / "stdout.log").read_text() == "brainstorm"

    @patch("helix.loop.spawn_agent")
    def test_stop_file(self, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path)
        global_cfg, workspace_cfg = _configs()

        (ws / ".helix" / "stop").write_text("stop")

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=10)

        mock_spawn.assert_not_called()

    @patch("helix.loop.spawn_agent")
    def test_agent_crash_continues(self, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path)
        global_cfg, workspace_cfg = _configs()
        brainstorm_calls = 0

        def side_effect(agent, ctx, log_dir, timeout=3600):
            nonlocal brainstorm_calls
            if agent.role == "master" and ctx.name == "context_brainstorm.md":
                brainstorm_calls += 1
                if brainstorm_calls == 1:
                    raise RuntimeError("Agent crashed")
                _write_brainstorm_selection(ws, 'mode: top_level\ntitle: "Retry after crash"\n')
            elif agent.role == "researcher" and ctx.name == "context_execute_plan.md":
                run_dir = ws / "runs" / "1"
                (run_dir / "plan.md").write_text("# Plan\nRetry")
            elif agent.role == "researcher" and ctx.name == "context_execute_run.md":
                run_dir = ws / "runs" / "1"
                (run_dir / "results.md").write_text('# Results\n```json\n{"val": 1.0}\n```\n')
            elif agent.role == "master" and ctx.name == "context_reflect.md":
                (ws / "runs" / "1" / "reflect.md").write_text("# Reflect\nRecovered")
            return AgentRun(stdout="ok", stderr="", exit_code=0, duration_seconds=1.0)

        mock_spawn.side_effect = side_effect

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=2)

        assert brainstorm_calls == 2
        assert mock_spawn.call_count == 5
        assert (ws / "runs" / "1" / "reflect.md").exists()

    @patch("helix.loop.spawn_agent")
    def test_missing_results_marks_failed(self, mock_spawn, tmp_path):
        """When results.md is never written, the run should be marked as incomplete."""
        ws = _setup_workspace(tmp_path)
        global_cfg, workspace_cfg = _configs()

        def side_effect(agent, ctx, log_dir, timeout=3600):
            if agent.role == "master" and ctx.name == "context_brainstorm.md":
                _write_brainstorm_selection(ws, 'mode: top_level\ntitle: "Try X"\n')
            elif agent.role == "researcher" and ctx.name == "context_execute_plan.md":
                run_dir = ws / "runs" / "1"
                (run_dir / "plan.md").write_text("# Plan\nDo X")
            elif agent.role == "master" and ctx.name == "context_reflect.md":
                (ws / "runs" / "1" / "reflect.md").write_text("# Reflect\nNo results")
            return AgentRun(stdout="ok", stderr="", exit_code=0, duration_seconds=1.0)

        mock_spawn.side_effect = side_effect

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=1)

        assert "1" in loop._failed_run_ids
        assert mock_spawn.call_count == 4

    @patch("helix.loop.spawn_agent")
    def test_pending_tree_node_marks_failed(self, mock_spawn, tmp_path):
        """When tree_search.md still shows (pending) after reflect, mark as incomplete."""
        ws = _setup_workspace(tmp_path)
        (ws / "tree_search.md").write_text(
            "# Research Tree\n\n"
            "1. [active] Test idea\n"
            "   idea: baseline\n"
            "   result: val 1.0\n"
            "   reflect: worth exploring\n"
        )
        global_cfg, workspace_cfg = _configs()

        def side_effect(agent, ctx, log_dir, timeout=3600):
            if agent.role == "master" and ctx.name == "context_brainstorm.md":
                _write_brainstorm_selection(ws, 'mode: child\nparent: "1"\ntitle: "Child idea"\n')
            elif agent.role == "researcher" and ctx.name == "context_execute_plan.md":
                run_dir = ws / "runs" / "1_1"
                (run_dir / "plan.md").write_text("# Plan\nDo child run")
            elif agent.role == "researcher" and ctx.name == "context_execute_run.md":
                run_dir = ws / "runs" / "1_1"
                (run_dir / "results.md").write_text('# Results\n```json\n{"val": 1.0}\n```\n')
            elif agent.role == "master" and ctx.name == "context_reflect.md":
                (ws / "runs" / "1_1" / "reflect.md").write_text("# Reflect\nStill pending")
                (ws / "tree_search.md").write_text(
                    "# Research Tree\n\n"
                    "1. [active] Test idea\n"
                    "   idea: baseline\n"
                    "   result: val 1.0\n"
                    "   reflect: worth exploring\n\n"
                    "  1.1. [frontier] Child idea\n"
                    "       idea: follow up on baseline\n"
                    "       result: (pending)\n"
                    "       reflect: (pending)\n"
                )
            return AgentRun(stdout="ok", stderr="", exit_code=0, duration_seconds=1.0)

        mock_spawn.side_effect = side_effect

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=1)

        assert "1_1" in loop._failed_run_ids

    @patch("helix.loop.spawn_agent")
    def test_missing_plan_skips_run_and_still_reflects(self, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path)
        global_cfg, workspace_cfg = _configs()

        def side_effect(agent, ctx, log_dir, timeout=3600):
            if agent.role == "master" and ctx.name == "context_brainstorm.md":
                _write_brainstorm_selection(ws, 'mode: top_level\ntitle: "Try X"\n')
            elif agent.role == "researcher" and ctx.name == "context_execute_plan.md":
                pass
            elif agent.role == "researcher" and ctx.name == "context_execute_run.md":
                assert False, "Execute Run should be skipped when plan.md is missing"
            elif agent.role == "master" and ctx.name == "context_reflect.md":
                (ws / "runs" / "1" / "reflect.md").write_text("# Reflect\nPlan missing")
            return AgentRun(stdout="ok", stderr="", exit_code=0, duration_seconds=1.0)

        mock_spawn.side_effect = side_effect

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=1)

        assert "1" in loop._failed_run_ids
        assert mock_spawn.call_count == 3
        assert (ws / "runs" / "1" / "reflect.md").exists()

    @patch("helix.loop.spawn_agent")
    def test_nonzero_plan_exit_marks_failed_and_still_reflects(self, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path)
        global_cfg, workspace_cfg = _configs()

        def side_effect(agent, ctx, log_dir, timeout=3600):
            if agent.role == "master" and ctx.name == "context_brainstorm.md":
                _write_brainstorm_selection(ws, 'mode: top_level\ntitle: "Try X"\n')
                return AgentRun(stdout="ok", stderr="", exit_code=0, duration_seconds=1.0)
            if agent.role == "researcher" and ctx.name == "context_execute_plan.md":
                (ws / "runs" / "1" / "plan.md").write_text("# Plan\nBroken")
                return AgentRun(stdout="", stderr="plan failed", exit_code=1, duration_seconds=1.0)
            if agent.role == "researcher" and ctx.name == "context_execute_run.md":
                assert False, "Execute Run should be skipped when plan exits nonzero"
            if agent.role == "master" and ctx.name == "context_reflect.md":
                (ws / "runs" / "1" / "reflect.md").write_text("# Reflect\nPlan failed")
            return AgentRun(stdout="ok", stderr="", exit_code=0, duration_seconds=1.0)

        mock_spawn.side_effect = side_effect

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=1)

        assert "1" in loop._failed_run_ids
        assert mock_spawn.call_count == 3
        assert (ws / "runs" / "1" / "reflect.md").exists()

    @patch("helix.loop.spawn_agent")
    def test_missing_master_agent_file_fails_before_spawning(self, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path, with_instructions=False)
        (ws / "researcher_agent.md").write_text("# Researcher Instructions\nExecute carefully.")
        global_cfg, workspace_cfg = _configs()

        loop = HelixLoop(ws, global_cfg, workspace_cfg)

        try:
            loop.run(max_runs=1)
            assert False, "Expected FileNotFoundError"
        except FileNotFoundError as exc:
            assert str(ws / "master_agent.md") in str(exc)

        mock_spawn.assert_not_called()
        assert not (ws / "runs").exists()

    @patch("helix.loop.spawn_agent")
    def test_missing_researcher_agent_file_fails_before_spawning(self, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path, with_instructions=False)
        (ws / "master_agent.md").write_text("# Master Instructions\nGuide the research.")
        global_cfg, workspace_cfg = _configs()

        loop = HelixLoop(ws, global_cfg, workspace_cfg)

        try:
            loop.run(max_runs=1)
            assert False, "Expected FileNotFoundError"
        except FileNotFoundError as exc:
            assert str(ws / "researcher_agent.md") in str(exc)

        mock_spawn.assert_not_called()
        assert not (ws / "runs").exists()

    @patch("helix.loop.spawn_agent")
    def test_run_does_not_overwrite_root_agent_docs(self, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path)
        (ws / "CLAUDE.md").write_text("human claude")
        (ws / "AGENTS.md").write_text("human agents")
        global_cfg, workspace_cfg = _configs()

        def side_effect(agent, ctx, log_dir, timeout=3600):
            if agent.role == "master" and ctx.name == "context_brainstorm.md":
                _write_brainstorm_selection(ws, 'mode: top_level\ntitle: "Try X"\n')
            elif agent.role == "researcher" and ctx.name == "context_execute_plan.md":
                run_dir = ws / "runs" / "1"
                (run_dir / "plan.md").write_text("# Plan\nDo X")
            elif agent.role == "researcher" and ctx.name == "context_execute_run.md":
                run_dir = ws / "runs" / "1"
                (run_dir / "results.md").write_text('# Results\n```json\n{"val": 1.0}\n```\n')
            elif agent.role == "master" and ctx.name == "context_reflect.md":
                (ws / "runs" / "1" / "reflect.md").write_text("# Reflect\nX worked")
            return AgentRun(stdout="ok", stderr="", exit_code=0, duration_seconds=1.0)

        mock_spawn.side_effect = side_effect

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=1)

        assert (ws / "CLAUDE.md").read_text() == "human claude"
        assert (ws / "AGENTS.md").read_text() == "human agents"

    @patch("helix.loop.spawn_agent")
    def test_success_after_execute_runs_reflect_then_stops(self, mock_spawn, tmp_path, capsys):
        ws = _setup_workspace(tmp_path)
        global_cfg, workspace_cfg = _configs()

        def side_effect(agent, ctx, log_dir, timeout=3600):
            if agent.role == "master" and ctx.name == "context_brainstorm.md":
                _write_brainstorm_selection(ws, 'mode: top_level\ntitle: "Try X"\n')
            elif agent.role == "researcher" and ctx.name == "context_execute_plan.md":
                run_dir = ws / "runs" / "1"
                (run_dir / "plan.md").write_text("# Plan\nDo X")
            elif agent.role == "researcher" and ctx.name == "context_execute_run.md":
                run_dir = ws / "runs" / "1"
                (run_dir / "results.md").write_text('# Results\n```json\n{"val": 0.1}\n```\n')
            elif agent.role == "master" and ctx.name == "context_reflect.md":
                (ws / "runs" / "1" / "reflect.md").write_text("# Reflect\nGoal met")
            return AgentRun(stdout="ok", stderr="", exit_code=0, duration_seconds=1.0)

        mock_spawn.side_effect = side_effect

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=5)

        output = capsys.readouterr().out
        assert mock_spawn.call_count == 4
        assert "Success check: All success criteria satisfied." in output
        assert "Success criteria met" in output

    @patch("helix.loop.spawn_agent")
    def test_invalid_criteria_abort_before_any_agent_spawn(self, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path)
        (ws / "goal.md").write_text(
            "# Goal\n"
            "Test goal\n\n"
            "## Success Criteria\n\n"
            "```yaml\n"
            "all:\n"
            "  - metric: val\n"
            "    op: approx\n"
            "    value: 0.5\n"
            "```\n"
        )
        global_cfg, workspace_cfg = _configs()

        loop = HelixLoop(ws, global_cfg, workspace_cfg)

        try:
            loop.run(max_runs=1)
            assert False, "Expected ValueError"
        except ValueError as exc:
            assert "unsupported operator" in str(exc)

        mock_spawn.assert_not_called()

    @patch("helix.loop.spawn_agent")
    def test_master_selects_child_branch_and_assigns_next_child_id(self, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path)
        (ws / "tree_search.md").write_text(
            "# Research Tree\n\n"
            "2. [active] Parent branch\n"
            "   idea: baseline\n"
            "   result: val 0.9\n"
            "   reflect: promising\n\n"
            "  2.1. [active] Deeper branch\n"
            "       idea: tune schedule\n"
            "       result: val 0.8\n"
            "       reflect: keep exploring\n\n"
            "    2.1.1. [dead-end] Old child\n"
            "           idea: test a bad variant\n"
            "           result: val 1.2\n"
            "           reflect: not worth it\n"
        )
        global_cfg, workspace_cfg = _configs()

        def side_effect(agent, ctx, log_dir, timeout=3600):
            if agent.role == "master" and ctx.name == "context_brainstorm.md":
                _write_brainstorm_selection(ws, 'mode: child\nparent: "2.1"\ntitle: "Next child"\n')
            elif agent.role == "researcher" and ctx.name == "context_execute_plan.md":
                run_dir = ws / "runs" / "2_1_2"
                (run_dir / "plan.md").write_text("# Plan\nExplore child")
            elif agent.role == "researcher" and ctx.name == "context_execute_run.md":
                run_dir = ws / "runs" / "2_1_2"
                (run_dir / "results.md").write_text('# Results\n```json\n{"val": 0.8}\n```\n')
            elif agent.role == "master" and ctx.name == "context_reflect.md":
                (ws / "runs" / "2_1_2" / "reflect.md").write_text("# Reflect\nChild explored")
            return AgentRun(stdout="ok", stderr="", exit_code=0, duration_seconds=1.0)

        mock_spawn.side_effect = side_effect

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=1)

        assert (ws / "runs" / "2_1_2" / "idea.md").exists()
        assert not (ws / "runs" / "2_1_1" / "idea.md").exists()

    @patch("helix.loop.spawn_agent")
    def test_master_selects_new_top_level_branch_and_assigns_next_root_id(self, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path)
        (ws / "tree_search.md").write_text(
            "# Research Tree\n\n"
            "1. [frontier] Existing frontier\n"
            "   idea: (pending)\n"
            "   result: (pending)\n"
            "   reflect: (pending)\n\n"
            "2. [active] Strong branch\n"
            "   idea: keep improving\n"
            "   result: val 0.8\n"
            "   reflect: promising\n"
        )
        global_cfg, workspace_cfg = _configs()

        def side_effect(agent, ctx, log_dir, timeout=3600):
            if agent.role == "master" and ctx.name == "context_brainstorm.md":
                _write_brainstorm_selection(ws, 'mode: top_level\ntitle: "Fresh direction"\n')
            elif agent.role == "researcher" and ctx.name == "context_execute_plan.md":
                run_dir = ws / "runs" / "3"
                (run_dir / "plan.md").write_text("# Plan\nTry a fresh direction")
            elif agent.role == "researcher" and ctx.name == "context_execute_run.md":
                run_dir = ws / "runs" / "3"
                (run_dir / "results.md").write_text('# Results\n```json\n{"val": 0.8}\n```\n')
            elif agent.role == "master" and ctx.name == "context_reflect.md":
                (ws / "runs" / "3" / "reflect.md").write_text("# Reflect\nFresh branch complete")
            return AgentRun(stdout="ok", stderr="", exit_code=0, duration_seconds=1.0)

        mock_spawn.side_effect = side_effect

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=1)

        assert (ws / "runs" / "3" / "idea.md").exists()
        assert not (ws / "runs" / "1" / "idea.md").exists()

    @patch("helix.loop.spawn_agent")
    def test_invalid_selection_aborts_before_execute(self, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path)
        global_cfg, workspace_cfg = _configs()

        def side_effect(agent, ctx, log_dir, timeout=3600):
            if agent.role == "master" and ctx.name == "context_brainstorm.md":
                path = ws / ".helix" / "brainstorm_selection.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# Idea\nMissing header")
            return AgentRun(stdout="ok", stderr="", exit_code=0, duration_seconds=1.0)

        mock_spawn.side_effect = side_effect

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=1)

        assert mock_spawn.call_count == 1
        assert not (ws / "runs").exists()

    @patch("helix.loop.spawn_agent")
    def test_selection_uses_master_output_not_first_frontier_node(self, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path)
        (ws / "tree_search.md").write_text(
            "# Research Tree\n\n"
            "1. [frontier] First frontier\n"
            "   idea: (pending)\n"
            "   result: (pending)\n"
            "   reflect: (pending)\n\n"
            "2. [active] Better parent\n"
            "   idea: stronger baseline\n"
            "   result: val 0.8\n"
            "   reflect: keep exploring\n"
        )
        global_cfg, workspace_cfg = _configs()

        def side_effect(agent, ctx, log_dir, timeout=3600):
            if agent.role == "master" and ctx.name == "context_brainstorm.md":
                _write_brainstorm_selection(ws, 'mode: child\nparent: "2"\ntitle: "Follow the better parent"\n')
            elif agent.role == "researcher" and ctx.name == "context_execute_plan.md":
                run_dir = ws / "runs" / "2_1"
                (run_dir / "plan.md").write_text("# Plan\nFollow parent 2")
            elif agent.role == "researcher" and ctx.name == "context_execute_run.md":
                run_dir = ws / "runs" / "2_1"
                (run_dir / "results.md").write_text('# Results\n```json\n{"val": 0.8}\n```\n')
            elif agent.role == "master" and ctx.name == "context_reflect.md":
                (ws / "runs" / "2_1" / "reflect.md").write_text("# Reflect\nParent 2 selected")
            return AgentRun(stdout="ok", stderr="", exit_code=0, duration_seconds=1.0)

        mock_spawn.side_effect = side_effect

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=1)

        assert (ws / "runs" / "2_1" / "idea.md").exists()
        assert not (ws / "runs" / "1" / "idea.md").exists()
