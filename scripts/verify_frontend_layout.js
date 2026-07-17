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

const indexHtml = fs.readFileSync(path.join(root, "static", "index.html"), "utf8");
const appJs = fs.readFileSync(path.join(root, "static", "app.js"), "utf8");
for (const snippet of ["layout-planner.js", "layoutSummary", "layoutWarnings", "paperFlowHint"]) {
  assert(indexHtml.includes(snippet), `missing layout UI hook: ${snippet}`);
}
for (const snippet of ["buildLayoutPlan", "updateLayoutSummary", "layout-risk-", "renderBasket();"]) {
  assert(appJs.includes(snippet), `missing layout behavior: ${snippet}`);
}

console.log("Frontend layout planning OK");
