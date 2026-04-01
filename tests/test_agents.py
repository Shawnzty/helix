"""Tests for helix/agents.py."""

from unittest.mock import MagicMock, patch

from helix.agents import build_command, spawn_agent
from helix.config import AgentConfig


def _master_agent():
    return AgentConfig(
        name="master", role="master", cli="claude",
        model="claude-opus-4.6",
        full_access_flag="--dangerously-skip-permissions",
    )


def _researcher_agent():
    return AgentConfig(
        name="researcher", role="researcher", cli="codex",
        model="gpt-5.4",
        full_access_flag="--dangerously-bypass-approvals-and-sandbox",
        reasoning_level="high",
    )


class TestBuildCommand:
    def test_claude_command(self, tmp_path):
        ctx = tmp_path / "context.md"
        ctx.write_text("test context")
        cmd = build_command(_master_agent(), ctx)
        assert cmd[0] == "claude"
        assert "--dangerously-skip-permissions" in cmd
        assert "-p" in cmd
        assert "test context" in cmd

    def test_codex_command(self, tmp_path):
        ctx = tmp_path / "context.md"
        ctx.write_text("test context")
        cmd = build_command(_researcher_agent(), ctx)
        assert cmd[0] == "codex"
        assert cmd[1] == "exec"  # non-interactive subcommand
        assert "--dangerously-bypass-approvals-and-sandbox" in cmd
        # codex takes prompt as positional arg (no flag)
        assert "-q" not in cmd
        assert cmd[-1] == "test context"


class TestSpawnAgent:
    @patch("helix.agents.subprocess.Popen")
    def test_successful_run(self, mock_popen_cls, tmp_path):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("output", "")
        mock_proc.returncode = 0
        mock_popen_cls.return_value = mock_proc

        ctx = tmp_path / "context.md"
        ctx.write_text("test")
        log_dir = tmp_path / "logs"

        result = spawn_agent(_master_agent(), ctx, log_dir)
        assert result.exit_code == 0
        assert result.stdout == "output"
        assert (log_dir / "stdout.log").read_text() == "output"

    @patch("helix.agents.subprocess.Popen")
    def test_nonzero_exit(self, mock_popen_cls, tmp_path):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "error msg")
        mock_proc.returncode = 1
        mock_popen_cls.return_value = mock_proc

        ctx = tmp_path / "context.md"
        ctx.write_text("test")
        log_dir = tmp_path / "logs"

        result = spawn_agent(_master_agent(), ctx, log_dir)
        assert result.exit_code == 1
        assert result.stderr == "error msg"

    @patch("helix.agents.subprocess.Popen")
    def test_timeout_sigterm(self, mock_popen_cls, tmp_path):
        import subprocess

        mock_proc = MagicMock()
        # First communicate raises timeout, second succeeds after SIGTERM
        mock_proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="test", timeout=1),
            ("partial", "timed out"),
        ]
        mock_proc.returncode = -15
        mock_popen_cls.return_value = mock_proc

        ctx = tmp_path / "context.md"
        ctx.write_text("test")
        log_dir = tmp_path / "logs"

        result = spawn_agent(_master_agent(), ctx, log_dir, timeout=1)
        mock_proc.send_signal.assert_called_once()
        assert result.stdout == "partial"
