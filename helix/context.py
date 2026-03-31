"""Build context markdown files for each helix step."""

from __future__ import annotations

import logging
from pathlib import Path

from helix.models import RunState

logger = logging.getLogger(__name__)


def _read_if_exists(path: Path) -> str:
    if path.exists():
        return path.read_text()
    return ""


def _ensure_helix_dir(workspace: Path) -> Path:
    helix_dir = workspace / ".helix"
    helix_dir.mkdir(parents=True, exist_ok=True)
    return helix_dir


def build_brainstorm_context(workspace: Path, run_id: str) -> Path:
    """Build context for master brainstorm step.

    Contains: goal.md + tree_search.md + instructions.
    """
    helix_dir = _ensure_helix_dir(workspace)
    tree_number = RunState.id_to_tree_number(run_id)

    goal = _read_if_exists(workspace / "goal.md")
    tree = _read_if_exists(workspace / "tree_search.md")
    reference_note = ""
    ref_dir = workspace / "reference"
    if ref_dir.is_dir() and any(ref_dir.iterdir()):
        files = [f.name for f in ref_dir.iterdir() if f.is_file()]
        reference_note = (
            f"\n\n## Reference Documents\n\n"
            f"The following reference documents are available in the `reference/` directory: {', '.join(files)}. "
            f"Read them if they would help inform your brainstorming.\n"
        )

    context = f"""# Brainstorm — Run {tree_number}

## Your Task

You are the **master** agent. Read the goal and research tree below. Decide whether to:
- Deepen an existing branch (pick a [frontier] node or extend an [active] branch)
- Start a new top-level research direction

Then write your reasoning and proposed idea to `runs/{run_id}/idea.md`.

## Goal

{goal}

## Research Tree

{tree}
{reference_note}
## Output

Write `runs/{run_id}/idea.md` with:
1. Your reasoning for choosing this direction
2. A clear description of the experiment to run
3. Expected outcomes and how to measure success
"""

    out = helix_dir / "context_brainstorm.md"
    out.write_text(context)
    return out


def build_execute_context(workspace: Path, run_id: str) -> Path:
    """Build context for researcher execute step.

    Contains: idea.md + goal.md + instructions (plan-first).
    """
    helix_dir = _ensure_helix_dir(workspace)
    tree_number = RunState.id_to_tree_number(run_id)

    idea = _read_if_exists(workspace / "runs" / run_id / "idea.md")
    goal = _read_if_exists(workspace / "goal.md")

    context = f"""# Execute — Run {tree_number}

## Your Task

You are the **researcher** agent. Implement the idea below.

**MANDATORY: Write `runs/{run_id}/plan.md` FIRST** before making any changes.
Your plan should include: exact files to create/modify, commands to run, order of operations, expected outputs.

Then execute the plan: write code, run experiments, collect results.

Finally, write `runs/{run_id}/results.md` with:
1. What was done (summary)
2. Metrics in a JSON code block:
```json
{{"metric_name": value, ...}}
```
3. Observations and analysis

**IMPORTANT**: If any single program execution would take longer than 1 hour, break it into smaller steps or find a faster approach. Check intermediate results and report partial progress.

## Idea

{idea}

## Goal & Constraints

{goal}

## Output Files

1. `runs/{run_id}/plan.md` (MANDATORY, write first)
2. Implementation (code in `runs/{run_id}/codes/`, data in `runs/{run_id}/data/`)
3. `runs/{run_id}/results.md` (write last)
"""

    out = helix_dir / "context_execute.md"
    out.write_text(context)
    return out


def build_reflect_context(workspace: Path, run_id: str) -> Path:
    """Build context for master reflect step.

    Contains: results.md + idea.md + tree_search.md + instructions.
    """
    helix_dir = _ensure_helix_dir(workspace)
    tree_number = RunState.id_to_tree_number(run_id)

    results = _read_if_exists(workspace / "runs" / run_id / "results.md")
    idea = _read_if_exists(workspace / "runs" / run_id / "idea.md")
    tree = _read_if_exists(workspace / "tree_search.md")

    context = f"""# Reflect — Run {tree_number}

## Your Task

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

## Idea (what was attempted)

{idea}

## Results

{results}

## Current Research Tree

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


def generate_agent_md(workspace: Path) -> None:
    """Generate CLAUDE.md and AGENTS.md at workspace root from research memory."""
    goal = _read_if_exists(workspace / "goal.md")
    tree = _read_if_exists(workspace / "tree_search.md")

    content = f"""# Project Context (Auto-generated by Helix)

## Goal

{goal}

## Research Progress

{tree}
"""

    (workspace / "CLAUDE.md").write_text(content)
    (workspace / "AGENTS.md").write_text(content)
    logger.info("Regenerated CLAUDE.md and AGENTS.md")
