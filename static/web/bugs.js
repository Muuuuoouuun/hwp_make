"use strict";
const bugState = { jobId: null, draft: null, submitting: false, loading: 0 };
const bugStatusNames = {
  submitted: "접수됨",
  investigating: "확인 중",
  resolved: "처리 완료",
};
function resetBugUI() {
  bugState.jobId = null;
  bugState.draft = null;
  bugState.submitting = false;
  bugState.loading++;
  $("bug-dialog").close();
  $("bug-form").reset();
  $("bug-list").replaceChildren();
  $("bug-history-refresh").disabled = false;
  $("bug-context").textContent = "";
  message("bug-feedback", "");
  message("bug-error", "");
  setBugBusy(false);
}
window.addEventListener("hwp-session-change", resetBugUI);
function setBugBusy(busy) {
  bugState.submitting = busy;
  for (const id of ["bug-fields", "close-bug", "bug-compose", "bug-history"])
    $(id).disabled = busy;
  $("bug-submit").textContent = busy ? "접수하는 중…" : "신고 접수";
}
function selectBugPanel(history) {
  $("bug-form").hidden = history;
  $("bug-history-panel").hidden = !history;
  $("bug-compose").setAttribute("aria-pressed", String(!history));
  $("bug-history").setAttribute("aria-pressed", String(history));
}
function openBugReport(jobId = null) {
  if (!state.user) return;
  if (bugState.jobId !== jobId) {
    $("bug-form").reset();
    bugState.draft = null;
  }
  bugState.jobId = jobId;
  $("bug-context").textContent = jobId
    ? `연결된 작업: ${jobId}`
    : "작업과 관계없는 화면 문제도 신고할 수 있어요.";
  selectBugPanel(false);
  message("bug-feedback", "");
  message("bug-error", "");
  if (!$("bug-dialog").open) $("bug-dialog").showModal();
  $("bug-subject").focus();
}
$("open-bug-report").addEventListener("click", () => openBugReport());
$("close-bug").addEventListener("click", () => $("bug-dialog").close());
$("bug-dialog").addEventListener("cancel", (event) => {
  if (bugState.submitting) event.preventDefault();
});
$("bug-compose").addEventListener("click", () => {
  selectBugPanel(false);
  message("bug-feedback", "");
  message("bug-error", "");
});
$("bug-history").addEventListener("click", () => {
  selectBugPanel(true);
  loadBugHistory();
});
$("bug-history-refresh").addEventListener("click", loadBugHistory);
$("bug-form").addEventListener("input", () => {
  bugState.draft = null;
});
$("bug-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (bugState.submitting) return;
  const generation = state.generation;
  if (!bugState.draft)
    bugState.draft = {
      key: crypto.randomUUID(),
      payload: {
        title: $("bug-subject").value.trim(),
        category: $("bug-category").value,
        description: $("bug-description").value.trim(),
        steps: $("bug-steps").value.trim(),
        expected: $("bug-expected").value.trim(),
        job_id: bugState.jobId,
        browser: navigator.userAgent.slice(0, 300),
        viewport: {
          width: Math.min(innerWidth, 20000),
          height: Math.min(innerHeight, 20000),
        },
      },
    };
  setBugBusy(true);
  message("bug-error", "");
  message("bug-feedback", "");
  try {
    const { report } = await api("/api/bug-reports", {
      method: "POST",
      body: bugState.draft.payload,
      key: bugState.draft.key,
    });
    if (generation !== state.generation) return;
    $("bug-form").reset();
    bugState.draft = null;
    message(
      "bug-feedback",
      `접수했습니다. 접수 번호: ${report.id}. 내 신고에서 처리 상태를 확인할 수 있어요.`,
    );
    selectBugPanel(true);
    await loadBugHistory();
  } catch (error) {
    if (generation === state.generation) message("bug-error", error.message);
  } finally {
    if (generation === state.generation) setBugBusy(false);
  }
});
async function loadBugHistory() {
  const generation = state.generation,
    request = ++bugState.loading;
  $("bug-history-refresh").disabled = true;
  message("bug-error", "");
  try {
    const data = await api("/api/bug-reports");
    if (generation !== state.generation || request !== bugState.loading) return;
    $("bug-list").innerHTML = data.items.length
      ? data.items
          .map(
            (report) =>
              `<details class="report-item"><summary><span>${escapeHTML(report.title)}</span><span class="report-status">${bugStatusNames[report.status]}</span></summary><p class="job-meta">${escapeHTML(report.id)} · ${escapeHTML(dateText(report.created))}</p><p class="report-text">${escapeHTML(report.description)}</p>${report.steps ? `<h3>재현 방법</h3><p class="report-text">${escapeHTML(report.steps)}</p>` : ""}${report.expected ? `<h3>기대한 결과</h3><p class="report-text">${escapeHTML(report.expected)}</p>` : ""}${report.job_id ? `<p class="job-meta">연결된 작업: ${escapeHTML(report.job_id)}</p>` : ""}${report.reply ? `<div class="notices"><strong>처리 답변</strong><p class="report-text">${escapeHTML(report.reply)}</p></div>` : '<p class="job-meta">아직 처리 답변이 없습니다.</p>'}</details>`,
          )
          .join("")
      : '<p class="notices">접수한 신고가 없습니다.</p>';
  } catch (error) {
    if (generation === state.generation && request === bugState.loading)
      message("bug-error", error.message);
  } finally {
    if (generation === state.generation && request === bugState.loading)
      $("bug-history-refresh").disabled = false;
  }
}
