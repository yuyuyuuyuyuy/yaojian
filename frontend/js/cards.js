/* 背得会（F5）：卡片复习——到期队列、四键自评、前置引导、跳回来源笔记。 */
(function () {
  function $(id) { return document.getElementById(id); }
  let queue = [];
  let current = null;

  function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  async function loadQueue() {
    const body = $("cards-body");
    body.innerHTML = `<div class="note-loading">⏳ 正在加载今日复习队列…</div>`;
    try {
      const r = await API.get("/api/cards/due");
      if (!r.ok) throw new Error(r.error || "加载失败");
      queue = r.queue || [];
      if (!queue.length) {
        body.innerHTML = `<div class="info-box">🎉 今天没有到期的卡片（到期但超出每日上限的会顺延到明天，不滚雪球）。<br><span class="hint">先去「📄 我的笔记」把笔记生成卡片吧。</span></div>`;
        return;
      }
      if (r.total_due > queue.length) {
        body.innerHTML += `<div class="info-box hint">今日到期 ${r.total_due} 张，按每日上限 ${r.limit} 张复习，其余顺延到明天（不惩罚）。</div>`;
      }
      showCard(queue[0]);
    } catch (e) {
      body.innerHTML = `<div class="info-box">加载失败：${escapeHtml(e.message)}</div>`;
    }
  }

  function showCard(card, flipped = false) {
    current = card;
    const body = $("cards-body");
    body.innerHTML = "";
    const box = document.createElement("div");
    box.className = "card-box";
    box.innerHTML = `
      <div class="card-progress">第 ${queue.indexOf(card) + 1} / ${queue.length} 张</div>
      <div class="card-face">${flipped ? escapeHtml(card.answer) : escapeHtml(card.question)}</div>
      <div class="card-actions">
        ${flipped ? `
          <button class="card-rate" data-rating="again">😵 忘记<br><span class="hint">今天重现</span></button>
          <button class="card-rate" data-rating="hard">😐 困难<br><span class="hint">间隔减半</span></button>
          <button class="card-rate" data-rating="good">🙂 正常<br><span class="hint">按曲线推进</span></button>
          <button class="card-rate" data-rating="easy">😎 轻松<br><span class="hint">加速推进</span></button>
        ` : `
          <button id="btn-card-show" class="btn btn-primary">显示答案</button>
          <button class="btn btn-ghost" id="btn-card-note">📖 回到来源笔记</button>
        `}
      </div>`;
    body.appendChild(box);
    if (flipped) {
      box.querySelectorAll(".card-rate").forEach(b => {
        b.addEventListener("click", () => rateCard(card, b.dataset.rating));
      });
    } else {
      $("btn-card-show").addEventListener("click", () => showCard(card, true));
      $("btn-card-note").addEventListener("click", () => {
        closeCardsModal();
        viewNote(card.source_note_id);  // notes.js 提供
      });
    }
  }

  async function rateCard(card, rating) {
    try {
      const r = await API.post(`/api/cards/${card.id}/review`, { rating });
      if (!r.ok) throw new Error(r.error || "保存失败");
    } catch (e) {
      toast("自评保存失败：" + e.message);
      return;
    }
    const idx = queue.indexOf(card);
    queue.splice(idx, 1);
    if (queue.length) showCard(queue[Math.min(idx, queue.length - 1)]);
    else loadQueue();
  }

  function openCardsModal() {
    $("modal-cards").classList.remove("hidden");
    // 前置引导（K11 碎片化教训）：首次进入提示
    if (!sessionStorage.getItem("la_cards_tip_shown")) {
      sessionStorage.setItem("la_cards_tip_shown", "1");
      setTimeout(() => {
        toast("💡 建议先通过问答/笔记建立整体认知，再背卡巩固细节");
      }, 400);
    }
    loadQueue();
  }

  function closeCardsModal() {
    $("modal-cards").classList.add("hidden");
  }

  window.addEventListener("DOMContentLoaded", () => {
    $("btn-cards").addEventListener("click", openCardsModal);
    $("btn-cards-close").addEventListener("click", closeCardsModal);
  });
})();
