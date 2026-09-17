/* 聊天视图：SSE 流式渲染、引用折叠展开、回答快捷操作、多轮、导出、历史会话 */

const EXAMPLE_CHIPS = [
  "检测药物内一般杂质的基础项目和合格范围是什么？",
  "什么是重金属检查法？它分几种方法？",
  "药物的降压作用机制是什么？",
];

/* ---------- 知识库选择器（单选/多选/全部） ---------- */

function kbScopeLabel() {
  const ids = App.state.kbIds;
  if (ids.length === 1) {
    if (ids[0] === "all") return "全部知识库";
    return (App.state.kbs.find(k => k.id === ids[0]) || {}).name || "问答";
  }
  return `已选 ${ids.length} 个知识库`;
}

function refreshKbPicker() {
  $("btn-kb-picker").textContent = kbScopeLabel() + " ▾";
  $("chat-title").textContent = "问答（" + kbScopeLabel() + "）";
  const menu = $("kb-picker-menu");
  const selected = new Set(App.state.kbIds);
  menu.innerHTML =
    `<label class="kb-pick-item">
       <input type="checkbox" class="kb-pick-box" data-id="all" ${selected.has("all") ? "checked" : ""}>
       <span>全部知识库</span>
     </label>` +
    App.state.kbs.map(k => `
      <label class="kb-pick-item">
        <input type="checkbox" class="kb-pick-box" data-id="${k.id}" ${selected.has(k.id) ? "checked" : ""}>
        <span class="kb-pick-name">${escapeHtml(k.name)}${k.builtin ? ` <em class="kb-pick-tag">内置</em>` : ""}</span>
        <span class="kb-pick-meta">${k.docs}篇</span>
      </label>`).join("") +
    `<div class="kb-picker-foot">已选 ${selected.has("all") ? "全部" : `${selected.size} 个`} · 切换后开启新对话</div>`;
}

async function applyKbSelection(ids) {
  App.state.kbIds = ids;
  refreshKbPicker();
  renderKbList();
  await newConversation();
}

/* ---------- 空状态（含引导） ---------- */

function renderEmptyState() {
  const ids = App.state.kbIds;
  let guide = "";
  if (ids.length === 1 && ids[0] !== "all") {
    const k = App.state.kbs.find(x => x.id === ids[0]);
    if (k && !k.docs) {
      guide = `<div class="empty-guide">
        <p>「${escapeHtml(k.name)}」还没有文档。先导入资料或拍照识字，再来提问。</p>
      </div>`;
    }
  }
  const box = $("messages");
  box.innerHTML = `
    <div class="empty-state">
      <h2>🧪 你好，我是药鉴</h2>
      <p>我能依据知识库资料回答问题，并标注引用来源。点击回答中的 <span class="cite">[1]</span> 徽章，可在回答下方定位并展开原文。</p>
      <div class="empty-chips">
        ${EXAMPLE_CHIPS.map(q => `<button class="chip" data-q="${escapeHtml(q)}">${escapeHtml(q)}</button>`).join("")}
      </div>
      ${guide}
      <div class="empty-actions">
        <button class="chip" id="empty-upload">📄 上传资料</button>
        <button class="chip" id="empty-ocr">📷 拍照识字</button>
      </div>
    </div>`;
  box.querySelectorAll(".chip[data-q]").forEach(ch => {
    ch.addEventListener("click", () => { $("input").value = ch.dataset.q; $("input").focus(); });
  });
  const up = $("empty-upload");
  if (up) up.addEventListener("click", () => {
    if (App.state.kbIds.length === 1 && App.state.kbIds[0] !== "all") addFilesToKb(App.state.kbIds[0]);
    else $("btn-new-kb").click();
  });
  const oc = $("empty-ocr");
  if (oc) oc.addEventListener("click", () => $("btn-ocr").click());
}

/* ---------- 会话 ---------- */

async function initChat() {
  await refreshKbPicker();
  await newConversation();
  bindChatEvents();
}

async function newConversation() {
  if (App.state.streamCtrl) App.state.streamCtrl.abort();
  const r = await API.post("/api/conversations", { kb_ids: App.state.kbIds });
  App.state.convId = r.id;
  renderEmptyState();
  App.state.streaming = false;
  $("btn-send").disabled = false;
}

function addMessageEl(role) {
  const box = $("messages");
  const empty = box.querySelector(".empty-state");
  if (empty) empty.remove();
  const msg = document.createElement("div");
  msg.className = "msg " + role;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  msg.appendChild(bubble);
  box.appendChild(msg);
  box.scrollTop = box.scrollHeight;
  return { msg, bubble };
}

/* ---------- 消息渲染（流式完成与历史载入共用） ---------- */

function buildCitationsEl(citations) {
  const sec = document.createElement("div");
  sec.className = "citations";
  const title = document.createElement("div");
  title.className = "citations-title";
  title.innerHTML = `<span>📚 引用来源（${citations.length} 条）</span>
    <span class="citations-actions">
      <button class="citations-toggle" data-act="expand-all">全部展开</button>
      <button class="citations-toggle" data-act="collapse-all">全部收起</button>
    </span>`;
  sec.appendChild(title);
  citations.forEach(c => {
    const item = document.createElement("div");
    item.className = "src-item";
    const page = c.page ? ` · 第${c.page}页` : "";
    const file = (c.kb_name ? c.kb_name + "｜" : "") + (c.source || c.file || "") + page;
    item.innerHTML = `
      <div class="src-item-head">
        <span class="src-n">[${c.n}]</span>
        <span class="src-file">${escapeHtml(file)}</span>
        <span class="src-score">相似度 ${c.score}</span>
      </div>
      <div class="src-item-body">${escapeHtml(c.text)}</div>`;
    sec.appendChild(item);
  });
  sec.querySelectorAll(".citations-toggle").forEach(b => {
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = b.dataset.act === "expand-all";
      sec.querySelectorAll(".src-item").forEach(it => it.classList.toggle("open", open));
    });
  });
  return sec;
}

function addAsstActions(msg, bubble) {
  const bar = document.createElement("div");
  bar.className = "asst-actions";
  bar.innerHTML = `
    <button class="asst-act" data-act="copy" title="复制全文">📋 复制</button>
    <button class="asst-act" data-act="stop" title="停止生成">⏹ 停止</button>
    <button class="asst-act hidden" data-act="regen" title="重新生成">🔄 重新生成</button>`;
  bubble.appendChild(bar);
  return bar;
}

function renderAssistantMessage(msg, text, citations, isLast) {
  /* 渲染一条已完成的助手消息（历史载入用） */
  const bubble = msg.querySelector(".bubble");
  const content = document.createElement("div");
  content.className = "md-content";
  content.innerHTML = renderMd(text);
  bubble.appendChild(content);
  if (citations && citations.length) bubble.appendChild(buildCitationsEl(citations));
  msg.dataset.answer = text;
  if (citations) msg.dataset.citations = JSON.stringify(citations);
  const bar = addAsstActions(msg, bubble);
  bar.querySelector('[data-act="stop"]').classList.add("hidden");
  if (isLast) bar.querySelector('[data-act="regen"]').classList.remove("hidden");
}

/* ---------- 发送与流式回答 ---------- */

async function sendMessage() {
  const input = $("input");
  const question = input.value.trim();
  if (!question || App.state.streaming || !App.state.convId) return;
  input.value = "";
  input.style.height = "auto";
  const userEl = addMessageEl("user");
  userEl.bubble.textContent = question;
  const asst = addMessageEl("assistant");
  prepareStreamingBubble(asst);
  await streamAnswer(asst, question, false);
}

function prepareStreamingBubble(asst) {
  asst.bubble.classList.add("streaming");
  const content = document.createElement("div");
  content.className = "md-content";
  asst.bubble.appendChild(content);
  addAsstActions(asst.msg, asst.bubble);
}

async function streamAnswer(asst, question, regenerate) {
  const convId = App.state.convId;  // 固定本次回答归属的会话（中途切库不影响）
  App.state.streaming = true;
  $("btn-send").disabled = true;
  const content = asst.bubble.querySelector(".md-content");
  let text = "";
  let renderTimer = null;
  const scheduleRender = () => {
    if (renderTimer) return;
    renderTimer = setTimeout(() => { content.innerHTML = renderMd(text); renderTimer = null; }, 80);
  };

  const ctrl = new AbortController();
  App.state.streamCtrl = ctrl;
  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, kb_ids: App.state.kbIds, conv_id: convId, regenerate }),
      signal: ctrl.signal,
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const line = chunk.trim();
        if (!line.startsWith("data:")) continue;
        let obj;
        try { obj = JSON.parse(line.slice(5).trim()); } catch (e) { continue; }
        if (obj.delta) { text += obj.delta; scheduleRender(); }
        if (obj.error) {
          // F14：余额类错误给友好提示（其余错误原样展示）
          const err = String(obj.error);
          const isBalance = /arrear|balance|insufficient|quota|limit|余额|额度|欠费/i.test(err);
          text += isBalance
            ? "\n\n> ⚠️ API 余额可能不足或已达限额。可：①前往[百炼控制台](https://bailian.console.aliyun.com/)充值 ②在设置页填入自己的 Key（设置 → API Key）。\n>\n> 原始错误：" + err
            : "\n\n> ⚠️ 出错了：" + err;
          scheduleRender();
        }
        if (obj.done !== undefined) {
          finalizeMessage(asst, content, text, obj.citations || []);
          break;
        }
      }
    }
  } catch (e) {
    const aborted = e.name === "AbortError";
    content.innerHTML = renderMd(text + (aborted ? "\n\n> ⏹ 已停止生成。" : `\n\n> ⚠️ 请求失败：${e.message}`));
    if (aborted) {
      // 补存半截回答，保持历史问答配对
      try { await API.post(`/api/conversations/${convId}/messages`, { role: "assistant", content: text }); } catch (err) {}
    } else {
      toast("回答失败：" + e.message, 5000);
    }
  } finally {
    App.state.streamCtrl = null;
    App.state.streaming = false;
    $("btn-send").disabled = false;
    asst.bubble.classList.remove("streaming");
    asst.msg.dataset.answer = text;
    const bar = asst.bubble.querySelector(".asst-actions");
    if (bar) {
      bar.querySelector('[data-act="stop"]').classList.add("hidden");
      bar.querySelector('[data-act="regen"]').classList.remove("hidden");
    }
    const box = $("messages");
    box.scrollTop = box.scrollHeight;
  }
}

function finalizeMessage(asst, content, text, citations) {
  asst.bubble.classList.remove("streaming");
  content.innerHTML = renderMd(text);
  asst.msg.dataset.citations = JSON.stringify(citations);
  asst.msg.dataset.answer = text;
  if (citations.length) {
    const cit = buildCitationsEl(citations);
    const bar = asst.bubble.querySelector(".asst-actions");
    asst.bubble.insertBefore(cit, bar);
  }
  const box = $("messages");
  box.scrollTop = box.scrollHeight;
}

/* ---------- 回答快捷操作 ---------- */

async function copyAnswer(msg) {
  const text = msg.dataset.answer || "";
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    toast("已复制全文");
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); toast("已复制全文"); } catch (e2) { toast("复制失败，请手动选择复制"); }
    ta.remove();
  }
}

async function regenerateAnswer(msg) {
  if (App.state.streaming) return;
  const prev = msg.previousElementSibling;
  const question = prev && prev.classList.contains("user") ? prev.querySelector(".bubble").textContent.trim() : "";
  if (!question) return toast("找不到对应的提问");
  const bubble = msg.querySelector(".bubble");
  bubble.innerHTML = "";
  prepareStreamingBubble({ msg, bubble });
  await streamAnswer({ msg, bubble }, question, true);
}

/* ---------- 历史会话 ---------- */

function kbScopeName(ids) {
  if (!ids || !ids.length) return "全部知识库";
  if (ids.length === 1) {
    if (ids[0] === "all") return "全部知识库";
    return (App.state.kbs.find(k => k.id === ids[0]) || {}).name || "未知知识库";
  }
  return `${ids.length} 个知识库`;
}

async function openHistory() {
  const r = await API.get("/api/conversations");
  const convs = r.conversations || [];
  const box = $("history-list");
  if (!convs.length) {
    box.innerHTML = `<div class="history-empty">暂无历史对话</div>`;
  } else {
    box.innerHTML = convs.map(c => `
      <div class="history-item" data-id="${c.id}">
        <div class="history-main">
          <div class="history-title">${escapeHtml(c.title || "新对话")}</div>
          <div class="history-meta">${escapeHtml(c.created_at || "")} · ${escapeHtml(kbScopeName(c.kb_ids))}</div>
        </div>
        <button class="icon-btn history-del" data-act="del" title="删除该对话">🗑</button>
      </div>`).join("");
    box.querySelectorAll(".history-item").forEach(item => {
      item.addEventListener("click", async () => {
        await loadConversation(item.dataset.id);
        $("modal-history").classList.add("hidden");
      });
      item.querySelector(".history-del").addEventListener("click", async (e) => {
        e.stopPropagation();
        await API.del(`/api/conversations/${item.dataset.id}`);
        toast("已删除该对话");
        openHistory();
      });
    });
  }
  $("modal-history").classList.remove("hidden");
}

async function loadConversation(convId) {
  const r = await API.get(`/api/conversations/${convId}/messages`);
  const msgs = r.messages || [];
  App.state.convId = convId;
  // 同步该会话的知识库作用域到选择器
  const convs = (await API.get("/api/conversations")).conversations || [];
  const conv = convs.find(c => c.id === convId);
  if (conv && conv.kb_ids && conv.kb_ids.length) {
    App.state.kbIds = conv.kb_ids;
    refreshKbPicker();
    renderKbList();
  }
  const box = $("messages");
  box.innerHTML = "";
  if (!msgs.length) { renderEmptyState(); return; }
  msgs.forEach((m, i) => {
    const el = addMessageEl(m.role === "user" ? "user" : "assistant");
    if (m.role === "user") {
      el.bubble.textContent = m.content;
    } else {
      renderAssistantMessage(el.msg, m.content, m.citations || [], i === msgs.length - 1);
    }
  });
  App.state.streaming = false;
  $("btn-send").disabled = false;
}

/* ---------- 事件绑定 ---------- */

function bindChatEvents() {
  $("btn-kb-picker").addEventListener("click", (e) => {
    e.stopPropagation();
    $("kb-picker-menu").classList.toggle("hidden");
  });
  document.addEventListener("click", () => {
    $("kb-picker-menu").classList.add("hidden");
    $("export-menu").classList.add("hidden");
  });
  $("kb-picker-menu").addEventListener("click", (e) => {
    e.stopPropagation();
    const box = e.target.closest("input[type=checkbox]");
    if (!box) return;
    const id = box.dataset.id;
    const selected = new Set(App.state.kbIds);
    if (id === "all") {
      if (box.checked) applyKbSelection(["all"]);
      else refreshKbPicker();  // 「全部」不允许取消（空选即全部）
    } else {
      selected.delete("all");
      if (box.checked) selected.add(id);
      else selected.delete(id);
      if (!selected.size) selected.add("all");
      applyKbSelection([...selected]);
    }
  });

  $("btn-new-conv").addEventListener("click", () => newConversation());
  $("btn-clear-conv").addEventListener("click", async () => {
    if (App.state.convId) await API.del(`/api/conversations/${App.state.convId}`);
    await newConversation();
    toast("已清空对话");
  });
  $("btn-history").addEventListener("click", openHistory);
  $("btn-history-close").addEventListener("click", () => $("modal-history").classList.add("hidden"));

  const input = $("input");
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 140) + "px";
  });
  $("btn-send").addEventListener("click", () => sendMessage());

  // 导出下拉
  $("btn-export").addEventListener("click", (e) => {
    e.stopPropagation();
    $("export-menu").classList.toggle("hidden");
  });
  $("export-menu").querySelectorAll("button").forEach(b => {
    b.addEventListener("click", async () => {
      $("export-menu").classList.add("hidden");
      await exportNote(b.dataset.format);
    });
  });

  // 消息区事件委托：引用徽章 / 引用条目 / 快捷操作
  $("messages").addEventListener("click", (e) => {
    const cite = e.target.closest(".cite");
    if (cite) {
      const msgEl = cite.closest(".msg");
      // 埋点：引用核对行为（仅本机记录；信任过程指标）
      try {
        const count = parseInt(sessionStorage.getItem("la_cite_count") || "0", 10) + 1;
        sessionStorage.setItem("la_cite_count", String(count));
        fetch("/api/events/citation", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            conv_id: App.state.convId || null,
            session_order: count,
            ref_index: parseInt(cite.dataset.cite || "1", 10),
          }),
        }).catch(() => {});
      } catch (e) { /* 埋点失败静默 */ }
      if (msgEl && msgEl.dataset.citations) {
        const n = parseInt(cite.dataset.cite) - 1;
        const item = msgEl.querySelectorAll(".src-item")[n];
        if (item) {
          item.classList.add("open");
          item.scrollIntoView({ behavior: "smooth", block: "center" });
          item.classList.remove("flash");
          void item.offsetWidth;  // 重触发高亮动画
          item.classList.add("flash");
        }
      }
      return;
    }
    const head = e.target.closest(".src-item-head");
    if (head) { head.parentElement.classList.toggle("open"); return; }
    const act = e.target.closest(".asst-act");
    if (act) {
      const msg = act.closest(".msg");
      if (act.dataset.act === "copy") copyAnswer(msg);
      else if (act.dataset.act === "stop") { if (App.state.streamCtrl) App.state.streamCtrl.abort(); }
      else if (act.dataset.act === "regen") regenerateAnswer(msg);
    }
  });
}

async function exportNote(format) {
  if (!App.state.convId) return toast("当前没有对话内容");
  const r = await API.post("/api/export", { conv_id: App.state.convId, format });
  if (r.ok) toast(`已导出：${r.path}`, 6000);
  else toast("导出失败：" + (r.error || "未知错误"), 5000);
}
