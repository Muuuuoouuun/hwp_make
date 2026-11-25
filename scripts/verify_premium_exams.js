"use strict";
// Saved exam client: create-then-update, unchanged drafts do not save, one save at
// a time, stale revisions stop saving, and the conflict copy keeps this tab's draft.
const assert = require("node:assert/strict");
const { pathToFileURL } = require("node:url");
const path = require("node:path");

(async () => {
  const { createExamSync, pickDraft } = await import(pathToFileURL(path.join(__dirname, "../static/premium-exams.js")));
  const base = { title: "  ", items: [{ id: 27, label: "원본 27", availability: "missing" }], numbering_mode: "sequential",
    start_number: 1, template_key: "basic", format: "hwpx", include_answer_sheet: 0 };
  assert.deepEqual(pickDraft(base), { title: "새 시험지", items: [{ id: 27, label: "원본 27" }], numbering_mode: "sequential",
    start_number: 1, template_key: "basic", format: "hwpx", include_answer_sheet: false });

  let draft = { ...base };
  let revision = 0;
  const requests = [];
  const statuses = [];
  let conflicts = 0;
  let hold = null;
  const server = (body) => ({ id: "exam1", revision: ++revision, updated_at: 1764000000, ...JSON.parse(body) });
  const api = async (url, options) => {
    requests.push({ url, method: options.method, body: JSON.parse(options.body) });
    if (hold) await hold;
    if (options.method === "PUT" && JSON.parse(options.body).expected_revision !== revision) {
      const error = new Error("conflict");
      error.status = 409;
      error.detail = { exam: { id: "exam1", revision } };
      throw error;
    }
    if (url === "/api/exams" && options.method === "POST" && requests.filter((r) => r.method === "POST").length > 1) {
      return { ...server(options.body), id: "copy1", revision: 1 };
    }
    return server(options.body);
  };
  const timers = [];
  const sync = createExamSync({
    api, snapshot: () => draft, onStatus: (kind) => statuses.push(kind), onConflict: () => conflicts++,
    setTimer: (fn) => { timers.push(fn); return timers.length; }, clearTimer: () => {},
  });

  sync.schedule();
  assert.equal(timers.length, 0, "nothing saves before the editor starts an exam");
  assert.equal(await sync.flush(), true, "flush is a no-op outside a saved exam");
  assert.equal(await sync.start(), true);
  assert.deepEqual(requests.map((r) => r.method), ["POST"]);
  assert.equal(sync.current().revision, 1);
  assert.equal(await sync.flush(), true);
  assert.equal(requests.length, 1, "an unchanged draft is not saved again");

  draft = { ...draft, items: [{ id: 5 }, { id: 27 }], start_number: 21 };
  sync.schedule();
  assert.equal(timers.length, 1, "edits are debounced");
  assert.equal(statuses.at(-1), "pending", "saved is never shown while an edit waits");
  // A second edit while the first save is in flight saves again afterwards, in order.
  let release;
  hold = new Promise((resolve) => { release = resolve; });
  const first = sync.flush();
  draft = { ...draft, title: "중간 대비" };
  const second = sync.flush();
  hold = null;
  release();
  assert.equal(await first, true);
  assert.equal(await second, true);
  const puts = requests.filter((r) => r.method === "PUT");
  assert.deepEqual(puts.map((r) => r.body.expected_revision), [1, 2], "saves run one at a time on the latest revision");
  assert.equal(puts[1].body.title, "중간 대비");
  assert.deepEqual(puts[0].body.items, [{ id: 5, label: "" }, { id: 27, label: "" }]);

  draft = { ...draft, start_number: NaN };
  sync.schedule();
  const invalid = { ...draft };
  draft = null;
  assert.equal(await sync.flush(), false, "an unsavable draft never reports saved");
  assert.equal(statuses.at(-1), "invalid");
  draft = { ...invalid, start_number: 3 };

  revision += 1; // Another tab saved.
  assert.equal(await sync.flush(), false);
  assert.equal(conflicts, 1);
  assert.equal(statuses.at(-1), "conflict");
  const before = requests.length;
  sync.schedule();
  assert.equal(await sync.flush(), false, "after a conflict nothing overwrites the other tab");
  assert.equal(requests.length, before);

  const copy = await sync.keepAsCopy();
  assert.equal(copy.id, "copy1");
  assert.equal(requests.at(-1).body.title, "중간 대비 (내 변경)");
  assert.equal(sync.current().id, "copy1");
  draft = { ...draft, title: copy.title };
  assert.equal(await sync.flush(), true, "the copy continues saving normally");

  sync.reset();
  assert.equal(sync.current(), null);
  sync.schedule();
  assert.equal(await sync.flush(), true);
  sync.begin({ id: "exam9", revision: 4, updated_at: 1764000000, ...draft });
  const count = requests.length;
  assert.equal(await sync.flush(), true);
  assert.equal(requests.length, count, "a just-opened exam is not re-saved");
  console.log("PREMIUM_EXAMS_CLIENT_OK: create/update, no-op saves, ordered saves, invalid hold, conflict stop, copy, reset/begin");
})().catch((error) => { console.error(error); process.exitCode = 1; });
