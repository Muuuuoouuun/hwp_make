// A small, dismissible hint: no modal backdrop and no first-visit focus capture.
export function initSimpleHelp({ openSettings } = {}) {
  const panel = document.getElementById("aiHelpPopover");
  const triggers = Array.from(document.querySelectorAll("[data-ai-help]"));
  if (!panel || !triggers.length) return;
  const closeButton = document.getElementById("aiHelpClose");
  const settingsButton = document.getElementById("aiHelpSettings");
  const description = document.getElementById("aiHelpDescription");
  const storageKey = "hwpMakeAiHelpSeen.v1";
  let anchor = null;

  const visibleTrigger = () => triggers.find((button) => button.getClientRects().length > 0);
  const place = () => {
    if (panel.hidden || !anchor) return;
    const rect = anchor.getBoundingClientRect();
    const gap = 12;
    panel.style.left = `${Math.max(gap, Math.min(rect.right - panel.offsetWidth, window.innerWidth - panel.offsetWidth - gap))}px`;
    const below = rect.bottom + 10;
    panel.style.top = `${Math.max(gap, Math.min(below, window.innerHeight - panel.offsetHeight - gap))}px`;
  };
  const close = (restoreFocus = false) => {
    panel.hidden = true;
    triggers.forEach((button) => button.setAttribute("aria-expanded", "false"));
    if (restoreFocus && anchor?.getClientRects().length) anchor.focus();
  };
  const show = (button, focus = false) => {
    anchor = button;
    const checkbox = document.getElementById(document.body.classList.contains("simple-converter-mode") ? "simpleMathAi" : "layoutMathAi");
    description.textContent = checkbox && !checkbox.disabled
      ? "PDF 수식 인식에 연결된 Gemini를 사용할 수 있어요. PDF를 선택한 뒤 옵션을 켜세요."
      : "AI 없이도 변환할 수 있어요. PDF 수식 인식이 필요할 때만 Gemini 키를 연결하세요.";
    panel.hidden = false;
    triggers.forEach((trigger) => trigger.setAttribute("aria-expanded", String(trigger === button)));
    place();
    try { localStorage.setItem(storageKey, "1"); } catch { /* This visit still works without storage. */ }
    if (focus) closeButton.focus();
  };
  triggers.forEach((button) => button.addEventListener("click", () => {
    if (!panel.hidden && anchor === button) close(true);
    else show(button, true);
  }));
  closeButton.addEventListener("click", () => close(true));
  settingsButton.addEventListener("click", () => {
    close(true);
    openSettings?.();
  });
  document.addEventListener("pointerdown", (event) => {
    if (!panel.hidden && !panel.contains(event.target) && !triggers.some((button) => button.contains(event.target))) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) {
      event.preventDefault();
      event.stopImmediatePropagation();
      close(true);
    }
  }, true);
  window.addEventListener("resize", place);
  window.addEventListener("scroll", place, true);
  // A mode switch can hide the anchor. Never leave a detached hint over the next screen.
  const observer = new MutationObserver(() => {
    if (!panel.hidden && anchor && !anchor.getClientRects().length) close();
  });
  observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });
  let seen = false;
  try { seen = localStorage.getItem(storageKey) === "1"; } catch { /* Show once for this page only. */ }
  if (!seen) {
    const button = visibleTrigger();
    if (button) show(button);
  }
}
