#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const css = fs.readFileSync(path.join(root, "static", "styles.css"), "utf8");
const html = fs.readFileSync(path.join(root, "static", "index.html"), "utf8");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

assert(html.includes("/static/styles.css?v=12"), "compact stylesheet cache version is not wired");
assert(/button\s*\{[\s\S]*?min-height:\s*32px;[\s\S]*?padding:\s*0 10px;/.test(css), "global button size is not compact");
assert(/\.export-box\s*\{[\s\S]*?grid-template-columns:\s*minmax\(150px, 1fr\)[\s\S]*?repeat\(4, max-content\);/.test(css), "desktop export controls are not content-sized");
assert(/\.dropzone\s*\{[\s\S]*?min-height:\s*76px;/.test(css), "dropzone compact height is missing");
assert(/\.side-workbench \.problem-merge-btn\s*\{[\s\S]*?width:\s*auto;/.test(css), "problem action still forces full width");
assert(/@media \(max-width:\s*1360px\) and \(min-width:\s*1001px\)[\s\S]*?grid-template-columns:\s*minmax\(150px, 1fr\)[\s\S]*?max-content max-content;/.test(css), "mid-width export controls do not wrap safely");
assert(/@media \(max-width:\s*620px\)[\s\S]*?\.workflow-strip\s*\{[\s\S]*?repeat\(3, minmax\(0, 1fr\)\)/.test(css), "mobile workflow is not a compact three-step row");
assert(/@media \(max-width:\s*620px\)[\s\S]*?\.export-box\s*\{[\s\S]*?repeat\(2, minmax\(0, 1fr\)\)/.test(css), "mobile export controls are not compact two-column controls");

console.log("Frontend compact layout OK");
