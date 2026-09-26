from __future__ import annotations

from datetime import date

from todo_app.models import (
    DeletionSnapshot,
    Priority,
    SortOption,
    Status,
    Subtask,
    SubtaskData,
    Task,
    TaskData,
    TaskFilters,
    TaskWithSubtasks,
)
from todo_app.repository import TaskRepository


class ValidationError(ValueError):
    pass


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository

    def create_task(
        self,
        title: str,
        description: str = "",
        priority: Priority | str = Priority.MEDIUM,
        due_date: date | None = None,
        subtasks: list[SubtaskData] | None = None,
    ) -> Task:
        normalized_subtasks = self._normalize_subtasks(subtasks) if subtasks is not None else None
        normalized = TaskData(
            title=self._normalize_title(title),
            description=description.strip(),
            priority=self._normalize_priority(priority),
            due_date=self._normalize_due_date(due_date),
        )
        created = self.repository.create(normalized)
        if normalized_subtasks is not None:
            self.repository.replace_subtasks(created.id, normalized_subtasks)
            return self.repository.get(created.id)
        return created

    def get_task(self, task_id: int) -> TaskWithSubtasks:
        return self.repository.get_with_subtasks(task_id)

    def update_task(
        self,
        task_id: int,
        title: str,
        description: str = "",
        priority: Priority | str = Priority.MEDIUM,
        due_date: date | None = None,
        subtasks: list[SubtaskData] | None = None,
    ) -> Task:
        normalized_subtasks = self._normalize_subtasks(subtasks) if subtasks is not None else None
        normalized = TaskData(
            title=self._normalize_title(title),
            description=description.strip(),
            priority=self._normalize_priority(priority),
            due_date=self._normalize_due_date(due_date),
        )
        updated = self.repository.update(task_id, normalized)
        if normalized_subtasks is not None:
            self.repository.replace_subtasks(task_id, normalized_subtasks)
            return self.repository.get(task_id)
        return updated

    def delete_task(self, task_id: int) -> None:
        self.repository.delete(task_id)

    def mark_done(self, task_id: int, done: bool) -> Task:
        return self.repository.mark_done(task_id, done)

    def list_subtasks(self, task_id: int) -> list[Subtask]:
        return self.repository.list_subtasks(task_id)

    def list_subtasks_for_tasks(self, task_ids: list[int]) -> dict[int, list[Subtask]]:
        return self.repository.list_subtasks_for_tasks(task_ids)

    def delete_items(self, task_ids: list[int], subtask_ids: list[int]) -> DeletionSnapshot:
        return self.repository.delete_many(task_ids, subtask_ids)

    def restore_deleted(self, snapshot: DeletionSnapshot) -> None:
        self.repository.restore(snapshot)

    def get_subtask(self, subtask_id: int) -> Subtask:
        return self.repository.get_subtask(subtask_id)

    def create_subtask(
        self,
        task_id: int,
        title: str,
        description: str = "",
        parent_subtask_id: int | None = None,
    ) -> Subtask:
        normalized_title = self._normalize_subtask_title(title)
        normalized_description = self._normalize_subtask_description(description)
        return self.repository.create_subtask(
            task_id=task_id,
            title=normalized_title,
            description=normalized_description,
            parent_subtask_id=parent_subtask_id,
        )

    def update_subtask_title(self, subtask_id: int, title: str) -> Subtask:
        normalized_title = self._normalize_subtask_title(title)
        return self.repository.update_subtask_title(subtask_id=subtask_id, title=normalized_title)

    def update_subtask(
        self,
        subtask_id: int,
        title: str | None = None,
        description: str | None = None,
    ) -> Subtask:
        normalized_title = self._normalize_subtask_title(title) if title is not None else None
        normalized_description = (
            self._normalize_subtask_description(description) if description is not None else None
        )
        return self.repository.update_subtask(
            subtask_id=subtask_id,
            title=normalized_title,
            description=normalized_description,
        )

    def delete_subtask(self, subtask_id: int) -> None:
        self.repository.delete_subtask(subtask_id)

    def mark_subtask_done(self, subtask_id: int, done: bool) -> Subtask:
        return self.repository.mark_subtask_done(subtask_id, done)

    def reorder_subtasks(
        self,
        task_id: int,
        parent_subtask_id: int | None,
        ordered_subtask_ids: list[int],
    ) -> list[Subtask]:
        if not ordered_subtask_ids:
            raise ValidationError("A nova ordem de subtarefas nao pode ser vazia.")
        return self.repository.reorder_subtasks(
            task_id=task_id,
            parent_subtask_id=parent_subtask_id,
            ordered_subtask_ids=ordered_subtask_ids,
        )

    def list_tasks(
        self,
        status: Status | str | None = None,
        priority: Priority | str | None = None,
        query: str = "",
        sort: SortOption = "created_desc",
    ) -> list[Task]:
        filters = TaskFilters(
            status=self._normalize_status(status),
            priority=self._normalize_priority(priority) if priority is not None else None,
            query=query.strip() or None,
        )
        return self.repository.list(filters=filters, sort=sort)

    def _normalize_title(self, title: str) -> str:
        normalized = title.strip()
        if not normalized:
            raise ValidationError("O titulo da tarefa e obrigatorio.")
        return normalized

    def _normalize_priority(self, priority: Priority | str) -> Priority:
        if isinstance(priority, Priority):
            return priority
        try:
            return Priority(priority)
        except ValueError as exc:
            raise ValidationError("Prioridade invalida.") from exc

    def _normalize_status(self, status: Status | str | None) -> Status | None:
        if status is None or isinstance(status, Status):
            return status
        try:
            return Status(status)
        except ValueError as exc:
            raise ValidationError("Estado invalido.") from exc

    def _normalize_due_date(self, due_date: date | None) -> date | None:
        if due_date is None:
            return None
        if not isinstance(due_date, date):
            raise ValidationError("Data limite invalida.")
        return due_date

    def _normalize_subtasks(self, subtasks: list[SubtaskData]) -> list[SubtaskData]:
        normalized: list[SubtaskData] = []
        for idx, subtask in enumerate(subtasks):
            if not isinstance(subtask, SubtaskData):
                raise ValidationError("Subtarefas invalidas.")
            title = self._normalize_subtask_title(subtask.title)
            status = self._normalize_status(subtask.status)
            if status is None:
                raise ValidationError("Estado invalido para subtarefa.")
            normalized.append(
                SubtaskData(
                    title=title,
                    description=self._normalize_subtask_description(subtask.description),
                    status=status,
                    position=idx,
                    parent_subtask_id=subtask.parent_subtask_id,
                )
            )
        return normalized

    def _normalize_subtask_title(self, title: str) -> str:
        normalized = title.strip()
        if not normalized:
            raise ValidationError("As subtarefas precisam de titulo.")
        return normalized

    def _normalize_subtask_description(self, description: str) -> str:
        return description.strip()
