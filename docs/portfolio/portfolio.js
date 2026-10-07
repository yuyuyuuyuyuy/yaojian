/* 药鉴作品集 —— 交互逻辑（纯原生 JS，无依赖） */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  /* ---------- 0. 动效降级（无障碍） ---------- */
  var REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- 1. 滚动浮现 ---------- */
  if (REDUCED) {
    document.querySelectorAll(".reveal").forEach(function (el) { el.classList.add("visible"); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("visible"); io.unobserve(e.target); }
      });
    }, { threshold: 0.12 });
    document.querySelectorAll(".reveal").forEach(function (el) { io.observe(el); });
  }

  /* ---------- 2. 数字滚动 ---------- */
  if (REDUCED) {
    document.querySelectorAll(".stat b[data-count]").forEach(function (el) {
      el.textContent = el.dataset.count;
    });
  } else {
    var cio = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        var el = e.target, target = parseInt(el.dataset.count, 10) || 0;
        var t0 = performance.now(), dur = 1200;
        function step(t) {
          var p = Math.min((t - t0) / dur, 1);
          el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3)));
          if (p < 1) requestAnimationFrame(step); else el.textContent = target;
        }
        requestAnimationFrame(step);
        cio.unobserve(el);
      });
    }, { threshold: 0.6 });
    document.querySelectorAll(".stat b[data-count]").forEach(function (el) { cio.observe(el); });
  }

  /* ---------- 3. 导航高亮（scrollspy） ---------- */
  var navLinks = Array.prototype.slice.call(document.querySelectorAll(".nav-links a"));
  var linkMap = {};
  navLinks.forEach(function (a) { linkMap[a.getAttribute("href").slice(1)] = a; });
  var sio = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      navLinks.forEach(function (a) { a.classList.remove("active"); });
      var a = linkMap[e.target.id];
      if (a) a.classList.add("active");
    });
  }, { rootMargin: "-40% 0px -55% 0px" });
  ["works", "overview", "demo", "story", "methods", "results", "reflect", "contact"].forEach(function (id) {
    var el = $(id);
    if (el) sio.observe(el);
  });

  /* ---------- 4. 交互式问答演示 ---------- */
  var DEMO = {
    q1: {
      q: "重金属检查法分几种方法？",
      a: "重金属检查法（通则 0821）分为三种方法：\n• [1] 硫代乙酰胺法——适用于溶于水、稀酸和乙醇的药品；\n• [2] 炽灼后的硫代乙酰胺法——适用于含芳环、杂环以及不溶于水、稀酸及乙醇的药品；\n• [3] 硫化钠法——适用于溶于碱性水溶液的药品。",
      sources: [
        { n: 1, text: "除另有规定外，取 25ml 纳氏比色管三支，甲管中加一定量的标准铅溶液与醋酸盐缓冲液（pH3.5）2ml，加水稀释成 25ml；乙管中加入供试品溶液 25ml；丙管中加入与乙管相同重量的供试品……", meta: "《中国药典》2025 年版四部 · 通则 0821 原文 · 相似度 0.87" },
        { n: 2, text: "……炽灼后的硫代乙酰胺法：取供试品照炽灼残渣检查法项下的方法炽灼，残渣加水溶解，滤过，滤液照第一法检查……", meta: "《中国药典》2025 年版四部 · 通则 0821 原文 · 相似度 0.82" },
        { n: 3, text: "硫化钠法：适用于溶于碱性水溶液而不溶于稀酸的药品，供试品加氢氧化钠试液溶解，再依次加硫化钠试液……", meta: "《中国药典》2025 年版四部 · 通则 0821 原文 · 相似度 0.79" }
      ]
    },
    q2: {
      q: "药物的降压作用机制是什么？",
      a: "资料中未找到相关内容。所选知识库中没有与这个问题相关的资料。\n建议：①换一个关键词试试；②先在侧边栏新建知识库并导入相关课件/笔记；③若是扫描版 PDF 无法检索，可在知识库旁点「OCR」整本识别后再问。",
      refusal: true,
      sources: []
    }
  };

  var typingTimer = null;

  function badgeHtml(text) {
    return esc(text).replace(/\[(\d+)\]/g, '<span class="cite" data-n="$1">[$1]</span>');
  }

  function renderSources(key) {
    var box = $("demo-sources");
    box.innerHTML = "";
    var d = DEMO[key];
    if (d.refusal) {
      box.innerHTML = '<div class="src-card">拒答演示：检索阈值与提示词铁律构成「防幻觉双防线」，查不到就明说，绝不编造。</div>';
      return;
    }
    d.sources.forEach(function (s) {
      var el = document.createElement("div");
      el.className = "src-card";
      el.dataset.n = s.n;
      el.innerHTML = "<b>[" + s.n + "]</b> " + esc(s.text) + '<div class="src-meta">' + esc(s.meta) + "</div>";
      box.appendChild(el);
    });
  }

  function runDemo(key) {
    var d = DEMO[key];
    if (!d) return;
    if (typingTimer) { clearInterval(typingTimer); typingTimer = null; }
    document.querySelectorAll("#demo-chips .chip").forEach(function (c) {
      c.classList.toggle("on", c.dataset.q === key);
    });
    var chat = $("demo-chat");
    // 旧回答先收回，再显示新回答
    var startNew = function () {
      chat.classList.remove("closing");
      chat.innerHTML = "";
      $("demo-sources").innerHTML = "";
      var qEl = document.createElement("div");
      qEl.className = "msg msg-q";
      qEl.textContent = "问：" + d.q;
      chat.appendChild(qEl);
      var aEl = document.createElement("div");
      aEl.className = "msg";
      var bEl = document.createElement("div");
      bEl.className = "msg-a";
      aEl.appendChild(bEl);
      chat.appendChild(aEl);
      var i = 0, text = d.a;
      var finish = function () {
        if (typingTimer) { clearInterval(typingTimer); typingTimer = null; }
        bEl.classList.remove("typing");
        bEl.innerHTML = badgeHtml(text);
        bEl.querySelectorAll(".cite").forEach(function (c) {
          c.setAttribute("role", "button");
          c.setAttribute("tabindex", "0");
          var hl = function () {
            document.querySelectorAll("#demo-sources .src-card").forEach(function (s) {
              if (s.dataset.n === c.dataset.n) s.classList.toggle("hl");
            });
          };
          c.addEventListener("click", hl);
          c.addEventListener("keydown", function (e) {
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); hl(); }
          });
        });
        renderSources(key);
      };
      // 点击回答立即显示完整内容（评审修复：打字动画可跳过）
      aEl.addEventListener("click", function () { if (typingTimer) finish(); });
      if (REDUCED) { finish(); return; }
      bEl.classList.add("typing");
      typingTimer = setInterval(function () {
        i += 2;
        bEl.textContent = text.slice(0, i);
        if (i >= text.length) finish();
      }, 40);
    };
    if (chat.children.length > 0) {
      chat.classList.add("closing");
      setTimeout(startNew, 160);
    } else {
      startNew();
    }
  }

  document.querySelectorAll("#demo-chips .chip").forEach(function (ch) {
    ch.addEventListener("click", function () { runDemo(ch.dataset.q); });
  });

  /* ---------- 5. 决策故事手风琴 ---------- */
  function syncTaria() {
    document.querySelectorAll(".t-head").forEach(function (h) {
      h.setAttribute("aria-expanded", h.parentElement.classList.contains("open") ? "true" : "false");
    });
  }
  document.querySelectorAll(".t-head").forEach(function (h) {
    h.addEventListener("click", function () {
      var card = h.parentElement;
      var wasOpen = card.classList.contains("open");
      document.querySelectorAll(".t-card.open").forEach(function (c) { c.classList.remove("open"); });
      if (!wasOpen) card.classList.add("open");
      syncTaria();
    });
  });

  /* ---------- 5.5 决策故事：默认展开前 2 张 + 全部展开/收起（评审修复） ---------- */
  var tCards = document.querySelectorAll("#timeline .t-card");
  if (tCards.length) {
    tCards.forEach(function (c, i) { if (i < 2) c.classList.add("open"); });
    syncTaria();
    var tAll = $("t-all");
    if (tAll) {
      tAll.addEventListener("click", function () {
        var allOpen = Array.prototype.every.call(tCards, function (c) { return c.classList.contains("open"); });
        tCards.forEach(function (c) { c.classList.toggle("open", !allOpen); });
        tAll.textContent = allOpen ? "全部展开" : "全部收起";
        tAll.setAttribute("aria-expanded", allOpen ? "false" : "true");
        syncTaria();
      });
    }
  }

  /* ---------- 6. 方法论翻卡 ---------- */
  document.querySelectorAll(".m-card").forEach(function (c) {
    var front = c.querySelector(".m-front");
    var back = c.querySelector(".m-back");
    function syncFlip() {
      var flipped = c.classList.contains("flipped");
      if (front) front.setAttribute("aria-pressed", flipped ? "true" : "false");
      if (back) {
        back.setAttribute("aria-hidden", flipped ? "false" : "true");
        back.inert = !flipped;
      }
    }
    c.addEventListener("click", function () {
      c.classList.toggle("flipped");
      syncFlip();
    });
    syncFlip();
  });

  /* ---------- 7. 核心功能横滑（仅药鉴页；选中卡 → 详情面板；箭头翻页） ---------- */
  var featGrid = $("feat-grid");
  var featDetail = $("feat-detail");
  var featCards = Array.prototype.slice.call(document.querySelectorAll(".feat-card"));

  function selectFeat(card) {
    featCards.forEach(function (c) {
      c.classList.remove("sel");
      var h = c.querySelector(".feat-head");
      if (h) h.setAttribute("aria-selected", "false");
    });
    card.classList.add("sel");
    var head = card.querySelector(".feat-head");
    if (head) head.setAttribute("aria-selected", "true");
    var p = featDetail.querySelector("p");
    if (p) p.textContent = card.dataset.desc || "";
    featDetail.style.opacity = 0;
    setTimeout(function () { featDetail.style.opacity = 1; }, 60);
  }

  if (featGrid && featDetail) {
    featCards.forEach(function (card) {
      card.addEventListener("click", function () { selectFeat(card); });
    });
    $("feat-prev").addEventListener("click", function () {
      featGrid.scrollBy({ left: -(featGrid.clientWidth * 0.8), behavior: "smooth" });
    });
    $("feat-next").addEventListener("click", function () {
      featGrid.scrollBy({ left: featGrid.clientWidth * 0.8, behavior: "smooth" });
    });
    if (featCards.length) selectFeat(featCards[0]);
  }

  /* ---------- 8. 产品界面轮播（仅药鉴页） ---------- */
  var GALLERY = window.PORTFOLIO_GALLERY || [
    { src: "首页.png", cap: "首页：上传资料" },
    { src: "拒答.png", cap: "拒答：查不到就明说，绝不编造" },
    { src: "笔记.png", cap: "知识笔记：模块勾选生成" },
    { src: "考点.png", cap: "考研场景包：考点频次一目了然" },
    { src: "背得快.png", cap: "背得会：按记忆曲线复习" }
  ];
  var galIdx = 0;
  var galImg = $("gal-img");
  var galCap = $("gal-cap");
  var galDots = $("gal-dots");

  if (galImg && galCap && galDots) {
    function renderGalDots() {
      galDots.innerHTML = "";
      GALLERY.forEach(function (g, i) {
        var d = document.createElement("span");
        d.className = "gal-dot" + (i === galIdx ? " on" : "");
        d.setAttribute("role", "button");
        d.setAttribute("tabindex", "0");
        d.setAttribute("aria-label", "第 " + (i + 1) + " 张：" + g.cap);
        d.addEventListener("click", function () { showGal(i); });
        d.addEventListener("keydown", function (e) {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showGal(i); }
        });
        galDots.appendChild(d);
      });
    }

    function showGal(i) {
      galIdx = (i + GALLERY.length) % GALLERY.length;
      galImg.style.opacity = 0;
      setTimeout(function () {
        galImg.src = GALLERY[galIdx].src;
        galImg.alt = GALLERY[galIdx].cap;
        galCap.textContent = GALLERY[galIdx].cap;
        galImg.style.opacity = 1;
        renderGalDots();
      }, 120);
    }

    $("gal-prev").addEventListener("click", function () { showGal(galIdx - 1); });
    $("gal-next").addEventListener("click", function () { showGal(galIdx + 1); });
    showGal(0);
  }

  /* ---------- 8.5 七环节流程条：点击环节 → 能力详情（仅海淘页） ---------- */
  var flowSteps = Array.prototype.slice.call(document.querySelectorAll(".flow-step"));
  var flowDetail = $("flow-detail");
  if (flowSteps.length && flowDetail) {
    function selectFlow(btn) {
      flowSteps.forEach(function (b) {
        b.classList.remove("sel");
        b.setAttribute("aria-pressed", "false");
      });
      btn.classList.add("sel");
      btn.setAttribute("aria-pressed", "true");
      var p = flowDetail.querySelector("p");
      if (p) p.textContent = btn.dataset.desc || "";
      flowDetail.style.opacity = 0;
      setTimeout(function () { flowDetail.style.opacity = 1; }, 60);
    }
    flowSteps.forEach(function (b) {
      b.addEventListener("click", function () { selectFlow(b); });
    });
    selectFlow(flowSteps[0]);
  }

  /* ---------- 9. 汉堡菜单（移动端） ---------- */
  var burger = $("nav-burger");
  var topnav = document.getElementById("topnav");
  if (burger && topnav) {
    function closeNav() {
      topnav.classList.remove("nav-open");
      burger.setAttribute("aria-expanded", "false");
    }
    burger.addEventListener("click", function () {
      var open = topnav.classList.toggle("nav-open");
      burger.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.querySelectorAll(".nav-links a").forEach(function (a) {
      a.addEventListener("click", closeNav);
    });
    document.addEventListener("click", function (e) {
      if (!topnav.contains(e.target)) closeNav();
    });
  }

  /* ---------- 9.5 导航滚动阴影（A4） ---------- */
  if (topnav) {
    var onNavScroll = function () {
      topnav.classList.toggle("scrolled", window.scrollY > 40);
    };
    window.addEventListener("scroll", onNavScroll, { passive: true });
    onNavScroll();
  }

  /* ---------- 10. 返回顶部 ---------- */
  var toTop = $("to-top");
  if (toTop) {
    window.addEventListener("scroll", function () {
      toTop.classList.toggle("show", window.scrollY > 600);
    }, { passive: true });
    toTop.addEventListener("click", function () {
      window.scrollTo({ top: 0, behavior: REDUCED ? "auto" : "smooth" });
    });
  }
})();
