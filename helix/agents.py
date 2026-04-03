"""Spawn agent CLI subprocesses with full permissions."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import signal
import subprocess
import time
from pathlib import Path

from helix.config import (
    AgentConfig,
    HELIX_THINKING_NONE,
    validate_thinking_level_for_agent,
)
from helix.models import AgentRun

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentInvocation:
    """Structured agent invocation with explicit prompt transport."""

    cmd: list[str]
    stdin_text: str | None = None


def build_invocation(agent: AgentConfig, context_path: Path) -> AgentInvocation:
    """Build the subprocess invocation for an agent."""
    context_content = context_path.read_text()
    thinking_level = validate_thinking_level_for_agent(
        cli=agent.cli,
        model=agent.model,
        thinking_level=agent.thinking_level,
    )

    cmd: list[str] = [agent.cli]

    if agent.cli == "codex":
        cmd.append("exec")

    if agent.full_access_flag:
        cmd.append(agent.full_access_flag)

    if agent.cli == "claude":
        cmd.extend(["--model", agent.model])
        if thinking_level and thinking_level != HELIX_THINKING_NONE:
            cmd.extend(["--effort", thinking_level])
    elif agent.cli == "codex" and agent.model:
        cmd.extend(["--model", agent.model])
        if thinking_level and thinking_level != HELIX_THINKING_NONE:
            cmd.extend(["-c", f'model_reasoning_effort="{thinking_level}"'])
    elif thinking_level and thinking_level != HELIX_THINKING_NONE:
        logger.warning(
            "Agent %s uses thinking_level=%s, but cli '%s' has no configured thinking-level mapping.",
            agent.name,
            thinking_level,
            agent.cli,
        )

    # Supported CLIs use stdin-first transport to avoid argv size limits.
    if agent.cli == "claude":
        cmd.append("-p")
        return AgentInvocation(cmd=cmd, stdin_text=context_content)

    if agent.cli == "codex":
        cmd.append("-")
        return AgentInvocation(cmd=cmd, stdin_text=context_content)

    # Compatibility fallback for unknown CLIs still passes the prompt via argv.
    if agent.prompt_flag:
        cmd.extend([agent.prompt_flag, context_content])
    else:
        cmd.append(context_content)

    return AgentInvocation(cmd=cmd)


def spawn_agent(
    agent: AgentConfig,
    context_path: Path,
    log_dir: Path,
    timeout: int = 3600,
) -> AgentRun:
    """Spawn an agent subprocess and capture output.

    Enforces timeout with SIGTERM → wait 10s → SIGKILL.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    invocation = build_invocation(agent, context_path)

    logger.info(
        "Spawning %s (%s) via %s: %s",
        agent.name,
        agent.cli,
        "stdin" if invocation.stdin_text is not None else "argv",
        " ".join(invocation.cmd[:3]),
    )

    start = time.monotonic()

    proc = subprocess.Popen(
        invocation.cmd,
        stdin=subprocess.PIPE if invocation.stdin_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = proc.communicate(input=invocation.stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning("Agent %s timed out after %ds, sending SIGTERM", agent.name, timeout)
        proc.send_signal(signal.SIGTERM)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("Agent %s did not stop after SIGTERM, sending SIGKILL", agent.name)
            proc.kill()
            stdout, stderr = proc.communicate()

    duration = time.monotonic() - start

    # Write logs
    (log_dir / "stdout.log").write_text(stdout or "")
    (log_dir / "stderr.log").write_text(stderr or "")

    result = AgentRun(
        stdout=stdout or "",
        stderr=stderr or "",
        exit_code=proc.returncode or 0,
        duration_seconds=duration,
    )

    if result.exit_code != 0:
        logger.warning("Agent %s exited with code %d", agent.name, result.exit_code)

    return result
