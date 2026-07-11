#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const appJs = fs.readFileSync(path.join(root, "static", "app.js"), "utf8");
const indexHtml = fs.readFileSync(path.join(root, "static", "index.html"), "utf8");
const start = appJs.indexOf("const MATH_OPERATOR");
const end = appJs.indexOf("function appendContentBadge");

if (start < 0 || end < 0 || end <= start) {
  throw new Error("Unable to locate formula detection block in static/app.js");
}

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(`${appJs.slice(start, end)}\nthis.formulaMatches = formulaMatches;\nthis.contentStats = contentStats;`, sandbox, {
  filename: "static/app.js:formula-snippet",
});

function tokens(text) {
  return sandbox.formulaMatches(text).map((match) => match[0]);
}

function assertToken(text, expected) {
  const found = tokens(text);
  if (!found.includes(expected)) {
    throw new Error(`Expected token ${JSON.stringify(expected)} in ${JSON.stringify(text)}, got ${JSON.stringify(found)}`);
  }
}

function assertNoToken(text) {
  const found = tokens(text);
  if (found.length) {
    throw new Error(`Expected no formula tokens in ${JSON.stringify(text)}, got ${JSON.stringify(found)}`);
  }
}

assertToken(String.raw`$x_{n+1}=\frac{1}{2}$`, String.raw`$x_{n+1}=\frac{1}{2}$`);
assertToken(String.raw`f(x)=\sqrt{x^2+1}`, String.raw`\sqrt{x^2+1}`);
assertToken(String.raw`\frac{\sqrt{x}}{2}`, String.raw`\frac{\sqrt{x}}{2}`);
assertToken(String.raw`\sum_{k=1}^{n} k`, String.raw`\sum_{k=1}^{n} k`);
assertToken(String.raw`\int_{0}^{1} dx`, String.raw`\int_{0}^{1} dx`);
assertToken(String.raw`\overline{x}`, String.raw`\overline{x}`);
assertToken(String.raw`\vec{v}`, String.raw`\vec{v}`);
assertToken(String.raw`\left(x+1\right)`, String.raw`\left(x+1\right)`);
assertToken(String.raw`\begin{matrix}a & b \\ c & d\end{matrix}`, String.raw`\begin{matrix}a & b \\ c & d\end{matrix}`);
assertToken(String.raw`\sin x+\cos x=1`, String.raw`\sin x`);
assertToken(String.raw`\sin x+\cos x=1`, String.raw`\cos x`);
assertToken(String.raw`\log_2 x`, String.raw`\log_2 x`);
assertToken(String.raw`\alpha_1+\beta_2`, String.raw`\alpha_1`);
assertToken(String.raw`\alpha_1+\beta_2`, String.raw`\beta_2`);
assertToken(String.raw`\phi+\varphi+\epsilon+\varepsilon`, String.raw`\phi`);
assertToken(String.raw`\phi+\varphi+\epsilon+\varepsilon`, String.raw`\varphi`);
assertToken(String.raw`\phi+\varphi+\epsilon+\varepsilon`, String.raw`\epsilon`);
assertToken(String.raw`\Gamma+\Theta+\Omega`, String.raw`\Gamma`);
assertToken(String.raw`\Gamma+\Theta+\Omega`, String.raw`\Omega`);
assertToken(String.raw`\lim_{x\to0}\frac{\sin x}{x}`, String.raw`\lim_{x\to0}\frac{\sin x}{x}`);
assertToken(String.raw`\lim_{\theta\to0}\frac{\sin\theta}{\theta}`, String.raw`\lim_{\theta\to0}\frac{\sin\theta}{\theta}`);
assertToken(String.raw`x\to0`, String.raw`x\to0`);
assertToken(String.raw`a\ne0`, String.raw`a\ne0`);
assertToken(String.raw`a\ge0`, String.raw`a\ge0`);
assertToken(String.raw`a\neq0`, String.raw`a\neq0`);
assertToken(String.raw`a\geq0`, String.raw`a\geq0`);
assertToken(String.raw`\int_{0}^{1} x^2\,dx`, String.raw`\int_{0}^{1} x^2\,dx`);
assertToken(String.raw`\sqrt[3]{x^2+1}`, String.raw`\sqrt[3]{x^2+1}`);
assertToken(String.raw`\binom{n}{r}`, String.raw`\binom{n}{r}`);
assertToken(String.raw`{}_{n}C_{r}`, String.raw`{}_{n}C_{r}`);
assertToken(String.raw`\left|x-1\right|`, String.raw`\left|x-1\right|`);
assertToken(String.raw`|x-1|`, String.raw`|x-1|`);
assertToken(String.raw`x\in\mathbb{R}`, String.raw`x\in\mathbb{R}`);
assertToken(String.raw`x\notin A`, String.raw`x\notin A`);
assertToken(String.raw`A\cup B`, String.raw`A\cup B`);
assertToken(String.raw`A\cap B`, String.raw`A\cap B`);
assertToken(String.raw`g\circ f`, String.raw`g\circ f`);
assertToken(String.raw`\overrightarrow{AB}`, String.raw`\overrightarrow{AB}`);
assertToken(String.raw`\widehat{ABC}`, String.raw`\widehat{ABC}`);
assertToken(String.raw`\mathrm{P}(A)`, String.raw`\mathrm{P}(A)`);
assertToken(String.raw`\min_{x\in A} f(x)`, String.raw`\min_{x\in A} f(x)`);
assertToken(String.raw`\max_{0\le x\le 1} x^2`, String.raw`\max_{0\le x\le 1} x^2`);
assertToken(String.raw`\arctan x`, String.raw`\arctan x`);
assertToken(String.raw`\Pr(A)=\frac{1}{2}`, String.raw`\Pr(A)=\frac{1}{2}`);
assertToken(String.raw`\left\lceil x\right\rceil`, String.raw`\left\lceil x\right\rceil`);
assertToken(String.raw`\left\lfloor x\right\rfloor`, String.raw`\left\lfloor x\right\rfloor`);
const longHancomEqn = "$lim _{x ``->`` 2} {} {g LEFT (x-1 RIGHT )} over {f LEFT (x RIGHT )-g LEFT (x RIGHT )} TIMES lim _{x ``->`` INF } {} {LEFT { f LEFT (x RIGHT ) it RIGHT } ^{2}} over {g LEFT (x RIGHT )} =k$";
assertToken(longHancomEqn, longHancomEqn);
assertToken("f'(1)=3", "f'(1)=3");
assertToken("x=-1", "x=-1");
assertToken("-2<x<3", "-2<x<3");
assertToken("2x=4", "2x=4");
assertToken("3(x-1)=6", "3(x-1)=6");
assertToken("f(x)=x^2+1", "f(x)=x^2+1");
assertToken("(x+1)/2=3", "(x+1)/2=3");
assertToken("α² + βₙ", "α²");
assertToken("α² + βₙ", "βₙ");
assertToken("√x", "√x");
assertToken("√(x+1)", "√(x+1)");
assertToken("√□5", "√□5");
assertToken("sqrt□5", "sqrt□5");
assertToken("∑_{k=1}^{n} k", "∑_{k=1}^{n} k");
assertToken("∫_0^1 f(x)dx", "∫_0^1 f(x)dx");
assertToken("α+β=γ", "α+β=γ");
assertToken("θ+Ω=π", "θ+Ω=π");
assertToken(String.raw`a≤b 이고 a≠0, x_1=2`, "a≤b");
assertToken(String.raw`a≤b 이고 a≠0, x_1=2`, "a≠0");
assertToken(String.raw`a≤b 이고 a≠0, x_1=2`, "x_1=2");
assertToken("유니코드 위첨자 x²", "x²");
assertToken("유니코드 아래첨자 xₙ", "xₙ");
assertToken("한글x²", "x²");
assertToken("값α²", "α²");
assertToken("문장xₙ", "xₙ");
assertToken("반지름r_1", "r_1");
assertToken("기본 분수 ½", "½");
assertToken("단일 기호 ≤", "≤");
const explicitWithCondition = "$" + "{a _{n}^{2} +5} over {3}$ (a_n 이 3의 배수가 아닌 경우)";
assertToken(explicitWithCondition, "$" + "{a _{n}^{2} +5} over {3}$");
if (tokens(explicitWithCondition).some((token) => token.includes("경우"))) {
  throw new Error(`Explicit math delimiter consumed Korean condition text: ${JSON.stringify(tokens(explicitWithCondition))}`);
}

const dateTokens = tokens("시험일 2026-07-07").filter((token) => token.includes("2026"));
if (dateTokens.length) {
  throw new Error(`Date-like text should not be counted as a formula: ${JSON.stringify(dateTokens)}`);
}
assertNoToken("쪽 범위 100-200");
assertNoToken("문항 ID A1-2026");
assertNoToken("가격은 $5 and $10");

const stats = sandbox.contentStats({
  stem: "일반 문장",
  choices: [],
  answer: "x=-1",
  explanation: String.raw`\frac{1}{2}`,
  tables: [[["항목", "값"], ["수식", String.raw`\sqrt{x}`]]],
});
if (stats.formulaCount < 3) {
  throw new Error(`Expected answer/explanation/table formulas to be counted, got ${stats.formulaCount}`);
}

for (const snippet of [
  String.raw`data-math-insert="\frac{a}{b}"`,
  String.raw`data-math-insert="\sqrt{x}"`,
  String.raw`data-math-insert="\sum_{k=1}^{n}"`,
  String.raw`data-math-insert="\int_{0}^{1} dx"`,
  String.raw`data-math-insert="\overline{x}"`,
  String.raw`data-math-insert="\vec{v}"`,
  String.raw`id="exportNativeMath"`,
]) {
  if (!indexHtml.includes(snippet)) {
    throw new Error(`Missing math toolbar snippet in index.html: ${snippet}`);
  }
}

if (!appJs.includes("native_math:")) {
  throw new Error("Missing native_math export payload in static/app.js");
}
if (!appJs.includes("native_math_default")) {
  throw new Error("Missing native_math_default template handling in static/app.js");
}
if (!appJs.includes("currentExportTemplate")) {
  throw new Error("Missing current export template lookup in static/app.js");
}
if (!appJs.includes("native_math: Boolean(els.exportNativeMath?.checked)")) {
  throw new Error("Missing native_math preview payload in static/app.js");
}

const insertStart = appJs.indexOf("const EDITOR_MATH_FIELD_IDS");
const insertEnd = appJs.indexOf("function setInputMode");
if (insertStart < 0 || insertEnd < 0 || insertEnd <= insertStart) {
  throw new Error("Unable to locate math insertion block in static/app.js");
}

const insertSandbox = {
  Event: class {
    constructor(type, init = {}) {
      this.type = type;
      Object.assign(this, init);
    }
  },
};
vm.createContext(insertSandbox);
vm.runInContext(
  `${appJs.slice(insertStart, insertEnd)}\nthis.mathInsertion = mathInsertion;\nthis.insertAtCursor = insertAtCursor;`,
  insertSandbox,
  { filename: "static/app.js:math-insertion-snippet" }
);

function fakeField(value, selectionStart = value.length, selectionEnd = selectionStart) {
  return {
    value,
    selectionStart,
    selectionEnd,
    focused: false,
    events: [],
    focus() {
      this.focused = true;
    },
    setRangeText(replacement, start, end) {
      this.value = `${this.value.slice(0, start)}${replacement}${this.value.slice(end)}`;
      this.selectionStart = start + replacement.length;
      this.selectionEnd = this.selectionStart;
    },
    setSelectionRange(start, end) {
      this.selectionStart = start;
      this.selectionEnd = end;
    },
    dispatchEvent(event) {
      this.events.push(event.type);
    },
  };
}

let field = fakeField("");
insertSandbox.insertAtCursor(field, String.raw`\frac{a}{b}`);
if (field.value !== String.raw`\frac{a}{b}` || field.value.slice(field.selectionStart, field.selectionEnd) !== "a") {
  throw new Error(`Fraction insertion should select numerator placeholder, got ${JSON.stringify(field)}`);
}

field = fakeField("x+1", 0, 3);
insertSandbox.insertAtCursor(field, String.raw`\sqrt{x}`);
if (field.value !== String.raw`\sqrt{x+1}` || !field.focused || !field.events.includes("input")) {
  throw new Error(`Sqrt insertion should wrap selected text and emit input, got ${JSON.stringify(field)}`);
}

field = fakeField("정답: y", 4, 5);
insertSandbox.insertAtCursor(field, "x^2");
if (field.value !== "정답: y^{2}") {
  throw new Error(`Superscript insertion should use selected base, got ${JSON.stringify(field.value)}`);
}

field = fakeField("해설:", 3, 3);
insertSandbox.insertAtCursor(field, String.raw`\vec{v}`);
if (field.value !== String.raw`해설: \vec{v}` || field.value.slice(field.selectionStart, field.selectionEnd) !== "v") {
  throw new Error(`Vector insertion should keep smart prefix and select placeholder, got ${JSON.stringify(field)}`);
}

console.log("Frontend formula detection OK");
