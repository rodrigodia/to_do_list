from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDropEvent, QFont, QKeySequence, QMouseEvent, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from todo_app.models import PRIORITY_LABELS_PT, Priority, Status, Subtask, Task, priority_label_pt
from todo_app.service import TaskService, ValidationError
from todo_app.ui.subtask_dialog import SubtaskDialog
from todo_app.ui.task_dialog import TaskDialog

ROLE_ENTITY_TYPE = Qt.UserRole
ROLE_ENTITY_ID = Qt.UserRole + 1
ROLE_TASK_ID = Qt.UserRole + 2
ROLE_PARENT_SUBTASK_ID = Qt.UserRole + 3
ROLE_DEPTH = Qt.UserRole + 4

DropTargetResolver = Callable[[int, int], int | None]


class ReorderTableWidget(QTableWidget):
    row_reordered = Signal()

    def __init__(self, rows: int, columns: int, parent: QWidget | None = None) -> None:
        super().__init__(rows, columns, parent)
        self._drag_source_row: int | None = None
        self._drop_target_resolver: DropTargetResolver | None = None

    def set_drop_target_resolver(self, resolver: DropTargetResolver) -> None:
        self._drop_target_resolver = resolver

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_source_row = self.rowAt(int(event.position().y()))
        super().mousePressEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.source() is not self:
            super().dropEvent(event)
            return

        source_row = self._drag_source_row if self._drag_source_row is not None else self.currentRow()
        self._drag_source_row = None
        if source_row < 0:
            event.ignore()
            return

        if self._drop_target_resolver is None:
            event.ignore()
            return

        target_row = self._drop_target_resolver(source_row, int(event.position().y()))
        if target_row is None:
            event.ignore()
            return

        moved_row = self._move_row(source_row, target_row)
        if moved_row is None:
            event.ignore()
            return

        self.clearSelection()
        self.selectRow(moved_row)
        self.setCurrentCell(moved_row, 1)
        self.row_reordered.emit()
        event.acceptProposedAction()

    def _move_row(self, source_row: int, target_row: int) -> int | None:
        row_count = self.rowCount()
        if source_row < 0 or source_row >= row_count:
            return None

        bounded_target = max(0, min(target_row, row_count))
        if bounded_target in {source_row, source_row + 1}:
            return None

        was_blocked = self.signalsBlocked()
        self.blockSignals(True)
        try:
            row_items: list[QTableWidgetItem | None] = []
            for col in range(self.columnCount()):
                item = self.item(source_row, col)
                row_items.append(item.clone() if item is not None else None)
            self.removeRow(source_row)

            insert_row = bounded_target - 1 if source_row < bounded_target else bounded_target
            self.insertRow(insert_row)
            for col, item in enumerate(row_items):
                if item is not None:
                    self.setItem(insert_row, col, item)
            return insert_row
        finally:
            self.blockSignals(was_blocked)


class MainWindow(QMainWindow):
    def __init__(self, service: TaskService) -> None:
        super().__init__()
        self.service = service
        self._loading_table = False

        self.setWindowTitle("To-Do List")
        self.resize(980, 620)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout()
        root.setLayout(layout)

        actions_bar = QHBoxLayout()
        self.new_button = QPushButton("Nova tarefa")
        self.new_subtask_button = QPushButton("Nova subtarefa")
        self.edit_button = QPushButton("Editar")
        self.delete_button = QPushButton("Apagar")
        actions_bar.addWidget(self.new_button)
        actions_bar.addWidget(self.new_subtask_button)
        actions_bar.addWidget(self.edit_button)
        actions_bar.addWidget(self.delete_button)
        actions_bar.addStretch()
        layout.addLayout(actions_bar)

        filters_bar = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItem("Por fazer", Status.TODO)
        self.status_filter.addItem("Concluidas", Status.DONE)
        self.status_filter.addItem("Todos os estados", None)

        self.priority_filter = QComboBox()
        self.priority_filter.addItem("Todas as prioridades", None)
        for priority in Priority:
            self.priority_filter.addItem(PRIORITY_LABELS_PT[priority], priority)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Pesquisar por titulo ou descricao...")

        self.sort_filter = QComboBox()
        self.sort_filter.addItem("Prioridade", "priority_desc")
        self.sort_filter.addItem("Data limite", "due_date_asc")
        self.sort_filter.addItem("Mais recentes", "created_desc")

        filters_bar.addWidget(self.status_filter)
        filters_bar.addWidget(self.priority_filter)
        filters_bar.addWidget(self.search_input, 1)
        filters_bar.addWidget(self.sort_filter)
        layout.addLayout(filters_bar)

        self.table = ReorderTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Feita", "Titulo", "Prioridade", "Data limite", "Subtarefas", "Atualizada"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.viewport().setAcceptDrops(True)
        self.table.setDropIndicatorShown(True)
        self.table.setDragDropOverwriteMode(False)
        self.table.setDragDropMode(QAbstractItemView.InternalMove)
        self.table.setDefaultDropAction(Qt.MoveAction)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        self.statusBar().showMessage("Pronto")

        self.new_button.clicked.connect(self._create_task)
        self.new_subtask_button.clicked.connect(self._create_subtask)
        self.edit_button.clicked.connect(self._edit_selected_item)
        self.delete_button.clicked.connect(self._delete_selected_item)
        self.status_filter.currentIndexChanged.connect(self.refresh_tasks)
        self.priority_filter.currentIndexChanged.connect(self.refresh_tasks)
        self.search_input.textChanged.connect(self.refresh_tasks)
        self.sort_filter.currentIndexChanged.connect(self.refresh_tasks)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.row_reordered.connect(self._on_rows_moved)
        self.table.set_drop_target_resolver(self._resolve_drop_target_row)
        self.table.itemDoubleClicked.connect(lambda _: self._edit_selected_item())
        self.delete_shortcut = QShortcut(QKeySequence(Qt.Key_Delete), self.table)
        self.delete_shortcut.activated.connect(self._delete_selected_item)
        self.new_subtask_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.new_subtask_shortcut.activated.connect(self._create_subtask)

        self.refresh_tasks()

    def refresh_tasks(self) -> None:
        status = self.status_filter.currentData()
        priority = self.priority_filter.currentData()
        query = self.search_input.text()
        sort = self.sort_filter.currentData()

        tasks = self.service.list_tasks(status=status, priority=priority, query=query, sort=sort)

        self._loading_table = True
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for task in tasks:
            self._append_task_row(task)
            subtasks = self.service.list_subtasks(task.id)
            self._append_nested_subtasks(task.id, subtasks)
        self.table.blockSignals(False)
        self._loading_table = False

        self.statusBar().showMessage(f"{len(tasks)} tarefa(s)")

    def _append_task_row(self, task: Task) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        checkbox_item = self._build_check_item(
            done=task.status is Status.DONE,
            entity_type="task",
            entity_id=task.id,
            task_id=task.id,
            parent_subtask_id=None,
            depth=0,
        )
        self.table.setItem(row, 0, checkbox_item)

        title_item = QTableWidgetItem(task.title)
        self._set_item_identity(title_item, "task", task.id, task.id, parent_subtask_id=None, depth=0)
        self.table.setItem(row, 1, title_item)

        self.table.setItem(row, 2, QTableWidgetItem(priority_label_pt(task.priority)))
        due_date_text = task.due_date.isoformat() if task.due_date else "Sem data"
        self.table.setItem(row, 3, QTableWidgetItem(due_date_text))

        progress_text = (
            "Sem subtarefas"
            if task.subtask_total == 0
            else f"{task.subtask_done}/{task.subtask_total} concluidas"
        )
        self.table.setItem(row, 4, QTableWidgetItem(progress_text))
        self.table.setItem(row, 5, QTableWidgetItem(_format_datetime(task.updated_at)))
        self._set_row_drag_enabled(row, enabled=False)

        if task.status is Status.DONE:
            self._strike_row_text(row)

    def _append_nested_subtasks(self, task_id: int, subtasks: list[Subtask]) -> None:
        children_by_parent: dict[int | None, list[Subtask]] = {}
        for subtask in subtasks:
            children_by_parent.setdefault(subtask.parent_subtask_id, []).append(subtask)

        for root_subtask in children_by_parent.get(None, []):
            self._append_subtask_recursive(task_id, root_subtask, children_by_parent, depth=1)

    def _append_subtask_recursive(
        self,
        task_id: int,
        subtask: Subtask,
        children_by_parent: dict[int | None, list[Subtask]],
        depth: int,
    ) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        checkbox_item = self._build_check_item(
            done=subtask.status is Status.DONE,
            entity_type="subtask",
            entity_id=subtask.id,
            task_id=task_id,
            parent_subtask_id=subtask.parent_subtask_id,
            depth=depth,
        )
        self.table.setItem(row, 0, checkbox_item)

        indent = "    " * depth
        title_text = f"{indent}- {subtask.title}"
        title_item = QTableWidgetItem(title_text)
        if subtask.description:
            title_item.setToolTip(subtask.description)
        self._set_item_identity(
            title_item,
            "subtask",
            subtask.id,
            task_id,
            parent_subtask_id=subtask.parent_subtask_id,
            depth=depth,
        )
        self.table.setItem(row, 1, title_item)

        self.table.setItem(row, 2, QTableWidgetItem(""))
        self.table.setItem(row, 3, QTableWidgetItem(""))
        child_count = len(children_by_parent.get(subtask.id, []))
        child_text = "" if child_count == 0 else f"{child_count} sub"
        self.table.setItem(row, 4, QTableWidgetItem(child_text))
        self.table.setItem(row, 5, QTableWidgetItem(_format_datetime(subtask.updated_at)))
        self._set_row_drag_enabled(row, enabled=True)

        if subtask.status is Status.DONE:
            self._strike_row_text(row)

        for child in children_by_parent.get(subtask.id, []):
            self._append_subtask_recursive(task_id, child, children_by_parent, depth=depth + 1)

    def _build_check_item(
        self,
        done: bool,
        entity_type: str,
        entity_id: int,
        task_id: int,
        parent_subtask_id: int | None,
        depth: int,
    ) -> QTableWidgetItem:
        checkbox_item = QTableWidgetItem("")
        checkbox_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        checkbox_item.setCheckState(Qt.Checked if done else Qt.Unchecked)
        self._set_item_identity(
            checkbox_item,
            entity_type,
            entity_id,
            task_id,
            parent_subtask_id=parent_subtask_id,
            depth=depth,
        )
        return checkbox_item

    def _set_item_identity(
        self,
        item: QTableWidgetItem,
        entity_type: str,
        entity_id: int,
        task_id: int,
        parent_subtask_id: int | None,
        depth: int,
    ) -> None:
        item.setData(ROLE_ENTITY_TYPE, entity_type)
        item.setData(ROLE_ENTITY_ID, entity_id)
        item.setData(ROLE_TASK_ID, task_id)
        item.setData(ROLE_PARENT_SUBTASK_ID, parent_subtask_id)
        item.setData(ROLE_DEPTH, depth)

    def _set_row_drag_enabled(self, row: int, enabled: bool) -> None:
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            if item is None:
                continue
            flags = item.flags() | Qt.ItemIsDropEnabled
            if enabled:
                flags |= Qt.ItemIsDragEnabled
            else:
                flags &= ~Qt.ItemIsDragEnabled
            item.setFlags(flags)

    def _strike_row_text(self, row: int) -> None:
        for column in (1, 2, 3, 4, 5):
            item = self.table.item(row, column)
            if item is None:
                continue
            font = QFont(item.font())
            font.setStrikeOut(True)
            item.setFont(font)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading_table or item.column() != 0:
            return

        entity_type = item.data(ROLE_ENTITY_TYPE)
        entity_id = item.data(ROLE_ENTITY_ID)
        done = item.checkState() == Qt.Checked

        try:
            if entity_type == "task":
                self.service.mark_done(int(entity_id), done)
            elif entity_type == "subtask":
                self.service.mark_subtask_done(int(entity_id), done)
            self.refresh_tasks()
        except ValueError as exc:
            QMessageBox.warning(self, "Erro", str(exc))
            self.refresh_tasks()

    def _resolve_drop_target_row(self, source_row: int, drop_y: int) -> int | None:
        source = self._row_identity(source_row)
        if source is None or source["entity_type"] != "subtask":
            return None

        task_id = int(source["task_id"])
        parent_subtask_id = source["parent_subtask_id"]
        sibling_rows = [
            row
            for row in range(self.table.rowCount())
            if (
                (row_identity := self._row_identity(row)) is not None
                and row_identity["entity_type"] == "subtask"
                and int(row_identity["task_id"]) == task_id
                and row_identity["parent_subtask_id"] == parent_subtask_id
            )
        ]
        if len(sibling_rows) <= 1:
            return source_row

        hovered_row = self.table.rowAt(drop_y)
        if hovered_row < 0:
            target_row = (
                sibling_rows[0]
                if drop_y < self._gap_y(sibling_rows[0])
                else self._subtree_end_row(sibling_rows[-1])
            )
        else:
            reference_row = (
                hovered_row
                if hovered_row in sibling_rows
                else min(sibling_rows, key=lambda row: abs(drop_y - self._row_center_y(row)))
            )
            target_row = (
                reference_row
                if drop_y < self._row_center_y(reference_row)
                else self._subtree_end_row(reference_row)
            )

        source_index = sibling_rows.index(source_row)
        target_index = self._slot_index_from_row(sibling_rows, target_row)
        if target_index in {source_index, source_index + 1}:
            return source_row
        return target_row

    def _row_identity(self, row: int) -> dict[str, int | str | None] | None:
        title_item = self.table.item(row, 1)
        if title_item is None:
            return None
        entity_type = title_item.data(ROLE_ENTITY_TYPE)
        entity_id = title_item.data(ROLE_ENTITY_ID)
        task_id = title_item.data(ROLE_TASK_ID)
        parent_raw = title_item.data(ROLE_PARENT_SUBTASK_ID)
        depth_raw = title_item.data(ROLE_DEPTH)
        if entity_type not in {"task", "subtask"}:
            return None
        if entity_id is None or task_id is None or depth_raw is None:
            return None
        return {
            "entity_type": str(entity_type),
            "entity_id": int(entity_id),
            "task_id": int(task_id),
            "parent_subtask_id": int(parent_raw) if parent_raw is not None else None,
            "depth": int(depth_raw),
        }

    def _subtree_end_row(self, row: int) -> int:
        start = self._row_identity(row)
        if start is None or start["entity_type"] != "subtask":
            return row + 1

        task_id = int(start["task_id"])
        start_depth = int(start["depth"])
        cursor = row + 1
        while cursor < self.table.rowCount():
            current = self._row_identity(cursor)
            if current is None:
                break
            if int(current["task_id"]) != task_id:
                break
            if current["entity_type"] != "subtask":
                break
            if int(current["depth"]) <= start_depth:
                break
            cursor += 1
        return cursor

    def _gap_y(self, row: int) -> int:
        row_count = self.table.rowCount()
        if row_count == 0:
            return 0
        if row <= 0:
            return self.table.visualRect(self.table.model().index(0, 0)).top()
        if row >= row_count:
            return self.table.visualRect(self.table.model().index(row_count - 1, 0)).bottom() + 1
        return self.table.visualRect(self.table.model().index(row, 0)).top()

    def _row_center_y(self, row: int) -> int:
        rect = self.table.visualRect(self.table.model().index(row, 0))
        return rect.center().y()

    def _slot_index_from_row(self, sibling_rows: list[int], target_row: int) -> int:
        for idx, row in enumerate(sibling_rows):
            if target_row <= row:
                return idx
        return len(sibling_rows)

    def _on_rows_moved(self, *_: object) -> None:
        if self._loading_table:
            return

        try:
            changed = self._persist_visible_subtask_order()
        except (ValidationError, ValueError) as exc:
            QMessageBox.warning(self, "Erro", str(exc))
            self.refresh_tasks()
            return

        if changed:
            self.refresh_tasks()

    def _persist_visible_subtask_order(self) -> bool:
        grouped_order: dict[tuple[int, int | None], list[int]] = {}
        for row in range(self.table.rowCount()):
            title_item = self.table.item(row, 1)
            if title_item is None:
                continue
            if title_item.data(ROLE_ENTITY_TYPE) != "subtask":
                continue
            task_id = int(title_item.data(ROLE_TASK_ID))
            subtask_id = int(title_item.data(ROLE_ENTITY_ID))
            parent_raw = title_item.data(ROLE_PARENT_SUBTASK_ID)
            parent_subtask_id = int(parent_raw) if parent_raw is not None else None
            grouped_order.setdefault((task_id, parent_subtask_id), []).append(subtask_id)

        if not grouped_order:
            return False

        existing_order_by_group: dict[tuple[int, int | None], list[int]] = {}
        for task_id in sorted({task_id for task_id, _ in grouped_order}):
            for subtask in self.service.list_subtasks(task_id):
                key = (task_id, subtask.parent_subtask_id)
                existing_order_by_group.setdefault(key, []).append(subtask.id)

        changed = False
        for key, new_order in grouped_order.items():
            if existing_order_by_group.get(key, []) == new_order:
                continue
            task_id, parent_subtask_id = key
            self.service.reorder_subtasks(
                task_id=task_id,
                parent_subtask_id=parent_subtask_id,
                ordered_subtask_ids=new_order,
            )
            changed = True

        return changed

    def _create_task(self) -> None:
        dialog = TaskDialog(self)
        if dialog.exec() != TaskDialog.Accepted:
            return

        title, description, priority, due_date = dialog.get_values()
        try:
            self.service.create_task(
                title=title,
                description=description,
                priority=priority,
                due_date=due_date,
            )
            self.refresh_tasks()
        except ValidationError as exc:
            QMessageBox.warning(self, "Validacao", str(exc))

    def _create_subtask(self) -> None:
        selected = self._selected_entity()
        if selected is None:
            QMessageBox.information(
                self,
                "Nova subtarefa",
                "Seleciona primeiro uma tarefa ou subtarefa para definir onde criar.",
            )
            return

        parent_subtask_id: int | None
        task_id = selected["task_id"]
        if selected["entity_type"] == "task":
            parent_subtask_id = None
        else:
            parent_subtask_id = selected["entity_id"]

        dialog = SubtaskDialog(self, is_edit=False)
        if dialog.exec() != SubtaskDialog.Accepted:
            return
        title, description = dialog.get_values()
        if not title:
            return

        try:
            self.service.create_subtask(
                task_id=task_id,
                title=title,
                description=description,
                parent_subtask_id=parent_subtask_id,
            )
            self.refresh_tasks()
        except (ValidationError, ValueError) as exc:
            QMessageBox.warning(self, "Erro", str(exc))

    def _edit_selected_item(self) -> None:
        selected = self._selected_entity()
        if selected is None:
            QMessageBox.information(self, "Editar", "Seleciona uma tarefa ou subtarefa para editar.")
            return

        if selected["entity_type"] == "task":
            self._edit_selected_task(selected["entity_id"])
        else:
            self._edit_selected_subtask(selected["entity_id"])

    def _edit_selected_task(self, task_id: int) -> None:
        task = self.service.get_task(task_id)
        dialog = TaskDialog(self, task=task)
        if dialog.exec() != TaskDialog.Accepted:
            return

        title, description, priority, due_date = dialog.get_values()
        try:
            self.service.update_task(
                task_id=task_id,
                title=title,
                description=description,
                priority=priority,
                due_date=due_date,
            )
            self.refresh_tasks()
        except (ValidationError, ValueError) as exc:
            QMessageBox.warning(self, "Erro", str(exc))

    def _edit_selected_subtask(self, subtask_id: int) -> None:
        subtask = self.service.get_subtask(subtask_id)
        dialog = SubtaskDialog(
            self,
            title=subtask.title,
            description=subtask.description,
            is_edit=True,
        )
        if dialog.exec() != SubtaskDialog.Accepted:
            return
        title, description = dialog.get_values()
        try:
            self.service.update_subtask(
                subtask_id=subtask_id,
                title=title,
                description=description,
            )
            self.refresh_tasks()
        except (ValidationError, ValueError) as exc:
            QMessageBox.warning(self, "Erro", str(exc))

    def _delete_selected_item(self) -> None:
        selected_entities = self._selected_entities()
        if not selected_entities:
            QMessageBox.information(
                self,
                "Apagar",
                "Seleciona uma ou mais tarefas/subtarefas para apagar.",
            )
            return

        task_count = sum(1 for item in selected_entities if item["entity_type"] == "task")
        subtask_count = len(selected_entities) - task_count
        if task_count and subtask_count:
            message = (
                f"Tens a certeza que queres apagar {task_count} tarefa(s) e "
                f"{subtask_count} subtarefa(s)?"
            )
        elif task_count > 1:
            message = f"Tens a certeza que queres apagar as {task_count} tarefas selecionadas?"
        elif task_count == 1 and subtask_count == 0:
            message = "Tens a certeza que queres apagar a tarefa selecionada?"
        elif subtask_count > 1:
            message = (
                f"Tens a certeza que queres apagar as {subtask_count} subtarefas selecionadas? "
                "Subtarefas-filhas tambem serao apagadas."
            )
        else:
            message = (
                "Tens a certeza que queres apagar a subtarefa selecionada? "
                "As subtarefas-filhas tambem serao apagadas."
            )

        answer = QMessageBox.question(
            self,
            "Confirmar apagamento",
            message,
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        entities_to_delete = self._normalize_delete_selection(selected_entities)
        errors: list[str] = []
        for item in entities_to_delete:
            try:
                if item["entity_type"] == "task":
                    self.service.delete_task(item["entity_id"])
                else:
                    self.service.delete_subtask(item["entity_id"])
            except ValueError as exc:
                # Ignore "already deleted" from cascade effects.
                if "nao existe" not in str(exc):
                    errors.append(str(exc))

        self.refresh_tasks()
        if errors:
            QMessageBox.warning(self, "Erro", errors[0])

    def _selected_entity(self) -> dict[str, int | str] | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        title_item = self.table.item(row, 1)
        if title_item is None:
            return None
        entity_type = title_item.data(ROLE_ENTITY_TYPE)
        entity_id = title_item.data(ROLE_ENTITY_ID)
        task_id = title_item.data(ROLE_TASK_ID)
        if entity_type not in {"task", "subtask"}:
            return None
        if entity_id is None or task_id is None:
            return None
        return {
            "entity_type": str(entity_type),
            "entity_id": int(entity_id),
            "task_id": int(task_id),
        }

    def _selected_entities(self) -> list[dict[str, int | str]]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        entities: list[dict[str, int | str]] = []
        seen: set[tuple[str, int]] = set()

        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]

        for row in rows:
            title_item = self.table.item(row, 1)
            if title_item is None:
                continue
            entity_type = title_item.data(ROLE_ENTITY_TYPE)
            entity_id = title_item.data(ROLE_ENTITY_ID)
            task_id = title_item.data(ROLE_TASK_ID)
            if entity_type not in {"task", "subtask"}:
                continue
            if entity_id is None or task_id is None:
                continue
            key = (str(entity_type), int(entity_id))
            if key in seen:
                continue
            seen.add(key)
            entities.append(
                {
                    "entity_type": str(entity_type),
                    "entity_id": int(entity_id),
                    "task_id": int(task_id),
                }
            )

        return entities

    def _normalize_delete_selection(
        self, entities: list[dict[str, int | str]]
    ) -> list[dict[str, int | str]]:
        selected_task_ids = {
            int(entity["entity_id"])
            for entity in entities
            if entity["entity_type"] == "task"
        }

        filtered = [
            entity
            for entity in entities
            if not (
                entity["entity_type"] == "subtask"
                and int(entity["task_id"]) in selected_task_ids
            )
        ]

        filtered.sort(key=lambda entity: 0 if entity["entity_type"] == "task" else 1)
        return filtered


def _format_datetime(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M")
