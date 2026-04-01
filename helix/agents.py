"""Spawn agent CLI subprocesses with full permissions."""

from __future__ import annotations

import logging
import signal
import subprocess
import time
from pathlib import Path

from helix.config import AgentConfig
from helix.models import AgentRun

logger = logging.getLogger(__name__)


def build_command(agent: AgentConfig, context_path: Path) -> list[str]:
    """Build the CLI command list for an agent invocation."""
    context_content = context_path.read_text()

    cmd: list[str] = [agent.cli]

    # Codex requires "exec" subcommand for non-interactive (piped) usage
    if agent.cli == "codex":
        cmd.append("exec")

    # Full access flag
    if agent.full_access_flag:
        cmd.append(agent.full_access_flag)

    # Model flag
    if agent.cli == "claude":
        cmd.extend(["--model", agent.model])
    elif agent.cli == "codex" and agent.model:
        cmd.extend(["--model", agent.model])

    # Prompt: either behind a flag (-p for claude) or as positional arg (codex exec)
    if agent.prompt_flag:
        cmd.extend([agent.prompt_flag, context_content])
    else:
        cmd.append(context_content)

    return cmd


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
    cmd = build_command(agent, context_path)

    logger.info("Spawning %s (%s): %s %s ...", agent.name, agent.cli, cmd[0], cmd[1] if len(cmd) > 1 else "")

    start = time.monotonic()

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
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
