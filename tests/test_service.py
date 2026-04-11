from datetime import date

import pytest

from todo_app.models import Priority, Status, SubtaskData
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
        subtasks=[
            SubtaskData(title="Criar guiao"),
            SubtaskData(title="Ensaiar", status=Status.DONE),
        ],
    )
    loaded = service.get_task(task.id)
    assert len(loaded.subtasks) == 2
    assert loaded.subtask_total == 2
    assert loaded.subtask_done == 1

    edited = service.update_task(
        task_id=task.id,
        title="Preparar demo final",
        description="Slides e roteiro",
        priority=Priority.MEDIUM,
        due_date=date(2026, 4, 11),
        subtasks=[
            SubtaskData(title="Atualizar screenshots", status=Status.TODO),
        ],
    )
    assert edited.title == "Preparar demo final"
    assert edited.priority is Priority.MEDIUM

    service.mark_done(task.id, True)
    filtered = service.list_tasks(status=Status.DONE, priority=Priority.MEDIUM, query="demo")
    assert len(filtered) == 1
    assert filtered[0].id == task.id
    assert filtered[0].subtask_total == 1

    service.delete_task(task.id)
    assert service.list_tasks() == []


def test_service_rejects_invalid_subtask_title(service: TaskService):
    with pytest.raises(ValidationError):
        service.create_task(
            title="Task com subtarefa",
            subtasks=[SubtaskData(title="   ")],
        )


def test_service_supports_nested_subtasks(service: TaskService):
    task = service.create_task(title="Projeto X", priority=Priority.HIGH)

    root = service.create_subtask(task.id, "Backend", description="Implementacao principal")
    child = service.create_subtask(task.id, "API auth", parent_subtask_id=root.id)
    grandchild = service.create_subtask(task.id, "Testes auth", parent_subtask_id=child.id)

    service.mark_subtask_done(child.id, True)
    service.update_subtask(
        grandchild.id,
        title="Testes de permissao",
        description="Cobrir cenarios invalidos",
    )

    loaded = service.get_task(task.id)
    assert loaded.subtask_total == 3
    assert loaded.subtask_done == 2
    assert len(loaded.subtasks) == 3

    by_id = {subtask.id: subtask for subtask in loaded.subtasks}
    assert by_id[root.id].description == "Implementacao principal"
    assert by_id[child.id].parent_subtask_id == root.id
    assert by_id[grandchild.id].parent_subtask_id == child.id
    assert by_id[grandchild.id].description == "Cobrir cenarios invalidos"

    service.delete_subtask(root.id)
    remaining = service.list_subtasks(task.id)
    assert remaining == []


def test_service_mark_done_cascades_to_nested_subtasks(service: TaskService):
    task = service.create_task(title="Planeamento", priority=Priority.MEDIUM)
    root = service.create_subtask(task.id, "Sprint 1")
    child = service.create_subtask(task.id, "Task tecnica", parent_subtask_id=root.id)

    service.mark_done(task.id, True)
    all_subtasks_done = {sub.id: sub for sub in service.list_subtasks(task.id)}
    assert all_subtasks_done[root.id].status is Status.DONE
    assert all_subtasks_done[child.id].status is Status.DONE

    service.mark_subtask_done(root.id, False)
    all_subtasks_after_uncheck = {sub.id: sub for sub in service.list_subtasks(task.id)}
    assert all_subtasks_after_uncheck[root.id].status is Status.TODO
    assert all_subtasks_after_uncheck[child.id].status is Status.DONE
    assert service.get_task(task.id).status is Status.TODO


def test_service_uncheck_nested_subtask_marks_ancestors_todo(service: TaskService):
    task = service.create_task(title="Release", priority=Priority.HIGH)
    root = service.create_subtask(task.id, "Planeamento")
    child = service.create_subtask(task.id, "Checklist", parent_subtask_id=root.id)
    grandchild = service.create_subtask(task.id, "Validacao final", parent_subtask_id=child.id)

    service.mark_done(task.id, True)
    service.mark_subtask_done(grandchild.id, False)

    state = {sub.id: sub for sub in service.list_subtasks(task.id)}
    assert state[grandchild.id].status is Status.TODO
    assert state[child.id].status is Status.TODO
    assert state[root.id].status is Status.TODO
    assert service.get_task(task.id).status is Status.TODO


def test_service_subtask_description_is_trimmed(service: TaskService):
    task = service.create_task(title="Qualidade", priority=Priority.LOW)
    created = service.create_subtask(task.id, "Review", description="   notas   ")
    assert created.description == "notas"


def test_service_reorder_subtasks(service: TaskService):
    task = service.create_task(title="Ordem visual", priority=Priority.MEDIUM)
    first = service.create_subtask(task.id, "Primeira")
    second = service.create_subtask(task.id, "Segunda")
    third = service.create_subtask(task.id, "Terceira")

    service.reorder_subtasks(
        task_id=task.id,
        parent_subtask_id=None,
        ordered_subtask_ids=[third.id, first.id, second.id],
    )
    ordered = [sub.id for sub in service.list_subtasks(task.id) if sub.parent_subtask_id is None]
    assert ordered == [third.id, first.id, second.id]


def test_service_reorder_subtasks_requires_ids(service: TaskService):
    task = service.create_task(title="Validacao", priority=Priority.LOW)
    service.create_subtask(task.id, "A")

    with pytest.raises(ValidationError):
        service.reorder_subtasks(task.id, parent_subtask_id=None, ordered_subtask_ids=[])
