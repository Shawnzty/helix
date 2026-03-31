"""Typer CLI for Helix."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Optional

import typer
import yaml
from rich.console import Console
from rich.table import Table

from helix.config import (
    AgentConfig,
    GlobalConfig,
    load_global_config,
    load_workspace_config,
    resolve_config,
    save_workspace_config,
)
from helix.loop import HelixLoop
from helix.runs import get_best_run, get_frontier_runs, parse_tree_search

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(name="helix", help="Autonomous AI research framework.")
config_app = typer.Typer(help="Manage config.yaml.")
agents_app = typer.Typer(help="Manage agents in helix.toml.")
app.add_typer(config_app, name="config")
app.add_typer(agents_app, name="agents")

PathOption = Annotated[Path, typer.Option("--path", help="Workspace path.")]


# ---------------------------------------------------------------------------
# helix run / status / history / stop
# ---------------------------------------------------------------------------


@app.command()
def run(
    path: PathOption = Path("."),
    max_runs: Annotated[int, typer.Option("--max-runs", help="Maximum number of runs.")] = 100,
) -> None:
    """Run the helix loop."""
    workspace = path.resolve()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        global_cfg, workspace_cfg = resolve_config(workspace)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    loop = HelixLoop(workspace, global_cfg, workspace_cfg)
    loop.run(max_runs=max_runs)


@app.command()
def status(path: PathOption = Path(".")) -> None:
    """Show current research status."""
    workspace = path.resolve()
    nodes = parse_tree_search(workspace)

    if not nodes:
        console.print("[dim]No runs yet. tree_search.md is empty.[/dim]")
        return

    best = get_best_run(nodes)
    frontiers = get_frontier_runs(nodes)

    console.print(f"[bold]Total runs:[/bold] {len(nodes)}")
    if best:
        console.print(f"[bold green]Best:[/bold green] {best.number}. [{best.status}] {best.title}")
        if best.result:
            console.print(f"  result: {best.result}")
    if frontiers:
        console.print(f"[bold blue]Frontier ({len(frontiers)}):[/bold blue]")
        for f in frontiers:
            console.print(f"  {f.number}. {f.title}")


@app.command()
def history(
    path: PathOption = Path("."),
    last: Annotated[Optional[int], typer.Option("--last", help="Show last N runs.")] = None,
) -> None:
    """Show run history from tree_search.md."""
    workspace = path.resolve()
    nodes = parse_tree_search(workspace)

    if not nodes:
        console.print("[dim]No runs yet.[/dim]")
        return

    if last:
        nodes = nodes[-last:]

    table = Table(title="Run History")
    table.add_column("Run", style="bold")
    table.add_column("Status")
    table.add_column("Title")
    table.add_column("Result")

    for node in nodes:
        status_style = {
            "best": "green",
            "active": "cyan",
            "frontier": "blue",
            "dead-end": "dim",
        }.get(node.status.lower().replace("★ ", ""), "white")

        table.add_row(
            node.number,
            f"[{status_style}]{node.status}[/{status_style}]",
            node.title,
            node.result or "—",
        )

    console.print(table)


@app.command()
def stop(path: PathOption = Path(".")) -> None:
    """Signal the running helix loop to stop after the current step."""
    workspace = path.resolve()
    stop_file = workspace / ".helix" / "stop"
    stop_file.parent.mkdir(parents=True, exist_ok=True)
    stop_file.write_text("stop")
    console.print("[yellow]Stop signal written. The loop will stop after the current step.[/yellow]")


# ---------------------------------------------------------------------------
# helix config
# ---------------------------------------------------------------------------


@config_app.command("init")
def config_init(path: PathOption = Path(".")) -> None:
    """Create a default config.yaml."""
    workspace = path.resolve()
    config_path = workspace / "config.yaml"
    if config_path.exists():
        console.print("[yellow]config.yaml already exists.[/yellow]")
        return

    default = {
        "openai_api_key": "",
        "anthropic_api_key": "",
        "defaults": {
            "setup_model": "gpt-5.4",
            "master_cli": "claude",
            "master_model": "claude-opus-4.6",
            "researcher_cli": "codex",
            "researcher_model": "gpt-5.4",
            "claude_full_access_flag": "--dangerously-skip-permissions",
            "codex_full_access_flag": "--dangerously-bypass-approvals-and-sandbox",
            "codex_reasoning_level": "high",
            "agent_timeout_seconds": 3600,
        },
    }
    with config_path.open("w") as f:
        yaml.dump(default, f, default_flow_style=False, sort_keys=False)
    console.print(f"[green]Created {config_path}[/green]")


@config_app.command("show")
def config_show(path: PathOption = Path(".")) -> None:
    """Display current config (API keys masked)."""
    workspace = path.resolve()
    cfg = load_global_config(workspace / "config.yaml")

    def mask(key: str) -> str:
        if not key:
            return "(not set)"
        if len(key) > 12:
            return key[:8] + "..." + key[-4:]
        return "****"

    console.print(f"[bold]openai_api_key:[/bold] {mask(cfg.openai_api_key)}")
    console.print(f"[bold]anthropic_api_key:[/bold] {mask(cfg.anthropic_api_key)}")
    for k, v in cfg.defaults.items():
        console.print(f"[bold]{k}:[/bold] {v}")


@config_app.command("set")
def config_set(
    key: str,
    value: str,
    path: PathOption = Path("."),
) -> None:
    """Set a config value."""
    workspace = path.resolve()
    config_path = workspace / "config.yaml"

    data: dict = {}
    if config_path.exists():
        with config_path.open() as f:
            data = yaml.safe_load(f) or {}

    # Handle nested defaults.X keys
    if "." in key:
        parts = key.split(".", 1)
        data.setdefault(parts[0], {})[parts[1]] = value
    else:
        data[key] = value

    with config_path.open("w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    console.print(f"[green]Set {key} = {value}[/green]")


# ---------------------------------------------------------------------------
# helix agents
# ---------------------------------------------------------------------------


@agents_app.command("list")
def agents_list(path: PathOption = Path(".")) -> None:
    """List configured agents."""
    workspace = path.resolve()
    try:
        wc = load_workspace_config(workspace / "helix.toml")
    except FileNotFoundError:
        console.print("[red]helix.toml not found.[/red]")
        raise typer.Exit(1)

    table = Table(title="Agents")
    table.add_column("Name", style="bold")
    table.add_column("Role")
    table.add_column("CLI")
    table.add_column("Model")
    table.add_column("Description")

    for agent in wc.agents:
        table.add_row(agent.name, agent.role, agent.cli, agent.model, agent.description)

    console.print(table)


@agents_app.command("add")
def agents_add(
    name: Annotated[str, typer.Option("--name")],
    role: Annotated[str, typer.Option("--role")],
    cli: Annotated[str, typer.Option("--cli")] = "claude",
    model: Annotated[str, typer.Option("--model")] = "claude-opus-4.6",
    full_access_flag: Annotated[str, typer.Option("--full-access-flag")] = "--dangerously-skip-permissions",
    description: Annotated[str, typer.Option("--description")] = "",
    path: PathOption = Path("."),
) -> None:
    """Add an agent to helix.toml."""
    workspace = path.resolve()
    toml_path = workspace / "helix.toml"
    try:
        wc = load_workspace_config(toml_path)
    except FileNotFoundError:
        console.print("[red]helix.toml not found.[/red]")
        raise typer.Exit(1)

    agent = AgentConfig(
        name=name, role=role, cli=cli, model=model,
        full_access_flag=full_access_flag, description=description,
    )
    wc.agents.append(agent)

    # Re-validate
    try:
        wc.model_validate(wc.model_dump())
    except Exception as e:
        console.print(f"[red]Validation error: {e}[/red]")
        raise typer.Exit(1)

    save_workspace_config(toml_path, wc)
    console.print(f"[green]Added agent '{name}' ({role}).[/green]")


@agents_app.command("remove")
def agents_remove(
    name: Annotated[str, typer.Option("--name")],
    path: PathOption = Path("."),
) -> None:
    """Remove an agent from helix.toml."""
    workspace = path.resolve()
    toml_path = workspace / "helix.toml"
    try:
        wc = load_workspace_config(toml_path)
    except FileNotFoundError:
        console.print("[red]helix.toml not found.[/red]")
        raise typer.Exit(1)

    original_count = len(wc.agents)
    wc.agents = [a for a in wc.agents if a.name != name]

    if len(wc.agents) == original_count:
        console.print(f"[yellow]Agent '{name}' not found.[/yellow]")
        return

    # Re-validate
    try:
        wc.model_validate(wc.model_dump())
    except Exception as e:
        console.print(f"[red]Cannot remove — would break validation: {e}[/red]")
        raise typer.Exit(1)

    save_workspace_config(toml_path, wc)
    console.print(f"[green]Removed agent '{name}'.[/green]")
