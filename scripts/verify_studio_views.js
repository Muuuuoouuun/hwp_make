"use strict";
// View switching is a save boundary. Exercise rejected saves, races, and session
// expiry without coupling the test to markup or CSS details.
const assert = require("node:assert/strict");
const { pathToFileURL } = require("node:url");
const path = require("node:path");

(async () => {
  const { createViewTransition } = await import(pathToFileURL(path.join(__dirname, "../static/studio-views.js")));
  let active = true;
  let failureCount = 0;
  const applied = [];
  const pending = [];
  const switchView = createViewTransition({ active: () => active,
    save: () => new Promise((resolve) => pending.push(resolve)),
    apply: (view) => applied.push(view), failed: () => failureCount++,
  });

  assert.equal(await switchView("unknown"), false);
  assert.equal(pending.length, 0);
  const rejected = switchView("paper");
  pending.shift()(false);
  assert.equal(await rejected, false);
  assert.deepEqual(applied, [], "Failed save must preserve the editing view");
  assert.equal(failureCount, 1);

  const earlier = switchView("paper");
  const latest = switchView("order");
  const firstSave = pending.shift();
  pending.shift()(true);
  assert.equal(await latest, true);
  firstSave(true);
  assert.equal(await earlier, false);
  assert.deepEqual(applied, ["order"], "A late save must not restore an earlier view");

  const expired = switchView("edit");
  active = false;
  pending.shift()(true);
  assert.equal(await expired, false);
  assert.equal(await switchView("paper"), false);
  assert.deepEqual(applied, ["order"], "Session expiry must prevent switching");
  assert.equal(pending.length, 0);
  active = true;
  const resumed = switchView("edit");
  pending.shift()(true);
  assert.equal(await resumed, true);
  assert.deepEqual(applied, ["order", "edit"]);
  console.log("STUDIO_VIEWS_OK: failed-save preservation, latest-request wins, session expiry, resumed switching");
})().catch((error) => { console.error(error); process.exitCode = 1; });
