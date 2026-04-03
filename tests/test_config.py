"""Tests for helix/config.py."""

import pytest
import yaml

from helix.config import (
    AgentConfig,
    GlobalConfig,
    WorkspaceConfig,
    load_global_config,
    load_workspace_config,
    save_workspace_config,
)


def _write_toml(path, content):
    path.write_text(content)


def _write_yaml(path, data):
    with path.open("w") as f:
        yaml.dump(data, f)


class TestAgentConfig:
    def test_prompt_flag_claude(self):
        a = AgentConfig(name="m", role="master", cli="claude")
        assert a.prompt_flag == "-p"

    def test_prompt_flag_codex(self):
        a = AgentConfig(name="r", role="researcher", cli="codex")
        assert a.prompt_flag is None  # codex takes prompt as positional arg

    def test_prompt_flag_unknown_defaults_to_p(self):
        a = AgentConfig(name="x", role="researcher", cli="custom-cli")
        assert a.prompt_flag == "-p"

    def test_legacy_reasoning_level_loads_as_thinking_level(self):
        a = AgentConfig.model_validate({
            "name": "m",
            "role": "master",
            "reasoning_level": "high",
        })
        assert a.thinking_level == "high"

    def test_legacy_claude_model_is_normalized(self):
        a = AgentConfig(name="m", role="master", model="claude-opus-4.6")
        assert a.model == "claude-opus-4-6"

    def test_claude_accepts_max_for_opus(self):
        a = AgentConfig(
            name="m",
            role="master",
            cli="claude",
            model="claude-opus-4-6",
            thinking_level="max",
        )
        assert a.thinking_level == "max"

    def test_claude_rejects_xhigh(self):
        with pytest.raises(ValueError, match="use 'max' instead"):
            AgentConfig(
                name="m",
                role="master",
                cli="claude",
                model="claude-opus-4-6",
                thinking_level="xhigh",
            )

    def test_claude_non_opus_rejects_max(self):
        with pytest.raises(ValueError, match="only supported for claude-opus-4-6"):
            AgentConfig(
                name="m",
                role="master",
                cli="claude",
                model="claude-sonnet-4-6",
                thinking_level="max",
            )

    def test_codex_accepts_xhigh(self):
        a = AgentConfig(
            name="r",
            role="researcher",
            cli="codex",
            model="gpt-5.4",
            thinking_level="xhigh",
        )
        assert a.thinking_level == "xhigh"

    def test_codex_rejects_max(self):
        with pytest.raises(ValueError, match="use 'xhigh' instead"):
            AgentConfig(
                name="r",
                role="researcher",
                cli="codex",
                model="gpt-5.4",
                thinking_level="max",
            )

    def test_unknown_codex_model_allows_custom_reasoning_value(self):
        a = AgentConfig(
            name="r",
            role="researcher",
            cli="codex",
            model="my-custom-codex-model",
            thinking_level="turbo",
        )
        assert a.thinking_level == "turbo"


class TestWorkspaceConfig:
    def test_valid_config(self):
        wc = WorkspaceConfig(agents=[
            AgentConfig(name="m", role="master"),
            AgentConfig(name="r", role="researcher"),
        ])
        assert wc.get_master().name == "m"
        assert wc.get_researcher().name == "r"

    def test_no_master_raises(self):
        with pytest.raises(ValueError, match="Exactly 1 master"):
            WorkspaceConfig(agents=[
                AgentConfig(name="r", role="researcher"),
            ])

    def test_two_masters_raises(self):
        with pytest.raises(ValueError, match="Exactly 1 master"):
            WorkspaceConfig(agents=[
                AgentConfig(name="m1", role="master"),
                AgentConfig(name="m2", role="master"),
                AgentConfig(name="r", role="researcher"),
            ])

    def test_no_researcher_raises(self):
        with pytest.raises(ValueError, match="At least 1 researcher"):
            WorkspaceConfig(agents=[
                AgentConfig(name="m", role="master"),
            ])


class TestLoadGlobalConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        cfg = load_global_config(tmp_path / "config.yaml")
        assert cfg.openai_api_key == ""
        assert cfg.get_default("agent_timeout_seconds") == 3600
        assert cfg.get_default("master_model") == "claude-opus-4-6"
        assert cfg.get_default("master_thinking_level") == "none"

    def test_load_from_yaml(self, tmp_path):
        _write_yaml(tmp_path / "config.yaml", {
            "openai_api_key": "sk-test",
            "defaults": {"agent_timeout_seconds": 7200},
        })
        cfg = load_global_config(tmp_path / "config.yaml")
        assert cfg.openai_api_key == "sk-test"
        assert cfg.get_default("agent_timeout_seconds") == 7200


class TestLoadWorkspaceConfig:
    def test_load_valid_toml(self, tmp_path):
        _write_toml(tmp_path / "helix.toml", """
[[agents]]
name = "master"
role = "master"
cli = "claude"
model = "claude-opus-4-6"
full_access_flag = "--dangerously-skip-permissions"
description = "Master agent"
thinking_level = "high"

[[agents]]
name = "researcher"
role = "researcher"
cli = "codex"
model = "gpt-5.4"
full_access_flag = "--dangerously-bypass-approvals-and-sandbox"
description = "Researcher agent"
reasoning_level = "medium"
""")
        wc = load_workspace_config(tmp_path / "helix.toml")
        assert len(wc.agents) == 2
        assert wc.get_master().cli == "claude"
        assert wc.get_master().thinking_level == "high"
        assert wc.get_researcher().thinking_level == "medium"

    def test_missing_toml_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_workspace_config(tmp_path / "helix.toml")


class TestSaveWorkspaceConfig:
    def test_round_trip(self, tmp_path):
        wc = WorkspaceConfig(agents=[
            AgentConfig(name="m", role="master"),
            AgentConfig(name="r", role="researcher"),
        ])
        toml_path = tmp_path / "helix.toml"
        save_workspace_config(toml_path, wc)
        loaded = load_workspace_config(toml_path)
        assert loaded.get_master().name == "m"
        assert loaded.get_researcher().name == "r"
        saved = toml_path.read_text()
        assert "thinking_level" not in saved

    def test_save_writes_thinking_level_field(self, tmp_path):
        wc = WorkspaceConfig(agents=[
            AgentConfig(name="m", role="master", thinking_level="high"),
            AgentConfig(name="r", role="researcher", thinking_level="none"),
        ])
        toml_path = tmp_path / "helix.toml"
        save_workspace_config(toml_path, wc)
        saved = toml_path.read_text()
        assert 'thinking_level = "high"' in saved
        assert 'reasoning_level' not in saved
