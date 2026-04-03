"""Tests for helix/setup.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from helix.models import SetupDraft
from helix.setup import (
    SetupCancelled,
    _SETUP_SYSTEM_PROMPT,
    audit_workspace,
    run_setup_flow,
)


class FakeUI:
    def __init__(
        self,
        *,
        mode: str = "local",
        workspace_action: str = "keep",
        yes_no: list[bool] | None = None,
        texts: list[str] | None = None,
        secrets: list[str] | None = None,
        file_selections: list[list[str]] | None = None,
        model_choices: list[str] | None = None,
        thinking_choices: list[str] | None = None,
        paragraph: str = "Optimize training below 1.05 without touching prepare.py.",
    ) -> None:
        self.mode = mode
        self.workspace_action = workspace_action
        self.yes_no = yes_no or []
        self.texts = texts or []
        self.secrets = secrets or []
        self.file_selections = file_selections or []
        self.model_choices = model_choices or []
        self.thinking_choices = thinking_choices or []
        self.paragraph = paragraph
        self.audit_snapshots = []
        self.review_calls: list[tuple[list[str], list[str]]] = []
        self.thinking_prompts: list[tuple[str, str, tuple[str, ...], str, str | None]] = []

    def choose_mode(self):
        return self.mode

    def show_audit(self, audit):
        self.audit_snapshots.append(audit)

    def prompt_workspace_action(self):
        return self.workspace_action

    def prompt_yes_no(self, message: str, default: bool = True) -> bool:
        if self.yes_no:
            return self.yes_no.pop(0)
        return default

    def prompt_text(self, message: str, default: str | None = None) -> str:
        if self.texts:
            return self.texts.pop(0)
        return default or ""

    def prompt_secret(self, message: str) -> str:
        if self.secrets:
            return self.secrets.pop(0)
        return ""

    def prompt_paragraph(self) -> str:
        return self.paragraph

    def prompt_model_choice(self, role: str, default_model: str, preset_models):
        if self.model_choices:
            return self.model_choices.pop(0)
        return default_model

    def prompt_thinking_level(
        self,
        role: str,
        default_level: str,
        levels,
        *,
        label: str = "thinking level",
        provider_note: str | None = None,
    ) -> str:
        self.thinking_prompts.append((role, default_level, tuple(levels), label, provider_note))
        if self.thinking_choices:
            return self.thinking_choices.pop(0)
        return default_level

    def prompt_file_selection(self, files, message: str):
        if self.file_selections:
            return self.file_selections.pop(0)
        return []

    def show_review(self, write_files, keep_files):
        self.review_calls.append((list(write_files), list(keep_files)))

    def info(self, message: str) -> None:
        return None

    def warn(self, message: str) -> None:
        return None

    def success(self, message: str) -> None:
        return None


class FakeSetupClient:
    def __init__(self, drafts: list[SetupDraft]) -> None:
        self.drafts = drafts
        self.calls: list[tuple[str, list[tuple[str, str]]]] = []

    def generate(self, paragraph: str, follow_ups: list[tuple[str, str]]) -> SetupDraft:
        self.calls.append((paragraph, list(follow_ups)))
        return self.drafts.pop(0)


def _write_valid_workspace(workspace: Path) -> None:
    (workspace / "goal.md").write_text(
        "# Goal\n\n"
        "Optimize training.\n\n"
        "## Success Criteria\n\n"
        "```yaml\n"
        "all:\n"
        "  - metric: val_bpb\n"
        "    op: \"<\"\n"
        "    value: 1.05\n"
        "```\n\n"
        "## Boundary\n\n"
        "Do not edit prepare.py.\n\n"
        "## Evaluation\n\n"
        "Run evaluate.sh.\n\n"
        "## Limitation\n\n"
        "Single GPU.\n"
    )
    (workspace / "master_agent.md").write_text("# Master\nPrefer bold but grounded branches.\n")
    (workspace / "researcher_agent.md").write_text("# Researcher\nKeep runs narrow and measurable.\n")
    (workspace / "helix.toml").write_text(
        "[[agents]]\n"
        "name = \"master\"\n"
        "role = \"master\"\n"
        "cli = \"claude\"\n"
        "model = \"claude-opus-4-6\"\n"
        "full_access_flag = \"--dangerously-skip-permissions\"\n"
        "description = \"Master\"\n\n"
        "[[agents]]\n"
        "name = \"researcher\"\n"
        "role = \"researcher\"\n"
        "cli = \"codex\"\n"
        "model = \"gpt-5.4\"\n"
        "full_access_flag = \"--dangerously-bypass-approvals-and-sandbox\"\n"
        "description = \"Researcher\"\n"
    )
    (workspace / "tree_search.md").write_text("# Research Tree\n\n")


class TestWorkspaceAudit:
    def test_reports_invalid_goal_and_helix(self, tmp_path):
        (tmp_path / "goal.md").write_text("# Goal\n\n## Success Criteria\n\nnot yaml\n")
        (tmp_path / "helix.toml").write_text("[[agents]]\nname = \"master\"\n")

        audit = audit_workspace(tmp_path)

        assert audit.get("goal.md").status == "invalid"
        assert audit.get("helix.toml").status == "invalid"
        assert audit.get("tree_search.md").status == "missing"


class TestLocalSetup:
    def test_scaffolds_missing_core_files(self, tmp_path):
        ui = FakeUI(mode="local", yes_no=[True, False, False, True])

        audit = run_setup_flow(tmp_path, ui, mode="local")

        assert audit.is_initialized() is True
        for file_name in ("goal.md", "master_agent.md", "researcher_agent.md", "helix.toml", "tree_search.md"):
            assert (tmp_path / file_name).exists()
        assert not (tmp_path / "config.yaml").exists()
        assert not (tmp_path / "evaluate.sh").exists()
        helix_toml = (tmp_path / "helix.toml").read_text()
        assert 'model = "claude-opus-4-6"' in helix_toml
        assert 'thinking_level = "none"' in helix_toml

    def test_repairing_invalid_file_creates_backup(self, tmp_path):
        _write_valid_workspace(tmp_path)
        (tmp_path / "goal.md").write_text("# Goal\n\n## Success Criteria\n\nnot yaml\n")
        ui = FakeUI(mode="local", yes_no=[True, False, False, True])

        run_setup_flow(tmp_path, ui, mode="local")

        assert (tmp_path / "goal.md.bak").exists()
        assert "not yaml" in (tmp_path / "goal.md.bak").read_text()


class TestConversationalSetup:
    def test_missing_config_and_core_files_generate_workspace(self, tmp_path):
        ui = FakeUI(
            mode="conversational",
            yes_no=[True, False, True],
            secrets=["sk-test"],
            model_choices=["claude-sonnet-4-6", "gpt-5.4"],
            thinking_choices=["high", "xhigh"],
        )
        client = FakeSetupClient([
            SetupDraft(
                summary="Train optimization workspace drafted.",
                goal_md="# Goal\n\n## Success Criteria\n\n```yaml\nall:\n  - metric: val_bpb\n    op: \"<\"\n    value: 1.05\n```\n\n## Boundary\n\nOnly edit train.py.\n\n## Evaluation\n\nRun evaluate.sh.\n\n## Limitation\n\nSingle H100.\n",
                master_agent_md="# Master Agent Instructions\n\nProject summary.\n",
                researcher_agent_md="# Researcher Agent Instructions\n\nProject summary.\n",
            )
        ])

        audit = run_setup_flow(
            tmp_path,
            ui,
            mode="conversational",
            setup_model="gpt-5.4",
            setup_client=client,
        )

        assert audit.is_initialized() is True
        assert (tmp_path / "config.yaml").exists()
        assert (tmp_path / "setup_transcript.md").exists()
        assert "sk-test" in (tmp_path / "config.yaml").read_text()
        assert client.calls[0][0].startswith("Optimize training")
        helix_toml = (tmp_path / "helix.toml").read_text()
        assert 'model = "claude-sonnet-4-6"' in helix_toml
        assert 'thinking_level = "high"' in helix_toml
        assert helix_toml.count('thinking_level = "xhigh"') == 1
        assert ui.thinking_prompts[0][2] == ("none", "low", "medium", "high")
        assert ui.thinking_prompts[0][3] == "effort"
        assert ui.thinking_prompts[1][2] == ("none", "low", "medium", "high", "xhigh")
        assert ui.thinking_prompts[1][3] == "reasoning effort"

    def test_missing_api_key_cancels_before_llm_call(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        (tmp_path / "config.yaml").write_text("openai_api_key: \"\"\ndefaults: {}\n")
        ui = FakeUI(mode="conversational", secrets=[""])
        client = FakeSetupClient([
            SetupDraft(
                summary="unused",
                goal_md="# Goal\n\n## Success Criteria\n\n```yaml\nall:\n  - metric: x\n    op: \"==\"\n    value: true\n```\n\n## Boundary\n\n.\n\n## Evaluation\n\n.\n\n## Limitation\n\n.\n",
                master_agent_md="# Master\n",
                researcher_agent_md="# Researcher\n",
            )
        ])

        with pytest.raises(SetupCancelled):
            run_setup_flow(
                tmp_path,
                ui,
                mode="conversational",
                setup_model="gpt-5.4",
                setup_client=client,
            )

        assert client.calls == []

    def test_existing_role_files_are_kept_by_default(self, tmp_path):
        _write_valid_workspace(tmp_path)
        original_master = (tmp_path / "master_agent.md").read_text()
        original_researcher = (tmp_path / "researcher_agent.md").read_text()
        ui = FakeUI(mode="conversational", workspace_action="keep", yes_no=[False, False])
        client = FakeSetupClient([])

        audit = run_setup_flow(
            tmp_path,
            ui,
            mode="conversational",
            setup_model="gpt-5.4",
            setup_client=client,
        )

        assert audit.is_initialized() is True
        assert client.calls == []
        assert (tmp_path / "master_agent.md").read_text() == original_master
        assert (tmp_path / "researcher_agent.md").read_text() == original_researcher

    def test_follow_up_answers_are_captured(self, tmp_path):
        ui = FakeUI(
            mode="conversational",
            yes_no=[True, False, True],
            texts=["Single H100, 5 minutes."],
            secrets=["sk-test"],
        )
        client = FakeSetupClient([
            SetupDraft(
                summary="Need one more detail.",
                needs_follow_up=True,
                follow_up_questions=["What is the runtime budget?"],
            ),
            SetupDraft(
                summary="Finalized after follow-up.",
                goal_md="# Goal\n\n## Success Criteria\n\n```yaml\nall:\n  - metric: val_bpb\n    op: \"<\"\n    value: 1.05\n```\n\n## Boundary\n\nOnly edit train.py.\n\n## Evaluation\n\nRun evaluate.sh.\n\n## Limitation\n\nSingle H100.\n",
                master_agent_md="# Master Agent Instructions\n\nProject summary.\n",
                researcher_agent_md="# Researcher Agent Instructions\n\nProject summary.\n",
            ),
        ])

        run_setup_flow(
            tmp_path,
            ui,
            mode="conversational",
            setup_model="gpt-5.4",
            setup_client=client,
        )

        transcript = (tmp_path / "setup_transcript.md").read_text()
        assert "What is the runtime budget?" in transcript
        assert "Single H100, 5 minutes." in transcript
        assert len(client.calls) == 2


class TestSetupPrompt:
    def test_system_prompt_discourages_framework_duplication(self):
        assert "do not duplicate framework mechanics" in _SETUP_SYSTEM_PROMPT.lower()
        assert "durable, project-specific preferences" in _SETUP_SYSTEM_PROMPT.lower()
