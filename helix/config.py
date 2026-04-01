"""Parse config.yaml and helix.toml. Resolve config with CLI → toml → yaml → defaults."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, model_validator

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

import tomli_w

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in defaults
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "setup_model": "gpt-5.4",
    "master_cli": "claude",
    "master_model": "claude-opus-4.6",
    "researcher_cli": "codex",
    "researcher_model": "gpt-5.4",
    "claude_full_access_flag": "--dangerously-skip-permissions",
    "codex_full_access_flag": "--dangerously-bypass-approvals-and-sandbox",
    "codex_reasoning_level": "high",
    "agent_timeout_seconds": 3600,
}

# Map cli name → prompt flag used to pass the prompt string.
# None means the prompt is a positional argument (no flag needed).
PROMPT_FLAGS: dict[str, str | None] = {
    "claude": "-p",
    "codex": None,  # codex takes prompt as positional argument
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class AgentConfig(BaseModel):
    name: str
    role: str  # "master" or "researcher"
    cli: str = "claude"
    model: str = "claude-opus-4.6"
    full_access_flag: str = "--dangerously-skip-permissions"
    description: str = ""
    reasoning_level: str | None = None

    @property
    def prompt_flag(self) -> str | None:
        """Return the flag for passing the prompt, or None if positional."""
        return PROMPT_FLAGS.get(self.cli, "-p")


class WorkspaceConfig(BaseModel):
    agents: list[AgentConfig] = []

    @model_validator(mode="after")
    def _validate_roles(self) -> WorkspaceConfig:
        masters = [a for a in self.agents if a.role == "master"]
        researchers = [a for a in self.agents if a.role == "researcher"]
        if len(masters) != 1:
            raise ValueError(f"Exactly 1 master required, found {len(masters)}")
        if len(researchers) < 1:
            raise ValueError("At least 1 researcher required")
        return self

    def get_master(self) -> AgentConfig:
        return next(a for a in self.agents if a.role == "master")

    def get_researcher(self) -> AgentConfig:
        return next(a for a in self.agents if a.role == "researcher")


class GlobalConfig(BaseModel):
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    defaults: dict[str, Any] = {}

    def get_default(self, key: str) -> Any:
        return self.defaults.get(key, DEFAULTS.get(key))


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_global_config(path: Path) -> GlobalConfig:
    """Load config.yaml from *path* (file path, not directory)."""
    if not path.exists():
        logger.warning("config.yaml not found at %s, using defaults", path)
        return GlobalConfig()
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return GlobalConfig(**data)


def load_workspace_config(path: Path) -> WorkspaceConfig:
    """Load helix.toml from *path* (file path, not directory)."""
    if not path.exists():
        raise FileNotFoundError(f"helix.toml not found at {path}")
    with path.open("rb") as f:
        data = tomllib.load(f)
    agents = [AgentConfig(**a) for a in data.get("agents", [])]
    return WorkspaceConfig(agents=agents)


def save_workspace_config(path: Path, config: WorkspaceConfig) -> None:
    """Write helix.toml."""
    data = {"agents": [a.model_dump(exclude_none=True) for a in config.agents]}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        tomli_w.dump(data, f)


def resolve_config(
    workspace_path: Path,
    cli_overrides: dict[str, Any] | None = None,
) -> tuple[GlobalConfig, WorkspaceConfig]:
    """Load and merge configs. Priority: CLI → toml → yaml → defaults."""
    global_cfg = load_global_config(workspace_path / "config.yaml")
    workspace_cfg = load_workspace_config(workspace_path / "helix.toml")

    # Apply defaults from config.yaml to agents that don't override them
    for agent in workspace_cfg.agents:
        if agent.role == "master":
            if not agent.model or agent.model == "claude-opus-4.6":
                model_val = global_cfg.get_default("master_model")
                if model_val:
                    agent.model = model_val
        elif agent.role == "researcher":
            if not agent.model or agent.model == "gpt-5.4":
                model_val = global_cfg.get_default("researcher_model")
                if model_val:
                    agent.model = model_val

    # CLI overrides (if any) would be applied here
    if cli_overrides:
        for key, value in cli_overrides.items():
            if hasattr(global_cfg, key):
                setattr(global_cfg, key, value)

    return global_cfg, workspace_cfg
