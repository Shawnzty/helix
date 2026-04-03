"""Pydantic data models for Helix."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
    metrics: dict[str, Any] = Field(default_factory=dict)
    observations: str = ""


class TreeNode(BaseModel):
    number: str  # e.g. "2.1.1"
    status: str  # e.g. "active", "dead-end", "frontier", "★ best"
    title: str  # one-line summary
    idea: str = ""
    result: str = ""
    reflect: str = ""
    depth: int = 0
    children: list[TreeNode] = Field(default_factory=list)


class Criterion(BaseModel):
    metric: str
    op: str
    value: Any

    @field_validator("metric")
    @classmethod
    def _validate_metric(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("metric must not be empty")
        return value

    @field_validator("op")
    @classmethod
    def _validate_op(cls, value: str) -> str:
        if value not in {"<", "<=", ">", ">=", "==", "!="}:
            raise ValueError(f"unsupported operator: {value}")
        return value

    def describe(self) -> str:
        return f"{self.metric} {self.op} {self.value!r}"


class SuccessCriteria(BaseModel):
    all: list[Criterion] | None = None
    any: list[Criterion] | None = None

    @model_validator(mode="after")
    def _validate_mode(self) -> SuccessCriteria:
        has_all = self.all is not None
        has_any = self.any is not None

        if has_all == has_any:
            raise ValueError("success criteria must define exactly one of 'all' or 'any'")
        if has_all and not self.all:
            raise ValueError("'all' must contain at least one criterion")
        if has_any and not self.any:
            raise ValueError("'any' must contain at least one criterion")
        return self

    @property
    def mode(self) -> str:
        return "all" if self.all is not None else "any"

    @property
    def criteria(self) -> list[Criterion]:
        return self.all if self.all is not None else (self.any or [])


class SuccessEvaluation(BaseModel):
    passed: bool = False
    failed_conditions: list[str] = Field(default_factory=list)
    missing_metrics: list[str] = Field(default_factory=list)
    summary: str = ""


class BranchSelection(BaseModel):
    mode: Literal["child", "top_level"]
    parent: str | None = None
    title: str
    rationale: str = ""

    @field_validator("parent")
    @classmethod
    def _validate_parent(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.strip():
            raise ValueError("parent must not be empty")
        parts = value.split(".")
        if any(not part.isdigit() for part in parts):
            raise ValueError(f"invalid tree number: {value}")
        return value

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be empty")
        return value

    @model_validator(mode="after")
    def _validate_mode(self) -> BranchSelection:
        if self.mode == "child" and self.parent is None:
            raise ValueError("child mode requires a parent")
        if self.mode == "top_level" and self.parent is not None:
            raise ValueError("top_level mode must not include a parent")
        return self


class WorkspaceFileAudit(BaseModel):
    path: str
    required: bool
    status: Literal["valid", "missing", "invalid"]
    message: str = ""


class WorkspaceAudit(BaseModel):
    files: list[WorkspaceFileAudit] = Field(default_factory=list)

    def get(self, path: str) -> WorkspaceFileAudit:
        return next(entry for entry in self.files if entry.path == path)

    @property
    def core_files(self) -> list[WorkspaceFileAudit]:
        return [entry for entry in self.files if entry.required]

    @property
    def optional_files(self) -> list[WorkspaceFileAudit]:
        return [entry for entry in self.files if not entry.required]

    @property
    def missing_core(self) -> list[WorkspaceFileAudit]:
        return [entry for entry in self.core_files if entry.status == "missing"]

    @property
    def invalid_core(self) -> list[WorkspaceFileAudit]:
        return [entry for entry in self.core_files if entry.status == "invalid"]

    @property
    def valid_core(self) -> list[WorkspaceFileAudit]:
        return [entry for entry in self.core_files if entry.status == "valid"]

    def is_initialized(self) -> bool:
        return all(entry.status == "valid" for entry in self.core_files)


class SetupDraft(BaseModel):
    summary: str = ""
    needs_follow_up: bool = False
    follow_up_questions: list[str] = Field(default_factory=list)
    goal_md: str | None = None
    master_agent_md: str | None = None
    researcher_agent_md: str | None = None

    @field_validator("follow_up_questions")
    @classmethod
    def _validate_follow_up_questions(cls, value: list[str]) -> list[str]:
        cleaned = [question.strip() for question in value if question.strip()]
        if len(cleaned) > 3:
            raise ValueError("at most 3 follow-up questions are allowed")
        return cleaned

    @model_validator(mode="after")
    def _validate_shape(self) -> SetupDraft:
        if self.needs_follow_up:
            if not self.follow_up_questions:
                raise ValueError("follow-up questions are required when needs_follow_up is true")
            return self

        if self.follow_up_questions:
            raise ValueError("follow-up questions must be empty when setup is complete")

        missing = [
            field_name
            for field_name in ("goal_md", "master_agent_md", "researcher_agent_md")
            if not getattr(self, field_name)
        ]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"setup draft is missing required files: {joined}")
        return self
