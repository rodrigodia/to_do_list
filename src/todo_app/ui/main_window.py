from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

from PySide6.QtCore import (
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDropEvent,
    QFont,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPalette,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from todo_app.models import (
    PRIORITY_LABELS_PT,
    DeletionSnapshot,
    Priority,
    Status,
    Subtask,
    Task,
    priority_label_pt,
)
from todo_app.service import TaskService, ValidationError
from todo_app.ui.subtask_dialog import SubtaskDialog
from todo_app.ui.task_dialog import TaskDialog

ROLE_ENTITY_TYPE = Qt.UserRole
ROLE_ENTITY_ID = Qt.UserRole + 1
ROLE_TASK_ID = Qt.UserRole + 2
ROLE_PARENT_SUBTASK_ID = Qt.UserRole + 3
ROLE_DEPTH = Qt.UserRole + 4
ROLE_GROUP_ACCENT = Qt.UserRole + 5

SEARCH_DEBOUNCE_MS = 250
UNDO_STACK_LIMIT = 20
STATUS_MESSAGE_MS = 8000

PRIORITY_COLORS = {
    Priority.HIGH: QColor("#c62828"),
    Priority.MEDIUM: QColor("#ef6c00"),
    Priority.LOW: QColor("#2e7d32"),
}
OVERDUE_COLOR = QColor("#c62828")

# Intensidade (0-1) com que a cor do texto e misturada no fundo, para funcionar em
# temas claros e escuros sem cores fixas.
GROUP_ALT_TINT = 0.035
TASK_HEADER_TINT = 0.09
SEPARATOR_TINT = 0.35
ACCENT_WIDTH = 4
CHECK_COLUMN_OFFSET = ACCENT_WIDTH + 4

TREE_BRANCH = "├─ "
TREE_LAST = "└─ "
TREE_PIPE = "│   "
TREE_SPACE = "     "

DropTargetResolver = Callable[[int, int], int | None]
EntityKey = tuple[str, int]


@dataclass(slots=True, frozen=True)
class GroupStyle:
    background: QColor
    header_background: QColor
    accent: QColor


def _mix(base: QColor, other: QColor, amount: float) -> QColor:
    return QColor.fromRgbF(
        base.redF() + (other.redF() - base.redF()) * amount,
        base.greenF() + (other.greenF() - base.greenF()) * amount,
        base.blueF() + (other.blueF() - base.blueF()) * amount,
    )


class TaskGroupDelegate(QStyledItemDelegate):
    """Desenha a barra de cor de cada grupo e o separador acima de cada tarefa."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        if index.column() == 0:
            if option.state & QStyle.State_Selected:
                gutter = option.palette.highlight()
            else:
                gutter = index.data(Qt.BackgroundRole) or option.palette.base()
            painter.fillRect(option.rect, gutter)
            super().paint(painter, self._shifted(option), index)
            accent = index.data(ROLE_GROUP_ACCENT)
            if accent is not None:
                bar = QRect(
                    option.rect.left(), option.rect.top(), ACCENT_WIDTH, option.rect.height()
                )
                painter.fillRect(bar, accent)
        else:
            super().paint(painter, option, index)

        if index.row() > 0 and _is_task_row(index):
            painter.save()
            palette = option.palette
            color = _mix(palette.color(QPalette.Base), palette.color(QPalette.Text), SEPARATOR_TINT)
            painter.setPen(QPen(color, 1))
            painter.drawLine(option.rect.topLeft(), option.rect.topRight())
            painter.restore()

    def editorEvent(
        self,
        event: QEvent,
        model,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> bool:
        if index.column() == 0:
            option = self._shifted(option)
        return super().editorEvent(event, model, option, index)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        if index.column() == 0:
            size.setWidth(size.width() + CHECK_COLUMN_OFFSET)
        return size

    @staticmethod
    def _shifted(option: QStyleOptionViewItem) -> QStyleOptionViewItem:
        shifted = QStyleOptionViewItem(option)
        shifted.rect = option.rect.adjusted(CHECK_COLUMN_OFFSET, 0, 0, 0)
        return shifted


def _is_task_row(index: QModelIndex) -> bool:
    return index.siblingAtColumn(1).data(ROLE_ENTITY_TYPE) == "task"


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

        source_row = (
            self._drag_source_row if self._drag_source_row is not None else self.currentRow()
        )
        self._drag_source_row = None
        if self.move_row_by_drop(source_row, int(event.position().y())):
            event.acceptProposedAction()
        else:
            event.ignore()

    def move_row_by_drop(self, source_row: int, drop_y: int) -> bool:
        """Move a linha como se tivesse sido largada na coordenada vertical drop_y."""
        if source_row < 0 or self._drop_target_resolver is None:
            return False

        target_row = self._drop_target_resolver(source_row, drop_y)
        if target_row is None:
            return False

        moved_row = self._move_row(source_row, target_row)
        if moved_row is None:
            return False

        # selectRow/setCurrentCell dependem das teclas modificadoras (ex.: Ctrl alterna a
        # selecao), por isso a linha movida e selecionada diretamente no modelo de selecao.
        selection_model = self.selectionModel()
        selection_model.setCurrentIndex(
            self.model().index(moved_row, 1),
            QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows,
        )
        self.row_reordered.emit()
        return True

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
        self._undo_stack: list[DeletionSnapshot] = []

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
        self.undo_button = QPushButton("Desfazer")
        self.undo_button.setEnabled(False)
        actions_bar.addWidget(self.new_button)
        actions_bar.addWidget(self.new_subtask_button)
        actions_bar.addWidget(self.edit_button)
        actions_bar.addWidget(self.delete_button)
        actions_bar.addWidget(self.undo_button)
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
        # As cores alternam por grupo (tarefa + subtarefas), nao por linha.
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setItemDelegate(TaskGroupDelegate(self.table))
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

        self.task_count_label = QLabel()
        self.statusBar().addPermanentWidget(self.task_count_label)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self.search_timer.timeout.connect(self._on_filters_changed)

        self.new_button.clicked.connect(self._create_task)
        self.new_subtask_button.clicked.connect(self._create_subtask)
        self.edit_button.clicked.connect(self._edit_selected_item)
        self.delete_button.clicked.connect(self._delete_selected_item)
        self.undo_button.clicked.connect(self._undo_last_delete)
        self.status_filter.currentIndexChanged.connect(self._on_filters_changed)
        self.priority_filter.currentIndexChanged.connect(self._on_filters_changed)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.sort_filter.currentIndexChanged.connect(self._on_filters_changed)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.row_reordered.connect(self._on_rows_moved)
        self.table.set_drop_target_resolver(self._resolve_drop_target_row)
        self.table.itemDoubleClicked.connect(lambda _: self._edit_selected_item())
        self.delete_shortcut = QShortcut(QKeySequence(Qt.Key_Delete), self.table)
        self.delete_shortcut.activated.connect(self._delete_selected_item)
        self.new_subtask_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self.new_subtask_shortcut.activated.connect(self._create_subtask)
        self.undo_shortcut = QShortcut(QKeySequence.Undo, self)
        self.undo_shortcut.activated.connect(self._undo_last_delete)

        self.refresh_tasks()

    def _on_filters_changed(self, *_: object) -> None:
        self.refresh_tasks()

    def _on_search_text_changed(self, _text: str) -> None:
        # Espera que o utilizador pare de escrever antes de voltar a consultar a BD.
        self.search_timer.start()

    def refresh_tasks(self, select: set[EntityKey] | None = None) -> None:
        """Redesenha a tabela.

        Por omissao mantem a selecao, a linha atual e o scroll. Se `select` for dado,
        seleciona essas entidades e faz scroll ate elas.
        """
        self.search_timer.stop()
        if select is None:
            keys_to_select = self._selected_keys()
            current_key = self._current_key()
        else:
            keys_to_select = select
            current_key = next(iter(select), None)
        scroll_value = self.table.verticalScrollBar().value()

        status = self.status_filter.currentData()
        priority = self.priority_filter.currentData()
        query = self.search_input.text()
        sort = self.sort_filter.currentData()

        tasks = self.service.list_tasks(status=status, priority=priority, query=query, sort=sort)
        subtasks_by_task = self.service.list_subtasks_for_tasks([task.id for task in tasks])
        today = datetime.now().astimezone().date()

        self._loading_table = True
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for group_index, task in enumerate(tasks):
            style = self._group_style(group_index, task)
            self._append_task_row(task, today, style)
            self._append_nested_subtasks(task.id, subtasks_by_task.get(task.id, []), style)
        self.table.blockSignals(False)
        self._loading_table = False

        self._restore_selection(keys_to_select, current_key)
        if select is None:
            self.table.verticalScrollBar().setValue(scroll_value)
        else:
            self._scroll_to_key(current_key)

        self.task_count_label.setText(f"{len(tasks)} tarefa(s)")

    def _group_style(self, group_index: int, task: Task) -> GroupStyle:
        palette = self.table.palette()
        base = palette.color(QPalette.Base)
        text = palette.color(QPalette.Text)
        background = base if group_index % 2 == 0 else _mix(base, text, GROUP_ALT_TINT)
        accent = (
            palette.color(QPalette.Mid)
            if task.status is Status.DONE
            else PRIORITY_COLORS[task.priority]
        )
        return GroupStyle(
            background=background,
            header_background=_mix(background, text, TASK_HEADER_TINT),
            accent=accent,
        )

    def _apply_group_style(self, row: int, background: QColor, accent: QColor) -> None:
        for column in range(self.table.columnCount()):
            item = self.table.item(row, column)
            if item is not None:
                item.setBackground(background)
        self.table.item(row, 0).setData(ROLE_GROUP_ACCENT, accent)

    def _append_task_row(self, task: Task, today: date, style: GroupStyle) -> None:
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
        title_font = QFont(title_item.font())
        title_font.setBold(True)
        title_item.setFont(title_font)
        if task.description:
            title_item.setToolTip(task.description)
        self._set_item_identity(
            title_item, "task", task.id, task.id, parent_subtask_id=None, depth=0
        )
        self.table.setItem(row, 1, title_item)

        priority_item = QTableWidgetItem(priority_label_pt(task.priority))
        priority_item.setForeground(PRIORITY_COLORS[task.priority])
        self.table.setItem(row, 2, priority_item)

        self.table.setItem(row, 3, self._build_due_date_item(task, today))

        progress_text = (
            "Sem subtarefas"
            if task.subtask_total == 0
            else f"{task.subtask_done}/{task.subtask_total} concluidas"
        )
        self.table.setItem(row, 4, QTableWidgetItem(progress_text))
        self.table.setItem(row, 5, QTableWidgetItem(_format_datetime(task.updated_at)))
        self._set_row_drag_enabled(row, enabled=False)
        self._apply_group_style(row, style.header_background, style.accent)

        if task.status is Status.DONE:
            self._strike_row_text(row)

    def _build_due_date_item(self, task: Task, today: date) -> QTableWidgetItem:
        if task.due_date is None:
            return QTableWidgetItem("Sem data")

        item = QTableWidgetItem(task.due_date.isoformat())
        if task.status is not Status.DONE and task.due_date < today:
            item.setText(f"{task.due_date.isoformat()} (atrasada)")
            item.setForeground(OVERDUE_COLOR)
            font = QFont(item.font())
            font.setBold(True)
            item.setFont(font)
        return item

    def _append_nested_subtasks(
        self, task_id: int, subtasks: list[Subtask], style: GroupStyle
    ) -> None:
        children_by_parent: dict[int | None, list[Subtask]] = {}
        for subtask in subtasks:
            children_by_parent.setdefault(subtask.parent_subtask_id, []).append(subtask)

        roots = children_by_parent.get(None, [])
        for idx, root_subtask in enumerate(roots):
            self._append_subtask_recursive(
                task_id,
                root_subtask,
                children_by_parent,
                depth=1,
                prefix="",
                is_last=idx == len(roots) - 1,
                style=style,
            )

    def _append_subtask_recursive(
        self,
        task_id: int,
        subtask: Subtask,
        children_by_parent: dict[int | None, list[Subtask]],
        depth: int,
        prefix: str,
        is_last: bool,
        style: GroupStyle,
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

        connector = TREE_LAST if is_last else TREE_BRANCH
        title_item = QTableWidgetItem(f"{prefix}{connector}{subtask.title}")
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
        self._apply_group_style(row, style.background, style.accent)

        if subtask.status is Status.DONE:
            self._strike_row_text(row)

        children = children_by_parent.get(subtask.id, [])
        child_prefix = prefix + (TREE_SPACE if is_last else TREE_PIPE)
        for idx, child in enumerate(children):
            self._append_subtask_recursive(
                task_id,
                child,
                children_by_parent,
                depth=depth + 1,
                prefix=child_prefix,
                is_last=idx == len(children) - 1,
                style=style,
            )

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

    def _row_key(self, row: int) -> EntityKey | None:
        title_item = self.table.item(row, 1)
        if title_item is None:
            return None
        entity_type = title_item.data(ROLE_ENTITY_TYPE)
        entity_id = title_item.data(ROLE_ENTITY_ID)
        if entity_type not in {"task", "subtask"} or entity_id is None:
            return None
        return str(entity_type), int(entity_id)

    def _row_for_key(self, key: EntityKey | None) -> int:
        if key is None:
            return -1
        for row in range(self.table.rowCount()):
            if self._row_key(row) == key:
                return row
        return -1

    def _selected_keys(self) -> set[EntityKey]:
        keys: set[EntityKey] = set()
        for index in self.table.selectionModel().selectedRows():
            key = self._row_key(index.row())
            if key is not None:
                keys.add(key)
        return keys

    def _current_key(self) -> EntityKey | None:
        row = self.table.currentRow()
        return self._row_key(row) if row >= 0 else None

    def _restore_selection(self, keys: set[EntityKey], current_key: EntityKey | None) -> None:
        selection_model = self.table.selectionModel()
        selection_model.clearSelection()

        current_row = self._row_for_key(current_key)
        if current_row >= 0:
            selection_model.setCurrentIndex(
                self.table.model().index(current_row, 1), QItemSelectionModel.NoUpdate
            )

        for row in range(self.table.rowCount()):
            if self._row_key(row) in keys:
                selection_model.select(
                    self.table.model().index(row, 0),
                    QItemSelectionModel.Select | QItemSelectionModel.Rows,
                )

    def _scroll_to_key(self, key: EntityKey | None) -> None:
        row = self._row_for_key(key)
        if row >= 0:
            self.table.scrollToItem(self.table.item(row, 1))

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

        task_ids = sorted({task_id for task_id, _ in grouped_order})
        existing_order_by_group: dict[tuple[int, int | None], list[int]] = {}
        for task_id, subtasks in self.service.list_subtasks_for_tasks(task_ids).items():
            for subtask in subtasks:
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
            created = self.service.create_task(
                title=title,
                description=description,
                priority=priority,
                due_date=due_date,
            )
            self.refresh_tasks(select={("task", created.id)})
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
            created = self.service.create_subtask(
                task_id=task_id,
                title=title,
                description=description,
                parent_subtask_id=parent_subtask_id,
            )
            self.refresh_tasks(select={("subtask", created.id)})
        except (ValidationError, ValueError) as exc:
            QMessageBox.warning(self, "Erro", str(exc))

    def _edit_selected_item(self) -> None:
        selected = self._selected_entity()
        if selected is None:
            QMessageBox.information(
                self, "Editar", "Seleciona uma tarefa ou subtarefa para editar."
            )
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

        task_ids = [int(e["entity_id"]) for e in selected_entities if e["entity_type"] == "task"]
        subtask_ids = [
            int(e["entity_id"]) for e in selected_entities if e["entity_type"] == "subtask"
        ]
        snapshot = self.service.delete_items(task_ids, subtask_ids)
        self.refresh_tasks()
        if snapshot.is_empty:
            return

        self._undo_stack.append(snapshot)
        del self._undo_stack[:-UNDO_STACK_LIMIT]
        self.undo_button.setEnabled(True)
        deleted_count = len(snapshot.tasks) + len(snapshot.subtasks)
        self.statusBar().showMessage(
            f"{deleted_count} item(ns) apagado(s). Ctrl+Z para desfazer.", STATUS_MESSAGE_MS
        )

    def _undo_last_delete(self) -> None:
        if not self._undo_stack:
            return

        snapshot = self._undo_stack.pop()
        self.undo_button.setEnabled(bool(self._undo_stack))
        try:
            self.service.restore_deleted(snapshot)
        except ValueError as exc:
            QMessageBox.warning(self, "Desfazer", str(exc))
            self.refresh_tasks()
            return

        # Seleciona so as raizes do que foi restaurado (os descendentes vem por arrasto).
        restored_keys: set[EntityKey] = {("task", task.id) for task in snapshot.tasks}
        restored_task_ids = {task.id for task in snapshot.tasks}
        restored_subtask_ids = {sub.id for sub in snapshot.subtasks}
        restored_keys |= {
            ("subtask", sub.id)
            for sub in snapshot.subtasks
            if sub.task_id not in restored_task_ids
            and sub.parent_subtask_id not in restored_subtask_ids
        }
        self.refresh_tasks(select=restored_keys)
        restored_count = len(snapshot.tasks) + len(snapshot.subtasks)
        self.statusBar().showMessage(f"{restored_count} item(ns) restaurado(s).", STATUS_MESSAGE_MS)

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


def _format_datetime(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M")
