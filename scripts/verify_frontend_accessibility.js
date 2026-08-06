#!/usr/bin/env node
"use strict";

// 핵심 변환 UX와 키보드·모바일 접근성 회귀핀.
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "static", "index.html"), "utf8");
const js = fs.readFileSync(path.join(root, "static", "app.js"), "utf8");
const css = fs.readFileSync(path.join(root, "static", "styles.css"), "utf8");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

// 단순 변환 모드는 기존 작업실을 제거하지 않고 첫 화면에서만 숨긴다.
assert(/<body class="simple-converter-mode">/.test(html), "simple converter mode is not active");
for (const id of [
  "simpleConverter",
  "simpleDropzone",
  "simpleFileInput",
  "simpleSelectedFile",
  "simpleConvertButton",
  "simpleConversionStatus",
]) {
  assert(html.includes(`id="${id}"`), `simple converter element missing: ${id}`);
}
assert(/id="simpleConversionStatus"[^>]*role="status"[^>]*aria-live="polite"[^>]*aria-atomic="true"/.test(html), "simple conversion live status missing");
assert(css.includes("body.simple-converter-mode > .app-shell"), "legacy workspace is not visually preserved and hidden");
assert(js.includes('els.simpleDropzone?.addEventListener("drop"'), "simple converter drag-and-drop wiring missing");
assert(js.includes("async function runSimpleConversion()"), "simple conversion action missing");
assert(js.includes("await exportPdfLayoutFiles()"), "PDF layout conversion is not wired to the simple screen");
assert(js.includes("await importFiles({ quick: true, skipReplaceConfirm: true })"), "general HWPX conversion is not wired to the simple screen");

// 빠른 건너뛰기와 모달 기본 계약.
assert(/class="skip-link"\s+href="#workspace"/.test(html), "skip link missing");
assert(/id="workspace"[^>]*tabindex="-1"/.test(html), "workspace skip target missing");
assert(/\.skip-link:focus\s*\{[^}]*translateY\(0\)/s.test(css), "skip link focus style missing");
assert((html.match(/role="dialog"\s+aria-modal="true"/g) || []).length >= 5, "modal semantics regressed");
assert(js.includes("trapModalFocus(event, modal)"), "modal focus trap missing");
assert(js.includes("els.appShell.inert = inactive"), "modal background inert handling missing");

// 탭은 선택 탭 한 개만 Tab 순서에 두고 방향키/Home/End를 지원한다.
assert((html.match(/role="tab"/g) || []).length >= 5, "expected tab controls missing");
assert(js.includes("button.tabIndex = active ? 0 : -1"), "roving tab index missing");
for (const key of ["ArrowRight", "ArrowLeft", "Home", "End"]) {
  assert(js.includes(`event.key === "${key}"`), `tab keyboard key missing: ${key}`);
}

// 변환은 준비·진행·완료·실패 상태를 지속적으로 알리고 중복 실행을 막는다.
assert(/id="conversionStatus"[^>]*role="status"[^>]*aria-live="polite"[^>]*aria-atomic="true"/.test(html), "conversion live status missing");
assert((html.match(/aria-describedby="conversionStatus"/g) || []).length === 2, "conversion buttons are not described by status");
for (const contract of [
  "state.conversionBusy = true",
  "setConversionStatus(`문항 ${ids.length}개를 ${format} 파일로 변환하고 있습니다.`, \"working\")",
  "변환 완료",
  "변환 실패",
  "setButtonBusy(els.exportButton",
  "setButtonBusy(els.previewButton",
]) assert(js.includes(contract), `conversion feedback contract missing: ${contract}`);
assert(js.includes("서버에 연결하지 못했습니다. 연결 상태를 확인한 뒤 다시 시도하세요."), "friendly network recovery message missing");

// 자동저장 중 추가 입력이 들어와도 최신 세대가 다시 저장되어야 한다.
assert(js.includes("draftRevision: 0"), "draft revision state missing");
assert(js.includes("savingDraftPromise: null"), "serialized draft save promise missing");
assert(js.includes("state.draftRevision === revision"), "draft save generation guard missing");
assert(js.includes("return flushActiveDraft({ quiet })"), "pending draft reflush missing");
assert(js.includes('window.addEventListener("beforeunload"'), "unsaved-change exit warning missing");
assert((js.match(/await selectProblem\(dropped\.id\)/g) || []).length === 2, "drop paths must preserve the active draft");
assert(!js.includes("state.activeId = dropped.id"), "drop path bypasses safe problem selection");

// 초기 영역은 독립 로드·오류 재시도, 목록은 total 기반 페이지네이션을 제공한다.
assert(js.includes("Promise.allSettled(["), "resilient parallel initialization missing");
assert(js.includes("기록을 불러오지 못했습니다:"), "export history error state missing");
assert(js.includes('retry.textContent = "다시 시도"'), "inline retry action missing");
assert(/id="loadMoreProblemsButton"/.test(html), "problem pagination control missing");
assert(js.includes('params.set("limit", "100")'), "bounded problem page size missing");
assert(js.includes("state.problemsHasMore = Boolean(data.has_more)"), "problem has-more contract missing");
assert(js.includes("offset < missingIds.length; offset += 100"), "large basket hydration batching missing");
assert(!js.includes("missingIds.slice(0, 100)"), "basket hydration is capped at the first 100 missing problems");

// 파일은 서버 한도 전에 차단하고 진행률·취소를 제공한다.
assert(js.includes("MAX_CLIENT_UPLOAD_BYTES = 64 * 1024 * 1024"), "client upload preflight missing");
assert(js.includes("new AbortController()"), "import cancellation controller missing");
assert(js.includes("setImportProgress("), "file import progress feedback missing");
assert(/id="cancelImportButton"/.test(html), "file import cancel action missing");
assert(js.includes("작업을 취소했습니다. ${created.length}개 문항은 이미 가져와 목록에 반영했습니다."), "partial import cancellation reconciliation missing");
assert(js.includes("작업을 취소했습니다. ${results.length}개 파일은 이미 만들어 기록에 반영했습니다."), "partial layout-export history reconciliation missing");
assert(js.includes("!created.length && message === \"작업이 취소되었습니다.\""), "server-commit import abort race refresh missing");
assert(js.includes("!results.length && message === \"작업이 취소되었습니다.\""), "server-commit export abort race refresh missing");

// 모바일 조작 목표와 입력 확대 방지, 축소 모션.
assert(/@media \(max-width: 700px\)[\s\S]*min-height:\s*44px/.test(css), "mobile 44px target rule missing");
assert(/@media \(max-width: 700px\)[\s\S]*input, select, textarea\s*\{\s*font-size:\s*16px/.test(css), "mobile input zoom prevention missing");
assert(/@media \(prefers-reduced-motion: reduce\)/.test(css), "reduced motion support missing");
assert(css.includes("--success: #1d6f4e"), "AA success color token missing");
assert(css.includes("--warning: #7a4a00"), "AA warning color token missing");
assert(css.includes("--muted: #5f6b7d"), "AA muted text token missing");
assert(css.includes("color: #667085"), "AA placeholder token missing");

console.log("Frontend accessibility + conversion trust contracts OK");
