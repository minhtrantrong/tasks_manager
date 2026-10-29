"""Pydantic models returned by the repository and MCP tools."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class Model(BaseModel):
    """Base model: snake_case fields, camelCase JSON aliases."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class Project(Model):
    id: int
    slug: str
    name: str
    description: str | None = None
    root_path: str | None = None
    require_closure: bool = False
    created_at: str
    archived_at: str | None = None


class ProjectSummary(Model):
    id: int
    slug: str
    name: str
    counts: dict[str, int] = Field(default_factory=dict)
    archived: bool = False


class Task(Model):
    id: int
    project_id: int
    parent_id: int | None = None
    seq: float
    title: str
    description: str | None = None
    design: str | None = None
    type: str = "task"
    workflow: str = "simple"
    status: str = "open"
    priority: int = 3
    meta: dict[str, Any] = Field(default_factory=dict)
    owner: str | None = None
    lease_expires_at: str | None = None
    block_reason: str | None = None
    outcome: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None


class TaskSummary(Model):
    id: int
    title: str
    type: str
    workflow: str
    status: str
    priority: int
    seq: float
    owner: str | None = None
    updated_at: str


class Relation(Model):
    task_id: int
    related_id: int
    kind: str


class RelationView(Model):
    related_id: int
    kind: str
    target_status: str


class JournalEntry(Model):
    id: int
    task_id: int | None = None
    project_id: int | None = None
    kind: str
    body: str
    actor: str | None = None
    session_ref: str | None = None
    created_at: str


class ContextEntry(Model):
    id: int
    task_id: int | None = None
    body: str
    actor: str | None = None
    created_at: str


class TaskDetail(Task):
    relations: list[RelationView] = Field(default_factory=list)
    children: list[TaskSummary] = Field(default_factory=list)
    story_context: list[ContextEntry] = Field(default_factory=list)
    journal: list[JournalEntry] = Field(default_factory=list)


class Page(Model, Generic[T]):
    items: list[T] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 20


class GraphNode(Model):
    id: int
    title: str
    status: str
    priority: int
    seq: float
    type: str
    workflow: str


class GraphEdge(Model):
    from_id: int = Field(alias="from")
    to_id: int = Field(alias="to")
    kind: str


class Graph(Model):
    project_id: int
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    waiting: list[int] = Field(default_factory=list)


class SessionEvent(Model):
    id: int
    project_id: int
    task_id: int | None = None
    kind: str
    detail: str | None = None
    created_at: str


class Checkpoint(Model):
    id: int
    project_id: int
    task_id: int | None = None
    summary: str
    next_actions: list[str] = Field(default_factory=list)
    created_at: str


class RecallHit(Model):
    source: str
    task_id: int | None = None
    project_id: int
    title: str | None = None
    snippet: str
    created_at: str
