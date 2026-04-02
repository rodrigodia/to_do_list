# To-Do List Desktop (Python + PySide6)

Aplicacao desktop local para gerir tarefas com interface grafica, persistencia em SQLite e foco em simplicidade.

## Requisitos

- Python 3.12+

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

## Comandos

- Run: `python -m todo_app`
- Test: `pytest`
- Lint: `ruff check .`
- Format: `black .`
- Build EXE (Windows): `pyinstaller --name TodoList --windowed --onefile src/todo_app/__main__.py`

## Funcionalidades v1

- Criar, editar e apagar tarefas
- Marcar/desmarcar tarefa como concluida
- Criar e gerir subtarefas com multiplos niveis (subtarefas de subtarefas)
- Mostrar subtarefas na lista principal com indentacao hierarquica
- Filtrar por estado e prioridade
- Pesquisar por texto no titulo/descricao
- Ordenar por mais recentes, data limite e prioridade

## Estrutura

- `src/todo_app/ui`: Interface grafica
- `src/todo_app/service.py`: Regras de negocio e validacao
- `src/todo_app/repository.py`: Acesso SQLite e queries
- `src/todo_app/models.py`: Tipos e entidades
- `tests`: Testes unitarios e de integracao
