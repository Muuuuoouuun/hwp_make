#!/usr/bin/env node
"use strict";

// 간단 변환 화면 계약 회귀핀.
// 이 화면의 4대 계약: ① 스튜디오와 서로 오갈 수 있어야 하고 ② PDF는 편집형 structured
// 모드로 변환하며 ③ 스튜디오의 시험지 구성(basket)·폼 상태를 부수효과로 바꾸지 않고
// ④ 진행 중 취소, 품질 점수, 최근 변환 이력을 화면 안에서 제공한다.
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "static", "index.html"), "utf8");
const js = fs.readFileSync(path.join(root, "static", "app.js"), "utf8");
const css = fs.readFileSync(path.join(root, "static", "styles.css"), "utf8");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

// ① 모드 전환: 간단 → 스튜디오, 스튜디오 → 간단 진입점이 모두 존재해야 한다.
assert(html.includes('id="simpleStudioButton"'), "simple → studio entry button missing");
assert(html.includes('id="simpleModeButton"'), "studio → simple return button missing");
assert(js.includes("function applyUiMode(mode"), "applyUiMode mode switcher missing");
assert(js.includes('applyUiMode("studio"'), "studio switch wiring missing");
assert(js.includes('applyUiMode("simple"'), "simple switch wiring missing");
assert(!js.includes("UI_MODE_STORAGE_KEY"), "legacy UI storage must not control the premium route");
assert(!html.includes('window.localStorage.getItem("hwpMakeUiMode")'), "pre-paint must ignore legacy UI mode");
assert(js.includes('if (mode === "studio") return enterPremiumEditor()'), "editor must require the explicit session-aware entry action");
assert(!js.includes("window.location.assign("), "login/editor entry must preserve the selected File in the current page");
assert(css.includes("body:not(.simple-converter-mode) .simple-converter"), "simple screen is not hidden in studio mode");
// 프리미엄은 별도 페이지 초기화에서 용지 크기를 측정한다.
for (const remeasure of ["applyWorkspaceLayout()", "ensurePaperBaseWidth()", "updatePaperCanvasSize()"]) {
  assert(
    js.split("function applyUiMode")[1]?.includes(remeasure),
    `studio re-measure call missing in applyUiMode: ${remeasure}`,
  );
}

// ② PDF는 편집형 기본값(structured)으로, 스튜디오 원본 레이아웃 버튼은 coordinate 유지.
assert(/layoutMode:\s*"structured"/.test(js), "simple PDF conversion must request structured layout mode");
assert(/exportPdfLayoutFiles\(\{\s*layoutMode = "coordinate"/.test(js), "studio coordinate default regressed");
assert(js.includes('layout_mode: layoutMode'), "layout_mode is not parameterized in the export payload");

// ③ 스튜디오 상태 보호: basket 비파괴 + 폼 상태 오버라이드 + 파일 선택 복원 + UI 부수효과 차단.
assert(js.includes("await exportSelected(state.recognizedProblems.map"), "basic conversion must reuse recognized source IDs without importing or changing basket");
assert(js.includes('templateKey: "basic"'), "simple conversion must pass basic options rather than read studio form state");
assert(js.includes("kind: EXT_KINDS[simpleFileExtension(file)]"), "recognition must classify the selected file independently of studio controls");
assert(/if \(quick && preserveBasket\)/.test(js), "preserveBasket fast path missing in handleImportedProblems");
assert(/if \(!preserveBasket\) \{\s*\n\s*addManyToBasket/.test(js), "partial-failure path may still clobber the basket");
assert(!/els\.exportTemplate\.value\s*=\s*"basic"/.test(js), "simple conversion still mutates the studio template select");
assert(!/els\.importKind\.value\s*=\s*"auto"/.test(js), "simple conversion still mutates the studio import-kind select");
assert(js.includes("const studioFiles = Array.from(els.fileInput?.files || [])"), "studio file selection is not snapshotted");
assert(/for \(const studioFile of studioFiles\) restore\.items\.add\(studioFile\)/.test(js), "studio file selection is not restored after simple conversion");
assert(/if \(!overrides\) \{\s*\n[^}]*setWorkflowStep\(3\)/.test(js), "simple export still mutates studio workflow step / mobile pane");
// 같은 파일 재변환은 중복 스킵된 기존 문항을 재사용해 멱등하게 성공해야 한다.
assert(js.includes("existingProblems"), "duplicate-skip reuse (existing problems) is not wired");
assert(js.includes("existing.push(...(result.existing || []))"), "import result existing list is not collected");
// 동시 실행·컨트롤러 수명 계약.
assert(js.includes("if (state.importController === controller) state.importController = null"), "abort controller slot is not ownership-guarded");
assert(js.includes("다른 변환이 아직 진행 중입니다"), "concurrent conversion is not blocked in the simple screen");
// 모드 전환 시 숨김 상태에서 굳은 용지 기준 폭 캐시를 리셋해야 한다.
assert(/state\.paperBaseWidth = 0;\s*\n\s*state\.paperViewportMode = null;/.test(js), "paper base width cache is not reset when entering studio");
assert(/if \(!els\.paperStage \|\| !els\.paperStage\.clientWidth\) return;/.test(js), "hidden-state paper measurement is not guarded");
// 취소 버튼이 포커스를 쥔 채 사라지면 안 된다.
assert(js.includes("document.activeElement === els.simpleCancelButton"), "cancel button focus hand-off missing");

// ④ 취소·품질·이력·AI 토글.
assert(html.includes('id="simpleCancelButton"'), "simple cancel button missing");
assert(js.includes("state.simpleCancelRequested = true"), "cancel request flag missing");
assert(js.includes("state.importController?.abort()"), "cancel is not wired to the abort controller");
assert(js.includes('setSimpleConversionStatus("대기를 중단했습니다. 서버에서 생성이 계속될 수'), "cancel semantics must distinguish stopping the wait from stopping server work");
// 취소는 내보내기(2단계) fetch까지 닿아야 한다: signal 스레딩.
assert(js.includes("exportSignal: controller.signal"), "export phase is not cancellable (signal not threaded)");
assert(js.includes("signal: signal || undefined"), "exportSelected fetch ignores the abort signal");
assert(html.includes('id="simpleQualityNote"'), "quality note element missing");
assert(js.includes("quality.objective_score"), "objective score is not surfaced");
assert(html.includes('id="simpleHistoryList"'), "recent conversion history list missing");
assert(js.includes("function renderSimpleHistory()"), "renderSimpleHistory missing");
assert(/function renderHistory\(\) \{\s*\n\s*renderSimpleHistory\(\);/.test(js), "history refresh does not update the simple screen");
assert(html.includes('id="simpleMathAi"'), "simple math AI toggle missing");
assert(js.includes("els.simpleMathAi.disabled = !mathReady"), "simple math AI toggle is not gated by AI status");

console.log("Frontend simple converter contracts OK");
