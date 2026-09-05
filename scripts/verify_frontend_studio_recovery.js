"use strict";

// Behavioral checks execute the real basket functions against an isolated DOM
// and API stub; no server or user database is touched.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8").replace(/\r\n/g, "\n");
function implementation(name) {
  const match = new RegExp(`(?:async )?function ${name}\\(`).exec(source);
  assert.ok(match, `${name} exists`);
  return source.slice(match.index, source.indexOf("\n}\n", match.index) + 3);
}
class Element {
  constructor() {
    this.children = [];
    this.dataset = {};
    this.listeners = {};
    this.classList = { toggle() {}, add() {}, remove() {} };
  }
  append(...children) { this.children.push(...children); }
  setAttribute() {}
  removeAttribute() {}
  addEventListener(name, fn) { this.listeners[name] = fn; }
  set innerHTML(value) { this.children = []; }
}
const state = { basket: [], problems: [], problemById: new Map(), conversionBusy: false };
const elements = Object.fromEntries([
  "basketBadge", "selectedText", "flowBasketCount", "libraryBasketHint",
  "basketClearButton", "orderEditorButton", "previewButton", "exportButton", "basketList",
].map((name) => [name, new Element()]));
let fetchProblem;
const context = vm.createContext({
  state, els: elements,
  api: (url) => fetchProblem(Number(url.split("/").pop())),
  document: { createElement: () => new Element() },
  window: { requestAnimationFrame: () => {} },
  persistBasket() {}, syncPaperPreviewMeta() {}, syncConversionReadyStatus() {},
  computeLayoutPlan: () => null, renderLayoutPlanSummary() {},
  problemLabel: (problem) => problem.title || "문항", compactText: (value) => value,
  icon: () => new Element(),
});
for (const name of ["resolveBasketProblem", "basketHasUnavailableProblems", "hydrateBasketProblems", "renderBasket"]) {
  vm.runInContext(implementation(name), context);
}
(async () => {
  state.basket = Array.from({ length: 205 }, (_, index) => ({ id: index + 1, label: `문항${index + 1}` }));
  state.problemById.set(2, { id: 2, title: "삭제 전 캐시" });
  const calls = [];
  fetchProblem = async (id) => {
    calls.push(id);
    if (id === 2) throw Object.assign(new Error("missing"), { status: 404 });
    if (id === 3) throw new Error("network down");
    return { id, title: `문항${id}`, stem: "본문" };
  };
  await context.hydrateBasketProblems();
  assert.equal(calls.length, 205, "all batches and cached items are revalidated");
  assert.equal(state.basket.length, 205, "a failure never silently deletes a selection");
  assert.equal(state.basket[1].availability, "missing", "404 is a missing document");
  assert.equal(state.basket[2].availability, "retry", "network failure remains recoverable");
  context.renderBasket();
  assert.equal(elements.exportButton.disabled, true);
  assert.equal(elements.previewButton.disabled, true);
  const notice = elements.basketList.children[0];
  assert.match(notice.children[0].textContent, /확인할 수 없는/);
  fetchProblem = async (id) => ({ id, title: `복구${id}`, stem: "본문" });
  await notice.children[1].listeners.click();
  assert.equal(context.basketHasUnavailableProblems(), false);
  assert.equal(elements.exportButton.disabled, false, "retry restores export readiness");
  assert.deepEqual(state.basket.map((entry) => entry.id), Array.from({ length: 205 }, (_, i) => i + 1));
  // A selection removed while its detail request is pending must stay removed.
  state.basket = [{ id: 900, label: "pending" }];
  let complete;
  fetchProblem = () => new Promise((resolve) => { complete = resolve; });
  const pending = context.hydrateBasketProblems();
  state.basket = [];
  complete({ id: 900, title: "late response" });
  await pending;
  assert.equal(state.basket.length, 0);
  assert.equal(state.problemById.has(900), false);
  console.log("Studio basket recovery: 205 items, stale cache, 404/network, retry and removal race PASS");
})().catch((error) => { console.error(error); process.exitCode = 1; });
