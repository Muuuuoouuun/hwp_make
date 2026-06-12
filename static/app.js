const state = {
  problems: [],
  basket: [], // 내보내기 순서를 유지하는 [{id, label}] 목록
  activeId: null,
  templates: [],
  lastDefaultTitle: "문항 모음",
};

const els = {
  statusText: document.querySelector("#statusText"),
  importKind: document.querySelector("#importKind"),
  fileInput: document.querySelector("#fileInput"),
  fileName: document.querySelector("#fileName"),
  dropzone: document.querySelector("#dropzone"),
  importButton: document.querySelector("#importButton"),
  collectUrl: document.querySelector("#collectUrl"),
  collectButton: document.querySelector("#collectButton"),
  metaSubject: document.querySelector("#metaSubject"),
  metaUnit: document.querySelector("#metaUnit"),
  metaTags: document.querySelector("#metaTags"),
  manualTitle: document.querySelector("#manualTitle"),
  manualStem: document.querySelector("#manualStem"),
  manualButton: document.querySelector("#manualButton"),
  problemList: document.querySelector("#problemList"),
  countBadge: document.querySelector("#countBadge"),
  searchInput: document.querySelector("#searchInput"),
  sourceFilter: document.querySelector("#sourceFilter"),
  selectedText: document.querySelector("#selectedText"),
  selectAllButton: document.querySelector("#selectAllButton"),
  clearSelectionButton: document.querySelector("#clearSelectionButton"),
  basketList: document.querySelector("#basketList"),
  basketBadge: document.querySelector("#basketBadge"),
  previewButton: document.querySelector("#previewButton"),
  previewModal: document.querySelector("#previewModal"),
  previewPages: document.querySelector("#previewPages"),
  previewNote: document.querySelector("#previewNote"),
  previewClose: document.querySelector("#previewClose"),
  exportTitle: document.querySelector("#exportTitle"),
  exportTemplate: document.querySelector("#exportTemplate"),
  exportFormat: document.querySelector("#exportFormat"),
  exportButton: document.querySelector("#exportButton"),
  emptyEditor: document.querySelector("#emptyEditor"),
  editorForm: document.querySelector("#editorForm"),
  deleteButton: document.querySelector("#deleteButton"),
  editNumber: document.querySelector("#editNumber"),
  editTitle: document.querySelector("#editTitle"),
  editSubject: document.querySelector("#editSubject"),
  editUnit: document.querySelector("#editUnit"),
  editTags: document.querySelector("#editTags"),
  editStem: document.querySelector("#editStem"),
  editChoices: document.querySelector("#editChoices"),
  editAnswer: document.querySelector("#editAnswer"),
  editSource: document.querySelector("#editSource"),
  editExplanation: document.querySelector("#editExplanation"),
  imagePreview: document.querySelector("#imagePreview"),
  attachButton: document.querySelector("#attachButton"),
  attachInput: document.querySelector("#attachInput"),
  toast: document.querySelector("#toast"),
};

function toast(message) {
  els.toast.textContent = message;
  els.toast.classList.remove("hidden");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => els.toast.classList.add("hidden"), 3600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // Keep the HTTP status text.
    }
    throw new Error(detail);
  }
  return response.json();
}

async function loadProblems() {
  const params = new URLSearchParams();
  if (els.searchInput.value.trim()) params.set("q", els.searchInput.value.trim());
  if (els.sourceFilter.value) params.set("source_type", els.sourceFilter.value);
  const data = await api(`/api/problems?${params.toString()}`);
  state.problems = data.items;
  els.countBadge.textContent = String(state.problems.length);
  els.statusText.textContent = `로컬 DB ${state.problems.length}개`;
  renderList();
  renderBasket();
  renderEditor();
}

async function loadExportTemplates() {
  const data = await api("/api/export-templates");
  state.templates = data.items || [];
  els.exportTemplate.innerHTML = "";
  for (const template of state.templates) {
    const option = document.createElement("option");
    option.value = template.key;
    option.textContent = template.label;
    option.title = template.description || template.label;
    els.exportTemplate.append(option);
  }
  const active = state.templates.find((template) => template.key === els.exportTemplate.value) || state.templates[0];
  state.lastDefaultTitle = active?.default_title || "문항 모음";
}

function syncExportTitleToTemplate() {
  const template = state.templates.find((item) => item.key === els.exportTemplate.value);
  if (!template) return;
  const current = els.exportTitle.value.trim();
  if (!current || current === state.lastDefaultTitle) {
    els.exportTitle.value = template.default_title || "문항 모음";
  }
  state.lastDefaultTitle = template.default_title || "문항 모음";
}

function problemLabel(problem) {
  const number = problem.number ? `${problem.number}. ` : "";
  return `${number}${problem.title || "문제"}`;
}

const SOURCE_LABELS = {
  manual: "직접",
  pdf: "PDF",
  image: "이미지",
  hwp: "HWP",
  hwpx: "HWPX",
  docx: "DOCX",
  web: "웹",
  csv: "CSV",
  sqlite: "SQLite",
};

function sourceLabel(source) {
  return SOURCE_LABELS[source] || source || "DB";
}

// --- 내보내기 바구니 ---------------------------------------------------------

function inBasket(id) {
  return state.basket.some((entry) => entry.id === id);
}

function addToBasket(problem) {
  if (!inBasket(problem.id)) {
    state.basket.push({ id: problem.id, label: problemLabel(problem) });
  }
}

function removeFromBasket(id) {
  state.basket = state.basket.filter((entry) => entry.id !== id);
}

function moveBasketItem(index, target) {
  if (target < 0 || target >= state.basket.length) return;
  const [item] = state.basket.splice(index, 1);
  state.basket.splice(target, 0, item);
  renderBasket();
}

function renderBasket() {
  els.basketBadge.textContent = String(state.basket.length);
  els.selectedText.textContent = `${state.basket.length}개 선택`;
  els.basketList.innerHTML = "";
  if (!state.basket.length) {
    const empty = document.createElement("div");
    empty.className = "basket-empty";
    empty.textContent = "비어 있음";
    els.basketList.append(empty);
    return;
  }
  state.basket.forEach((entry, index) => {
    const problem = state.problems.find((item) => item.id === entry.id);
    if (problem) entry.label = problemLabel(problem);

    const row = document.createElement("div");
    row.className = "basket-row";
    row.draggable = true;
    row.dataset.index = index;

    const handle = document.createElement("span");
    handle.className = "basket-handle";
    handle.textContent = "⠿";

    const label = document.createElement("span");
    label.className = "basket-label";
    label.textContent = `${index + 1}. ${entry.label}`;
    label.title = entry.label;
    label.addEventListener("click", () => {
      state.activeId = entry.id;
      renderList();
      renderEditor();
    });

    const up = document.createElement("button");
    up.type = "button";
    up.className = "basket-btn";
    up.textContent = "▲";
    up.addEventListener("click", () => moveBasketItem(index, index - 1));

    const down = document.createElement("button");
    down.type = "button";
    down.className = "basket-btn";
    down.textContent = "▼";
    down.addEventListener("click", () => moveBasketItem(index, index + 1));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "basket-btn danger";
    remove.textContent = "✕";
    remove.addEventListener("click", () => {
      removeFromBasket(entry.id);
      renderList();
      renderBasket();
    });

    row.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("text/plain", String(index));
      event.dataTransfer.effectAllowed = "move";
      row.classList.add("dragging");
    });
    row.addEventListener("dragend", () => row.classList.remove("dragging"));
    row.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      row.classList.add("drag-over");
    });
    row.addEventListener("dragleave", () => row.classList.remove("drag-over"));
    row.addEventListener("drop", (event) => {
      event.preventDefault();
      row.classList.remove("drag-over");
      const from = Number(event.dataTransfer.getData("text/plain"));
      if (!Number.isNaN(from) && from !== index) moveBasketItem(from, index);
    });

    row.append(handle, label, up, down, remove);
    els.basketList.append(row);
  });
}

// --- 문제 목록 ---------------------------------------------------------------

function renderList() {
  els.problemList.innerHTML = "";
  if (!state.problems.length) {
    const empty = document.createElement("div");
    empty.className = "empty-editor";
    empty.textContent = "문제가 없습니다.";
    els.problemList.append(empty);
    return;
  }
  for (const problem of state.problems) {
    const row = document.createElement("article");
    row.className = `problem-row ${problem.id === state.activeId ? "active" : ""}`;
    row.dataset.id = problem.id;

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = inBasket(problem.id);
    checkbox.addEventListener("click", (event) => {
      event.stopPropagation();
      if (checkbox.checked) addToBasket(problem);
      else removeFromBasket(problem.id);
      renderBasket();
    });

    const body = document.createElement("div");
    const title = document.createElement("div");
    title.className = "problem-title";
    title.innerHTML = `<span></span><b class="source-pill">${sourceLabel(problem.source_type)}</b>`;
    title.querySelector("span").textContent = problemLabel(problem);

    const meta = document.createElement("div");
    meta.className = "problem-meta";
    meta.textContent = [problem.subject, problem.unit, problem.tags].filter(Boolean).join(" · ") || problem.source_name || "로컬";

    const preview = document.createElement("div");
    preview.className = "problem-preview";
    preview.textContent = problem.stem || (problem.image_paths?.length ? "이미지 첨부" : "본문 없음");

    body.append(title, meta, preview);
    row.append(checkbox, body);
    row.addEventListener("click", () => {
      state.activeId = problem.id;
      renderList();
      renderEditor();
    });
    els.problemList.append(row);
  }
}

function activeProblem() {
  return state.problems.find((item) => item.id === state.activeId) || null;
}

function renderEditor() {
  const problem = activeProblem();
  if (!problem) {
    els.emptyEditor.classList.remove("hidden");
    els.editorForm.classList.add("hidden");
    return;
  }
  els.emptyEditor.classList.add("hidden");
  els.editorForm.classList.remove("hidden");
  els.editNumber.value = problem.number || "";
  els.editTitle.value = problem.title || "";
  els.editSubject.value = problem.subject || "";
  els.editUnit.value = problem.unit || "";
  els.editTags.value = problem.tags || "";
  els.editStem.value = problem.stem || "";
  els.editChoices.value = (problem.choices || []).join("\n");
  els.editAnswer.value = problem.answer || "";
  els.editSource.value = problem.source_name || "";
  els.editExplanation.value = problem.explanation || "";
  els.imagePreview.innerHTML = "";
  (problem.image_urls || []).forEach((url, index) => {
    const figure = document.createElement("div");
    figure.className = "image-figure";

    const image = document.createElement("img");
    image.src = url;
    image.alt = problem.title || "첨부 이미지";

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "image-remove";
    remove.textContent = "✕";
    remove.title = "이미지 삭제";
    remove.addEventListener("click", () => removeImage(problem, index));

    figure.append(image, remove);
    els.imagePreview.append(figure);
  });
}

function editorPayload(problem, imagePaths) {
  return {
    source_type: problem.source_type || "manual",
    source_name: els.editSource.value.trim(),
    source_page: problem.source_page,
    number: els.editNumber.value.trim(),
    subject: els.editSubject.value.trim(),
    unit: els.editUnit.value.trim(),
    tags: els.editTags.value.trim(),
    title: els.editTitle.value.trim(),
    stem: els.editStem.value,
    choices: els.editChoices.value.split("\n").map((item) => item.trim()).filter(Boolean),
    answer: els.editAnswer.value.trim(),
    explanation: els.editExplanation.value,
    image_paths: imagePaths,
  };
}

async function removeImage(problem, index) {
  const imagePaths = (problem.image_paths || []).filter((_, i) => i !== index);
  try {
    await api(`/api/problems/${problem.id}`, {
      method: "PUT",
      body: JSON.stringify(editorPayload(problem, imagePaths)),
    });
    await loadProblems();
    toast("이미지를 삭제했습니다.");
  } catch (error) {
    toast(`이미지 삭제 실패: ${error.message}`);
  }
}

async function attachImages() {
  const problem = activeProblem();
  const files = Array.from(els.attachInput.files || []);
  if (!problem || !files.length) return;
  try {
    // 첨부 전에 현재 편집 내용을 먼저 저장해 둔다.
    await api(`/api/problems/${problem.id}`, {
      method: "PUT",
      body: JSON.stringify(editorPayload(problem, problem.image_paths || [])),
    });
    for (const file of files) {
      await api(`/api/problems/${problem.id}/images`, {
        method: "POST",
        body: JSON.stringify({ filename: file.name, data_base64: await fileToBase64(file) }),
      });
    }
    els.attachInput.value = "";
    await loadProblems();
    toast(`이미지 ${files.length}개를 첨부했습니다.`);
  } catch (error) {
    toast(`이미지 첨부 실패: ${error.message}`);
  }
}

function metadata() {
  return {
    subject: els.metaSubject.value.trim(),
    unit: els.metaUnit.value.trim(),
    tags: els.metaTags.value.trim(),
  };
}

// --- 가져오기 ----------------------------------------------------------------

const EXT_KINDS = {
  pdf: "pdf",
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  webp: "image",
  bmp: "image",
  tif: "image",
  tiff: "image",
  hwp: "hwp",
  hwpx: "hwpx",
  docx: "docx",
  csv: "csv",
  tsv: "csv",
  db: "sqlite",
  sqlite: "sqlite",
  sqlite3: "sqlite",
};

function kindForFile(file) {
  const chosen = els.importKind.value;
  if (chosen !== "auto") return chosen;
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  return EXT_KINDS[ext] || null;
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",", 2)[1] : result);
    };
    reader.readAsDataURL(file);
  });
}

async function importFiles() {
  const files = Array.from(els.fileInput.files || []);
  if (!files.length) {
    toast("파일을 선택하세요.");
    return;
  }
  els.importButton.disabled = true;
  try {
    let total = 0;
    const notices = [];
    for (const file of files) {
      const kind = kindForFile(file);
      if (!kind) {
        notices.push(`${file.name}: 지원하지 않는 형식이라 건너뜀`);
        continue;
      }
      const dataBase64 = await fileToBase64(file);
      const result = await api("/api/import", {
        method: "POST",
        body: JSON.stringify({
          kind,
          filename: file.name,
          data_base64: dataBase64,
          metadata: metadata(),
        }),
      });
      total += result.created?.length || 0;
      notices.push(...(result.notices || []));
    }
    await loadProblems();
    toast(`${total}개 문항을 가져왔습니다.${notices.length ? ` ${notices[0]}` : ""}`);
    els.fileInput.value = "";
    els.fileName.textContent = "PDF, 이미지, HWP, HWPX, DOCX, CSV, DB";
  } catch (error) {
    toast(`가져오기 실패: ${error.message}`);
  } finally {
    els.importButton.disabled = false;
  }
}

async function collectFromUrl() {
  const url = els.collectUrl.value.trim();
  if (!url) {
    toast("수집할 URL을 입력하세요.");
    return;
  }
  els.collectButton.disabled = true;
  els.collectButton.textContent = "수집 중...";
  try {
    const result = await api("/api/collect", {
      method: "POST",
      body: JSON.stringify({ url, metadata: metadata() }),
    });
    await loadProblems();
    toast(result.notices?.[0] || `${result.created?.length || 0}개 문항을 수집했습니다.`);
    els.collectUrl.value = "";
  } catch (error) {
    toast(`수집 실패: ${error.message}`);
  } finally {
    els.collectButton.disabled = false;
    els.collectButton.textContent = "URL 수집";
  }
}

async function addManualProblem() {
  const title = els.manualTitle.value.trim();
  const stem = els.manualStem.value.trim();
  if (!title && !stem) {
    toast("제목이나 본문을 입력하세요.");
    return;
  }
  const result = await api("/api/problems", {
    method: "POST",
    body: JSON.stringify({
      ...metadata(),
      source_type: "manual",
      title,
      stem,
      choices: [],
    }),
  });
  state.activeId = result.item.id;
  els.manualTitle.value = "";
  els.manualStem.value = "";
  await loadProblems();
  toast("문제를 추가했습니다.");
}

async function saveActive(event) {
  event.preventDefault();
  const problem = activeProblem();
  if (!problem) return;
  await api(`/api/problems/${problem.id}`, {
    method: "PUT",
    body: JSON.stringify(editorPayload(problem, problem.image_paths || [])),
  });
  await loadProblems();
  toast("저장했습니다.");
}

async function deleteActive() {
  const problem = activeProblem();
  if (!problem) return;
  await fetch(`/api/problems/${problem.id}`, { method: "DELETE" });
  removeFromBasket(problem.id);
  state.activeId = null;
  await loadProblems();
  toast("삭제했습니다.");
}

async function exportSelected() {
  const ids = state.basket.map((entry) => entry.id);
  if (!ids.length && state.activeId) ids.push(state.activeId);
  if (!ids.length) {
    toast("내보낼 문제를 선택하세요.");
    return;
  }
  els.exportButton.disabled = true;
  try {
    const response = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ids,
        title: els.exportTitle.value.trim() || "문항 모음",
        format: els.exportFormat.value,
        template_key: els.exportTemplate.value || "basic",
      }),
    });
    if (!response.ok) throw new Error(await response.text());
    const blob = await response.blob();
    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename\*=UTF-8''([^;]+)|filename="?([^"]+)"?/);
    const fallback = `${els.exportTitle.value || "문항 모음"}.${els.exportFormat.value}`;
    const filename = decodeURIComponent(match?.[1] || match?.[2] || fallback);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    toast(`${ids.length}개 문항을 내보냈습니다.`);
  } catch (error) {
    toast(`내보내기 실패: ${error.message}`);
  } finally {
    els.exportButton.disabled = false;
  }
}

async function previewExport() {
  const ids = state.basket.map((entry) => entry.id);
  if (!ids.length && state.activeId) ids.push(state.activeId);
  if (!ids.length) {
    toast("미리 볼 문제를 선택하세요.");
    return;
  }
  els.previewButton.disabled = true;
  els.previewButton.textContent = "렌더링...";
  try {
    const result = await api("/api/preview", {
      method: "POST",
      body: JSON.stringify({
        ids,
        title: els.exportTitle.value.trim() || "문항 모음",
        format: "hwpx",
        template_key: els.exportTemplate.value || "basic",
      }),
    });
    els.previewPages.innerHTML = "";
    for (const src of result.pages || []) {
      const image = document.createElement("img");
      image.src = src;
      image.alt = "미리보기 페이지";
      els.previewPages.append(image);
    }
    const notes = [];
    if (result.truncated) notes.push(`전체 ${result.page_count}쪽 중 ${result.pages.length}쪽만 표시`);
    if (result.note) notes.push(result.note);
    els.previewNote.textContent = notes.join(" · ");
    els.previewModal.classList.remove("hidden");
  } catch (error) {
    toast(`미리보기 실패: ${error.message}`);
  } finally {
    els.previewButton.disabled = false;
    els.previewButton.textContent = "미리보기";
  }
}

function debounce(fn, delay = 250) {
  let timer;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), delay);
  };
}

function showSelectedFiles() {
  const files = Array.from(els.fileInput.files || []);
  els.fileName.textContent = files.length
    ? files.map((file) => file.name).join(", ")
    : "PDF, 이미지, HWP, HWPX, DOCX, CSV, DB";
}

els.fileInput.addEventListener("change", showSelectedFiles);
els.dropzone.addEventListener("dragover", (event) => {
  event.preventDefault();
  els.dropzone.classList.add("drag-over");
});
els.dropzone.addEventListener("dragleave", () => els.dropzone.classList.remove("drag-over"));
els.dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  els.dropzone.classList.remove("drag-over");
  if (event.dataTransfer?.files?.length) {
    els.fileInput.files = event.dataTransfer.files;
    showSelectedFiles();
  }
});
els.importButton.addEventListener("click", importFiles);
els.collectButton.addEventListener("click", collectFromUrl);
els.collectUrl.addEventListener("keydown", (event) => {
  if (event.key === "Enter") collectFromUrl();
});
els.manualButton.addEventListener("click", addManualProblem);
els.attachButton.addEventListener("click", () => els.attachInput.click());
els.attachInput.addEventListener("change", attachImages);
els.editorForm.addEventListener("submit", saveActive);
els.deleteButton.addEventListener("click", deleteActive);
els.exportButton.addEventListener("click", exportSelected);
els.previewButton.addEventListener("click", previewExport);
els.previewClose.addEventListener("click", () => els.previewModal.classList.add("hidden"));
els.previewModal.addEventListener("click", (event) => {
  if (event.target === els.previewModal) els.previewModal.classList.add("hidden");
});
els.exportTemplate.addEventListener("change", syncExportTitleToTemplate);
els.searchInput.addEventListener("input", debounce(loadProblems));
els.sourceFilter.addEventListener("change", loadProblems);
els.selectAllButton.addEventListener("click", () => {
  for (const problem of state.problems) addToBasket(problem);
  renderList();
  renderBasket();
});
els.clearSelectionButton.addEventListener("click", () => {
  state.basket = [];
  renderList();
  renderBasket();
});

(async function init() {
  await loadExportTemplates();
  syncExportTitleToTemplate();
  await loadProblems();
})().catch((error) => {
  els.statusText.textContent = "서버 연결 실패";
  toast(error.message);
});
