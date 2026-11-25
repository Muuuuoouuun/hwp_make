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
  current: null,
  retryKeys: new Map(),
  quota: null,
  batch: [],
  batchBusy: false,
};
const wantsLogin = new URLSearchParams(location.search).get("login") === "1";
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
    if (response.status === 401 && auth) {
      if (state.user?.guest) showGuestReconnect("게스트 접근이 끝났어요. 새로 연결하면 이전 작업은 불러올 수 없어요.");
      else showAuth();
    }
    const error = new Error(
      typeof data.detail === "string"
        ? data.detail
        : "요청을 처리하지 못했습니다. 다시 시도해 주세요.",
    );
    error.status = response.status;
    throw error;
  }
  return data;
}
function showQuota(quota) {
  if (!state.user?.guest || !quota) return;
  state.quota = quota;
  $("guest-quota").textContent =
    `무료 ${quota.remaining} / ${quota.limit}회` +
    (quota.pending ? ` · 진행 중 ${quota.pending}회 예약` : "");
}
function showGuestReconnect(text) {
  showAuth();
  $("auth").hidden = true;
  $("startup").hidden = false;
  $("startup-message").textContent = text;
  $("guest-reconnect").hidden = false;
}
async function openGuest() {
  const reconnect = $("guest-reconnect");
  reconnect.disabled = true;
  $("startup-message").textContent = "로컬 게스트 작업 공간을 여는 중이에요.";
  try {
    const { user, quota } = await api("/api/guest", { method: "POST", auth: false });
    showWorkspace(user, quota);
  } catch (error) { showGuestReconnect(error.message); }
  finally { reconnect.disabled = false; }
}
$("guest-reconnect").addEventListener("click", openGuest);
function showAuth() {
  state.generation++;
  state.retryKeys.clear();
  renderCurrent(null);
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
  $("startup").hidden = true;
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
function showWorkspace(user, quota) {
  state.generation++;
  state.retryKeys.clear();
  renderCurrent(null);
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
  $("startup").hidden = true;
  $("auth").hidden = true;
  $("workspace").hidden = false;
  $("navigation").hidden = false;
  const guest = Boolean(user.guest);
  $("logout").hidden = guest;
  $("open-bug-report").hidden = guest;
  $("guest-signin").hidden = !guest;
  $("guest-quota").hidden = !guest;
  $("format-row").hidden = guest;
  $("file").accept = guest ? ".pdf,.docx" : ".pdf,.hwp,.hwpx,.docx,.txt";
  $("privacy-title").textContent = guest ? "이 브라우저에서만 확인" : "내 계정에서만 확인";
  $("privacy-copy").textContent = guest
    ? "게스트 세션 시작 후 24시간 동안 이 브라우저에서 결과를 받을 수 있어요."
    : "업로드한 파일과 변환 결과는 내 계정에서만 확인할 수 있어요.";
  $("workspace-copy").textContent = guest
    ? "학습지 PDF를 편집 가능한 한글 문서(HWPX)로 바꾸세요."
    : "파일을 올려두세요. 변환이 끝나면 여기서 다시 받을 수 있어요.";
  $("guide-format").textContent = guest ? "텍스트를 선택할 수 있는 PDF를 사용하세요. DOCX도 지원해요." : "PDF, HWP, HWPX, DOCX, TXT를 지원해요.";
  $("guide-output").textContent = guest ? "HWPX로 받아 문구를 고치세요. 수식과 표 배치는 한글에서 확인하세요." : "HWPX 또는 DOCX로 받을 수 있어요. 수식과 표는 다운로드 후 확인하세요.";
  if (guest) $("format").value = "hwpx";
  const footerNote = $("workspace-footer-note");
  if (footerNote) footerNote.textContent = guest
    ? "게스트 무료 3회 · 실패와 취소는 차감되지 않아요."
    : "PDF 최대 50쪽 · 하루 10회 · 파일은 작업에서 삭제할 수 있어요.";
  $("logout").title = guest ? "" : `${user.name} · ${user.email}`;
  showQuota(quota);
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
  $("choose-file").removeAttribute("aria-describedby");
  message("upload-error", "");
  message("upload-message", "");
  state.file = null;
  state.key = null;
  const filePattern = state.user?.guest ? /\.(pdf|docx)$/i : /\.(pdf|hwp|hwpx|docx|txt)$/i;
  if (
    file &&
    (!filePattern.test(file.name) ||
      file.size > 20 * 1024 * 1024 ||
      !file.size)
  ) {
    const supported = state.user?.guest ? "PDF 또는 DOCX" : "PDF, HWP, HWPX, DOCX 또는 TXT";
    const reason = !file.size
      ? "빈 파일입니다. 내용이 있는 문서를 선택하세요."
      : !filePattern.test(file.name)
        ? `지원하지 않는 파일 형식입니다. ${supported} 파일을 선택하세요.`
        : `파일 크기가 20MB를 넘습니다. 더 작은 문서를 선택하세요. (선택한 파일 ${file.size.toLocaleString("ko-KR")}바이트)`;
    message("upload-error", reason);
    $("choose-file").setAttribute("aria-describedby", "upload-error");
    $("choose-file").focus();
    $("file").value = "";
    file = null;
  }
  state.file = file;
  $("dropzone").classList.toggle("has-file", Boolean(file));
  $("convert").hidden = !file;
  $("file-ready").hidden = !file;
  $("convert").disabled = !file || state.uploading;
  $("file-title").textContent = file ? file.name : (state.user?.guest ? "PDF 학습지를 여기에 끌어다 놓으세요" : "변환할 파일을 선택하세요");
  $("file-meta").textContent = file
    ? `${sizeText(file.size)} · 변환을 시작할 수 있어요.`
    : state.user?.guest
      ? "PDF 최대 50쪽 · 파일당 20MB · DOCX도 지원"
      : "PDF · HWP · HWPX · DOCX · TXT / 최대 20MB";
  $("choose-file").textContent = file ? "다른 파일 선택" : "파일 선택";
  $("convert").textContent = state.uploading ? "접수 중…" : (state.user?.guest ? "한글로 변환" : "변환 시작");
  if (file && !state.uploading) $("convert").focus();
}
$("use-example").addEventListener("click", async () => {
  try {
    const response = await fetch("/web-static/lesson-example.pdf");
    if (!response.ok) throw new Error();
    chooseFile(new File([await response.blob()], "분수-연습지.pdf", {type: "application/pdf"}));
    $("convert").focus();
  } catch {
    message("upload-error", "예시 PDF를 열지 못했어요. 다시 시도해 주세요.");
  }
});
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
  for (const id of ["convert", "choose-file", "use-example", "file", "format", "logout"])
    $(id).disabled = true;
  $("convert").textContent = "업로드하고 접수하는 중…";
  message("upload-error", "");
  message("upload-message", "업로드가 끝날 때까지 이 화면을 열어두세요.");
  try {
    const { job } = await submitFile(state.file, state.user?.guest ? "hwpx" : $("format").value, state.key);
    if (generation !== state.generation) return;
    chooseFile(null);
    $("file").value = "";
    message(
      "upload-message",
      `접수했습니다. 이제 창을 닫아도 변환은 계속돼요. (${job.filename})`,
    );
    renderCurrent(job);
    $("current-job-title").tabIndex = -1;
    $("current-job-title").focus();
    state.offset = 0;
    await refresh();
  } catch (error) {
    if (generation === state.generation) {
      message("upload-message", "");
      message("upload-error", error.message);
    }
  } finally {
    state.uploading = false;
    for (const id of ["choose-file", "use-example", "file", "format", "logout"])
      $(id).disabled = false;
    $("convert").disabled = !state.file;
    $("convert").textContent = state.file ? "다시 접수 시도" : "변환 시작";
    $("convert").hidden = !state.file;
  }
});
async function submitFile(file, format, key) {
  const body = new FormData();
  body.append("file", file);
  body.append("output_format", format);
  const result = await api("/api/jobs", { method: "POST", body, key });
  if (!result.job?.id) throw new Error("접수 결과를 확인하지 못했어요. 다시 접수해 주세요.");
  return result;
}

function renderBatch() {
  const remaining = state.batch.filter(item => item.file);
  const list = $("batch-list");
  list.replaceChildren();
  for (const item of state.batch) {
    const row = document.createElement("li");
    row.textContent = item.name + " · " + item.status;
    list.append(row);
  }
  $("batch-start").hidden = !remaining.length;
  $("batch-start").disabled = state.batchBusy;
  $("batch-start").textContent = state.batchBusy ? "접수 중…" :
    state.batch.some(item => item.attempted) ? "미접수 파일 다시 접수" : remaining.length + "개 파일 접수";
  $("batch-choose").disabled = state.batchBusy;
}
window.addEventListener("hwp-session-change", () => {
  state.batch = [];
  state.batchBusy = false;
  state.quota = null;
  $("batch-files").value = "";
  $("batch-panel").open = false;
  message("batch-message", "");
  message("batch-error", "");
  renderBatch();
});
$("batch-choose").addEventListener("click", () => $("batch-files").click());
$("batch-files").addEventListener("change", () => {
  const files = Array.from($("batch-files").files);
  $("batch-files").value = "";
  if (!files.length || state.batchBusy) return;
  message("batch-error", "");
  if (files.length > 3) {
    message("batch-error", "한 묶음에는 최대 3개까지 선택할 수 있어요.");
    return;
  }
  if (state.batch.some(item => item.uncertain)) {
    message("batch-error", "응답을 받지 못한 파일이 있어요. 미접수 파일 다시 접수를 눌러 기존 접수 여부를 먼저 확인해 주세요.");
    return;
  }
  state.batch = files.map(file => {
    const valid = /\.(pdf|docx)$/i.test(file.name) && file.size > 0 && file.size <= 20 * 1024 * 1024;
    return { name: file.name, file: valid ? file : null, key: crypto.randomUUID(),
      status: valid ? "접수 대기" : "제외 · 20MB 이하의 빈 파일이 아닌 PDF 또는 DOCX를 선택해 주세요." };
  });
  message("batch-message", "");
  renderBatch();
});
$("batch-start").addEventListener("click", async () => {
  if (state.batchBusy || !state.user) return;
  const pending = state.batch.filter(item => item.file);
  if (!pending.length) return;
  message("batch-error", "");
  if (!state.batch.some(item => item.attempted) && state.quota && pending.length > state.quota.remaining) {
    message("batch-error", "현재 접수 가능한 파일은 " + state.quota.remaining + "개예요. 파일을 다시 선택해 주세요.");
    return;
  }
  const generation = state.generation;
  state.batchBusy = true;
  message("batch-message", "접수가 끝날 때까지 이 화면을 열어 두세요.");
  try {
    for (const item of pending) {
      item.attempted = true;
      item.status = "접수 중";
      renderBatch();
      try {
        const {job} = await submitFile(item.file, "hwpx", item.key);
        if (generation !== state.generation) return;
        item.status = "접수됨";
        item.file = null;
        item.uncertain = false;
        renderCurrent(job);
      } catch (error) {
        if (generation !== state.generation) return;
        if ([400, 409, 413, 415, 422].includes(error.status)) {
          item.status = "제외 · " + error.message;
          item.file = null;
          item.uncertain = false;
          continue;
        }
        item.uncertain = !error.status || error.status >= 500;
        item.status = item.uncertain ? "응답 미확인" : "접수 대기";
        message("batch-error", error.message);
        break;
      }
    }
    message("batch-message", state.batch.some(item => item.file)
      ? "접수를 잠시 멈췄어요. 다시 접수하면 이미 접수된 작업을 이어서 확인해요."
      : "접수 처리가 끝났어요. 접수된 파일의 진행 상태와 다운로드는 내 작업에서 확인하세요.");
    await refresh();
  } finally {
    if (generation === state.generation) {
      state.batchBusy = false;
      renderBatch();
    }
  }
});

function renderCurrent(job) {
  state.current = job;
  $("current-job").hidden = !job;
  if (!job) return;
  const info = {
    queued: "접수 완료 · 변환 대기 중",
    running: "변환 중 · 접수했으니 이 창을 닫아도 돼요.",
    validating: "결과 검사 중",
    succeeded: "파일 생성 완료 · 한글에서 수식과 배치를 확인하세요.",
    failed: "변환 실패 · 상세에서 이유를 확인하고 다시 시도할 수 있어요.",
    cancel_requested: "취소 요청됨 · 실제 중단을 기다리는 중이에요.",
    cancelled: "취소됨 · 완료 횟수는 차감되지 않아요.",
  };
  const file = $("current-job-file"), status = $("current-job-status");
  const download = $("current-job-download");
  const icon = job.state === "succeeded" ? "done" : ["failed","cancelled"].includes(job.state) ? "error" : "process";
  $("current-job-title").querySelector(".hand").className = "hand " + (icon === "done" ? "checked" : icon === "error" ? "corrected" : "notebook");
  $("current-job").dataset.state = icon;
  if (file.textContent !== job.filename) file.textContent = job.filename;
  if (status.textContent !== info[job.state]) status.textContent = info[job.state] || "";
  download.hidden = job.state !== "succeeded";
  download.textContent = `${job.format.toUpperCase()} 다운로드`;
  if (job.state === "succeeded") download.href = `/api/jobs/${job.id}/download`;
  else download.removeAttribute("href");
}
function openJobDetail(job) {
  state.detail = job.id;
  renderDetail(job);
  message("detail-error", "");
  $("detail").showModal();
}
$("current-job-detail").addEventListener("click", () => {
  if (state.current) openJobDetail(state.current);
});
function renderJobs() {
  if (!state.jobs.length) {
    const isAll = state.filter === "all";
    $("job-list").innerHTML =
      `<div class="empty"><div><strong>${isAll ? "아직 변환한 파일이 없어요" : "해당 상태의 작업이 없어요"}</strong><p>${isAll ? "첫 파일을 올려 시작해 보세요." : "다른 필터에서 내 작업을 확인해 보세요."}</p></div></div>`;
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
    const tracked = state.current;
    if (!tracked && filter === "all" && offset === 0 && data.items.length)
      renderCurrent(data.items[0]);
    else if (tracked) {
      let latest = data.items.find((j) => j.id === tracked.id);
      if (!latest) {
        try { latest = (await api(`/api/jobs/${tracked.id}`)).job; }
        catch (error) {
          if (error.status === 404 && generation === state.generation && state.current?.id === tracked.id) {
            renderCurrent(null);
            if (state.detail === tracked.id) $("detail").close();
          }
        }
      }
      if (latest && generation === state.generation && state.current?.id === tracked.id)
        renderCurrent(latest);
    }
    if (generation !== state.generation) return;
    showQuota(data.quota);
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
  openJobDetail(job);
});
function renderDetail(job) {
  $("detail-title").textContent = job.filename;
  $("detail-content").dataset.state = job.state;
  const result = job.result;
  $("detail-content").innerHTML =
    `<div class="status ${job.state}">${stateNames[job.state]}</div><dl class="detail-meta"><dt>접수</dt><dd>${escapeHTML(dateText(job.created))}</dd><dt>출력 형식</dt><dd>${job.format.toUpperCase()}</dd><dt>보관 기한</dt><dd>${(state.user?.guest ? "게스트 세션 중 확인 가능" : escapeHTML(dateText(job.created + 30 * 86400)))}</dd>${result ? `<dt>원본 쪽수</dt><dd>${result.source_pages ? `${result.source_pages}쪽` : "미확인"}</dd><dt>인식 문항</dt><dd>${result.problem_count ? `${escapeHTML(result.problem_count)}개` : "미확인"}</dd>` : ""}</dl>${job.error ? `<p class="error">${escapeHTML(job.error)}</p>` : ""}<div class="notices"><strong>${result ? "다운로드 후 확인해 주세요" : "작업 안내"}</strong>${result ? `<ul>${result.warnings.map((w) => `<li>${escapeHTML(w)}</li>`).join("")}</ul>` : `<p>${job.state === "cancel_requested" ? "실제 변환 중단을 확인하고 있어요." : active.has(job.state) ? "접수가 완료되어 창을 닫아도 작업은 계속됩니다. 긴 문서는 몇 분이 걸릴 수 있어요." : "원본을 다시 받거나 작업을 삭제할 수 있어요."}</p>`}</div><div class="detail-actions">${job.state === "succeeded" ? `<a class="primary" href="/api/jobs/${job.id}/download" download>결과 다운로드</a>` : ""}<a href="/api/jobs/${job.id}/download?source=true" download>원본 받기</a>${active.has(job.state) ? `<button id="cancel-job" class="plain danger" type="button" ${job.state === "cancel_requested" ? "disabled" : ""}>변환 취소</button>` : `${["failed", "cancelled"].includes(job.state) ? '<button id="retry-job" class="plain" type="button">다시 시도</button>' : ""}<button id="delete-job" class="plain danger" type="button">작업 삭제</button>`}</div>`;
  const reportButton = document.createElement("button");
  reportButton.id = "report-job";
  reportButton.type = "button";
  reportButton.className = "plain";
  reportButton.textContent = "이 작업 신고";
  if (!state.user?.guest) $("detail-content").querySelector(".detail-actions").append(reportButton);
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
  if (button.disabled) return;
  button.disabled = true;
  message("detail-error", "");
  try {
    if (button.id === "cancel-job")
      await api(`/api/jobs/${jobId}/cancel`, { method: "POST" });
    if (button.id === "delete-job") {
      const result = await api(`/api/jobs/${jobId}`, { method: "DELETE" });
      if (generation === state.generation)
        message("upload-message", result.deletion === "complete"
          ? "원본과 결과를 삭제했어요."
          : "다운로드를 차단했어요. 사용 중인 파일은 로컬 서버가 다시 삭제를 시도해요.");
    }
    if (button.id === "retry-job") {
      if (!state.retryKeys.has(jobId)) state.retryKeys.set(jobId, crypto.randomUUID());
      const {job} = await api(`/api/jobs/${jobId}/retry`, {
        method: "POST",
        key: state.retryKeys.get(jobId),
      });
      if (generation === state.generation) {
        state.retryKeys.delete(jobId);
        renderCurrent(job);
      }
    }
    if (generation !== state.generation) return;
    if (button.id === "delete-job" && state.current?.id === jobId) renderCurrent(null);
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
  if (setupToken) { showAuth(); return; }
  try {
    const { user } = await api("/api/me", { auth: false });
    showWorkspace(user);
    return;
  } catch { /* Account authentication is separate from guest sessions. */ }
  if (wantsLogin) { showAuth(); return; }
  await openGuest();
})();
