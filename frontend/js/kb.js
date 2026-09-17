/* 知识库：侧边栏列表、新建弹窗（文件/文件夹导入）、更新索引、重命名、删除 */

async function refreshKbs() {
  const r = await API.get("/api/kbs");
  App.state.kbs = r.kbs || [];
  renderKbList();
  refreshKbPicker();
  const busy = App.state.kbs.find(k => k.ingest && k.ingest.running);
  if (busy) pollIngest(busy.id);
}

function renderKbList() {
  const ul = $("kb-list");
  ul.innerHTML = "";
  for (const k of App.state.kbs) {
    const li = document.createElement("li");
    const isActive = App.state.kbIds.length === 1 && App.state.kbIds[0] === k.id;
    li.className = "kb-item" + (isActive ? " active" : "");
    const busy = k.ingest && k.ingest.running;
    const dot = busy ? "busy" : (k.indexed ? "ok" : "bad");
    li.innerHTML = `
      <span class="kb-dot ${dot}"></span>
      <span class="kb-name" title="${escapeHtml(k.name)}">${escapeHtml(k.name)}</span>
      <span class="kb-meta">${k.docs}篇</span>
      <span class="kb-actions">
        <button data-act="add" title="添加文件">＋</button>
        <button data-act="ingest" title="重建索引">⟳</button>
        ${k.builtin ? "" : `<button data-act="exam" title="${k.exam ? "考点管理" : "设为考研资料库"}">🎯</button><button data-act="ocr" title="整本 OCR（扫描版 PDF）">📑</button><button data-act="rename" title="重命名">✎</button><button data-act="del" title="删除">🗑</button>`}
      </span>`;
    li.querySelector(".kb-name").addEventListener("click", () => switchKb(k.id));
    li.querySelectorAll(".kb-actions button").forEach(b => {
      b.addEventListener("click", (e) => { e.stopPropagation(); kbAction(k, b.dataset.act, li); });
    });
    if (busy) {
      const bar = document.createElement("div");
      bar.className = "kb-progress";
      bar.innerHTML = `<div style="width:${k.ingest.pct || 0}%"></div>`;
      li.appendChild(bar);
    }
    ul.appendChild(li);
  }
  // 空状态引导：只有内置库时，提示自建课程库
  if (App.state.kbs.length <= 1) {
    const hint = document.createElement("li");
    hint.className = "kb-hint";
    hint.textContent = "＋ 新建你的课程知识库，开始积累资料";
    hint.addEventListener("click", () => $("btn-new-kb").click());
    ul.appendChild(hint);
  }
}

async function switchKb(kbId) {
  // 侧边栏点库名 = 单选该库（多选用聊天头部选择器）
  App.state.kbIds = [kbId];
  refreshKbPicker();
  renderKbList();
  await newConversation();
}

async function kbAction(k, act, li) {
  if (act === "exam") {
    if (k.exam) openExamTags(k);
    else if (confirm(`将「${k.name}」设为考研资料库？\n导入真题/讲义后可用 AI 自动提取考点标签。`)) {
      await API.patch(`/api/kbs/${k.id}`, { exam: true });
      toast("已设为考研资料库 🎯");
      await refreshKbs();
    }
  } else if (act === "ingest") {
    await API.post(`/api/kbs/${k.id}/ingest`);
    toast(`已开始重建「${k.name}」索引`);
    pollIngest(k.id);
  } else if (act === "rename") {
    const name = prompt("新的知识库名称：", k.name);
    if (name && name.trim()) {
      await API.patch(`/api/kbs/${k.id}`, { name: name.trim() });
      refreshKbs();
    }
  } else if (act === "del") {
    if (!confirm(`确定删除知识库「${k.name}」？其中的文档副本将一并删除。`)) return;
    const r = await API.del(`/api/kbs/${k.id}`);
    if (r.ok) { toast("已删除"); refreshKbs(); }
    else toast("删除失败：" + (r.error || ""));
  } else if (act === "add") {
    await addFilesToKb(k.id);
  } else if (act === "ocr") {
    openOcrPdfModal(k);
  }
}

let pollTimer = null;
function pollIngest(kbId) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const r = await API.get("/api/kbs");
    const k = (r.kbs || []).find(x => x.id === kbId);
    if (!k) { clearInterval(pollTimer); return; }
    const st = k.ingest || {};
    if (!st.running) {
      clearInterval(pollTimer);
      refreshKbs();
      if (st.error) {
        toast(`「${k.name}」索引失败：${st.error}`, 8000);
      } else {
        const errCount = (st.stats && st.stats.errors && st.stats.errors.length) || 0;
        if (errCount > 0) {
          toast(`「${k.name}」索引完成：${k.chunks} 块，但有 ${errCount} 个文件未入库（如扫描版 PDF 需用「📑 整本 OCR」）——详情见 设置 → 语料统计`, 10000);
        } else {
          toast(`「${k.name}」索引完成：${k.chunks} 个知识块`);
        }
      }
      return;
    }
    const li = [...document.querySelectorAll(".kb-item")].find(el => el.querySelector(".kb-name").textContent === k.name);
    if (li) {
      const bar = li.querySelector(".kb-progress");
      if (bar) bar.querySelector("div").style.width = (st.pct || 0) + "%";
    }
  }, 1200);
}

/* ---------- 新建知识库弹窗 ---------- */

function bindKbModal() {
  $("btn-new-kb").addEventListener("click", () => {
    App.state.pendingFiles = [];
    App.state.pendingFolder = null;
    $("kb-name").value = "";
    $("kb-picked").textContent = "未选择";
    $("kb-create-progress").classList.add("hidden");
    $("btn-create-kb").disabled = false;
    $("modal-kb").classList.remove("hidden");
    $("kb-name").focus();
  });
  $("btn-cancel-kb").addEventListener("click", () => $("modal-kb").classList.add("hidden"));

  $("btn-pick-files").addEventListener("click", () => $("file-input").click());
  $("file-input").addEventListener("change", () => {
    App.state.pendingFiles = [...$("file-input").files];
    App.state.pendingFolder = null;
    $("kb-picked").textContent = `已选择 ${App.state.pendingFiles.length} 个文件`;
  });
  $("btn-pick-folder").addEventListener("click", () => $("folder-input").click());
  $("folder-input").addEventListener("change", () => {
    App.state.pendingFolder = [...$("folder-input").files];
    App.state.pendingFiles = [];
    $("kb-picked").textContent = `已选择文件夹（${App.state.pendingFolder.length} 个文档）`;
  });

  $("btn-create-kb").addEventListener("click", async () => {
    const name = $("kb-name").value.trim() || "未命名知识库";
    const hasDocs = App.state.pendingFiles.length || App.state.pendingFolder.length;
    const exam = (document.querySelector('input[name="kb-purpose"]:checked') || {}).value === "exam";
    $("btn-create-kb").disabled = true;
    try {
      const r = await API.post("/api/kbs", { name });
      const kbId = r.id;
      if (exam) await API.patch(`/api/kbs/${kbId}`, { exam: true });
      let imported = 0;
      if (hasDocs) {
        $("kb-create-progress").classList.remove("hidden");
        $("kb-create-msg").textContent = "正在复制文档…";
        if (App.state.pendingFiles.length) {
          const up = await API.upload(`/api/kbs/${kbId}/upload`, App.state.pendingFiles);
          imported = up.imported || 0;
        } else {
          const up = await API.upload(`/api/kbs/${kbId}/upload`, App.state.pendingFolder);
          imported = up.imported || 0;
        }
      }
      $("modal-kb").classList.add("hidden");
      await refreshKbs();
      toast(`知识库「${name}」已创建，导入 ${imported} 篇文档`);
      if (imported) pollIngest(kbId);
      else await API.post(`/api/kbs/${kbId}/ingest`), pollIngest(kbId);
      switchKb(kbId);
    } catch (e) {
      toast("创建失败：" + e.message, 5000);
      $("btn-create-kb").disabled = false;
    }
  });
}

async function addFilesToKb(kbId) {
  const input = $("file-input");
  input.value = "";
  input.click();
  await new Promise(resolve => {
    input.addEventListener("change", async function handler() {
      input.removeEventListener("change", handler);
      if (!input.files.length) return resolve();
      toast(`正在为「${(App.state.kbs.find(k => k.id === kbId) || {}).name}」导入 ${input.files.length} 个文件…`);
      const up = await API.upload(`/api/kbs/${kbId}/upload`, [...input.files]);
      toast(`已导入 ${up.imported || 0} 篇文档，开始建立索引`);
      pollIngest(kbId);
      resolve();
    });
  });
}

/* ---------- 整本 OCR（扫描版 PDF） ---------- */

let pollOcrTimer = null;

function bindOcrPdfModal() {
  $("btn-ocr-pdf-cancel").addEventListener("click", () => $("modal-ocr-pdf").classList.add("hidden"));
}

async function openOcrPdfModal(k) {
  $("modal-ocr-pdf").dataset.kbId = k.id;
  $("ocr-pdf-progress").classList.add("hidden");
  await renderOcrPdfList(k.id);
  $("modal-ocr-pdf").classList.remove("hidden");
}

async function renderOcrPdfList(kbId) {
  const box = $("ocr-pdf-list");
  const k = App.state.kbs.find(x => x.id === kbId) || {};
  const ocrRunning = k.ocr && k.ocr.running;
  const r = await API.get(`/api/kbs/${kbId}/docs`);
  const pdfs = (r.docs || []).filter(d => d.rel.toLowerCase().endsWith(".pdf"));
  if (!pdfs.length) {
    box.innerHTML = `<div class="info-box">该知识库中没有 PDF 文件。先把扫描版 PDF 上传进知识库，再来这里识别。</div>`;
    return;
  }
  box.innerHTML = pdfs.map(d => `
    <div class="ocr-pdf-item">
      <span class="ocr-pdf-name" title="${escapeHtml(d.rel)}">${escapeHtml(d.rel)}</span>
      <span class="hint">${(d.size / 1048576).toFixed(2)} MB · ${escapeHtml(d.mtime)}</span>
      <button class="btn btn-primary" data-rel="${escapeHtml(d.rel)}" ${ocrRunning ? "disabled" : ""}>${ocrRunning ? "识别中…" : "开始识别"}</button>
    </div>`).join("");
  box.querySelectorAll("button[data-rel]").forEach(b => {
    b.addEventListener("click", async () => {
      b.disabled = true;
      b.textContent = "启动中…";
      const r2 = await API.post(`/api/kbs/${kbId}/ocr-pdf`, { rel: b.dataset.rel });
      if (r2.ok) {
        $("ocr-pdf-progress").classList.remove("hidden");
        $("ocr-pdf-bar").style.width = "0%";
        $("ocr-pdf-msg").textContent = "OCR 已启动…";
        pollPdfOcr(kbId);
      } else {
        b.disabled = false;
        b.textContent = "开始识别";
        toast("启动失败：" + (r2.error || ""), 5000);
      }
    });
  });
}

function pollPdfOcr(kbId) {
  clearInterval(pollOcrTimer);
  pollOcrTimer = setInterval(async () => {
    const r = await API.get("/api/kbs");
    const k = (r.kbs || []).find(x => x.id === kbId);
    if (!k) { clearInterval(pollOcrTimer); return; }
    const ocrSt = k.ocr || {};
    const ing = k.ingest || {};
    const bar = $("ocr-pdf-bar");
    const msg = $("ocr-pdf-msg");
    if (ocrSt.running) {
      if (bar) bar.style.width = (ocrSt.pct || 0) + "%";
      if (msg) msg.textContent = `${ocrSt.message || "识别中"}（${ocrSt.current || ""}）`;
      return;
    }
    clearInterval(pollOcrTimer);
    if (ocrSt.error) {
      toast(`整本 OCR 失败：${ocrSt.error}`, 6000);
    } else if (ing.running) {
      if (msg) msg.textContent = "识别完成，正在建立索引…";
      pollIngest(kbId);
    } else {
      if (bar) bar.style.width = "100%";
      if (msg) msg.textContent = "OCR 完成";
      toast("整本 OCR 完成，已加入索引");
    }
    refreshKbs();
    renderOcrPdfList(kbId);
  }, 1500);
}
