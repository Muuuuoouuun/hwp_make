#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
require(path.join(root, "static", "layout-planner.js"));

const planner = globalThis.HwpLayoutPlanner;
if (!planner?.planLayout) throw new Error("HwpLayoutPlanner was not attached to globalThis");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function problem(id, lineCount, extra = {}) {
  return {
    id,
    title: `layout-${id}`,
    stem: Array.from({ length: lineCount }, (_, index) => `문항 ${id}의 ${index + 1}번째 줄입니다.`).join("\n"),
    choices: [],
    tables: [],
    image_paths: [],
    ...extra,
  };
}

const twoColumn = { key: "kice_math", label: "평가원 수학", columns: 2, inline_short_choices: true };
const boundaryPlan = planner.planLayout([problem(1, 10), problem(2, 7)], twoColumn);
assert(boundaryPlan.columns === 2, "two-column template was not respected");
assert(boundaryPlan.placements[0].start.column === 1, "first problem should start in left column");
assert(boundaryPlan.placements[1].start.column === 2, "second problem should move intact to right column");
assert(!boundaryPlan.placements[1].oversized, "a fitting problem must not be marked split");
assert(boundaryPlan.placements[1].breakBefore, "column boundary move should be explicit");

const oversizedPlan = planner.planLayout([problem(3, 42), problem(4, 1)], twoColumn);
assert(oversizedPlan.splitCount === 1, "oversized problem risk was not detected");
assert(oversizedPlan.placements[0].endSlot > oversizedPlan.placements[0].startSlot, "oversized problem should span slots");
assert(oversizedPlan.pageCount >= 2, "oversized problem should increase predicted page count");
assert(
  oversizedPlan.pages.some((page) => page.columns.some((column) => column.continuations.length)),
  "continued columns should be represented in the page plan",
);

const reordered = planner.planLayout([problem(4, 1), problem(3, 42)], twoColumn);
assert(reordered.placements[0].id === 4, "reordered first problem id was not retained");
assert(reordered.placements[1].startSlot !== oversizedPlan.placements[0].startSlot, "reorder did not change placement");

const mediaPlan = planner.planLayout(
  [problem(5, 2, { image_paths: ["one.png", "two.png"], tables: [[["구분", "값"], ["가", "긴 표 내용"]]] })],
  twoColumn,
);
assert(mediaPlan.placements[0].estimatedHeight >= 80, "image/table height was not included");

const oneColumn = planner.planLayout([problem(6, 10), problem(7, 10)], { key: "basic", columns: 1 });
assert(oneColumn.columns === 1, "single-column template was not respected");
assert(oneColumn.placements.every((item) => item.start.column === 1), "single-column plan emitted a second column");

// 워크벤치 배선 핀 (P1-⑤, 2026-08-03 병합 이후 재통합): layout-planner.js 가 index.html 에서
// 로드되고, app.js 의 renderBasket() 흐름이 planLayout 을 호출해 "예상 배치·경계 경고"
// (요약 줄 · 문항 배지 · 분할 경고 목록)를 실제로 렌더링하는지 고정한다.
const indexHtml = fs.readFileSync(path.join(root, "static", "index.html"), "utf8");
const appJs = fs.readFileSync(path.join(root, "static", "app.js"), "utf8");

assert(
  /<script src="\/static\/layout-planner\.js\?v=\d+"><\/script>/.test(indexHtml),
  "index.html does not load layout-planner.js with a cache-busted script tag",
);
const plannerTagIndex = indexHtml.indexOf("layout-planner.js");
const appTagIndex = indexHtml.indexOf("/static/app.js");
assert(
  plannerTagIndex >= 0 && appTagIndex >= 0 && plannerTagIndex < appTagIndex,
  "layout-planner.js must load before the app.js module tag so HwpLayoutPlanner exists on globalThis in time",
);
for (const id of ["layoutPlanSummary", "layoutPlanWarnings"]) {
  assert(indexHtml.includes(`id="${id}"`), `index.html is missing #${id}`);
  assert(
    appJs.includes(`document.querySelector("#${id}")`),
    `app.js does not bind #${id} in its els lookup table`,
  );
}

assert(appJs.includes("function computeLayoutPlan("), "app.js is missing computeLayoutPlan()");
assert(
  appJs.includes("window.HwpLayoutPlanner"),
  "computeLayoutPlan() must read the planner off window.HwpLayoutPlanner (defensive against a missing script tag)",
);
assert(/planner\.planLayout\(/.test(appJs), "computeLayoutPlan() does not call HwpLayoutPlanner.planLayout()");
assert(appJs.includes("function renderLayoutPlanSummary("), "app.js is missing renderLayoutPlanSummary()");
assert(appJs.includes("function createLayoutRiskBadge("), "app.js is missing createLayoutRiskBadge()");
assert(appJs.includes("basket-risk-badge"), "basket rows do not render a layout-risk badge element");
assert(
  appJs.includes("분할 위험") && appJs.includes("단 이동"),
  "risk badge copy (분할 위험 for oversized / 단 이동 for breakBefore) is missing",
);

// renderBasket() must compute + render the plan on every call, since both basket mutations and
// syncTemplatePreview() (export template change) funnel through it.
const renderBasketStart = appJs.indexOf("function renderBasket(");
assert(renderBasketStart >= 0, "renderBasket() not found in app.js");
const renderBasketBody = appJs.slice(renderBasketStart, renderBasketStart + 1000);
assert(renderBasketBody.includes("computeLayoutPlan()"), "renderBasket() does not compute the layout plan");
assert(
  renderBasketBody.includes("renderLayoutPlanSummary(layoutPlan)"),
  "renderBasket() does not render the layout plan summary/warnings",
);
assert(
  appJs.includes("layoutPlan?.placements?.[index]"),
  "basket rows are not matched to their layout-plan placement by index",
);

const syncTemplatePreviewStart = appJs.indexOf("function syncTemplatePreview()");
assert(syncTemplatePreviewStart >= 0, "syncTemplatePreview() not found in app.js");
const syncTemplatePreviewBody = appJs.slice(syncTemplatePreviewStart, syncTemplatePreviewStart + 800);
assert(
  syncTemplatePreviewBody.includes("renderBasket();"),
  "syncTemplatePreview() must still re-render the basket (and therefore the layout plan) on template change",
);

console.log("Frontend layout planning + workbench wiring OK");
