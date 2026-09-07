#!/usr/bin/env node
"use strict";

// Execute the actual frontend functions with controlled DOM/network boundaries.
// No browser, server, user database or generated documents are modified.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const source = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");
function fn(name) {
  const match = new RegExp(`^(?:async )?function ${name}\\(`, "m").exec(source);
  assert(match, `Function ${name} must exist`);
  return source.slice(match.index, source.indexOf("\n}", match.index) + 2);
}
function element() {
  const classes = new Set();
  return {
    disabled: false, textContent: "", dataset: {}, files: [], children: [], attributes: {},
    classList: { add: (...xs) => xs.forEach(x => classes.add(x)), remove: (...xs) => xs.forEach(x => classes.delete(x)), contains: x => classes.has(x), toggle: (x, value) => value ? classes.add(x) : classes.delete(x) },
    setAttribute(k, v) { this.attributes[k] = v; }, removeAttribute(k) { delete this.attributes[k]; },
    append(...xs) { this.children.push(...xs); }, replaceChildren(...xs) { this.children = xs; },
    addEventListener(k, cb) { this[k] = cb; }, focus() { this.focused = true; }, click() { this.clicked = (this.clicked || 0) + 1; }, remove() {},
  };
}
function harness(names) {
  const els = Object.fromEntries(["simpleFileInput", "simpleStudioButton", "simpleFileRemove", "simpleDropzone", "simpleConvertButton", "simpleCancelButton", "simpleQualityNote", "simpleResultActions", "simpleHistoryList", "simpleMathAi", "simpleMathAiOption", "simpleSelectedFile", "simpleFileName", "simpleFileMeta", "simpleConversionStatus", "simpleConversionStatusText", "fileInput", "fileName", "layoutExportButton", "importButton", "quickImportButton"].map(k => [k, element()]));
  const state = { simpleConversionBusy: false, simpleCancelRequested: false, simpleFailure: "", simpleNotices: [], exports: [], recognitionRequestId: 0, session: { authenticated: false }, workspaceStage: "input" };
  const body = element(); body.classList.add("simple-converter-mode");
  const context = vm.createContext({
    state, els, document: { body, activeElement: null, createElement: element, querySelector: () => null },
    URL: { revokeObjectURL() {} }, AbortController, console,
    MAX_CLIENT_UPLOAD_BYTES: 64 * 1024 * 1024, DEFAULT_EXPORT_TITLE: "새 시험지", EXT_KINDS: { pdf: "pdf", txt: "text" },
    DataTransfer: class { constructor() { this.files = []; this.items = { add: f => this.files.push(f) }; } },
    setButtonBusy() {}, validateUploadSizes: () => true, showSelectedFiles() {}, toast() {},
    setImportButtonsDisabled: (buttons, disabled) => buttons.forEach(b => b.disabled = disabled),
    setImportProgress() {}, loadExportHistory: async () => true, fileToBase64: async () => "dGVzdA==",
    visibleModals: () => [], editableTarget: () => false,
    renderWorkspaceStage() {},
    recognizeSimpleFile: async (file) => {
      state.recognizedFile = file;
      state.recognizedProblems = [{ id: 1 }];
      state.workspaceStage = "ready";
      els.simpleMathAiOption.classList.toggle("hidden", !/\.pdf$/i.test(file.name));
      return true;
    },
  });
  vm.runInContext(names.map(fn).join("\n"), context);
  return context;
}
const helpers = ["friendlyErrorMessage", "responseError", "isPdfFile", "simpleFileExtension", "formatSimpleFileSize", "assignSingleFile", "setSimpleConversionStatus", "setSimpleQualityNote", "clearSimpleResult", "simpleQualityMessages", "showSimpleQuality", "simpleArtifactLink", "appendSimpleReview", "appendSimpleArtifactActions", "showSimpleResult", "setSimpleFile", "runSimpleConversion"];

(async () => {
  const c = harness(helpers);
  const error = await c.responseError({ status: 409, text: async () => JSON.stringify({ detail: { message: "삭제된 문항입니다", code: "missing_problems", missing_ids: [7] } }) });
  assert.equal(error.message, "삭제된 문항입니다");
  assert.equal(error.status, 409);
  assert.equal(error.detail.code, "missing_problems");

  const warnings = c.simpleQualityMessages({ quality: { objective_score: 80, objective_score_target: 98, full_page_raster_fallback: true, meets_editable_text_target: false }, fidelity: { available: false } });
  assert(warnings.some(x => x.includes("시각 일치 미검증")));
  assert(warnings.some(x => x.includes("목표 미달")));
  assert(warnings.some(x => x.includes("편집이 제한")));
  assert(!c.simpleQualityMessages({ quality: { objective_score: null } }).some(x => x.includes("0.0점")));

  c.els.simpleQualityNote.textContent = "이전 파일의 점수";
  c.setSimpleFile({ name: "B.txt", size: 10 }, { syncInput: true });
  assert.equal(c.els.simpleQualityNote.textContent, "");
  assert(c.els.simpleMathAiOption.classList.contains("hidden"));
  c.state.simpleConversionBusy = true;
  c.setSimpleFile({ name: "C.pdf", size: 10 }, { syncInput: true });
  assert.equal(c.els.simpleFileName.textContent, "B.txt", "busy must preserve the selected file");
  c.state.simpleConversionBusy = false;

  c.setSimpleFile({ name: "A.pdf", type: "application/pdf", size: 12 }, { syncInput: true });
  let release;
  c.exportPdfLayoutFiles = async () => new Promise(resolve => release = resolve);
  const running = c.runSimpleConversion();
  assert(c.els.simpleFileInput.disabled, "actual input must lock while running");
  assert(c.els.simpleStudioButton.disabled, "mode cannot swap the running input bridge");
  c.state.simpleFailure = "암호화된 PDF를 열 수 없습니다";
  release(false);
  await running;
  assert.equal(c.els.simpleConversionStatusText.textContent, "암호화된 PDF를 열 수 없습니다");
  assert(!c.els.simpleFileInput.disabled);

  c.exportPdfLayoutFiles = async () => { c.state.simpleCancelRequested = true; return false; };
  await c.runSimpleConversion();
  assert(c.els.simpleConversionStatusText.textContent.includes("서버에서 생성이 계속될 수"));

  c.exportPdfLayoutFiles = async ({ collect }) => {
    collect.push({ export: { name: "A.hwpx", url: "/exports/A.hwpx" }, source: { copy: { url: "/exports/A.pdf" } }, run: { report: { url: "/exports/report.json" } }, quality: { objective_score: 90, objective_score_target: 98 } });
    return true;
  };
  await c.runSimpleConversion();
  assert(c.els.simpleConversionStatusText.textContent.startsWith("A.pdf 생성 완료"));
  assert.equal(c.els.simpleResultActions.children[0].href, "/exports/A.hwpx");
  const review = c.els.simpleResultActions.children[2];
  assert.equal(review.children[0].textContent, "검수 내용");
  assert.equal(review.children[2].href, "/exports/report.json");
  assert.equal(review.children[2].textContent, "상세 기록(JSON)");
  assert(review.children[1].children.some(x => x.textContent === "한글에서 확인 필요"));
  const archiveReview = element();
  c.appendSimpleReview(archiveReview, {
    scope: { original_page_count: 40, selected_page_count: 20, includes_entire_source: false },
    summary: { output_page_count: 22, output_problem_count: 30 },
    quality: { editable_text_coverage_ratio: 0.92 },
  });
  const archiveValues = archiveReview.children[0].children[1].children.map(x => x.textContent);
  assert(archiveValues.includes("30개"));
  assert(archiveValues.includes("40쪽 중 20쪽 변환"));
  assert(archiveValues.includes("22쪽"));
  assert(archiveValues.includes("92.0%"));

  const keys = harness(["handleGlobalKeydown"]);
  let prevented = 0;
  keys.handleGlobalKeydown({ key: "o", ctrlKey: true, preventDefault: () => prevented++ });
  assert.equal(keys.els.simpleFileInput.clicked, 1);
  assert.equal(keys.els.fileInput.clicked, undefined);
  keys.handleGlobalKeydown({ key: "?", preventDefault() {} }); // No hidden studio modal call.
  keys.state.simpleConversionBusy = true;
  keys.handleGlobalKeydown({ key: "o", ctrlKey: true, preventDefault() {} });
  assert.equal(keys.els.simpleFileInput.clicked, 1);
  assert.equal(prevented, 1);

  const history = harness(["renderSimpleHistory"]);
  history.state.exportsError = "연결 실패";
  let retried = 0;
  history.loadExportHistory = async () => retried++;
  history.renderSimpleHistory();
  const retry = history.els.simpleHistoryList.children[1];
  await retry.click();
  assert.equal(retried, 1);

  const request = harness(["friendlyErrorMessage", "isPdfFile", "exportPdfLayoutFiles"]);
  request.state.simpleConversionBusy = true;
  request.els.fileInput.files = [{ name: "broken.pdf", size: 4 }];
  request.api = async () => { throw new Error("손상된 PDF입니다"); };
  assert.equal(await request.exportPdfLayoutFiles(), false);
  assert.equal(request.state.simpleFailure, "손상된 PDF입니다");
  console.log("Conversion UI behavior OK: errors, file locking, mode keys, quality, recovery, artifact links");
})().catch(error => { console.error(error); process.exitCode = 1; });
