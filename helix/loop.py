"""The 3-step helix loop: Brainstorm → Execute → Reflect."""

from __future__ import annotations

import logging
import signal
from pathlib import Path

from rich.console import Console

from helix.agents import spawn_agent
from helix.config import GlobalConfig, WorkspaceConfig
from helix.context import (
    build_brainstorm_context,
    build_execute_context,
    build_reflect_context,
    generate_agent_md,
)
from helix.runs import (
    create_run_folder,
    get_frontier_runs,
    next_run_id,
    parse_results,
    parse_tree_search,
)

logger = logging.getLogger(__name__)
console = Console()


class HelixLoop:
    """Orchestrates the brainstorm → execute → reflect cycle."""

    def __init__(
        self,
        workspace: Path,
        global_config: GlobalConfig,
        workspace_config: WorkspaceConfig,
    ) -> None:
        self.workspace = workspace
        self.global_config = global_config
        self.workspace_config = workspace_config
        self._shutdown_requested = False
        self._original_sigint = None
        self._original_sigterm = None
        self._failed_run_ids: set[str] = set()  # Track failed runs to avoid infinite retry

    def _install_signal_handlers(self) -> None:
        self._original_sigint = signal.getsignal(signal.SIGINT)
        self._original_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _restore_signal_handlers(self) -> None:
        if self._original_sigint is not None:
            signal.signal(signal.SIGINT, self._original_sigint)
        if self._original_sigterm is not None:
            signal.signal(signal.SIGTERM, self._original_sigterm)

    def _handle_signal(self, signum: int, frame: object) -> None:
        sig_name = signal.Signals(signum).name
        console.print(f"\n[yellow]Received {sig_name} — finishing current step, then stopping...[/yellow]")
        logger.info("Received %s, requesting graceful shutdown", sig_name)
        self._shutdown_requested = True

    def _check_stop_file(self) -> bool:
        stop_file = self.workspace / ".helix" / "stop"
        if stop_file.exists():
            stop_file.unlink()
            console.print("[yellow]Stop file detected — shutting down.[/yellow]")
            return True
        return False

    def _determine_run_id(self) -> str:
        """Pick a frontier node or create a new top-level run."""
        nodes = parse_tree_search(self.workspace)
        frontiers = get_frontier_runs(nodes)

        if frontiers:
            # Pick the first frontier node that hasn't already failed
            for frontier in frontiers:
                run_id = frontier.number.replace(".", "_")
                if run_id not in self._failed_run_ids:
                    logger.info("Picked frontier run: %s", frontier.number)
                    return run_id

        # No usable frontier — create a new top-level run
        # Account for both existing tree nodes and previously failed IDs
        run_id = next_run_id(self.workspace, parent_id=None)
        while run_id in self._failed_run_ids:
            run_id = str(int(run_id) + 1)
        return run_id

    def run(self, max_runs: int = 100) -> None:
        """Run the helix loop."""
        self._install_signal_handlers()
        timeout = self.global_config.get_default("agent_timeout_seconds") or 3600
        master = self.workspace_config.get_master()
        researcher = self.workspace_config.get_researcher()

        try:
            for run_count in range(1, max_runs + 1):
                if self._shutdown_requested or self._check_stop_file():
                    break

                run_id = self._determine_run_id()
                tree_number = run_id.replace("_", ".")
                console.rule(f"[bold blue]Run {tree_number}[/bold blue] ({run_count}/{max_runs})")

                run_dir = create_run_folder(self.workspace, run_id)
                log_dir = run_dir / "logs"

                # --- Step 1: Brainstorm ---
                console.print("[bold cyan]Step 1: Brainstorm[/bold cyan]")
                try:
                    ctx = build_brainstorm_context(self.workspace, run_id)
                    result = spawn_agent(master, ctx, log_dir / "brainstorm", timeout=timeout)
                    if result.exit_code != 0:
                        console.print(f"[red]Master brainstorm failed (exit {result.exit_code})[/red]")
                        if result.stderr:
                            console.print(f"[dim red]stderr: {result.stderr[:500]}[/dim red]")
                        if result.stdout:
                            console.print(f"[dim red]stdout: {result.stdout[:500]}[/dim red]")
                        logger.error("Brainstorm failed for run %s: exit %d", run_id, result.exit_code)
                        self._failed_run_ids.add(run_id)
                        continue
                except Exception:
                    logger.exception("Brainstorm crashed for run %s", run_id)
                    console.print("[red]Master brainstorm crashed — skipping run[/red]")
                    self._failed_run_ids.add(run_id)
                    continue

                if self._shutdown_requested or self._check_stop_file():
                    break

                # --- Step 2: Execute ---
                console.print("[bold cyan]Step 2: Execute[/bold cyan]")
                try:
                    ctx = build_execute_context(self.workspace, run_id)
                    result = spawn_agent(researcher, ctx, log_dir / "execute", timeout=timeout)
                    if result.exit_code != 0:
                        console.print(f"[red]Researcher execute failed (exit {result.exit_code})[/red]")
                        if result.stderr:
                            console.print(f"[dim red]stderr: {result.stderr[:500]}[/dim red]")
                        if result.stdout:
                            console.print(f"[dim red]stdout: {result.stdout[:500]}[/dim red]")
                        logger.error("Execute failed for run %s: exit %d", run_id, result.exit_code)
                        # Still try to reflect on partial results

                    # Parse results if available
                    parsed = parse_results(self.workspace, run_id)
                    if parsed.metrics:
                        console.print(f"  Metrics: {parsed.metrics}")
                except Exception:
                    logger.exception("Execute crashed for run %s", run_id)
                    console.print("[red]Researcher execute crashed[/red]")

                if self._shutdown_requested or self._check_stop_file():
                    break

                # --- Step 3: Reflect ---
                console.print("[bold cyan]Step 3: Reflect[/bold cyan]")
                try:
                    ctx = build_reflect_context(self.workspace, run_id)
                    result = spawn_agent(master, ctx, log_dir / "reflect", timeout=timeout)
                    if result.exit_code != 0:
                        console.print(f"[red]Master reflect failed (exit {result.exit_code})[/red]")
                        if result.stderr:
                            console.print(f"[dim red]stderr: {result.stderr[:500]}[/dim red]")
                        if result.stdout:
                            console.print(f"[dim red]stdout: {result.stdout[:500]}[/dim red]")
                        logger.error("Reflect failed for run %s: exit %d", run_id, result.exit_code)
                except Exception:
                    logger.exception("Reflect crashed for run %s", run_id)
                    console.print("[red]Master reflect crashed[/red]")

                # --- Post-run validation ---
                # Check if critical files were actually produced
                results_path = self.workspace / "runs" / run_id / "results.md"
                if not results_path.exists():
                    console.print(f"[yellow]Warning: results.md missing for run {tree_number} — marking as incomplete[/yellow]")
                    self._failed_run_ids.add(run_id)

                # Check if tree_search.md was actually updated for this run
                nodes_after = parse_tree_search(self.workspace)
                this_node = next((n for n in nodes_after if n.number == tree_number), None)
                if this_node and this_node.result in ("(pending)", ""):
                    console.print(f"[yellow]Warning: tree_search.md not updated for run {tree_number} — marking as incomplete[/yellow]")
                    self._failed_run_ids.add(run_id)

                # Regenerate CLAUDE.md / AGENTS.md
                generate_agent_md(self.workspace)
                console.print(f"[green]Run {tree_number} complete.[/green]\n")

        finally:
            self._restore_signal_handlers()

        # Summary
        total = run_count if 'run_count' in dir() else 0
        failed = len(self._failed_run_ids)
        console.print(f"[bold green]Helix loop finished.[/bold green] Runs attempted: {total}, incomplete: {failed}")
