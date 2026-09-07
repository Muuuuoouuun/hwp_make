"use strict";

// Run actual workspace, numbering, planner and export functions against isolated
// browser boundaries. No user database or live server is needed.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8").replace(/\r\n/g, "\n");
const html = fs.readFileSync(path.join(__dirname, "../static/index.html"), "utf8");
function implementation(name) {
  const match = new RegExp(`^(?:async )?function ${name}\\(`, "m").exec(source);
  assert.ok(match, name);
  return source.slice(match.index, source.indexOf("\n}\n", match.index) + 3);
}
function element() {
  return { value: "", checked: false, children: [], dataset: {}, disabled: false,
    classList: { toggle() {}, add() {}, remove() {} },
    append(...children) { this.children.push(...children); }, replaceChildren() { this.children = []; },
    setAttribute() {}, addEventListener() {}, removeAttribute() {},
  };
}
const els = new Proxy({}, { get: (target, key) => target[key] ??= element() });
const state = { basket: [], problems: [], problemById: new Map(), numberingMode: "sequential", startNumber: 1, duplicateConfirmationKey: "", orderDraft: [], workspaceStage: "input", session: { authenticated: false }, recognizedProblems: [] };
const storage = new Map();
let storageReads = 0;
let requested = [];
const c = vm.createContext({
  state, els, DEFAULT_EXPORT_TITLE: "새 시험지", PREMIUM_NUMBERING_KEY: "premium-numbering", BASKET_STORAGE_KEY: "premium-basket",
  window: { location: { pathname: "/premium/studio", assign: (url) => { c.window.location.pathname = url; } }, requestAnimationFrame() {}, HwpLayoutPlanner: { planLayout: (problems) => problems } },
  localStorage: { getItem: (key) => { storageReads++; return storage.get(key) ?? null; }, setItem: (key, value) => storage.set(key, value) },
  document: { createElement: element }, icon: element, compactText: (text) => text,
  currentExportTemplate: () => ({ columns: 1 }),
  renderBasket() {}, renderList() {}, closeModal() {}, toast() {}, renderWorkspaceStage() {}, visibleModals: () => [],
  flushActiveDraft: async () => true, setWorkflowStep() {}, mobileWorkspaceActive: () => false,
  setButtonBusy() {}, setConversionStatus() {},
  fetch: async (url, options) => { requested.push({ url, body: JSON.parse(options.body) }); return { ok: false, status: 422, text: async () => JSON.stringify({ detail: { message: "fixture export stopped" } }) }; },
});
for (const name of ["isPremiumWorkspace", "restoreBasket", "persistBasket", "restoreNumbering", "resolveBasketProblem", "outputNumber", "numberMapping", "duplicateOriginalNumbers", "syncNumberingControls", "numberingPayload", "changeNumbering", "moveBasketItem", "renderOrderEditor", "moveOrderDraft", "applyOrderEditor", "computeLayoutPlan", "applyUiMode", "basketHasUnavailableProblems", "friendlyErrorMessage", "responseError", "exportSelected", "previewExport", "loadProblems"]) {
  vm.runInContext(implementation(name), c);
}
const plain = (value) => JSON.parse(JSON.stringify(value));
async function main() {
  // Legacy saved modes and query strings cannot activate the premium workspace.
  assert.ok(!html.includes('document.body.classList.remove("simple-converter-mode")'), "routes cannot reveal editor before state initialization");
  for (const pathname of ["/", "/premium", "/premium/studio", "/premium/studio/", "/premium-fake"]) {
    c.window.location.pathname = pathname;
    assert.equal(c.isPremiumWorkspace(), false, pathname);
    state.session.authenticated = true;
    assert.equal(c.isPremiumWorkspace(), false, "login alone cannot open any route");
    state.session.authenticated = false;
  }
  c.window.location.pathname = "/";
  assert.deepEqual(plain(c.restoreBasket()), []);
  c.restoreNumbering(); c.persistBasket();
  assert.equal(storageReads, 0, "basic route must never read premium state");
  assert.equal(await c.loadProblems(), false, "basic route must never fetch problem library");
  assert.deepEqual(plain(c.numberingPayload()), { workspace: "basic", numbering_mode: "preserve", start_number: 1 });
  let editorRequests = 0;
  c.enterPremiumEditor = async () => editorRequests++;
  await c.applyUiMode("studio"); assert.equal(editorRequests, 1);
  assert.equal(c.window.location.pathname, "/", "entry keeps same-page file selection");
  state.session.authenticated = true; state.workspaceStage = "editor";
  c.window.location.pathname = "/premium/studio";
  storage.set("hwpmake.basket.v1", JSON.stringify([{ id: 1, label: "기존 문항" }]));
  assert.equal(c.restoreBasket()[0].id, 1, "premium migration retains legacy selection");
  storage.set("premium-basket", "[]");
  assert.equal(c.restoreBasket().length, 0, "explicitly cleared premium basket never resurrects legacy selection");

  const originals = [12, 27, 5].map((number, index) => ({ id: index + 1, number: String(number), title: `문항 ${number}`, stem: `${number}. 본문` }));
  state.problems = originals; state.problemById = new Map(originals.map((p) => [p.id, p]));
  state.basket = originals.map((p) => ({ id: p.id, label: p.title }));
  c.moveBasketItem(0, 2);
  assert.deepEqual(state.basket.map((p) => p.id), [2, 3, 1]);
  assert.deepEqual(plain(c.computeLayoutPlan()).map((p) => p.number), ["1", "2", "3"]);
  state.startNumber = 21;
  assert.deepEqual(plain(c.computeLayoutPlan()).map((p) => p.number), ["21", "22", "23"]);
  assert.equal(c.numberMapping(originals[1], 0), "출력 21 · 원본 27");
  state.orderDraft = state.basket.map((p) => ({ ...p }));
  c.renderOrderEditor();
  assert.equal(els.orderEditorList.children[0].children[0].textContent, "21");
  c.moveOrderDraft(0, 2);
  assert.match(els.orderEditorList.children[0].children[1].children[0].textContent, /출력 21 · 원본 5/);
  c.applyOrderEditor();
  assert.deepEqual(plain(state.basket).map((p) => p.id), [3, 1, 2]);
  assert.deepEqual(originals.map((p) => p.number), ["12", "27", "5"], "source numbers remain immutable");
  assert.deepEqual(originals.map((p) => p.stem), ["12. 본문", "27. 본문", "5. 본문"], "planner must never rewrite source stems");

  els.numberingMode.value = "preserve"; els.startNumber.value = "21";
  c.changeNumbering(); c.restoreNumbering();
  assert.equal(state.numberingMode, "preserve"); assert.equal(state.startNumber, 21);
  assert.deepEqual(plain(c.computeLayoutPlan()).map((p) => p.number), ["5", "12", "27"]);
  originals[2].number = "12";
  assert.throws(() => c.numberingPayload(), /중복 원번호/);
  els.confirmDuplicateNumbers.checked = true;
  assert.equal(c.numberingPayload().confirm_duplicate_numbers, true);
  c.moveBasketItem(0, 2);
  assert.throws(() => c.numberingPayload(), /중복 원번호/, "reorder invalidates acknowledgement");
  state.numberingMode = "sequential";
  for (const start of [0, -1, 1.5, NaN, 998, 1000]) {
    state.startNumber = start;
    assert.throws(() => c.numberingPayload(), /1~999/);
  }
  state.startNumber = 997;
  assert.equal(c.numberingPayload().start_number, 997, "last output 999 is supported");
  state.startNumber = 21;
  els.exportTitle.value = "시험지"; els.exportFormat.value = "hwpx"; els.exportTemplate.value = "basic";
  await c.exportSelected();
  assert.equal(requested.at(-1).body.workspace, "premium");
  assert.equal(requested.at(-1).body.start_number, 21);
  assert.deepEqual(requested.at(-1).body.ids, state.basket.map((p) => p.id));
  await c.exportSelected([1, 2], { title: "기본 변환", format: "hwpx", templateKey: "basic", includeAnswerSheet: false, nativeMath: false });
  assert.equal(requested.at(-1).body.workspace, "basic", "simple override wins even on premium route");
  assert.equal(requested.at(-1).body.numbering_mode, "preserve");
  assert.equal(requested.at(-1).body.start_number, 1);
  // A pending save may change original numbers after the user confirmed a
  // different duplicate set. Neither export nor preview may reuse that consent.
  state.numberingMode = "preserve";
  c.syncNumberingControls(); els.confirmDuplicateNumbers.checked = true;
  const beforeSaveRequests = requested.length;
  c.flushActiveDraft = async () => { originals[1].number = "12"; return true; };
  await c.exportSelected();
  assert.equal(requested.length, beforeSaveRequests, "save must invalidate stale duplicate export approval");
  originals[1].number = "27";
  c.syncNumberingControls(); els.confirmDuplicateNumbers.checked = true;
  c.api = async () => { throw new Error("preview must not request with stale duplicate approval"); };
  await c.previewExport();
  assert.equal(els.confirmDuplicateNumbers.checked, false, "preview also rechecks numbering after saving");
  c.flushActiveDraft = async () => true;
  const error = await c.responseError({ status: 422, text: async () => JSON.stringify({ detail: { code: "unsupported", message: "지원하지 않는 문항", items: [{ position: 2, message: "이미지 번호 확인 필요" }] } }) });
  assert.match(error.message, /2번째 문항: 이미지 번호 확인 필요/);
  const init = source.slice(source.indexOf("(async function init()"));
  let premiumReads = 0;
  vm.runInContext("async function loadProblems() { throw new Error('premium library fetched in basic'); }", c);
  Object.assign(c, { initSimpleHelp() {}, openAISettings() {}, isPdfFile: () => false, refreshSession: async () => { state.session = { authenticated: true }; },
    loadExportHistory: async () => {}, loadAIStatus: async () => {}, api: async () => { premiumReads++; throw new Error("premium capability fetched in basic"); } });
  c.window.location.pathname = "/";
  state.workspaceStage = "input";
  await vm.runInContext(init, c);
  assert.equal(premiumReads, 0, "basic boot must not request premium APIs");
  console.log("Premium frontend PASS: route isolation, legacy migration, immutable reorder mappings, saved policy, duplicate acknowledgement, 999 bound, export payloads and basic boot");
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
