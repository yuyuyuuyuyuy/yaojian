/* F8 考研场景包：考点管理——AI 自动提取 + 人工修正（标注可见可改）。 */
(function () {
  function $(id) { return document.getElementById(id); }
  let currentKb = null;

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  async function loadExamTags() {
    const body = $("exam-tags-body");
    body.innerHTML = `<div class="note-loading">⏳ 加载考点…</div>`;
    const r = await API.get(`/api/kbs/${currentKb.id}/tags`);
    if (!r.ok) { body.innerHTML = `<div class="info-box">加载失败：${escapeHtml(r.error || "")}</div>`; return; }
    const files = Object.keys(r.tags);
    body.innerHTML = "";
    if (!files.length && !r.pending.length) {
      body.innerHTML = `<div class="info-box">还没有文档。先给这个库导入真题/讲义（点知识库旁的 ＋）。</div>`;
      return;
    }
    for (const f of files) {
      const box = document.createElement("div");
      box.className = "exam-file";
      box.innerHTML = `
        <div class="exam-file-head">📄 ${escapeHtml(f)}</div>
        <div class="exam-tag-list">
          ${r.tags[f].map(t => `<span class="exam-tag">${escapeHtml(t.tag)} <button class="exam-tag-del" data-id="${t.id}" title="删除该考点">×</button></span>`).join("")}
          <button class="exam-tag-add" data-file="${escapeHtml(f)}">＋ 加考点</button>
        </div>`;
      box.querySelectorAll(".exam-tag-del").forEach(b => {
        b.addEventListener("click", async () => {
          await API.del(`/api/kbs/${currentKb.id}/tags/${b.dataset.id}`);
          loadExamTags();
        });
      });
      box.querySelector(".exam-tag-add").addEventListener("click", () => {
        const tag = prompt(`为「${f}」添加考点标签：`);
        if (tag) API.post(`/api/kbs/${currentKb.id}/tags`, { file_name: f, tag }).then(loadExamTags);
      });
      body.appendChild(box);
    }
    if (r.pending.length) {
      const box = document.createElement("div");
      box.className = "exam-file exam-pending";
      box.innerHTML = `
        <div class="exam-file-head">⏳ 待分析（${r.pending.length} 个文件）：${r.pending.map(escapeHtml).join("、")}</div>
        <button class="btn btn-primary" id="btn-exam-analyze">🤖 AI 提取考点（约 1~2 分/文件，共 ${r.pending.length} 个）</button>`;
      box.querySelector("#btn-exam-analyze").addEventListener("click", async (e) => {
        const btn = e.target;
        btn.disabled = true;
        btn.textContent = "分析中…（失败的文件会跳过，可重试）";
        const r2 = await API.post(`/api/kbs/${currentKb.id}/tags/analyze`, {});
        toast(r2.ok ? `已分析 ${r2.analyzed} 个文件` : "分析失败：" + (r2.error || ""));
        loadExamTags();
      });
      body.appendChild(box);
    }
  }

  function openExamTags(kb) {
    currentKb = kb;
    $("exam-kb-name").textContent = `「${kb.name}」的考点分布：AI 自动标记，可手动增删修正`;
    $("modal-exam-tags").classList.remove("hidden");
    loadExamTags();
  }

  window.addEventListener("DOMContentLoaded", () => {
    $("btn-exam-close").addEventListener("click", () => $("modal-exam-tags").classList.add("hidden"));
    $("btn-exam-unset").addEventListener("click", async () => {
      if (!confirm(`将「${currentKb.name}」切换为普通课程库？已提取的考点会被保留（不再显示入口）。`)) return;
      await API.patch(`/api/kbs/${currentKb.id}`, { exam: false });
      $("modal-exam-tags").classList.add("hidden");
      toast("已切换为普通课程库");
      await refreshKbs();
    });
  });
})();
