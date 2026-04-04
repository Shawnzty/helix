"""Workspace setup engine for Helix."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any

import httpx
import yaml

from helix.config import (
    AgentConfig,
    GlobalConfig,
    HELIX_THINKING_NONE,
    WorkspaceConfig,
    build_default_global_config_data,
    normalize_model_id,
    thinking_level_choices,
    thinking_level_prompt_label,
    load_global_config,
    load_workspace_config,
    render_workspace_config,
    validate_thinking_level_for_agent,
)
from helix.models import SetupDraft, WorkspaceAudit, WorkspaceFileAudit
from helix.setup_ui import RequirementSource, SetupMode, SetupUI
from helix.success import SuccessCriteriaError, parse_success_criteria

CORE_FILES = (
    "goal.md",
    "master_agent.md",
    "researcher_agent.md",
    "helix.toml",
    "tree_search.md",
)
OPTIONAL_FILES = (
    "config.yaml",
    "evaluate.sh",
    "setup_transcript.md",
)
LLM_MANAGED_FILES = {
    "goal.md",
    "master_agent.md",
    "researcher_agent.md",
}
SCAFFOLD_FILES = {
    "goal.md",
    "master_agent.md",
    "researcher_agent.md",
    "helix.toml",
    "tree_search.md",
    "evaluate.sh",
}
FILE_ORDER = (*CORE_FILES, *OPTIONAL_FILES)
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "blank"
_RESPONSES_URL = "https://api.openai.com/v1/responses"
CLAUDE_MODEL_PRESETS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
]
_SETUP_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "needs_follow_up": {"type": "boolean"},
        "follow_up_questions": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
        },
        "goal_md": {"type": ["string", "null"]},
        "master_agent_md": {"type": ["string", "null"]},
        "researcher_agent_md": {"type": ["string", "null"]},
        "repair_note": {"type": ["string", "null"]},
    },
    "required": [
        "summary",
        "needs_follow_up",
        "follow_up_questions",
        "goal_md",
        "master_agent_md",
        "researcher_agent_md",
        "repair_note",
    ],
}
_SETUP_SYSTEM_PROMPT = """You are Helix setup, the initialization assistant for a file-native autonomous research framework.

Your job is to draft only three files:
- goal.md
- master_agent.md
- researcher_agent.md

Important rules:
- Helix already injects step-specific workflow instructions at runtime.
- Do not duplicate framework mechanics like status labels, staged brainstorm file formats, or tree update syntax.
- Keep role files focused on durable, project-specific preferences.
- goal.md must contain these sections in order: # Goal, ## Success Criteria, ## Boundary, ## Evaluation, ## Limitation.
- The Success Criteria section must contain a fenced YAML block with machine-checkable criteria.
- The YAML block must define exactly one of `all` or `any`.
- Each criterion item must use exactly these keys: `metric`, `op`, `value`.
- Use only these operators: `<`, `<=`, `>`, `>=`, `==`, `!=`.
- Valid example:
```yaml
all:
  - metric: sharpe_ratio
    op: ">="
    value: 3.0
  - metric: max_drawdown_pct
    op: "<="
    value: 20
```
- Do not use alternative YAML layouts such as `primary_metric`, `secondary_metric`, `backtest_constraints`, `reporting_metrics_required`, `operational_limits`, or any other custom keys under `## Success Criteria`.
- Put richer constraints, objectives, and evaluation rules in `## Boundary`, `## Evaluation`, or `## Limitation`, not in the machine-checkable YAML block.
- master_agent.md should summarize the project and stable preferences for how the master should prioritize ideas, weigh risk, use external research, and reason over past work.
- researcher_agent.md should summarize the project and stable preferences for implementation scope, experiment hygiene, reporting, and when to inspect past work or external references.
- When the user's request is underspecified, ask at most 3 concise follow-up questions total.
- When you still need follow-up answers, set needs_follow_up=true and fill follow_up_questions. Leave the three file fields null.
- When you have enough information, set needs_follow_up=false, follow_up_questions=[] and return concise, editable markdown for all three files.
- Unless you are explicitly reporting an automatic repair, leave `repair_note` null.
"""
_GOAL_REPAIR_SYSTEM_PROMPT = """You are Helix setup repair, a focused repair assistant for `goal.md`.

Your job is to repair only `goal.md` so that:
- it preserves the intended project meaning
- `## Success Criteria` uses the exact Helix machine-checkable schema
- the result passes Helix's strict parser

Rules:
- Keep the same required section order: # Goal, ## Success Criteria, ## Boundary, ## Evaluation, ## Limitation.
- Under `## Success Criteria`, use a fenced YAML block with exactly one of `all` or `any`.
- Each criterion item must use exactly: `metric`, `op`, `value`.
- Use only `<`, `<=`, `>`, `>=`, `==`, `!=`.
- Do not use custom YAML keys such as `primary_metric`, `secondary_metric`, `backtest_constraints`, `reporting_metrics_required`, or `operational_limits`.
- Move richer constraints and reporting rules into `## Boundary`, `## Evaluation`, or `## Limitation`.
- Return only the full repaired `goal.md` markdown, nothing else.
"""


@dataclass(frozen=True)
class RequirementInput:
    """Initial requirement input collected for conversational setup."""

    source_kind: RequirementSource
    source_path: Path | None
    requirement_text: str


class SetupError(RuntimeError):
    """Raised when setup cannot complete."""


class SetupCancelled(SetupError):
    """Raised when the user cancels setup."""


class OpenAISetupClient:
    """Direct OpenAI Responses API client for conversational setup."""

    def __init__(
        self,
        api_key: str,
        model: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.http_client = http_client or httpx.Client(timeout=120.0)

    def generate(self, requirement_text: str, follow_ups: list[tuple[str, str]]) -> SetupDraft:
        transcript = [f"Initial requirement input:\n{requirement_text.strip()}"]
        if follow_ups:
            transcript.append("Follow-up answers:")
            for question, answer in follow_ups:
                transcript.append(f"- Q: {question}")
                transcript.append(f"  A: {answer}")

        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": _SETUP_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Draft the setup files for this Helix workspace.\n\n"
                        + "\n".join(transcript)
                    ),
                },
            ],
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "helix_setup_draft",
                    "strict": True,
                    "schema": _SETUP_SCHEMA,
                }
            },
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self.http_client.post(_RESPONSES_URL, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SetupError(f"Setup LLM call failed: {exc}") from exc

        output_text = _extract_response_text(response.json())
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise SetupError(f"Setup LLM returned invalid JSON: {exc}") from exc

        try:
            return SetupDraft.model_validate(parsed)
        except Exception as exc:
            raise SetupError(f"Setup LLM returned an invalid draft: {exc}") from exc

    def repair_goal_md(
        self,
        *,
        requirement_text: str,
        invalid_goal_md: str,
        parser_error: str,
    ) -> str:
        """Repair a generated goal.md using the exact parser failure."""
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": _GOAL_REPAIR_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Repair this generated goal.md so that Helix accepts it.\n\n"
                        "## Original Requirement Input\n"
                        f"{requirement_text.strip()}\n\n"
                        "## Parser Error\n"
                        f"{parser_error.strip()}\n\n"
                        "## Invalid goal.md\n"
                        f"{invalid_goal_md.strip()}\n"
                    ),
                },
            ],
            "store": False,
            "text": {"format": {"type": "text"}},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self.http_client.post(_RESPONSES_URL, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SetupError(f"Setup goal repair call failed: {exc}") from exc

        repaired = _extract_response_text(response.json()).strip()
        if not repaired:
            raise SetupError("Setup goal repair returned empty content.")
        return repaired


def audit_workspace(workspace: Path) -> WorkspaceAudit:
    """Audit the core and optional files that define a Helix workspace."""
    files = [
        _audit_goal_file(workspace),
        _audit_exists_only(workspace, "master_agent.md", required=True),
        _audit_exists_only(workspace, "researcher_agent.md", required=True),
        _audit_workspace_config(workspace),
        _audit_exists_only(workspace, "tree_search.md", required=True),
        _audit_global_config(workspace),
        _audit_exists_only(workspace, "evaluate.sh", required=False),
        _audit_exists_only(workspace, "setup_transcript.md", required=False),
    ]
    return WorkspaceAudit(files=files)


def run_setup_flow(
    workspace: Path,
    ui: SetupUI,
    *,
    mode: SetupMode | None = None,
    setup_model: str | None = None,
    setup_client: OpenAISetupClient | None = None,
) -> WorkspaceAudit:
    """Run either the conversational or local-files setup flow."""
    workspace.mkdir(parents=True, exist_ok=True)
    chosen_mode = mode or ui.choose_mode()
    if chosen_mode == "local":
        return _run_local_setup(workspace, ui)
    return _run_conversational_setup(
        workspace,
        ui,
        setup_model=setup_model,
        setup_client=setup_client,
    )


def _run_local_setup(workspace: Path, ui: SetupUI) -> WorkspaceAudit:
    audit = audit_workspace(workspace)
    ui.show_audit(audit)

    files_to_write: dict[str, str] = {}
    if audit.missing_core:
        missing = [entry.path for entry in audit.missing_core]
        if ui.prompt_yes_no(
            f"Scaffold missing core files ({', '.join(missing)}) from starter templates?",
            default=True,
        ):
            for file_name in missing:
                files_to_write[file_name] = build_scaffold_content(file_name)

    if audit.invalid_core:
        invalid = [entry.path for entry in audit.invalid_core]
        if ui.prompt_yes_no(
            f"Repair invalid core files ({', '.join(invalid)}) from starter templates?",
            default=True,
        ):
            for file_name in invalid:
                files_to_write[file_name] = build_scaffold_content(file_name)

    if "helix.toml" in files_to_write:
        files_to_write["helix.toml"] = _build_workspace_config_content(workspace, ui)

    optional_writes = _collect_optional_scaffolds(workspace, audit, ui, needs_setup_key=False)
    files_to_write.update(optional_writes)

    if files_to_write:
        _review_and_write(workspace, ui, files_to_write, audit)

    final_audit = audit_workspace(workspace)
    ui.show_audit(final_audit)
    if not final_audit.is_initialized():
        unresolved = [
            entry.path
            for entry in final_audit.core_files
            if entry.status != "valid"
        ]
        joined = ", ".join(unresolved)
        raise SetupError(f"Workspace is not initialized yet. Unresolved core files: {joined}")

    ui.success(f"Workspace initialized at {workspace}")
    return final_audit


def _run_conversational_setup(
    workspace: Path,
    ui: SetupUI,
    *,
    setup_model: str | None,
    setup_client: OpenAISetupClient | None,
) -> WorkspaceAudit:
    audit = audit_workspace(workspace)
    ui.show_audit(audit)

    selected_regenerate: set[str] = set()
    if audit.is_initialized():
        action = ui.prompt_workspace_action()
        if action == "cancel":
            raise SetupCancelled("Setup cancelled.")
        if action == "regenerate":
            selectable = [
                file_name
                for file_name in CORE_FILES
                if (workspace / file_name).exists()
            ]
            selected_regenerate = set(
                ui.prompt_file_selection(
                    selectable,
                    "Select setup files to regenerate. Leave blank to keep everything.",
                )
            )
            if not selected_regenerate:
                ui.warn("No files selected for regeneration. Existing files will be kept.")

    files_to_generate = set(selected_regenerate)
    files_to_generate.update(entry.path for entry in audit.missing_core)
    if audit.invalid_core:
        invalid = [entry.path for entry in audit.invalid_core]
        if ui.prompt_yes_no(
            f"Repair invalid core files ({', '.join(invalid)}) during setup?",
            default=True,
        ):
            files_to_generate.update(invalid)

    needs_llm = bool(files_to_generate & LLM_MANAGED_FILES)
    config_write: str | None = None
    model_name = setup_model or _default_setup_model(workspace)
    api_key = ""

    if needs_llm:
        config_write, api_key = _prepare_setup_config(workspace, audit, ui)

    files_to_write: dict[str, str] = {}
    if needs_llm:
        client = setup_client or OpenAISetupClient(api_key=api_key, model=model_name)
        requirement_input = _collect_requirement_input(workspace, ui)
        draft, follow_up_answers = _run_setup_conversation(
            client,
            requirement_input.requirement_text,
            ui,
        )
        draft = _validate_or_repair_goal_md(
            draft=draft,
            client=client,
            requirement_input=requirement_input,
        )

        if "goal.md" in files_to_generate:
            files_to_write["goal.md"] = draft.goal_md or ""
        if "master_agent.md" in files_to_generate:
            files_to_write["master_agent.md"] = draft.master_agent_md or ""
        if "researcher_agent.md" in files_to_generate:
            files_to_write["researcher_agent.md"] = draft.researcher_agent_md or ""
        files_to_write["setup_transcript.md"] = build_setup_transcript(
            requirement_input=requirement_input,
            follow_up_answers=follow_up_answers,
            draft=draft,
            model=model_name,
        )

    for file_name in sorted(files_to_generate - LLM_MANAGED_FILES):
        files_to_write[file_name] = build_scaffold_content(file_name)

    if "helix.toml" in files_to_write or "helix.toml" in files_to_generate:
        files_to_write["helix.toml"] = _build_workspace_config_content(workspace, ui)

    if config_write is not None:
        files_to_write["config.yaml"] = config_write

    files_to_write.update(_collect_optional_scaffolds(workspace, audit, ui, needs_setup_key=needs_llm))

    if not files_to_write:
        ui.success(f"Workspace already initialized at {workspace}")
        return audit_workspace(workspace)

    _review_and_write(workspace, ui, files_to_write, audit)
    final_audit = audit_workspace(workspace)
    ui.show_audit(final_audit)
    if not final_audit.is_initialized():
        unresolved = [
            entry.path
            for entry in final_audit.core_files
            if entry.status != "valid"
        ]
        joined = ", ".join(unresolved)
        raise SetupError(f"Workspace is not initialized yet. Unresolved core files: {joined}")

    ui.success(f"Workspace initialized at {workspace}")
    return final_audit


def _run_setup_conversation(
    client: OpenAISetupClient,
    requirement_text: str,
    ui: SetupUI,
) -> tuple[SetupDraft, list[tuple[str, str]]]:
    follow_up_answers: list[tuple[str, str]] = []

    while True:
        draft = client.generate(requirement_text, follow_up_answers)
        if not draft.needs_follow_up:
            return draft, follow_up_answers

        remaining = 3 - len(follow_up_answers)
        if remaining <= 0:
            raise SetupError("Setup LLM requested too many follow-up questions.")
        if len(draft.follow_up_questions) > remaining:
            raise SetupError("Setup LLM requested more than 3 follow-up questions in total.")

        for question in draft.follow_up_questions:
            answer = ui.prompt_text(question)
            follow_up_answers.append((question, answer))


def build_setup_transcript(
    *,
    requirement_input: RequirementInput,
    follow_up_answers: list[tuple[str, str]],
    draft: SetupDraft,
    model: str,
) -> str:
    source_label = "paragraph" if requirement_input.source_kind == "paragraph" else "markdown file"
    lines = [
        "# Setup Transcript",
        "",
        f"- Model: {model}",
        f"- Summary: {draft.summary}",
        f"- Requirement source: {source_label}",
    ]
    if draft.repair_note:
        lines.append(f"- Repair note: {draft.repair_note}")
    if requirement_input.source_path is not None:
        lines.append(f"- Requirement source path: {requirement_input.source_path}")
    lines.extend([
        "",
        "## Initial Requirement Input",
        "",
        requirement_input.requirement_text.strip(),
        "",
    ])

    if follow_up_answers:
        lines.extend(["## Follow-up Questions", ""])
        for question, answer in follow_up_answers:
            lines.append(f"- Q: {question}")
            lines.append(f"  A: {answer}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _collect_requirement_input(workspace: Path, ui: SetupUI) -> RequirementInput:
    """Collect the initial requirement text for conversational setup."""
    source_kind = ui.choose_requirement_source()
    if source_kind == "paragraph":
        requirement_text = ui.prompt_paragraph().strip()
        if not requirement_text:
            raise SetupError("Requirement paragraph must not be empty.")
        return RequirementInput(
            source_kind="paragraph",
            source_path=None,
            requirement_text=requirement_text,
        )

    entered_path = ui.prompt_markdown_path().strip()
    if not entered_path:
        raise SetupError("Markdown file path must not be empty.")

    source_path = Path(entered_path).expanduser()
    if not source_path.is_absolute():
        source_path = workspace / source_path

    resolved_path = source_path.resolve()
    if not resolved_path.exists():
        raise SetupError(f"Markdown requirement file not found: {resolved_path}")
    if not resolved_path.is_file():
        raise SetupError(f"Markdown requirement path must be a file: {resolved_path}")
    if resolved_path.suffix.lower() != ".md":
        raise SetupError(f"Requirement file must have a .md extension: {resolved_path}")
    try:
        requirement_text = resolved_path.read_text()
    except OSError as exc:
        raise SetupError(f"Could not read Markdown requirement file {resolved_path}: {exc}") from exc
    if not requirement_text.strip():
        raise SetupError(f"Markdown requirement file is empty: {resolved_path}")

    return RequirementInput(
        source_kind="markdown_file",
        source_path=resolved_path,
        requirement_text=requirement_text.strip(),
    )


def _validate_or_repair_goal_md(
    *,
    draft: SetupDraft,
    client: OpenAISetupClient,
    requirement_input: RequirementInput,
) -> SetupDraft:
    """Ensure the generated goal.md has valid machine-checkable success criteria."""
    goal_md = draft.goal_md or ""
    try:
        parse_success_criteria(goal_md)
        return draft
    except SuccessCriteriaError as exc:
        parser_error = str(exc)

    repaired_goal_md = client.repair_goal_md(
        requirement_text=requirement_input.requirement_text,
        invalid_goal_md=goal_md,
        parser_error=parser_error,
    )
    try:
        parse_success_criteria(repaired_goal_md)
    except SuccessCriteriaError as exc:
        raise SetupError(
            f"Generated goal.md remained invalid after one automatic repair attempt: {exc}"
        ) from exc

    return draft.model_copy(
        update={
            "goal_md": repaired_goal_md,
            "repair_note": f"goal.md required one automatic repair pass: {parser_error}",
        }
    )


def build_scaffold_content(file_name: str) -> str:
    """Return starter content for a workspace file."""
    if file_name == "config.yaml":
        return yaml.dump(build_default_global_config_data(), default_flow_style=False, sort_keys=False)

    template_path = _TEMPLATE_DIR / file_name
    if not template_path.exists():
        raise SetupError(f"No starter template found for {file_name}")
    return template_path.read_text()


def _build_workspace_config_content(workspace: Path, ui: SetupUI) -> str:
    existing_config = _load_existing_workspace_config(workspace / "helix.toml")
    global_cfg = _load_setup_global_config(workspace / "config.yaml")

    master_defaults = _default_agent_values(existing_config, global_cfg, role="master")
    researcher_defaults = _default_agent_values(existing_config, global_cfg, role="researcher")

    master_model = ui.prompt_model_choice(
        "master",
        master_defaults["model"],
        _preset_models_for_cli(master_defaults["cli"], master_defaults["model"]),
    )
    master_thinking = ui.prompt_thinking_level(
        "master",
        _prompt_default_thinking_level(master_defaults["cli"], master_model, master_defaults["thinking_level"]),
        thinking_level_choices(master_defaults["cli"], master_model),
        label=thinking_level_prompt_label(master_defaults["cli"]),
    )
    researcher_model = ui.prompt_model_choice(
        "researcher",
        researcher_defaults["model"],
        _preset_models_for_cli(researcher_defaults["cli"], researcher_defaults["model"]),
    )
    researcher_thinking = ui.prompt_thinking_level(
        "researcher",
        _prompt_default_thinking_level(
            researcher_defaults["cli"],
            researcher_model,
            researcher_defaults["thinking_level"],
        ),
        thinking_level_choices(researcher_defaults["cli"], researcher_model),
        label=thinking_level_prompt_label(researcher_defaults["cli"]),
    )

    config = WorkspaceConfig(agents=[
        AgentConfig(
            name=master_defaults["name"],
            role="master",
            cli=master_defaults["cli"],
            model=master_model,
            full_access_flag=master_defaults["full_access_flag"],
            description=master_defaults["description"],
            thinking_level=master_thinking,
        ),
        AgentConfig(
            name=researcher_defaults["name"],
            role="researcher",
            cli=researcher_defaults["cli"],
            model=researcher_model,
            full_access_flag=researcher_defaults["full_access_flag"],
            description=researcher_defaults["description"],
            thinking_level=researcher_thinking,
        ),
    ])
    return render_workspace_config(config)


def _load_existing_workspace_config(path: Path) -> WorkspaceConfig | None:
    try:
        return load_workspace_config(path)
    except Exception:
        return None


def _load_setup_global_config(path: Path) -> GlobalConfig:
    try:
        return load_global_config(path)
    except Exception:
        return GlobalConfig(**build_default_global_config_data())


def _default_agent_values(
    existing_config: WorkspaceConfig | None,
    global_cfg: GlobalConfig,
    *,
    role: str,
) -> dict[str, str]:
    existing_agent = None
    if existing_config is not None:
        if role == "master":
            existing_agent = existing_config.get_master()
        else:
            existing_agent = existing_config.get_researcher()

    cli_key = f"{role}_cli"
    model_key = f"{role}_model"
    thinking_key = f"{role}_thinking_level"

    cli = existing_agent.cli if existing_agent is not None else str(global_cfg.get_default(cli_key) or ("claude" if role == "master" else "codex"))
    model = existing_agent.model if existing_agent is not None else str(global_cfg.get_default(model_key) or ("claude-opus-4-6" if role == "master" else "gpt-5.4"))
    thinking_level = (
        existing_agent.thinking_level
        if existing_agent is not None and existing_agent.thinking_level
        else str(global_cfg.get_default(thinking_key) or "none")
    )
    cli = cli.strip().lower()
    model = normalize_model_id(cli, model.strip())
    name = existing_agent.name if existing_agent is not None else role
    description = (
        existing_agent.description
        if existing_agent is not None
        else ("Brainstorms ideas and reflects on results" if role == "master" else "Executes experiments, writes code, runs evaluation")
    )
    full_access_flag = (
        existing_agent.full_access_flag
        if existing_agent is not None
        else _default_full_access_flag(cli, global_cfg)
    )

    return {
        "name": name,
        "cli": cli,
        "model": model,
        "thinking_level": thinking_level,
        "description": description,
        "full_access_flag": full_access_flag,
    }


def _prompt_default_thinking_level(cli: str, model: str, thinking_level: str) -> str:
    """Return a safe default thinking level for setup prompts."""
    try:
        normalized = validate_thinking_level_for_agent(
            cli=cli,
            model=model,
            thinking_level=thinking_level,
        )
    except ValueError:
        return HELIX_THINKING_NONE

    choices = thinking_level_choices(cli, model)
    if normalized in choices:
        return normalized
    return HELIX_THINKING_NONE


def _default_full_access_flag(cli: str, global_cfg: GlobalConfig) -> str:
    if cli == "claude":
        return str(global_cfg.get_default("claude_full_access_flag") or "--dangerously-skip-permissions")
    if cli == "codex":
        return str(global_cfg.get_default("codex_full_access_flag") or "--dangerously-bypass-approvals-and-sandbox")
    return ""


def _preset_models_for_cli(cli: str, fallback_model: str) -> list[str]:
    if cli == "claude":
        return list(CLAUDE_MODEL_PRESETS)
    if cli == "codex":
        models = ["gpt-5.4"]
        if fallback_model not in models:
            models.append(fallback_model)
        return models
    return [fallback_model]


def _collect_optional_scaffolds(
    workspace: Path,
    audit: WorkspaceAudit,
    ui: SetupUI,
    *,
    needs_setup_key: bool,
) -> dict[str, str]:
    files_to_write: dict[str, str] = {}
    config_entry = audit.get("config.yaml")
    if not needs_setup_key:
        if config_entry.status != "valid" and ui.prompt_yes_no("Create or repair starter config.yaml?", default=False):
            files_to_write["config.yaml"] = build_scaffold_content("config.yaml")

    evaluate_entry = audit.get("evaluate.sh")
    if evaluate_entry.status != "valid" and ui.prompt_yes_no("Create starter evaluate.sh?", default=False):
        files_to_write["evaluate.sh"] = build_scaffold_content("evaluate.sh")
    return files_to_write


def _prepare_setup_config(
    workspace: Path,
    audit: WorkspaceAudit,
    ui: SetupUI,
) -> tuple[str | None, str]:
    config_path = workspace / "config.yaml"
    config_entry = audit.get("config.yaml")

    if config_entry.status == "valid":
        data = _load_yaml_mapping(config_path)
    else:
        if not ui.prompt_yes_no("Conversational setup needs config.yaml. Create or repair it now?", default=True):
            raise SetupCancelled("Conversational setup requires config.yaml before the LLM call.")
        data = build_default_global_config_data()

    api_key = str(data.get("openai_api_key", "")).strip()
    if not api_key:
        if "OPENAI_API_KEY" in os.environ and os.environ["OPENAI_API_KEY"].strip():
            api_key = os.environ["OPENAI_API_KEY"].strip()
        else:
            api_key = ui.prompt_secret("OpenAI API key")
        if not api_key:
            raise SetupCancelled("Conversational setup requires an OpenAI API key before the LLM call.")
        data["openai_api_key"] = api_key

    config_write = yaml.dump(data, default_flow_style=False, sort_keys=False)
    if config_entry.status == "valid" and config_path.exists():
        current = config_path.read_text()
        if current == config_write:
            return None, api_key
    return config_write, api_key


def _review_and_write(
    workspace: Path,
    ui: SetupUI,
    files_to_write: dict[str, str],
    audit: WorkspaceAudit,
) -> None:
    write_files = _ordered_file_names(files_to_write)
    keep_files = [
        entry.path
        for entry in audit.files
        if entry.status == "valid" and entry.path not in files_to_write
    ]
    ui.show_review(write_files, keep_files)
    if not ui.prompt_yes_no("Write these files?", default=True):
        raise SetupCancelled("Setup cancelled before writing files.")
    _write_files(workspace, files_to_write)


def _write_files(workspace: Path, files_to_write: dict[str, str]) -> None:
    for file_name in _ordered_file_names(files_to_write):
        path = workspace / file_name
        if path.exists():
            backup_path = path.with_name(path.name + ".bak")
            backup_path.write_text(path.read_text())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(files_to_write[file_name])
        if file_name == "evaluate.sh":
            path.chmod(0o755)


def _ordered_file_names(files: dict[str, str] | set[str]) -> list[str]:
    names = list(files if isinstance(files, set) else files.keys())
    priority = {name: index for index, name in enumerate(FILE_ORDER)}
    return sorted(names, key=lambda name: (priority.get(name, len(priority)), name))


def _default_setup_model(workspace: Path) -> str:
    config = load_global_config(workspace / "config.yaml")
    return str(config.get_default("setup_model") or "gpt-5.4")


def _audit_goal_file(workspace: Path) -> WorkspaceFileAudit:
    path = workspace / "goal.md"
    if not path.exists():
        return WorkspaceFileAudit(path="goal.md", required=True, status="missing")
    try:
        parse_success_criteria(path.read_text())
    except SuccessCriteriaError as exc:
        return WorkspaceFileAudit(path="goal.md", required=True, status="invalid", message=str(exc))
    return WorkspaceFileAudit(path="goal.md", required=True, status="valid")


def _audit_workspace_config(workspace: Path) -> WorkspaceFileAudit:
    path = workspace / "helix.toml"
    if not path.exists():
        return WorkspaceFileAudit(path="helix.toml", required=True, status="missing")
    try:
        load_workspace_config(path)
    except Exception as exc:
        return WorkspaceFileAudit(path="helix.toml", required=True, status="invalid", message=str(exc))
    return WorkspaceFileAudit(path="helix.toml", required=True, status="valid")


def _audit_global_config(workspace: Path) -> WorkspaceFileAudit:
    path = workspace / "config.yaml"
    if not path.exists():
        return WorkspaceFileAudit(path="config.yaml", required=False, status="missing")
    try:
        load_global_config(path)
    except Exception as exc:
        return WorkspaceFileAudit(path="config.yaml", required=False, status="invalid", message=str(exc))
    return WorkspaceFileAudit(path="config.yaml", required=False, status="valid")


def _audit_exists_only(workspace: Path, file_name: str, *, required: bool) -> WorkspaceFileAudit:
    path = workspace / file_name
    status = "valid" if path.exists() else "missing"
    return WorkspaceFileAudit(path=file_name, required=required, status=status)


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise SetupError(f"{path.name} must contain a YAML mapping")
    return loaded


def _extract_response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"]

    parts: list[str] = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)

    if parts:
        return "\n".join(parts)

    raise SetupError("Setup LLM response did not include text output.")
