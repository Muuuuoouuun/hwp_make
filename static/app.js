const DEFAULT_EXPORT_TITLE = "새 시험지";

const state = {
  problems: [],
  basket: [], // 내보내기 순서를 유지하는 [{id, label}] 목록
  activeId: null,
  templates: [],
  exports: [], // 내보내기 기록 [{name, size, modified, format, url}]
  lastDefaultTitle: DEFAULT_EXPORT_TITLE,
  sideMode: "source",
};

const els = {
  statusText: document.querySelector("#statusText"),
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
  basketList: document.querySelector("#basketList"),
  basketBadge: document.querySelector("#basketBadge"),
  historyList: document.querySelector("#historyList"),
  historyBadge: document.querySelector("#historyBadge"),
  previewButton: document.querySelector("#previewButton"),
  previewModal: document.querySelector("#previewModal"),
  previewPages: document.querySelector("#previewPages"),
  previewNote: document.querySelector("#previewNote"),
  previewClose: document.querySelector("#previewClose"),
  exportTitle: document.querySelector("#exportTitle"),
  paperTitlePreview: document.querySelector("#paperTitlePreview"),
  paperCountPreview: document.querySelector("#paperCountPreview"),
  exportTemplate: document.querySelector("#exportTemplate"),
  exportFormat: document.querySelector("#exportFormat"),
  exportAnswerSheet: document.querySelector("#exportAnswerSheet"),
  exportNativeMath: document.querySelector("#exportNativeMath"),
  nativeMathLabel: document.querySelector("#nativeMathLabel"),
  exportButton: document.querySelector("#exportButton"),
  emptyEditor: document.querySelector("#emptyEditor"),
  editorForm: document.querySelector("#editorForm"),
  contentBadges: document.querySelector("#contentBadges"),
  stemPreview: document.querySelector("#stemPreview"),
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

async function loadProblems() {
  const params = new URLSearchParams();
  if (els.searchInput.value.trim()) params.set("q", els.searchInput.value.trim());
  if (els.sourceFilter.value) params.set("source_type", els.sourceFilter.value);
  const data = await api(`/api/problems?${params.toString()}`);
  state.problems = data.items;
  els.countBadge.textContent = `${state.problems.length}개`;
  if (els.libraryProblemHint) els.libraryProblemHint.textContent = `검색 결과 ${state.problems.length}개`;
  els.statusText.textContent = `가져온 문제 ${state.problems.length}개`;
  if (els.flowProblemCount) els.flowProblemCount.textContent = `가져온 문제 ${state.problems.length}개`;
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
  state.lastDefaultTitle = exportDefaultTitle(active);
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

function syncExportOptions() {
  const isHwpx = els.exportFormat.value === "hwpx";
  const template = currentExportTemplate();
  if (els.exportNativeMath) {
    els.exportNativeMath.disabled = !isHwpx;
    els.exportNativeMath.checked = isHwpx && Boolean(template?.native_math_default);
  }
  if (els.nativeMathLabel) {
    els.nativeMathLabel.classList.toggle("disabled", !isHwpx);
  }
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
const LATEX_LEFT_RIGHT_PATTERN = String.raw`\\left[\s\S]{1,1200}?\\right(?:\\[{}]|\S)?`;
const LATEX_WRAPPED_LEFT_RIGHT_PATTERN = String.raw`${LATEX_WRAPPED_OPERAND}\s*${LATEX_LEFT_RIGHT_PATTERN}`;
const LATEX_WRAPPED_EXPRESSION_PATTERN = String.raw`(?:${MATH_OPERAND}|${LATEX_WRAPPED_OPERAND})\s*${MATH_OPERATOR}\s*(?:${MATH_OPERAND}|${LATEX_WRAPPED_OPERAND})(?:\s*${MATH_OPERATOR}\s*(?:${MATH_OPERAND}|${LATEX_WRAPPED_OPERAND}))*`;
const LATEX_FRACTION_PATTERN = String.raw`\\(?:frac|dfrac|tfrac)\{${LATEX_GROUP_CONTENT}\}\{${LATEX_GROUP_CONTENT}\}`;
const LATEX_BINOM_PATTERN = String.raw`\\(?:binom|dbinom|tbinom)\{${LATEX_GROUP_CONTENT}\}\{${LATEX_GROUP_CONTENT}\}`;
const LATEX_SQRT_PATTERN = String.raw`\\sqrt(?:\[[^\]\n]{0,80}\])?\{${LATEX_GROUP_CONTENT}\}`;
const LATEX_SPACE_COMMAND_PATTERN = String.raw`(?:\\[,;:! ]|\\(?:quad|qquad|enspace|thinspace|medspace|thickspace)(?![A-Za-z]))`;
const ABSOLUTE_VALUE_PATTERN = String.raw`\|(?=[^|$\n]*[a-zA-Z0-9${GREEK_RANGE}])[^|$\n]{1,160}\|`;
const LATEX_NARY_BODY_PATTERN = String.raw`(?:${LATEX_FRACTION_PATTERN}|${LATEX_SQRT_PATTERN}|\([^()\n]{1,120}\)|\[[^\[\]\n]{1,120}\]|${IDENTIFIER}(?:\([^()\n]{0,120}\))?(?:[_^](?:\{[^{}\n]{1,80}\}|[a-zA-Z0-9]+))*(?:d${IDENTIFIER})?|\d+(?:\.\d+)?)`;
const LATEX_NARY_PATTERN = String.raw`\\(?:sum|prod|int|iint)(?![A-Za-z])(?:\s*[_^](?:\{[^{}\n]{0,120}\}|[a-zA-Z0-9]+)){0,2}(?:\s+${LATEX_NARY_BODY_PATTERN})?(?:\s*(?:${LATEX_SPACE_COMMAND_PATTERN}\s*)?d${IDENTIFIER})?`;
const LATEX_FUNCTION_PATTERN = String.raw`\\(?:lim|log|ln|sin|cos|tan|sec|csc|cot)(?![A-Za-z])(?:\s*[_^](?:\{[^{}\n]{0,120}\}|[a-zA-Z0-9]+)){0,2}(?:\s*${LATEX_NARY_BODY_PATTERN})?(?:\s*\{${LATEX_GROUP_CONTENT}\})?`;
const LATEX_FUNCTION_EXPRESSION_PATTERN = String.raw`\\(?:lim|log|ln)(?![A-Za-z])(?:\s*[_^](?:\{[^{}\n]{0,120}\}|[a-zA-Z0-9]+)){0,2}(?:\s*${LATEX_NARY_BODY_PATTERN})?(?:\s*\{${LATEX_GROUP_CONTENT}\})?(?:\s*${MATH_OPERATOR}\s*(?:${LATEX_NARY_BODY_PATTERN}|${MATH_OPERAND}))+`;
const RADICAL_PLACEHOLDER_PATTERN = String.raw`[□▢]*`;
const RADICAL_BODY_PATTERN = String.raw`(?:${IDENTIFIER}|\([^()\n]{1,120}\)|\d+(?:\.\d+)?)`;
const UNICODE_RADICAL_PATTERN = String.raw`√\s*${RADICAL_PLACEHOLDER_PATTERN}\s*${RADICAL_BODY_PATTERN}`;
const HANCOM_RADICAL_PATTERN = String.raw`(?<![a-zA-Z0-9${GREEK_RANGE}])sqrt\s*${RADICAL_PLACEHOLDER_PATTERN}\s*${RADICAL_BODY_PATTERN}`;
const UNICODE_NARY_PATTERN = String.raw`[∑∏∫](?:[_^](?:\{[^{}\n]{0,120}\}|[a-zA-Z0-9]+)){0,2}(?:\s*${LATEX_NARY_BODY_PATTERN})?`;
const LATEX_COMMAND_PATTERN = String.raw`\\(?:frac|dfrac|tfrac|sqrt|sum|prod|int|iint|lim|log|ln|sin|cos|tan|sec|csc|cot|alpha|beta|gamma|delta|epsilon|varepsilon|zeta|eta|theta|vartheta|iota|kappa|lambda|mu|nu|xi|pi|varpi|rho|varrho|sigma|varsigma|tau|upsilon|phi|varphi|chi|psi|omega|Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Upsilon|Phi|Psi|Omega|nabla|le|leq|ge|geq|ne|neq|approx|cdot|times|div|pm|mp|infty|overline|underline|overrightarrow|widehat|hat|tilde|dot|ddot|check|bar|vec|angle|triangle|parallel|perp|because|therefore|binom|dbinom|tbinom|mathrm|mathbb|mathbf|text|operatorname|in|notin|cup|cap|subset|supset|subseteq|supseteq|circ|mid|vert|lvert|rvert|lVert|rVert|cdots|ldots)(?![A-Za-z])(?:\s*(?:[_^](?:\{[^{}\n]{0,120}\}|[a-zA-Z0-9]+)|\{[^{}\n]{0,120}\}|\[[^\]\n]{0,80}\])){0,4}`;
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

async function handleImportedProblems(created, { quick = false } = {}) {
  if (!created.length) {
    toast("새로 가져온 문제가 없습니다.");
    return;
  }
  state.activeId = created[0].id;
  addManyToBasket(created, { replace: quick });
  renderList();
  renderBasket();
  renderEditor();
  setSideMode("library");
  if (quick) {
    await exportSelected(created.map((problem) => problem.id));
  }
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
  if (els.previewButton) els.previewButton.disabled = !count;
  if (els.exportButton) els.exportButton.disabled = !count;
  els.basketList.innerHTML = "";
  if (!state.basket.length) {
    const empty = document.createElement("div");
    empty.className = "basket-empty";
    empty.textContent = "가운데 목록에서 담기 버튼을 누르면 시험지에 들어갈 문제가 여기에 쌓입니다.";
    els.basketList.append(empty);
    return;
  }

  const guide = document.createElement("div");
  guide.className = "layout-guide";
  guide.innerHTML = "<span>왼쪽 열</span><span>오른쪽 열</span>";
  els.basketList.append(guide);

  state.basket.forEach((entry, index) => {
    const problem = state.problems.find((item) => item.id === entry.id);
    if (problem) entry.label = problemLabel(problem);

    const row = document.createElement("div");
    row.className = `basket-row ${index % 2 === 0 ? "left-slot" : "right-slot"}`;
    row.draggable = true;
    row.dataset.index = index;

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
    position.textContent = `${Math.floor(index / 2) + 1}행 · ${index % 2 === 0 ? "왼쪽" : "오른쪽"}`;

    body.append(label, snippet, position);
    label.addEventListener("click", () => {
      state.activeId = entry.id;
      renderList();
      renderEditor();
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
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "history-row";

    const link = document.createElement("a");
    link.className = "history-link";
    link.href = item.url;
    link.download = item.name;
    link.title = item.name;

    const name = document.createElement("span");
    name.className = "history-name";
    name.textContent = item.name;

    const meta = document.createElement("span");
    meta.className = "history-meta";
    meta.innerHTML = `<b class="source-pill">${(item.format || "").toUpperCase()}</b> ${humanSize(item.size)} · ${formatExportTime(item.modified)}`;

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
  try {
    await api(`/api/exports/${encodeURIComponent(name)}`, { method: "DELETE" });
    await loadExportHistory();
    toast("기록을 삭제했습니다.");
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
    title.innerHTML = `<span></span><b class="source-pill">${sourceLabel(problem.source_type)}</b>`;
    title.querySelector("span").textContent = problemLabel(problem);

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
    row.addEventListener("click", () => {
      state.activeId = problem.id;
      renderList();
      renderEditor();
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
  return state.problems.find((item) => item.id === state.activeId) || null;
}

function renderEditor() {
  const problem = activeProblem();
  if (!problem) {
    els.emptyEditor.classList.remove("hidden");
    els.editorForm.classList.add("hidden");
    renderContentInspector(null);
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

async function importFiles({ quick = false } = {}) {
  const files = Array.from(els.fileInput.files || []);
  if (!files.length) {
    toast("파일을 선택하세요.");
    return;
  }
  setImportButtonsDisabled([els.importButton, els.quickImportButton], true);
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
    await loadProblems();
    await handleImportedProblems(created, { quick });
    toast(
      quick
        ? `${total}개 문항으로 시험지 파일을 만들었습니다.${notices.length ? ` ${notices[0]}` : ""}`
        : `${total}개 문항을 가져와 시험지 구성에 담았습니다.${notices.length ? ` ${notices[0]}` : ""}`
    );
    els.fileInput.value = "";
    els.fileName.textContent = "HWP, HWPX, DOCX, PDF, 이미지, TXT";
  } catch (error) {
    toast(`가져오기 실패: ${error.message}`);
  } finally {
    setImportButtonsDisabled([els.importButton, els.quickImportButton], false);
  }
}

async function collectFromUrl({ quick = false } = {}) {
  const url = els.collectUrl.value.trim();
  if (!url) {
    toast("수집할 URL을 입력하세요.");
    return;
  }
  setImportButtonsDisabled([els.collectButton, els.quickCollectButton], true);
  els.collectButton.textContent = "가져오는 중...";
  if (els.quickCollectButton) els.quickCollectButton.textContent = "만드는 중...";
  try {
    const result = await api("/api/collect", {
      method: "POST",
      body: JSON.stringify({ url, metadata: metadata() }),
    });
    await loadProblems();
    await handleImportedProblems(result.created || [], { quick });
    toast(result.notices?.[0] || `${result.created?.length || 0}개 문항을 가져왔습니다.`);
    els.collectUrl.value = "";
  } catch (error) {
    toast(`수집 실패: ${error.message}`);
  } finally {
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
    await loadProblems();
    await handleImportedProblems(created, { quick });
    toast(
      quick
        ? `${created.length}개 문항으로 시험지 파일을 만들었습니다.${result.notices?.[1] ? ` ${result.notices[1]}` : ""}`
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
  const problem = activeProblem();
  if (!problem) return;
  try {
    await api(`/api/problems/${problem.id}`, {
      method: "PUT",
      body: JSON.stringify(editorPayload(problem, problem.image_paths || [])),
    });
    await loadProblems();
    toast("저장했습니다.");
  } catch (error) {
    toast(`저장 실패: ${error.message}`);
  }
}

async function deleteActive() {
  const problem = activeProblem();
  if (!problem) return;
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
    return;
  }
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
  } catch (error) {
    toast(`내보내기 실패: ${error.message}`);
  } finally {
    els.exportButton.disabled = !state.basket.length;
  }
}

async function previewExport() {
  const ids = state.basket.map((entry) => entry.id);
  if (!ids.length) {
    toast("먼저 시험지에 넣을 문제를 담으세요.");
    return;
  }
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
    els.previewButton.disabled = !state.basket.length;
    els.previewButton.textContent = "시험지 미리보기";
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

function insertAtCursor(textarea, snippet) {
  if (!textarea || !snippet) return;
  const start = textarea.selectionStart ?? textarea.value.length;
  const end = textarea.selectionEnd ?? textarea.value.length;
  const before = textarea.value.slice(0, start);
  const prefix = before && !/[\s([{]$/.test(before) ? " " : "";
  textarea.setRangeText(prefix + snippet, start, end, "end");
  textarea.focus();
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

function handleMathInsert(event) {
  const button = event.currentTarget;
  const target = button.dataset.mathTarget === "manual" ? els.manualStem : els.editStem;
  insertAtCursor(target, button.dataset.mathInsert || "");
}

function setInputMode(mode) {
  const activeMode = mode || "file";
  els.inputModeButtons.forEach((button) => {
    const active = button.dataset.inputMode === activeMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
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
    button.setAttribute("aria-pressed", String(active));
  });
  els.sidePanes.forEach((pane) => {
    const active = pane.dataset.sidePane === activeMode;
    pane.classList.toggle("active", active);
    pane.classList.toggle("hidden", !active);
  });
}

els.sideSwitchButtons.forEach((button) => {
  button.addEventListener("click", () => setSideMode(button.dataset.sideMode));
});

els.inputModeButtons.forEach((button) => {
  button.addEventListener("click", () => setInputMode(button.dataset.inputMode));
});
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
els.importButton.addEventListener("click", () => importFiles({ quick: false }));
els.quickImportButton.addEventListener("click", () => importFiles({ quick: true }));
els.collectButton.addEventListener("click", () => collectFromUrl({ quick: false }));
els.quickCollectButton.addEventListener("click", () => collectFromUrl({ quick: true }));
els.collectUrl.addEventListener("keydown", (event) => {
  if (event.key === "Enter") collectFromUrl({ quick: false });
});
els.manualButton.addEventListener("click", () => addManualProblem({ quick: false }));
els.quickManualButton.addEventListener("click", () => addManualProblem({ quick: true }));
els.attachButton.addEventListener("click", () => els.attachInput.click());
els.attachInput.addEventListener("change", attachImages);
els.mathInsertButtons.forEach((button) => button.addEventListener("click", handleMathInsert));
els.editStem.addEventListener("input", refreshEditorInspector);
els.editChoices.addEventListener("input", refreshEditorInspector);
els.editorForm.addEventListener("submit", saveActive);
els.deleteButton.addEventListener("click", deleteActive);
els.exportButton.addEventListener("click", exportSelected);
els.previewButton.addEventListener("click", previewExport);
els.previewClose.addEventListener("click", () => els.previewModal.classList.add("hidden"));
els.previewModal.addEventListener("click", (event) => {
  if (event.target === els.previewModal) els.previewModal.classList.add("hidden");
});
els.exportTemplate.addEventListener("change", () => {
  syncExportTitleToTemplate();
  syncExportOptions();
});
els.exportTitle.addEventListener("input", syncPaperPreviewMeta);
els.exportFormat.addEventListener("change", syncExportOptions);
els.searchInput.addEventListener("input", debounce(loadProblems));
els.sourceFilter.addEventListener("change", loadProblems);
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
  if (event.currentTarget === event.target) els.basketList.classList.remove("board-drag-over");
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
  setSideMode(state.sideMode);
  await loadExportTemplates();
  syncExportTitleToTemplate();
  syncPaperPreviewMeta();
  syncExportOptions();
  await loadProblems();
  await loadExportHistory();
})().catch((error) => {
  els.statusText.textContent = "서버 연결 실패";
  toast(error.message);
});
