"use strict";
// View switching is a save boundary. Exercise rejected saves, races, and session
// expiry without coupling the test to markup or CSS details.
const assert = require("node:assert/strict");
const { pathToFileURL } = require("node:url");
const path = require("node:path");

(async () => {
  const { createViewTransition, previewNumberedStem } = await import(pathToFileURL(path.join(__dirname, "../static/studio-views.js")));
  for (const stem of ["27. 본문", "문제 27. 본문", "27) 본문"]) {
    assert.equal(previewNumberedStem({ number: "27", stem }, "1"), "1. 본문");
    assert.equal(previewNumberedStem({ number: "27", stem }, "27"), "27. 본문");
  }
  for (const stem of ["27.5 + x", "27.+x", "$27.5+x$", "(27) + x", "12. 다른 번호"]) {
    assert.equal(previewNumberedStem({ number: "27", stem }, "1"), `1. ${stem}`);
  }
  const shared = { number: "22", stem: "[21~22] 다음 글을 읽으시오.\nWhy do we ask questions?\nA complete shared passage.\n22. 글의 제목은?",
    layout: { block_type: "problem_with_shared_passage", shared_passage: { range: [21, 22] } } };
  const before = JSON.stringify(shared);
  assert.equal(previewNumberedStem(shared, "22"), shared.stem);
  for (const label of ["1", "101"]) {
    const preview = previewNumberedStem(shared, label);
    assert.ok(preview.startsWith(`[${label}] 다음 글`));
    assert.ok(preview.includes(`\n${label}. 글의 제목은?`));
    assert.equal((preview.match(new RegExp(`(^|\\n)${label}\\.`, "g")) || []).length, 1);
    assert.ok(!preview.includes("22. 글의 제목은?"));
    assert.ok(preview.indexOf("A complete shared passage.") < preview.indexOf(`${label}. 글의 제목은?`));
  }
  const article = { ...shared, number: "34", stem: "[31~34] 다음 빈칸을 고르시오.\n34. A\nparticularly powerful example follows.",
    layout: { block_type: "problem_with_shared_passage", shared_passage: { range: [31, 34] } } };
  assert.ok(previewNumberedStem(article, "3").includes("\n3. A\nparticularly powerful"));
  assert.equal(JSON.stringify(shared), before, "Preview must preserve stored source text and numbering");
  console.log("STUDIO_NUMBERING_OK: one label, preserved decimals, copied shared passage, renumbered article, immutable source");
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
