/* 应用入口：全局状态、API 封装、视图切换、吐司、初始化 */

const App = {
  state: {
    kbs: [],
    settings: {},
    convId: null,
    kbIds: ["all"],    // 当前知识库选择（id 列表；["all"]=全部），可单选/多选
    streaming: false,
    pendingFiles: [],   // 新建知识库时选择的文件
    pendingFolder: null,
  },
};

const API = {
  async get(url) {
    const r = await fetch(url);
    return r.json();
  },
  async post(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    return r.json();
  },
  async patch(url, body) {
    const r = await fetch(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    return r.json();
  },
  async del(url) {
    const r = await fetch(url, { method: "DELETE" });
    return r.json();
  },
  async upload(url, files) {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    const r = await fetch(url, { method: "POST", body: fd });
    return r.json();
  },
};

let toastTimer = null;
function toast(msg, ms = 3200) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), ms);
}

function showView(name) {
  document.getElementById("view-chat").classList.toggle("hidden", name !== "chat");
  document.getElementById("view-settings").classList.toggle("hidden", name !== "settings");
}

function $(id) { return document.getElementById(id); }

/* ---------- 初始化 ---------- */
async function initApp() {
  // 后端健康检查
  try {
    const h = await API.get("/api/health");
    if (!h.ok) { document.body.innerHTML = "<p style='padding:40px;text-align:center'>后端未就绪</p>"; return; }
  } catch (e) {
    document.body.innerHTML = "<p style='padding:40px;text-align:center'>无法连接后端服务，请重启程序</p>";
    return;
  }

  App.state.settings = await API.get("/api/settings");
  initTheme();
  await refreshKbs();
  await initChat();
  bindSettingsView();
  bindDebugView();
  bindKbModal();
  bindOcrModal();
  bindOcrPdfModal();
  bindNoteModals();
  bindWizard();
  bindFeedback();

  $("btn-open-settings").addEventListener("click", () => openSettings());
  $("btn-back-chat").addEventListener("click", () => showView("chat"));

  // 首次使用引导：完成/跳过后 onboarding_done 置位，不再出现（设置页可重新查看）
  if (!App.state.settings.onboarding_done) {
    openWizard();
  } else {
    showView("chat");
  }
}

document.addEventListener("DOMContentLoaded", initApp);
