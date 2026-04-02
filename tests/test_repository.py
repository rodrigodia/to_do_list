from datetime import date

from todo_app.models import Priority, Status, TaskData, TaskFilters
from todo_app.repository import TaskRepository


def test_repository_crud_roundtrip(tmp_path):
    repository = TaskRepository(tmp_path / "todo.db")
    repository.migrate()

    created = repository.create(
        TaskData(
            title="Estudar PySide6",
            description="Ler documentacao de widgets",
            priority=Priority.HIGH,
            due_date=date(2026, 4, 15),
        )
    )
    assert created.id > 0
    assert created.status is Status.TODO

    updated = repository.update(
        created.id,
        TaskData(
            title="Estudar PySide6 com exemplos",
            description="Criar prototipo local",
            priority=Priority.MEDIUM,
            due_date=date(2026, 4, 20),
        ),
    )
    assert updated.title == "Estudar PySide6 com exemplos"
    assert updated.priority is Priority.MEDIUM

    done_task = repository.mark_done(created.id, True)
    assert done_task.status is Status.DONE

    repository.delete(created.id)
    assert repository.list() == []


def test_repository_filters_and_search(tmp_path):
    repository = TaskRepository(tmp_path / "todo.db")
    repository.migrate()

    first = repository.create(
        TaskData(title="Comprar leite", description="Supermercado", priority=Priority.LOW)
    )
    second = repository.create(
        TaskData(title="Enviar relatorio", description="Projeto Alpha", priority=Priority.HIGH)
    )
    repository.mark_done(second.id, True)
    repository.create(
        TaskData(title="Treino", description="Corrida no parque", priority=Priority.HIGH)
    )

    done_high = repository.list(
        filters=TaskFilters(status=Status.DONE, priority=Priority.HIGH), sort="priority_desc"
    )
    assert len(done_high) == 1
    assert done_high[0].title == "Enviar relatorio"

    query_result = repository.list(filters=TaskFilters(query="leite"))
    assert len(query_result) == 1
    assert query_result[0].id == first.id

    by_due_date = repository.list(sort="due_date_asc")
    assert len(by_due_date) == 3


def test_repository_persistence_across_restarts(tmp_path):
    db_path = tmp_path / "todo.db"
    repo1 = TaskRepository(db_path)
    repo1.migrate()
    repo1.create(TaskData(title="Tarefa persistente", priority=Priority.HIGH))

    repo2 = TaskRepository(db_path)
    repo2.migrate()
    tasks = repo2.list()

    assert len(tasks) == 1
    assert tasks[0].title == "Tarefa persistente"
