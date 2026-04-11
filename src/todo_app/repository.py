from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from todo_app.models import (
    Priority,
    SortOption,
    Status,
    Subtask,
    SubtaskData,
    Task,
    TaskData,
    TaskFilters,
    TaskWithSubtasks,
)


class TaskRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def migrate(self) -> None:
        with self._connect() as conn:
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

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS subtasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    parent_subtask_id INTEGER NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK(status IN ('todo', 'done')),
                    position INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY(parent_subtask_id) REFERENCES subtasks(id) ON DELETE CASCADE
                )
                """
            )

            _ensure_subtasks_compat_columns(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_subtasks_task_id ON subtasks(task_id)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_subtasks_parent_id ON subtasks(parent_subtask_id)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_subtasks_status ON subtasks(status)")
            conn.commit()

    def create(self, task_data: TaskData) -> Task:
        now = _now_iso()
        with self._connect() as conn:
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
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT
                    t.id,
                    t.title,
                    t.description,
                    t.priority,
                    t.due_date,
                    t.status,
                    t.created_at,
                    t.updated_at,
                    (
                        SELECT COUNT(*)
                        FROM subtasks s
                        WHERE s.task_id = t.id
                    ) AS subtask_total,
                    (
                        SELECT COUNT(*)
                        FROM subtasks s
                        WHERE s.task_id = t.id AND s.status = 'done'
                    ) AS subtask_done
                FROM tasks t
                WHERE t.id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Tarefa com id {task_id} nao existe.")
        return _row_to_task(row)

    def get_with_subtasks(self, task_id: int) -> TaskWithSubtasks:
        task = self.get(task_id)
        subtasks = self.list_subtasks(task_id)
        return TaskWithSubtasks(
            id=task.id,
            title=task.title,
            description=task.description,
            priority=task.priority,
            due_date=task.due_date,
            status=task.status,
            created_at=task.created_at,
            updated_at=task.updated_at,
            subtask_total=task.subtask_total,
            subtask_done=task.subtask_done,
            subtasks=subtasks,
        )

    def update(self, task_id: int, task_data: TaskData) -> Task:
        with self._connect() as conn:
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
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
        if cursor.rowcount == 0:
            raise ValueError(f"Tarefa com id {task_id} nao existe.")

    def list(self, filters: TaskFilters | None = None, sort: SortOption = "created_desc") -> list[Task]:
        filters = filters or TaskFilters()
        where_parts: list[str] = []
        params: list[object] = []

        if filters.status is not None:
            where_parts.append("t.status = ?")
            params.append(filters.status.value)

        if filters.priority is not None:
            where_parts.append("t.priority = ?")
            params.append(filters.priority.value)

        if filters.query:
            where_parts.append(
                """
                (
                    LOWER(t.title) LIKE ?
                    OR LOWER(t.description) LIKE ?
                    OR EXISTS (
                        SELECT 1
                        FROM subtasks s
                        WHERE s.task_id = t.id
                        AND (LOWER(s.title) LIKE ? OR LOWER(s.description) LIKE ?)
                    )
                )
                """
            )
            like_value = f"%{filters.query.lower()}%"
            params.extend([like_value, like_value, like_value, like_value])

        where_sql = ""
        if where_parts:
            where_sql = "WHERE " + " AND ".join(where_parts)

        order_by = _resolve_order_by(sort)
        query = f"""
            SELECT
                t.id,
                t.title,
                t.description,
                t.priority,
                t.due_date,
                t.status,
                t.created_at,
                t.updated_at,
                (
                    SELECT COUNT(*)
                    FROM subtasks s
                    WHERE s.task_id = t.id
                ) AS subtask_total,
                (
                    SELECT COUNT(*)
                    FROM subtasks s
                    WHERE s.task_id = t.id AND s.status = 'done'
                ) AS subtask_done
            FROM tasks t
            {where_sql}
            ORDER BY {order_by}
        """

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, tuple(params)).fetchall()

        return [_row_to_task(row) for row in rows]

    def mark_done(self, task_id: int, done: bool) -> Task:
        new_status = Status.DONE if done else Status.TODO
        with self._connect() as conn:
            now = _now_iso()
            cursor = conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (new_status.value, now, task_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Tarefa com id {task_id} nao existe.")
            if done:
                conn.execute(
                    "UPDATE subtasks SET status = ?, updated_at = ? WHERE task_id = ?",
                    (Status.DONE.value, now, task_id),
                )
            conn.commit()
        return self.get(task_id)

    def list_subtasks(self, task_id: int) -> list[Subtask]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT
                    id,
                    task_id,
                    parent_subtask_id,
                    title,
                    description,
                    status,
                    position,
                    created_at,
                    updated_at
                FROM subtasks
                WHERE task_id = ?
                ORDER BY position ASC, id ASC
                """,
                (task_id,),
            ).fetchall()
        return [_row_to_subtask(row) for row in rows]

    def replace_subtasks(self, task_id: int, subtasks: list[SubtaskData]) -> list[Subtask]:
        with self._connect() as conn:
            _ensure_task_exists(conn, task_id)
            conn.execute("DELETE FROM subtasks WHERE task_id = ?", (task_id,))
            now = _now_iso()
            for idx, subtask in enumerate(subtasks):
                conn.execute(
                    """
                    INSERT INTO subtasks
                    (
                        task_id,
                        parent_subtask_id,
                        title,
                        description,
                        status,
                        position,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        subtask.parent_subtask_id,
                        subtask.title,
                        subtask.description,
                        subtask.status.value,
                        idx,
                        now,
                        now,
                    ),
                )
            _touch_task(conn, task_id)
            conn.commit()
        return self.list_subtasks(task_id)

    def create_subtask(
        self,
        task_id: int,
        title: str,
        description: str = "",
        parent_subtask_id: int | None = None,
    ) -> Subtask:
        with self._connect() as conn:
            _ensure_task_exists(conn, task_id)
            if parent_subtask_id is not None:
                _ensure_parent_belongs_to_task(conn, task_id, parent_subtask_id)

            position = _next_subtask_position(conn, task_id, parent_subtask_id)
            now = _now_iso()
            cursor = conn.execute(
                """
                INSERT INTO subtasks
                (
                    task_id,
                    parent_subtask_id,
                    title,
                    description,
                    status,
                    position,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    parent_subtask_id,
                    title,
                    description,
                    Status.TODO.value,
                    position,
                    now,
                    now,
                ),
            )
            subtask_id = int(cursor.lastrowid)
            _touch_task(conn, task_id)
            conn.commit()
        return self.get_subtask(subtask_id)

    def update_subtask_title(self, subtask_id: int, title: str) -> Subtask:
        return self.update_subtask(subtask_id=subtask_id, title=title)

    def update_subtask(
        self,
        subtask_id: int,
        title: str | None = None,
        description: str | None = None,
    ) -> Subtask:
        with self._connect() as conn:
            subtask = _get_subtask_row(conn, subtask_id)
            if subtask is None:
                raise ValueError(f"Subtarefa com id {subtask_id} nao existe.")
            new_title = title if title is not None else str(subtask["title"])
            new_description = description if description is not None else str(subtask["description"])
            conn.execute(
                "UPDATE subtasks SET title = ?, description = ?, updated_at = ? WHERE id = ?",
                (new_title, new_description, _now_iso(), subtask_id),
            )
            _touch_task(conn, int(subtask["task_id"]))
            conn.commit()
        return self.get_subtask(subtask_id)

    def delete_subtask(self, subtask_id: int) -> None:
        with self._connect() as conn:
            subtask = _get_subtask_row(conn, subtask_id)
            if subtask is None:
                raise ValueError(f"Subtarefa com id {subtask_id} nao existe.")
            task_id = int(subtask["task_id"])
            conn.execute(
                """
                WITH RECURSIVE subtree(id) AS (
                    SELECT id FROM subtasks WHERE id = ?
                    UNION ALL
                    SELECT s.id
                    FROM subtasks s
                    JOIN subtree st ON s.parent_subtask_id = st.id
                )
                DELETE FROM subtasks
                WHERE id IN (SELECT id FROM subtree)
                """,
                (subtask_id,),
            )
            _touch_task(conn, task_id)
            conn.commit()

    def mark_subtask_done(self, subtask_id: int, done: bool) -> Subtask:
        with self._connect() as conn:
            subtask = _get_subtask_row(conn, subtask_id)
            if subtask is None:
                raise ValueError(f"Subtarefa com id {subtask_id} nao existe.")
            now = _now_iso()
            task_id = int(subtask["task_id"])
            if done:
                conn.execute(
                    """
                    WITH RECURSIVE subtree(id) AS (
                        SELECT id FROM subtasks WHERE id = ?
                        UNION ALL
                        SELECT s.id
                        FROM subtasks s
                        JOIN subtree st ON s.parent_subtask_id = st.id
                    )
                    UPDATE subtasks
                    SET status = ?, updated_at = ?
                    WHERE id IN (SELECT id FROM subtree)
                    """,
                    (subtask_id, Status.DONE.value, now),
                )
            else:
                conn.execute(
                    "UPDATE subtasks SET status = ?, updated_at = ? WHERE id = ?",
                    (Status.TODO.value, now, subtask_id),
                )
                conn.execute(
                    """
                    WITH RECURSIVE ancestors(id) AS (
                        SELECT parent_subtask_id
                        FROM subtasks
                        WHERE id = ?
                        UNION ALL
                        SELECT s.parent_subtask_id
                        FROM subtasks s
                        JOIN ancestors a ON s.id = a.id
                        WHERE a.id IS NOT NULL
                    )
                    UPDATE subtasks
                    SET status = ?, updated_at = ?
                    WHERE id IN (
                        SELECT id FROM ancestors WHERE id IS NOT NULL
                    )
                    """,
                    (subtask_id, Status.TODO.value, now),
                )
                conn.execute(
                    "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                    (Status.TODO.value, now, task_id),
                )
            _touch_task(conn, task_id)
            conn.commit()
        return self.get_subtask(subtask_id)

    def get_subtask(self, subtask_id: int) -> Subtask:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT
                    id,
                    task_id,
                    parent_subtask_id,
                    title,
                    description,
                    status,
                    position,
                    created_at,
                    updated_at
                FROM subtasks
                WHERE id = ?
                """,
                (subtask_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Subtarefa com id {subtask_id} nao existe.")
        return _row_to_subtask(row)

    def reorder_subtasks(
        self,
        task_id: int,
        parent_subtask_id: int | None,
        ordered_subtask_ids: list[int],
    ) -> list[Subtask]:
        if not ordered_subtask_ids:
            raise ValueError("A nova ordem de subtarefas nao pode ser vazia.")

        with self._connect() as conn:
            _ensure_task_exists(conn, task_id)
            if parent_subtask_id is not None:
                _ensure_parent_belongs_to_task(conn, task_id, parent_subtask_id)

            sibling_ids = _list_subtask_ids_by_parent(conn, task_id, parent_subtask_id)
            if len(sibling_ids) != len(ordered_subtask_ids) or set(sibling_ids) != set(
                ordered_subtask_ids
            ):
                raise ValueError("A nova ordem de subtarefas e invalida.")
            if sibling_ids == ordered_subtask_ids:
                return self.list_subtasks(task_id)

            now = _now_iso()
            for idx, subtask_id in enumerate(ordered_subtask_ids):
                conn.execute(
                    "UPDATE subtasks SET position = ?, updated_at = ? WHERE id = ?",
                    (idx, now, subtask_id),
                )

            _touch_task(conn, task_id)
            conn.commit()

        return self.list_subtasks(task_id)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _resolve_order_by(sort: SortOption) -> str:
    if sort == "due_date_asc":
        return "CASE WHEN t.due_date IS NULL THEN 1 ELSE 0 END, t.due_date ASC, t.created_at DESC"
    if sort == "priority_desc":
        return (
            "CASE t.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 "
            "WHEN 'low' THEN 2 ELSE 3 END, t.created_at DESC"
        )
    return "t.created_at DESC"


def _row_to_task(row: sqlite3.Row) -> Task:
    due_date_text = row["due_date"]
    row_keys = row.keys()
    subtask_total = int(row["subtask_total"]) if "subtask_total" in row_keys else 0
    subtask_done = int(row["subtask_done"]) if "subtask_done" in row_keys else 0
    return Task(
        id=int(row["id"]),
        title=row["title"],
        description=row["description"],
        priority=Priority(row["priority"]),
        due_date=date.fromisoformat(due_date_text) if due_date_text else None,
        status=Status(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        subtask_total=subtask_total,
        subtask_done=subtask_done,
    )


def _row_to_subtask(row: sqlite3.Row) -> Subtask:
    parent_raw = row["parent_subtask_id"]
    return Subtask(
        id=int(row["id"]),
        task_id=int(row["task_id"]),
        parent_subtask_id=int(parent_raw) if parent_raw is not None else None,
        title=row["title"],
        description=row["description"],
        status=Status(row["status"]),
        position=int(row["position"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _get_subtask_row(conn: sqlite3.Connection, subtask_id: int) -> sqlite3.Row | None:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        SELECT
            id,
            task_id,
            parent_subtask_id,
            title,
            description,
            status,
            position,
            created_at,
            updated_at
        FROM subtasks
        WHERE id = ?
        """,
        (subtask_id,),
    ).fetchone()


def _ensure_task_exists(conn: sqlite3.Connection, task_id: int) -> None:
    row = conn.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise ValueError(f"Tarefa com id {task_id} nao existe.")


def _ensure_parent_belongs_to_task(
    conn: sqlite3.Connection, task_id: int, parent_subtask_id: int
) -> None:
    row = conn.execute(
        "SELECT task_id FROM subtasks WHERE id = ?",
        (parent_subtask_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Subtarefa pai com id {parent_subtask_id} nao existe.")
    if int(row[0]) != task_id:
        raise ValueError("A subtarefa pai nao pertence a esta tarefa.")


def _next_subtask_position(
    conn: sqlite3.Connection, task_id: int, parent_subtask_id: int | None
) -> int:
    if parent_subtask_id is None:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(position), -1) + 1
            FROM subtasks
            WHERE task_id = ? AND parent_subtask_id IS NULL
            """,
            (task_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(position), -1) + 1
            FROM subtasks
            WHERE task_id = ? AND parent_subtask_id = ?
            """,
            (task_id, parent_subtask_id),
        ).fetchone()
    return int(row[0]) if row is not None else 0


def _touch_task(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (_now_iso(), task_id))


def _list_subtask_ids_by_parent(
    conn: sqlite3.Connection, task_id: int, parent_subtask_id: int | None
) -> list[int]:
    conn.row_factory = sqlite3.Row
    if parent_subtask_id is None:
        rows = conn.execute(
            """
            SELECT id
            FROM subtasks
            WHERE task_id = ? AND parent_subtask_id IS NULL
            ORDER BY position ASC, id ASC
            """,
            (task_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id
            FROM subtasks
            WHERE task_id = ? AND parent_subtask_id = ?
            ORDER BY position ASC, id ASC
            """,
            (task_id, parent_subtask_id),
        ).fetchall()
    return [int(row["id"]) for row in rows]


def _ensure_subtasks_compat_columns(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(subtasks)").fetchall()
    column_names = {row[1] for row in rows}
    if "parent_subtask_id" not in column_names:
        conn.execute("ALTER TABLE subtasks ADD COLUMN parent_subtask_id INTEGER NULL")
    if "description" not in column_names:
        conn.execute("ALTER TABLE subtasks ADD COLUMN description TEXT NOT NULL DEFAULT ''")


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
