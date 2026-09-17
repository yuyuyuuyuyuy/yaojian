/* 使用数据面板（S6 埋点）：本机记录的行为数据——查看统计、导出、删除。数据不出本机。 */
(function () {
  function $(id) { return document.getElementById(id); }

  function downloadText(filename, text, mime) {
    const blob = new Blob([text], { type: mime || "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }

  function fmtCounts(counts) {
    const names = {
      question_asked: "提问", answer_done: "回答完成", citation_clicked: "引用核对",
      note_generated: "生成笔记", note_saved_to_kb: "笔记入库", doc_imported: "文档导入",
      card_reviewed: "卡片复习", refusal_followup: "拒答后继续提问",
      feedback_submitted: "提交反馈", key_replaced: "更换 Key", app_launch: "启动",
    };
    const parts = Object.keys(counts).map(k => {
      const label = names[k] || k;
      return `${label} ${counts[k]}`;
    });
    return parts.length ? parts.join(" ｜ ") : "本周暂无行为记录";
  }

  async function loadUsageStats() {
    const box = $("usage-stats");
    try {
      const resp = await fetch("/api/events/stats");
      const data = await resp.json();
      if (!data.ok) throw new Error(data.error || "加载失败");
      const s = data.stats;
      box.innerHTML = `
        <div class="stat-grid">
          <div class="stat-cell"><b>${s.week_effective_sessions}</b><span>本周有效学习会话</span></div>
          <div class="stat-cell"><b>${s.total_events}</b><span>累计行为记录</span></div>
        </div>
        <div class="info-box">统计自 <b>${s.week_start}</b> 起：${fmtCounts(s.week_counts || {})}</div>`;
    } catch (e) {
      box.innerHTML = `<div class="info-box">加载失败：${e.message}</div>`;
    }
  }

  function bindUsage() {
    const tab = document.querySelector('[data-tab="usage"]');
    if (tab && $("btn-usage-export")) {
      tab.addEventListener("click", loadUsageStats);
    }
    $("btn-usage-export").addEventListener("click", async () => {
      try {
        const resp = await fetch("/api/events/export");
        const data = await resp.json();
        if (!data.ok) throw new Error(data.error || "导出失败");
        const date = new Date().toISOString().slice(0, 10).replace(/-/g, "");
        downloadText(`yaojian-usage-${date}.json`, JSON.stringify(data.events, null, 2), "application/json");
        downloadText(`yaojian-usage-${date}-summary.csv`, data.summary_csv, "text/csv;charset=utf-8");
        loadUsageStats();
      } catch (e) {
        alert("导出失败：" + e.message);
      }
    });
    $("btn-usage-clear").addEventListener("click", async () => {
      if (!confirm("确定删除全部使用记录？此操作不可恢复。")) return;
      await fetch("/api/events", { method: "DELETE" });
      loadUsageStats();
    });
  }

  window.addEventListener("DOMContentLoaded", () => {
    loadUsageStats();  // 面板初始数据
    bindUsage();
  });
})();
