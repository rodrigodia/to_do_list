# To-Do List — Funcionalidades e Funcionamento

Documento de referência que descreve tudo o que a aplicação faz e como está construída por dentro.

---

## 1. Visão geral

Aplicação desktop local de gestão de tarefas, escrita em Python 3.12+ com **PySide6 (Qt)**. Os dados ficam guardados num ficheiro **SQLite** local.

Arranque: `python -m todo_app` (ou `todo-app` depois de `pip install -e .`), ou através do executável `dist/TodoList.exe`.

---

## 2. Arquitetura

A aplicação está organizada em camadas, cada uma só fala com a de baixo:

```
┌──────────────────────────┐
│  UI Desktop (PySide6)    │  janela, diálogos, atalhos, drag & drop
│  src/todo_app/ui/        │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│  TaskService             │  validação e normalização
│  service.py              │
└────────────┬─────────────┘
             ▼
┌──────────────────────────┐
│  TaskRepository          │  SQL, cascatas, ordenação
│  repository.py           │
└────────────┬─────────────┘
             ▼
      SQLite (todo.db)
```

| Ficheiro | Responsabilidade |
|----------|------------------|
| `models.py` | Enums (`Priority`, `Status`), dataclasses (`Task`, `Subtask`, `TaskData`, `SubtaskData`, `TaskFilters`, `TaskWithSubtasks`) e etiquetas em português |
| `repository.py` | Criação/migração do esquema, todas as queries SQL, regras de cascata de estado e de apagamento |
| `service.py` | Regras de negócio: limpa espaços, valida títulos, prioridades, estados e datas; lança `ValidationError` |
| `app.py` / `__main__.py` | Arranque (ícone, caminho da BD, janela principal) |
| `ui/main_window.py` | Janela principal: tabela, filtros, atalhos, drag & drop |
| `ui/task_dialog.py` | Diálogo de criar/editar tarefa |
| `ui/subtask_dialog.py` | Diálogo de criar/editar subtarefa |

---

## 3. Modelo de dados

### Tarefa (`tasks`)

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | inteiro | autoincremento |
| `title` | texto | obrigatório |
| `description` | texto | opcional (vazio por omissão) |
| `priority` | `low` / `medium` / `high` | apresentado como Baixa / Média / Alta; omissão = `medium` |
| `due_date` | data ISO ou `NULL` | data limite opcional |
| `status` | `todo` / `done` | Por fazer / Concluída; nasce sempre `todo` |
| `created_at`, `updated_at` | datetime ISO (UTC) | `updated_at` é atualizado sempre que a tarefa ou uma subtarefa muda |

Ao ler uma tarefa são também calculados `subtask_total` e `subtask_done` (contagem de subtarefas em todos os níveis).

### Subtarefa (`subtasks`)

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | inteiro | autoincremento |
| `task_id` | FK → `tasks.id` | `ON DELETE CASCADE` |
| `parent_subtask_id` | FK → `subtasks.id` ou `NULL` | `NULL` = subtarefa de 1.º nível; caso contrário é filha de outra subtarefa |
| `title` | texto | obrigatório |
| `description` | texto | opcional |
| `status` | `todo` / `done` | |
| `position` | inteiro | ordem entre irmãs (mesmo pai) |
| `created_at`, `updated_at` | datetime ISO (UTC) | |

As subtarefas formam uma **árvore com profundidade ilimitada** (subtarefas de subtarefas…).

### Índices e migrações

- Índices em `tasks(status)`, `tasks(priority)`, `subtasks(task_id)`, `subtasks(parent_subtask_id)`, `subtasks(status)`.
- `migrate()` é idempotente (`CREATE TABLE IF NOT EXISTS`) e acrescenta automaticamente as colunas `parent_subtask_id` e `description` a bases de dados antigas que não as tenham.
- Cada ligação ativa `PRAGMA foreign_keys = ON` para as cascatas funcionarem.

### Onde fica a base de dados

| Sistema | Caminho |
|---------|---------|
| Windows | `%APPDATA%\todo_app\todo.db` |
| macOS | `~/Library/Application Support/todo_app/todo.db` |
| Linux | `$XDG_DATA_HOME/todo_app/todo.db` (ou `~/.local/share/todo_app/todo.db`) |

A pasta é criada automaticamente no primeiro arranque.

---

## 4. Funcionalidades

### 4.1 Tarefas

- **Criar** tarefa com título, descrição, prioridade e data limite opcional.
- **Editar** qualquer um desses campos.
- **Apagar** tarefa — apaga também todas as suas subtarefas (cascata na BD).
- **Marcar / desmarcar como concluída.**
- **Progresso** de subtarefas visível na lista (ex.: `2/5 concluidas` ou `Sem subtarefas`).

### 4.2 Subtarefas (hierárquicas)

- **Criar** subtarefa diretamente numa tarefa ou dentro de outra subtarefa (qualquer nível).
- Cada subtarefa tem **título** (obrigatório) e **descrição** (opcional).
- **Editar** título e descrição.
- **Apagar** uma subtarefa apaga também toda a sua sub-árvore (CTE recursiva).
- **Reordenar** subtarefas entre irmãs por drag & drop.
- Novas subtarefas são colocadas no fim da lista das irmãs.
- A aplicação valida que a subtarefa pai pertence à mesma tarefa.

### 4.3 Regras automáticas de estado (cascatas)

| Ação | Efeito |
|------|--------|
| Marcar **tarefa** como concluída | Todas as subtarefas da tarefa passam a concluídas |
| Desmarcar **tarefa** | Só a tarefa volta a "por fazer"; as subtarefas mantêm o estado |
| Marcar **subtarefa** como concluída | Ela e todos os seus descendentes ficam concluídos |
| Desmarcar **subtarefa** | Ela, **todos os seus antepassados** e a **tarefa principal** voltam a "por fazer" |

Nota: concluir todas as subtarefas **não** conclui automaticamente a tarefa principal.

### 4.4 Filtros, pesquisa e ordenação

- **Estado:** Por fazer (omissão), Concluídas, Todos os estados.
- **Prioridade:** Todas, Baixa, Média, Alta.
- **Pesquisa de texto** (sem distinção de maiúsculas) no título e descrição da tarefa **e** no título/descrição de qualquer subtarefa.
- **Ordenação:**
  - Prioridade (Alta → Baixa, depois mais recentes) — **omissão**
  - Data limite mais próxima primeiro; tarefas sem data ficam no fim
  - Mais recentes primeiro

### 4.5 Seleção múltipla e apagamento em lote

- É possível selecionar várias tarefas e/ou subtarefas e apagá-las de uma vez.
- Se uma tarefa e subtarefas dessa mesma tarefa estiverem selecionadas, as subtarefas são descartadas da operação (já vão ser apagadas em cascata).
- Tudo é apagado numa única transação; IDs que já não existem são ignorados.

### 4.6 Desfazer apagamentos

- Antes de apagar, a aplicação guarda uma cópia de tudo o que vai ser removido (tarefas, subtarefas e descendentes, com IDs, estados, posições e datas originais).
- `Desfazer` / `Ctrl+Z` restaura o último apagamento, exatamente como estava. Podem desfazer-se até 20 apagamentos, do mais recente para o mais antigo.
- Depois de restaurar, os itens recuperados ficam selecionados.
- O histórico de desfazer existe só enquanto a aplicação está aberta.

### 4.7 Validações (camada de serviço)

- Título da tarefa obrigatório (após remover espaços) → `"O titulo da tarefa e obrigatorio."`
- Título da subtarefa obrigatório → `"As subtarefas precisam de titulo."`
- Prioridade e estado têm de ser valores válidos.
- Data limite tem de ser um objeto `date` (ou vazia).
- Descrições são guardadas sem espaços nas pontas.
- Reordenação exige uma lista não vazia contendo exatamente os mesmos IDs das irmãs atuais.

---

## 5. Interface

### Layout da janela

1. **Barra de ações:** `Nova tarefa`, `Nova subtarefa`, `Editar`, `Apagar`, `Desfazer`.
2. **Barra de filtros:** estado, prioridade, caixa de pesquisa e ordenação. Os filtros atualizam a lista de imediato; a pesquisa espera 250 ms depois da última tecla, para não consultar a base de dados a cada letra.
3. **Tabela** com as colunas: `Feita`, `Titulo`, `Prioridade`, `Data limite`, `Subtarefas`, `Atualizada`.
   - Cada tarefa e as suas subtarefas formam um **grupo visual**:
     - a linha da tarefa funciona como cabeçalho (título a negrito e fundo mais forte, com a descrição em tooltip);
     - há um separador acima de cada tarefa;
     - uma barra vertical à esquerda, com a cor da prioridade (cinzenta se concluída), percorre o grupo inteiro;
     - os grupos alternam de cor de fundo (em vez de alternar linha a linha).
     As cores derivam da paleta do sistema, por isso funcionam em tema claro e escuro.
   - As subtarefas aparecem logo abaixo da tarefa, com conectores de árvore (`├─`, `└─`, `│`) que mostram a hierarquia.
   - Para subtarefas, a coluna "Subtarefas" mostra o nº de filhas diretas (ex.: `2 sub`).
   - A descrição da subtarefa aparece como tooltip no título.
   - A prioridade tem cor: Alta a vermelho, Média a laranja, Baixa a verde.
   - Tarefas por fazer com a data limite ultrapassada mostram a data a vermelho e negrito, com `(atrasada)`.
   - Itens concluídos aparecem **riscados**.
   - Depois de qualquer ação, a seleção, a linha atual e a posição do scroll mantêm-se. Ao criar uma tarefa ou subtarefa, a nova linha fica selecionada e visível.
4. **Barra de estado:** número de tarefas mostradas (à direita) e mensagens temporárias, como "3 item(ns) apagado(s). Ctrl+Z para desfazer."

A lista é carregada com duas queries (tarefas + todas as subtarefas dessas tarefas), independentemente do número de tarefas.

### Interações

| Ação | Como |
|------|------|
| Concluir / reabrir | Clicar na checkbox da coluna "Feita" |
| Nova tarefa | Botão `Nova tarefa` → diálogo com título, descrição, prioridade, checkbox "Sem data limite" e seletor de data com calendário |
| Nova subtarefa | Selecionar uma tarefa (cria no 1.º nível) ou subtarefa (cria como filha) e carregar em `Nova subtarefa` ou `Ctrl+S` |
| Editar | Botão `Editar` ou **duplo clique** na linha |
| Apagar | Botão `Apagar` ou tecla `Delete` — pede confirmação com mensagem adaptada ao nº de tarefas/subtarefas selecionadas |
| Desfazer apagamento | Botão `Desfazer` ou `Ctrl+Z` |
| Seleção múltipla | `Ctrl+clique` / `Shift+clique` |
| Reordenar subtarefas | Arrastar e largar uma subtarefa; só pode ser movida entre irmãs (mesmo pai), e leva consigo a sua sub-árvore. Tarefas não são arrastáveis. A nova ordem é gravada de imediato. |

### Arranque

- Define um AppUserModelID no Windows para que o ícone apareça corretamente na barra de tarefas.
- Carrega o ícone `assets/images/icon_todo_list.jpg` (também dentro do EXE gerado pelo PyInstaller, via `sys._MEIPASS`).
- Executa `migrate()` e abre a janela principal.

---

## 6. Fluxo de uma ação (exemplo)

Marcar uma subtarefa como concluída:

1. O utilizador clica na checkbox → `MainWindow._on_item_changed` identifica a linha como subtarefa.
2. Chama `TaskService.mark_subtask_done(id, True)`.
3. O serviço delega em `TaskRepository.mark_subtask_done`, que com uma CTE recursiva marca a subtarefa e todos os descendentes como `done` e atualiza o `updated_at` da tarefa.
4. `refresh_tasks()` redesenha a tabela com os filtros atuais, mostrando o novo estado e o progresso atualizado.

---

## 7. Desenvolvimento

### Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

### Comandos

| Tarefa | Comando |
|--------|---------|
| Testes | `pytest` |
| Lint | `ruff check .` |
| Formatação | `black .` |
| EXE Windows | `pyinstaller --name TodoList --windowed --onefile --add-data "assets/images/icon_todo_list.jpg;assets/images" src/todo_app/__main__.py` (gera `dist/TodoList.exe`) |

### Dependências

- Runtime: `PySide6`.
- Dev: `pytest`, `pytest-qt`, `ruff`, `black`, `pyinstaller`.

### Ligações à base de dados

Cada operação abre uma ligação SQLite, faz commit se correr bem ou rollback se falhar, e **fecha sempre a ligação** (`TaskRepository._connect`).

### Testes

| Ficheiro | Cobre |
|----------|-------|
| `tests/test_repository.py` | CRUD, cascata de apagamento, cascatas de estado (descendentes e antepassados), filtros e pesquisa, descrição de subtarefas, reordenação e validação da nova ordem, persistência após reinício, fecho das ligações, rollback em erro, carregamento de subtarefas em lote, apagar em lote + restaurar (ida e volta completa), restauro que falha sem deixar lixo |
| `tests/test_service.py` | Validação de título e data, fluxo editar/concluir/apagar/filtrar, subtarefas aninhadas, cascatas de estado, trim da descrição, reordenação |
| `tests/test_main_window.py` | Interface real com `pytest-qt`: árvore de subtarefas, grupos visuais (fundos, barra de prioridade, cabeçalho a negrito), clique real do rato na checkbox, cores e datas atrasadas, pesquisa com espera (uma só query), pesquisa em subtarefas, manter seleção e scroll, cascata ao marcar pela checkbox, criar tarefa/subtarefa (incluindo `Ctrl+S`), apagar seleção mista + desfazer, cancelar apagamento, vários `Ctrl+Z` seguidos, drag & drop (reordenar, mover sub-árvore, recusar tarefas e mudanças de pai) |

Os testes usam uma base de dados temporária (`tmp_path`), por isso não tocam nos dados reais. Os testes de interface correm sem abrir janelas (`QT_QPA_PLATFORM=offscreen`, definido em `tests/conftest.py`).
