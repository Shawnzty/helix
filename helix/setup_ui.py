"""Rich-backed interactive UI helpers for Helix setup flows."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

import typer
from rich.console import Console
from rich.table import Table

from helix.models import WorkspaceAudit

SetupMode = Literal["conversational", "local"]
WorkspaceAction = Literal["keep", "regenerate", "cancel"]


class SetupUI(Protocol):
    """Interactive surface used by the setup engine."""

    def choose_mode(self) -> SetupMode: ...

    def show_audit(self, audit: WorkspaceAudit) -> None: ...

    def prompt_workspace_action(self) -> WorkspaceAction: ...

    def prompt_yes_no(self, message: str, default: bool = True) -> bool: ...

    def prompt_text(self, message: str, default: str | None = None) -> str: ...

    def prompt_secret(self, message: str) -> str: ...

    def prompt_paragraph(self) -> str: ...

    def prompt_model_choice(
        self,
        role: str,
        default_model: str,
        preset_models: Sequence[str],
    ) -> str: ...

    def prompt_thinking_level(
        self,
        role: str,
        default_level: str,
        levels: Sequence[str],
        *,
        label: str = "thinking level",
        provider_note: str | None = None,
    ) -> str: ...

    def prompt_file_selection(self, files: Sequence[str], message: str) -> list[str]: ...

    def show_review(self, write_files: Sequence[str], keep_files: Sequence[str]) -> None: ...

    def info(self, message: str) -> None: ...

    def warn(self, message: str) -> None: ...

    def success(self, message: str) -> None: ...


class ConsoleSetupUI:
    """CLI setup UI that uses Rich for display and Typer for input."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def choose_mode(self) -> SetupMode:
        self.console.print("[bold]Choose setup mode[/bold]")
        self.console.print("1. Conversational setup")
        self.console.print("2. Use existing local files")
        choice = typer.prompt("Mode", default="1")
        return "conversational" if choice.strip() == "1" else "local"

    def show_audit(self, audit: WorkspaceAudit) -> None:
        table = Table(title="Workspace Audit")
        table.add_column("File", style="bold")
        table.add_column("Required")
        table.add_column("Status")
        table.add_column("Details")

        status_style = {
            "valid": "green",
            "missing": "yellow",
            "invalid": "red",
        }

        for entry in audit.files:
            style = status_style.get(entry.status, "white")
            table.add_row(
                entry.path,
                "yes" if entry.required else "no",
                f"[{style}]{entry.status}[/{style}]",
                entry.message or "—",
            )

        self.console.print(table)

    def prompt_workspace_action(self) -> WorkspaceAction:
        self.console.print("[bold]Existing workspace detected[/bold]")
        self.console.print("1. Keep valid files and only fill gaps")
        self.console.print("2. Regenerate selected setup files")
        self.console.print("3. Cancel")
        choice = typer.prompt("Action", default="1").strip()
        if choice == "2":
            return "regenerate"
        if choice == "3":
            return "cancel"
        return "keep"

    def prompt_yes_no(self, message: str, default: bool = True) -> bool:
        suffix = "Y/n" if default else "y/N"
        response = typer.prompt(f"{message} [{suffix}]", default="y" if default else "n")
        return response.strip().lower().startswith("y")

    def prompt_text(self, message: str, default: str | None = None) -> str:
        if default is None:
            return typer.prompt(message).strip()
        return typer.prompt(message, default=default).strip()

    def prompt_secret(self, message: str) -> str:
        return typer.prompt(message, hide_input=True).strip()

    def prompt_paragraph(self) -> str:
        self.console.print("[bold]Describe your research task[/bold]")
        return typer.prompt("Paragraph").strip()

    def prompt_model_choice(
        self,
        role: str,
        default_model: str,
        preset_models: Sequence[str],
    ) -> str:
        self.console.print(f"[bold]Choose {role} model[/bold]")
        default_choice = len(preset_models) + 1
        for index, model in enumerate(preset_models, start=1):
            self.console.print(f"{index}. {model}")
            if model == default_model:
                default_choice = index
        self.console.print(f"{len(preset_models) + 1}. Custom model ID")
        choice = typer.prompt("Model", default=str(default_choice)).strip()
        try:
            selected = int(choice)
        except ValueError:
            selected = default_choice
        if 1 <= selected <= len(preset_models):
            return preset_models[selected - 1]
        return typer.prompt("Custom model ID", default=default_model).strip()

    def prompt_thinking_level(
        self,
        role: str,
        default_level: str,
        levels: Sequence[str],
        *,
        label: str = "thinking level",
        provider_note: str | None = None,
    ) -> str:
        self.console.print(f"[bold]Choose {role} {label}[/bold]")
        if provider_note:
            self.console.print(provider_note)
        default_choice = 1
        for index, level in enumerate(levels, start=1):
            display = f"{level} (use provider default)" if level == "none" else level
            self.console.print(f"{index}. {display}")
            if level == default_level:
                default_choice = index
        choice = typer.prompt(label.title(), default=str(default_choice)).strip()
        try:
            selected = int(choice)
        except ValueError:
            selected = default_choice
        if 1 <= selected <= len(levels):
            return levels[selected - 1]
        return default_level

    def prompt_file_selection(self, files: Sequence[str], message: str) -> list[str]:
        self.console.print(message)
        for file_name in files:
            self.console.print(f"- {file_name}")
        raw = typer.prompt("Comma-separated file names", default="").strip()
        if not raw:
            return []
        wanted = {part.strip() for part in raw.split(",") if part.strip()}
        return [file_name for file_name in files if file_name in wanted]

    def show_review(self, write_files: Sequence[str], keep_files: Sequence[str]) -> None:
        table = Table(title="Setup Review")
        table.add_column("File", style="bold")
        table.add_column("Action")

        for file_name in write_files:
            table.add_row(file_name, "[green]write[/green]")
        for file_name in keep_files:
            table.add_row(file_name, "[dim]keep[/dim]")

        self.console.print(table)

    def info(self, message: str) -> None:
        self.console.print(message)

    def warn(self, message: str) -> None:
        self.console.print(f"[yellow]{message}[/yellow]")

    def success(self, message: str) -> None:
        self.console.print(f"[green]{message}[/green]")
