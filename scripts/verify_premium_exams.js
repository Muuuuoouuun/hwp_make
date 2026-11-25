"use strict";
// Saved exam client: create-then-update, unchanged drafts do not save, one save at a
// time, one status per settle, stale revisions stop saving, and the conflict copy keeps
// this tab's draft. Timers are fake: 800ms = debounced save, 400ms = slow "저장 중".
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
  let nextId = "exam1";
  const server = (body) => ({ id: nextId, revision: ++revision, updated_at: 1764000000, ...JSON.parse(body) });
  const api = async (url, options) => {
    requests.push({ url, method: options.method, body: JSON.parse(options.body) });
    if (hold) await hold;
    if (options.method === "PUT" && JSON.parse(options.body).expected_revision !== revision) {
      const error = new Error("conflict");
      error.status = 409;
      error.detail = { exam: { id: "exam1", revision } };
      throw error;
    }
    return server(options.body);
  };
  const timers = [];
  const apiSwap = { current: api };
  const sync = createExamSync({
    api: (url, options) => apiSwap.current(url, options), snapshot: () => draft, onStatus: (kind) => statuses.push(kind), onConflict: () => conflicts++,
    setTimer: (fn, ms) => { timers.push({ fn, ms, alive: true }); return timers.length; },
    clearTimer: (id) => { if (timers[id - 1]) timers[id - 1].alive = false; },
  });
  const debounced = () => timers.filter((t) => t.ms === 800).length;
  const pendingSaves = () => timers.filter((t) => t.ms === 800 && t.alive).length;
  const holdNext = () => { let release; hold = new Promise((resolve) => { release = resolve; }); return () => { hold = null; release(); }; };

  sync.schedule();
  assert.equal(debounced(), 0, "nothing saves before the editor starts an exam");
  assert.equal(await sync.flush(), true, "flush is a no-op outside a saved exam");
  assert.equal(await sync.start(), true);
  assert.deepEqual(requests.map((r) => r.method), ["POST"]);
  assert.equal(sync.current().revision, 1);
  assert.equal(await sync.flush(), true);
  assert.equal(requests.length, 1, "an unchanged draft is not saved again");
  assert.ok(!statuses.includes("saving"), "a fast save never flashes 저장 중");

  draft = { ...draft, items: [{ id: 5 }, { id: 27 }], start_number: 21 };
  sync.schedule();
  assert.equal(debounced(), 1, "edits are debounced");
  assert.equal(statuses.at(-1), "pending", "saved is never shown while an edit waits");

  // A second edit while the first save is in flight saves again afterwards, in order,
  // and the older response never announces 저장됨 on its way.
  let release = holdNext();
  const first = sync.flush();
  timers.filter((t) => t.ms === 400).at(-1).fn();
  assert.equal(statuses.at(-1), "saving", "a slow save shows 저장 중");
  draft = { ...draft, title: "중간 대비" };
  const second = sync.flush();
  const mark = statuses.length;
  release();
  assert.equal(await first, true);
  assert.equal(await second, true);
  assert.equal(pendingSaves(), 0, "no stray debounced save is left behind");
  assert.equal(sync.dirty(), false);
  const settled = statuses.slice(mark).filter((s) => s !== "saving");
  assert.equal(settled[0], "pending", "an older response must not show 저장됨 while newer edits wait");
  assert.equal(statuses.at(-1), "saved");
  let puts = requests.filter((r) => r.method === "PUT");
  assert.deepEqual(puts.map((r) => r.body.expected_revision), [1, 2], "saves run one at a time on the latest revision");
  assert.equal(puts[1].body.title, "중간 대비");
  assert.deepEqual(puts[0].body.items, [{ id: 5, label: "" }, { id: 27, label: "" }]);

  // Reverting to the server copy while a save is in flight must still save the revert.
  const serverCopy = { ...draft };
  draft = { ...draft, start_number: 31 };
  release = holdNext();
  const inFlight = sync.flush();
  draft = { ...serverCopy };
  const before = debounced();
  sync.schedule();
  assert.equal(debounced(), before + 1, "a revert during a save is scheduled, not skipped");
  release();
  await inFlight;
  assert.equal(await sync.flush(), true);
  assert.equal(requests.at(-1).body.start_number, 21, "the reverted value reached the server");
  assert.equal(pendingSaves(), 0, "a save scheduled during a request and the one after it never pile up");

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
  const frozen = requests.length;
  sync.schedule();
  assert.equal(await sync.flush(), false, "after a conflict nothing overwrites the other tab");
  assert.equal(requests.length, frozen);

  assert.equal(sync.dirty(), true, "a conflict counts as unsaved (logout and tab close must warn)");

  // A failed copy stays in the conflict so both ways out remain available.
  const realApi = api;
  const failingPost = { failNext: true };
  const copyApi = async (url, options) => {
    if (failingPost.failNext && options.method === "POST") { failingPost.failNext = false; requests.push({ url, method: "POST", body: JSON.parse(options.body) }); const e = new Error("boom"); e.status = 500; throw e; }
    return realApi(url, options);
  };
  apiSwap.current = copyApi;
  assert.equal(await sync.keepAsCopy(), null);
  assert.equal(statuses.at(-1), "conflict", "copy failure keeps the conflict actions on screen");
  apiSwap.current = realApi;

  nextId = "copy1";
  const frozenAfterFail = requests.length;
  let releaseCopy = holdNext();
  const firstCopy = sync.keepAsCopy((created) => { draft = { ...draft, title: created.title }; });
  const secondCopy = sync.keepAsCopy();
  // Edit while the copy is being created: it must be saved next, not shown as 저장됨.
  draft = { ...draft, start_number: 21 };
  releaseCopy();
  const [copy, again] = await Promise.all([firstCopy, secondCopy]);
  assert.equal(requests.length, frozenAfterFail + 1, "a double click makes one copy");
  assert.equal(copy, again);
  assert.equal(copy.id, "copy1");
  assert.equal(requests.at(-1).body.title, "중간 대비 (내 변경)");
  assert.equal(requests.at(-1).body.start_number, 3, "the copy holds what was on screen when it was asked for");
  assert.equal(sync.current().id, "copy1");
  assert.equal(statuses.at(-1), "pending", "an edit made during the copy is not shown as saved");
  revision = copy.revision;
  assert.equal(await sync.flush(), true, "the copy continues saving normally");
  assert.equal(requests.at(-1).body.start_number, 21, "the edit made during the copy reached the server");

  // flush() re-checks the screen: an edit right after calling it is saved before success.
  const flushing = sync.flush();
  draft = { ...draft, start_number: 22 };
  assert.equal(await flushing, true);
  assert.equal(requests.at(-1).body.start_number, 22);

  // Switching exams while a request is in flight: the old request cannot clear the new one.
  release = holdNext();
  draft = { ...draft, start_number: 7 };
  const orphan = sync.flush();
  sync.reset();
  assert.equal(sync.current(), null);
  sync.begin({ id: "exam9", revision: 4, updated_at: 1764000000, ...draft, start_number: 9 });
  revision = 4;
  const count = requests.length;
  assert.equal(statuses.at(-1), "saved", "a just-opened exam shows 저장됨");
  release();
  await orphan;
  draft = { ...draft, start_number: 9 };
  assert.equal(await sync.flush(), true);
  assert.equal(requests.length, count, "a just-opened exam is not re-saved");
  console.log("PREMIUM_EXAMS_CLIENT_OK: create/update, no-op saves, ordered saves, one status per settle, slow-only 저장 중, revert during save, invalid hold, conflict stop, single copy, exam switch");
})().catch((error) => { console.error(error); process.exitCode = 1; });
