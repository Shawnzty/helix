"""Parse config.yaml and helix.toml. Resolve config with CLI → toml → yaml → defaults."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

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
    "master_model": "claude-opus-4-6",
    "master_thinking_level": "none",
    "researcher_cli": "codex",
    "researcher_model": "gpt-5.4",
    "researcher_thinking_level": "none",
    "claude_full_access_flag": "--dangerously-skip-permissions",
    "codex_full_access_flag": "--dangerously-bypass-approvals-and-sandbox",
    "agent_timeout_seconds": 3600,
}

HELIX_THINKING_NONE = "none"
GENERIC_THINKING_LEVELS = {"none", "low", "medium", "high", "max", "xhigh"}
CLAUDE_EFFORT_LEVELS = ("low", "medium", "high", "max")
CODEX_REASONING_LEVELS = ("low", "medium", "high", "xhigh")
KNOWN_CODEX_MODEL_REASONING_LEVELS = {
    "gpt-5.4": set(CODEX_REASONING_LEVELS),
    "gpt-5.3-codex": set(CODEX_REASONING_LEVELS),
}
LEGACY_CLAUDE_MODEL_IDS = {
    "claude-opus-4.6": "claude-opus-4-6",
    "claude-sonnet-4.6": "claude-sonnet-4-6",
}

# Map cli name → legacy argv prompt flag used only by the compatibility fallback.
# None means the fallback should use a positional prompt argument.
PROMPT_FLAGS: dict[str, str | None] = {
    "claude": "-p",
    "codex": None,  # codex takes prompt as positional argument
}


def normalize_model_id(cli: str, model: str) -> str:
    """Normalize known provider model aliases to canonical CLI-facing IDs."""
    if cli == "claude":
        return LEGACY_CLAUDE_MODEL_IDS.get(model, model)
    return model


def normalize_thinking_level(value: str | None) -> str | None:
    """Normalize a thinking-level string without applying provider rules yet."""
    if value is None:
        return value
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("thinking_level cannot be empty")
    return normalized


def thinking_level_prompt_label(cli: str) -> str:
    """Return the provider-appropriate prompt label for thinking controls."""
    if cli == "claude":
        return "effort"
    if cli == "codex":
        return "reasoning effort"
    return "thinking level"


def thinking_level_choices(cli: str, model: str | None = None) -> list[str]:
    """Return the user-facing thinking-level choices for a provider/model."""
    if cli == "claude":
        levels = list(CLAUDE_EFFORT_LEVELS)
        if model and _is_known_non_opus_claude_model(normalize_model_id(cli, model)):
            levels.remove("max")
        return [HELIX_THINKING_NONE, *levels]
    if cli == "codex":
        return [HELIX_THINKING_NONE, *CODEX_REASONING_LEVELS]
    return [HELIX_THINKING_NONE, "low", "medium", "high"]


def validate_thinking_level_for_agent(
    *,
    cli: str,
    model: str,
    thinking_level: str | None,
) -> str | None:
    """Validate thinking_level against the provider/model contract."""
    normalized = normalize_thinking_level(thinking_level)
    if normalized is None:
        return None

    normalized_cli = cli.strip().lower()
    normalized_model = normalize_model_id(normalized_cli, model)

    if normalized_cli == "claude":
        if normalized == HELIX_THINKING_NONE:
            return normalized
        if normalized == "xhigh":
            raise ValueError("Claude thinking_level 'xhigh' is not supported; use 'max' instead.")
        if normalized not in CLAUDE_EFFORT_LEVELS:
            allowed = ", ".join([HELIX_THINKING_NONE, *CLAUDE_EFFORT_LEVELS])
            raise ValueError(f"Claude thinking_level must be one of: {allowed}")
        if normalized == "max" and _is_known_non_opus_claude_model(normalized_model):
            raise ValueError(
                f"Claude thinking_level 'max' is only supported for claude-opus-4-6; use 'high' for {normalized_model}."
            )
        return normalized

    if normalized_cli == "codex":
        if normalized == "max":
            raise ValueError("Codex/OpenAI thinking_level 'max' is not supported; use 'xhigh' instead.")
        if normalized == HELIX_THINKING_NONE:
            return normalized
        known_levels = KNOWN_CODEX_MODEL_REASONING_LEVELS.get(normalized_model)
        if known_levels is not None and normalized not in known_levels:
            allowed = ", ".join([HELIX_THINKING_NONE, *CODEX_REASONING_LEVELS])
            raise ValueError(
                f"Codex/OpenAI thinking_level '{normalized}' is not supported for {normalized_model}; choose one of {allowed}."
            )
        if normalized in CODEX_REASONING_LEVELS:
            return normalized
        if known_levels is None:
            return normalized

        allowed = ", ".join([HELIX_THINKING_NONE, *CODEX_REASONING_LEVELS])
        raise ValueError(
            f"Codex/OpenAI thinking_level '{normalized}' is not supported for {normalized_model}; choose one of {allowed}."
        )

    if normalized not in GENERIC_THINKING_LEVELS:
        allowed = ", ".join(sorted(GENERIC_THINKING_LEVELS))
        raise ValueError(f"thinking_level must be one of: {allowed}")
    return normalized


def _is_known_non_opus_claude_model(model: str) -> bool:
    """Return True when we can confidently identify a non-Opus Claude model."""
    normalized = model.strip().lower()
    if normalized in {"sonnet", "haiku"}:
        return True
    return normalized.startswith("claude-sonnet-") or normalized.startswith("claude-haiku-")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class AgentConfig(BaseModel):
    name: str
    role: str  # "master" or "researcher"
    cli: str = "claude"
    model: str = "claude-opus-4-6"
    full_access_flag: str = "--dangerously-skip-permissions"
    description: str = ""
    thinking_level: str | None = Field(
        default=None,
        validation_alias=AliasChoices("thinking_level", "reasoning_level"),
        serialization_alias="thinking_level",
    )

    @field_validator("cli")
    @classmethod
    def _normalize_cli(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("model")
    @classmethod
    def _normalize_model(cls, value: str) -> str:
        return value.strip()

    @field_validator("thinking_level")
    @classmethod
    def _validate_thinking_level(cls, value: str | None) -> str | None:
        return normalize_thinking_level(value)

    @model_validator(mode="after")
    def _validate_provider_thinking_level(self) -> AgentConfig:
        self.model = normalize_model_id(self.cli, self.model)
        self.thinking_level = validate_thinking_level_for_agent(
            cli=self.cli,
            model=self.model,
            thinking_level=self.thinking_level,
        )
        return self

    @property
    def prompt_flag(self) -> str | None:
        """Return the fallback argv prompt flag, or None if positional."""
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
        if key == "researcher_thinking_level" and "researcher_thinking_level" not in self.defaults:
            legacy = self.defaults.get("codex_reasoning_level")
            if legacy is not None:
                return legacy
        return self.defaults.get(key, DEFAULTS.get(key))


def build_default_global_config_data() -> dict[str, Any]:
    """Return the default config.yaml structure."""
    return {
        "openai_api_key": "",
        "anthropic_api_key": "",
        "defaults": dict(DEFAULTS),
    }


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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_workspace_config(config))


def render_workspace_config(config: WorkspaceConfig) -> str:
    """Serialize a workspace config to TOML."""
    data = {"agents": [a.model_dump(exclude_none=True, by_alias=True) for a in config.agents]}
    return tomli_w.dumps(data)


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
            if not agent.model or agent.model == DEFAULTS["master_model"]:
                model_val = global_cfg.get_default("master_model")
                if model_val:
                    agent.model = normalize_model_id(agent.cli, str(model_val))
            if not agent.thinking_level:
                thinking_val = global_cfg.get_default("master_thinking_level")
                if thinking_val:
                    agent.thinking_level = validate_thinking_level_for_agent(
                        cli=agent.cli,
                        model=agent.model,
                        thinking_level=str(thinking_val),
                    )
        elif agent.role == "researcher":
            if not agent.model or agent.model == "gpt-5.4":
                model_val = global_cfg.get_default("researcher_model")
                if model_val:
                    agent.model = normalize_model_id(agent.cli, str(model_val))
            if not agent.thinking_level:
                thinking_val = global_cfg.get_default("researcher_thinking_level")
                if thinking_val:
                    agent.thinking_level = validate_thinking_level_for_agent(
                        cli=agent.cli,
                        model=agent.model,
                        thinking_level=str(thinking_val),
                    )

    # CLI overrides (if any) would be applied here
    if cli_overrides:
        for key, value in cli_overrides.items():
            if hasattr(global_cfg, key):
                setattr(global_cfg, key, value)

    return global_cfg, workspace_cfg
