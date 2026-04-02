from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
)


class SubtaskDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        title: str = "",
        description: str = "",
        is_edit: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar subtarefa" if is_edit else "Nova subtarefa")
        self.setModal(True)
        self.resize(420, 260)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Titulo da subtarefa")
        self.title_input.setText(title)

        self.description_input = QTextEdit()
        self.description_input.setPlaceholderText("Descricao (opcional)")
        self.description_input.setPlainText(description)

        form = QFormLayout()
        form.addRow("Titulo", self.title_input)
        form.addRow("Descricao", self.description_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def get_values(self) -> tuple[str, str]:
        return self.title_input.text(), self.description_input.toPlainText()
