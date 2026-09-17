/* 设置页：基本设置表单 + 首次启动向导 + 主题 */

/* ---------- 主题 ---------- */

function applyTheme(theme) {
  /* theme: auto / light / dark。settings.json 为单一事实源，localStorage 仅作启动防闪白镜像。 */
  const dark = theme === "dark" || (theme !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
  try { localStorage.setItem("la_theme", theme || "auto"); } catch (e) {}
}

function initTheme() {
  applyTheme(App.state.settings.theme || "auto");
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", () => {
    if ((App.state.settings.theme || "auto") === "auto") applyTheme("auto");
  });
}

function bindSettingsView() {
  // 标签切换（基本设置 / 召回调试 / 语料统计）
  document.querySelectorAll(".tab").forEach(t => {
    t.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
      t.classList.add("active");
      document.querySelectorAll(".tab-panel").forEach(p => p.classList.add("hidden"));
      $("tab-" + t.dataset.tab).classList.remove("hidden");
      if (t.dataset.tab === "stats") refreshStats();
    });
  });

  $("btn-save-settings").addEventListener("click", saveSettings);

  // 重新查看使用引导（分步向导逻辑见 wizard.js）
  $("btn-reopen-wizard").addEventListener("click", openWizard);

  // 备份与恢复（F13）
  $("btn-backup-export").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.textContent = "正在打包…";
    try {
      const resp = await fetch("/api/backup/export");
      if (!resp.ok) throw new Error("导出失败（HTTP " + resp.status + "）");
      const blob = await resp.blob();
      const dispo = resp.headers.get("Content-Disposition") || "";
      const m = dispo.match(/filename=\"?([^\";]+)\"?/);
      const filename = m ? m[1] : "yaojian-backup.zip";
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      toast(`备份包「${filename}」已导出到下载文件夹 ✅`, 6000);
    } catch (err) {
      toast("导出失败：" + err.message, 5000);
    } finally {
      btn.disabled = false;
      btn.textContent = "⬇ 导出备份包";
    }
  });
  $("btn-backup-pick").addEventListener("click", () => $("backup-file-input").click());
  $("backup-file-input").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    try {
      const resp = await fetch("/api/backup/import", { method: "POST", body: fd });
      const data = await resp.json();
      if (!data.ok) throw new Error(data.error || "校验失败");
      const s = data.summary;
      if (!confirm(`备份包校验通过：${s.kb_count} 个知识库、${s.conv_count} 条对话。\n\n恢复将【覆盖】当前全部数据（旧数据会保留一份可找回）。\n确定继续吗？`)) return;
      const resp2 = await fetch("/api/backup/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: data.token }),
      });
      const d2 = await resp2.json();
      if (!d2.ok) throw new Error(d2.error || "恢复失败");
      alert("恢复完成！请关闭并重新打开药鉴。");
    } catch (err) {
      alert("恢复失败：" + err.message);
    }
  });
}

function openSettings() {
  const s = App.state.settings;
  $("set-api-key").value = "";
  $("set-api-key").placeholder = s.has_key ? "已配置（留空保持不变，输入则替换）" : "未配置（必填）";
  $("set-llm-model").value = s.llm_model || "qwen-plus";
  $("set-embed-model").value = s.embed_model || "text-embedding-v4";
  $("set-ocr-model").value = s.ocr_model || "qwen3-vl-plus";
  $("set-theme").value = s.theme || "auto";
  $("set-top-k").value = s.top_k || 6;
  $("set-threshold").value = s.score_threshold ?? 0.3;
  $("set-card-limit").value = s.card_daily_limit || 20;
  $("data-dir").textContent = s.data_dir || "本机用户数据目录";
  refreshDebugKbSelect();
  loadUsage();
  showView("settings");
}

/* ---------- 用量与费用（F14：本机估算，以控制台账单为准） ---------- */

async function loadUsage() {
  const box = document.getElementById("usage-box");
  if (!box) return;
  try {
    const resp = await fetch("/api/usage");
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || "加载失败");
    const u = data.usage;
    const ocr = u.ocr_pdf_pages ? `＋ PDF 整本 OCR ${u.ocr_pdf_pages} 页` : "";
    box.innerHTML = `<b>本月用量（${u.month_start}）</b>：问答 ${u.qa} 次 ｜ 笔记 ${u.note} 篇 ｜ 图片识别 ${u.ocr_images} 张${ocr}<br>` +
      `<b>估算费用：${u.cost_low} ~ ${u.cost_high} 元</b>（按公开单价区间估算，以百炼控制台账单为准）`;
  } catch (e) {
    box.textContent = "本月用量加载失败：" + e.message;
  }
}

async function saveSettings() {
  const body = {
    api_key: $("set-api-key").value.trim(),
    llm_model: $("set-llm-model").value.trim() || "qwen-plus",
    embed_model: $("set-embed-model").value.trim() || "text-embedding-v4",
    ocr_model: $("set-ocr-model").value.trim() || "qwen3-vl-plus",
    theme: $("set-theme").value || "auto",
    top_k: parseInt($("set-top-k").value) || 6,
    score_threshold: parseFloat($("set-threshold").value) ?? 0.3,
    card_daily_limit: parseInt($("set-card-limit").value) || 20,
  };
  const r = await API.post("/api/settings", body);
  if (r.ok !== undefined && r.ok !== false) {
    App.state.settings = r.settings;
    applyTheme(r.settings.theme || "auto");
    toast("设置已保存");
    $("set-api-key").value = "";
  } else {
    toast("保存失败：" + (r.error || "未知错误"), 5000);
  }
}
