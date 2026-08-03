#!/usr/bin/env node
"use strict";
// 워크벤치 UI 회귀핀 (2026-08-03 병합에서 구 UI 핀 verify_frontend_compact.js 를 대체).
// 특정 CSS 수치 대신 "배선 무결성"을 고정한다:
//  1) index.html 이 app.js / styles.css 를 캐시버스트 버전과 함께 로드한다.
//  2) app.js 가 리터럴로 참조하는 모든 #id 가 index.html 에 실제로 존재한다.
//  3) 워크벤치 3단계 흐름과 모달 시스템이 존재한다.

const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "static", "index.html"), "utf8");
const js = fs.readFileSync(path.join(root, "static", "app.js"), "utf8");
const css = fs.readFileSync(path.join(root, "static", "styles.css"), "utf8");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

// 1) 자산 배선
assert(/\/static\/app\.js\?v=\d+/.test(html), "app.js cache-busted script tag missing");
assert(/\/static\/styles\.css\?v=\d+/.test(html), "styles.css cache-busted link tag missing");

// 2) id 배선 무결성: app.js 의 리터럴 id 참조가 index.html 에 전부 존재해야 한다.
//    (동적으로 생성되는 id 는 리터럴 매칭에 걸리지 않으므로 자연히 제외된다.)
const htmlIds = new Set([...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]));
const referenced = new Set();
for (const m of js.matchAll(/getElementById\(\s*["']([^"']+)["']\s*\)/g)) referenced.add(m[1]);
for (const m of js.matchAll(/querySelector(?:All)?\(\s*["']#([A-Za-z][\w-]*)["']\s*\)/g)) referenced.add(m[1]);
// app.js 가 스스로 createElement 등으로 만들어 붙이는 id 는 예외 목록에 추가한다.
const dynamicallyCreated = new Set();
for (const m of js.matchAll(/\.id\s*=\s*["']([^"']+)["']/g)) dynamicallyCreated.add(m[1]);
const missing = [...referenced].filter((id) => !htmlIds.has(id) && !dynamicallyCreated.has(id));
assert(
  missing.length === 0,
  `app.js references ids missing from index.html: ${missing.slice(0, 10).join(", ")}`,
);
assert(referenced.size >= 50, `suspiciously few id references parsed (${referenced.size}) — parser broken?`);

// 3) 워크벤치 구조 핀
const workflowSteps = (html.match(/workflow-step/g) || []).length;
assert(workflowSteps >= 3, "workbench 3-step workflow strip missing");
for (const modalId of ["previewModal", "orderEditorModal", "aiSettingsModal"]) {
  assert(htmlIds.has(modalId), `workbench modal missing: ${modalId}`);
  assert(js.includes(modalId), `workbench modal unwired in app.js: ${modalId}`);
}
assert(css.includes(".modal"), "modal styles missing from styles.css");

console.log(`Frontend workbench wiring OK (ids referenced=${referenced.size}, defined=${htmlIds.size})`);
