"""Tests for helix/agents.py."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from helix.agents import build_invocation, spawn_agent
from helix.config import AgentConfig


def _master_agent():
    return AgentConfig(
        name="master", role="master", cli="claude",
        model="claude-opus-4-6",
        full_access_flag="--dangerously-skip-permissions",
    )


def _researcher_agent():
    return AgentConfig(
        name="researcher", role="researcher", cli="codex",
        model="gpt-5.4",
        full_access_flag="--dangerously-bypass-approvals-and-sandbox",
        thinking_level="high",
    )


def _fallback_agent():
    return AgentConfig(
        name="fallback", role="researcher", cli="custom-cli",
        model="custom-model",
        full_access_flag="--allow-all",
    )


class TestBuildInvocation:
    def test_claude_uses_stdin_transport(self, tmp_path):
        ctx = tmp_path / "context.md"
        ctx.write_text("test context")
        invocation = build_invocation(_master_agent(), ctx)
        assert invocation.cmd[0] == "claude"
        assert "--dangerously-skip-permissions" in invocation.cmd
        assert "-p" in invocation.cmd
        assert "test context" not in invocation.cmd
        assert invocation.stdin_text == "test context"

    def test_claude_thinking_level_adds_effort_flag(self, tmp_path):
        ctx = tmp_path / "context.md"
        ctx.write_text("test context")
        agent = AgentConfig(
            name="master",
            role="master",
            cli="claude",
            model="claude-opus-4-6",
            full_access_flag="--dangerously-skip-permissions",
            thinking_level="high",
        )
        invocation = build_invocation(agent, ctx)
        assert "--effort" in invocation.cmd
        assert "high" in invocation.cmd

    def test_claude_thinking_level_none_adds_no_effort_flag(self, tmp_path):
        ctx = tmp_path / "context.md"
        ctx.write_text("test context")
        agent = AgentConfig(
            name="master",
            role="master",
            cli="claude",
            model="claude-opus-4-6",
            full_access_flag="--dangerously-skip-permissions",
            thinking_level="none",
        )
        invocation = build_invocation(agent, ctx)
        assert "--effort" not in invocation.cmd

    def test_codex_uses_stdin_transport(self, tmp_path):
        ctx = tmp_path / "context.md"
        ctx.write_text("test context")
        invocation = build_invocation(_researcher_agent(), ctx)
        assert invocation.cmd[0] == "codex"
        assert invocation.cmd[1] == "exec"
        assert "--dangerously-bypass-approvals-and-sandbox" in invocation.cmd
        assert invocation.cmd[-1] == "-"
        assert "test context" not in invocation.cmd
        assert invocation.stdin_text == "test context"

    def test_codex_thinking_level_adds_config_override(self, tmp_path):
        ctx = tmp_path / "context.md"
        ctx.write_text("test context")
        invocation = build_invocation(_researcher_agent(), ctx)
        assert "--effort" not in invocation.cmd
        assert "-c" in invocation.cmd
        assert 'model_reasoning_effort="high"' in invocation.cmd

    def test_codex_xhigh_adds_reasoning_override(self, tmp_path):
        ctx = tmp_path / "context.md"
        ctx.write_text("test context")
        agent = AgentConfig(
            name="researcher",
            role="researcher",
            cli="codex",
            model="gpt-5.4",
            full_access_flag="--dangerously-bypass-approvals-and-sandbox",
            thinking_level="xhigh",
        )
        invocation = build_invocation(agent, ctx)
        assert 'model_reasoning_effort="xhigh"' in invocation.cmd

    def test_codex_none_adds_no_reasoning_override(self, tmp_path):
        ctx = tmp_path / "context.md"
        ctx.write_text("test context")
        agent = AgentConfig(
            name="researcher",
            role="researcher",
            cli="codex",
            model="gpt-5.4",
            full_access_flag="--dangerously-bypass-approvals-and-sandbox",
            thinking_level="none",
        )
        invocation = build_invocation(agent, ctx)
        assert "-c" not in invocation.cmd

    def test_codex_max_raises_with_xhigh_hint(self, tmp_path):
        ctx = tmp_path / "context.md"
        ctx.write_text("test context")
        with pytest.raises(ValueError, match="use 'xhigh' instead"):
            build_invocation(
                AgentConfig(
                    name="researcher",
                    role="researcher",
                    cli="codex",
                    model="gpt-5.4",
                    full_access_flag="--dangerously-bypass-approvals-and-sandbox",
                    thinking_level="max",
                ),
                ctx,
            )

    def test_unknown_cli_falls_back_to_argv(self, tmp_path):
        ctx = tmp_path / "context.md"
        ctx.write_text("test context")
        invocation = build_invocation(_fallback_agent(), ctx)
        assert invocation.cmd[0] == "custom-cli"
        assert "--allow-all" in invocation.cmd
        assert "-p" in invocation.cmd
        assert "test context" in invocation.cmd
        assert invocation.stdin_text is None


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
        mock_popen_cls.assert_called_once_with(
            ["claude", "--dangerously-skip-permissions", "--model", "claude-opus-4-6", "-p"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        mock_proc.communicate.assert_called_once_with(input="test", timeout=3600)

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

    @patch("helix.agents.subprocess.Popen")
    def test_fallback_cli_uses_argv_transport(self, mock_popen_cls, tmp_path):
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("output", "")
        mock_proc.returncode = 0
        mock_popen_cls.return_value = mock_proc

        ctx = tmp_path / "context.md"
        ctx.write_text("test")
        log_dir = tmp_path / "logs"

        result = spawn_agent(_fallback_agent(), ctx, log_dir)
        assert result.exit_code == 0
        mock_popen_cls.assert_called_once_with(
            ["custom-cli", "--allow-all", "-p", "test"],
            stdin=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        mock_proc.communicate.assert_called_once_with(input=None, timeout=3600)
