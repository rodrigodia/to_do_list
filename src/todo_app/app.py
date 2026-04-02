from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from todo_app.repository import TaskRepository
from todo_app.service import TaskService
from todo_app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("To-Do List")

    repository = TaskRepository(_default_db_path())
    repository.migrate()

    service = TaskService(repository)
    window = MainWindow(service)
    window.show()

    return app.exec()


def _default_db_path() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.getenv("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    app_dir = base / "todo_app"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir / "todo.db"
