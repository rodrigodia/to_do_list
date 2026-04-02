from datetime import date

from todo_app.models import Priority, Status, SubtaskData, TaskData, TaskFilters
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
    assert created.subtask_total == 0

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


def test_repository_subtasks_association_and_cascade_delete(tmp_path):
    repository = TaskRepository(tmp_path / "todo.db")
    repository.migrate()

    created = repository.create(
        TaskData(title="Planear viagem", description="Checklist geral", priority=Priority.MEDIUM)
    )
    root = repository.create_subtask(created.id, "Reservar hotel", description="Zona centro")
    child = repository.create_subtask(created.id, "Enviar docs", parent_subtask_id=root.id)
    repository.mark_subtask_done(child.id, True)
    repository.create_subtask(created.id, "Comprar bilhetes")

    task_with_counts = repository.get(created.id)
    assert task_with_counts.subtask_total == 3
    assert task_with_counts.subtask_done == 1

    subtasks = repository.list_subtasks(created.id)
    assert len(subtasks) == 3
    by_title = {subtask.title: subtask for subtask in subtasks}
    assert by_title["Reservar hotel"].parent_subtask_id is None
    assert by_title["Reservar hotel"].description == "Zona centro"
    assert by_title["Enviar docs"].parent_subtask_id == root.id
    assert by_title["Enviar docs"].status is Status.DONE

    repository.delete_subtask(root.id)
    remaining = repository.list_subtasks(created.id)
    assert len(remaining) == 1
    assert remaining[0].title == "Comprar bilhetes"


def test_repository_mark_done_cascades_to_descendants(tmp_path):
    repository = TaskRepository(tmp_path / "todo.db")
    repository.migrate()

    task = repository.create(TaskData(title="Lancar versao", priority=Priority.HIGH))
    root = repository.create_subtask(task.id, "Checklist release")
    child = repository.create_subtask(task.id, "Criar tag", parent_subtask_id=root.id)
    grandchild = repository.create_subtask(task.id, "Validar changelog", parent_subtask_id=child.id)

    repository.mark_subtask_done(root.id, True)
    subtasks_after_root_done = {sub.id: sub for sub in repository.list_subtasks(task.id)}
    assert subtasks_after_root_done[root.id].status is Status.DONE
    assert subtasks_after_root_done[child.id].status is Status.DONE
    assert subtasks_after_root_done[grandchild.id].status is Status.DONE

    repository.mark_done(task.id, False)
    subtasks_after_task_todo = {sub.id: sub for sub in repository.list_subtasks(task.id)}
    assert subtasks_after_task_todo[root.id].status is Status.DONE
    assert subtasks_after_task_todo[child.id].status is Status.DONE
    assert subtasks_after_task_todo[grandchild.id].status is Status.DONE

    repository.mark_subtask_done(root.id, False)
    subtasks_after_root_todo = {sub.id: sub for sub in repository.list_subtasks(task.id)}
    assert subtasks_after_root_todo[root.id].status is Status.TODO
    assert subtasks_after_root_todo[child.id].status is Status.DONE
    assert subtasks_after_root_todo[grandchild.id].status is Status.DONE
    task_after_root_todo = repository.get(task.id)
    assert task_after_root_todo.status is Status.TODO


def test_repository_uncheck_subtask_marks_all_ancestors_todo(tmp_path):
    repository = TaskRepository(tmp_path / "todo.db")
    repository.migrate()

    task = repository.create(TaskData(title="Arquitetura", priority=Priority.HIGH))
    root = repository.create_subtask(task.id, "Backend")
    child = repository.create_subtask(task.id, "API", parent_subtask_id=root.id)
    grandchild = repository.create_subtask(task.id, "Auth", parent_subtask_id=child.id)

    repository.mark_done(task.id, True)
    repository.mark_subtask_done(grandchild.id, False)

    state = {sub.id: sub for sub in repository.list_subtasks(task.id)}
    assert state[grandchild.id].status is Status.TODO
    assert state[child.id].status is Status.TODO
    assert state[root.id].status is Status.TODO
    assert repository.get(task.id).status is Status.TODO


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
    repository.replace_subtasks(
        first.id,
        [
            SubtaskData(title="Passar no supermercado", description="Levar cupoes", status=Status.TODO),
            SubtaskData(title="Pagar caixa", description="Confirmar desconto fidelidade", status=Status.TODO),
        ],
    )

    done_high = repository.list(
        filters=TaskFilters(status=Status.DONE, priority=Priority.HIGH), sort="priority_desc"
    )
    assert len(done_high) == 1
    assert done_high[0].title == "Enviar relatorio"

    query_result = repository.list(filters=TaskFilters(query="supermercado"))
    assert len(query_result) == 1
    assert query_result[0].id == first.id

    subtask_description_result = repository.list(filters=TaskFilters(query="fidelidade"))
    assert len(subtask_description_result) == 1
    assert subtask_description_result[0].id == first.id

    by_due_date = repository.list(sort="due_date_asc")
    assert len(by_due_date) == 3


def test_repository_update_subtask_description(tmp_path):
    repository = TaskRepository(tmp_path / "todo.db")
    repository.migrate()
    task = repository.create(TaskData(title="Documentar app", priority=Priority.MEDIUM))
    subtask = repository.create_subtask(task.id, "Escrever draft", description="Primeira versao")

    repository.update_subtask(subtask.id, description="Versao final revista")
    loaded = repository.get_subtask(subtask.id)
    assert loaded.description == "Versao final revista"


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
