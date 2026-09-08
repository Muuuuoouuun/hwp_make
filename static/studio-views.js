// Three presentations of the existing workspace. Inputs and basket rows are
// moved, never cloned, so every view uses the same draft and export policy.
const VIEW_KEY = "hwpmake.premium.view.v1";
const VIEWS = ["edit", "paper", "order"];

export function createViewTransition({ active, save, apply, failed }) {
  let revision = 0;
  return async (next) => {
    if (!VIEWS.includes(next) || !active()) return false;
    const request = ++revision;
    const saved = await save();
    if (request !== revision || !active()) return false;
    if (!saved) { failed(); return false; }
    apply(next);
    return true;
  };
}

export function createStudioViews(api) {
  const { state, els } = api;
  const byId = (id) => document.getElementById(id);
  const buttons = [...document.querySelectorAll("[data-studio-view]")];
  let mounted = false;
  let view = "edit";
  let settings;
  let activeHeading;

  function disclosure(node, title) {
    if (!node) return;
    const details = document.createElement("details");
    details.className = "studio-disclosure";
    const summary = document.createElement("summary");
    summary.textContent = title;
    node.before(details);
    details.append(summary, node);
    return details;
  }

  function wire() {
    mounted = true;
    document.body.classList.add("studio-ready");
    byId("studioSourceHost").append(document.querySelector(".source-pane"));
    settings = document.querySelector(".preview-controls");
    const numbering = settings.querySelector(".numbering-controls");
    settings.prepend(numbering);
    numbering.after(textNode("h3", "studio-output-heading", "출력 설정"));
    byId("studioTitleHost").append(els.exportTitle.closest("label"));
    byId("studioHeaderActions").append(els.previewButton, els.exportButton);
    byId("studioUtilities").append(els.simpleModeButton, els.editorSessionButton,
      els.shortcutHelpButton, els.aiStatusButton);
    const compactHeader = window.matchMedia("(max-width: 640px)");
    const placeRenderAction = () => {
      if (compactHeader.matches) byId("studioUtilities").prepend(els.previewButton);
      else byId("studioHeaderActions").prepend(els.previewButton);
    };
    compactHeader.addEventListener("change", placeRenderAction);
    placeRenderAction();
    document.querySelector(".app-shell").append(els.layoutPlanWarnings, document.querySelector(".preview-footer"));
    byId("studioOrderList").append(els.basketList);
    document.querySelector(".preview-note").textContent = "구성 미리보기는 추정 배치입니다. 실제 페이지는 HWPX 렌더 보기에서 확인하세요.";
    document.querySelector(".preview-pane .pane-titlebar h2").textContent = "구성 미리보기";

    activeHeading = document.createElement("div");
    activeHeading.className = "studio-active-heading";
    els.editorForm.prepend(activeHeading);
    const metadata = disclosure(document.querySelector(".editor-meta-strip"), "문항 정보");
    const recognition = disclosure(byId("contentInspector"), "인식 내용 확인");
    disclosure(document.querySelector(".secondary-side"), "정답·해설");
    const ai = disclosure(document.querySelector(".ai-assistant"), "AI 문항 도구");
    ai.before(metadata, recognition);
    els.editNumber.closest("label").querySelector("span").textContent = "원번호";

    for (const [modalId, closeId] of [["studioSourceModal", "studioSourceClose"], ["studioSettingsModal", "studioSettingsClose"]]) {
      const modal = byId(modalId);
      byId(closeId).addEventListener("click", () => api.closeModal(modal));
      modal.addEventListener("click", (event) => { if (event.target === modal) api.closeModal(modal); });
    }
    byId("studioAddSource").addEventListener("click", () => openSources());
    byId("studioEditSelected").addEventListener("click", () => setView("edit"));
    byId("studioOpenSettings").addEventListener("click", () => {
      if (view === "order") { els.numberingMode.focus(); return; }
      api.openModal(byId("studioSettingsModal"), byId("studioOpenSettings"), els.numberingMode);
    });
    buttons.forEach((button) => button.addEventListener("click", () => setView(button.dataset.studioView)));
    document.querySelector(".studio-view-switcher").addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      const index = buttons.indexOf(event.target);
      if (index < 0) return;
      event.preventDefault();
      const next = event.key === "Home" ? 0 : event.key === "End" ? 2 : (index + (event.key === "ArrowRight" ? 1 : 2)) % 3;
      buttons[next].focus();
      setView(VIEWS[next]);
    });
    for (const control of [els.exportTemplate, els.exportFormat, els.exportAnswerSheet]) {
      control.addEventListener("change", refresh);
    }
    // Keep source import available through existing shortcut/workflow controls.
    byId("studioSourceHost").addEventListener("click", (event) => {
      if (event.target.closest(".problem-row")) refresh();
    });
  }

  function applyView(next) {
    view = next;
    document.body.dataset.studioView = view;
    // Legacy canvas sizing still owns zoom and panning; the new grid owns panels.
    state.panelLayout.sourceCollapsed = false;
    state.panelLayout.previewCollapsed = false;
    byId(view === "order" ? "studioInspector" : "studioSettingsHost").append(settings);
    buttons.forEach((button) => {
      const selected = button.dataset.studioView === view;
      button.setAttribute("aria-pressed", String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    byId("studioEditSelected").hidden = view === "edit";
    byId("studioOpenSettings").hidden = view === "order";
    try { localStorage.setItem(VIEW_KEY, view); } catch { /* A session can work without storage. */ }
    refresh();
    if (view === "paper") {
      state.paperBaseWidth = 720;
      state.paperViewportMode = window.matchMedia("(max-width: 980px)").matches ? "mobile" : "desktop";
      window.requestAnimationFrame(() => api.fitPreviewToStage({ announce: false }));
    }
  }

  // A failed save keeps the view and draft; rapid switches apply only the last request.
  const setView = createViewTransition({ active,
    save: () => api.flushActiveDraft({ quiet: true }), apply: applyView,
    failed: () => api.toast("문항을 저장하지 못했습니다. 편집 내용을 확인한 뒤 다시 전환해 주세요."),
  });

  function openSources() {
    if (!active()) return;
    api.setSideMode("source");
    api.openModal(byId("studioSourceModal"), byId("studioAddSource"), byId("sourceTab"));
  }

  function textNode(tag, className, text) {
    const node = document.createElement(tag);
    node.className = className;
    node.textContent = text;
    return node;
  }

  function refresh() {
    if (!mounted || !active()) return;
    const nav = byId("studioQuestionNav");
    const focusedId = nav.contains(document.activeElement) ? document.activeElement.dataset.problemId : null;
    nav.replaceChildren();
    byId("studioNavCount").textContent = `${state.basket.length}문항`;
    byId("studioEditSelected").disabled = !state.activeId;
    const emptyOrder = els.basketList.querySelector(".basket-empty");
    if (emptyOrder) emptyOrder.textContent = "자료 추가에서 문항을 담으면 이곳에서 순서를 정할 수 있습니다.";
    if (!state.basket.length) nav.append(textNode("p", "studio-nav-empty", "자료를 추가해 첫 문항을 담아보세요."));
    state.basket.forEach((entry, index) => {
      const problem = api.resolveBasketProblem(entry);
      const row = document.createElement("button");
      row.type = "button";
      row.className = "studio-question-link";
      row.dataset.problemId = String(entry.id);
      row.setAttribute("aria-current", String(state.activeId === entry.id));
      row.disabled = Boolean(entry.availability || !problem);
      const number = api.outputNumber(problem, index) || "—";
      row.append(textNode("span", "studio-nav-number", number.padStart(2, "0")));
      const copy = document.createElement("span");
      copy.className = "studio-nav-copy";
      copy.append(textNode("span", "studio-nav-title", problem?.title || (problem?.stem || entry.label).slice(0, 70)),
        textNode("small", "studio-nav-source", problem ? `원본 ${problem.number || "번호 없음"}` : "문항 확인 필요"));
      row.append(copy);
      row.addEventListener("click", async () => { await api.selectProblem(entry.id); refresh(); });
      nav.append(row);
    });
    if (focusedId) nav.querySelector(`[data-problem-id="${Number(focusedId)}"]`)?.focus({ preventScroll: true });

    const selected = state.basket.findIndex((entry) => entry.id === state.activeId);
    const problem = state.problemById.get(state.activeId);
    activeHeading.replaceChildren(
      textNode("strong", "studio-active-number", selected >= 0 ? String(api.outputNumber(problem, selected) || "—").padStart(2, "0") : "문항"),
      textNode("span", "studio-active-source", `원본 ${problem?.number || "번호 없음"}${problem?.subject ? ` · ${problem.subject}` : ""}`),
    );
    for (const row of els.basketList.querySelectorAll(".basket-row")) {
      const index = Number(row.dataset.index);
      const entry = state.basket[index];
      const item = api.resolveBasketProblem(entry);
      let number = row.querySelector(".studio-order-number");
      if (!number) {
        number = textNode("strong", "studio-order-number", "");
        row.querySelector(".basket-body").before(number);
      }
      number.textContent = String(api.outputNumber(item, index) || "—").padStart(2, "0");
      number.setAttribute("aria-label", `출력 번호 ${number.textContent}`);
      row.querySelector(".basket-label").textContent = `원본 ${item?.number || "번호 없음"} · ${item?.title || entry.label}`;
      row.classList.toggle("studio-selected", entry?.id === state.activeId);
    }
    if (view === "paper") renderDocument();
  }

  function renderDocument() {
    const content = byId("studioDocumentContent");
    els.paperLayoutHint.textContent = "구성 확인용 추정 배치 · 최종 줄바꿈과 쪽수는 출력 파일에서 확인하세요.";
    content.replaceChildren();
    content.classList.toggle("two-column", api.currentExportTemplate()?.columns === 2);
    if (!state.basket.length) content.append(textNode("p", "studio-document-empty", "시험지에 담은 문항이 없습니다."));
    state.basket.forEach((entry, index) => {
      const problem = api.resolveBasketProblem(entry);
      const item = document.createElement("article");
      item.className = "studio-document-question";
      item.append(textNode("p", "studio-document-stem", `${api.outputNumber(problem, index) || "—"}. ${problem?.stem || "문항을 확인할 수 없습니다."}`));
      if (problem?.choices?.length) {
        const choices = document.createElement("ol");
        choices.className = "studio-document-choices";
        problem.choices.forEach((choice) => choices.append(textNode("li", "", choice)));
        item.append(choices);
      }
      for (const table of problem?.tables || []) {
        const grid = document.createElement("table");
        for (const cells of table) {
          const row = document.createElement("tr");
          for (const cell of cells) row.append(textNode("td", "", String(cell)));
          grid.append(row);
        }
        item.append(grid);
      }
      for (const url of problem?.image_urls || []) {
        const image = document.createElement("img");
        image.src = url;
        image.alt = `${index + 1}번째 문항 이미지`;
        image.addEventListener("load", () => api.updatePaperCanvasSize({ preserveCenter: true }), { once: true });
        item.append(image);
      }
      content.append(item);
    });
    if (els.exportAnswerSheet.checked && state.basket.length) {
      const answers = textNode("section", "studio-document-answers", "정답·해설");
      state.basket.forEach((entry, index) => {
        const problem = api.resolveBasketProblem(entry);
        answers.append(textNode("p", "", `${api.outputNumber(problem, index) || "—"}. ${problem?.answer || "정답 미입력"}${problem?.explanation ? ` · ${problem.explanation}` : ""}`));
      });
      content.append(answers);
    }
    window.requestAnimationFrame(() => api.updatePaperCanvasSize({ preserveCenter: true }));
  }

  function active() { return state.workspaceStage === "editor" && state.session?.authenticated === true; }
  function enter() {
    if (!active()) return;
    if (!mounted) wire();
    try { const saved = localStorage.getItem(VIEW_KEY); if (VIEWS.includes(saved)) view = saved; } catch { /* Default edit. */ }
    applyView(view);
  }
  return { active, enter, refresh, setView, openSources };
}
