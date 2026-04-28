// ============ UI自动化平台前端逻辑 ============
const API = ""; // 与后端同源

const state = {
  suites: [],
  currentSuiteId: null,
  currentRunId: null,
  pollTimer: null,
  liveWs: null,        // 浏览器画面 WebSocket
  liveFallback: null,  // WebSocket 不可用时的 HTTP 轮询定时器
  frameCount: 0,
};

// ---------- 工具函数 ----------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

async function api(path, opts = {}) {
  const resp = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${text}`);
  }
  return resp.json();
}

function fmtTime(ts) {
  const d = new Date(ts);
  return d.toLocaleTimeString("zh-CN", { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
}

function escapeHtml(s) {
  if (s == null) return "";
  const map = {};
  map["&"] = "&" + "amp;";
  map["<"] = "&" + "lt;";
  map[">"] = "&" + "gt;";
  map['"'] = "&" + "quot;";
  map["'"] = "&" + "#39;";
  return String(s).replace(/[&<>"']/g, c => map[c]);
}

// ---------- 加载用例集 ----------
async function loadSuites() {
  try {
    state.suites = await api("/api/suites");
  } catch (e) {
    console.error("加载用例集失败", e);
    state.suites = [];
  }
  renderSuiteList();
  if (state.currentSuiteId) {
    renderSuiteDetail(state.currentSuiteId);
  }
}

function renderSuiteList() {
  const list = $("#suite-list");
  if (state.suites.length === 0) {
    list.innerHTML = '<div class="empty-tip" style="padding:20px;font-size:12px">暂无用例集<br>点击「+ 新建用例集」开始</div>';
    return;
  }
  list.innerHTML = state.suites.map(s => {
    const caseCount = (s.cases || []).length;
    const tags = (s.tags || []).map(t => `<span class="tag">${escapeHtml(t)}</span>`).join("");
    return `<div class="suite-item ${s.id === state.currentSuiteId ? "active" : ""}" data-id="${s.id}">
      <div class="name">${escapeHtml(s.name)}</div>
      <div class="meta">${caseCount} 条用例 · ${tags || '<span style="color:var(--text-dim)">无标签</span>'}</div>
    </div>`;
  }).join("");
  $$(".suite-item").forEach(el => {
    el.addEventListener("click", () => {
      state.currentSuiteId = el.dataset.id;
      renderSuiteList();
      renderSuiteDetail(el.dataset.id);
    });
  });
}

// ---------- 用例集详情 ----------
function renderSuiteDetail(suiteId) {
  const s = state.suites.find(x => x.id === suiteId);
  const detail = $("#suite-detail");
  if (!s) {
    detail.innerHTML = '<div class="empty-tip">用例集不存在</div>';
    return;
  }
  const casesHtml = (s.cases || []).map((c, i) => renderCaseCard(c, i)).join("") || '<div class="empty-tip">暂无用例，点击「编辑」添加</div>';
  detail.innerHTML = `
    <h2>${escapeHtml(s.name)}</h2>
    <div class="detail-meta">
      ${escapeHtml(s.description || "")} ${s.base_url ? `· <span style="color:var(--cyan)">${escapeHtml(s.base_url)}</span>` : ""}
    </div>
    <div class="detail-actions">
      <button class="btn primary" onclick="runSuite('${s.id}')">▶ 运行整个用例集</button>
      <button class="btn" onclick="editSuite('${s.id}')">✎ 编辑</button>
      <button class="btn ghost" onclick="deleteSuite('${s.id}')">🗑 删除</button>
    </div>
    ${casesHtml}
  `;
}

function renderCaseCard(c, idx) {
  const status = c.status || "";
  const steps = (c.steps || []).map((st, i) => {
    const st_status = st.status || "pending";
    return `<tr>
      <td class="col-idx">${i + 1}</td>
      <td>${escapeHtml(st.description)}</td>
      <td>${escapeHtml(st.expected || "-")}</td>
      <td class="actual">${escapeHtml(st.actual || "-")}</td>
      <td class="col-status"><span class="status-tag ${st_status}">${st_status}</span></td>
    </tr>`;
  }).join("");
  return `<div class="case-card ${status}" data-case-card="${c.id}">
    <div class="case-head-row" onclick="this.parentElement.classList.toggle('open')">
      <div>
        <div class="name">📋 ${escapeHtml(c.name)} ${status ? `<span class="status-tag ${status}">${status}</span>` : ""}</div>
        ${c.precondition ? `<div class="pre">前置：${escapeHtml(c.precondition)}</div>` : ""}
      </div>
      <button class="btn small" onclick="event.stopPropagation(); runCase('${c.id}')">▶ 运行</button>
    </div>
    <div class="case-body">
      <table class="steps-table">
        <thead>
          <tr><th class="col-idx">#</th><th class="col-desc">执行步骤</th><th class="col-exp">预期结果</th><th>实际结果</th><th class="col-status">状态</th></tr>
        </thead>
        <tbody>${steps || '<tr><td colspan="5" style="text-align:center;color:var(--text-dim)">暂无步骤</td></tr>'}</tbody>
      </table>
    </div>
  </div>`;
}

// ---------- 运行 ----------
async function runSuite(suiteId) {
  try {
    const { run_id } = await api(`/api/suites/${suiteId}/run`, { method: "POST" });
    startPolling(run_id);
  } catch (e) { alert("启动运行失败：" + e.message); }
}
async function runCase(caseId) {
  try {
    const { run_id } = await api(`/api/cases/${caseId}/run`, { method: "POST" });
    startPolling(run_id);
  } catch (e) { alert("启动运行失败：" + e.message); }
}

function startPolling(runId) {
  state.currentRunId = runId;
  $("#run-status").className = "badge running";
  $("#run-status").textContent = "执行中";
  $("#run-logs").innerHTML = "";
  $("#run-summary").innerHTML = `<div style="color:var(--text-dim)">run_id: ${runId}</div>`;
  startLiveView(runId);
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    try {
      const r = await api(`/api/runs/${runId}`);
      renderLogs(r.logs || []);
      if (r.status !== "running") {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        $("#run-status").className = `badge ${r.status === "done" ? "done" : "error"}`;
        $("#run-status").textContent = r.status === "done" ? "完成" : "异常";
        renderSummary(r.summary);
        stopLiveView();
        // 刷新用例集列表（展示实际结果）
        await loadSuites();
      }
    } catch (e) {
      console.error(e);
    }
  }, 800);
}

// ---------- 浏览器实时画面 ----------
function startLiveView(runId) {
  stopLiveView();
  state.frameCount = 0;
  const img = $("#live-img");
  const placeholder = $("#live-placeholder");
  const meta = $("#live-meta");
  img.style.display = "none";
  placeholder.style.display = "flex";
  meta.textContent = "连接中...";

  // 方案：WebSocket + HTTP 并行兜底（WebSocket 优先展示，HTTP 作为保险丝）
  // 无论 WebSocket 是否连上，1 秒内没收到帧就启动 HTTP 轮询；
  // 收到帧后 HTTP 轮询自动关闭
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const wsUrl = `${proto}://${location.host}/ws/screencast/${runId}`;
  try {
    const ws = new WebSocket(wsUrl);
    state.liveWs = ws;
    ws.onopen = () => {
      meta.textContent = "WebSocket 已连接，等待画面...";
    };
    ws.onmessage = (ev) => {
      let payload;
      try { payload = JSON.parse(ev.data); } catch { return; }
      if (payload.type === "frame" && payload.data) {
        renderFrame(payload);
        meta.textContent = `实时(WS) · ${state.frameCount} 帧`;
      }
    };
    ws.onerror = () => {
      console.warn("WebSocket error, 启动 HTTP 兜底");
      startLiveHttpFallback(runId, true);
    };
    ws.onclose = () => {
      console.warn("WebSocket closed");
      startLiveHttpFallback(runId, true);
    };
  } catch (e) {
    console.warn("WebSocket 不可用", e);
  }

  // 保险丝：1 秒后若无帧，启动 HTTP 轮询
  setTimeout(() => {
    if (state.frameCount === 0 && state.currentRunId === runId) {
      startLiveHttpFallback(runId, false);
    }
  }, 1000);
}

function renderFrame(payload) {
  const img = $("#live-img");
  const placeholder = $("#live-placeholder");
  img.src = `data:image/${payload.format || "jpeg"};base64,${payload.data}`;
  if (img.style.display === "none") {
    img.style.display = "block";
    placeholder.style.display = "none";
  }
  state.frameCount++;
}

function startLiveHttpFallback(runId, silent) {
  if (state.liveFallback) return;
  if (!silent) console.log("启动 HTTP 画面轮询");
  const meta = $("#live-meta");
  state.liveFallback = setInterval(async () => {
    try {
      const r = await api(`/api/runs/${runId}/frame`);
      if (r && r.data) {
        renderFrame(r);
        meta.textContent = `实时(HTTP) · ${state.frameCount} 帧`;
      }
    } catch (e) { /* ignore */ }
  }, 400);
}

function stopLiveView() {
  if (state.liveWs) {
    try { state.liveWs.close(); } catch {}
    state.liveWs = null;
  }
  if (state.liveFallback) {
    clearInterval(state.liveFallback);
    state.liveFallback = null;
  }
  const meta = $("#live-meta");
  if (meta) {
    meta.textContent = `已结束 · 共 ${state.frameCount} 帧`;
  }
}

function renderLogs(logs) {
  const box = $("#run-logs");
  box.innerHTML = logs.map(l =>
    `<div class="log-line ${l.level}"><span class="log-time">${fmtTime(l.ts)}</span>[${l.level}] ${escapeHtml(l.msg)}</div>`
  ).join("");
  box.scrollTop = box.scrollHeight;
}

function renderSummary(summary) {
  if (!summary) return;
  const dur = summary.duration_ms ? (summary.duration_ms / 1000).toFixed(2) + "s" : "-";
  $("#run-summary").innerHTML = `
    <span class="stat">用例集: <strong>${escapeHtml(summary.suite_name || "-")}</strong></span>
    <span class="stat green">通过: <strong>${summary.passed || 0}</strong></span>
    <span class="stat red">失败: <strong>${summary.failed || 0}</strong></span>
    <span class="stat">总数: <strong>${summary.total || 0}</strong></span>
    <span class="stat">耗时: <strong>${dur}</strong></span>
    ${summary.error ? `<div style="color:var(--red);margin-top:6px">错误: ${escapeHtml(summary.error)}</div>` : ""}
  `;
}

// ---------- 用例集 CRUD ----------
async function deleteSuite(id) {
  if (!confirm("确定删除该用例集？")) return;
  await api(`/api/suites/${id}`, { method: "DELETE" });
  if (state.currentSuiteId === id) state.currentSuiteId = null;
  await loadSuites();
  if (!state.currentSuiteId) $("#suite-detail").innerHTML = '<div class="empty-tip">请选择左侧用例集</div>';
}

function openSuiteModal(suite) {
  $("#suite-modal-title").textContent = suite ? "编辑用例集" : "新建用例集";
  $("#suite-id").value = suite?.id || "";
  $("#suite-name").value = suite?.name || "";
  $("#suite-desc").value = suite?.description || "";
  $("#suite-baseurl").value = suite?.base_url || "";
  $("#suite-tags").value = (suite?.tags || []).join(",");
  const list = $("#case-list-edit");
  list.innerHTML = "";
  (suite?.cases || []).forEach(c => list.appendChild(buildCaseBlock(c)));
  if (!suite) list.appendChild(buildCaseBlock());
  showModal("modal-suite");
}

function buildCaseBlock(c = {}) {
  const tpl = $("#tpl-case").content.cloneNode(true);
  const root = tpl.querySelector("[data-case]");
  root.dataset.caseId = c.id || "";
  root.querySelector("[data-case-name]").value = c.name || "";
  root.querySelector("[data-case-pre]").value = c.precondition || "";
  const stepsBox = root.querySelector("[data-steps]");
  (c.steps && c.steps.length ? c.steps : [{}]).forEach(st => stepsBox.appendChild(buildStepRow(st)));

  root.querySelector("[data-case-del]").addEventListener("click", () => root.remove());
  root.querySelector("[data-step-add]").addEventListener("click", () => {
    stepsBox.appendChild(buildStepRow());
    renumber(root);
  });
  renumber(root);
  return root;
}

function buildStepRow(st = {}) {
  const tpl = $("#tpl-step").content.cloneNode(true);
  const row = tpl.querySelector("[data-step]");
  row.dataset.stepId = st.id || "";
  row.querySelector("[data-step-desc]").value = st.description || "";
  row.querySelector("[data-step-exp]").value = st.expected || "";
  row.querySelector("[data-step-del]").addEventListener("click", () => {
    const parent = row.closest("[data-case]");
    row.remove();
    if (parent) renumber(parent);
  });
  return row;
}

function renumber(caseBlock) {
  caseBlock.querySelectorAll("[data-step]").forEach((r, i) => {
    r.querySelector("[data-step-idx]").textContent = i + 1;
  });
}

function collectSuiteFromModal() {
  const id = $("#suite-id").value || undefined;
  const name = $("#suite-name").value.trim();
  if (!name) { alert("请填写用例集名称"); return null; }
  const tags = $("#suite-tags").value.split(",").map(t => t.trim()).filter(Boolean);
  const cases = $$("#case-list-edit [data-case]").map(block => ({
    id: block.dataset.caseId || undefined,
    name: block.querySelector("[data-case-name]").value.trim() || "未命名用例",
    precondition: block.querySelector("[data-case-pre]").value.trim(),
    steps: $$("[data-step]", block).map(row => ({
      id: row.dataset.stepId || undefined,
      description: row.querySelector("[data-step-desc]").value.trim(),
      expected: row.querySelector("[data-step-exp]").value.trim(),
    })).filter(st => st.description),
  }));
  return {
    id,
    name,
    description: $("#suite-desc").value.trim(),
    base_url: $("#suite-baseurl").value.trim(),
    tags,
    cases,
  };
}

async function saveSuite() {
  const data = collectSuiteFromModal();
  if (!data) return;
  try {
    if (data.id) {
      await api(`/api/suites/${data.id}`, { method: "PUT", body: JSON.stringify(data) });
    } else {
      const created = await api("/api/suites", { method: "POST", body: JSON.stringify(data) });
      state.currentSuiteId = created.id;
    }
    hideModal("modal-suite");
    await loadSuites();
  } catch (e) {
    alert("保存失败：" + e.message);
  }
}

function editSuite(id) {
  const s = state.suites.find(x => x.id === id);
  openSuiteModal(s);
}

// ---------- 配置 ----------
async function loadConfig() {
  const cfg = await api("/api/config");
  $("#cfg-llm-enabled").checked = !!cfg.llm.enabled;
  $("#cfg-llm-baseurl").value = cfg.llm.base_url || "";
  $("#cfg-llm-apikey").value = "";
  $("#cfg-llm-apikey").placeholder = cfg.llm.api_key_masked || "sk-...";
  $("#cfg-llm-model").value = cfg.llm.model || "";
  $("#cfg-headless").checked = !!cfg.browser.headless;
  $("#cfg-browser").value = cfg.browser.browser || "chromium";
  $("#cfg-timeout").value = cfg.browser.default_timeout || 10000;
}

async function saveConfig() {
  const payload = {
    llm: {
      enabled: $("#cfg-llm-enabled").checked,
      base_url: $("#cfg-llm-baseurl").value.trim(),
      model: $("#cfg-llm-model").value.trim(),
    },
    browser: {
      headless: $("#cfg-headless").checked,
      browser: $("#cfg-browser").value,
      default_timeout: Number($("#cfg-timeout").value) || 10000,
    },
  };
  const apiKey = $("#cfg-llm-apikey").value.trim();
  if (apiKey) payload.llm.api_key = apiKey;
  try {
    await api("/api/config", { method: "POST", body: JSON.stringify(payload) });
    hideModal("modal-config");
    alert("配置已保存");
  } catch (e) { alert("保存失败：" + e.message); }
}

// ---------- 关键词帮助 ----------
async function loadHelp() {
  try {
    const r = await api("/api/keywords");
    $("#help-text").textContent = r.help;
  } catch (e) { $("#help-text").textContent = "加载失败"; }
}

async function testParse() {
  const sentence = $("#parse-input").value.trim();
  if (!sentence) return;
  try {
    const r = await api("/api/parse", { method: "POST", body: JSON.stringify({ sentence }) });
    $("#parse-result").textContent = `来源: ${r.source}\n${JSON.stringify(r.action, null, 2)}`;
  } catch (e) { $("#parse-result").textContent = "解析失败: " + e.message; }
}

// ---------- 弹窗工具 ----------
function showModal(id) { $("#" + id).classList.remove("hidden"); }
function hideModal(id) { $("#" + id).classList.add("hidden"); }

// ---------- 初始化 ----------
document.addEventListener("DOMContentLoaded", () => {
  $("#btn-new-suite").addEventListener("click", () => openSuiteModal(null));
  $("#btn-run-all").addEventListener("click", () => {
    if (state.currentSuiteId) runSuite(state.currentSuiteId);
    else alert("请先选择一个用例集");
  });
  $("#btn-config").addEventListener("click", async () => { await loadConfig(); showModal("modal-config"); });
  $("#btn-help").addEventListener("click", async () => { await loadHelp(); showModal("modal-help"); });
  $("#btn-save-config").addEventListener("click", saveConfig);
  $("#btn-save-suite").addEventListener("click", saveSuite);
  $("#btn-test-parse").addEventListener("click", testParse);
  $("#btn-add-case").addEventListener("click", () => $("#case-list-edit").appendChild(buildCaseBlock()));

  // 关闭按钮
  $$("[data-close]").forEach(el => el.addEventListener("click", () => hideModal(el.dataset.close)));
  $$(".modal").forEach(m => m.addEventListener("click", (e) => { if (e.target === m) m.classList.add("hidden"); }));

  // 暴露给 inline onclick
  window.runSuite = runSuite;
  window.runCase = runCase;
  window.editSuite = editSuite;
  window.deleteSuite = deleteSuite;

  loadSuites();
});