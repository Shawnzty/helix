"""Pydantic data models for Helix."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RunState(BaseModel):
    run_id: str  # filesystem id, e.g. "2_1_1"
    tree_number: str  # display id, e.g. "2.1.1"
    status: str  # "active", "dead-end", "frontier", "best", etc.
    parent_id: str | None = None

    @staticmethod
    def id_to_tree_number(run_id: str) -> str:
        """Convert filesystem id '2_1_1' to tree number '2.1.1'."""
        return run_id.replace("_", ".")

    @staticmethod
    def tree_number_to_id(tree_number: str) -> str:
        """Convert tree number '2.1.1' to filesystem id '2_1_1'."""
        return tree_number.replace(".", "_")

    @staticmethod
    def parent_from_id(run_id: str) -> str | None:
        """Return parent id: '2_1_1' → '2_1', '2' → None."""
        parts = run_id.split("_")
        if len(parts) <= 1:
            return None
        return "_".join(parts[:-1])


class AgentRun(BaseModel):
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_seconds: float = 0.0


class ParsedResults(BaseModel):
    metrics: dict[str, Any] = {}
    observations: str = ""


class TreeNode(BaseModel):
    number: str  # e.g. "2.1.1"
    status: str  # e.g. "active", "dead-end", "frontier", "★ best"
    title: str  # one-line summary
    idea: str = ""
    result: str = ""
    reflect: str = ""
    depth: int = 0
    children: list[TreeNode] = []
