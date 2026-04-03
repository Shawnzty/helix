"""Build context markdown files for each helix step."""

from __future__ import annotations

from pathlib import Path

from helix.models import RunState, SuccessEvaluation
from helix.selection import get_brainstorm_selection_path

MASTER_AGENT_FILE = "master_agent.md"
RESEARCHER_AGENT_FILE = "researcher_agent.md"


def _read_if_exists(path: Path) -> str:
    if path.exists():
        return path.read_text()
    return ""


def _read_required(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required instruction file not found: {path}")
    return path.read_text()


def _ensure_helix_dir(workspace: Path) -> Path:
    helix_dir = workspace / ".helix"
    helix_dir.mkdir(parents=True, exist_ok=True)
    return helix_dir


def get_agent_instruction_path(workspace: Path, role: str) -> Path:
    """Return the human-authored instruction file for an agent role."""
    if role == "master":
        return workspace / MASTER_AGENT_FILE
    if role == "researcher":
        return workspace / RESEARCHER_AGENT_FILE
    raise ValueError(f"Unknown agent role: {role}")


def validate_instruction_files(workspace: Path) -> None:
    """Ensure all required human-authored instruction files are present."""
    for role in ("master", "researcher"):
        _read_required(get_agent_instruction_path(workspace, role))


def _human_instruction_section(workspace: Path, role: str) -> str:
    instructions = _read_required(get_agent_instruction_path(workspace, role))
    return f"""## Human Agent Instructions

{instructions}

"""


def _success_check_section(success_evaluation: SuccessEvaluation | None) -> str:
    if success_evaluation is None:
        return ""

    lines = [
        "## Success Check",
        "",
        f"- Passed: {'yes' if success_evaluation.passed else 'no'}",
        f"- Summary: {success_evaluation.summary}",
    ]
    if success_evaluation.missing_metrics:
        missing = ", ".join(success_evaluation.missing_metrics)
        lines.append(f"- Missing metrics: {missing}")
    if success_evaluation.failed_conditions:
        failed = "; ".join(success_evaluation.failed_conditions)
        lines.append(f"- Failed conditions: {failed}")

    return "\n".join(lines) + "\n\n"


def build_brainstorm_context(workspace: Path) -> Path:
    """Build context for master brainstorm step.

    Contains: goal.md + tree_search.md + instructions.
    """
    helix_dir = _ensure_helix_dir(workspace)
    staged_output_path = get_brainstorm_selection_path(workspace)

    goal = _read_if_exists(workspace / "goal.md")
    tree = _read_if_exists(workspace / "tree_search.md")

    # Build optional resources section
    resources_lines: list[str] = []
    ref_dir = workspace / "reference"
    if ref_dir.is_dir() and any(ref_dir.iterdir()):
        files = [f.name for f in ref_dir.iterdir() if f.is_file()]
        resources_lines.append(
            f"- **Reference documents** are available in the `reference/` directory: "
            f"{', '.join(files)}. Read any that are relevant to your brainstorming."
        )

    resources_section = ""
    if resources_lines:
        resources_section = "\n" + "\n".join(resources_lines) + "\n"

    context = f"""# Brainstorm — Select The Next Run

{_human_instruction_section(workspace, "master")}## Your Task

You are the **master** agent. Read the full goal and research tree below. Reason over the entire search landscape, then choose exactly one next branch to execute.

You may either:
- Deepen any existing branch whose node is not marked `[dead-end]`
- Start a new top-level research direction

Do **not** update `tree_search.md` during Brainstorm. The framework will validate your selection, assign the final run number, and then materialize `runs/{{id}}/idea.md`.

## Capabilities

You have full computer access. Use your judgment — if any of these would help, do them:
- **Web search**: Search the web for papers, documentation, benchmarks, or techniques relevant to the research goal. Do this when you need external knowledge to inform your next idea.
- **Read reference documents**: If a `reference/` directory exists, read files in it that are relevant.
- **Read project files**: Explore the codebase, data, or previous run artifacts to understand the current state.

These are optional — only use them when they would genuinely help you make a better decision. Don't search or read every time.
{resources_section}
## Goal

{goal}

## Research Tree

{tree}

## Output

Write your staged brainstorm output to `{staged_output_path.relative_to(workspace)}`.

The file must start with YAML front matter:

```yaml
---
mode: child
parent: "2.1"
title: "Your short experiment title"
rationale: "Why this is the best next branch"
---
```

Use `mode: top_level` and omit `parent` when starting a new top-level direction.

After the YAML front matter, write the normal idea markdown with:
1. Your reasoning for choosing this direction
2. A clear description of the experiment to run
3. Expected outcomes and how to measure success
"""

    out = helix_dir / "context_brainstorm.md"
    out.write_text(context)
    return out


def build_execute_plan_context(workspace: Path, run_id: str) -> Path:
    """Build context for the researcher planning step."""
    helix_dir = _ensure_helix_dir(workspace)
    tree_number = RunState.id_to_tree_number(run_id)

    idea = _read_if_exists(workspace / "runs" / run_id / "idea.md")
    goal = _read_if_exists(workspace / "goal.md")

    context = f"""# Execute Plan — Run {tree_number}

{_human_instruction_section(workspace, "researcher")}## Your Task

You are the **researcher** agent. Your only job in this step is to write `runs/{run_id}/plan.md`.

Do **not** implement yet. Read the idea and goal below, then produce a concrete execution plan.

Your plan should include:
1. Exact files to create or modify
2. Commands to run
3. Order of operations
4. Expected outputs and metrics
5. Risks, checkpoints, or validation steps

You may read more workspace files on demand if needed, but Helix is only inlining the files below for this planning step.

## Idea

{idea}

## Goal & Constraints

{goal}

## Output File

`runs/{run_id}/plan.md`
"""

    out = helix_dir / "context_execute_plan.md"
    out.write_text(context)
    return out


def build_execute_run_context(workspace: Path, run_id: str) -> Path:
    """Build context for the researcher execution step."""
    helix_dir = _ensure_helix_dir(workspace)
    tree_number = RunState.id_to_tree_number(run_id)

    plan = _read_if_exists(workspace / "runs" / run_id / "plan.md")

    context = f"""# Execute Run — Run {tree_number}

{_human_instruction_section(workspace, "researcher")}## Your Task

You are the **researcher** agent. Execute the plan below.

Use `runs/{run_id}/plan.md` as the source of truth for this step. If reality diverges from the plan, update `plan.md` before continuing.

Then implement the work, run experiments, and collect results.

Finally, write `runs/{run_id}/results.md` with:
1. What was done (summary)
2. Metrics in a JSON code block:
```json
{{"metric_name": value, ...}}
```
3. Observations and analysis

The framework will compare these JSON metrics against the YAML block under `## Success Criteria` in `goal.md`. If you need to review the goal again, read `goal.md` from the workspace on demand.

**IMPORTANT**: If any single program execution would take longer than 1 hour, break it into smaller steps or find a faster approach. Check intermediate results and report partial progress.

## Plan

{plan}

## Output Files

1. Implementation (code in `runs/{run_id}/codes/`, data in `runs/{run_id}/data/`)
2. `runs/{run_id}/results.md` (write last)
"""

    out = helix_dir / "context_execute_run.md"
    out.write_text(context)
    return out


def build_reflect_context(
    workspace: Path,
    run_id: str,
    success_evaluation: SuccessEvaluation | None = None,
) -> Path:
    """Build context for master reflect step.

    Contains: goal.md + idea.md + plan.md + results.md + tree_search.md + instructions.
    """
    helix_dir = _ensure_helix_dir(workspace)
    tree_number = RunState.id_to_tree_number(run_id)

    goal = _read_if_exists(workspace / "goal.md")
    results = _read_if_exists(workspace / "runs" / run_id / "results.md")
    idea = _read_if_exists(workspace / "runs" / run_id / "idea.md")
    plan = _read_if_exists(workspace / "runs" / run_id / "plan.md")
    tree = _read_if_exists(workspace / "tree_search.md")

    context = f"""# Reflect — Run {tree_number}

{_human_instruction_section(workspace, "master")}## Your Task

You are the **master** agent. Review the results of run {tree_number} and:

1. Write `runs/{run_id}/reflect.md` with your analysis:
   - Did the experiment succeed or fail?
   - What was learned?
   - What should be tried next?

2. Update `tree_search.md`:
   - Update this run's node with status, result summary, and reflection
   - Mark as [★ best] if it's the new best result (update previous best to [active])
   - Mark as [dead-end] if the approach didn't work
   - Mark as [active] if it's promising and worth exploring further
   - Add [frontier] child nodes for promising next directions
   - Keep all existing nodes — never delete history

## Goal & Constraints

{goal}

## Idea (what was attempted)

{idea}

## Plan

{plan}

## Results

{results}

{_success_check_section(success_evaluation)}## Current Research Tree

{tree}

## Format for tree_search.md nodes

```
N. [status] Title
   idea: one-sentence summary
   result: one-sentence summary with key metric
   reflect: one-sentence takeaway
```

Indent children with 2 spaces per level. Number children as N.1, N.2, etc.
"""

    out = helix_dir / "context_reflect.md"
    out.write_text(context)
    return out
