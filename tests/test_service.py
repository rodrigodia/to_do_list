from datetime import date

import pytest

from todo_app.models import Priority, Status
from todo_app.repository import TaskRepository
from todo_app.service import TaskService, ValidationError


@pytest.fixture
def service(tmp_path):
    repository = TaskRepository(tmp_path / "todo.db")
    repository.migrate()
    return TaskService(repository)


def test_create_task_requires_title(service: TaskService):
    with pytest.raises(ValidationError):
        service.create_task("   ")


def test_create_task_rejects_invalid_due_date_type(service: TaskService):
    with pytest.raises(ValidationError):
        service.create_task("Task", due_date="2026-04-01")  # type: ignore[arg-type]


def test_service_supports_edit_complete_delete_and_filters(service: TaskService):
    task = service.create_task(
        title="Preparar demo",
        description="Organizar slides",
        priority=Priority.HIGH,
        due_date=date(2026, 4, 10),
    )

    edited = service.update_task(
        task_id=task.id,
        title="Preparar demo final",
        description="Slides e roteiro",
        priority=Priority.MEDIUM,
        due_date=date(2026, 4, 11),
    )
    assert edited.title == "Preparar demo final"
    assert edited.priority is Priority.MEDIUM

    service.mark_done(task.id, True)
    filtered = service.list_tasks(status=Status.DONE, priority=Priority.MEDIUM, query="demo")
    assert len(filtered) == 1
    assert filtered[0].id == task.id

    service.delete_task(task.id)
    assert service.list_tasks() == []
