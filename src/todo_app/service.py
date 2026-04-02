from __future__ import annotations

from datetime import date

from todo_app.models import Priority, SortOption, Status, Task, TaskData, TaskFilters
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
    ) -> Task:
        normalized = TaskData(
            title=self._normalize_title(title),
            description=description.strip(),
            priority=self._normalize_priority(priority),
            due_date=self._normalize_due_date(due_date),
        )
        return self.repository.create(normalized)

    def get_task(self, task_id: int) -> Task:
        return self.repository.get(task_id)

    def update_task(
        self,
        task_id: int,
        title: str,
        description: str = "",
        priority: Priority | str = Priority.MEDIUM,
        due_date: date | None = None,
    ) -> Task:
        normalized = TaskData(
            title=self._normalize_title(title),
            description=description.strip(),
            priority=self._normalize_priority(priority),
            due_date=self._normalize_due_date(due_date),
        )
        return self.repository.update(task_id, normalized)

    def delete_task(self, task_id: int) -> None:
        self.repository.delete(task_id)

    def mark_done(self, task_id: int, done: bool) -> Task:
        return self.repository.mark_done(task_id, done)

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
