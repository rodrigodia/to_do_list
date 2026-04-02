from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
)

from todo_app.models import PRIORITY_LABELS_PT, Priority, Task


class TaskDialog(QDialog):
    def __init__(self, parent=None, task: Task | None = None) -> None:
        super().__init__(parent)
        self.task = task
        self.setWindowTitle("Editar tarefa" if task else "Nova tarefa")
        self.setModal(True)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Ex.: Preparar reuniao de sprint")

        self.description_input = QTextEdit()
        self.description_input.setPlaceholderText("Notas da tarefa...")
        self.description_input.setFixedHeight(90)

        self.priority_input = QComboBox()
        for priority in Priority:
            self.priority_input.addItem(PRIORITY_LABELS_PT[priority], priority)

        self.no_due_date_checkbox = QCheckBox("Sem data limite")
        self.no_due_date_checkbox.setChecked(True)

        self.due_date_input = QDateEdit()
        self.due_date_input.setCalendarPopup(True)
        self.due_date_input.setDate(QDate.currentDate())
        self.due_date_input.setEnabled(False)

        self.no_due_date_checkbox.toggled.connect(self._toggle_due_date)

        form = QFormLayout()
        form.addRow("Titulo", self.title_input)
        form.addRow("Descricao", self.description_input)
        form.addRow("Prioridade", self.priority_input)
        form.addRow("", self.no_due_date_checkbox)
        form.addRow("Data limite", self.due_date_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

        if task is not None:
            self._load_task(task)

    def get_values(self) -> tuple[str, str, Priority, date | None]:
        title = self.title_input.text()
        description = self.description_input.toPlainText()
        priority = self.priority_input.currentData()
        due_date = None if self.no_due_date_checkbox.isChecked() else self.due_date_input.date().toPython()
        return title, description, priority, due_date

    def _toggle_due_date(self, no_due_date: bool) -> None:
        self.due_date_input.setEnabled(not no_due_date)

    def _load_task(self, task: Task) -> None:
        self.title_input.setText(task.title)
        self.description_input.setText(task.description)

        idx = self.priority_input.findData(task.priority)
        if idx >= 0:
            self.priority_input.setCurrentIndex(idx)

        if task.due_date is None:
            self.no_due_date_checkbox.setChecked(True)
            self.due_date_input.setEnabled(False)
        else:
            self.no_due_date_checkbox.setChecked(False)
            self.due_date_input.setEnabled(True)
            self.due_date_input.setDate(QDate(task.due_date.year, task.due_date.month, task.due_date.day))
