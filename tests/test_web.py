from fastapi.testclient import TestClient

from todo_app.models import Priority, TaskData
from todo_app.repository import TaskRepository
from todo_app.web.app import create_app


def test_web_index_renders(tmp_path):
    app = create_app(tmp_path / "todo.db")
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    assert "To-Do List Web" in response.text


def test_web_create_task_and_subtask(tmp_path):
    db_path = tmp_path / "todo.db"
    app = create_app(db_path)
    client = TestClient(app)

    create_task_response = client.post(
        "/tasks/create",
        data={
            "title": "Task Web",
            "description": "Criada pelo browser",
            "priority": "high",
            "due_date": "2026-04-10",
            "next_url": "/",
        },
    )
    assert create_task_response.status_code == 200

    repository = TaskRepository(db_path)
    repository.migrate()
    tasks = repository.list()
    assert len(tasks) == 1
    assert tasks[0].title == "Task Web"

    create_subtask_response = client.post(
        "/subtasks/create",
        data={
            "task_id": str(tasks[0].id),
            "title": "Subtask Web",
            "description": "Descricao subtask",
            "next_url": "/",
        },
    )
    assert create_subtask_response.status_code == 200

    subtasks = repository.list_subtasks(tasks[0].id)
    assert len(subtasks) == 1
    assert subtasks[0].title == "Subtask Web"
    assert subtasks[0].description == "Descricao subtask"


def test_web_bulk_delete_multiple_selection(tmp_path):
    db_path = tmp_path / "todo.db"
    app = create_app(db_path)
    client = TestClient(app)
    repository = TaskRepository(db_path)
    repository.migrate()

    first = repository.create(TaskData(title="A", priority=Priority.LOW))
    second = repository.create(TaskData(title="B", priority=Priority.MEDIUM))

    response = client.post(
        "/bulk-delete",
        data={
            "selected": [f"task:{first.id}", f"task:{second.id}"],
            "next_url": "/",
        },
    )
    assert response.status_code == 200
    assert repository.list() == []


def test_web_update_subtask_description(tmp_path):
    db_path = tmp_path / "todo.db"
    app = create_app(db_path)
    client = TestClient(app)
    repository = TaskRepository(db_path)
    repository.migrate()

    task = repository.create(TaskData(title="Root", priority=Priority.HIGH))
    subtask = repository.create_subtask(task.id, title="Child", description="Antiga")

    response = client.post(
        f"/subtasks/{subtask.id}/update",
        data={
            "title": "Child atualizado",
            "description": "Nova descricao",
            "next_url": "/",
        },
    )
    assert response.status_code == 200

    updated = repository.get_subtask(subtask.id)
    assert updated.title == "Child atualizado"
    assert updated.description == "Nova descricao"
