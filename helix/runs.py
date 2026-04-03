"""Run folder management and tree_search.md parsing."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from helix.models import ParsedResults, RunState, TreeNode

logger = logging.getLogger(__name__)

# Regex for tree_search.md parsing
# Matches lines like: "  2.1.1. [★ best] Muon + cosine + warmup"
_NODE_RE = re.compile(
    r"^(\s*)(\d+(?:\.\d+)*)\.\s+\[([^\]]+)\]\s+(.*)$"
)
# Matches lines like: "   idea: replace O(n²) attention"
_FIELD_RE = re.compile(
    r"^\s+(idea|result|reflect):\s+(.*)$"
)


def create_run_folder(workspace: Path, run_id: str) -> Path:
    """Create runs/{run_id}/ with standard subdirectories."""
    run_dir = workspace / "runs" / run_id
    for subdir in ("codes", "data", "logs"):
        (run_dir / subdir).mkdir(parents=True, exist_ok=True)
    logger.info("Created run folder: %s", run_dir)
    return run_dir


def parse_results(workspace: Path, run_id: str) -> ParsedResults:
    """Parse runs/{run_id}/results.md — extract JSON metrics block."""
    results_path = workspace / "runs" / run_id / "results.md"
    if not results_path.exists():
        logger.warning("results.md not found for run %s", run_id)
        return ParsedResults()

    text = results_path.read_text()

    # Extract JSON from fenced code block
    metrics: dict = {}
    json_match = re.search(r"```json\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if json_match:
        try:
            metrics = json.loads(json_match.group(1))
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON metrics in run %s", run_id)

    # Everything outside the JSON block is observations
    observations = text
    if json_match:
        observations = text[:json_match.start()] + text[json_match.end():]
    observations = observations.strip()

    return ParsedResults(metrics=metrics, observations=observations)


def parse_tree_search(workspace: Path) -> list[TreeNode]:
    """Parse tree_search.md into a flat list of TreeNode objects."""
    tree_path = workspace / "tree_search.md"
    if not tree_path.exists():
        return []

    text = tree_path.read_text()
    nodes: list[TreeNode] = []
    current_node: TreeNode | None = None

    for line in text.splitlines():
        node_match = _NODE_RE.match(line)
        if node_match:
            indent, number, status, title = node_match.groups()
            depth = number.count(".")
            current_node = TreeNode(
                number=number,
                status=status.strip(),
                title=title.strip(),
                depth=depth,
            )
            nodes.append(current_node)
            continue

        if current_node:
            field_match = _FIELD_RE.match(line)
            if field_match:
                field_name, field_value = field_match.groups()
                setattr(current_node, field_name, field_value.strip())

    return nodes


def get_best_run(nodes: list[TreeNode]) -> TreeNode | None:
    """Find the node marked as best."""
    for node in nodes:
        if "best" in node.status.lower():
            return node
    return None


def get_frontier_runs(nodes: list[TreeNode]) -> list[TreeNode]:
    """Get all frontier nodes."""
    return [n for n in nodes if n.status.lower() == "frontier"]


def get_node_by_number(nodes: list[TreeNode], tree_number: str) -> TreeNode | None:
    """Fetch a tree node by its display number."""
    return next((node for node in nodes if node.number == tree_number), None)


def is_dead_end(node: TreeNode) -> bool:
    """Return True when a node is marked as a dead end."""
    return "dead-end" in node.status.lower()


def next_top_level_run_id(workspace: Path) -> str:
    """Compute the next top-level run ID."""
    nodes = parse_tree_search(workspace)
    top_level = [int(n.number) for n in nodes if "." not in n.number]
    next_num = max(top_level, default=0) + 1
    return str(next_num)


def next_child_run_id(workspace: Path, parent_tree_number: str) -> str:
    """Compute the next child run ID for a parent tree number like '2.1'."""
    nodes = parse_tree_search(workspace)
    prefix = parent_tree_number + "."
    children = [
        int(n.number.split(".")[-1])
        for n in nodes
        if n.number.startswith(prefix) and n.number.count(".") == parent_tree_number.count(".") + 1
    ]
    next_child = max(children, default=0) + 1
    return RunState.tree_number_to_id(f"{parent_tree_number}.{next_child}")


def increment_run_id(run_id: str) -> str:
    """Increment the final segment of a run ID, preserving its parent path."""
    if "_" not in run_id:
        return str(int(run_id) + 1)

    parts = run_id.split("_")
    parts[-1] = str(int(parts[-1]) + 1)
    return "_".join(parts)


def next_run_id(workspace: Path, parent_id: str | None = None) -> str:
    """Compute the next run ID.

    If parent_id is given, find max child and increment.
    Otherwise, find max top-level number and increment.
    """
    if parent_id is None:
        return next_top_level_run_id(workspace)

    # Next child of parent
    return next_child_run_id(workspace, RunState.id_to_tree_number(parent_id))
