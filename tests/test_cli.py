"""Tests for helix/cli.py."""

import yaml
from typer.testing import CliRunner

from helix.cli import app

runner = CliRunner()


def _setup_workspace(tmp_path):
    """Create minimal workspace files."""
    (tmp_path / "helix.toml").write_text("""
[[agents]]
name = "master"
role = "master"
cli = "claude"
model = "claude-opus-4-6"
full_access_flag = "--dangerously-skip-permissions"
description = "Master"

[[agents]]
name = "researcher"
role = "researcher"
cli = "codex"
model = "gpt-5.4"
full_access_flag = "--dangerously-bypass-approvals-and-sandbox"
description = "Researcher"
""")
    (tmp_path / "tree_search.md").write_text("""# Research Tree

1. [active] First run
   idea: try X
   result: val 1.10
   reflect: promising

  1.1. [★ best] Improved X
       idea: tune X
       result: val 1.05
       reflect: better

2. [frontier] Try Y
   idea: (pending)
   result: (pending)
   reflect: (pending)
""")
    return tmp_path


class TestStatus:
    def test_status_with_runs(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        result = runner.invoke(app, ["status", "--path", str(ws)])
        assert result.exit_code == 0
        assert "Best" in result.output or "best" in result.output

    def test_status_empty(self, tmp_path):
        (tmp_path / "tree_search.md").write_text("# Research Tree\n\n")
        result = runner.invoke(app, ["status", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "empty" in result.output.lower() or "No runs" in result.output


class TestHistory:
    def test_history(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        result = runner.invoke(app, ["history", "--path", str(ws)])
        assert result.exit_code == 0

    def test_history_last_n(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        result = runner.invoke(app, ["history", "--path", str(ws), "--last", "1"])
        assert result.exit_code == 0


class TestStop:
    def test_stop_creates_file(self, tmp_path):
        result = runner.invoke(app, ["stop", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / ".helix" / "stop").exists()


class TestInit:
    def test_init_without_mode_uses_picker_and_scaffolds(self, tmp_path):
        result = runner.invoke(
            app,
            ["init", "--path", str(tmp_path)],
            input="2\ny\n1\n1\n1\n1\nn\nn\ny\n",
        )
        assert result.exit_code == 0
        assert "Choose setup mode" in result.output
        assert (tmp_path / "goal.md").exists()
        assert (tmp_path / "master_agent.md").exists()
        assert (tmp_path / "researcher_agent.md").exists()
        assert (tmp_path / "helix.toml").exists()
        assert (tmp_path / "tree_search.md").exists()

    def test_init_local_validates_existing_workspace(self, tmp_path):
        (tmp_path / "goal.md").write_text(
            "# Goal\n\n## Success Criteria\n\n```yaml\nall:\n  - metric: val_bpb\n    op: \"<\"\n    value: 1.05\n```\n\n"
            "## Boundary\n\nOnly edit train.py.\n\n## Evaluation\n\nRun evaluate.sh.\n\n## Limitation\n\nSingle GPU.\n"
        )
        (tmp_path / "master_agent.md").write_text("# Master\n")
        (tmp_path / "researcher_agent.md").write_text("# Researcher\n")
        (tmp_path / "tree_search.md").write_text("# Research Tree\n\n")
        (tmp_path / "helix.toml").write_text(
            "[[agents]]\nname = \"master\"\nrole = \"master\"\ncli = \"claude\"\nmodel = \"claude-opus-4-6\"\nfull_access_flag = \"--dangerously-skip-permissions\"\ndescription = \"Master\"\n\n"
            "[[agents]]\nname = \"researcher\"\nrole = \"researcher\"\ncli = \"codex\"\nmodel = \"gpt-5.4\"\nfull_access_flag = \"--dangerously-bypass-approvals-and-sandbox\"\ndescription = \"Researcher\"\n"
        )

        result = runner.invoke(
            app,
            ["init", "--path", str(tmp_path), "--mode", "local"],
            input="n\nn\n",
        )
        assert result.exit_code == 0
        assert "Workspace initialized" in result.output


class TestSetupCommand:
    def test_setup_reuses_local_flow(self, tmp_path):
        result = runner.invoke(
            app,
            ["setup", "--path", str(tmp_path), "--mode", "local"],
            input="y\n1\n1\n1\n1\nn\nn\ny\n",
        )
        assert result.exit_code == 0
        assert (tmp_path / "goal.md").exists()
        assert (tmp_path / "tree_search.md").exists()


class TestConfigInit:
    def test_creates_config(self, tmp_path):
        result = runner.invoke(app, ["config", "init", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / "config.yaml").exists()

    def test_no_overwrite(self, tmp_path):
        (tmp_path / "config.yaml").write_text("existing: true")
        result = runner.invoke(app, ["config", "init", "--path", str(tmp_path)])
        assert "already exists" in result.output


class TestConfigShow:
    def test_show(self, tmp_path):
        with (tmp_path / "config.yaml").open("w") as f:
            yaml.dump({"openai_api_key": "sk-1234567890abcdef", "defaults": {}}, f)
        result = runner.invoke(app, ["config", "show", "--path", str(tmp_path)])
        assert result.exit_code == 0
        # Key should be masked
        assert "sk-12345..." in result.output
        assert "sk-1234567890abcdef" not in result.output


class TestConfigSet:
    def test_set_key(self, tmp_path):
        result = runner.invoke(app, ["config", "set", "openai_api_key", "sk-new", "--path", str(tmp_path)])
        assert result.exit_code == 0
        with (tmp_path / "config.yaml").open() as f:
            data = yaml.safe_load(f)
        assert data["openai_api_key"] == "sk-new"

    def test_set_nested(self, tmp_path):
        result = runner.invoke(app, ["config", "set", "defaults.agent_timeout_seconds", "7200", "--path", str(tmp_path)])
        assert result.exit_code == 0


class TestAgentsList:
    def test_list(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        result = runner.invoke(app, ["agents", "list", "--path", str(ws)])
        assert result.exit_code == 0
        assert "master" in result.output
        assert "researcher" in result.output


class TestAgentsAdd:
    def test_add(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        result = runner.invoke(app, [
            "agents", "add",
            "--name", "explorer",
            "--role", "researcher",
            "--cli", "claude",
            "--model", "claude-sonnet-4",
            "--path", str(ws),
        ])
        assert result.exit_code == 0
        assert "Added" in result.output


class TestAgentsRemove:
    def test_remove_nonexistent(self, tmp_path):
        ws = _setup_workspace(tmp_path)
        result = runner.invoke(app, ["agents", "remove", "--name", "nonexistent", "--path", str(ws)])
        assert "not found" in result.output
