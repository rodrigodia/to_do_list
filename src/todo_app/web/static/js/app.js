(function () {
  let lastSelectedRowIndex = null;

  function allBulkCheckboxes() {
    return Array.from(document.querySelectorAll(".bulk-checkbox"));
  }

  function selectedBulkCheckboxes() {
    return allBulkCheckboxes().filter((checkbox) => checkbox.checked);
  }

  function isTypingTarget(target) {
    if (!target) return false;
    const tag = (target.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || target.isContentEditable;
  }

  function isRowSelectionIgnoredTarget(target) {
    if (!target) return true;
    return Boolean(
      target.closest(
        "a, button, input:not(.row-selector-input), select, textarea, label, summary"
      )
    );
  }

  function bulkDeleteForm() {
    return document.getElementById("bulk-delete-form");
  }

  function selectionCountElement() {
    return document.getElementById("selection-count");
  }

  function filtersForm() {
    return document.getElementById("filters-form");
  }

  function updateSelectionUi() {
    const selected = selectedBulkCheckboxes();
    const count = selected.length;
    const label = selectionCountElement();
    if (label) {
      label.textContent = `${count} selecionado(s)`;
    }

    document.querySelectorAll("tr.selectable-row").forEach((row) => {
      const checkbox = row.querySelector(".bulk-checkbox");
      if (!checkbox) return;
      row.classList.toggle("row-selected", checkbox.checked);
    });
  }

  function setAllSelection(value) {
    allBulkCheckboxes().forEach((checkbox) => {
      checkbox.checked = value;
    });
    updateSelectionUi();
  }

  function clearSelection() {
    setAllSelection(false);
  }

  function selectableRows() {
    return Array.from(document.querySelectorAll("tr.selectable-row"));
  }

  function checkboxFromRow(row) {
    if (!row) return null;
    return row.querySelector(".bulk-checkbox");
  }

  function rowIndex(rows, row) {
    return rows.indexOf(row);
  }

  function firstSelectedRowIndex(rows) {
    for (let idx = 0; idx < rows.length; idx += 1) {
      const checkbox = checkboxFromRow(rows[idx]);
      if (checkbox && checkbox.checked) {
        return idx;
      }
    }
    return -1;
  }

  function resolveAnchorIndex(rows) {
    if (
      lastSelectedRowIndex !== null &&
      lastSelectedRowIndex >= 0 &&
      lastSelectedRowIndex < rows.length
    ) {
      return lastSelectedRowIndex;
    }
    return firstSelectedRowIndex(rows);
  }

  function selectRange(rows, startIndex, endIndex, append) {
    if (!append) {
      allBulkCheckboxes().forEach((checkbox) => {
        checkbox.checked = false;
      });
    }

    const from = Math.min(startIndex, endIndex);
    const to = Math.max(startIndex, endIndex);
    for (let idx = from; idx <= to; idx += 1) {
      const checkbox = checkboxFromRow(rows[idx]);
      if (!checkbox) continue;
      checkbox.checked = true;
    }
    updateSelectionUi();
  }

  function selectOnlyRow(row) {
    clearSelection();
    const checkbox = checkboxFromRow(row);
    if (!checkbox) return;
    checkbox.checked = true;
    updateSelectionUi();
  }

  function toggleRowSelection(row) {
    const checkbox = checkboxFromRow(row);
    if (!checkbox) return;
    checkbox.checked = !checkbox.checked;
    updateSelectionUi();
  }

  function currentRelativeUrl() {
    return window.location.pathname + window.location.search;
  }

  function goToNewSubtaskFromSelection() {
    const selected = selectedBulkCheckboxes();
    if (selected.length === 0) {
      window.alert("Seleciona primeiro uma tarefa ou subtarefa.");
      return;
    }

    const source = selected[0];
    const entityType = source.dataset.entityType;
    const entityId = source.dataset.entityId;
    const taskId = source.dataset.taskId;
    const nextUrl = encodeURIComponent(currentRelativeUrl());

    if (entityType === "task") {
      window.location.href = `/subtasks/new?task_id=${entityId}&next_url=${nextUrl}`;
      return;
    }

    if (entityType === "subtask") {
      window.location.href =
        `/subtasks/new?task_id=${taskId}&parent_subtask_id=${entityId}&next_url=${nextUrl}`;
    }
  }

  function setupAutoFilters() {
    const form = filtersForm();
    if (!form) return;

    form.addEventListener("change", function () {
      form.submit();
    });
  }

  function tryOpenEditFromRow(row) {
    if (!row) return;
    const editUrl = row.dataset.editUrl;
    if (!editUrl) return;
    window.location.href = editUrl;
  }

  document.addEventListener("click", function (event) {
    if (event.button !== 0) {
      return;
    }
    const target = event.target;
    if (!target) return;

    if (target.id === "select-all-button") {
      setAllSelection(true);
      lastSelectedRowIndex = 0;
      return;
    }
    if (target.id === "clear-selection-button") {
      clearSelection();
      lastSelectedRowIndex = null;
      return;
    }

    const row = target.closest("tr.selectable-row");
    if (!row) {
      return;
    }
    if (isRowSelectionIgnoredTarget(target)) {
      return;
    }

    const rows = selectableRows();
    const clickedRowIndex = rowIndex(rows, row);
    if (clickedRowIndex < 0) {
      return;
    }

    if (event.shiftKey) {
      const anchorIndex = resolveAnchorIndex(rows);
      if (anchorIndex < 0) {
        selectOnlyRow(row);
      } else {
        selectRange(rows, anchorIndex, clickedRowIndex, event.ctrlKey || event.metaKey);
      }
      lastSelectedRowIndex = clickedRowIndex;
      return;
    }

    if (event.ctrlKey || event.metaKey) {
      toggleRowSelection(row);
      lastSelectedRowIndex = clickedRowIndex;
    } else {
      selectOnlyRow(row);
      lastSelectedRowIndex = clickedRowIndex;
    }
  });

  document.addEventListener("dblclick", function (event) {
    if (event.button !== 0) {
      return;
    }

    const target = event.target;
    if (!target) return;
    if (isRowSelectionIgnoredTarget(target)) {
      return;
    }

    const row = target.closest("tr.selectable-row");
    if (!row) {
      return;
    }

    event.preventDefault();
    tryOpenEditFromRow(row);
  });

  document.addEventListener("change", function (event) {
    if (event.target && event.target.classList.contains("bulk-checkbox")) {
      updateSelectionUi();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (isTypingTarget(event.target)) {
      return;
    }

    if (event.key === "Delete") {
      const selected = selectedBulkCheckboxes();
      if (selected.length === 0) {
        return;
      }
      event.preventDefault();
      const ok = window.confirm(`Apagar ${selected.length} item(ns) selecionado(s)?`);
      if (!ok) {
        return;
      }
      const form = bulkDeleteForm();
      if (form) {
        form.submit();
      }
      return;
    }

    if (
      (event.ctrlKey || event.metaKey) &&
      event.altKey &&
      event.key.toLowerCase() === "s"
    ) {
      event.preventDefault();
      goToNewSubtaskFromSelection();
    }
  });

  setupAutoFilters();
  updateSelectionUi();
})();
