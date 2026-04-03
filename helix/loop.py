"""The 3-step helix loop: Brainstorm → Execute → Reflect."""

from __future__ import annotations

import logging
import signal
import shutil
from pathlib import Path

from rich.console import Console

from helix.agents import spawn_agent
from helix.config import GlobalConfig, WorkspaceConfig
from helix.context import (
    build_brainstorm_context,
    build_execute_plan_context,
    build_execute_run_context,
    build_reflect_context,
    validate_instruction_files,
)
from helix.models import BranchSelection, SuccessEvaluation
from helix.runs import (
    create_run_folder,
    increment_run_id,
    next_child_run_id,
    next_top_level_run_id,
    parse_results,
    parse_tree_search,
)
from helix.selection import (
    BrainstormSelectionError,
    get_brainstorm_selection_path,
    parse_brainstorm_selection,
    validate_branch_selection,
)
from helix.success import evaluate_success, load_success_criteria

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

    def _assign_run_id(self, selection: BranchSelection) -> str:
        """Compute the concrete run ID from a validated branch selection."""
        if selection.mode == "top_level":
            run_id = next_top_level_run_id(self.workspace)
        else:
            assert selection.parent is not None
            run_id = next_child_run_id(self.workspace, selection.parent)

        while run_id in self._failed_run_ids:
            run_id = increment_run_id(run_id)

        return run_id

    def _move_brainstorm_logs(self, temp_log_dir: Path, run_dir: Path) -> None:
        """Move staged brainstorm logs into the final run folder."""
        if not temp_log_dir.exists():
            return

        target_dir = run_dir / "logs" / "brainstorm"
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_log_dir), str(target_dir))

    def run(self, max_runs: int = 100) -> None:
        """Run the helix loop."""
        validate_instruction_files(self.workspace)
        success_criteria = load_success_criteria(self.workspace)
        self._install_signal_handlers()
        timeout = self.global_config.get_default("agent_timeout_seconds") or 3600
        master = self.workspace_config.get_master()
        researcher = self.workspace_config.get_researcher()

        try:
            for run_count in range(1, max_runs + 1):
                if self._shutdown_requested or self._check_stop_file():
                    break

                console.rule(f"[bold blue]Cycle {run_count}[/bold blue] ({run_count}/{max_runs})")
                staged_brainstorm_path = get_brainstorm_selection_path(self.workspace)
                if staged_brainstorm_path.exists():
                    staged_brainstorm_path.unlink()
                brainstorm_log_dir = self.workspace / ".helix" / "logs" / f"brainstorm_{run_count}"
                if brainstorm_log_dir.exists():
                    shutil.rmtree(brainstorm_log_dir)

                # --- Step 1: Brainstorm ---
                console.print("[bold cyan]Step 1: Brainstorm[/bold cyan]")
                try:
                    ctx = build_brainstorm_context(self.workspace)
                    result = spawn_agent(master, ctx, brainstorm_log_dir, timeout=timeout)
                    if result.exit_code != 0:
                        console.print(f"[red]Master brainstorm failed (exit {result.exit_code})[/red]")
                        if result.stderr:
                            console.print(f"[dim red]stderr: {result.stderr[:500]}[/dim red]")
                        if result.stdout:
                            console.print(f"[dim red]stdout: {result.stdout[:500]}[/dim red]")
                        logger.error("Brainstorm failed in cycle %d: exit %d", run_count, result.exit_code)
                        continue

                    selection, _idea_body = parse_brainstorm_selection(staged_brainstorm_path)
                    nodes = parse_tree_search(self.workspace)
                    validate_branch_selection(selection, nodes)
                    run_id = self._assign_run_id(selection)
                    tree_number = run_id.replace("_", ".")
                    run_dir = create_run_folder(self.workspace, run_id)
                    log_dir = run_dir / "logs"
                    (run_dir / "idea.md").write_text(staged_brainstorm_path.read_text())
                    self._move_brainstorm_logs(brainstorm_log_dir, run_dir)
                    console.print(
                        f"[green]Selected run {tree_number}[/green]: {selection.title}"
                    )
                except BrainstormSelectionError as exc:
                    logger.error("Invalid brainstorm selection in cycle %d: %s", run_count, exc)
                    console.print(f"[red]{exc}[/red]")
                    continue
                except Exception:
                    logger.exception("Brainstorm crashed in cycle %d", run_count)
                    console.print("[red]Master brainstorm crashed — skipping cycle[/red]")
                    continue

                if self._shutdown_requested or self._check_stop_file():
                    break

                success_evaluation: SuccessEvaluation | None = None

                # --- Step 2: Execute ---
                console.print("[bold cyan]Step 2: Execute[/bold cyan]")
                plan_path = self.workspace / "runs" / run_id / "plan.md"
                plan_failed = False
                plan_missing_warned = False

                console.print("[cyan]  Plan[/cyan]")
                try:
                    ctx = build_execute_plan_context(self.workspace, run_id)
                    result = spawn_agent(researcher, ctx, log_dir / "execute_plan", timeout=timeout)
                    if result.exit_code != 0:
                        console.print(f"[red]Researcher plan failed (exit {result.exit_code})[/red]")
                        if result.stderr:
                            console.print(f"[dim red]stderr: {result.stderr[:500]}[/dim red]")
                        if result.stdout:
                            console.print(f"[dim red]stdout: {result.stdout[:500]}[/dim red]")
                        logger.error("Plan failed for run %s: exit %d", run_id, result.exit_code)
                        plan_failed = True
                except Exception:
                    logger.exception("Execute plan crashed for run %s", run_id)
                    console.print("[red]Researcher plan crashed[/red]")
                    plan_failed = True

                if not plan_path.exists():
                    console.print(
                        f"[yellow]Warning: plan.md missing for run {tree_number} — skipping Execute Run[/yellow]"
                    )
                    self._failed_run_ids.add(run_id)
                    plan_failed = True
                    plan_missing_warned = True

                if not plan_failed:
                    if self._shutdown_requested or self._check_stop_file():
                        break

                    console.print("[cyan]  Run[/cyan]")
                    try:
                        ctx = build_execute_run_context(self.workspace, run_id)
                        result = spawn_agent(researcher, ctx, log_dir / "execute_run", timeout=timeout)
                        if result.exit_code != 0:
                            console.print(f"[red]Researcher run failed (exit {result.exit_code})[/red]")
                            if result.stderr:
                                console.print(f"[dim red]stderr: {result.stderr[:500]}[/dim red]")
                            if result.stdout:
                                console.print(f"[dim red]stdout: {result.stdout[:500]}[/dim red]")
                            logger.error("Run failed for run %s: exit %d", run_id, result.exit_code)
                            # Still try to reflect on partial results

                        parsed = parse_results(self.workspace, run_id)
                        if parsed.metrics:
                            console.print(f"  Metrics: {parsed.metrics}")
                        success_evaluation = evaluate_success(success_criteria, parsed.metrics)
                        if success_evaluation.passed:
                            console.print(f"[green]  Success check: {success_evaluation.summary}[/green]")
                        elif success_evaluation.missing_metrics:
                            console.print(f"[yellow]  Success check: {success_evaluation.summary}[/yellow]")
                        else:
                            console.print(f"[yellow]  Success check: {success_evaluation.summary}[/yellow]")
                    except Exception:
                        logger.exception("Execute run crashed for run %s", run_id)
                        console.print("[red]Researcher run crashed[/red]")
                        success_evaluation = evaluate_success(success_criteria, {})
                        console.print(f"[yellow]  Success check: {success_evaluation.summary}[/yellow]")
                else:
                    console.print("[yellow]Skipping Execute Run because the planning step did not finish cleanly.[/yellow]")
                    success_evaluation = evaluate_success(success_criteria, {})
                    console.print(f"[yellow]  Success check: {success_evaluation.summary}[/yellow]")

                if self._shutdown_requested or self._check_stop_file():
                    break

                # --- Step 3: Reflect ---
                console.print("[bold cyan]Step 3: Reflect[/bold cyan]")
                try:
                    ctx = build_reflect_context(
                        self.workspace,
                        run_id,
                        success_evaluation=success_evaluation,
                    )
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
                if not plan_path.exists() and not plan_missing_warned:
                    console.print(f"[yellow]Warning: plan.md missing for run {tree_number} — marking as incomplete[/yellow]")
                    self._failed_run_ids.add(run_id)

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

                console.print(f"[green]Run {tree_number} complete.[/green]\n")

                if success_evaluation and success_evaluation.missing_metrics:
                    console.print(
                        f"[yellow]Run {tree_number} missing metrics required for success checking — marked as incomplete.[/yellow]"
                    )
                    self._failed_run_ids.add(run_id)

                if success_evaluation and success_evaluation.passed:
                    console.print("[bold green]Success criteria met — stopping after this run.[/bold green]")
                    break

        finally:
            self._restore_signal_handlers()

        # Summary
        total = run_count if 'run_count' in dir() else 0
        failed = len(self._failed_run_ids)
        console.print(f"[bold green]Helix loop finished.[/bold green] Runs attempted: {total}, incomplete: {failed}")
