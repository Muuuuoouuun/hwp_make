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
  // 2026-10-03 S단계: PDF 는 선택 시 인식하지 않고, 폴백·문항 편집 때만 recognizeSimpleFile 을 부른다.
  // 스텁은 호출 기록(recognizeCalls)과 다음 인식 결과(nextRecognized)·실패(recognizeFailure)를 제어한다.
  const recognizeCalls = [];
  const context = vm.createContext({
    state, els, document: { body, activeElement: null, createElement: element, querySelector: () => null },
    recognizeCalls, nextRecognized: null, recognizeFailure: null, loadAIStatus: async () => ({}),
    URL: { revokeObjectURL() {} }, AbortController, console,
    MAX_CLIENT_UPLOAD_BYTES: 64 * 1024 * 1024, DEFAULT_EXPORT_TITLE: "새 시험지", EXT_KINDS: { pdf: "pdf", txt: "text" },
    SIMPLE_EXPORT_TEMPLATE: /^const SIMPLE_EXPORT_TEMPLATE = "([^"]+)";$/m.exec(source)?.[1],
    DataTransfer: class { constructor() { this.files = []; this.items = { add: f => this.files.push(f) }; } },
    setButtonBusy() {}, validateUploadSizes: () => true, showSelectedFiles() {}, toast() {},
    setImportButtonsDisabled: (buttons, disabled) => buttons.forEach(b => b.disabled = disabled),
    setImportProgress() {}, loadExportHistory: async () => true, fileToBase64: async () => "dGVzdA==",
    visibleModals: () => [], editableTarget: () => false,
    renderWorkspaceStage() {},
    recognizeSimpleFile: async (file, options = {}) => {
      recognizeCalls.push({ file, options });
      if (context.recognizeFailure) {
        if (options.inline) state.simpleFailure = context.recognizeFailure;
        return false;
      }
      state.recognizedFile = file;
      state.recognizedProblems = context.nextRecognized || [{ id: 1 }];
      if (options.inline) return true;
      state.workspaceStage = "ready";
      els.simpleMathAiOption.classList.toggle("hidden", !/\.pdf$/i.test(file.name));
      return true;
    },
  });
  vm.runInContext(names.map(fn).join("\n"), context);
  return context;
}
const helpers = ["friendlyErrorMessage", "responseError", "isPdfFile", "simpleFileExtension", "formatSimpleFileSize", "assignSingleFile", "setSimpleConversionStatus", "setSimpleQualityNote", "clearSimpleResult", "conversionReview", "reviewHeadline", "simpleReviewNotice", "simpleQualityMessages", "showSimpleQuality", "simpleArtifactLink", "appendSimpleReview", "appendSimpleArtifactActions", "showSimpleResult", "setSimpleFile", "runSimpleConversion", "layoutFailureReason", "simpleLayoutFallbackEligible", "recognizedProblemsImageOnly", "simpleFallbackNotice"];

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

  c.recognizeCalls.length = 0;
  c.setSimpleFile({ name: "A.pdf", type: "application/pdf", size: 12 }, { syncInput: true });
  // PDF 는 선택 즉시 변환 준비 상태가 되고 /api/import(인식)를 먼저 돌리지 않는다.
  assert.equal(c.recognizeCalls.length, 0, "selecting a PDF must not run recognition");
  assert.equal(c.state.workspaceStage, "ready");
  assert.equal(c.els.simpleConversionStatusText.textContent, "A.pdf · 바로 변환할 수 있습니다");
  assert.equal(c.els.simpleConversionStatus.dataset.tone, "ready");
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
  // 2026-10-03 계약 변경: 문항 단위 결함은 422 거부 대신 파일 + review 로 온다.
  // 결과 카드 맨 위에 확인 필요 문항 안내가 오고, 다운로드 링크는 그 다음, 상세는 접힌다.
  const flaggedReview = { ok: false, flag_count: 2, headline: "확인 필요 문항 2개: 23번, 28번 (수식·문단)",
    message: "문항 2개는 수식·문단 복원이 불완전할 수 있습니다. 한글에서 23번, 28번 문항을 원본과 비교해 확인하세요.",
    flagged_questions: [{ id: "v1:q23", label: "23번", summary: "23번: 수식 구조가 원본과 다를 수 있습니다" },
      { id: "v1:q28", label: "28번", summary: "28번: 문단이 줄마다 끊겼을 수 있습니다" }], document_issues: [] };
  c.exportPdfLayoutFiles = async ({ collect }) => {
    collect.push({ export: { name: "B.hwpx", url: "/exports/B.hwpx" }, review: flaggedReview, quality: { objective_score: 90, objective_score_target: 98, review: flaggedReview } });
    return true;
  };
  await c.runSimpleConversion();
  const alert = c.els.simpleResultActions.children[0];
  assert.equal(alert.className, "simple-review-alert", "review notice must be the first item of the result card");
  assert.equal(alert.children[0].textContent, flaggedReview.headline);
  assert.equal(alert.children[1].textContent, flaggedReview.message);
  assert.equal(alert.children[2].children[0].textContent, "문항별 확인 내용");
  assert.deepEqual(alert.children[2].children[1].children.map(x => x.textContent), flaggedReview.flagged_questions.map(x => x.summary));
  assert.equal(c.els.simpleResultActions.children[1].href, "/exports/B.hwpx", "download stays available with the review");
  assert(c.simpleQualityMessages({ review: flaggedReview, quality: {} }).includes("확인 필요 문항 2개"));
  assert(c.simpleQualityMessages({ quality: { review: { ok: false, flag_count: 0, document_issues: [{ summary: "문항 번호" }] } } }).includes("문서 일부 확인 필요"));
  assert.equal(c.reviewHeadline({ ok: false, flagged_questions: [{ label: "3번" }] }), "확인 필요 문항 1개: 3번");
  assert.equal(c.conversionReview({ review: { ok: true, flag_count: 0 } }), null);
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

  const request = harness(["friendlyErrorMessage", "layoutFailureReason", "isPdfFile", "exportPdfLayoutFiles"]);
  request.state.simpleConversionBusy = true;
  request.els.fileInput.files = [{ name: "broken.pdf", size: 4 }];
  request.api = async () => { throw new Error("손상된 PDF입니다"); };
  assert.equal(await request.exportPdfLayoutFiles(), false);
  assert.equal(request.state.simpleFailure, "손상된 PDF입니다");

  // 실패 사유 정리: 업로드 경로는 공백(한글 파일명·사용자 폴더 '홍 길동')을 포함할 수 있어도 남지 않아야 한다(3단계 재검증 지적).
  const reasonOf = (message) => request.layoutFailureReason(new Error(message));
  const generic = "PDF 레이아웃 변환 실패 · 원본의 문항 배치를 분석하지 못했습니다.";
  const noEditable = "PDF 레이아웃 변환 실패: structured PDF recognition found no editable problems: ";
  for (const path of [
    "C:\\Projects\\hwp_make\\data\\uploads\\20261003_1_scanned_10.pdf",
    "C:\\Projects\\hwp_make\\data\\uploads\\20261003_1_3월 모의고사 스캔.pdf",
    "C:\\Users\\홍 길동\\AppData\\Local\\HWPMake\\uploads\\20261003_1_scan.pdf",
    "C:/Users/홍 길동/uploads/시험 1.pdf",
    "\\\\server\\share\\시험 자료\\1학기.pdf",
  ]) {
    const reason = reasonOf(`${noEditable}${path}`);
    assert.equal(reason, generic, `path must be dropped entirely: ${reason}`);
  }
  assert.equal(reasonOf("PDF 레이아웃 변환 실패: [Errno 2] No such file: 'C:\\\\a b\\\\x.pdf'"), generic);
  assert.equal(reasonOf("PDF 레이아웃 변환 실패: http://localhost/x 참고"), "PDF 레이아웃 변환 실패: http://localhost/x 참고", "URL is not a drive path");
  assert.equal(reasonOf("PDF 레이아웃 변환 실패: 3쪽 표를 읽지 못했습니다"), "PDF 레이아웃 변환 실패: 3쪽 표를 읽지 못했습니다");
  assert.equal(reasonOf("편집할 수 있는 문항을 찾지 못했습니다."), "편집할 수 있는 문항을 찾지 못했습니다.");

  // 간단 모드 PDF 폴백(2026-10-03 3단계): 원본 배치 복원이 4xx로 거절되면 같은 파일의 인식 문항으로
  // 재구성형 HWPX를 만든다. 실제 exportPdfLayoutFiles·responseError 를 거쳐 서버 오류가 전달되는지까지 본다.
  const fb = harness([...helpers, "setConversionStatus", "exportPdfLayoutFiles"]);
  // 2026-10-03 4단계: 간단 변환 전용 양식 'simple'(원번호·원문자 선지·끝 정답표)로 바뀌었다.
  assert.equal(fb.SIMPLE_EXPORT_TEMPLATE, "simple", "fallback template constant must be readable from app.js");
  const serverError = (status, detail) => fb.responseError({ status, statusText: "err", text: async () => JSON.stringify({ detail }) });
  const groupingDetail = "PDF 레이아웃 변환 실패: native question grouping does not match source inventory: C:\\Projects\\data\\uploads\\S.pdf";
  let exportCalls = [];
  const startPdf = (problems) => {
    fb.setSimpleFile({ name: "S.pdf", type: "application/pdf", size: 12 }, { syncInput: true });
    assert.equal(fb.state.recognizedFile, null, "PDF selection leaves recognition for the fallback");
    fb.nextRecognized = problems;
    fb.recognizeCalls.length = 0;
    exportCalls = [];
  };
  const textProblems = [{ id: 1, stem: "1. 다음 중 옳은 것은?", choices: ["가", "나"] }, { id: 2, stem: "2. 윗글의 내용과 일치하는 것은?" }];
  fb.exportSelected = async (ids, overrides, { signal }) => {
    exportCalls.push({ ids, overrides, owned: fb.state.importController?.signal === signal, busy: fb.state.simpleConversionBusy,
      cancelShown: !fb.els.simpleCancelButton.classList.contains("hidden"), cancelEnabled: !fb.els.simpleCancelButton.disabled });
    fb.state.simpleLastArtifact = { name: "S.hwpx", url: "blob:S" };
    return true;
  };

  // ① 4xx → 폴백 → 성공 안내(서버 사유는 내부 영문·경로 없이 한국어로).
  startPdf(textProblems);
  fb.api = async () => { throw await serverError(400, groupingDetail); };
  await fb.runSimpleConversion();
  assert.equal(exportCalls.length, 1, "4xx layout failure must fall back to the recognized problems");
  assert.equal(fb.recognizeCalls.length, 1, "fallback recognizes the PDF only after the 4xx");
  assert.equal(fb.recognizeCalls[0].file.name, "S.pdf");
  assert.equal(fb.recognizeCalls[0].options.inline, true, "fallback recognition must run inline (cancellable, no stage change)");
  assert.deepEqual(exportCalls[0].ids, [1, 2]);
  assert.equal(exportCalls[0].overrides.templateKey, fb.SIMPLE_EXPORT_TEMPLATE);
  assert.equal(exportCalls[0].overrides.format, "hwpx");
  assert(exportCalls[0].owned, "fallback export must own the cancellable importController");
  assert(exportCalls[0].busy && exportCalls[0].cancelShown && exportCalls[0].cancelEnabled, "fallback keeps busy state and the cancel button");
  assert.equal(fb.state.importController, null);
  assert(fb.els.simpleConversionStatusText.textContent.includes("재구성형 HWPX 생성 완료"));
  const fallbackCard = fb.els.simpleResultActions.children[0];
  assert(fallbackCard.className.includes("simple-fallback-alert"), "fallback notice must lead the result card");
  const fallbackLines = fallbackCard.children.map(x => x.textContent);
  assert.equal(fallbackLines[0], "원본 배치 복원에 실패해 인식한 문항으로 재구성형 HWPX를 만들었습니다.");
  assert.equal(fallbackLines[1], "실패 사유: PDF 레이아웃 변환 실패 · 원본의 문항 배치를 분석하지 못했습니다.");
  assert.equal(fallbackLines[2], "글자 편집은 가능하지만 원본 배치는 다릅니다.");
  assert(!fallbackLines.join(" ").match(/native|[A-Za-z]:\\/), "teacher-facing reason must not leak internal text or paths");
  assert.equal(fb.els.simpleResultActions.children[1].href, "blob:S", "download uses the existing exportSelected artifact");

  // ② 스캔 PDF(인식 결과가 이미지 1문항) → 폴백 결과도 이미지뿐이라는 안내.
  startPdf([{ id: 12, stem: "", choices: [], image_paths: ["uploads/page1.png"] }]);
  const scanMessage = "편집할 수 있는 문항이나 문장을 찾지 못해 편집형 문서를 제공할 수 없습니다. 글자를 선택할 수 있는 PDF인지 확인해 주세요.";
  fb.api = async () => { throw await serverError(422, { message: scanMessage, fatal: "no_editable_content" }); };
  await fb.runSimpleConversion();
  assert.equal(exportCalls.length, 1);
  const scanLines = fb.els.simpleResultActions.children[0].children.map(x => x.textContent);
  assert.equal(scanLines[1], `실패 사유: ${scanMessage}`);
  assert(scanLines[2].includes("글자 편집은 할 수 없습니다"), "image-only fallback must say text is not editable");
  assert(!scanLines[2].includes("글자 편집은 가능"));

  // ③ 취소 → 폴백 없음(AbortError, 그리고 취소 요청 뒤에 도착한 4xx 모두).
  startPdf(textProblems);
  fb.api = async () => { fb.state.simpleCancelRequested = true; const abort = new Error("The operation was aborted."); abort.name = "AbortError"; throw abort; };
  await fb.runSimpleConversion();
  assert.equal(exportCalls.length, 0, "cancel must not trigger the fallback");
  assert.equal(fb.recognizeCalls.length, 0, "cancel must not start recognition either");
  assert(fb.els.simpleConversionStatusText.textContent.includes("서버에서 생성이 계속될 수"));
  startPdf(textProblems);
  fb.api = async () => { fb.state.simpleCancelRequested = true; throw await serverError(400, groupingDetail); };
  await fb.runSimpleConversion();
  assert.equal(exportCalls.length, 0, "a 4xx that arrives after cancel must not trigger the fallback");

  // 4xx 가 아니거나(5xx·연결 실패) 다른 파일의 인식 결과면 폴백하지 않는다.
  startPdf(textProblems);
  fb.api = async () => { throw await serverError(500, "PDF 레이아웃 HWPX 생성 중 오류가 발생했습니다"); };
  await fb.runSimpleConversion();
  assert.equal(exportCalls.length, 0, "5xx must not trigger the fallback");
  assert.equal(fb.recognizeCalls.length, 0, "5xx must not start recognition");
  startPdf(textProblems);
  fb.state.recognizedFile = { name: "other.pdf" };
  fb.state.recognizedProblems = [{ id: 77, stem: "다른 파일" }];
  fb.api = async () => { throw await serverError(400, groupingDetail); };
  await fb.runSimpleConversion();
  assert.equal(fb.recognizeCalls.length, 1, "another file's recognition must not be reused; the current PDF is recognized");
  assert.equal(exportCalls.length, 1);
  assert.deepEqual(exportCalls[0].ids, [1, 2], "recognized problems of another file must not be exported");

  // 폴백 인식 자체가 실패하면 두 사유를 함께 보여 준다.
  startPdf(textProblems);
  fb.recognizeFailure = "편집 가능한 문항을 찾지 못했습니다.";
  fb.api = async () => { throw await serverError(400, groupingDetail); };
  await fb.runSimpleConversion();
  fb.recognizeFailure = null;
  assert.equal(exportCalls.length, 0, "failed recognition must not export");
  const recognitionFailed = fb.els.simpleConversionStatusText.textContent;
  assert(recognitionFailed.includes("원본 배치 복원 실패: PDF 레이아웃 변환 실패 · 원본의 문항 배치를 분석하지 못했습니다."), recognitionFailed);
  assert(recognitionFailed.includes("인식한 문항으로 다시 만들기도 실패: 편집 가능한 문항을 찾지 못했습니다."), recognitionFailed);
  assert.equal(fb.els.simpleConversionStatus.dataset.tone, "error");
  assert.equal(fb.state.importController, null);

  // 폴백 실패 → 두 사유를 함께 보여 준다(exportSelected 는 실패를 setConversionStatus 로 남긴다).
  startPdf(textProblems);
  fb.api = async () => { throw await serverError(400, groupingDetail); };
  fb.exportSelected = async () => { fb.setConversionStatus("HWPX 변환 실패 · 삭제된 문항입니다", "error"); return false; };
  await fb.runSimpleConversion();
  const bothReasons = fb.els.simpleConversionStatusText.textContent;
  assert(bothReasons.includes("원본 배치 복원 실패: PDF 레이아웃 변환 실패 · 원본의 문항 배치를 분석하지 못했습니다."), bothReasons);
  assert(bothReasons.includes("인식한 문항으로 다시 만들기도 실패: HWPX 변환 실패 · 삭제된 문항입니다"), bothReasons);
  assert.equal(fb.els.simpleConversionStatus.dataset.tone, "error");
  assert.equal(fb.state.importController, null);
  console.log("Conversion UI behavior OK: errors, file locking, mode keys, quality, recovery, artifact links, PDF direct conversion + on-demand recognition fallback");
})().catch(error => { console.error(error); process.exitCode = 1; });
