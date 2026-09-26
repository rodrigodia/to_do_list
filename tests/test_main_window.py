from datetime import date, datetime, timedelta

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QMessageBox

from todo_app.models import Priority, Status
from todo_app.repository import TaskRepository
from todo_app.service import TaskService
from todo_app.ui import main_window as main_window_module
from todo_app.ui.main_window import (
    CHECK_COLUMN_OFFSET,
    OVERDUE_COLOR,
    PRIORITY_COLORS,
    ROLE_GROUP_ACCENT,
    MainWindow,
)

STATUS_ALL_INDEX = 2
TODAY = datetime.now().astimezone().date()


@pytest.fixture
def service(tmp_path):
    repository = TaskRepository(tmp_path / "todo.db")
    repository.migrate()
    return TaskService(repository)


@pytest.fixture
def make_window(qtbot, service):
    def factory(show_all: bool = True) -> MainWindow:
        window = MainWindow(service)
        qtbot.addWidget(window)
        if show_all:
            window.status_filter.setCurrentIndex(STATUS_ALL_INDEX)
        window.show()
        qtbot.waitExposed(window)
        return window

    return factory


@pytest.fixture
def confirm_dialogs(monkeypatch):
    answers: list[QMessageBox.StandardButton] = []

    def fake_question(*_args, **_kwargs):
        return answers.pop(0) if answers else QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", fake_question)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: pytest.fail(f"warning: {a[2]}"))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    return answers


def titles(window: MainWindow) -> list[str]:
    return [window.table.item(row, 1).text() for row in range(window.table.rowCount())]


def row_of(window: MainWindow, entity_type: str, entity_id: int) -> int:
    row = window._row_for_key((entity_type, entity_id))
    assert row >= 0, f"{entity_type}:{entity_id} nao esta visivel"
    return row


def select(window: MainWindow, *keys: tuple[str, int]) -> None:
    window._restore_selection(set(keys), keys[0])


def install_fake_dialog(monkeypatch, name: str, values: tuple) -> None:
    class FakeDialog:
        Accepted = 1

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def exec(self) -> int:
            return self.Accepted

        def get_values(self) -> tuple:
            return values

    monkeypatch.setattr(main_window_module, name, FakeDialog)


def test_renders_tasks_with_nested_subtasks_in_order(make_window, service):
    task = service.create_task("Viagem", priority=Priority.HIGH)
    hotel = service.create_subtask(task.id, "Hotel")
    service.create_subtask(task.id, "Pagar sinal", parent_subtask_id=hotel.id)
    service.create_subtask(task.id, "Voos")
    service.create_task("Compras", priority=Priority.LOW)

    window = make_window()

    assert titles(window) == [
        "Viagem",
        "├─ Hotel",
        "│   └─ Pagar sinal",
        "└─ Voos",
        "Compras",
    ]
    assert window.table.item(0, 4).text() == "0/3 concluidas"
    assert window.table.item(1, 4).text() == "1 sub"
    assert window.task_count_label.text() == "2 tarefa(s)"


def test_priority_colors_and_overdue_highlight(make_window, service):
    yesterday = TODAY - timedelta(days=1)
    overdue = service.create_task("Atrasada", priority=Priority.HIGH, due_date=yesterday)
    done_late = service.create_task("Feita tarde", priority=Priority.LOW, due_date=yesterday)
    service.mark_done(done_late.id, True)
    future = service.create_task(
        "Futura", priority=Priority.MEDIUM, due_date=TODAY + timedelta(days=3)
    )

    window = make_window()

    overdue_row = row_of(window, "task", overdue.id)
    due_item = window.table.item(overdue_row, 3)
    assert due_item.text() == f"{yesterday.isoformat()} (atrasada)"
    assert due_item.foreground().color() == OVERDUE_COLOR
    assert due_item.font().bold()
    assert window.table.item(overdue_row, 2).foreground().color() == PRIORITY_COLORS[Priority.HIGH]

    done_row = row_of(window, "task", done_late.id)
    assert window.table.item(done_row, 3).text() == yesterday.isoformat()
    assert window.table.item(done_row, 1).font().strikeOut()

    future_row = row_of(window, "task", future.id)
    assert "atrasada" not in window.table.item(future_row, 3).text()
    assert window.table.item(future_row, 2).foreground().color() == PRIORITY_COLORS[Priority.MEDIUM]


def test_search_is_debounced_and_queries_once(make_window, service, qtbot, monkeypatch):
    service.create_task("Comprar leite")
    service.create_task("Enviar relatorio")
    window = make_window()

    calls: list[str] = []
    original = service.list_tasks

    def spy(**kwargs):
        calls.append(kwargs["query"])
        return original(**kwargs)

    monkeypatch.setattr(service, "list_tasks", spy)

    qtbot.keyClicks(window.search_input, "leite")
    assert calls == []
    assert window.table.rowCount() == 2

    qtbot.waitUntil(lambda: window.table.rowCount() == 1, timeout=2000)
    assert titles(window) == ["Comprar leite"]
    assert calls == ["leite"]


def test_search_matches_subtask_content(make_window, service, qtbot):
    task = service.create_task("Casa")
    service.create_subtask(task.id, "Canalizador", description="ligar amanha")
    service.create_task("Outra")
    window = make_window()

    window.search_input.setText("AMANHA")
    qtbot.waitUntil(lambda: window.task_count_label.text() == "1 tarefa(s)", timeout=2000)
    assert titles(window) == ["Casa", "└─ Canalizador"]


def test_refresh_keeps_selection_and_scroll(make_window, service):
    tasks = [service.create_task(f"Tarefa {i:02d}") for i in range(60)]
    target = tasks[5]
    sub = service.create_subtask(target.id, "Sub alvo")
    window = make_window()
    scrollbar = window.table.verticalScrollBar()
    assert scrollbar.maximum() > 0

    select(window, ("task", target.id), ("task", tasks[10].id))
    scrollbar.setValue(scrollbar.maximum() // 2)
    scroll_before = scrollbar.value()

    sub_row = row_of(window, "subtask", sub.id)
    window.table.item(sub_row, 0).setCheckState(Qt.Checked)

    assert service.get_subtask(sub.id).status is Status.DONE
    assert window._selected_keys() == {("task", target.id), ("task", tasks[10].id)}
    assert window._current_key() == ("task", target.id)
    assert scrollbar.value() == scroll_before


def test_checking_task_in_ui_cascades_and_hides_it_from_todo_filter(make_window, service):
    task = service.create_task("Projeto")
    root = service.create_subtask(task.id, "Fase 1")
    service.create_subtask(task.id, "Passo", parent_subtask_id=root.id)
    service.create_task("Outra")
    window = make_window(show_all=False)
    assert window.task_count_label.text() == "2 tarefa(s)"

    window.table.item(row_of(window, "task", task.id), 0).setCheckState(Qt.Checked)

    assert titles(window) == ["Outra"]
    assert all(sub.status is Status.DONE for sub in service.list_subtasks(task.id))

    window.status_filter.setCurrentIndex(STATUS_ALL_INDEX)
    for row in range(row_of(window, "task", task.id), row_of(window, "task", task.id) + 3):
        assert window.table.item(row, 0).checkState() == Qt.Checked
        assert window.table.item(row, 1).font().strikeOut()


def test_create_task_selects_new_row(make_window, service, monkeypatch, confirm_dialogs):
    for i in range(40):
        service.create_task(f"Antiga {i}", priority=Priority.HIGH)
    install_fake_dialog(
        monkeypatch, "TaskDialog", ("  Nova  ", "desc", Priority.LOW, date(2030, 1, 1))
    )
    window = make_window()

    window.new_button.click()

    created = service.list_tasks(query="Nova")[0]
    assert created.title == "Nova"
    row = row_of(window, "task", created.id)
    assert window._selected_keys() == {("task", created.id)}
    assert window.table.visualItemRect(window.table.item(row, 1)).intersects(
        window.table.viewport().rect()
    )


def test_create_nested_subtask_with_shortcut(make_window, service, monkeypatch, qtbot):
    task = service.create_task("Relatorio")
    section = service.create_subtask(task.id, "Seccao 1")
    install_fake_dialog(monkeypatch, "SubtaskDialog", ("Graficos", "com legenda"))
    window = make_window()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow, timeout=2000)

    select(window, ("subtask", section.id))
    qtbot.keyClick(window.table, Qt.Key_S, Qt.ControlModifier)

    created = [s for s in service.list_subtasks(task.id) if s.title == "Graficos"]
    assert len(created) == 1
    assert created[0].parent_subtask_id == section.id
    assert created[0].description == "com legenda"
    assert titles(window) == ["Relatorio", "└─ Seccao 1", "     └─ Graficos"]
    assert window._selected_keys() == {("subtask", created[0].id)}


def test_create_subtask_without_selection_does_nothing(
    make_window, service, monkeypatch, confirm_dialogs
):
    service.create_task("Sozinha")
    install_fake_dialog(monkeypatch, "SubtaskDialog", ("Nao devia existir", ""))
    window = make_window()
    window.table.setCurrentCell(-1, -1)

    window.new_subtask_button.click()

    assert service.list_subtasks(service.list_tasks()[0].id) == []


def test_delete_mixed_selection_then_undo_restores_everything(
    make_window, service, confirm_dialogs
):
    keep = service.create_task("Fica", priority=Priority.HIGH)
    keep_sub = service.create_subtask(keep.id, "Sub que fica")
    drop_sub = service.create_subtask(keep.id, "Sub que sai")
    service.create_subtask(keep.id, "Neta que sai", parent_subtask_id=drop_sub.id)
    gone = service.create_task("Sai", priority=Priority.LOW, due_date=date(2031, 3, 3))
    gone_sub = service.create_subtask(gone.id, "Vai junto")
    service.mark_subtask_done(gone_sub.id, True)
    window = make_window()
    titles_before = titles(window)

    select(window, ("task", gone.id), ("subtask", gone_sub.id), ("subtask", drop_sub.id))
    window.delete_button.click()

    assert titles(window) == ["Fica", "└─ Sub que fica"]
    assert window.undo_button.isEnabled()
    assert "4 item(ns) apagado(s)" in window.statusBar().currentMessage()

    window.undo_button.click()

    assert titles(window) == titles_before
    assert not window.undo_button.isEnabled()
    restored = service.get_task(gone.id)
    assert restored.due_date == date(2031, 3, 3)
    assert service.get_subtask(gone_sub.id).status is Status.DONE
    assert service.get_subtask(keep_sub.id).title == "Sub que fica"
    assert window._selected_keys() == {("task", gone.id), ("subtask", drop_sub.id)}


def test_delete_cancelled_keeps_items(make_window, service, confirm_dialogs):
    task = service.create_task("Nao apagar")
    window = make_window()
    select(window, ("task", task.id))
    confirm_dialogs.append(QMessageBox.No)

    window.delete_button.click()

    assert titles(window) == ["Nao apagar"]
    assert not window.undo_button.isEnabled()


def test_multiple_undos_are_applied_in_reverse_order(make_window, service, confirm_dialogs, qtbot):
    task = service.create_task("Arvore")
    parent = service.create_subtask(task.id, "Pai")
    child = service.create_subtask(task.id, "Filho", parent_subtask_id=parent.id)
    window = make_window()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow, timeout=2000)

    select(window, ("subtask", child.id))
    qtbot.keyClick(window.table, Qt.Key_Delete)
    select(window, ("subtask", parent.id))
    qtbot.keyClick(window.table, Qt.Key_Delete)
    assert titles(window) == ["Arvore"]

    qtbot.keyClick(window.table, Qt.Key_Z, Qt.ControlModifier)
    assert titles(window) == ["Arvore", "└─ Pai"]
    qtbot.keyClick(window.table, Qt.Key_Z, Qt.ControlModifier)
    assert titles(window) == ["Arvore", "└─ Pai", "     └─ Filho"]
    assert not window.undo_button.isEnabled()

    # Sem nada para desfazer, o atalho nao faz nada.
    qtbot.keyClick(window.table, Qt.Key_Z, Qt.ControlModifier)
    assert titles(window) == ["Arvore", "└─ Pai", "     └─ Filho"]


def drop_y_above(window: MainWindow, row: int) -> int:
    return window.table.visualRect(window.table.model().index(row, 0)).top() + 2


def drop_y_below(window: MainWindow, row: int) -> int:
    return window.table.visualRect(window.table.model().index(row, 0)).bottom() - 2


def test_drag_subtask_reorders_siblings_and_moves_subtree(make_window, service, confirm_dialogs):
    task = service.create_task("Sprint")
    a = service.create_subtask(task.id, "A")
    a_child = service.create_subtask(task.id, "A1", parent_subtask_id=a.id)
    b = service.create_subtask(task.id, "B")
    c = service.create_subtask(task.id, "C")
    window = make_window()
    assert titles(window) == ["Sprint", "├─ A", "│   └─ A1", "├─ B", "└─ C"]
    moved = window.table.move_row_by_drop(
        row_of(window, "subtask", a.id), drop_y_below(window, row_of(window, "subtask", c.id))
    )

    assert moved
    assert titles(window) == ["Sprint", "├─ B", "├─ C", "└─ A", "     └─ A1"]
    top_level = [s.id for s in service.list_subtasks(task.id) if s.parent_subtask_id is None]
    assert top_level == [b.id, c.id, a.id]
    assert service.get_subtask(a_child.id).parent_subtask_id == a.id
    assert window._selected_keys() == {("subtask", a.id)}

    moved_back = window.table.move_row_by_drop(
        row_of(window, "subtask", c.id), drop_y_above(window, row_of(window, "subtask", b.id))
    )
    assert moved_back
    top_level = [s.id for s in service.list_subtasks(task.id) if s.parent_subtask_id is None]
    assert top_level == [c.id, b.id, a.id]


def test_drag_rejects_tasks_and_keeps_subtask_within_its_parent(
    make_window, service, confirm_dialogs
):
    first = service.create_task("Primeira", priority=Priority.HIGH)
    x = service.create_subtask(first.id, "X")
    x1 = service.create_subtask(first.id, "X1", parent_subtask_id=x.id)
    x2 = service.create_subtask(first.id, "X2", parent_subtask_id=x.id)
    y = service.create_subtask(first.id, "Y")
    second = service.create_task("Segunda", priority=Priority.LOW)
    other = service.create_subtask(second.id, "Outra")
    window = make_window()
    titles_before = titles(window)

    # Tarefas nao se arrastam.
    assert not window.table.move_row_by_drop(
        row_of(window, "task", first.id), drop_y_below(window, row_of(window, "task", second.id))
    )
    # Largar no mesmo sitio nao muda nada.
    assert not window.table.move_row_by_drop(
        row_of(window, "subtask", x.id), drop_y_above(window, row_of(window, "subtask", x.id))
    )
    assert titles(window) == titles_before

    # Largar X2 sobre outra tarefa: fica limitado as irmas (X1), sem mudar de pai.
    window.table.move_row_by_drop(
        row_of(window, "subtask", x2.id), drop_y_above(window, row_of(window, "subtask", y.id))
    )
    x2_loaded = service.get_subtask(x2.id)
    assert x2_loaded.task_id == first.id
    assert x2_loaded.parent_subtask_id == x.id
    assert service.get_subtask(other.id).task_id == second.id
    top_level = [s.id for s in service.list_subtasks(first.id) if s.parent_subtask_id is None]
    assert top_level == [x.id, y.id]

    window.table.move_row_by_drop(
        row_of(window, "subtask", x2.id), drop_y_above(window, row_of(window, "subtask", x1.id))
    )
    children = [s.id for s in service.list_subtasks(first.id) if s.parent_subtask_id == x.id]
    assert children == [x2.id, x1.id]


def row_background(window: MainWindow, row: int):
    colors = {window.table.item(row, col).background().color().name() for col in range(6)}
    assert len(colors) == 1, "todas as celulas da linha devem ter o mesmo fundo"
    return colors.pop()


def test_task_groups_are_visually_distinct(make_window, service):
    first = service.create_task("Primeira", priority=Priority.HIGH, description="notas")
    f1 = service.create_subtask(first.id, "F1")
    f1a = service.create_subtask(first.id, "F1a", parent_subtask_id=f1.id)
    second = service.create_task("Segunda", priority=Priority.MEDIUM)
    s1 = service.create_subtask(second.id, "S1")
    third = service.create_task("Terceira", priority=Priority.LOW)
    service.mark_done(third.id, True)
    window = make_window()

    assert not window.table.alternatingRowColors()

    # Dentro de um grupo, as subtarefas partilham o fundo; a tarefa tem um fundo proprio.
    first_header = row_background(window, row_of(window, "task", first.id))
    first_body = row_background(window, row_of(window, "subtask", f1.id))
    assert row_background(window, row_of(window, "subtask", f1a.id)) == first_body
    assert first_header != first_body

    # Grupos consecutivos alternam de cor.
    second_header = row_background(window, row_of(window, "task", second.id))
    second_body = row_background(window, row_of(window, "subtask", s1.id))
    assert second_body != first_body
    assert second_header != first_header
    assert row_background(window, row_of(window, "task", third.id)) == first_header

    # A barra lateral tem a cor da prioridade em todas as linhas do grupo.
    for key in (("task", first.id), ("subtask", f1.id), ("subtask", f1a.id)):
        accent = window.table.item(row_of(window, *key), 0).data(ROLE_GROUP_ACCENT)
        assert accent == PRIORITY_COLORS[Priority.HIGH]
    s1_accent = window.table.item(row_of(window, "subtask", s1.id), 0).data(ROLE_GROUP_ACCENT)
    assert s1_accent == PRIORITY_COLORS[Priority.MEDIUM]
    done_accent = window.table.item(row_of(window, "task", third.id), 0).data(ROLE_GROUP_ACCENT)
    assert done_accent == window.table.palette().color(QPalette.Mid)

    # Titulo da tarefa a negrito com a descricao em tooltip; subtarefas sem negrito.
    first_title = window.table.item(row_of(window, "task", first.id), 1)
    assert first_title.font().bold()
    assert first_title.toolTip() == "notas"
    assert not window.table.item(row_of(window, "subtask", f1.id), 1).font().bold()


def test_group_colors_follow_the_regrouping_after_filtering(make_window, service, qtbot):
    alpha = service.create_task("Alpha")
    service.create_task("Beta")
    gamma = service.create_task("Gamma alvo")
    window = make_window()
    assert row_background(window, row_of(window, "task", alpha.id)) == row_background(
        window, row_of(window, "task", gamma.id)
    )
    first_group_color = row_background(window, 0)

    window.search_input.setText("alvo")
    qtbot.waitUntil(lambda: window.table.rowCount() == 1, timeout=2000)

    # Ao filtrar, o primeiro grupo visivel volta a usar a primeira cor.
    assert row_background(window, row_of(window, "task", gamma.id)) == first_group_color


def checkbox_point(window: MainWindow, row: int, x_offset: int) -> QPoint:
    rect = window.table.visualRect(window.table.model().index(row, 0))
    return QPoint(rect.left() + x_offset, rect.center().y())


def test_checkbox_toggles_with_real_mouse_click(make_window, service, qtbot):
    task = service.create_task("Clicar")
    sub = service.create_subtask(task.id, "Sub")
    window = make_window()
    viewport = window.table.viewport()

    sub_row = row_of(window, "subtask", sub.id)
    # Clique na barra de cor (fora da checkbox) nao altera o estado.
    qtbot.mouseClick(viewport, Qt.LeftButton, pos=checkbox_point(window, sub_row, 1))
    assert service.get_subtask(sub.id).status is Status.TODO

    # Clique sobre a checkbox, ja deslocada para a direita da barra.
    qtbot.mouseClick(
        viewport, Qt.LeftButton, pos=checkbox_point(window, sub_row, CHECK_COLUMN_OFFSET + 8)
    )
    assert service.get_subtask(sub.id).status is Status.DONE

    task_row = row_of(window, "task", task.id)
    qtbot.mouseClick(
        viewport, Qt.LeftButton, pos=checkbox_point(window, task_row, CHECK_COLUMN_OFFSET + 8)
    )
    assert service.get_task(task.id).status is Status.DONE
