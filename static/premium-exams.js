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

  function cancelTimer() { if (timer !== null) clearTimer(timer); timer = null; }

  function accept(result) {
    exam = { id: result.id, revision: result.revision };
    saved = JSON.stringify(pickDraft(result));
    savedText = `저장됨 · ${savedTime(result.updated_at)}`;
    onStatus("saved", savedText);
  }

  async function save() {
    cancelTimer();
    if (!ready || conflict) return !conflict;
    if (inflight) { await inflight; return save(); }
    const raw = snapshot();
    if (!raw) { onStatus("invalid", "번호 설정을 확인하면 저장됩니다"); return false; }
    const draft = pickDraft(raw);
    const body = JSON.stringify(draft);
    if (exam && body === saved) { onStatus("saved", savedText); return true; }
    const run = generation;
    onStatus("saving", "저장 중…");
    inflight = (async () => {
      try {
        const result = exam
          ? await api(`/api/exams/${encodeURIComponent(exam.id)}`, { method: "PUT", body: JSON.stringify({ ...draft, expected_revision: exam.revision }) })
          : await api("/api/exams", { method: "POST", body });
        if (run !== generation) return false;
        accept(result);
        // The result may differ from what we sent only by server normalization.
        return JSON.stringify(pickDraft(raw)) === saved;
      } catch (error) {
        if (run !== generation) return false;
        if (error.status === 409) {
          conflict = true;
          onStatus("conflict", "다른 화면에서 먼저 저장됨");
          onConflict(error.detail?.exam || null);
        } else {
          onStatus("error", error.status === 401 ? "로그인이 만료되어 저장하지 못했습니다" : "저장하지 못했습니다");
        }
        return false;
      } finally {
        inflight = null;
      }
    })();
    return inflight;
  }

  return {
    // Forget the current exam; nothing saves until begin() or start().
    reset() { generation += 1; cancelTimer(); ready = false; exam = null; saved = ""; conflict = false; inflight = null; onStatus("idle", ""); },
    // Continue an exam loaded from the server.
    begin(loaded) { generation += 1; cancelTimer(); inflight = null; ready = true; conflict = false; accept(loaded); },
    // Save the current composition, creating the exam if there is none yet.
    start() { ready = true; return save(); },
    // "저장됨" stays only while the server holds exactly what is on screen.
    schedule() {
      if (!ready || conflict) return;
      const raw = snapshot();
      if (raw && exam && JSON.stringify(pickDraft(raw)) === saved) return;
      cancelTimer();
      onStatus("pending", "저장 전 변경 있음");
      timer = setTimer(() => { timer = null; save(); }, delay);
    },
    // Resolves true only when the server holds the current draft.
    flush() { return ready ? save() : Promise.resolve(true); },
    // Conflict escape: keep this tab's draft as a separate exam. Returns it, or null.
    async keepAsCopy() {
      const raw = snapshot();
      if (!raw) return null;
      const run = ++generation;
      cancelTimer();
      inflight = null;
      const draft = pickDraft(raw);
      draft.title = `${draft.title} (내 변경)`.slice(0, 300);
      try {
        const result = await api("/api/exams", { method: "POST", body: JSON.stringify(draft) });
        if (run !== generation) return null;
        ready = true;
        conflict = false;
        accept(result);
        return result;
      } catch {
        if (run === generation) onStatus("error", "새 시험지로 저장하지 못했습니다");
        return null;
      }
    },
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
