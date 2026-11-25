// Server-saved premium exams. One save runs at a time; later edits queue behind it.
// A stale revision stops saving until the user picks the latest copy or keeps theirs
// as a new exam, so another tab's work is never overwritten.
const DEFAULT_TITLE = "새 시험지";

// The exact shape the server stores, so "unchanged" is a string comparison.
export function pickDraft(source) {
  return {
    title: String(source.title || "").trim().slice(0, 300) || DEFAULT_TITLE,
    items: (source.items || []).map(({ id, label }) => ({ id, label: String(label || "").slice(0, 200) })),
    numbering_mode: source.numbering_mode,
    start_number: source.start_number,
    template_key: source.template_key,
    format: source.format,
    include_answer_sheet: Boolean(source.include_answer_sheet),
  };
}

export function savedTime(seconds, now = new Date()) {
  const date = new Date(seconds * 1000);
  const time = date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  return date.toDateString() === now.toDateString() ? time : `${date.getMonth() + 1}월 ${date.getDate()}일 ${time}`;
}

// snapshot() returns the current draft, or null while it cannot be saved (invalid start number).
export function createExamSync({ api, snapshot, onStatus, onConflict, delay = 800, setTimer = setTimeout, clearTimer = clearTimeout }) {
  let ready = false;
  let exam = null;
  let saved = "";
  let savedText = "";
  let conflict = false;
  let timer = null;
  let inflight = null;
  let generation = 0;

  let copying = null;
  let failed = false; // the last request failed (not a conflict); flush stops retrying

  function cancelTimer() { if (timer !== null) clearTimer(timer); timer = null; }

  function accept(result) {
    exam = { id: result.id, revision: result.revision };
    failed = false;
    saved = JSON.stringify(pickDraft(result));
    savedText = `저장됨 · ${savedTime(result.updated_at)}`;
  }

  // Emit exactly one status for what is on screen now versus the server copy.
  function settle() {
    const now = snapshot();
    if (!now) { onStatus("invalid", "번호 확인 필요"); return false; }
    if (JSON.stringify(pickDraft(now)) === saved) { onStatus("saved", savedText); return true; }
    onStatus("pending", "저장 전 변경 있음");
    cancelTimer();
    timer = setTimer(() => { timer = null; save(); }, delay);
    return false;
  }

  function matchesScreen() {
    const now = snapshot();
    return Boolean(now) && JSON.stringify(pickDraft(now)) === saved;
  }

  async function save() {
    cancelTimer();
    if (!ready || conflict) return !conflict;
    if (inflight) {
      const waitingFor = generation;
      await inflight;
      return waitingFor === generation ? save() : false;
    }
    const raw = snapshot();
    if (!raw) { onStatus("invalid", "번호 확인 필요"); return false; }
    const draft = pickDraft(raw);
    const body = JSON.stringify(draft);
    if (exam && body === saved) return settle();
    const run = generation;
    // Fast saves never flash "저장 중"; only a slow one shows it.
    const slow = setTimer(() => { if (run === generation) onStatus("saving", "저장 중"); }, 400);
    inflight = (async () => {
      try {
        const result = exam
          ? await api(`/api/exams/${encodeURIComponent(exam.id)}`, { method: "PUT", body: JSON.stringify({ ...draft, expected_revision: exam.revision }) })
          : await api("/api/exams", { method: "POST", body });
        if (run !== generation) return false;
        accept(result);
        return settle();
      } catch (error) {
        if (run !== generation) return false;
        if (error.status === 409) {
          conflict = true;
          onStatus("conflict", "자동 저장 멈춤");
          onConflict(error.detail?.exam || null);
        } else {
          failed = true;
          onStatus("error", error.status === 401 ? "로그인이 만료되어 저장하지 못했습니다" : "저장하지 못했습니다");
        }
        return false;
      } finally {
        clearTimer(slow);
        // A request from an exam that was since closed must not clear the new exam's request.
        if (run === generation) inflight = null;
      }
    })();
    return inflight;
  }

  return {
    // Forget the current exam; nothing saves until begin() or start().
    reset() { generation += 1; cancelTimer(); ready = false; exam = null; saved = ""; conflict = false; failed = false; inflight = null; copying = null; onStatus("idle", ""); },
    // Continue an exam loaded from the server.
    begin(loaded) { generation += 1; cancelTimer(); inflight = null; copying = null; ready = true; conflict = false; accept(loaded); onStatus("saved", savedText); },
    // Save the current composition, creating the exam if there is none yet.
    start() { ready = true; return save(); },
    // "저장됨" stays only while the server holds exactly what is on screen.
    schedule() {
      if (!ready || conflict) return;
      const raw = snapshot();
      // While a request is in flight the server copy is about to change, so never skip.
      if (!inflight && raw && exam && JSON.stringify(pickDraft(raw)) === saved) return;
      cancelTimer();
      onStatus("pending", "저장 전 변경 있음");
      timer = setTimer(() => { timer = null; save(); }, delay);
    },
    // Resolves true only when the server holds what is on screen at that moment.
    async flush() {
      if (!ready) return true;
      const started = generation;
      for (let attempt = 0; attempt < 5; attempt += 1) {
        // Success only if the screen still matches after the await (it may have changed meanwhile).
        if (await save() && started === generation && matchesScreen()) return true;
        // A flush begun for one exam never continues into the next one.
        if (started !== generation) return false;
        if (conflict || failed || !snapshot()) return false; // a real failure, not just newer edits
      }
      return false;
    },
    // Conflict escape: keep this tab's draft as a separate exam. Returns it, or null.
    // `applied(copy)` runs before comparing, so the caller can show the copy's title first.
    keepAsCopy(applied = () => {}) {
      // A second click while the copy is being made reuses the same request.
      if (copying) return copying;
      const raw = snapshot();
      if (!raw) return Promise.resolve(null);
      const run = ++generation;
      cancelTimer();
      inflight = null;
      const draft = pickDraft(raw);
      draft.title = `${draft.title} (내 변경)`.slice(0, 300);
      copying = (async () => {
        try {
          const result = await api("/api/exams", { method: "POST", body: JSON.stringify(draft) });
          if (run !== generation) return null;
          ready = true;
          conflict = false;
          accept(result);
          applied(result);
          // Edits made while the copy was being created are saved next, not hidden.
          settle();
          return result;
        } catch {
          // Stay in the conflict so both ways out remain on screen.
          if (run === generation) onStatus("conflict", "자동 저장 멈춤");
          return null;
        } finally {
          copying = null;
        }
      })();
      return copying;
    },
    // True while something on screen is not confirmed by the server.
    dirty() { return ready && (timer !== null || inflight !== null || copying !== null || conflict || failed || !matchesScreen()); },
    current() { return exam ? { ...exam } : null; },
  };
}

// Rows for the "내 시험지" list. Handlers receive the exam summary. The exam open in
// the editor (editingId) cannot be deleted or reopened from here.
export function renderExamList(container, exams, { open, duplicate, remove }, editingId = null) {
  container.replaceChildren();
  if (!exams.length) {
    const empty = document.createElement("p");
    empty.className = "exam-list-empty";
    empty.textContent = "저장한 시험지가 없습니다. 파일을 넣어 문항을 편집하면 자동으로 저장됩니다.";
    container.append(empty);
    return;
  }
  for (const exam of exams) {
    const row = document.createElement("div");
    row.className = "exam-list-row";
    const copy = document.createElement("div");
    copy.className = "exam-list-copy";
    const title = document.createElement("strong");
    title.textContent = exam.title;
    const meta = document.createElement("small");
    const numbering = exam.numbering_mode === "preserve" ? "원번호 유지"
      : exam.item_count ? `${exam.start_number}~${exam.start_number + exam.item_count - 1}번` : `${exam.start_number}번부터`;
    meta.textContent = `${exam.item_count}문항 · ${numbering} · ${savedTime(exam.updated_at)} 저장`;
    copy.append(title, meta);
    const actions = document.createElement("div");
    actions.className = "exam-list-actions";
    const editing = exam.id === editingId;
    if (editing) meta.textContent += " · 편집 중";
    for (const [label, handler, className] of [["열기", open, "primary"], ["복제", duplicate, "ghost"], ["삭제", remove, "ghost danger"]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = className;
      button.textContent = label;
      button.disabled = editing && handler !== duplicate;
      button.setAttribute("aria-label", `${exam.title} ${label}`);
      button.addEventListener("click", () => handler(exam));
      actions.append(button);
    }
    row.append(copy, actions);
    container.append(row);
  }
}
