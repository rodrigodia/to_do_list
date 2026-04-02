from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Literal


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Status(StrEnum):
    TODO = "todo"
    DONE = "done"


SortOption = Literal["created_desc", "due_date_asc", "priority_desc"]

PRIORITY_LABELS_PT = {
    Priority.LOW: "Baixa",
    Priority.MEDIUM: "Media",
    Priority.HIGH: "Alta",
}

STATUS_LABELS_PT = {
    Status.TODO: "Por fazer",
    Status.DONE: "Concluida",
}


@dataclass(slots=True)
class TaskData:
    title: str
    description: str = ""
    priority: Priority = Priority.MEDIUM
    due_date: date | None = None


@dataclass(slots=True)
class Task:
    id: int
    title: str
    description: str
    priority: Priority
    due_date: date | None
    status: Status
    created_at: datetime
    updated_at: datetime
    subtask_total: int = 0
    subtask_done: int = 0


@dataclass(slots=True)
class SubtaskData:
    title: str
    status: Status = Status.TODO
    position: int = 0
    parent_subtask_id: int | None = None


@dataclass(slots=True)
class Subtask:
    id: int
    task_id: int
    title: str
    status: Status
    position: int
    parent_subtask_id: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class TaskWithSubtasks(Task):
    subtasks: list[Subtask] = field(default_factory=list)


@dataclass(slots=True)
class TaskFilters:
    status: Status | None = None
    priority: Priority | None = None
    query: str | None = None


def priority_label_pt(priority: Priority) -> str:
    return PRIORITY_LABELS_PT[priority]
