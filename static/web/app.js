"use strict";
const $ = (id) => document.getElementById(id);
const stateNames = {
  queued: "대기 중",
  running: "변환 중",
  validating: "결과 검사 중",
  succeeded: "완료",
  failed: "실패",
  cancel_requested: "취소 요청됨",
  cancelled: "취소됨",
};
const active = new Set(["queued", "running", "validating", "cancel_requested"]);
const state = {
  user: null,
  file: null,
  key: null,
  filter: "all",
  offset: 0,
  total: 0,
  jobs: [],
  generation: 0,
  loading: false,
  uploading: false,
  detail: null,
  renderKey: null,
};
let setupToken = new URLSearchParams(location.hash.slice(1)).get("setup");
if (setupToken) history.replaceState(null, "", location.pathname);
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const sizeText = (bytes) =>
  bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))}KB`
    : `${(bytes / 1024 / 1024).toFixed(1)}MB`;
const dateText = (seconds) =>
  new Intl.DateTimeFormat("ko-KR", {
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(seconds * 1000));
function message(id, text) {
  $(id).textContent = text;
  $(id).hidden = !text;
}
async function api(path, { method = "GET", body, key, auth = true } = {}) {
  const headers = { "X-HWP-Request": "1" };
  if (key) headers["Idempotency-Key"] = key;
  if (body && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body,
      credentials: "same-origin",
    });
  } catch {
    throw new Error(
      "서버에 연결하지 못했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.",
    );
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && auth) showAuth();
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "요청을 처리하지 못했습니다. 다시 시도해 주세요.",
    );
  }
  return data;
}
function showAuth() {
  state.generation++;
  window.dispatchEvent(new Event("hwp-session-change"));
  state.user = null;
  state.jobs = [];
  state.detail = null;
  state.file = null;
  state.key = null;
  state.offset = 0;
  state.loading = false;
  $("file").value = "";
  $("job-list").replaceChildren();
  $("detail").close();
  $("detail-content").replaceChildren();
  $("password").value = "";
  $("workspace").hidden = true;
  $("navigation").hidden = true;
  $("auth").hidden = false;
  $("name-field").hidden = !setupToken;
  $("name").required = Boolean(setupToken);
  $("password").autocomplete = setupToken ? "new-password" : "current-password";
  $("auth-title").textContent = setupToken
    ? "내 문서 공간을 시작하세요"
    : "내 문서 작업을 이어가세요";
  $("auth-description").textContent = setupToken
    ? "처음 사용할 계정을 만들어 주세요. 이 설정 링크는 한 번만 사용할 수 있어요."
    : "초대받은 계정으로 로그인하세요. 자료와 변환 결과는 내 계정에서만 볼 수 있어요.";
  $("login-submit").textContent = setupToken ? "계정 만들고 시작" : "로그인";
}
function showWorkspace(user) {
  state.generation++;
  window.dispatchEvent(new Event("hwp-session-change"));
  state.user = user;
  state.file = null;
  state.key = null;
  state.jobs = [];
  state.filter = "all";
  state.offset = 0;
  state.loading = false;
  state.renderKey = null;
  $("auth-form").reset();
  $("auth").hidden = true;
  $("workspace").hidden = false;
  $("navigation").hidden = false;
  $("logout").title = `${user.name} · ${user.email}`;
  $("file").value = "";
  chooseFile(null);
  message("auth-error", "");
  message("upload-message", "");
  message("upload-error", "");
  document
    .querySelectorAll("[data-filter]")
    .forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.filter === "all")),
    );
  $("job-list").innerHTML =
    '<div class="empty"><p>내 작업을 불러오고 있어요.</p></div>';
  refresh();
}
$("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  message("auth-error", "");
  $("login-submit").disabled = true;
  try {
    const body = {
      email: $("email").value.trim(),
      password: $("password").value,
    };
    if (setupToken) {
      body.name = $("name").value.trim();
      body.token = setupToken;
    }
    const data = await api(setupToken ? "/api/setup" : "/api/login", {
      method: "POST",
      body,
      auth: false,
    });
    setupToken = null;
    showWorkspace(data.user);
  } catch (error) {
    message("auth-error", error.message);
  } finally {
    $("login-submit").disabled = false;
  }
});
$("logout").addEventListener("click", async () => {
  $("logout").disabled = true;
  try {
    await api("/api/logout", { method: "POST" });
    showAuth();
  } catch (error) {
    message("jobs-error", error.message);
  } finally {
    $("logout").disabled = false;
  }
});
function chooseFile(file) {
  message("upload-error", "");
  message("upload-message", "");
  state.file = null;
  state.key = null;
  if (
    file &&
    (!/\.(pdf|hwp|hwpx|docx|txt)$/i.test(file.name) ||
      file.size > 20 * 1024 * 1024 ||
      !file.size)
  ) {
    message(
      "upload-error",
      !file.size
        ? "빈 파일은 변환할 수 없습니다."
        : "20MB 이하의 PDF, HWP, HWPX, DOCX, TXT 파일을 선택해 주세요.",
    );
    $("file").value = "";
    file = null;
  }
  state.file = file;
  $("file-title").textContent = file ? file.name : "변환할 파일을 놓아주세요";
  $("file-meta").textContent = file
    ? `${sizeText(file.size)} · 전체 내용을 보존해 변환합니다`
    : "PDF · HWP · HWPX · DOCX · TXT / 최대 20MB";
  $("choose-file").textContent = file ? "다른 파일 선택" : "파일 선택";
}
$("choose-file").addEventListener("click", () => $("file").click());
$("file").addEventListener("change", () =>
  chooseFile($("file").files[0] || null),
);
$("format").addEventListener("change", () => {
  state.key = null;
});
for (const name of ["dragenter", "dragover"]) {
  $("dropzone").addEventListener(name, (event) => {
    event.preventDefault();
    if (!state.uploading) $("dropzone").classList.add("dragging");
  });
}
$("dropzone").addEventListener("dragleave", () =>
  $("dropzone").classList.remove("dragging"),
);
$("dropzone").addEventListener("drop", (event) => {
  event.preventDefault();
  $("dropzone").classList.remove("dragging");
  if (state.uploading) return;
  if (event.dataTransfer.files.length !== 1) {
    message("upload-error", "한 번에 파일 하나를 선택해 주세요.");
    return;
  }
  chooseFile(event.dataTransfer.files[0]);
});
$("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.uploading) return;
  if (!state.file) {
    message("upload-error", "먼저 변환할 파일을 선택해 주세요.");
    $("choose-file").focus();
    return;
  }
  const generation = state.generation;
  state.uploading = true;
  state.key ||= crypto.randomUUID();
  for (const id of ["convert", "choose-file", "file", "format", "logout"])
    $(id).disabled = true;
  $("convert").textContent = "업로드하고 접수하는 중…";
  message("upload-error", "");
  message("upload-message", "업로드가 끝날 때까지 이 화면을 열어두세요.");
  try {
    const body = new FormData();
    body.append("file", state.file);
    body.append("output_format", $("format").value);
    const { job } = await api("/api/jobs", {
      method: "POST",
      body,
      key: state.key,
    });
    if (generation !== state.generation) return;
    chooseFile(null);
    $("file").value = "";
    message(
      "upload-message",
      `접수했습니다. 이제 창을 닫아도 변환은 계속돼요. (${job.filename})`,
    );
    state.offset = 0;
    await refresh();
  } catch (error) {
    if (generation === state.generation) {
      message("upload-message", "");
      message("upload-error", error.message);
    }
  } finally {
    state.uploading = false;
    for (const id of ["convert", "choose-file", "file", "format", "logout"])
      $(id).disabled = false;
    $("convert").textContent = "변환 시작";
  }
});
function renderJobs() {
  if (!state.jobs.length) {
    const isAll = state.filter === "all";
    $("job-list").innerHTML =
      `<div class="empty"><img src="/web-static/mark.svg" alt=""><div><strong>${isAll ? "아직 변환한 파일이 없어요" : "해당 상태의 작업이 없어요"}</strong><p>${isAll ? "첫 파일을 올려 시작해 보세요." : "다른 필터에서 내 작업을 확인해 보세요."}</p></div></div>`;
  } else {
    $("job-list").innerHTML = state.jobs
      .map(
        (job) =>
          `<article class="job-row"><div><div class="filename">${escapeHTML(job.filename)}</div><p class="job-meta">${escapeHTML(dateText(job.created))} · ${sizeText(job.input_size)} → ${job.format.toUpperCase()}</p></div><div class="status ${job.state}">${stateNames[job.state]}</div><div class="row-actions">${job.state === "succeeded" ? `<a href="/api/jobs/${job.id}/download" download>다운로드</a>` : ""}<button type="button" data-detail="${job.id}" aria-label="${escapeHTML(job.filename)} 상세 보기">상세 보기</button></div></article>`,
      )
      .join("");
  }
  $("pagination").hidden = state.total <= 50;
  $("previous").disabled = state.offset === 0;
  $("next").disabled = state.offset + 50 >= state.total;
  $("page-label").textContent =
    `${Math.floor(state.offset / 50) + 1} / ${Math.max(1, Math.ceil(state.total / 50))}`;
}
async function refresh() {
  if (!state.user || state.loading) return;
  state.loading = true;
  const generation = state.generation,
    filter = state.filter,
    offset = state.offset;
  $("refresh").disabled = true;
  try {
    const data = await api(`/api/jobs?offset=${offset}&status=${filter}`);
    if (
      generation !== state.generation ||
      filter !== state.filter ||
      offset !== state.offset
    )
      return;
    const focused = document.activeElement?.dataset?.detail;
    const previous = state.jobs.map((j) => `${j.id}:${j.state}`).join();
    state.jobs = data.items;
    state.total = data.total;
    const renderKey = JSON.stringify([
      filter,
      offset,
      data.total,
      data.items.map((j) => [
        j.id,
        j.filename,
        j.format,
        j.input_size,
        j.state,
        j.created,
        j.result,
        j.error,
      ]),
    ]);
    if (renderKey !== state.renderKey) {
      state.renderKey = renderKey;
      renderJobs();
      if (focused)
        Array.from(document.querySelectorAll("[data-detail]"))
          .find((b) => b.dataset.detail === focused)
          ?.focus();
    }
    message("jobs-error", "");
    if (
      previous &&
      previous !== state.jobs.map((j) => `${j.id}:${j.state}`).join()
    )
      $("poll-status").textContent = "작업 상태가 업데이트되었습니다.";
    if (state.detail && $("detail").open) {
      const detailId = state.detail;
      const job =
        state.jobs.find((j) => j.id === detailId) ||
        (await api(`/api/jobs/${detailId}`)).job;
      if (
        generation === state.generation &&
        state.detail === detailId &&
        $("detail").open &&
        $("detail-content").dataset.state !== job.state
      )
        renderDetail(job);
    }
  } catch (error) {
    if (generation === state.generation) message("jobs-error", error.message);
  } finally {
    if (generation === state.generation) {
      state.loading = false;
      $("refresh").disabled = false;
      if (filter !== state.filter || offset !== state.offset) refresh();
    }
  }
}
$("refresh").addEventListener("click", refresh);
document.querySelectorAll("[data-filter]").forEach((button) =>
  button.addEventListener("click", () => {
    state.filter = button.dataset.filter;
    state.offset = 0;
    document
      .querySelectorAll("[data-filter]")
      .forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    refresh();
  }),
);
$("previous").addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - 50);
  refresh();
});
$("next").addEventListener("click", () => {
  state.offset += 50;
  refresh();
});
$("job-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-detail]");
  if (!button) return;
  const job = state.jobs.find((j) => j.id === button.dataset.detail);
  if (!job) return;
  state.detail = job.id;
  renderDetail(job);
  message("detail-error", "");
  $("detail").showModal();
});
function renderDetail(job) {
  $("detail-title").textContent = job.filename;
  $("detail-content").dataset.state = job.state;
  const result = job.result;
  $("detail-content").innerHTML =
    `<div class="status ${job.state}">${stateNames[job.state]}</div><dl class="detail-meta"><dt>접수</dt><dd>${escapeHTML(dateText(job.created))}</dd><dt>출력 형식</dt><dd>${job.format.toUpperCase()}</dd><dt>보관 기한</dt><dd>${escapeHTML(dateText(job.created + 30 * 86400))}</dd>${result ? `<dt>원본 쪽수</dt><dd>${result.source_pages ? `${result.source_pages}쪽` : "미확인"}</dd><dt>인식 문항</dt><dd>${result.problem_count ? `${escapeHTML(result.problem_count)}개` : "미확인"}</dd>` : ""}</dl>${job.error ? `<p class="error">${escapeHTML(job.error)}</p>` : ""}<div class="notices"><strong>${result ? "다운로드 후 확인해 주세요" : "작업 안내"}</strong>${result ? `<ul>${result.warnings.map((w) => `<li>${escapeHTML(w)}</li>`).join("")}</ul>` : `<p>${job.state === "cancel_requested" ? "실제 변환 중단을 확인하고 있어요." : active.has(job.state) ? "접수가 완료되어 창을 닫아도 작업은 계속됩니다. 긴 문서는 몇 분이 걸릴 수 있어요." : "원본을 다시 받거나 작업을 삭제할 수 있어요."}</p>`}</div><div class="detail-actions">${job.state === "succeeded" ? `<a class="primary" href="/api/jobs/${job.id}/download" download>결과 다운로드</a>` : ""}<a href="/api/jobs/${job.id}/download?source=true" download>원본 받기</a>${active.has(job.state) ? `<button id="cancel-job" class="plain danger" type="button" ${job.state === "cancel_requested" ? "disabled" : ""}>변환 취소</button>` : `${["failed", "cancelled"].includes(job.state) ? '<button id="retry-job" class="plain" type="button">다시 시도</button>' : ""}<button id="delete-job" class="plain danger" type="button">작업 삭제</button>`}</div>`;
  const reportButton = document.createElement("button");
  reportButton.id = "report-job";
  reportButton.type = "button";
  reportButton.className = "plain";
  reportButton.textContent = "이 작업 신고";
  $("detail-content").querySelector(".detail-actions").append(reportButton);
}
$("close-detail").addEventListener("click", () => $("detail").close());
$("detail").addEventListener("close", () => {
  state.detail = null;
});
$("detail-content").addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const jobId = state.detail,
    generation = state.generation;
  if (button.id === "report-job") {
    $("detail").close();
    openBugReport(jobId);
    return;
  }
  if (button.id === "delete-job" && button.dataset.confirm !== "yes") {
    button.dataset.confirm = "yes";
    button.textContent = "원본·결과 모두 삭제";
    message(
      "detail-error",
      "삭제하면 이 작업의 원본과 결과를 다시 받을 수 없습니다. 한 번 더 누르면 삭제합니다.",
    );
    return;
  }
  button.disabled = true;
  message("detail-error", "");
  try {
    if (button.id === "cancel-job")
      await api(`/api/jobs/${jobId}/cancel`, { method: "POST" });
    if (button.id === "delete-job")
      await api(`/api/jobs/${jobId}`, { method: "DELETE" });
    if (button.id === "retry-job")
      await api(`/api/jobs/${jobId}/retry`, {
        method: "POST",
        key: crypto.randomUUID(),
      });
    if (generation !== state.generation) return;
    if (button.id !== "cancel-job") $("detail").close();
    await refresh();
  } catch (error) {
    if (generation === state.generation) message("detail-error", error.message);
  } finally {
    button.disabled = false;
  }
});
setInterval(() => {
  if (!document.hidden && state.user) refresh();
}, 2500);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});
(async () => {
  try {
    const { user } = await api("/api/me", { auth: false });
    setupToken = null;
    showWorkspace(user);
  } catch {
    showAuth();
  }
})();
