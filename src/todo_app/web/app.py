from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from todo_app.models import Priority, SortOption, Status, Subtask, Task
from todo_app.repository import TaskRepository
from todo_app.service import TaskService, ValidationError


@dataclass(slots=True)
class SubtaskViewRow:
    subtask: Subtask
    depth: int


@dataclass(slots=True)
class TaskTreeView:
    task: Task
    rows: list[SubtaskViewRow]


def create_app(db_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="To-Do List Web")
    web_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(web_dir / "templates"))
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

    repository = TaskRepository(db_path or _default_db_path())
    repository.migrate()
    service = TaskService(repository)
    app.state.service = service
    app.state.templates = templates

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        status: str | None = Query(default=Status.TODO.value),
        priority: str | None = Query(default=None),
        query: str = Query(default=""),
        sort: str = Query(default="priority_desc"),
    ) -> HTMLResponse:
        status_value = _parse_status(status)
        priority_value = _parse_priority(priority)
        sort_value = _parse_sort(sort)
        current_url = _current_relative_url(request)

        tasks = service.list_tasks(
            status=status_value,
            priority=priority_value,
            query=query,
            sort=sort_value,
        )
        task_trees = [
            TaskTreeView(task=task, rows=_build_subtask_rows(service.list_subtasks(task.id)))
            for task in tasks
        ]
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "task_trees": task_trees,
                "filters": {
                    "status": status_value.value if status_value is not None else "",
                    "priority": priority_value.value if priority_value is not None else "",
                    "query": query,
                    "sort": sort_value,
                },
                "current_url": current_url,
                "encoded_current_url": quote(current_url, safe="/?=&"),
            },
        )

    @app.post("/tasks/create")
    def create_task(
        title: str = Form(...),
        description: str = Form(default=""),
        priority: str = Form(default=Priority.MEDIUM.value),
        due_date: str = Form(default=""),
        next_url: str = Form(default="/"),
    ) -> RedirectResponse:
        try:
            service.create_task(
                title=title,
                description=description,
                priority=priority,
                due_date=_parse_due_date(due_date),
            )
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(_safe_next_url(next_url), status_code=303)

    @app.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
    def edit_task_form(
        request: Request,
        task_id: int,
        next_url: str = Query(default="/"),
    ) -> HTMLResponse:
        task = service.get_task(task_id)
        return templates.TemplateResponse(
            request,
            "task_form.html",
            {
                "task": task,
                "next_url": _safe_next_url(next_url),
                "priority_values": list(Priority),
            },
        )

    @app.post("/tasks/{task_id}/update")
    def update_task(
        task_id: int,
        title: str = Form(...),
        description: str = Form(default=""),
        priority: str = Form(default=Priority.MEDIUM.value),
        due_date: str = Form(default=""),
        next_url: str = Form(default="/"),
    ) -> RedirectResponse:
        try:
            service.update_task(
                task_id=task_id,
                title=title,
                description=description,
                priority=priority,
                due_date=_parse_due_date(due_date),
            )
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(_safe_next_url(next_url), status_code=303)

    @app.post("/tasks/{task_id}/delete")
    def delete_task(
        task_id: int,
        next_url: str = Form(default="/"),
    ) -> RedirectResponse:
        try:
            service.delete_task(task_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse(_safe_next_url(next_url), status_code=303)

    @app.post("/tasks/{task_id}/status")
    def update_task_status(
        task_id: int,
        done: str | None = Form(default=None),
        next_url: str = Form(default="/"),
    ) -> RedirectResponse:
        try:
            service.mark_done(task_id, done == "on")
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse(_safe_next_url(next_url), status_code=303)

    @app.get("/subtasks/new", response_class=HTMLResponse)
    def new_subtask_form(
        request: Request,
        task_id: int = Query(...),
        parent_subtask_id: int | None = Query(default=None),
        next_url: str = Query(default="/"),
    ) -> HTMLResponse:
        try:
            task = service.get_task(task_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        parent_subtask = None
        if parent_subtask_id is not None:
            parent_subtask = service.get_subtask(parent_subtask_id)
            if parent_subtask.task_id != task_id:
                raise HTTPException(status_code=400, detail="Subtarefa pai invalida.")

        return templates.TemplateResponse(
            request,
            "subtask_form.html",
            {
                "mode": "new",
                "task": task,
                "subtask": None,
                "parent_subtask": parent_subtask,
                "task_id": task_id,
                "parent_subtask_id": parent_subtask_id,
                "next_url": _safe_next_url(next_url),
            },
        )

    @app.post("/subtasks/create")
    def create_subtask(
        task_id: int = Form(...),
        parent_subtask_id: int | None = Form(default=None),
        title: str = Form(...),
        description: str = Form(default=""),
        next_url: str = Form(default="/"),
    ) -> RedirectResponse:
        try:
            service.create_subtask(
                task_id=task_id,
                parent_subtask_id=parent_subtask_id,
                title=title,
                description=description,
            )
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(_safe_next_url(next_url), status_code=303)

    @app.get("/subtasks/{subtask_id}/edit", response_class=HTMLResponse)
    def edit_subtask_form(
        request: Request,
        subtask_id: int,
        next_url: str = Query(default="/"),
    ) -> HTMLResponse:
        try:
            subtask = service.get_subtask(subtask_id)
            task = service.get_task(subtask.task_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        parent_subtask = (
            service.get_subtask(subtask.parent_subtask_id)
            if subtask.parent_subtask_id is not None
            else None
        )
        return templates.TemplateResponse(
            request,
            "subtask_form.html",
            {
                "mode": "edit",
                "task": task,
                "subtask": subtask,
                "parent_subtask": parent_subtask,
                "task_id": subtask.task_id,
                "parent_subtask_id": subtask.parent_subtask_id,
                "next_url": _safe_next_url(next_url),
            },
        )

    @app.post("/subtasks/{subtask_id}/update")
    def update_subtask(
        subtask_id: int,
        title: str = Form(...),
        description: str = Form(default=""),
        next_url: str = Form(default="/"),
    ) -> RedirectResponse:
        try:
            service.update_subtask(
                subtask_id=subtask_id,
                title=title,
                description=description,
            )
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(_safe_next_url(next_url), status_code=303)

    @app.post("/subtasks/{subtask_id}/delete")
    def delete_subtask(
        subtask_id: int,
        next_url: str = Form(default="/"),
    ) -> RedirectResponse:
        try:
            service.delete_subtask(subtask_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse(_safe_next_url(next_url), status_code=303)

    @app.post("/subtasks/{subtask_id}/status")
    def update_subtask_status(
        subtask_id: int,
        done: str | None = Form(default=None),
        next_url: str = Form(default="/"),
    ) -> RedirectResponse:
        try:
            service.mark_subtask_done(subtask_id, done == "on")
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse(_safe_next_url(next_url), status_code=303)

    @app.post("/bulk-delete")
    def bulk_delete(
        selected: list[str] = Form(default_factory=list),
        next_url: str = Form(default="/"),
    ) -> RedirectResponse:
        entities = _normalize_delete_selection(selected)
        for entity_type, entity_id, _task_id in entities:
            try:
                if entity_type == "task":
                    service.delete_task(entity_id)
                else:
                    service.delete_subtask(entity_id)
            except ValueError:
                # Cascade deletions can make some selected ids disappear.
                continue
        return RedirectResponse(_safe_next_url(next_url), status_code=303)

    return app


def main() -> int:
    import uvicorn

    uvicorn.run("todo_app.web.app:app", host="127.0.0.1", port=8000, reload=False)
    return 0


def _build_subtask_rows(subtasks: list[Subtask]) -> list[SubtaskViewRow]:
    children_by_parent: dict[int | None, list[Subtask]] = {}
    for subtask in subtasks:
        children_by_parent.setdefault(subtask.parent_subtask_id, []).append(subtask)

    rows: list[SubtaskViewRow] = []

    def walk(parent_id: int | None, depth: int) -> None:
        for subtask in children_by_parent.get(parent_id, []):
            rows.append(SubtaskViewRow(subtask=subtask, depth=depth))
            walk(subtask.id, depth + 1)

    walk(None, 1)
    return rows


def _parse_status(value: str | None) -> Status | None:
    if value in (None, ""):
        return None
    return Status(value)


def _parse_priority(value: str | None) -> Priority | None:
    if value in (None, ""):
        return None
    return Priority(value)


def _parse_sort(value: str | None) -> SortOption:
    allowed: set[str] = {"created_desc", "due_date_asc", "priority_desc"}
    return value if value in allowed else "priority_desc"


def _parse_due_date(value: str) -> date | None:
    clean = value.strip()
    if not clean:
        return None
    return date.fromisoformat(clean)


def _safe_next_url(value: str | None) -> str:
    if not value:
        return "/"
    if value.startswith("/"):
        return value
    return "/"


def _current_relative_url(request: Request) -> str:
    query = str(request.url.query)
    return request.url.path if not query else f"{request.url.path}?{query}"


def _parse_entity_token(token: str) -> tuple[str, int, int | None] | None:
    parts = token.split(":")
    if len(parts) < 2:
        return None
    entity_type = parts[0]
    if entity_type not in {"task", "subtask"}:
        return None
    try:
        entity_id = int(parts[1])
    except ValueError:
        return None
    task_id = None
    if len(parts) == 3 and parts[2]:
        try:
            task_id = int(parts[2])
        except ValueError:
            task_id = None
    return entity_type, entity_id, task_id


def _normalize_delete_selection(
    selected_tokens: list[str],
) -> list[tuple[str, int, int | None]]:
    parsed: list[tuple[str, int, int | None]] = []
    seen: set[tuple[str, int]] = set()

    for token in selected_tokens:
        entity = _parse_entity_token(token)
        if entity is None:
            continue
        key = (entity[0], entity[1])
        if key in seen:
            continue
        seen.add(key)
        parsed.append(entity)

    selected_task_ids = {entity_id for entity_type, entity_id, _ in parsed if entity_type == "task"}
    filtered = [
        entity
        for entity in parsed
        if not (
            entity[0] == "subtask"
            and entity[2] is not None
            and entity[2] in selected_task_ids
        )
    ]
    filtered.sort(key=lambda item: 0 if item[0] == "task" else 1)
    return filtered


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


def new_subtask_url_from_token(token: str, next_url: str) -> str:
    parsed = _parse_entity_token(token)
    if parsed is None:
        return "/"

    entity_type, entity_id, task_id = parsed
    if entity_type == "task":
        return f"/subtasks/new?task_id={entity_id}&next_url={quote(next_url, safe='/?=&')}"
    if task_id is None:
        return "/"
    return (
        f"/subtasks/new?task_id={task_id}&parent_subtask_id={entity_id}"
        f"&next_url={quote(next_url, safe='/?=&')}"
    )


app = create_app()
