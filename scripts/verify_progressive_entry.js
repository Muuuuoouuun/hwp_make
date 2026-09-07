"use strict";

// Runtime checks of the actual staged entry functions with isolated DOM/network.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8").replace(/\r\n/g, "\n");
function implementation(name) {
  const match = new RegExp(`^(?:async )?function ${name}\\(`, "m").exec(source);
  assert.ok(match, name);
  return source.slice(match.index, source.indexOf("\n}\n", match.index) + 3);
}
function element() {
  const classes = new Set();
  return { value: "", textContent: "", dataset: {}, files: [], children: [], disabled: false,
    classList: { add: (...xs) => xs.forEach(x => classes.add(x)), remove: (...xs) => xs.forEach(x => classes.delete(x)),
      toggle: (x, on) => on ? classes.add(x) : classes.delete(x), contains: x => classes.has(x) },
    focus() {}, setAttribute() {}, removeAttribute() {}, replaceChildren() {}, reportValidity: () => true,
  };
}
function harness() {
  const els = new Proxy({}, { get: (obj, key) => obj[key] ??= element() });
  const calls = [];
  const state = { workspaceStage: "input", session: { authenticated: false, setup_required: false },
    selectedFile: null, recognizedFile: null, recognizedProblems: [], recognitionRequestId: 0,
    recognitionController: null, basket: [{ id: 99, label: "saved draft" }], problems: [], problemById: new Map(),
    simpleNotices: [], simpleConversionBusy: false, editorOpening: false, editorSourceFile: null,
  };
  const c = vm.createContext({ state, els, calls, AbortController, console,
    document: { body: element(), title: "", activeElement: null },
    window: { location: { pathname: "/premium/studio" } },
    EXT_KINDS: { txt: "text", pdf: "pdf", docx: "docx" }, MAX_CLIENT_UPLOAD_BYTES: 64 * 1024 * 1024,
    DEFAULT_EXPORT_TITLE: "새 시험지",
    DataTransfer: class { constructor() { this.files = []; this.items = { add: f => this.files.push(f) }; } },
    clearSimpleResult() { state.simpleNotices = []; }, setSimpleQualityNote() {}, setButtonBusy() {},
    friendlyErrorMessage: e => e.message, isPdfFile: f => /\.pdf$/i.test(f?.name || ""),
    fileToBase64: async () => "ZmlsZQ==", loadAIStatus: async () => {},
    api: async url => { throw new Error(`Unexpected API: ${url}`); },
    initializePremiumEditor: async () => calls.push("initialize"), selectProblem: async id => calls.push(["select", id]),
    openSessionDialog: async () => calls.push("login-dialog"), closeModal: () => calls.push("close-modal"),
    problemLabel: p => p.title || String(p.id), restoreBasket: () => [{ id: 99, label: "saved draft" }],
    visibleModals: () => [], flushActiveDraft: async () => true, validateUploadSizes: () => true,
    showSimpleQuality() {}, showSimpleResult() {}, showSelectedFiles() {},
  });
  for (const name of ["isPremiumWorkspace", "simpleFileExtension", "formatSimpleFileSize", "assignSingleFile",
    "setSimpleConversionStatus", "renderWorkspaceStage", "setSimpleFile", "recognizeSimpleFile",
    "refreshSession", "authenticateLocalSession", "enterPremiumEditor", "applyUiMode", "runSimpleConversion"]) {
    vm.runInContext(implementation(name), c);
  }
  return c;
}
const plain = x => JSON.parse(JSON.stringify(x));
const file = name => ({ name, size: 16, type: name.endsWith(".pdf") ? "application/pdf" : "text/plain" });
const tick = () => new Promise(resolve => setImmediate(resolve));
async function run() {
  const c = harness();
  const { state, els } = c;
  c.renderWorkspaceStage();
  assert.equal(c.isPremiumWorkspace(), false, "premium URL cannot bypass staged entry");
  assert(els.simpleActions.classList.contains("hidden"));
  assert(els.simpleHistory.classList.contains("hidden"));
  const imported = [{ id: 1, number: "27", title: "first" }, { id: 2, number: "12", title: "second" }];
  const requests = [];
  c.api = async (url, options) => {
    requests.push({ url, body: options?.body ? JSON.parse(options.body) : null });
    if (url === "/api/import") return { created: [imported[1]], existing: [imported[0], imported[1]], ordered_ids: [1, 2], notices: [] };
    if (url === "/api/session/login") return { authenticated: true, user: { name: "local" }, premium_access: true };
    if (url === "/api/session") return { authenticated: true, premium_access: true };
    if (url === "/api/premium-capabilities") return { available: true };
    throw new Error(url);
  };
  const chosen = file("worksheet.txt");
  assert.equal(await c.setSimpleFile(chosen, { syncInput: true }), true);
  assert.equal(state.workspaceStage, "ready");
  assert.equal(state.selectedFile, chosen);
  assert.equal(state.recognizedFile, chosen);
  assert.equal(els.simpleFileInput.files[0], chosen);
  assert.deepEqual(plain(state.recognizedProblems).map(p => p.id), [1, 2]);
  assert.deepEqual(state.basket, [{ id: 99, label: "saved draft" }], "recognition never overwrites composition");
  assert.equal(state.problemById.size, 0, "recognition never initializes editor data");
  assert.equal(requests.length, 1);
  assert.deepEqual(requests[0].body, { kind: "text", filename: chosen.name, data_base64: "ZmlsZQ==", metadata: {} });
  assert.equal(await c.enterPremiumEditor(), false);
  assert(c.calls.includes("login-dialog"));
  assert.equal(state.workspaceStage, "ready");

  els.sessionPassword.value = "local-password-2026";
  await c.authenticateLocalSession({ preventDefault() {} });
  assert.equal(state.session.authenticated, true);
  assert.equal(state.workspaceStage, "ready", "login alone must not open editor");
  assert.equal(state.selectedFile, chosen, "login retains exact File object");
  assert.equal(state.recognizedFile, chosen);
  assert.equal(els.sessionPassword.value, "");
  assert.equal(c.calls.includes("initialize"), false);
  assert.equal(await c.enterPremiumEditor(), true);
  assert.equal(c.isPremiumWorkspace(), true);
  assert.deepEqual(plain(state.basket).map(p => p.id), [1, 2]);
  assert.equal(requests.filter(r => r.url === "/api/import").length, 1, "editor entry reuses recognition");
  state.basket.reverse();
  await c.applyUiMode("simple");
  assert.equal(state.workspaceStage, "ready");
  assert.equal(state.selectedFile, chosen);
  await c.enterPremiumEditor();
  assert.deepEqual(plain(state.basket).map(p => p.id), [2, 1], "same File reentry keeps edits");
  await c.applyUiMode("simple");
  let exported;
  c.exportSelected = async (...args) => { exported = args; return true; };
  await c.runSimpleConversion();
  assert.deepEqual(plain(exported[0]), [1, 2], "basic output uses source recognition order, not edited basket");
  assert.equal(exported[1].templateKey, "basic");
  assert.equal(state.workspaceStage, "results");
  assert.equal(requests.filter(r => r.url === "/api/import").length, 1, "basic output never imports the same File twice");

  // A later file or clear must win over an earlier response, even if the
  // server completes despite AbortController cancellation.
  const race = harness();
  const pending = new Map();
  race.api = async (url, options) => new Promise(resolve => pending.set(JSON.parse(options.body).filename, resolve));
  const a = file("A.txt"), b = file("B.txt");
  const first = race.setSimpleFile(a);
  await tick();
  const firstController = race.state.recognitionController;
  const second = race.setSimpleFile(b);
  await tick();
  assert(firstController.signal.aborted);
  pending.get("B.txt")({ created: [{ id: 20 }] });
  await second;
  pending.get("A.txt")({ created: [{ id: 10 }] });
  await first;
  assert.equal(race.state.recognizedFile, b);
  assert.deepEqual(plain(race.state.recognizedProblems).map(p => p.id), [20]);
  const clearing = race.setSimpleFile(a);
  await tick();
  race.setSimpleFile(null, { syncInput: true });
  pending.get("A.txt")({ created: [{ id: 30 }] });
  await clearing;
  assert.equal(race.state.workspaceStage, "input");
  assert.equal(race.state.recognizedFile, null);
  assert.equal(race.state.recognizedProblems.length, 0);

  const bad = harness();
  let importCalls = 0;
  bad.api = async () => { importCalls++; throw new Error("Network failed"); };
  await bad.setSimpleFile(file("bad.exe"));
  assert.equal(importCalls, 0);
  assert.equal(bad.state.workspaceStage, "error");
  await bad.setSimpleFile(file("broken.txt"));
  assert.equal(importCalls, 1);
  assert.equal(bad.state.workspaceStage, "error");
  assert.equal(bad.state.recognizedFile, null);
  bad.api = async () => ({ existing: [{ id: 31 }], created: [] });
  assert.equal(await bad.recognizeSimpleFile(), true, "all-existing import is a successful retry");
  assert.equal(bad.state.workspaceStage, "ready");
  bad.api = async () => ({ created: [{ id: 31 }], ordered_ids: [999] });
  assert.equal(await bad.recognizeSimpleFile(), false, "unknown ordered source IDs must fail");
  assert.equal(bad.state.workspaceStage, "error");
  bad.api = async () => ({ created: [{ id: 31 }, { id: 32 }], ordered_ids: [31] });
  assert.equal(await bad.recognizeSimpleFile(), false, "ordered source metadata must not silently omit a recognized problem");

  const opening = harness();
  opening.state.session = { authenticated: true };
  opening.state.selectedFile = chosen;
  opening.state.recognizedFile = chosen;
  opening.state.recognizedProblems = imported;
  opening.state.workspaceStage = "ready";
  let releaseSession;
  opening.api = async url => url === "/api/session"
    ? new Promise(resolve => { releaseSession = resolve; })
    : { available: true };
  const entering = opening.enterPremiumEditor();
  await tick();
  opening.setSimpleFile(null);
  releaseSession({ authenticated: true });
  await entering;
  // An implementation may lock file changes or cancel the pending transition.
  assert(opening.state.selectedFile === chosen || !opening.isPremiumWorkspace(), "clearing the file during account refresh must not open an empty editor");
  console.log("PROGRESSIVE_ENTRY_OK: input-first, real recognition, ordered reuse, login retention, explicit editor, basic conversion, stale races and retry");
}
run().catch(error => { console.error(error); process.exitCode = 1; });
