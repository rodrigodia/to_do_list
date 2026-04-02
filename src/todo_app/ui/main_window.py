from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
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

from todo_app.models import PRIORITY_LABELS_PT, Priority, Status, Task, priority_label_pt
from todo_app.service import TaskService, ValidationError
from todo_app.ui.task_dialog import TaskDialog


class MainWindow(QMainWindow):
    def __init__(self, service: TaskService) -> None:
        super().__init__()
        self.service = service
        self._loading_table = False

        self.setWindowTitle("To-Do List")
        self.resize(920, 560)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout()
        root.setLayout(layout)

        actions_bar = QHBoxLayout()
        self.new_button = QPushButton("Nova tarefa")
        self.edit_button = QPushButton("Editar")
        self.delete_button = QPushButton("Apagar")
        actions_bar.addWidget(self.new_button)
        actions_bar.addWidget(self.edit_button)
        actions_bar.addWidget(self.delete_button)
        actions_bar.addStretch()
        layout.addLayout(actions_bar)

        filters_bar = QHBoxLayout()
        self.status_filter = QComboBox()
        self.status_filter.addItem("Todos os estados", None)
        self.status_filter.addItem("Por fazer", Status.TODO)
        self.status_filter.addItem("Concluidas", Status.DONE)

        self.priority_filter = QComboBox()
        self.priority_filter.addItem("Todas as prioridades", None)
        for priority in Priority:
            self.priority_filter.addItem(PRIORITY_LABELS_PT[priority], priority)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Pesquisar por titulo ou descricao...")

        self.sort_filter = QComboBox()
        self.sort_filter.addItem("Mais recentes", "created_desc")
        self.sort_filter.addItem("Data limite", "due_date_asc")
        self.sort_filter.addItem("Prioridade", "priority_desc")

        filters_bar.addWidget(self.status_filter)
        filters_bar.addWidget(self.priority_filter)
        filters_bar.addWidget(self.search_input, 1)
        filters_bar.addWidget(self.sort_filter)
        layout.addLayout(filters_bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Feita", "Titulo", "Prioridade", "Data limite", "Atualizada"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self.table)

        self.statusBar().showMessage("Pronto")

        self.new_button.clicked.connect(self._create_task)
        self.edit_button.clicked.connect(self._edit_selected_task)
        self.delete_button.clicked.connect(self._delete_selected_task)
        self.status_filter.currentIndexChanged.connect(self.refresh_tasks)
        self.priority_filter.currentIndexChanged.connect(self.refresh_tasks)
        self.search_input.textChanged.connect(self.refresh_tasks)
        self.sort_filter.currentIndexChanged.connect(self.refresh_tasks)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemDoubleClicked.connect(lambda _: self._edit_selected_task())

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
        self.table.blockSignals(False)
        self._loading_table = False

        self.statusBar().showMessage(f"{len(tasks)} tarefa(s)")

    def _append_task_row(self, task: Task) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        checkbox_item = QTableWidgetItem("")
        checkbox_item.setData(Qt.UserRole, task.id)
        checkbox_item.setFlags(
            Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
        )
        checkbox_item.setCheckState(Qt.Checked if task.status is Status.DONE else Qt.Unchecked)
        self.table.setItem(row, 0, checkbox_item)

        title_item = QTableWidgetItem(task.title)
        title_item.setData(Qt.UserRole, task.id)
        self.table.setItem(row, 1, title_item)

        priority_item = QTableWidgetItem(priority_label_pt(task.priority))
        self.table.setItem(row, 2, priority_item)

        due_date_text = task.due_date.isoformat() if task.due_date else "Sem data"
        self.table.setItem(row, 3, QTableWidgetItem(due_date_text))

        updated_text = _format_datetime(task.updated_at)
        self.table.setItem(row, 4, QTableWidgetItem(updated_text))

        if task.status is Status.DONE:
            self._strike_row_text(row)

    def _strike_row_text(self, row: int) -> None:
        for column in (1, 2, 3, 4):
            item = self.table.item(row, column)
            if item is None:
                continue
            font = QFont(item.font())
            font.setStrikeOut(True)
            item.setFont(font)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading_table or item.column() != 0:
            return

        task_id = item.data(Qt.UserRole)
        done = item.checkState() == Qt.Checked
        try:
            self.service.mark_done(int(task_id), done)
            self.refresh_tasks()
        except ValueError as exc:
            QMessageBox.warning(self, "Erro", str(exc))
            self.refresh_tasks()

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

    def _edit_selected_task(self) -> None:
        task_id = self._selected_task_id()
        if task_id is None:
            QMessageBox.information(self, "Editar tarefa", "Seleciona uma tarefa para editar.")
            return

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

    def _delete_selected_task(self) -> None:
        task_id = self._selected_task_id()
        if task_id is None:
            QMessageBox.information(self, "Apagar tarefa", "Seleciona uma tarefa para apagar.")
            return

        answer = QMessageBox.question(
            self,
            "Confirmar apagamento",
            "Tens a certeza que queres apagar a tarefa selecionada?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            self.service.delete_task(task_id)
            self.refresh_tasks()
        except ValueError as exc:
            QMessageBox.warning(self, "Erro", str(exc))

    def _selected_task_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        title_item = self.table.item(row, 1)
        if title_item is None:
            return None
        task_id = title_item.data(Qt.UserRole)
        if task_id is None:
            return None
        return int(task_id)


def _format_datetime(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M")
