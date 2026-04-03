from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from todo_app.repository import TaskRepository
from todo_app.service import TaskService
from todo_app.ui.main_window import MainWindow


def main() -> int:
    _set_windows_app_user_model_id()
    app = QApplication(sys.argv)
    app.setApplicationName("To-Do List")
    icon = _load_app_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    repository = TaskRepository(_default_db_path())
    repository.migrate()

    service = TaskService(repository)
    window = MainWindow(service)
    if icon is not None:
        window.setWindowIcon(icon)
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


def _load_app_icon() -> QIcon | None:
    icon_path = _icon_path()
    if icon_path is None:
        return None
    icon = QIcon(str(icon_path))
    return None if icon.isNull() else icon


def _icon_path() -> Path | None:
    icon_relative_path = Path("assets") / "images" / "icon_todo_list.jpg"

    if hasattr(sys, "_MEIPASS"):
        bundled_path = Path(getattr(sys, "_MEIPASS")) / icon_relative_path
        if bundled_path.exists():
            return bundled_path

    project_root = Path(__file__).resolve().parents[2]
    local_path = project_root / icon_relative_path
    if local_path.exists():
        return local_path

    return None


def _set_windows_app_user_model_id() -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("todo.list.app")
    except Exception:
        # Ignore if unavailable; app still runs normally.
        return
