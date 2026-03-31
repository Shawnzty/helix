"""Tests for helix/loop.py."""

from unittest.mock import MagicMock, patch

from helix.config import AgentConfig, GlobalConfig, WorkspaceConfig
from helix.loop import HelixLoop
from helix.models import AgentRun


def _setup_workspace(tmp_path):
    """Create a minimal workspace for loop testing."""
    (tmp_path / "goal.md").write_text("# Goal\nTest goal")
    (tmp_path / "tree_search.md").write_text("# Research Tree\n\n")
    (tmp_path / ".helix").mkdir(exist_ok=True)
    return tmp_path


def _configs():
    global_cfg = GlobalConfig(defaults={"agent_timeout_seconds": 60})
    workspace_cfg = WorkspaceConfig(agents=[
        AgentConfig(name="master", role="master", cli="claude"),
        AgentConfig(name="researcher", role="researcher", cli="codex"),
    ])
    return global_cfg, workspace_cfg


class TestHelixLoop:
    @patch("helix.loop.spawn_agent")
    @patch("helix.loop.generate_agent_md")
    def test_single_run(self, mock_gen, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path)
        global_cfg, workspace_cfg = _configs()

        # Mock agent to write expected files
        def side_effect(agent, ctx, log_dir, timeout=3600):
            run_dir = ws / "runs" / "1"
            run_dir.mkdir(parents=True, exist_ok=True)
            if agent.role == "master" and "brainstorm" in str(ctx):
                (run_dir / "idea.md").write_text("# Idea\nTry X")
            elif agent.role == "researcher":
                (run_dir / "plan.md").write_text("# Plan\nDo X")
                (run_dir / "results.md").write_text('# Results\n```json\n{"val": 1.0}\n```\n')
            elif agent.role == "master" and "reflect" in str(ctx):
                (run_dir / "reflect.md").write_text("# Reflect\nX worked")
            return AgentRun(stdout="ok", stderr="", exit_code=0, duration_seconds=1.0)

        mock_spawn.side_effect = side_effect

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=1)

        assert mock_spawn.call_count == 3  # brainstorm + execute + reflect
        mock_gen.assert_called_once()

    @patch("helix.loop.spawn_agent")
    @patch("helix.loop.generate_agent_md")
    def test_stop_file(self, mock_gen, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path)
        global_cfg, workspace_cfg = _configs()

        # Create stop file before loop starts
        (ws / ".helix" / "stop").write_text("stop")

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=10)

        mock_spawn.assert_not_called()

    @patch("helix.loop.spawn_agent")
    @patch("helix.loop.generate_agent_md")
    def test_agent_crash_continues(self, mock_gen, mock_spawn, tmp_path):
        ws = _setup_workspace(tmp_path)
        global_cfg, workspace_cfg = _configs()

        # First brainstorm crashes, loop should continue to next iteration
        call_count = 0

        def side_effect(agent, ctx, log_dir, timeout=3600):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise RuntimeError("Agent crashed")
            run_dir = ws / "runs" / "1"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "idea.md").write_text("# Idea\nRetry")
            (run_dir / "results.md").write_text("# Results\nOk")
            (run_dir / "reflect.md").write_text("# Reflect\nOk")
            return AgentRun(stdout="ok", stderr="", exit_code=0, duration_seconds=1.0)

        mock_spawn.side_effect = side_effect

        loop = HelixLoop(ws, global_cfg, workspace_cfg)
        loop.run(max_runs=2)

        # First run crashed at brainstorm, second run should have completed
        assert call_count >= 2
