const DEFAULT_EXPORT_TITLE = "새 시험지";
const WORKSPACE_LAYOUT_KEY = "hwp-make:workspace-layout-v2";
const PREVIEW_ZOOM_MIN = 0.5;
const PREVIEW_ZOOM_MAX = 2;
const PREVIEW_ZOOM_STEP = 0.1;
const ACTUAL_PREVIEW_ZOOM_MIN = 0.25;
const ACTUAL_PREVIEW_ZOOM_MAX = 2;
const ACTUAL_PREVIEW_ZOOM_STEP = 0.1;

const state = {
  problems: [],
  problemById: new Map(),
  basket: [], // 내보내기 순서를 유지하는 [{id, label}] 목록
  activeId: null,
  templates: [],
  exports: [], // 내보내기 기록 [{name, size, modified, format, url}]
  lastDefaultTitle: DEFAULT_EXPORT_TITLE,
  sideMode: "source",
  activeMathField: null,
  problemsRequestId: 0,
  collecting: false,
  nativeMathTouched: false,
  draftDirty: false,
  savingDraft: false,
  aiStatus: null,
  aiBusy: false,
  panelLayout: {
    sourceWidth: 280,
    previewWidth: 400,
    sourceCollapsed: false,
    previewCollapsed: false,
  },
  previewZoom: 1,
  previewFit: false,
  paperBaseWidth: 0,
  panMode: false,
  spacePanning: false,
  panPointer: null,
  panelResize: null,
  layoutFrame: null,
  mobilePane: "source",
  aiAction: null,
  lastModalTrigger: null,
  orderDraft: [],
  actualPreviewPages: [],
  actualPreviewPageIndex: 0,
  actualPreviewZoom: 1,
  actualPreviewFit: true,
  actualPreviewNaturalWidth: 0,
  actualPreviewNaturalHeight: 0,
};

const els = {
  statusText: document.querySelector("#statusText"),
  workspace: document.querySelector(".workspace"),
  appShell: document.querySelector(".app-shell"),
  saveStatus: document.querySelector("#saveStatus"),
  shortcutHelpButton: document.querySelector("#shortcutHelpButton"),
  viewPresetButtons: document.querySelectorAll("[data-view-preset]"),
  workflowSteps: document.querySelectorAll("[data-workflow-step]"),
  flowProblemCount: document.querySelector("#flowProblemCount"),
  flowBasketCount: document.querySelector("#flowBasketCount"),
  inputModeButtons: document.querySelectorAll("[data-input-mode]"),
  inputModePanels: document.querySelectorAll("[data-input-panel]"),
  sideSwitchButtons: document.querySelectorAll("[data-side-mode]"),
  sidePanes: document.querySelectorAll("[data-side-pane]"),
  mathInsertButtons: document.querySelectorAll("[data-math-insert]"),
  importKind: document.querySelector("#importKind"),
  fileInput: document.querySelector("#fileInput"),
  fileName: document.querySelector("#fileName"),
  dropzone: document.querySelector("#dropzone"),
  importButton: document.querySelector("#importButton"),
  quickImportButton: document.querySelector("#quickImportButton"),
  layoutExportButton: document.querySelector("#layoutExportButton"),
  layoutMathAi: document.querySelector("#layoutMathAi"),
  collectUrl: document.querySelector("#collectUrl"),
  collectButton: document.querySelector("#collectButton"),
  quickCollectButton: document.querySelector("#quickCollectButton"),
  metaSubject: document.querySelector("#metaSubject"),
  metaUnit: document.querySelector("#metaUnit"),
  metaTags: document.querySelector("#metaTags"),
  manualTitle: document.querySelector("#manualTitle"),
  manualStem: document.querySelector("#manualStem"),
  manualButton: document.querySelector("#manualButton"),
  quickManualButton: document.querySelector("#quickManualButton"),
  problemList: document.querySelector("#problemList"),
  countBadge: document.querySelector("#countBadge"),
  libraryProblemHint: document.querySelector("#libraryProblemHint"),
  libraryBasketHint: document.querySelector("#libraryBasketHint"),
  searchInput: document.querySelector("#searchInput"),
  sourceFilter: document.querySelector("#sourceFilter"),
  selectedText: document.querySelector("#selectedText"),
  selectAllButton: document.querySelector("#selectAllButton"),
  clearSelectionButton: document.querySelector("#clearSelectionButton"),
  basketClearButton: document.querySelector("#basketClearButton"),
  orderEditorButton: document.querySelector("#orderEditorButton"),
  basketList: document.querySelector("#basketList"),
  basketBadge: document.querySelector("#basketBadge"),
  historyList: document.querySelector("#historyList"),
  historyBadge: document.querySelector("#historyBadge"),
  previewButton: document.querySelector("#previewButton"),
  previewModal: document.querySelector("#previewModal"),
  previewPages: document.querySelector("#previewPages"),
  previewNote: document.querySelector("#previewNote"),
  previewClose: document.querySelector("#previewClose"),
  previewThumbs: document.querySelector("#previewThumbs"),
  actualPreviewPrev: document.querySelector("#actualPreviewPrev"),
  actualPreviewNext: document.querySelector("#actualPreviewNext"),
  actualPreviewPageLabel: document.querySelector("#actualPreviewPageLabel"),
  actualPreviewZoomOut: document.querySelector("#actualPreviewZoomOut"),
  actualPreviewZoomIn: document.querySelector("#actualPreviewZoomIn"),
  actualPreviewZoomLabel: document.querySelector("#actualPreviewZoomLabel"),
  actualPreviewFit: document.querySelector("#actualPreviewFit"),
  actualPreviewStage: document.querySelector("#actualPreviewStage"),
  actualPreviewViewport: document.querySelector("#actualPreviewViewport"),
  actualPreviewImage: document.querySelector("#actualPreviewImage"),
  orderEditorModal: document.querySelector("#orderEditorModal"),
  orderEditorList: document.querySelector("#orderEditorList"),
  orderEditorCount: document.querySelector("#orderEditorCount"),
  orderEditorStatus: document.querySelector("#orderEditorStatus"),
  orderEditorClose: document.querySelector("#orderEditorClose"),
  orderEditorCancel: document.querySelector("#orderEditorCancel"),
  orderEditorApply: document.querySelector("#orderEditorApply"),
  exportTitle: document.querySelector("#exportTitle"),
  paperTitlePreview: document.querySelector("#paperTitlePreview"),
  paperCountPreview: document.querySelector("#paperCountPreview"),
  paperSheet: document.querySelector("#paperSheet"),
  paperStage: document.querySelector("#paperStage"),
  paperViewport: document.querySelector("#paperViewport"),
  paperTemplateLabel: document.querySelector("#paperTemplateLabel"),
  paperLayoutHint: document.querySelector("#paperLayoutHint"),
  paperColumnLabel: document.querySelector("#paperColumnLabel"),
  exportTemplate: document.querySelector("#exportTemplate"),
  exportFormat: document.querySelector("#exportFormat"),
  exportAnswerSheet: document.querySelector("#exportAnswerSheet"),
  exportNativeMath: document.querySelector("#exportNativeMath"),
  nativeMathLabel: document.querySelector("#nativeMathLabel"),
  exportButton: document.querySelector("#exportButton"),
  emptyEditor: document.querySelector("#emptyEditor"),
  editorForm: document.querySelector("#editorForm"),
  contentBadges: document.querySelector("#contentBadges"),
  recognitionLayerButton: document.querySelector("#recognitionLayerButton"),
  recognitionLayerModal: document.querySelector("#recognitionLayerModal"),
  recognitionLayerContext: document.querySelector("#recognitionLayerContext"),
  recognitionLayerSummary: document.querySelector("#recognitionLayerSummary"),
  recognitionLayerMap: document.querySelector("#recognitionLayerMap"),
  recognitionPageLabel: document.querySelector("#recognitionPageLabel"),
  recognitionLayerList: document.querySelector("#recognitionLayerList"),
  recognitionLayerClose: document.querySelector("#recognitionLayerClose"),
  recognitionLayerDone: document.querySelector("#recognitionLayerDone"),
  stemPreview: document.querySelector("#stemPreview"),
  deleteButton: document.querySelector("#deleteButton"),
  editorContext: document.querySelector("#editorContext"),
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
  aiStatusButton: document.querySelector("#aiStatusButton"),
  aiStatusDot: document.querySelector("#aiStatusDot"),
  aiStatusText: document.querySelector("#aiStatusText"),
  aiPanelStatus: document.querySelector("#aiPanelStatus"),
  aiSettingsButton: document.querySelector("#aiSettingsButton"),
  aiReviewButton: document.querySelector("#aiReviewButton"),
  aiMathButton: document.querySelector("#aiMathButton"),
  aiOcrButton: document.querySelector("#aiOcrButton"),
  aiReconstructButton: document.querySelector("#aiReconstructButton"),
  aiResult: document.querySelector("#aiResult"),
  aiResultContent: document.querySelector("#aiResultContent"),
  aiResultClose: document.querySelector("#aiResultClose"),
  aiSettingsModal: document.querySelector("#aiSettingsModal"),
  aiSettingsForm: document.querySelector("#aiSettingsForm"),
  aiSettingsClose: document.querySelector("#aiSettingsClose"),
  geminiApiKey: document.querySelector("#geminiApiKey"),
  openAiApiKey: document.querySelector("#openAiApiKey"),
  geminiKeyStatus: document.querySelector("#geminiKeyStatus"),
  openAiKeyStatus: document.querySelector("#openAiKeyStatus"),
  sourceDivider: document.querySelector("#sourceDivider"),
  previewDivider: document.querySelector("#previewDivider"),
  collapseButtons: document.querySelectorAll("[data-collapse-pane]"),
  zoomOutButton: document.querySelector("#zoomOutButton"),
  zoomInButton: document.querySelector("#zoomInButton"),
  zoomLabel: document.querySelector("#zoomLabel"),
  zoomFitButton: document.querySelector("#zoomFitButton"),
  previewPanButton: document.querySelector("#previewPanButton"),
  shortcutHelpModal: document.querySelector("#shortcutHelpModal"),
  shortcutHelpClose: document.querySelector("#shortcutHelpClose"),
  toast: document.querySelector("#toast"),
};

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "2");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");

  const paths = {
    grip: ["M8 6h.01", "M16 6h.01", "M8 12h.01", "M16 12h.01", "M8 18h.01", "M16 18h.01"],
    up: ["m18 15-6-6-6 6"],
    down: ["m6 9 6 6 6-6"],
    close: ["M18 6 6 18", "m6 6 12 12"],
  };

  for (const d of paths[name] || []) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

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

async function loadProblems({ render = true } = {}) {
  const requestId = ++state.problemsRequestId;
  const params = new URLSearchParams();
  if (els.searchInput.value.trim()) params.set("q", els.searchInput.value.trim());
  if (els.sourceFilter.value) params.set("source_type", els.sourceFilter.value);
  const data = await api(`/api/problems?${params.toString()}`);
  if (requestId !== state.problemsRequestId) return false;
  state.problems = data.items;
  if (!params.toString()) state.problemById = new Map();
  for (const problem of data.items) state.problemById.set(problem.id, problem);
  if (!params.toString() && state.activeId && !state.problemById.has(state.activeId)) state.activeId = null;
  els.countBadge.textContent = `${state.problems.length}개`;
  if (els.libraryProblemHint) els.libraryProblemHint.textContent = `검색 결과 ${state.problems.length}개`;
  els.statusText.textContent = `가져온 문제 ${state.problems.length}개`;
  if (els.flowProblemCount) els.flowProblemCount.textContent = `가져온 문제 ${state.problems.length}개`;
  if (render) {
    renderList();
    renderBasket();
    renderEditor();
  }
  return true;
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
  state.lastDefaultTitle = exportDefaultTitle(active);
  syncTemplatePreview();
}

function currentExportTemplate() {
  return state.templates.find((item) => item.key === els.exportTemplate.value) || state.templates[0] || null;
}

function exportDefaultTitle(template) {
  const title = String(template?.default_title || DEFAULT_EXPORT_TITLE).trim();
  return title === "문항 모음" ? DEFAULT_EXPORT_TITLE : title;
}

function syncExportTitleToTemplate() {
  const template = currentExportTemplate();
  if (!template) return;
  const defaultTitle = exportDefaultTitle(template);
  const current = els.exportTitle.value.trim();
  if (!current || current === state.lastDefaultTitle || current === "문항 모음") {
    els.exportTitle.value = defaultTitle;
  }
  state.lastDefaultTitle = defaultTitle;
  syncPaperPreviewMeta();
}

function syncPaperPreviewMeta() {
  if (els.paperTitlePreview) {
    els.paperTitlePreview.textContent = els.exportTitle.value.trim() || DEFAULT_EXPORT_TITLE;
  }
  if (els.paperCountPreview) {
    els.paperCountPreview.textContent = `${state.basket.length}문항`;
  }
}

function syncExportOptions({ resetNativeMath = false } = {}) {
  const isHwpx = els.exportFormat.value === "hwpx";
  const template = currentExportTemplate();
  if (els.exportNativeMath) {
    els.exportNativeMath.disabled = !isHwpx;
    if (resetNativeMath || !state.nativeMathTouched) {
      els.exportNativeMath.checked = Boolean(template?.native_math_default);
    }
  }
  if (els.nativeMathLabel) {
    els.nativeMathLabel.classList.toggle("disabled", !isHwpx);
  }
  if (els.exportButton) {
    els.exportButton.textContent = `${isHwpx ? "HWPX" : "DOCX"} 만들기`;
  }
}

function syncTemplatePreview() {
  const template = currentExportTemplate();
  if (!template || !els.paperSheet) return;
  const columns = Number(template.columns) === 2 ? 2 : 1;
  els.paperSheet.classList.toggle("two-column", columns === 2);
  els.paperSheet.classList.toggle("one-column", columns === 1);
  if (els.paperTemplateLabel) els.paperTemplateLabel.textContent = template.label || "문항 모음";
  if (els.paperColumnLabel) els.paperColumnLabel.textContent = `${columns}단`;
  if (els.paperLayoutHint) {
    els.paperLayoutHint.textContent = `선택한 양식은 ${columns}단으로 출력되며, 실제 열 넘김은 문항 높이에 따라 결정됩니다.`;
  }
  renderBasket();
}

function setWorkflowStep(step) {
  els.workflowSteps.forEach((item) => {
    const active = Number(item.dataset.workflowStep) === Number(step);
    item.classList.toggle("active", active);
    item.setAttribute("aria-pressed", String(active));
  });
}

function setSaveStatus(text, tone = "") {
  if (!els.saveStatus) return;
  els.saveStatus.textContent = text;
  els.saveStatus.className = `save-status ${tone}`.trim();
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, Number(value) || min));
}

function desktopWorkspaceActive() {
  return window.matchMedia("(min-width: 981px)").matches;
}

function mobileWorkspaceActive() {
  return window.matchMedia("(max-width: 700px)").matches;
}

function setMobilePane(pane, { focus = false } = {}) {
  if (!els.workspace || !["source", "editor", "preview"].includes(pane)) return;
  state.mobilePane = pane;
  els.workspace.dataset.mobilePane = pane;
  if (mobileWorkspaceActive()) {
    const step = pane === "source" ? 1 : pane === "editor" ? 2 : 3;
    setWorkflowStep(step);
    if (focus) {
      const target = pane === "source" ? document.querySelector(".source-pane") : pane === "editor" ? document.querySelector(".editor-pane") : document.querySelector(".preview-pane");
      window.requestAnimationFrame(() => target?.scrollIntoView({ block: "start" }));
    }
  }
}

function currentViewPreset() {
  const { sourceCollapsed, previewCollapsed } = state.panelLayout;
  if (!sourceCollapsed && !previewCollapsed) return "all";
  if (!sourceCollapsed && previewCollapsed) return "source";
  if (sourceCollapsed && previewCollapsed) return "edit";
  return "preview";
}

function syncViewPresetButtons() {
  const current = currentViewPreset();
  els.viewPresetButtons.forEach((button) => {
    const active = button.dataset.viewPreset === current;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function setViewPreset(preset, { announce = true } = {}) {
  if (!["all", "source", "edit", "preview"].includes(preset)) return;
  if (!desktopWorkspaceActive()) {
    setMobilePane(preset === "edit" ? "editor" : preset === "preview" ? "preview" : "source", { focus: true });
    return;
  }
  state.panelLayout.sourceCollapsed = preset === "edit" || preset === "preview";
  state.panelLayout.previewCollapsed = preset === "edit" || preset === "source";
  applyWorkspaceLayout({ announce });
}

function activateWorkflowStep(step) {
  const number = Number(step);
  if (number === 1) {
    setSideMode("source");
    setMobilePane("source", { focus: true });
    if (desktopWorkspaceActive()) setViewPreset("source");
  } else if (number === 2) {
    setWorkflowStep(2);
    setMobilePane("editor", { focus: true });
    if (desktopWorkspaceActive()) setViewPreset("edit");
  } else if (number === 3) {
    setWorkflowStep(3);
    setMobilePane("preview", { focus: true });
    if (desktopWorkspaceActive()) setViewPreset("preview");
  }
}

function workspaceLimits(kind) {
  const width = els.workspace?.clientWidth || window.innerWidth;
  const compact = width <= 1240;
  const editorMin = compact ? 380 : 450;
  const dividerWidth = 18;
  if (kind === "source") {
    const preview = state.panelLayout.previewCollapsed ? 0 : state.panelLayout.previewWidth;
    return { min: 240, max: Math.max(240, Math.min(440, width - editorMin - preview - dividerWidth)) };
  }
  const source = state.panelLayout.sourceCollapsed ? 0 : state.panelLayout.sourceWidth;
  return { min: compact ? 300 : 340, max: Math.max(compact ? 300 : 340, Math.min(620, width - editorMin - source - dividerWidth)) };
}

function normalizePanelLayout() {
  if (!desktopWorkspaceActive()) return;
  let sourceLimits = workspaceLimits("source");
  state.panelLayout.sourceWidth = clamp(state.panelLayout.sourceWidth, sourceLimits.min, sourceLimits.max);
  let previewLimits = workspaceLimits("preview");
  state.panelLayout.previewWidth = clamp(state.panelLayout.previewWidth, previewLimits.min, previewLimits.max);
  sourceLimits = workspaceLimits("source");
  state.panelLayout.sourceWidth = clamp(state.panelLayout.sourceWidth, sourceLimits.min, sourceLimits.max);
}

function restoreWorkspaceLayout() {
  try {
    const saved = JSON.parse(localStorage.getItem(WORKSPACE_LAYOUT_KEY) || "null");
    if (saved && typeof saved === "object") {
      if (Number.isFinite(Number(saved.sourceWidth))) state.panelLayout.sourceWidth = Number(saved.sourceWidth);
      if (Number.isFinite(Number(saved.previewWidth))) state.panelLayout.previewWidth = Number(saved.previewWidth);
      state.panelLayout.sourceCollapsed = Boolean(saved.sourceCollapsed);
      state.panelLayout.previewCollapsed = Boolean(saved.previewCollapsed);
    }
  } catch {
    // 손상된 레이아웃 설정은 기본값을 사용한다.
  }
  normalizePanelLayout();
}

function persistWorkspaceLayout() {
  try {
    localStorage.setItem(WORKSPACE_LAYOUT_KEY, JSON.stringify(state.panelLayout));
  } catch {
    // 저장할 수 없는 브라우저 환경에서도 현재 세션 동작은 유지한다.
  }
}

function applyWorkspaceLayout({ announce = false, persist = true } = {}) {
  if (!els.workspace) return;
  normalizePanelLayout();
  els.workspace.style.setProperty("--source-size", `${state.panelLayout.sourceWidth}px`);
  els.workspace.style.setProperty("--preview-size", `${state.panelLayout.previewWidth}px`);
  els.workspace.classList.toggle("source-collapsed", state.panelLayout.sourceCollapsed);
  els.workspace.classList.toggle("preview-collapsed", state.panelLayout.previewCollapsed);
  syncViewPresetButtons();

  for (const button of els.collapseButtons) {
    const pane = button.dataset.collapsePane;
    const collapsed = Boolean(state.panelLayout[`${pane}Collapsed`]);
    button.setAttribute("aria-expanded", String(!collapsed));
    button.setAttribute("aria-label", `${pane === "source" ? "자료" : "미리보기"} 패널 ${collapsed ? "펼치기" : "접기"}`);
    button.title = button.getAttribute("aria-label");
  }
  const sourceLimits = workspaceLimits("source");
  const previewLimits = workspaceLimits("preview");
  Object.entries({ source: els.sourceDivider, preview: els.previewDivider }).forEach(([kind, divider]) => {
    if (!divider) return;
    const limits = kind === "source" ? sourceLimits : previewLimits;
    divider.setAttribute("aria-valuemin", String(limits.min));
    divider.setAttribute("aria-valuemax", String(limits.max));
    divider.setAttribute("aria-valuenow", String(Math.round(state.panelLayout[`${kind}Width`])));
  });
  if (persist) persistWorkspaceLayout();
  if (state.layoutFrame) window.cancelAnimationFrame(state.layoutFrame);
  state.layoutFrame = window.requestAnimationFrame(() => {
    state.layoutFrame = null;
    if (state.previewFit) fitPreviewToStage({ announce: false });
    else updatePaperCanvasSize({ preserveCenter: true });
  });
  if (announce) {
    const source = state.panelLayout.sourceCollapsed ? "자료 접힘" : `자료 ${Math.round(state.panelLayout.sourceWidth)}px`;
    const preview = state.panelLayout.previewCollapsed ? "미리보기 접힘" : `미리보기 ${Math.round(state.panelLayout.previewWidth)}px`;
    toast(`${source} · ${preview}`);
  }
}

function togglePanel(pane, { focusButton = false } = {}) {
  if (!desktopWorkspaceActive()) {
    toast("작은 화면에서는 패널이 세로로 이어집니다.");
    return;
  }
  const key = `${pane}Collapsed`;
  const next = !state.panelLayout[key];
  const panel = pane === "source" ? document.querySelector(".source-pane") : document.querySelector(".preview-pane");
  const button = Array.from(els.collapseButtons).find((item) => item.dataset.collapsePane === pane);
  if (next && panel?.contains(document.activeElement)) button?.focus();
  state.panelLayout[key] = next;
  applyWorkspaceLayout({ announce: true });
  if (focusButton) button?.focus();
}

function resizePanel(kind, nextWidth, { announce = false, persist = true } = {}) {
  if (!desktopWorkspaceActive()) return;
  const limits = workspaceLimits(kind);
  state.panelLayout[`${kind}Width`] = clamp(nextWidth, limits.min, limits.max);
  state.panelLayout[`${kind}Collapsed`] = false;
  applyWorkspaceLayout({ announce, persist });
}

function beginPanelResize(event) {
  if (!desktopWorkspaceActive() || event.button !== 0 || event.target.closest("button")) return;
  const divider = event.currentTarget;
  const kind = divider.dataset.divider;
  state.panelResize = {
    kind,
    divider,
    pointerId: event.pointerId,
    startX: event.clientX,
    startWidth: state.panelLayout[`${kind}Width`],
  };
  divider.setPointerCapture?.(event.pointerId);
  divider.classList.add("resizing");
  els.workspace.classList.add("is-resizing");
  event.preventDefault();
}

function movePanelResize(event) {
  const resize = state.panelResize;
  if (!resize || (event.pointerId != null && event.pointerId !== resize.pointerId)) return;
  const delta = event.clientX - resize.startX;
  resizePanel(resize.kind, resize.startWidth + (resize.kind === "source" ? delta : -delta), { persist: false });
}

function endPanelResize(event) {
  const resize = state.panelResize;
  if (!resize || (event?.pointerId != null && event.pointerId !== resize.pointerId)) return;
  resize.divider.releasePointerCapture?.(resize.pointerId);
  resize.divider.classList.remove("resizing");
  els.workspace.classList.remove("is-resizing");
  state.panelResize = null;
  persistWorkspaceLayout();
}

function handleDividerKeydown(event) {
  const kind = event.currentTarget.dataset.divider;
  const limits = workspaceLimits(kind);
  const current = state.panelLayout[`${kind}Width`];
  let next = null;
  const step = event.shiftKey ? 40 : 10;
  if (event.key === "Home") next = limits.min;
  if (event.key === "End") next = limits.max;
  if (event.key === "ArrowLeft") next = current + (kind === "source" ? -step : step);
  if (event.key === "ArrowRight") next = current + (kind === "source" ? step : -step);
  if (next == null) return;
  event.preventDefault();
  resizePanel(kind, next, { announce: true });
}

function previewZoomPercent() {
  return Math.round(state.previewZoom * 100);
}

function updatePaperCanvasSize({ preserveCenter = false } = {}) {
  if (!els.paperStage || !els.paperViewport || !els.paperSheet || state.panelLayout.previewCollapsed) return;
  if (!state.paperBaseWidth) state.paperBaseWidth = Math.max(400, els.paperStage.clientWidth - 32);
  const stage = els.paperStage;
  const hadCanvasSize = Boolean(els.paperViewport.style.width && els.paperViewport.style.height);
  const oldWidth = Math.max(1, els.paperViewport.offsetWidth);
  const oldHeight = Math.max(1, els.paperViewport.offsetHeight);
  const centerX = (stage.scrollLeft + stage.clientWidth / 2) / oldWidth;
  const centerY = (stage.scrollTop + stage.clientHeight / 2) / oldHeight;

  els.paperSheet.style.setProperty("--paper-base-width", `${state.paperBaseWidth}px`);
  els.paperSheet.style.setProperty("--paper-zoom", String(state.previewZoom));
  const baseHeight = Math.max(520, els.paperSheet.offsetHeight);
  const scaledWidth = Math.round(state.paperBaseWidth * state.previewZoom);
  const scaledHeight = Math.round(baseHeight * state.previewZoom);
  els.paperViewport.style.width = `${scaledWidth}px`;
  els.paperViewport.style.height = `${scaledHeight}px`;
  if (preserveCenter && hadCanvasSize) {
    stage.scrollLeft = Math.max(0, centerX * scaledWidth - stage.clientWidth / 2);
    stage.scrollTop = Math.max(0, centerY * scaledHeight - stage.clientHeight / 2);
  } else if (!hadCanvasSize) {
    stage.scrollLeft = 0;
    stage.scrollTop = 0;
  }
  const percent = previewZoomPercent();
  if (els.zoomLabel) {
    els.zoomLabel.textContent = `${percent}%`;
    els.zoomLabel.setAttribute("aria-label", `시험지 배율 ${percent}%, 눌러 100%로 초기화`);
  }
  stage.setAttribute("aria-label", `시험지 작업 캔버스, 현재 배율 ${percent}%. Space를 누른 채 드래그하여 이동합니다.`);
}

function setPreviewZoom(nextZoom, { announce = true, fit = false } = {}) {
  const rounded = Math.round(clamp(nextZoom, PREVIEW_ZOOM_MIN, PREVIEW_ZOOM_MAX) * 20) / 20;
  state.previewZoom = rounded;
  state.previewFit = fit;
  updatePaperCanvasSize({ preserveCenter: true });
  if (announce) toast(`시험지 배율 ${previewZoomPercent()}%`);
}

function fitPreviewToStage({ announce = true } = {}) {
  if (!els.paperStage || !els.paperSheet || state.panelLayout.previewCollapsed) return;
  if (!state.paperBaseWidth) state.paperBaseWidth = Math.max(400, els.paperStage.clientWidth - 32);
  els.paperSheet.style.setProperty("--paper-base-width", `${state.paperBaseWidth}px`);
  const baseHeight = Math.max(520, els.paperSheet.offsetHeight);
  const widthScale = (els.paperStage.clientWidth - 32) / state.paperBaseWidth;
  const heightScale = (els.paperStage.clientHeight - 32) / baseHeight;
  setPreviewZoom(Math.min(1, widthScale, heightScale), { announce, fit: true });
  els.paperStage.scrollTo?.({ left: 0, top: 0, behavior: "auto" });
}

function resetPreviewZoom({ announce = true } = {}) {
  setPreviewZoom(1, { announce, fit: false });
  if (els.paperStage) {
    els.paperStage.scrollLeft = 0;
    els.paperStage.scrollTop = 0;
  }
}

function setPanMode(active) {
  state.panMode = Boolean(active);
  els.previewPanButton?.classList.toggle("active", state.panMode);
  els.previewPanButton?.setAttribute("aria-pressed", String(state.panMode));
  els.paperStage?.classList.toggle("pan-ready", state.panMode || state.spacePanning);
}

function interactiveCanvasTarget(target) {
  return Boolean(target.closest("button, input, select, textarea, a, [draggable='true']"));
}

function beginCanvasPan(event) {
  const allowedButton = event.button === 0 || event.button === 1;
  const wantsPan = event.button === 1 || state.panMode || state.spacePanning;
  if (!allowedButton || !wantsPan || interactiveCanvasTarget(event.target)) return;
  event.preventDefault();
  const stage = els.paperStage;
  stage.focus({ preventScroll: true });
  stage.setPointerCapture(event.pointerId);
  state.panPointer = {
    id: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    scrollLeft: stage.scrollLeft,
    scrollTop: stage.scrollTop,
  };
  stage.classList.add("panning");
}

function moveCanvasPan(event) {
  const pan = state.panPointer;
  if (!pan || pan.id !== event.pointerId) return;
  els.paperStage.scrollLeft = pan.scrollLeft - (event.clientX - pan.startX);
  els.paperStage.scrollTop = pan.scrollTop - (event.clientY - pan.startY);
}

function endCanvasPan(event) {
  const pan = state.panPointer;
  if (!pan || pan.id !== event.pointerId) return;
  state.panPointer = null;
  els.paperStage.classList.remove("panning");
  if (!state.panMode && !state.spacePanning) els.paperStage.classList.remove("pan-ready");
}

function canvasContextActive() {
  const active = document.activeElement;
  return Boolean(els.paperStage?.matches(":hover") || els.paperStage?.contains(active) || document.querySelector(".preview-pane")?.contains(active));
}

function visibleModals() {
  return Array.from(document.querySelectorAll(".modal:not(.hidden)"));
}

function syncModalState() {
  if (!els.appShell) return;
  const inactive = visibleModals().length > 0;
  els.appShell.inert = inactive;
  els.appShell.toggleAttribute("inert", inactive);
  document.documentElement.classList.toggle("modal-open", inactive);
}

function openModal(modal, trigger, focusTarget) {
  if (!modal) return;
  state.lastModalTrigger = trigger || document.activeElement;
  modal.classList.remove("hidden");
  syncModalState();
  window.requestAnimationFrame(() => (focusTarget || modal.querySelector("button, input, select, textarea, [tabindex='0']"))?.focus());
}

function closeModal(modal) {
  if (!modal || modal.classList.contains("hidden")) return;
  modal.classList.add("hidden");
  syncModalState();
  const trigger = state.lastModalTrigger;
  state.lastModalTrigger = null;
  if (trigger?.isConnected) window.requestAnimationFrame(() => trigger.focus());
}

function closeTopmostModal() {
  const modal = visibleModals().pop();
  if (!modal) return false;
  if (modal === els.aiSettingsModal) closeAISettings();
  else if (modal === els.orderEditorModal) cancelOrderEditor();
  else closeModal(modal);
  return true;
}

function trapModalFocus(event, modal) {
  if (event.key !== "Tab") return;
  const focusable = Array.from(modal.querySelectorAll("button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])"))
    .filter((item) => item.offsetParent !== null);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function openShortcutHelp() {
  openModal(els.shortcutHelpModal, document.activeElement, els.shortcutHelpClose);
}

function closeShortcutHelp() {
  closeModal(els.shortcutHelpModal);
}

function editableTarget(target) {
  return Boolean(target?.closest("input, textarea, select, [contenteditable='true']"));
}

async function commandSave() {
  if (!activeProblem()) {
    toast("저장할 문항을 먼저 선택하세요.");
    return;
  }
  state.draftDirty = true;
  await flushActiveDraft({ quiet: false });
}

function commandOpenFile() {
  if (state.panelLayout.sourceCollapsed) togglePanel("source");
  setSideMode("source");
  setInputMode("file");
  els.fileInput.click();
}

function handleGlobalKeydown(event) {
  if (event.isComposing || event.keyCode === 229 || event.getModifierState?.("AltGraph")) return;
  const modal = visibleModals().pop();
  if (modal) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeTopmostModal();
      return;
    }
    if (modal === els.previewModal && !editableTarget(event.target)) {
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        setActualPreviewPage(state.actualPreviewPageIndex - 1);
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        setActualPreviewPage(state.actualPreviewPageIndex + 1);
        return;
      }
      if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        setActualPreviewZoom(state.actualPreviewZoom + ACTUAL_PREVIEW_ZOOM_STEP);
        return;
      }
      if (event.key === "-" || event.key === "_") {
        event.preventDefault();
        setActualPreviewZoom(state.actualPreviewZoom - ACTUAL_PREVIEW_ZOOM_STEP);
        return;
      }
      if (event.shiftKey && event.code === "Digit0") {
        event.preventDefault();
        setActualPreviewZoom(1, { center: true });
        return;
      }
      if (event.shiftKey && event.code === "Digit1") {
        event.preventDefault();
        fitActualPreview();
        return;
      }
    }
    trapModalFocus(event, modal);
    return;
  }
  if (event.key === "Escape") {
    if (state.panelResize) {
      endPanelResize();
      event.preventDefault();
    } else if (state.panPointer) {
      state.panPointer = null;
      els.paperStage?.classList.remove("panning");
      event.preventDefault();
    } else if (state.panMode) {
      setPanMode(false);
      event.preventDefault();
    }
    return;
  }

  const commandKey = event.ctrlKey || event.metaKey;
  const key = event.key.toLowerCase();
  if (commandKey && !event.altKey) {
    if (key === "s") {
      event.preventDefault();
      if (event.repeat) return;
      commandSave();
      return;
    }
    if (key === "o") {
      event.preventDefault();
      if (event.repeat) return;
      commandOpenFile();
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (event.repeat) return;
      previewExport();
      return;
    }
    if (!event.repeat && key === "b") {
      event.preventDefault();
      togglePanel("source", { focusButton: true });
      return;
    }
    if (!event.repeat && event.key === "\\") {
      event.preventDefault();
      togglePanel("preview", { focusButton: true });
      return;
    }
  }
  if (editableTarget(event.target)) return;

  if (event.key === "?" && !event.repeat) {
    event.preventDefault();
    openShortcutHelp();
    return;
  }
  if (event.key === "/" && !event.repeat) {
    event.preventDefault();
    if (state.panelLayout.sourceCollapsed) togglePanel("source");
    setSideMode("library");
    els.searchInput.focus();
    return;
  }
  if (event.code === "Space" && !event.repeat && canvasContextActive()) {
    state.spacePanning = true;
    els.paperStage?.classList.add("pan-ready");
    event.preventDefault();
    return;
  }
  if (event.shiftKey && event.key === "0" && canvasContextActive()) {
    event.preventDefault();
    resetPreviewZoom();
    return;
  }
  if (event.shiftKey && event.key === "1" && canvasContextActive()) {
    event.preventDefault();
    fitPreviewToStage();
    return;
  }
  if (canvasContextActive() && (event.key === "+" || event.key === "=")) {
    event.preventDefault();
    setPreviewZoom(state.previewZoom + PREVIEW_ZOOM_STEP);
    return;
  }
  if (canvasContextActive() && event.key === "-") {
    event.preventDefault();
    setPreviewZoom(state.previewZoom - PREVIEW_ZOOM_STEP);
  }
}

function handleGlobalKeyup(event) {
  if (event.code !== "Space") return;
  state.spacePanning = false;
  if (!state.panMode && !state.panPointer) els.paperStage?.classList.remove("pan-ready");
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
  text: "텍스트",
  web: "웹",
  csv: "CSV",
  sqlite: "SQLite",
};

function sourceLabel(source) {
  return SOURCE_LABELS[source] || source || "자료";
}

function compactText(value, maxLength = 92) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "본문 미리보기 없음";
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

const MATH_OPERATOR = String.raw`(?:->|=>|\\(?:to|le|leq|ge|geq|ne|neq|cdot|times|div|pm|mp|approx|in|notin|cup|cap|subset|supset|subseteq|supseteq|circ|mid|vert)(?![A-Za-z])|[+\-*\/=<>≤≥≠≈×÷±∈∉∪∩⊂⊃⊆⊇∘^!])`;
const MATH_SYMBOL = String.raw`[√∑∏∫∞≤≥≠≈±×÷∠△∥⊥∈∉∪∩⊂⊃⊆⊇∘′″]`;
const GREEK_RANGE = String.raw`α-ωΑ-Ω`;
const GREEK_LETTER = String.raw`[${GREEK_RANGE}]`;
const IDENTIFIER = String.raw`[a-zA-Z${GREEK_RANGE}][a-zA-Z0-9${GREEK_RANGE}]*`;
const SUPERSCRIPT_CHARS = String.raw`⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ`;
const SUBSCRIPT_CHARS = String.raw`₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ`;
const VULGAR_FRACTION_CHARS = String.raw`¼½¾⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞`;
const PRIME_CHARS = String.raw`'′″`;
const UNICODE_SUP_SUB_PATTERN = String.raw`(?<![a-zA-Z0-9${GREEK_RANGE}])[a-zA-Z${GREEK_RANGE}][a-zA-Z0-9${GREEK_RANGE}]*[${SUPERSCRIPT_CHARS}${SUBSCRIPT_CHARS}]+`;
const VULGAR_FRACTION_PATTERN = String.raw`[${VULGAR_FRACTION_CHARS}]`;
const MATH_OPERAND = String.raw`(?:[+\-]?\d+(?:\.\d+)?(?:\s*\/\s*[+\-]?\d+(?:\.\d+)?)?|[+\-]?\d+(?:\.\d+)?\([^()\n]{1,120}\)|[+\-]?\d*(?:\.\d+)?${IDENTIFIER}[${PRIME_CHARS}]*(?:\([^()\n]{0,120}\))?(?:[_^](?:\{[^{}\n]{1,80}\}|[a-zA-Z0-9]+))*|${IDENTIFIER}[${PRIME_CHARS}]*\([^()\n]{0,120}\)(?:[_^](?:\{[^{}\n]{1,80}\}|[a-zA-Z0-9]+))*|\([^()\n]{1,120}\)|${MATH_SYMBOL})`;
const LATEX_GROUP_CONTENT = String.raw`(?:[^{}\n]|\\[A-Za-z]+(?:\{[^{}\n]{0,120}\})?|\{[^{}\n]{0,120}\}){0,180}`;
const LATEX_WRAPPED_OPERAND = String.raw`\\(?:mathrm|mathbb|mathbf|text|operatorname)\{${LATEX_GROUP_CONTENT}\}`;
const LATEX_WRAPPED_FUNCTION_PATTERN = String.raw`${LATEX_WRAPPED_OPERAND}\([^()\n]{0,120}\)`;
const LATEX_LEFT_RIGHT_PATTERN = String.raw`\\left[\s\S]{1,1200}?\\right(?:\\[A-Za-z]+|\\[{}]|\S)?`;
const LATEX_WRAPPED_LEFT_RIGHT_PATTERN = String.raw`${LATEX_WRAPPED_OPERAND}\s*${LATEX_LEFT_RIGHT_PATTERN}`;
const LATEX_WRAPPED_EXPRESSION_PATTERN = String.raw`(?:${MATH_OPERAND}|${LATEX_WRAPPED_OPERAND})\s*${MATH_OPERATOR}\s*(?:${MATH_OPERAND}|${LATEX_WRAPPED_OPERAND})(?:\s*${MATH_OPERATOR}\s*(?:${MATH_OPERAND}|${LATEX_WRAPPED_OPERAND}))*`;
const LATEX_FRACTION_PATTERN = String.raw`\\(?:frac|dfrac|tfrac)\{${LATEX_GROUP_CONTENT}\}\{${LATEX_GROUP_CONTENT}\}`;
const LATEX_BINOM_PATTERN = String.raw`\\(?:binom|dbinom|tbinom)\{${LATEX_GROUP_CONTENT}\}\{${LATEX_GROUP_CONTENT}\}`;
const LATEX_SQRT_PATTERN = String.raw`\\sqrt(?:\[[^\]\n]{0,80}\])?\{${LATEX_GROUP_CONTENT}\}`;
const LATEX_SPACE_COMMAND_PATTERN = String.raw`(?:\\[,;:! ]|\\(?:quad|qquad|enspace|thinspace|medspace|thickspace)(?![A-Za-z]))`;
const ABSOLUTE_VALUE_PATTERN = String.raw`\|(?=[^|$\n]*[a-zA-Z0-9${GREEK_RANGE}])[^|$\n]{1,160}\|`;
const LATEX_NARY_BODY_PATTERN = String.raw`(?:${LATEX_FRACTION_PATTERN}|${LATEX_SQRT_PATTERN}|\([^()\n]{1,120}\)|\[[^\[\]\n]{1,120}\]|${IDENTIFIER}(?:\([^()\n]{0,120}\))?(?:[_^](?:\{[^{}\n]{1,80}\}|[a-zA-Z0-9]+))*(?:d${IDENTIFIER})?|\d+(?:\.\d+)?)`;
const LATEX_NARY_PATTERN = String.raw`\\(?:sum|prod|int|iint)(?![A-Za-z])(?:\s*[_^](?:\{[^{}\n]{0,120}\}|[a-zA-Z0-9]+)){0,2}(?:\s+${LATEX_NARY_BODY_PATTERN})?(?:\s*(?:${LATEX_SPACE_COMMAND_PATTERN}\s*)?d${IDENTIFIER})?`;
const LATEX_FUNCTION_PATTERN = String.raw`\\(?:lim|log|ln|sin|cos|tan|sec|csc|cot|arcsin|arccos|arctan|sinh|cosh|tanh|min|max|argmin|argmax|arg|exp|det|gcd|lcm|Pr)(?![A-Za-z])(?:\s*[_^](?:\{[^{}\n]{0,120}\}|[a-zA-Z0-9]+)){0,2}(?:\s*${LATEX_NARY_BODY_PATTERN})?(?:\s*\{${LATEX_GROUP_CONTENT}\})?`;
const LATEX_FUNCTION_EXPRESSION_PATTERN = String.raw`\\(?:lim|log|ln|min|max|argmin|argmax|arg|exp|det|gcd|lcm|Pr)(?![A-Za-z])(?:\s*[_^](?:\{[^{}\n]{0,120}\}|[a-zA-Z0-9]+)){0,2}(?:\s*${LATEX_NARY_BODY_PATTERN})?(?:\s*\{${LATEX_GROUP_CONTENT}\})?(?:\s*${MATH_OPERATOR}\s*(?:${LATEX_NARY_BODY_PATTERN}|${MATH_OPERAND}))+`;
const RADICAL_PLACEHOLDER_PATTERN = String.raw`[□▢]*`;
const RADICAL_BODY_PATTERN = String.raw`(?:${IDENTIFIER}|\([^()\n]{1,120}\)|\d+(?:\.\d+)?)`;
const UNICODE_RADICAL_PATTERN = String.raw`√\s*${RADICAL_PLACEHOLDER_PATTERN}\s*${RADICAL_BODY_PATTERN}`;
const HANCOM_RADICAL_PATTERN = String.raw`(?<![a-zA-Z0-9${GREEK_RANGE}])sqrt\s*${RADICAL_PLACEHOLDER_PATTERN}\s*${RADICAL_BODY_PATTERN}`;
const UNICODE_NARY_PATTERN = String.raw`[∑∏∫](?:[_^](?:\{[^{}\n]{0,120}\}|[a-zA-Z0-9]+)){0,2}(?:\s*${LATEX_NARY_BODY_PATTERN})?`;
const LATEX_COMMAND_PATTERN = String.raw`\\(?:frac|dfrac|tfrac|sqrt|sum|prod|int|iint|lim|log|ln|sin|cos|tan|sec|csc|cot|arcsin|arccos|arctan|sinh|cosh|tanh|min|max|argmin|argmax|arg|exp|det|gcd|lcm|Pr|alpha|beta|gamma|delta|epsilon|varepsilon|zeta|eta|theta|vartheta|iota|kappa|lambda|mu|nu|xi|pi|varpi|rho|varrho|sigma|varsigma|tau|upsilon|phi|varphi|chi|psi|omega|Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Upsilon|Phi|Psi|Omega|nabla|le|leq|ge|geq|ne|neq|approx|cdot|times|div|pm|mp|infty|overline|underline|overrightarrow|widehat|hat|tilde|dot|ddot|check|bar|vec|angle|triangle|parallel|perp|because|therefore|binom|dbinom|tbinom|mathrm|mathbb|mathbf|text|operatorname|in|notin|cup|cap|subset|supset|subseteq|supseteq|circ|mid|vert|lvert|rvert|lVert|rVert|lceil|rceil|lfloor|rfloor|langle|rangle|cdots|ldots)(?![A-Za-z])(?:\s*(?:[_^](?:\{[^{}\n]{0,120}\}|[a-zA-Z0-9]+)|\{[^{}\n]{0,120}\}|\[[^\]\n]{0,80}\])){0,4}`;
const SUPER_SUB_PATTERN = String.raw`(?<![a-zA-Z0-9${GREEK_RANGE}])[a-zA-Z${GREEK_RANGE}][a-zA-Z0-9${GREEK_RANGE}]*[${PRIME_CHARS}]*(?:[_^](?:\{[^{}\n]{1,80}\}|[a-zA-Z0-9]+))+`;
const PREFIXED_SUP_SUB_PATTERN = String.raw`(?:\{\})?(?:[_^](?:\{[^{}\n]{1,80}\}|[a-zA-Z0-9]+))+[a-zA-Z${GREEK_RANGE}][a-zA-Z0-9${GREEK_RANGE}]*(?:[_^](?:\{[^{}\n]{1,80}\}|[a-zA-Z0-9]+))+`;
const DATE_LIKE_TOKEN_PATTERN = /^\d{1,4}[-/.]\d{1,2}(?:[-/.]\d{1,2})?$/;
const NUMERIC_RANGE_TOKEN_PATTERN = /^\d+(?:\.\d+)?\s*[-~]\s*\d+(?:\.\d+)?$/;
const ALNUM_ID_TOKEN_PATTERN = /^[A-Za-z]+\d+\s*[-/]\s*\d{2,}$/;
const CURRENCY_SPAN_TOKEN_PATTERN = /^\$\d+(?:\.\d+)?(?:\s+\w+)?\s+\$\d+(?:\.\d+)?$/;
const CURRENCY_FRAGMENT_TOKEN_PATTERN = /^\$\d+(?:\.\d+)?(?:\s+\w+)?\s*\$$/;
const MATH_SYMBOL_TOKEN_PATTERN = /^[√∑∏∫∞≤≥≠≈±×÷∠△∥⊥∈∉∪∩⊂⊃⊆⊇∘′″¼½¾⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞]$/;
const FORMULA_TOKEN_PATTERN = new RegExp(
  [
    String.raw`\$[^$\n]{1,2000}\$`,
    String.raw`\\\([^)]{1,2000}\\\)`,
    String.raw`\\\[[\s\S]{1,2400}?\\\]`,
    String.raw`\\begin\{(?:aligned|matrix|cases|array|pmatrix|bmatrix)\}[\s\S]{1,2400}?\\end\{[a-zA-Z*]+\}`,
    LATEX_WRAPPED_LEFT_RIGHT_PATTERN,
    LATEX_LEFT_RIGHT_PATTERN,
    LATEX_WRAPPED_FUNCTION_PATTERN,
    LATEX_WRAPPED_EXPRESSION_PATTERN,
    LATEX_FRACTION_PATTERN,
    LATEX_BINOM_PATTERN,
    LATEX_SQRT_PATTERN,
    LATEX_NARY_PATTERN,
    LATEX_FUNCTION_EXPRESSION_PATTERN,
    LATEX_FUNCTION_PATTERN,
    UNICODE_RADICAL_PATTERN,
    HANCOM_RADICAL_PATTERN,
    UNICODE_NARY_PATTERN,
    LATEX_COMMAND_PATTERN,
    UNICODE_SUP_SUB_PATTERN,
    VULGAR_FRACTION_PATTERN,
    ABSOLUTE_VALUE_PATTERN,
    MATH_SYMBOL,
    PREFIXED_SUP_SUB_PATTERN,
    String.raw`${MATH_OPERAND}\s*${MATH_OPERATOR}\s*${MATH_OPERAND}(?:\s*${MATH_OPERATOR}\s*${MATH_OPERAND})*`,
    SUPER_SUB_PATTERN,
  ].join("|"),
  "g"
);

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function formulaMatches(text) {
  const value = String(text || "");
  FORMULA_TOKEN_PATTERN.lastIndex = 0;
  return Array.from(value.matchAll(FORMULA_TOKEN_PATTERN)).filter((match) => {
    const token = match[0].trim();
    return (
      (token.length > 1 || MATH_SYMBOL_TOKEN_PATTERN.test(token)) &&
      !DATE_LIKE_TOKEN_PATTERN.test(token) &&
      !NUMERIC_RANGE_TOKEN_PATTERN.test(token) &&
      !ALNUM_ID_TOKEN_PATTERN.test(token) &&
      !CURRENCY_SPAN_TOKEN_PATTERN.test(token) &&
      !CURRENCY_FRAGMENT_TOKEN_PATTERN.test(token)
    );
  });
}

function contentStats(problem) {
  const stem = String(problem?.stem || "").replace(/\r\n?/g, "\n");
  const choices = asArray(problem?.choices).map((choice) => String(choice || "").trim()).filter(Boolean);
  const imagePaths = asArray(problem?.image_paths).filter(Boolean);
  const tables = asArray(problem?.tables).filter((table) => Array.isArray(table) && table.length);
  const answer = String(problem?.answer || "").trim();
  const explanation = String(problem?.explanation || "").trim();
  const tableCells = tables.flatMap((table) =>
    table.flatMap((row) => (Array.isArray(row) ? row.map((cell) => String(cell || "").trim()) : []))
  ).filter(Boolean);
  const lineCount = stem ? stem.split("\n").length : 0;
  const formulaCount = formulaMatches([stem, ...choices, answer, explanation, ...tableCells].join("\n")).length;

  return {
    stem,
    lineCount,
    formulaCount,
    isLongStem: stem.trim().length >= 220 || lineCount >= 6,
    imageCount: imagePaths.length,
    tableCount: tables.length,
    choiceCount: choices.length,
  };
}

function appendContentBadge(label, tone = "neutral") {
  const badge = document.createElement("span");
  badge.className = `content-badge ${tone}`;
  badge.textContent = label;
  els.contentBadges.append(badge);
}

function renderStemPreview(stem) {
  const text = String(stem || "");
  els.stemPreview.innerHTML = "";
  if (!text.trim()) {
    const empty = document.createElement("span");
    empty.className = "stem-preview-empty";
    empty.textContent = "본문 없음";
    els.stemPreview.append(empty);
    return;
  }

  const fragment = document.createDocumentFragment();
  let cursor = 0;
  for (const match of formulaMatches(text)) {
    const index = match.index ?? 0;
    const token = match[0];
    if (index < cursor) continue;
    if (index > cursor) fragment.append(document.createTextNode(text.slice(cursor, index)));

    const code = document.createElement("code");
    code.className = "formula-token";
    code.textContent = token;
    fragment.append(code);
    cursor = index + token.length;
  }
  if (cursor < text.length) {
    fragment.append(document.createTextNode(text.slice(cursor)));
  }
  els.stemPreview.append(fragment);
}

function renderContentInspector(problem) {
  const stats = contentStats(problem);
  els.contentBadges.innerHTML = "";
  appendContentBadge(`본문 ${stats.lineCount}줄`, stats.lineCount ? "neutral" : "empty");
  appendContentBadge(`수식 ${stats.formulaCount}개`, stats.formulaCount ? "math" : "empty");
  if (stats.isLongStem) appendContentBadge("긴 지문", "warn");
  appendContentBadge(`이미지 ${stats.imageCount}개`, stats.imageCount ? "media" : "empty");
  appendContentBadge(`표 ${stats.tableCount}개`, stats.tableCount ? "table" : "empty");
  appendContentBadge(`선지 ${stats.choiceCount}개`, stats.choiceCount ? "neutral" : "empty");
  renderStemPreview(stats.stem);
  if (els.recognitionLayerButton) {
    els.recognitionLayerButton.disabled = !problem;
    els.recognitionLayerButton.title = problem ? "문항의 인식 구조와 원본 좌표 보기" : "문항을 먼저 선택하세요";
  }
}

function recognitionSourceLabel(problem) {
  const layout = problem?.layout || {};
  if (layout.block_type === "image_fallback") return "이미지 보존";
  if (problem?.source_type === "pdf" && layout.bbox_px) return "PDF 텍스트";
  if (problem?.source_type === "manual") return "직접 입력";
  if (problem?.source_type === "web") return "웹 구조";
  return "구조 데이터";
}

function validBbox(value) {
  return Array.isArray(value) && value.length === 4 && value.every((item) => Number.isFinite(Number(item)));
}

function recognitionModel(problem) {
  const stats = contentStats(problem);
  const layout = problem?.layout || {};
  const page = layout.page || {};
  const bbox = validBbox(layout.bbox_px) ? layout.bbox_px.map(Number) : null;
  const pageWidth = Number(page.width_px || page.width || 0);
  const pageHeight = Number(page.height_px || page.height || 0);
  const pdfLines = asArray(layout.pdf_lines).filter((line) => {
    if (!validBbox(line?.bbox_px)) return false;
    const [, , width, height] = line.bbox_px.map(Number);
    if (!(pageWidth > 0 && pageHeight > 0)) return true;
    return width > 0 && height > 0 && width <= pageWidth && height <= pageHeight * .12;
  });
  const imageFallback = layout.block_type === "image_fallback";
  const answer = String(problem?.answer || "").trim();
  const explanation = String(problem?.explanation || "").trim();
  const repairs = asArray(layout.math_geometry_repairs).length;
  const hasBrokenGlyph = /[\uE000-\uF8FF�]/.test([problem?.stem, ...(problem?.choices || []), answer, explanation].join("\n"));
  const parts = [
    { label: "본문", tone: stats.lineCount || imageFallback ? "good" : "error", detail: stats.lineCount ? `${stats.lineCount}줄의 본문이 구조화됨` : imageFallback ? "본문을 이미지 블록으로 보존함" : "본문이 없어 입력 확인 필요" },
    { label: "수식", tone: stats.formulaCount ? "good" : "neutral", detail: `${stats.formulaCount}개 감지${repairs ? ` · 좌표 ${repairs}개 복원` : ""}` },
    { label: "선지", tone: stats.choiceCount && !answer ? "review" : "good", detail: stats.choiceCount ? `${stats.choiceCount}개${answer ? " · 정답 입력됨" : " · 정답 확인 필요"}` : "선지 없는 서술형 또는 미입력" },
    { label: "이미지", tone: stats.imageCount ? "good" : "neutral", detail: stats.imageCount ? `${stats.imageCount}개 첨부 또는 보존` : "이미지 없음" },
    { label: "표", tone: stats.tableCount ? "good" : "neutral", detail: stats.tableCount ? `${stats.tableCount}개 표 구조 보존` : "표 없음" },
    { label: "해설", tone: explanation ? "good" : "review", detail: explanation ? "해설 입력됨" : "해설 없음 · 필요 시 보완" },
  ];
  const issues = [];
  if (!stats.lineCount && !imageFallback) issues.push("본문 없음");
  if (imageFallback) issues.push("OCR 확인 권장");
  if (stats.choiceCount && !answer) issues.push("정답 미입력");
  if (problem?.source_type === "pdf" && (!bbox || !pdfLines.length)) issues.push("PDF 좌표 일부 없음");
  if (hasBrokenGlyph) issues.push("깨진 문자 확인");
  return { stats, layout, page, bbox, pdfLines, repairs, parts, issues, sourceLabel: recognitionSourceLabel(problem) };
}

function appendRecognitionSummary(label, tone = "neutral") {
  const item = document.createElement("span");
  item.className = `recognition-summary-item ${tone}`;
  const dot = document.createElement("i");
  dot.setAttribute("aria-hidden", "true");
  item.append(dot, document.createTextNode(label));
  els.recognitionLayerSummary.append(item);
}

function renderRecognitionMap(model) {
  els.recognitionLayerMap.replaceChildren();
  const width = Number(model.page.width_px || model.page.width || 0);
  const height = Number(model.page.height_px || model.page.height || 0);
  const pageNumber = model.page.number || model.layout.page_number || activeProblem()?.source_page || "";
  els.recognitionPageLabel.textContent = pageNumber ? `${pageNumber}쪽` : "페이지 번호 없음";
  if (!(width > 0 && height > 0)) {
    const empty = document.createElement("div");
    empty.className = "recognition-map-empty";
    empty.textContent = "이 문항에는 페이지 좌표가 없습니다. 내용 항목 상태는 오른쪽 목록에서 확인할 수 있습니다.";
    els.recognitionLayerMap.append(empty);
    return;
  }
  const page = document.createElement("div");
  page.className = "recognition-page";
  page.style.setProperty("--recognition-page-ratio", String(width / height));
  const applyBox = (element, box) => {
    const [x, y, w, h] = box.map(Number);
    element.style.left = `${Math.max(0, Math.min(100, x / width * 100))}%`;
    element.style.top = `${Math.max(0, Math.min(100, y / height * 100))}%`;
    element.style.width = `${Math.max(.7, Math.min(100, w / width * 100))}%`;
    element.style.height = `${Math.max(.4, Math.min(100, h / height * 100))}%`;
  };
  model.pdfLines.slice(0, 120).forEach((line) => {
    const marker = document.createElement("span");
    marker.className = "recognition-line";
    marker.setAttribute("aria-hidden", "true");
    applyBox(marker, line.bbox_px);
    page.append(marker);
  });
  if (model.bbox) {
    const region = document.createElement("div");
    region.className = "recognition-page-region";
    region.dataset.label = "문항 영역";
    region.setAttribute("role", "img");
    region.setAttribute("aria-label", "원본 페이지에서 인식된 문항 영역");
    applyBox(region, model.bbox);
    page.append(region);
  }
  els.recognitionLayerMap.append(page);
}

function renderRecognitionLayer(problem) {
  const model = recognitionModel(problem);
  els.recognitionLayerContext.textContent = `${problemLabel(problem)} · ${model.sourceLabel}`;
  els.recognitionLayerSummary.replaceChildren();
  appendRecognitionSummary(model.sourceLabel, model.bbox || problem.source_type === "manual" ? "good" : "review");
  appendRecognitionSummary(`본문 ${model.stats.lineCount}줄`, model.stats.lineCount ? "good" : model.layout.block_type === "image_fallback" ? "review" : "error");
  appendRecognitionSummary(`수식 ${model.stats.formulaCount}`, model.stats.formulaCount ? "good" : "neutral");
  appendRecognitionSummary(`선지 ${model.stats.choiceCount}`, model.stats.choiceCount ? "good" : "neutral");
  appendRecognitionSummary(`좌표 줄 ${model.pdfLines.length}`, model.pdfLines.length ? "good" : "neutral");
  appendRecognitionSummary(model.issues.length ? `검토 ${model.issues.length}` : "구조 이상 없음", model.issues.length ? "review" : "good");
  els.recognitionLayerList.replaceChildren();
  model.parts.forEach((part) => {
    const item = document.createElement("div");
    item.className = "recognition-layer-item";
    const dot = document.createElement("span");
    dot.className = `recognition-status-dot ${part.tone}`;
    dot.setAttribute("aria-hidden", "true");
    const copy = document.createElement("span");
    copy.className = "recognition-layer-copy";
    const title = document.createElement("strong");
    title.textContent = part.label;
    const detail = document.createElement("span");
    detail.textContent = part.detail;
    copy.append(title, detail);
    item.append(dot, copy);
    els.recognitionLayerList.append(item);
  });
  if (model.issues.length) {
    const item = document.createElement("div");
    item.className = "recognition-layer-item";
    const dot = document.createElement("span");
    dot.className = "recognition-status-dot review";
    const copy = document.createElement("span");
    copy.className = "recognition-layer-copy";
    const title = document.createElement("strong");
    title.textContent = "확인할 항목";
    const detail = document.createElement("span");
    detail.textContent = model.issues.join(" · ");
    copy.append(title, detail);
    item.append(dot, copy);
    els.recognitionLayerList.append(item);
  }
  renderRecognitionMap(model);
}

function openRecognitionLayer() {
  const problem = activeProblem();
  if (!problem) return;
  renderRecognitionLayer(editorDraftProblem(problem));
  openModal(els.recognitionLayerModal, els.recognitionLayerButton, els.recognitionLayerClose);
}

// --- 내보내기 바구니 ---------------------------------------------------------

const BASKET_STORAGE_KEY = "hwpmake.basket.v1";

function persistBasket() {
  try {
    localStorage.setItem(BASKET_STORAGE_KEY, JSON.stringify(state.basket));
  } catch {
    // localStorage 비활성(사생활 모드 등)이면 조용히 무시한다. 세션 내 동작엔 지장 없음.
  }
}

function restoreBasket() {
  try {
    const parsed = JSON.parse(localStorage.getItem(BASKET_STORAGE_KEY) || "[]");
    if (Array.isArray(parsed)) {
      return parsed
        .filter((entry) => entry && typeof entry.id === "number")
        .map((entry) => ({ id: entry.id, label: String(entry.label || `#${entry.id}`) }));
    }
  } catch {
    // 손상된 저장값은 무시한다.
  }
  return [];
}

function inBasket(id) {
  return state.basket.some((entry) => entry.id === id);
}

function addToBasket(problem) {
  if (!inBasket(problem.id)) {
    state.basket.push({ id: problem.id, label: problemLabel(problem) });
  }
}

function addManyToBasket(problems, { replace = false } = {}) {
  if (replace) state.basket = [];
  for (const problem of problems) addToBasket(problem);
}

function insertBasketProblemAt(problem, targetIndex) {
  const existingIndex = state.basket.findIndex((entry) => entry.id === problem.id);
  const entry =
    existingIndex >= 0
      ? state.basket.splice(existingIndex, 1)[0]
      : { id: problem.id, label: problemLabel(problem) };
  const adjustedTarget = existingIndex >= 0 && existingIndex < targetIndex ? targetIndex - 1 : targetIndex;
  const index = Math.max(0, Math.min(adjustedTarget, state.basket.length));
  state.basket.splice(index, 0, entry);
}

function toggleBasket(problem) {
  if (inBasket(problem.id)) removeFromBasket(problem.id);
  else addToBasket(problem);
}

function removeFromBasket(id) {
  state.basket = state.basket.filter((entry) => entry.id !== id);
}

function clearBasket() {
  state.basket = [];
  renderList();
  renderBasket();
}

function moveBasketItem(index, target) {
  if (target < 0 || target >= state.basket.length) return;
  const [item] = state.basket.splice(index, 1);
  state.basket.splice(target, 0, item);
  renderBasket();
}

function renderOrderEditor(focusIndex = null) {
  const count = state.orderDraft.length;
  els.orderEditorCount.textContent = `담은 문제 ${count}개`;
  els.orderEditorApply.disabled = !count;
  els.orderEditorList.replaceChildren();
  if (!count) {
    const empty = document.createElement("div");
    empty.className = "order-editor-empty";
    empty.textContent = "적용할 문항이 없습니다. 취소하면 기존 순서를 유지합니다.";
    els.orderEditorList.append(empty);
    els.orderEditorStatus.textContent = "모든 문항이 임시 목록에서 제거됨";
    return;
  }
  state.orderDraft.forEach((entry, index) => {
    const problem = state.problemById.get(entry.id) || state.problems.find((item) => item.id === entry.id);
    const row = document.createElement("div");
    row.className = "order-editor-row";
    row.tabIndex = 0;
    row.dataset.orderIndex = String(index);
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", `${index + 1}번째 문항 ${entry.label}. Alt와 위아래 화살표로 이동하거나 Delete로 제거합니다.`);
    const number = document.createElement("span");
    number.className = "order-editor-index";
    number.textContent = String(index + 1);
    const copy = document.createElement("span");
    copy.className = "order-editor-copy";
    const title = document.createElement("strong");
    title.textContent = entry.label;
    const snippet = document.createElement("span");
    snippet.textContent = compactText(problem?.stem || "본문 미리보기 없음");
    copy.append(title, snippet);
    const makeButton = (label, iconName, disabled, handler, danger = false) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = danger ? "danger" : "ghost";
      button.title = label;
      button.setAttribute("aria-label", label);
      button.disabled = disabled;
      button.append(icon(iconName));
      button.addEventListener("click", handler);
      return button;
    };
    const up = makeButton("위로 이동", "up", index === 0, () => moveOrderDraft(index, index - 1));
    const down = makeButton("아래로 이동", "down", index === count - 1, () => moveOrderDraft(index, index + 1));
    const remove = makeButton("임시 순서에서 제거", "close", false, () => removeOrderDraft(index), true);
    row.addEventListener("keydown", (event) => {
      if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
        event.preventDefault();
        event.stopPropagation();
        moveOrderDraft(index, event.key === "ArrowUp" ? index - 1 : index + 1);
      } else if (event.key === "Delete") {
        event.preventDefault();
        event.stopPropagation();
        removeOrderDraft(index);
      }
    });
    row.append(number, copy, up, down, remove);
    els.orderEditorList.append(row);
  });
  if (focusIndex !== null) {
    const index = Math.max(0, Math.min(focusIndex, count - 1));
    window.requestAnimationFrame(() => els.orderEditorList.querySelector(`[data-order-index="${index}"]`)?.focus());
  }
}

function moveOrderDraft(index, target) {
  if (target < 0 || target >= state.orderDraft.length || index === target) return;
  const [item] = state.orderDraft.splice(index, 1);
  state.orderDraft.splice(target, 0, item);
  els.orderEditorStatus.textContent = `${item.label}을 ${target + 1}번째로 이동`;
  renderOrderEditor(target);
}

function removeOrderDraft(index) {
  const [item] = state.orderDraft.splice(index, 1);
  if (!item) return;
  els.orderEditorStatus.textContent = `${item.label}을 임시 목록에서 제거`;
  renderOrderEditor(Math.min(index, state.orderDraft.length - 1));
}

function openOrderEditor() {
  if (!state.basket.length) return;
  state.orderDraft = state.basket.map((entry) => ({ ...entry }));
  els.orderEditorStatus.textContent = "변경은 순서 적용을 누를 때 반영됩니다.";
  renderOrderEditor();
  openModal(els.orderEditorModal, els.orderEditorButton, els.orderEditorClose);
}

function cancelOrderEditor() {
  state.orderDraft = [];
  closeModal(els.orderEditorModal);
}

function applyOrderEditor() {
  if (!state.orderDraft.length) return;
  state.basket = state.orderDraft.map((entry) => ({ ...entry }));
  state.orderDraft = [];
  renderList();
  renderBasket();
  closeModal(els.orderEditorModal);
  toast("문항 순서를 적용했습니다.");
}

async function handleImportedProblems(created, { quick = false } = {}) {
  if (!created.length) {
    renderList();
    renderBasket();
    renderEditor();
    toast("새로 가져온 문제가 없습니다.");
    return false;
  }
  state.activeId = created[0].id;
  addManyToBasket(created, { replace: quick });
  renderList();
  renderBasket();
  renderEditor();
  setSideMode("library");
  if (quick) {
    return exportSelected(created.map((problem) => problem.id));
  }
  return true;
}

function renderBasket() {
  persistBasket();
  const count = state.basket.length;
  els.basketBadge.textContent = String(state.basket.length);
  els.selectedText.textContent = `담은 문제 ${count}개`;
  if (els.flowBasketCount) els.flowBasketCount.textContent = `담은 문제 ${count}개`;
  if (els.libraryBasketHint) els.libraryBasketHint.textContent = `담은 문제 ${count}개`;
  syncPaperPreviewMeta();
  if (els.basketClearButton) els.basketClearButton.disabled = !state.basket.length;
  if (els.orderEditorButton) els.orderEditorButton.disabled = !state.basket.length;
  if (els.previewButton) els.previewButton.disabled = !count;
  if (els.exportButton) els.exportButton.disabled = !count;
  els.basketList.innerHTML = "";
  if (!state.basket.length) {
    const empty = document.createElement("div");
    empty.className = "basket-empty";
    empty.textContent = "가운데 목록에서 담기 버튼을 누르면 시험지에 들어갈 문제가 여기에 쌓입니다.";
    els.basketList.append(empty);
    window.requestAnimationFrame(() => updatePaperCanvasSize());
    return;
  }

  state.basket.forEach((entry, index) => {
    const problem = state.problemById.get(entry.id) || state.problems.find((item) => item.id === entry.id);
    if (problem) entry.label = problemLabel(problem);

    const row = document.createElement("div");
    row.className = `basket-row ${index % 2 === 0 ? "left-slot" : "right-slot"}`;
    row.draggable = true;
    row.dataset.index = index;
    row.tabIndex = 0;
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", `${index + 1}번째 문항 ${problemLabel(problem || { title: entry.label })}. Alt+위아래 화살표로 순서를 바꾸고 Delete로 제거합니다.`);

    const handle = document.createElement("span");
    handle.className = "basket-handle";
    handle.append(icon("grip"));

    const body = document.createElement("span");
    body.className = "basket-body";

    const label = document.createElement("span");
    label.className = "basket-label";
    label.textContent = `${index + 1}. ${entry.label}`;
    label.title = entry.label;

    const snippet = document.createElement("span");
    snippet.className = "basket-snippet";
    snippet.textContent = compactText(problem?.stem || entry.label);

    const position = document.createElement("span");
    position.className = "basket-position";
    position.textContent = `${index + 1}번째 문항 · 실제 열 위치는 페이지 렌더에서 확정`;

    body.append(label, snippet, position);
    label.addEventListener("click", async () => {
      await selectProblem(entry.id);
    });

    const up = document.createElement("button");
    up.type = "button";
    up.className = "basket-btn";
    up.title = "위로 이동";
    up.setAttribute("aria-label", "위로 이동");
    up.append(icon("up"));
    up.addEventListener("click", () => moveBasketItem(index, index - 1));

    const down = document.createElement("button");
    down.type = "button";
    down.className = "basket-btn";
    down.title = "아래로 이동";
    down.setAttribute("aria-label", "아래로 이동");
    down.append(icon("down"));
    down.addEventListener("click", () => moveBasketItem(index, index + 1));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "basket-btn danger";
    remove.title = "목록에서 제거";
    remove.setAttribute("aria-label", "목록에서 제거");
    remove.append(icon("close"));
    remove.addEventListener("click", () => {
      removeFromBasket(entry.id);
      renderList();
      renderBasket();
    });

    row.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("text/plain", String(index));
      event.dataTransfer.setData("application/x-basket-index", String(index));
      event.dataTransfer.effectAllowed = "move";
      row.classList.add("dragging");
    });
    row.addEventListener("dragend", () => row.classList.remove("dragging"));
    row.addEventListener("keydown", (event) => {
      if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
        event.preventDefault();
        event.stopPropagation();
        const target = event.key === "ArrowUp" ? index - 1 : index + 1;
        if (target >= 0 && target < state.basket.length) {
          moveBasketItem(index, target);
          window.requestAnimationFrame(() => els.basketList.querySelector(`[data-index="${target}"]`)?.focus());
        }
        return;
      }
      if (event.key === "Delete") {
        event.preventDefault();
        event.stopPropagation();
        removeFromBasket(entry.id);
        renderList();
        renderBasket();
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        selectProblem(entry.id);
      }
    });
    row.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      row.classList.add("drag-over");
    });
    row.addEventListener("dragleave", () => row.classList.remove("drag-over"));
    row.addEventListener("drop", (event) => {
      event.preventDefault();
      event.stopPropagation();
      row.classList.remove("drag-over");
      const problemId = Number(event.dataTransfer.getData("application/x-problem-id"));
      if (!Number.isNaN(problemId) && problemId > 0) {
        const dropped = state.problems.find((item) => item.id === problemId);
        if (dropped) {
          insertBasketProblemAt(dropped, index);
          state.activeId = dropped.id;
          renderList();
          renderBasket();
          renderEditor();
        }
        return;
      }
      const from = Number(event.dataTransfer.getData("application/x-basket-index") || event.dataTransfer.getData("text/plain"));
      if (!Number.isNaN(from) && from !== index) moveBasketItem(from, index);
    });

    row.append(handle, body, up, down, remove);
    els.basketList.append(row);
  });
  window.requestAnimationFrame(() => updatePaperCanvasSize());
}

// --- 내보내기 기록 -----------------------------------------------------------

function humanSize(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const value = bytes / 1024 ** index;
  return `${value >= 10 || index === 0 ? Math.round(value) : value.toFixed(1)} ${units[index]}`;
}

function formatExportTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

async function loadExportHistory() {
  try {
    const data = await api("/api/exports");
    state.exports = data.items || [];
  } catch {
    state.exports = [];
  }
  renderHistory();
}

function renderHistory() {
  const items = state.exports || [];
  els.historyBadge.textContent = String(items.length);
  els.historyList.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "basket-empty";
    empty.textContent = "아직 없음";
    els.historyList.append(empty);
    return;
  }
  for (const item of items.slice(0, 20)) {
    const row = document.createElement("div");
    row.className = "history-row";

    const link = document.createElement("a");
    link.className = "history-link";
    link.href = item.url;
    link.download = item.display_name || item.name;
    link.title = item.name;

    const name = document.createElement("span");
    name.className = "history-name";
    name.textContent = item.display_name || item.name;

    const meta = document.createElement("span");
    meta.className = "history-meta";
    const formatPill = document.createElement("b");
    formatPill.className = "source-pill";
    formatPill.textContent = (item.format || "").toUpperCase();
    meta.append(formatPill, document.createTextNode(` ${humanSize(item.size)} · ${formatExportTime(item.modified)}`));

    link.append(name, meta);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "basket-btn danger";
    remove.title = "기록 삭제";
    remove.setAttribute("aria-label", "기록 삭제");
    remove.append(icon("close"));
    remove.addEventListener("click", () => deleteExport(item.name));

    row.append(link, remove);
    els.historyList.append(row);
  }
}

async function deleteExport(name) {
  if (!window.confirm(`“${name}” 파일을 로컬 저장소에서 영구 삭제할까요?`)) return;
  try {
    await api(`/api/exports/${encodeURIComponent(name)}`, { method: "DELETE" });
    await loadExportHistory();
    toast("파일을 삭제했습니다.");
  } catch (error) {
    toast(`삭제 실패: ${error.message}`);
  }
}

// --- 문제 목록 ---------------------------------------------------------------

function renderList() {
  els.problemList.innerHTML = "";
  if (!state.problems.length) {
    const empty = document.createElement("div");
    empty.className = "empty-editor";
    empty.textContent = "왼쪽에서 파일·텍스트·URL을 가져오면 문제가 여기에 나타납니다.";
    els.problemList.append(empty);
    return;
  }
  for (const problem of state.problems) {
    const row = document.createElement("article");
    const selected = inBasket(problem.id);
    row.className = `problem-row ${problem.id === state.activeId ? "active" : ""} ${selected ? "selected" : ""}`;
    row.dataset.id = problem.id;
    row.draggable = true;

    const body = document.createElement("div");
    body.className = "problem-body";
    const title = document.createElement("div");
    title.className = "problem-title";
    const titleText = document.createElement("span");
    titleText.textContent = problemLabel(problem);
    const sourcePill = document.createElement("b");
    sourcePill.className = "source-pill";
    sourcePill.textContent = sourceLabel(problem.source_type);
    title.append(titleText, sourcePill);

    const meta = document.createElement("div");
    meta.className = "problem-meta";
    meta.textContent = [problem.subject, problem.unit, problem.tags].filter(Boolean).join(" · ") || problem.source_name || "로컬";

    const preview = document.createElement("div");
    preview.className = "problem-preview";
    preview.textContent = problem.stem || (problem.image_paths?.length ? "이미지 첨부" : "본문 없음");

    const mergeButton = document.createElement("button");
    mergeButton.type = "button";
    mergeButton.className = `problem-merge-btn ${selected ? "active" : ""}`;
    mergeButton.textContent = selected ? "빼기" : "시험지에 담기";
    mergeButton.title = selected ? "시험지 구성에서 빼기" : "시험지 구성에 담기";
    mergeButton.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleBasket(problem);
      renderList();
      renderBasket();
    });

    const action = document.createElement("div");
    action.className = "problem-action";

    const status = document.createElement("span");
    status.className = `problem-status ${selected ? "selected" : ""}`;
    status.textContent = selected ? "담김" : "보관함";

    body.append(title, meta, preview);
    action.append(status, mergeButton);
    row.append(body, action);
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    row.setAttribute("aria-label", `${problemLabel(problem)} 편집`);
    row.addEventListener("click", () => selectProblem(problem.id));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectProblem(problem.id);
      }
    });
    row.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("application/x-problem-id", String(problem.id));
      event.dataTransfer.effectAllowed = "copyMove";
      row.classList.add("dragging");
    });
    row.addEventListener("dragend", () => row.classList.remove("dragging"));
    els.problemList.append(row);
  }
}

function activeProblem() {
  return state.problemById.get(state.activeId) || state.problems.find((item) => item.id === state.activeId) || null;
}

async function selectProblem(problemId) {
  if (problemId === state.activeId) return;
  const saved = await flushActiveDraft({ quiet: true });
  if (!saved) return;
  state.activeId = problemId;
  setWorkflowStep(2);
  renderList();
  renderEditor();
  if (mobileWorkspaceActive()) setMobilePane("editor", { focus: true });
}

function renderEditor() {
  const problem = activeProblem();
  clearAIResult();
  if (!problem) {
    els.emptyEditor.classList.remove("hidden");
    els.editorForm.classList.add("hidden");
    renderContentInspector(null);
    if (els.deleteButton) els.deleteButton.disabled = true;
    if (els.editorContext) {
      els.editorContext.textContent = "선택 없음";
      els.editorContext.removeAttribute("title");
    }
    state.draftDirty = false;
    setSaveStatus("변경 없음");
    return;
  }
  els.emptyEditor.classList.add("hidden");
  els.editorForm.classList.remove("hidden");
  if (els.deleteButton) els.deleteButton.disabled = false;
  if (els.editorContext) {
    const context = problemLabel(problem);
    els.editorContext.textContent = context;
    els.editorContext.title = context;
  }
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
  renderContentInspector(problem);
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
    remove.title = "이미지 삭제";
    remove.setAttribute("aria-label", "이미지 삭제");
    remove.append(icon("close"));
    remove.addEventListener("click", () => removeImage(problem, index));

    figure.append(image, remove);
    els.imagePreview.append(figure);
  });
  state.draftDirty = false;
  setSaveStatus("저장됨", "saved");
  syncAIActionState();
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
    tables: Array.isArray(problem.tables) ? problem.tables : [],
  };
}

function editorDraftProblem(problem) {
  return {
    ...problem,
    ...editorPayload(problem, problem.image_paths || []),
  };
}

function refreshEditorInspector() {
  const problem = activeProblem();
  if (!problem || els.editorForm.classList.contains("hidden")) return;
  renderContentInspector(editorDraftProblem(problem));
}

function markDraftDirty() {
  if (!activeProblem() || els.editorForm.classList.contains("hidden")) return;
  state.draftDirty = true;
  setSaveStatus("저장되지 않은 변경", "saving");
  window.clearTimeout(markDraftDirty.timer);
  markDraftDirty.timer = window.setTimeout(() => flushActiveDraft({ quiet: true }), 900);
}

async function flushActiveDraft({ quiet = false } = {}) {
  const problem = activeProblem();
  if (!problem || !state.draftDirty) return true;
  if (state.savingDraft) return false;
  state.savingDraft = true;
  setSaveStatus("저장 중…", "saving");
  try {
    const updated = await api(`/api/problems/${problem.id}`, {
      method: "PUT",
      body: JSON.stringify(editorPayload(problem, problem.image_paths || [])),
    });
    const savedProblem = updated.item || updated;
    if (savedProblem?.id) {
      state.problemById.set(savedProblem.id, savedProblem);
      const index = state.problems.findIndex((item) => item.id === savedProblem.id);
      if (index >= 0) state.problems[index] = savedProblem;
    }
    state.draftDirty = false;
    setSaveStatus("저장됨", "saved");
    renderList();
    renderBasket();
    if (!quiet) toast("문항을 저장했습니다.");
    return true;
  } catch (error) {
    setSaveStatus("저장 실패", "error");
    if (!quiet) toast(`저장 실패: ${error.message}`);
    return false;
  } finally {
    state.savingDraft = false;
  }
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
  txt: "text",
  text: "text",
  md: "text",
  markdown: "text",
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

function textToBase64(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (let index = 0; index < bytes.length; index += 0x8000) {
    const chunk = bytes.subarray(index, index + 0x8000);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

function setImportButtonsDisabled(buttons, disabled) {
  for (const button of buttons.filter(Boolean)) button.disabled = disabled;
}

function isPdfFile(file) {
  return file?.type === "application/pdf" || /\.pdf$/i.test(file?.name || "");
}

async function importFiles({ quick = false } = {}) {
  const files = Array.from(els.fileInput.files || []);
  if (!files.length) {
    toast("파일을 선택하세요.");
    return;
  }
  setImportButtonsDisabled([els.importButton, els.quickImportButton, els.layoutExportButton], true);
  try {
    let total = 0;
    const notices = [];
    const created = [];
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
      const resultCreated = result.created || [];
      total += resultCreated.length;
      created.push(...resultCreated);
      notices.push(...(result.notices || []));
    }
    await loadProblems({ render: false });
    const completed = await handleImportedProblems(created, { quick });
    toast(
      quick && completed
        ? `${total}개 문항으로 시험지 파일을 만들었습니다.${notices.length ? ` ${notices[0]}` : ""}`
        : quick
          ? `${total}개 문항은 가져왔지만 파일 만들기는 완료되지 않았습니다.`
          : `${total}개 문항을 가져와 시험지 구성에 담았습니다.${notices.length ? ` ${notices[0]}` : ""}`
    );
    els.fileInput.value = "";
    els.fileName.textContent = "HWP, HWPX, DOCX, PDF, 이미지, TXT";
  } catch (error) {
    toast(`가져오기 실패: ${error.message}`);
  } finally {
    setImportButtonsDisabled([els.importButton, els.quickImportButton, els.layoutExportButton], false);
  }
}

async function exportPdfLayoutFiles() {
  const files = Array.from(els.fileInput.files || []);
  if (!files.length) {
    toast("PDF 파일을 선택하세요.");
    return;
  }
  const pdfFiles = files.filter(isPdfFile);
  if (!pdfFiles.length) {
    toast("PDF 파일만 원본 레이아웃 HWPX로 만들 수 있습니다.");
    return;
  }

  setImportButtonsDisabled([els.importButton, els.quickImportButton, els.layoutExportButton], true);
  try {
    const results = [];
    for (const file of pdfFiles) {
      const payload = {
        filename: file.name,
        data_base64: await fileToBase64(file),
        boxed_passages: true,
        layout_mode: "coordinate",
        native_math: true,
      };
      if (els.layoutMathAi?.checked) {
        payload.math_ai_recognition = true;
        payload.math_ai_model = "gemini-3.5-flash";
      }
      const result = await api("/api/pdf-layout-export", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      results.push(result);
      if (result.export?.url) {
        const link = document.createElement("a");
        link.href = result.export.url;
        link.download = result.export.name || `${file.name}.hwpx`;
        document.body.append(link);
        link.click();
        link.remove();
      }
    }
    await loadExportHistory();
    toast(`${results.length}개 PDF를 원본 레이아웃 HWPX로 만들었습니다.`);
  } catch (error) {
    toast(`원본 레이아웃 변환 실패: ${error.message}`);
  } finally {
    setImportButtonsDisabled([els.importButton, els.quickImportButton, els.layoutExportButton], false);
  }
}

async function collectFromUrl({ quick = false } = {}) {
  if (state.collecting) return;
  const url = els.collectUrl.value.trim();
  if (!url) {
    toast("수집할 URL을 입력하세요.");
    return;
  }
  state.collecting = true;
  setImportButtonsDisabled([els.collectButton, els.quickCollectButton], true);
  els.collectButton.textContent = "가져오는 중...";
  if (els.quickCollectButton) els.quickCollectButton.textContent = "만드는 중...";
  try {
    const result = await api("/api/collect", {
      method: "POST",
      body: JSON.stringify({ url, metadata: metadata() }),
    });
    await loadProblems({ render: false });
    const completed = await handleImportedProblems(result.created || [], { quick });
    toast(
      quick && !completed
        ? `${result.created?.length || 0}개 문항은 가져왔지만 파일 만들기는 완료되지 않았습니다.`
        : result.notices?.[0] || `${result.created?.length || 0}개 문항을 가져왔습니다.`
    );
    els.collectUrl.value = "";
  } catch (error) {
    toast(`수집 실패: ${error.message}`);
  } finally {
    state.collecting = false;
    setImportButtonsDisabled([els.collectButton, els.quickCollectButton], false);
    els.collectButton.textContent = "URL에서 가져오기";
    if (els.quickCollectButton) els.quickCollectButton.textContent = "바로 만들기";
  }
}

async function addManualProblem({ quick = false } = {}) {
  const title = els.manualTitle.value.trim();
  const stem = els.manualStem.value.trim();
  if (!title && !stem) {
    toast("제목이나 본문을 입력하세요.");
    return;
  }
  setImportButtonsDisabled([els.manualButton, els.quickManualButton], true);
  try {
    const result = await api("/api/import-text", {
      method: "POST",
      body: JSON.stringify({
        title,
        text: stem || title,
        metadata: metadata(),
        source_type: "manual",
      }),
    });
    const created = result.created || [];
    if (created.length) {
      state.activeId = created[created.length - 1].id;
    }
    els.manualTitle.value = "";
    els.manualStem.value = "";
    await loadProblems({ render: false });
    const completed = await handleImportedProblems(created, { quick });
    toast(
      quick && completed
        ? `${created.length}개 문항으로 시험지 파일을 만들었습니다.${result.notices?.[1] ? ` ${result.notices[1]}` : ""}`
        : quick
          ? `${created.length}개 문항은 가져왔지만 파일 만들기는 완료되지 않았습니다.`
          : `${created.length}개 문항을 가져와 시험지 구성에 담았습니다.${result.notices?.[1] ? ` ${result.notices[1]}` : ""}`
    );
  } catch (error) {
    toast(`입력 실패: ${error.message}`);
  } finally {
    setImportButtonsDisabled([els.manualButton, els.quickManualButton], false);
  }
}

async function saveActive(event) {
  event.preventDefault();
  state.draftDirty = true;
  await flushActiveDraft({ quiet: false });
}

async function deleteActive() {
  const problem = activeProblem();
  if (!problem) return;
  if (!window.confirm(`“${problemLabel(problem)}” 문항을 영구 삭제할까요?`)) return;
  try {
    await api(`/api/problems/${problem.id}`, { method: "DELETE" });
    removeFromBasket(problem.id);
    state.activeId = null;
    await loadProblems();
    toast("삭제했습니다.");
  } catch (error) {
    toast(`삭제 실패: ${error.message}`);
  }
}

async function exportSelected(idsOverride = null) {
  const ids = Array.isArray(idsOverride) ? idsOverride : state.basket.map((entry) => entry.id);
  if (!ids.length) {
    toast("먼저 시험지에 넣을 문제를 담으세요.");
    return false;
  }
  if (!(await flushActiveDraft({ quiet: true }))) {
    toast("편집 중인 문항을 저장하지 못해 내보내기를 중단했습니다.");
    return false;
  }
  setWorkflowStep(3);
  if (mobileWorkspaceActive()) setMobilePane("preview", { focus: true });
  els.exportButton.disabled = true;
  try {
    const response = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ids,
        title: els.exportTitle.value.trim() || DEFAULT_EXPORT_TITLE,
        format: els.exportFormat.value,
        template_key: els.exportTemplate.value || "basic",
        include_answer_sheet: els.exportAnswerSheet.checked,
        native_math: els.exportFormat.value === "hwpx" && Boolean(els.exportNativeMath?.checked),
      }),
    });
    if (!response.ok) throw new Error(await response.text());
    const blob = await response.blob();
    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename\*=UTF-8''([^;]+)|filename="?([^"]+)"?/);
    const fallback = `${els.exportTitle.value || DEFAULT_EXPORT_TITLE}.${els.exportFormat.value}`;
    const filename = decodeURIComponent(match?.[1] || match?.[2] || fallback);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    await loadExportHistory();
    toast(`${ids.length}개 문항을 내보냈습니다.`);
    return true;
  } catch (error) {
    toast(`내보내기 실패: ${error.message}`);
    return false;
  } finally {
    els.exportButton.disabled = !state.basket.length;
  }
}

function renderActualPreviewThumbs() {
  els.previewThumbs.replaceChildren();
  state.actualPreviewPages.forEach((src, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "preview-thumb";
    button.setAttribute("aria-label", `${index + 1}쪽 보기`);
    if (index === state.actualPreviewPageIndex) button.setAttribute("aria-current", "page");
    const image = document.createElement("img");
    image.src = src;
    image.alt = "";
    const label = document.createElement("span");
    label.textContent = String(index + 1);
    button.append(image, label);
    button.addEventListener("click", () => setActualPreviewPage(index, { focusStage: true }));
    els.previewThumbs.append(button);
  });
}

function updateActualPreviewControls() {
  const count = state.actualPreviewPages.length;
  const index = state.actualPreviewPageIndex;
  els.actualPreviewPageLabel.textContent = count ? `${index + 1} / ${count}` : "0 / 0";
  els.actualPreviewPrev.disabled = !count || index === 0;
  els.actualPreviewNext.disabled = !count || index === count - 1;
  els.actualPreviewZoomOut.disabled = !count || state.actualPreviewZoom <= ACTUAL_PREVIEW_ZOOM_MIN;
  els.actualPreviewZoomIn.disabled = !count || state.actualPreviewZoom >= ACTUAL_PREVIEW_ZOOM_MAX;
  els.actualPreviewZoomLabel.textContent = `${Math.round(state.actualPreviewZoom * 100)}%`;
  els.actualPreviewZoomLabel.setAttribute("aria-label", `현재 배율 ${Math.round(state.actualPreviewZoom * 100)}%, 눌러 100%로 초기화`);
  els.actualPreviewFit.classList.toggle("active", state.actualPreviewFit);
  els.actualPreviewFit.setAttribute("aria-pressed", String(state.actualPreviewFit));
}

function updateActualPreviewGeometry({ center = false } = {}) {
  const width = state.actualPreviewNaturalWidth;
  const height = state.actualPreviewNaturalHeight;
  if (!(width > 0 && height > 0)) return;
  const stage = els.actualPreviewStage;
  const oldCenterX = stage.scrollLeft + stage.clientWidth / 2;
  const oldCenterY = stage.scrollTop + stage.clientHeight / 2;
  const oldZoom = Number(els.actualPreviewViewport.dataset.zoom || state.actualPreviewZoom || 1);
  els.actualPreviewViewport.style.width = `${Math.ceil(width * state.actualPreviewZoom) + 2}px`;
  els.actualPreviewViewport.style.height = `${Math.ceil(height * state.actualPreviewZoom) + 2}px`;
  els.actualPreviewViewport.style.setProperty("--actual-preview-zoom", String(state.actualPreviewZoom));
  els.actualPreviewViewport.dataset.zoom = String(state.actualPreviewZoom);
  updateActualPreviewControls();
  window.requestAnimationFrame(() => {
    if (center) {
      stage.scrollLeft = Math.max(0, (stage.scrollWidth - stage.clientWidth) / 2);
      stage.scrollTop = 0;
    } else if (oldZoom > 0) {
      const ratio = state.actualPreviewZoom / oldZoom;
      stage.scrollLeft = Math.max(0, oldCenterX * ratio - stage.clientWidth / 2);
      stage.scrollTop = Math.max(0, oldCenterY * ratio - stage.clientHeight / 2);
    }
  });
}

function setActualPreviewZoom(value, { fit = false, center = false } = {}) {
  if (!state.actualPreviewPages.length) return;
  state.actualPreviewZoom = Math.max(ACTUAL_PREVIEW_ZOOM_MIN, Math.min(ACTUAL_PREVIEW_ZOOM_MAX, Math.round(Number(value) * 100) / 100));
  state.actualPreviewFit = fit;
  updateActualPreviewGeometry({ center });
}

function fitActualPreview() {
  if (!(state.actualPreviewNaturalWidth > 0 && state.actualPreviewNaturalHeight > 0)) return;
  const availableWidth = Math.max(1, els.actualPreviewStage.clientWidth - 44);
  const availableHeight = Math.max(1, els.actualPreviewStage.clientHeight - 44);
  const zoom = Math.min(availableWidth / state.actualPreviewNaturalWidth, availableHeight / state.actualPreviewNaturalHeight, 1);
  setActualPreviewZoom(zoom, { fit: true, center: true });
}

function setActualPreviewPage(index, { focusStage = false } = {}) {
  const count = state.actualPreviewPages.length;
  if (!count) return;
  state.actualPreviewPageIndex = Math.max(0, Math.min(index, count - 1));
  state.actualPreviewNaturalWidth = 0;
  state.actualPreviewNaturalHeight = 0;
  state.actualPreviewFit = true;
  renderActualPreviewThumbs();
  updateActualPreviewControls();
  els.actualPreviewViewport.style.width = "1px";
  els.actualPreviewViewport.style.height = "1px";
  els.actualPreviewImage.alt = `실제 출력 미리보기 ${state.actualPreviewPageIndex + 1}쪽`;
  els.actualPreviewImage.onload = () => {
    state.actualPreviewNaturalWidth = els.actualPreviewImage.naturalWidth;
    state.actualPreviewNaturalHeight = els.actualPreviewImage.naturalHeight;
    window.requestAnimationFrame(() => fitActualPreview());
  };
  els.actualPreviewImage.src = state.actualPreviewPages[state.actualPreviewPageIndex];
  if (els.actualPreviewImage.complete && els.actualPreviewImage.naturalWidth) els.actualPreviewImage.onload();
  if (focusStage) window.requestAnimationFrame(() => els.actualPreviewStage.focus());
}

function resetActualPreview() {
  state.actualPreviewPages = [];
  state.actualPreviewPageIndex = 0;
  state.actualPreviewZoom = 1;
  state.actualPreviewFit = true;
  state.actualPreviewNaturalWidth = 0;
  state.actualPreviewNaturalHeight = 0;
  els.previewThumbs.replaceChildren();
  els.actualPreviewImage.removeAttribute("src");
  els.actualPreviewImage.alt = "";
  updateActualPreviewControls();
}

async function previewExport() {
  const ids = state.basket.map((entry) => entry.id);
  if (!ids.length) {
    toast("먼저 시험지에 넣을 문제를 담으세요.");
    return;
  }
  if (!(await flushActiveDraft({ quiet: true }))) {
    toast("편집 중인 문항을 저장하지 못해 미리보기를 중단했습니다.");
    return;
  }
  setWorkflowStep(3);
  if (mobileWorkspaceActive()) setMobilePane("preview", { focus: true });
  const buttonLabel = els.previewButton.textContent;
  els.previewButton.disabled = true;
  els.previewButton.textContent = "미리보기 생성...";
  try {
    const result = await api("/api/preview", {
      method: "POST",
      body: JSON.stringify({
        ids,
        title: els.exportTitle.value.trim() || DEFAULT_EXPORT_TITLE,
        format: "hwpx",
        template_key: els.exportTemplate.value || "basic",
        include_answer_sheet: els.exportAnswerSheet.checked,
        native_math: Boolean(els.exportNativeMath?.checked),
      }),
    });
    resetActualPreview();
    state.actualPreviewPages = asArray(result.pages).filter(Boolean);
    const notes = [];
    if (result.truncated) notes.push(`전체 ${result.page_count}쪽 중 ${state.actualPreviewPages.length}쪽만 표시`);
    if (result.note) notes.push(result.note);
    if (!notes.length) notes.push(`렌더된 ${state.actualPreviewPages.length}쪽`);
    els.previewNote.textContent = notes.join(" · ");
    openModal(els.previewModal, els.previewButton, els.previewClose);
    setActualPreviewPage(0);
  } catch (error) {
    toast(`미리보기 실패: ${error.message}`);
  } finally {
    els.previewButton.disabled = !state.basket.length;
    els.previewButton.textContent = buttonLabel;
  }
}

// --- AI 작업 도우미 ---------------------------------------------------------

async function loadAIStatus() {
  try {
    state.aiStatus = await api("/api/ai/status");
    renderAIStatus();
  } catch (error) {
    state.aiStatus = null;
    if (els.aiStatusText) els.aiStatusText.textContent = "AI 연결 실패";
    if (els.aiPanelStatus) els.aiPanelStatus.textContent = `상태를 불러오지 못했습니다: ${error.message}`;
  }
  syncAIActionState();
}

function renderAIStatus() {
  const status = state.aiStatus;
  if (!status) return;
  const settings = status.settings || {};
  const ocr = status.features?.ocr || {};
  const remoteReady = Boolean(settings.hasGeminiApiKey || settings.hasOpenAiApiKey);
  const localReady = Boolean(status.features?.mathAnalysis?.available || ocr.available);
  if (els.aiStatusText) els.aiStatusText.textContent = remoteReady ? "AI 연결됨" : localReady ? "로컬 AI 도구" : "AI 키 필요";
  if (els.aiStatusDot) {
    els.aiStatusDot.classList.toggle("ready", remoteReady);
    els.aiStatusDot.classList.toggle("partial", !remoteReady && localReady);
  }
  if (els.aiPanelStatus) {
    const ocrLabel = ocr.autoBackend && ocr.autoBackend !== "none" ? `OCR ${ocr.autoBackend}` : "OCR 미설정";
    els.aiPanelStatus.textContent = `문항·수식 점검은 로컬 실행 · ${ocrLabel} · 원격 기능은 실행 전 동의`;
  }
  if (els.layoutMathAi) {
    const mathReady = Boolean(status.features?.mathRecognition?.available);
    els.layoutMathAi.disabled = !mathReady;
    if (!mathReady) els.layoutMathAi.checked = false;
    els.layoutMathAi.closest("label")?.classList.toggle("disabled", !mathReady);
    els.layoutMathAi.closest("label")?.setAttribute("title", mathReady ? "PDF 수식 이미지를 Gemini로 인식합니다." : "Gemini API 키를 AI 설정에서 연결하면 사용할 수 있습니다.");
  }
  if (els.geminiKeyStatus) els.geminiKeyStatus.textContent = settings.hasGeminiApiKey ? `설정됨 (${settings.geminiApiKeyPreview || "보안 저장"})` : "설정되지 않음";
  if (els.openAiKeyStatus) els.openAiKeyStatus.textContent = settings.hasOpenAiApiKey ? `설정됨 (${settings.openAiApiKeyPreview || "보안 저장"})` : "설정되지 않음";
}

function syncAIActionState() {
  const problem = activeProblem();
  const hasImage = Boolean(problem?.image_urls?.length);
  const features = state.aiStatus?.features || {};
  if (els.aiReviewButton) els.aiReviewButton.disabled = !problem || state.aiBusy;
  if (els.aiMathButton) els.aiMathButton.disabled = !problem || state.aiBusy;
  if (els.aiOcrButton) els.aiOcrButton.disabled = !problem || !hasImage || !features.ocr?.available || state.aiBusy;
  if (els.aiReconstructButton) els.aiReconstructButton.disabled = !problem || !hasImage || !features.imageReconstruction?.available || state.aiBusy;
  const states = [
    [els.aiReviewButton, "문항 점검", !problem ? "문항을 먼저 선택하세요" : "문항 완결성과 정답·해설을 점검합니다"],
    [els.aiMathButton, "수식 분석", !problem ? "문항을 먼저 선택하세요" : "본문과 해설의 수식 구조를 분석합니다"],
    [els.aiOcrButton, "이미지 OCR", !problem ? "문항을 먼저 선택하세요" : !hasImage ? "첨부 이미지가 필요합니다" : !features.ocr?.available ? "사용 가능한 OCR 엔진이 없습니다" : "첫 번째 첨부 이미지를 인식합니다"],
    [els.aiReconstructButton, "그림 복원", !problem ? "문항을 먼저 선택하세요" : !hasImage ? "첨부 이미지가 필요합니다" : !features.imageReconstruction?.available ? "AI 연결이 필요합니다" : "첫 번째 첨부 이미지를 선명하게 복원합니다"],
  ];
  states.forEach(([button, label, reason]) => {
    if (!button) return;
    button.title = reason;
    button.setAttribute("aria-label", button.disabled && !state.aiBusy ? `${label} — ${reason}` : label);
  });
}

function setAIBusy(busy, message = "", action = "") {
  state.aiBusy = busy;
  state.aiAction = busy ? action : null;
  const actions = { review: els.aiReviewButton, math: els.aiMathButton, ocr: els.aiOcrButton, reconstruct: els.aiReconstructButton };
  Object.entries(actions).forEach(([name, button]) => {
    if (!button) return;
    const active = busy && name === action;
    button.classList.toggle("loading", active);
    button.toggleAttribute("aria-busy", active);
  });
  document.querySelector(".ai-assistant")?.toggleAttribute("aria-busy", busy);
  syncAIActionState();
  if (message && els.aiPanelStatus) els.aiPanelStatus.textContent = message;
}

function clearAIResult() {
  els.aiResult?.classList.add("hidden");
  if (els.aiResultContent) els.aiResultContent.replaceChildren();
}

function showAIResult(title, content) {
  if (!els.aiResult || !els.aiResultContent) return;
  els.aiResultContent.replaceChildren();
  const heading = document.createElement("strong");
  heading.textContent = title;
  els.aiResultContent.append(heading);
  if (content instanceof Node) els.aiResultContent.append(content);
  else {
    const text = document.createElement("p");
    text.textContent = String(content || "결과가 없습니다.");
    els.aiResultContent.append(text);
  }
  els.aiResult.classList.remove("hidden");
  window.requestAnimationFrame(() => els.aiResult.scrollIntoView({ block: "nearest" }));
}

async function reviewActiveProblem() {
  const problem = activeProblem();
  if (!problem) return;
  const requestProblemId = problem.id;
  setAIBusy(true, "문항의 완결성과 정답·해설을 점검하는 중…", "review");
  try {
    const draft = editorDraftProblem(problem);
    const result = await api("/api/ai/problem/review", {
      method: "POST",
      body: JSON.stringify({
        number: draft.number || "", subject: draft.subject || "", unit: draft.unit || "", tags: draft.tags || "",
        title: draft.title || "", stem: draft.stem || "", choices: draft.choices || [], answer: draft.answer || "", explanation: draft.explanation || "",
      }),
    });
    if (state.activeId !== requestProblemId) return toast("이전 문항의 AI 점검이 완료되었습니다.");
    const wrap = document.createElement("div");
    const summary = document.createElement("p");
    const score = document.createElement("span");
    score.className = "ai-score";
    score.textContent = String(result.score ?? 0);
    summary.append(score, document.createTextNode(result.summary?.text || "점검 완료"));
    wrap.append(summary);
    for (const finding of result.findings || []) {
      const item = document.createElement("div");
      item.className = `ai-finding ${finding.severity || "info"}`;
      const strong = document.createElement("strong");
      strong.textContent = finding.title || "점검 항목";
      const detail = document.createElement("span");
      detail.textContent = finding.detail || "";
      item.append(strong, detail);
      if (finding.suggestion) {
        const suggestion = document.createElement("small");
        suggestion.textContent = `제안: ${finding.suggestion}`;
        item.append(suggestion);
      }
      wrap.append(item);
    }
    showAIResult("문항 점검 결과", wrap);
  } catch (error) {
    toast(`문항 점검 실패: ${error.message}`);
  } finally {
    setAIBusy(false);
    renderAIStatus();
  }
}

async function analyzeActiveMath() {
  const problem = activeProblem();
  if (!problem) return;
  const requestProblemId = problem.id;
  const text = [els.editStem.value, els.editChoices.value, els.editExplanation.value].filter(Boolean).join("\n");
  if (!text.trim()) {
    toast("분석할 본문이나 선지를 입력하세요.");
    return;
  }
  setAIBusy(true, "수식 구조와 한컴 수식 변환 가능성을 분석하는 중…", "math");
  try {
    const result = await api("/api/ai/math/analyze", { method: "POST", body: JSON.stringify({ text }) });
    if (state.activeId !== requestProblemId) return toast("이전 문항의 수식 분석이 완료되었습니다.");
    const wrap = document.createElement("div");
    const summary = document.createElement("p");
    const mathSummary = result.summary || {};
    summary.textContent = `수식 후보 ${mathSummary.count ?? (result.spans || []).length}개${mathSummary.has_latex ? " · LaTeX 표기 있음" : ""}${mathSummary.has_symbolic ? " · 기호식 있음" : ""}`;
    const normalized = document.createElement("pre");
    normalized.textContent = result.normalizedText || text;
    wrap.append(summary, normalized);
    showAIResult("수식 분석 결과", wrap);
  } catch (error) {
    toast(`수식 분석 실패: ${error.message}`);
  } finally {
    setAIBusy(false);
    renderAIStatus();
  }
}

async function imageUrlToBase64(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error("첨부 이미지를 읽을 수 없습니다.");
  const blob = await response.blob();
  return fileToBase64(new File([blob], "problem-image", { type: blob.type || "image/png" }));
}

async function ocrActiveImage() {
  const problem = activeProblem();
  const imageUrl = problem?.image_urls?.[0];
  if (!imageUrl) return;
  const requestProblemId = problem.id;
  const backend = state.aiStatus?.features?.ocr?.autoBackend || "none";
  const remote = backend === "gemini";
  if (remote && !window.confirm("첨부 이미지 1장을 Gemini로 전송해 OCR을 실행할까요? 원본 문항은 자동으로 바뀌지 않습니다.")) return;
  setAIBusy(true, `${backend} OCR을 실행하는 중…`, "ocr");
  try {
    const result = await api("/api/ai/ocr", {
      method: "POST",
      body: JSON.stringify({ filename: "problem-image.png", dataBase64: await imageUrlToBase64(imageUrl), backend: "auto", allowRemote: remote }),
    });
    if (state.activeId !== requestProblemId) return toast("이전 문항의 OCR이 완료되었습니다.");
    const wrap = document.createElement("div");
    const meta = document.createElement("p");
    meta.textContent = `${result.backend} · 신뢰도 ${Math.round(Number(result.confidence || 0) * 100)}%`;
    const text = document.createElement("pre");
    text.textContent = result.normalizedText || result.text || "인식된 텍스트가 없습니다.";
    wrap.append(meta, text);
    if (result.normalizedText || result.text) {
      const apply = document.createElement("button");
      apply.type = "button";
      apply.textContent = "본문 끝에 추가";
      apply.addEventListener("click", () => {
        els.editStem.value = `${els.editStem.value.trim()}\n${result.normalizedText || result.text}`.trim();
        markDraftDirty();
        refreshEditorInspector();
        apply.textContent = "추가됨";
        apply.disabled = true;
        toast("OCR 결과를 본문에 추가했습니다. 저장 전에 검토하세요.");
      });
      wrap.append(apply);
    }
    showAIResult("이미지 OCR 결과", wrap);
  } catch (error) {
    toast(`OCR 실패: ${error.message}`);
  } finally {
    setAIBusy(false);
    renderAIStatus();
  }
}

async function reconstructActiveImage() {
  const problem = activeProblem();
  const imageUrl = problem?.image_urls?.[0];
  if (!imageUrl) return;
  const requestProblemId = problem.id;
  const providers = state.aiStatus?.features?.imageReconstruction?.providers || {};
  const provider = providers.gemini?.available ? "gemini" : providers.openai?.available ? "openai" : "";
  if (!provider) return;
  if (!window.confirm(`첨부 이미지 1장을 ${provider === "gemini" ? "Gemini" : "OpenAI"}로 전송해 선명한 문제 그림으로 재구성할까요? 결과를 검토한 뒤 적용할 수 있습니다.`)) return;
  setAIBusy(true, "문제 그림을 재구성하는 중…", "reconstruct");
  try {
    const result = await api("/api/ai/reconstruct", {
      method: "POST",
      body: JSON.stringify({ filename: "problem-image.png", dataBase64: await imageUrlToBase64(imageUrl), provider, allowRemote: true, transparentBackground: true, sharpen: true }),
    });
    if (state.activeId !== requestProblemId) return toast("이전 문항의 그림 복원이 완료되었습니다.");
    const wrap = document.createElement("div");
    const image = document.createElement("img");
    image.src = result.file?.url;
    image.alt = "AI로 재구성한 문제 그림";
    image.style.maxWidth = "100%";
    const apply = document.createElement("button");
    apply.type = "button";
    apply.textContent = "문항 이미지에 추가";
    apply.addEventListener("click", async () => {
      const paths = [...(problem.image_paths || []), result.file.path];
      try {
        await api(`/api/problems/${problem.id}`, { method: "PUT", body: JSON.stringify(editorPayload(problem, paths)) });
        await loadProblems();
        toast("복원 이미지를 문항에 추가했습니다.");
      } catch (error) {
        toast(`이미지 적용 실패: ${error.message}`);
      }
    });
    wrap.append(image, apply);
    showAIResult("그림 복원 결과", wrap);
  } catch (error) {
    toast(`그림 복원 실패: ${error.message}`);
  } finally {
    setAIBusy(false);
    renderAIStatus();
  }
}

function openAISettings() {
  renderAIStatus();
  openModal(els.aiSettingsModal, document.activeElement, els.geminiApiKey);
}

function closeAISettings() {
  closeModal(els.aiSettingsModal);
  if (els.geminiApiKey) els.geminiApiKey.value = "";
  if (els.openAiApiKey) els.openAiApiKey.value = "";
}

async function saveAISettings(event) {
  event.preventDefault();
  const payload = {};
  if (els.geminiApiKey.value.trim()) payload.geminiApiKey = els.geminiApiKey.value.trim();
  if (els.openAiApiKey.value.trim()) payload.openAiApiKey = els.openAiApiKey.value.trim();
  if (!Object.keys(payload).length) {
    toast("변경할 API 키를 입력하세요.");
    return;
  }
  try {
    await api("/api/ai/settings", { method: "PUT", body: JSON.stringify(payload) });
    await loadAIStatus();
    closeAISettings();
    toast("AI 연결 설정을 저장했습니다.");
  } catch (error) {
    toast(`AI 설정 저장 실패: ${error.message}`);
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
    : "HWP, HWPX, DOCX, PDF, 이미지, TXT";
}

const EDITOR_MATH_FIELD_IDS = new Set(["editStem", "editChoices", "editAnswer", "editExplanation"]);

function selectableSnippet(text, needle) {
  const index = text.indexOf(needle);
  return {
    text,
    selectionStart: index >= 0 ? index : text.length,
    selectionEnd: index >= 0 ? index + needle.length : text.length,
  };
}

function mathInsertion(snippet, selectedText = "") {
  const selected = String(selectedText || "");
  if (snippet === "x^2") {
    return selected ? { text: `${selected}^{2}` } : selectableSnippet("x^2", "x");
  }
  if (snippet === "x_{n}") {
    return selected ? { text: `${selected}_{n}` } : selectableSnippet("x_{n}", "x");
  }
  if (snippet === String.raw`\frac{a}{b}`) {
    return selected
      ? selectableSnippet(String.raw`\frac{${selected}}{b}`, "b")
      : selectableSnippet(String.raw`\frac{a}{b}`, "a");
  }
  if (snippet === String.raw`\sqrt{x}`) {
    return selected ? { text: String.raw`\sqrt{${selected}}` } : selectableSnippet(String.raw`\sqrt{x}`, "x");
  }
  if (snippet === String.raw`\overline{x}`) {
    return selected ? { text: String.raw`\overline{${selected}}` } : selectableSnippet(String.raw`\overline{x}`, "x");
  }
  if (snippet === String.raw`\vec{v}`) {
    return selected ? { text: String.raw`\vec{${selected}}` } : selectableSnippet(String.raw`\vec{v}`, "v");
  }
  if (snippet === String.raw`\sum_{k=1}^{n}`) {
    return selectableSnippet(snippet, "k=1");
  }
  if (snippet === String.raw`\int_{0}^{1} dx`) {
    return selectableSnippet(snippet, "0");
  }
  return { text: snippet };
}

function focusMathField(field) {
  if (!field) return;
  try {
    field.focus({ preventScroll: true });
  } catch {
    field.focus();
  }
}

function insertAtCursor(textarea, snippet) {
  if (!textarea || !snippet) return;
  const start = textarea.selectionStart ?? textarea.value.length;
  const end = textarea.selectionEnd ?? textarea.value.length;
  const selected = textarea.value.slice(start, end);
  const insertion = mathInsertion(snippet, selected);
  const before = textarea.value.slice(0, start);
  const prefix = before && !/[\s([{]$/.test(before) ? " " : "";
  textarea.setRangeText(prefix + insertion.text, start, end, "end");
  const selectionBase = start + prefix.length;
  const selectionStart = insertion.selectionStart;
  const selectionEnd = insertion.selectionEnd;
  if (
    typeof textarea.setSelectionRange === "function" &&
    Number.isInteger(selectionStart) &&
    Number.isInteger(selectionEnd) &&
    selectionEnd > selectionStart
  ) {
    textarea.setSelectionRange(selectionBase + selectionStart, selectionBase + selectionEnd);
  }
  focusMathField(textarea);
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

function handleMathInsert(event) {
  const button = event.currentTarget;
  const activeField = state.activeMathField;
  const useActiveEditorField = activeField && EDITOR_MATH_FIELD_IDS.has(activeField.id);
  const target = button.dataset.mathTarget === "manual"
    ? els.manualStem
    : (useActiveEditorField ? activeField : els.editStem);
  insertAtCursor(target, button.dataset.mathInsert || "");
}

function rememberMathField(event) {
  state.activeMathField = event.currentTarget;
}

function setInputMode(mode) {
  const activeMode = mode || "file";
  els.inputModeButtons.forEach((button) => {
    const active = button.dataset.inputMode === activeMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  els.inputModePanels.forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.inputPanel !== activeMode);
  });
}

function setSideMode(mode) {
  const activeMode = mode || "source";
  state.sideMode = activeMode;
  els.sideSwitchButtons.forEach((button) => {
    const active = button.dataset.sideMode === activeMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  els.sidePanes.forEach((pane) => {
    const active = pane.dataset.sidePane === activeMode;
    pane.classList.toggle("active", active);
    pane.classList.toggle("hidden", !active);
  });
  setWorkflowStep(activeMode === "library" ? 2 : 1);
  if (mobileWorkspaceActive()) setMobilePane("source");
}

async function safeLoadProblems() {
  try {
    if (!(await flushActiveDraft({ quiet: true }))) return;
    await loadProblems();
  } catch (error) {
    toast(`문제 목록을 불러오지 못했습니다: ${error.message}`);
  }
}

els.sideSwitchButtons.forEach((button) => {
  button.addEventListener("click", () => setSideMode(button.dataset.sideMode));
});
els.viewPresetButtons.forEach((button) => {
  button.addEventListener("click", () => setViewPreset(button.dataset.viewPreset));
});
els.workflowSteps.forEach((button) => {
  button.addEventListener("click", () => activateWorkflowStep(button.dataset.workflowStep));
});

els.inputModeButtons.forEach((button) => {
  button.addEventListener("click", () => setInputMode(button.dataset.inputMode));
});
els.fileInput.addEventListener("change", showSelectedFiles);
els.dropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    els.fileInput.click();
  }
});
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
els.importButton.addEventListener("click", () => importFiles({ quick: false }));
els.quickImportButton.addEventListener("click", () => importFiles({ quick: true }));
els.layoutExportButton.addEventListener("click", exportPdfLayoutFiles);
els.collectButton.addEventListener("click", () => collectFromUrl({ quick: false }));
els.quickCollectButton.addEventListener("click", () => collectFromUrl({ quick: true }));
els.collectUrl.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    collectFromUrl({ quick: false });
  }
});
els.manualButton.addEventListener("click", () => addManualProblem({ quick: false }));
els.quickManualButton.addEventListener("click", () => addManualProblem({ quick: true }));
els.attachButton.addEventListener("click", () => els.attachInput.click());
els.attachInput.addEventListener("change", attachImages);
els.mathInsertButtons.forEach((button) => button.addEventListener("click", handleMathInsert));
[
  els.manualStem,
  els.editStem,
  els.editChoices,
  els.editAnswer,
  els.editExplanation,
].filter(Boolean).forEach((field) => {
  field.addEventListener("focus", rememberMathField);
  field.addEventListener("click", rememberMathField);
  field.addEventListener("keyup", rememberMathField);
});
els.editStem.addEventListener("input", refreshEditorInspector);
els.editChoices.addEventListener("input", refreshEditorInspector);
els.editAnswer.addEventListener("input", refreshEditorInspector);
els.editExplanation.addEventListener("input", refreshEditorInspector);
[els.editNumber, els.editTitle, els.editSubject, els.editUnit, els.editTags, els.editStem, els.editChoices, els.editAnswer, els.editSource, els.editExplanation]
  .filter(Boolean)
  .forEach((field) => field.addEventListener("input", markDraftDirty));
els.editorForm.addEventListener("submit", saveActive);
els.deleteButton.addEventListener("click", deleteActive);
els.exportButton.addEventListener("click", exportSelected);
els.previewButton.addEventListener("click", previewExport);
els.previewClose.addEventListener("click", () => closeModal(els.previewModal));
els.previewModal.addEventListener("click", (event) => {
  if (event.target === els.previewModal) closeModal(els.previewModal);
});
els.actualPreviewPrev?.addEventListener("click", () => setActualPreviewPage(state.actualPreviewPageIndex - 1, { focusStage: true }));
els.actualPreviewNext?.addEventListener("click", () => setActualPreviewPage(state.actualPreviewPageIndex + 1, { focusStage: true }));
els.actualPreviewZoomOut?.addEventListener("click", () => setActualPreviewZoom(state.actualPreviewZoom - ACTUAL_PREVIEW_ZOOM_STEP));
els.actualPreviewZoomIn?.addEventListener("click", () => setActualPreviewZoom(state.actualPreviewZoom + ACTUAL_PREVIEW_ZOOM_STEP));
els.actualPreviewZoomLabel?.addEventListener("click", () => setActualPreviewZoom(1, { center: true }));
els.actualPreviewFit?.addEventListener("click", fitActualPreview);
els.orderEditorButton?.addEventListener("click", openOrderEditor);
els.orderEditorClose?.addEventListener("click", cancelOrderEditor);
els.orderEditorCancel?.addEventListener("click", cancelOrderEditor);
els.orderEditorApply?.addEventListener("click", applyOrderEditor);
els.orderEditorModal?.addEventListener("click", (event) => {
  if (event.target === els.orderEditorModal) cancelOrderEditor();
});
els.recognitionLayerButton?.addEventListener("click", openRecognitionLayer);
els.recognitionLayerClose?.addEventListener("click", () => closeModal(els.recognitionLayerModal));
els.recognitionLayerDone?.addEventListener("click", () => closeModal(els.recognitionLayerModal));
els.recognitionLayerModal?.addEventListener("click", (event) => {
  if (event.target === els.recognitionLayerModal) closeModal(els.recognitionLayerModal);
});
els.aiStatusButton?.addEventListener("click", openAISettings);
els.aiSettingsButton?.addEventListener("click", openAISettings);
els.aiSettingsClose?.addEventListener("click", closeAISettings);
els.aiSettingsModal?.addEventListener("click", (event) => {
  if (event.target === els.aiSettingsModal) closeAISettings();
});
els.aiSettingsForm?.addEventListener("submit", saveAISettings);
els.aiReviewButton?.addEventListener("click", reviewActiveProblem);
els.aiMathButton?.addEventListener("click", analyzeActiveMath);
els.aiOcrButton?.addEventListener("click", ocrActiveImage);
els.aiReconstructButton?.addEventListener("click", reconstructActiveImage);
els.aiResultClose?.addEventListener("click", clearAIResult);
els.shortcutHelpButton?.addEventListener("click", openShortcutHelp);
els.shortcutHelpClose?.addEventListener("click", closeShortcutHelp);
els.shortcutHelpModal?.addEventListener("click", (event) => {
  if (event.target === els.shortcutHelpModal) closeShortcutHelp();
});
els.collapseButtons.forEach((button) => button.addEventListener("click", () => togglePanel(button.dataset.collapsePane, { focusButton: true })));
[els.sourceDivider, els.previewDivider].filter(Boolean).forEach((divider) => {
  divider.addEventListener("pointerdown", beginPanelResize);
  divider.addEventListener("keydown", handleDividerKeydown);
  divider.addEventListener("dblclick", () => {
    resizePanel(divider.dataset.divider, divider.dataset.divider === "source" ? 280 : 400, { announce: true });
  });
});
els.zoomOutButton?.addEventListener("click", () => setPreviewZoom(state.previewZoom - PREVIEW_ZOOM_STEP));
els.zoomInButton?.addEventListener("click", () => setPreviewZoom(state.previewZoom + PREVIEW_ZOOM_STEP));
els.zoomLabel?.addEventListener("click", () => resetPreviewZoom());
els.zoomFitButton?.addEventListener("click", () => fitPreviewToStage());
els.previewPanButton?.addEventListener("click", () => setPanMode(!state.panMode));
els.paperStage?.addEventListener("pointerdown", beginCanvasPan);
els.paperStage?.addEventListener("pointermove", moveCanvasPan);
els.paperStage?.addEventListener("pointerup", endCanvasPan);
els.paperStage?.addEventListener("pointercancel", endCanvasPan);
els.paperStage?.addEventListener("dblclick", (event) => {
  if (!interactiveCanvasTarget(event.target)) fitPreviewToStage();
});
els.paperStage?.addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key) || event.altKey || event.ctrlKey || event.metaKey) return;
  event.preventDefault();
  const distance = event.shiftKey ? 120 : 48;
  if (event.key === "ArrowLeft") els.paperStage.scrollLeft -= distance;
  if (event.key === "ArrowRight") els.paperStage.scrollLeft += distance;
  if (event.key === "ArrowUp") els.paperStage.scrollTop -= distance;
  if (event.key === "ArrowDown") els.paperStage.scrollTop += distance;
});
document.addEventListener("keydown", handleGlobalKeydown);
document.addEventListener("keyup", handleGlobalKeyup);
document.addEventListener("pointermove", movePanelResize);
document.addEventListener("pointerup", endPanelResize);
document.addEventListener("pointercancel", endPanelResize);
window.addEventListener("blur", () => {
  endPanelResize();
  state.spacePanning = false;
  state.panPointer = null;
  els.paperStage?.classList.remove("pan-ready", "panning");
});
window.addEventListener("resize", debounce(() => {
  normalizePanelLayout();
  applyWorkspaceLayout();
  if (!els.previewModal?.classList.contains("hidden") && state.actualPreviewFit) fitActualPreview();
}, 120));
els.exportTemplate.addEventListener("change", () => {
  state.nativeMathTouched = false;
  syncExportTitleToTemplate();
  syncExportOptions({ resetNativeMath: true });
  syncTemplatePreview();
});
els.exportTitle.addEventListener("input", syncPaperPreviewMeta);
els.exportFormat.addEventListener("change", () => syncExportOptions());
if (els.exportNativeMath) {
  els.exportNativeMath.addEventListener("change", () => {
    state.nativeMathTouched = true;
  });
}
els.searchInput.addEventListener("input", debounce(safeLoadProblems));
els.sourceFilter.addEventListener("change", safeLoadProblems);
els.selectAllButton.addEventListener("click", () => {
  for (const problem of state.problems) addToBasket(problem);
  renderList();
  renderBasket();
});
els.clearSelectionButton.addEventListener("click", () => {
  clearBasket();
});
els.basketClearButton.addEventListener("click", clearBasket);
els.basketList.addEventListener("dragover", (event) => {
  if (Array.from(event.dataTransfer.types || []).includes("application/x-problem-id")) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    els.basketList.classList.add("board-drag-over");
  }
});
els.basketList.addEventListener("dragleave", (event) => {
  if (!event.currentTarget.contains(event.relatedTarget)) {
    els.basketList.classList.remove("board-drag-over");
  }
});
document.addEventListener("dragend", () => {
  els.basketList.classList.remove("board-drag-over");
});
els.basketList.addEventListener("drop", (event) => {
  els.basketList.classList.remove("board-drag-over");
  const problemId = Number(event.dataTransfer.getData("application/x-problem-id"));
  if (Number.isNaN(problemId) || problemId <= 0) return;
  event.preventDefault();
  const dropped = state.problems.find((item) => item.id === problemId);
  if (!dropped) return;
  insertBasketProblemAt(dropped, state.basket.length);
  state.activeId = dropped.id;
  renderList();
  renderBasket();
  renderEditor();
});

(async function init() {
  state.basket = restoreBasket();
  restoreWorkspaceLayout();
  setMobilePane(state.mobilePane);
  applyWorkspaceLayout();
  setSideMode(state.sideMode);
  await loadExportTemplates();
  syncExportTitleToTemplate();
  syncPaperPreviewMeta();
  syncExportOptions({ resetNativeMath: true });
  await loadProblems();
  await loadExportHistory();
  await loadAIStatus();
  window.requestAnimationFrame(() => {
    state.paperBaseWidth = Math.max(400, els.paperStage.clientWidth - 32);
    updatePaperCanvasSize();
  });
})().catch((error) => {
  els.statusText.textContent = "서버 연결 실패";
  toast(error.message);
});
