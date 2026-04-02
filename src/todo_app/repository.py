from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from todo_app.models import Priority, SortOption, Status, Task, TaskData, TaskFilters


class TaskRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def migrate(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    priority TEXT NOT NULL CHECK(priority IN ('low', 'medium', 'high')),
                    due_date TEXT NULL,
                    status TEXT NOT NULL CHECK(status IN ('todo', 'done')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority)")
            conn.commit()

    def create(self, task_data: TaskData) -> Task:
        now = _now_iso()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks (title, description, priority, due_date, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_data.title,
                    task_data.description,
                    task_data.priority.value,
                    task_data.due_date.isoformat() if task_data.due_date else None,
                    Status.TODO.value,
                    now,
                    now,
                ),
            )
            task_id = int(cursor.lastrowid)
            conn.commit()
        return self.get(task_id)

    def get(self, task_id: int) -> Task:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, title, description, priority, due_date, status, created_at, updated_at
                FROM tasks
                WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Tarefa com id {task_id} nao existe.")
        return _row_to_task(row)

    def update(self, task_id: int, task_data: TaskData) -> Task:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET title = ?, description = ?, priority = ?, due_date = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    task_data.title,
                    task_data.description,
                    task_data.priority.value,
                    task_data.due_date.isoformat() if task_data.due_date else None,
                    _now_iso(),
                    task_id,
                ),
            )
            conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"Tarefa com id {task_id} nao existe.")
        return self.get(task_id)

    def delete(self, task_id: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"Tarefa com id {task_id} nao existe.")

    def list(self, filters: TaskFilters | None = None, sort: SortOption = "created_desc") -> list[Task]:
        filters = filters or TaskFilters()
        where_parts: list[str] = []
        params: list[object] = []

        if filters.status is not None:
            where_parts.append("status = ?")
            params.append(filters.status.value)

        if filters.priority is not None:
            where_parts.append("priority = ?")
            params.append(filters.priority.value)

        if filters.query:
            where_parts.append("(LOWER(title) LIKE ? OR LOWER(description) LIKE ?)")
            like_value = f"%{filters.query.lower()}%"
            params.extend([like_value, like_value])

        where_sql = ""
        if where_parts:
            where_sql = "WHERE " + " AND ".join(where_parts)

        order_by = _resolve_order_by(sort)
        query = f"""
            SELECT id, title, description, priority, due_date, status, created_at, updated_at
            FROM tasks
            {where_sql}
            ORDER BY {order_by}
        """

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, tuple(params)).fetchall()

        return [_row_to_task(row) for row in rows]

    def mark_done(self, task_id: int, done: bool) -> Task:
        new_status = Status.DONE if done else Status.TODO
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (new_status.value, _now_iso(), task_id),
            )
            conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"Tarefa com id {task_id} nao existe.")
        return self.get(task_id)


def _resolve_order_by(sort: SortOption) -> str:
    if sort == "due_date_asc":
        return "CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date ASC, created_at DESC"
    if sort == "priority_desc":
        return (
            "CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 "
            "WHEN 'low' THEN 2 ELSE 3 END, created_at DESC"
        )
    return "created_at DESC"


def _row_to_task(row: sqlite3.Row) -> Task:
    due_date_text = row["due_date"]
    return Task(
        id=int(row["id"]),
        title=row["title"],
        description=row["description"],
        priority=Priority(row["priority"]),
        due_date=date.fromisoformat(due_date_text) if due_date_text else None,
        status=Status(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
