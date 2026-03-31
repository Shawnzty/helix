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
        assert a.prompt_flag == "-q"

    def test_prompt_flag_unknown_defaults_to_p(self):
        a = AgentConfig(name="x", role="researcher", cli="custom-cli")
        assert a.prompt_flag == "-p"


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
model = "claude-opus-4.6"
full_access_flag = "--dangerously-skip-permissions"
description = "Master agent"

[[agents]]
name = "researcher"
role = "researcher"
cli = "codex"
model = "gpt-5.4"
full_access_flag = "--dangerously-bypass-approvals-and-sandbox"
description = "Researcher agent"
""")
        wc = load_workspace_config(tmp_path / "helix.toml")
        assert len(wc.agents) == 2
        assert wc.get_master().cli == "claude"

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
