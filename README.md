# To-Do List (Desktop + Web)

Aplicacao local para gerir tarefas com persistencia SQLite.

Inclui duas interfaces:
- Desktop: PySide6
- Web: FastAPI + templates server-side

## Requisitos

- Python 3.12+

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

## Comandos

- Run Desktop: `python -m todo_app`
- Run Web (script): `todo-web`
- Run Web (uvicorn): `uvicorn todo_app.web.app:app --reload`
- Test: `pytest`
- Lint: `ruff check .`
- Format: `black .`
- Build EXE (Windows): `pyinstaller --name TodoList --windowed --onefile --add-data "assets/images/icon_todo_list.jpg;assets/images" src/todo_app/__main__.py`

## Funcionalidades v1

- Criar, editar e apagar tarefas
- Marcar/desmarcar tarefa como concluida
- Criar e gerir subtarefas com multiplos niveis (subtarefas de subtarefas)
- Definir titulo e descricao para cada subtarefa
- Mostrar subtarefas na lista principal com indentacao hierarquica
- Filtrar por estado e prioridade
- Pesquisar por texto no titulo/descricao
- Ordenar por mais recentes, data limite e prioridade
- Apagar em lote por selecao multipla
- Atalhos na versao web: `Delete` (apagar selecao) e `Ctrl+S` (nova subtarefa da selecao)

## Estrutura

- `src/todo_app/ui`: Interface grafica
- `src/todo_app/web`: Interface web, templates e static files
- `src/todo_app/service.py`: Regras de negocio e validacao
- `src/todo_app/repository.py`: Acesso SQLite e queries
- `src/todo_app/models.py`: Tipos e entidades
- `tests`: Testes unitarios e de integracao
