#!/usr/bin/env node
"use strict";

// 2026-10-03 5b단계 회귀 핀: 실제 static/app.js 함수를 DOM·네트워크 없이 실행한다.
// (1) 422 입력 검증 목록·{code,message,hint} 를 한국어로 보이고, 0바이트·확장자 없는 파일은 업로드 전에 막는다.
// (2) Content-Disposition 의 소문자 filename*=utf-8'' 와 '%'가 든 이름에서 'URI malformed' 없이 파일명을 얻는다.
// (3) 0문항 인식이면 서버 notices[0] 을 상태 문구로, 결과 카드에는 서버 notices 를 접기로 보인다.
// (4) review 가 있으면 위 품질 한 줄에 review 요약·점수를 되풀이하지 않는다(점수는 '검수 내용' 접기 안).
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const source = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8").replace(/\r\n/g, "\n");
function fn(name) {
  const match = new RegExp(`^(?:async )?function ${name}[(]`, "m").exec(source);
  assert(match, `Function ${name} must exist`);
  return source.slice(match.index, source.indexOf("\n}\n", match.index) + 3);
}
function element() {
  const classes = new Set();
  return {
    disabled: false, textContent: "", className: "", dataset: {}, files: [], children: [], attributes: {},
    classList: { add: (...xs) => xs.forEach(x => classes.add(x)), remove: (...xs) => xs.forEach(x => classes.delete(x)), contains: x => classes.has(x), toggle: (x, on) => on ? classes.add(x) : classes.delete(x) },
    setAttribute(k, v) { this.attributes[k] = v; }, removeAttribute(k) { delete this.attributes[k]; },
    append(...xs) { this.children.push(...xs); }, replaceChildren(...xs) { this.children = xs; },
    addEventListener() {}, focus() {}, click() {}, remove() {},
  };
}
function harness(names, extra = {}) {
  const els = new Proxy({}, { get: (obj, key) => obj[key] ??= element() });
  const toasts = [];
  const state = { simpleConversionBusy: false, simpleNotices: [], recognizedNotices: [], recognizedProblems: [], recognizedFile: null,
    recognitionRequestId: 0, recognitionController: null, selectedFile: null, workspaceStage: "input", session: { authenticated: false } };
  const context = vm.createContext({
    state, els, toasts, console, AbortController,
    document: { body: element(), createElement: element },
    URL: { revokeObjectURL() {} },
    MAX_CLIENT_UPLOAD_BYTES: 64 * 1024 * 1024,
    EXT_KINDS: { pdf: "pdf", txt: "text", hwpx: "hwpx" },
    toast: (message) => toasts.push(message),
    renderWorkspaceStage() {}, loadAIStatus: async () => {}, fileToBase64: async () => "dGVzdA==",
    ...extra,
  });
  vm.runInContext(names.map(fn).join("\n"), context);
  return context;
}

(async () => {
  // ---- (1) 오류 표시 -------------------------------------------------------
  const e = harness(["friendlyErrorMessage", "responseError"]);
  const fromBody = async (status, body) => (await e.responseError({ status, statusText: "x", text: async () => JSON.stringify(body) })).message;
  // 5a 이후 서버 422: detail 은 검증 목록, 최상위에 {code,message,hint}. 안내(hint)까지 보인다.
  assert.equal(await fromBody(422, { detail: [{ type: "string_too_short", loc: ["body", "data_base64"] }], code: "empty", message: "빈 파일이라 변환할 수 없습니다.", hint: "내용이 들어 있는 파일을 다시 선택해 주세요." }),
    "빈 파일이라 변환할 수 없습니다. 내용이 들어 있는 파일을 다시 선택해 주세요.");
  // detail 객체 {code,message,hint}(400·422 엔진 거부)
  assert.equal(await fromBody(400, { detail: { code: "damaged", message: "손상된 HWPX 패키지입니다.", hint: "원본 파일을 다시 내려받거나 다시 저장한 뒤 올려 주세요." } }),
    "손상된 HWPX 패키지입니다. 원본 파일을 다시 내려받거나 다시 저장한 뒤 올려 주세요.");
  assert.equal(await fromBody(409, { detail: { message: "삭제된 문항입니다", code: "missing_problems" } }), "삭제된 문항입니다", "hint 가 없으면 message 그대로");
  assert.equal(await fromBody(400, { detail: "번호 오류" }), "번호 오류");
  // 서버가 {code,message} 없이 pydantic 목록만 줄 때(감사 C1-09 원문): 영문 JSON 대신 한국어 요약.
  const pydantic = { detail: [{ type: "string_too_short", loc: ["body", "data_base64"], msg: "String should have at least 1 character", input: "" }] };
  const summary = await fromBody(422, pydantic);
  assert.equal(summary, "입력값이 올바르지 않습니다: 파일이 비어 있습니다");
  assert(!/detail|string_too_short|String should/.test(summary), summary);
  assert.equal(e.friendlyErrorMessage(JSON.stringify({ detail: [{ type: "literal_error", loc: ["body", "kind"] }, { type: "missing", loc: ["body", "filename"] }] })),
    "입력값이 올바르지 않습니다: 지원하지 않는 파일 형식입니다, 파일 이름이 빠졌습니다");
  assert.equal(e.friendlyErrorMessage(JSON.stringify({ detail: [{ type: "json_invalid", loc: ["body", 3] }] })), "입력값이 올바르지 않습니다: 요청 형식 오류");
  assert.equal(e.friendlyErrorMessage(JSON.stringify({ detail: [] })), "입력값이 올바르지 않습니다: 요청 형식 오류");
  assert.equal(e.friendlyErrorMessage(new Error("Failed to fetch")), "서버에 연결하지 못했습니다. 연결 상태를 확인한 뒤 다시 시도하세요.");
  assert.equal(e.friendlyErrorMessage("평범한 오류"), "평범한 오류");

  // 0바이트·확장자 없는 파일은 업로드 전에 막는다(서버 요청 없음).
  const requests = [];
  const s = harness(["isPdfFile", "simpleFileExtension", "formatSimpleFileSize", "setSimpleConversionStatus", "setSimpleQualityNote", "clearSimpleResult", "setSimpleFile", "recognizeSimpleFile", "validateUploadSizes"], {
    api: async (url) => { requests.push(url); return { created: [], notices: [] }; },
  });
  for (const [file, expected] of [
    [{ name: "빈 시험지.pdf", size: 0, type: "application/pdf" }, "빈 파일(0바이트)이라 변환할 수 없습니다. 내용이 들어 있는 파일을 다시 선택해 주세요."],
    [{ name: "빈.txt", size: 0 }, "빈 파일(0바이트)이라 변환할 수 없습니다. 내용이 들어 있는 파일을 다시 선택해 주세요."],
    [{ name: "pdf", size: 100 }, "파일 이름에 확장자(.pdf, .hwp 등)가 없어 형식을 알 수 없습니다. 확장자가 붙은 원본 파일을 선택해 주세요."],
    [{ name: "시험지", size: 100 }, "파일 이름에 확장자(.pdf, .hwp 등)가 없어 형식을 알 수 없습니다. 확장자가 붙은 원본 파일을 선택해 주세요."],
    [{ name: "시험지.xyz", size: 100 }, "지원하지 않는 파일 형식입니다."],
  ]) {
    await s.setSimpleFile(file);
    assert.equal(s.state.workspaceStage, "error", file.name);
    assert.equal(s.els.simpleConversionStatusText.textContent, expected, file.name);
    assert.equal(s.els.simpleConversionStatus.dataset.tone, "error");
  }
  assert.equal(requests.length, 0, "blocked files must not reach /api/import");
  assert.equal(s.validateUploadSizes([{ name: "a.txt", size: 0 }]), false, "studio/PDF paths share the empty-file block");
  assert(s.toasts.at(-1).startsWith("a.txt: 빈 파일(0바이트)"), s.toasts.at(-1));
  assert.equal(s.validateUploadSizes([{ name: "a.txt", size: 5 }]), true);
  // 빈 PDF 에는 막다른 변환 버튼을 띄우지 않는다(2026-10-03 S단계: PDF 는 인식 없이 바로 변환하므로 pdfConvertible 이 버튼 조건).
  const stage = fn("renderWorkspaceStage");
  assert(/pdfConvertible = hasFile && isPdfFile\(state\.selectedFile\)\s*&& Number\(state\.selectedFile\.size\) > 0 && state\.selectedFile\.size <= MAX_CLIENT_UPLOAD_BYTES/.test(stage), "empty PDF must not offer the conversion button");
  assert(/els\.simpleConvertButton\.disabled = !convertible \|\| state\.simpleConversionBusy/.test(stage), "PDF conversion button must follow the convertible flag");

  // ---- (2) 다운로드 파일명 -------------------------------------------------
  const d = harness(["downloadFilename"]);
  // 서버 실측(격리 서버 8906, '정답률 30% 문항 100%.txt' → /api/export): Starlette 는 소문자 utf-8'' 로 보낸다.
  const measured = "attachment; filename*=utf-8''20261003_170618_%EC%A0%95%EB%8B%B5%EB%A5%A0%2030_%20%EB%AC%B8%ED%95%AD%20100_.hwpx";
  const fallback = "정답률 30% 문항 100%.hwpx";
  // 수정 전 코드(대소문자 구분 정규식 + fallback 을 decodeURIComponent)는 이 입력에서 URIError 를 던졌다.
  const before = (disposition) => {
    const match = disposition.match(/filename\*=UTF-8''([^;]+)|filename="?([^"]+)"?/);
    return decodeURIComponent(match?.[1] || match?.[2] || fallback);
  };
  assert.throws(() => before(measured), /URI malformed/, "pre-fix behaviour reproduces the audit failure");
  assert.equal(d.downloadFilename(measured, fallback), "20261003_170618_정답률 30_ 문항 100_.hwpx");
  assert.equal(d.downloadFilename("attachment; filename*=UTF-8''%ED%95%9C%EA%B8%80.hwpx", fallback), "한글.hwpx");
  assert.equal(d.downloadFilename("attachment; FILENAME=\"plain name.docx\"", fallback), "plain name.docx");
  assert.equal(d.downloadFilename("attachment; filename=plain.hwpx", fallback), "plain.hwpx");
  // 잘못된 퍼센트 인코딩: 예외 없이 일반 filename= 또는 대체 이름.
  assert.equal(d.downloadFilename("attachment; filename*=utf-8''100%25%ZZ.hwpx; filename=\"safe.hwpx\"", fallback), "safe.hwpx");
  assert.equal(d.downloadFilename("attachment; filename*=utf-8''bad%E0%A4%A.hwpx", fallback), fallback);
  assert.equal(d.downloadFilename("", fallback), fallback, "missing header uses the fallback as-is (no decoding of '%')");
  assert.equal(d.downloadFilename(null, fallback), fallback);
  const exportSelected = fn("exportSelected");
  assert(exportSelected.includes("downloadFilename(disposition,"), "exportSelected must use the tolerant filename parser");
  assert(!/decodeURIComponent\(match/.test(exportSelected), "inline decode of the header must be gone");

  // ---- (3) 0문항 notices · 결과 카드 notices 접기 ----------------------------
  const r = harness(["isPdfFile", "simpleFileExtension", "formatSimpleFileSize", "setSimpleConversionStatus", "setSimpleQualityNote", "clearSimpleResult", "setSimpleFile", "recognizeSimpleFile", "friendlyErrorMessage"], {
    // 서버 실측: 공백뿐인 TXT → 200 {created: [], notices: ['텍스트에서 문항을 찾지 못했습니다.']}
    api: async () => ({ ok: true, created: [], notices: ["텍스트에서 문항을 찾지 못했습니다."] }),
  });
  assert.equal(await r.setSimpleFile({ name: "blank.txt", size: 6 }), false);
  assert.equal(r.state.workspaceStage, "error");
  assert.equal(r.els.simpleConversionStatusText.textContent, "텍스트에서 문항을 찾지 못했습니다. 파일 내용을 확인하고 다시 인식해 주세요.");
  r.api = async () => ({ ok: true, created: [] });
  await r.setSimpleFile({ name: "blank2.txt", size: 6 });
  assert.equal(r.els.simpleConversionStatusText.textContent, "편집 가능한 문항을 찾지 못했습니다. 파일 내용을 확인하고 다시 인식해 주세요.", "no notices keeps the generic message");
  // 0개 새로 + 기존 문항 재사용(재가져오기)은 정상 인식이다.
  r.api = async () => ({ created: [], existing: [{ id: 4 }], ordered_ids: [4], notices: ["새로 가져온 문제가 없습니다."] });
  assert.equal(await r.setSimpleFile({ name: "again.txt", size: 6 }), true);
  assert.equal(r.state.workspaceStage, "ready");
  assert.deepEqual([...r.state.recognizedNotices], ["새로 가져온 문제가 없습니다."]);

  const card = harness(["setSimpleQualityNote", "conversionReview", "reviewHeadline", "simpleReviewNotice", "simpleQualityMessages", "showSimpleQuality", "simpleArtifactLink", "appendSimpleReview", "appendSimpleArtifactActions", "showSimpleResult", "simpleFallbackNotice"]);
  const flatten = (node) => [node.textContent, ...(node.children || []).flatMap(flatten)].filter(Boolean);
  const noticeFold = () => card.els.simpleResultActions.children.find((x) => String(x.className).includes("simple-notice-details"));
  // 비PDF(인식 문항으로 만든 결과): 인식 단계 notices 를 접기로.
  card.state.recognizedNotices = ["2개 문항을 텍스트에서 가져왔습니다.", "그림 1개는 표 안에 있어 가져오지 못했습니다."];
  card.state.simpleLastArtifact = { name: "A.hwpx", url: "blob:A" };
  card.showSimpleResult([]);
  let fold = noticeFold();
  assert(fold, "server notices must be shown as a fold on the result card");
  assert.equal(fold.children[0].textContent, "안내·주의사항 2개");
  assert.deepEqual(fold.children[1].children.map((x) => x.textContent), card.state.recognizedNotices);
  assert.equal(card.els.simpleResultActions.children[0].href, "blob:A", "download link stays first");
  // PDF 결과: 응답 notices 를 쓰되 review 안내와 같은 문장은 빼고, 품질 줄에는 review 요약·점수를 되풀이하지 않는다.
  const review = { ok: false, flag_count: 2, headline: "확인 필요 문항 2개: 23번, 28번", message: "문항 2개는 수식 복원이 불완전할 수 있습니다.", flagged_questions: [{ label: "23번" }, { label: "28번" }] };
  const pdfResult = { export: { name: "B.hwpx", url: "/files/B.hwpx" }, review, run: { report: { url: "/files/r.json" } },
    quality: { objective_score: 52.4, objective_score_target: 98, visual_sync_ratio: 0.97 }, fidelity: { available: true },
    notices: [review.message, "편집 가능한 수식 61개를 생성했습니다.", "원본 배치 품질 기준을 충족하지 못했습니다. 결과를 확인해 주세요."] };
  card.showSimpleQuality([pdfResult]);
  const line = card.els.simpleQualityNote.textContent;
  assert(!/자동 점검|목표 미달|확인 필요 문항/.test(line), `review must lead; score/review summary must not repeat on the quality line: ${line}`);
  card.showSimpleResult([pdfResult]);
  const children = card.els.simpleResultActions.children;
  assert.equal(children[0].className, "simple-review-alert", "review notice stays first");
  fold = noticeFold();
  assert.deepEqual(fold.children[1].children.map((x) => x.textContent), pdfResult.notices.slice(1), "review message is not duplicated in the notices fold");
  const reviewFold = children.find((x) => x.children?.[0]?.textContent === "검수 내용");
  assert(flatten(reviewFold).some((text) => text.includes("자동 점검 52.4점 / 목표 98점")), "score text lives inside the '검수 내용' fold");
  // review 가 없으면 기존처럼 점수·경고가 품질 줄에 남는다.
  card.showSimpleQuality([{ quality: { objective_score: 80, objective_score_target: 98, visual_sync_ratio: 0.9 }, fidelity: { available: true } }]);
  assert(card.els.simpleQualityNote.textContent.includes("자동 점검 80.0점"));
  // notices 가 없으면 접기를 만들지 않는다.
  card.showSimpleResult([{ export: { name: "C.hwpx", url: "/files/C.hwpx" }, notices: [] }]);
  assert.equal(noticeFold(), undefined);

  console.log("Frontend error/notice display OK: 422 summary + hint, empty/extensionless block, filename* case + '%' decode, zero-import reason, notices fold, review-first quality line");
})().catch((error) => { console.error(error); process.exitCode = 1; });
