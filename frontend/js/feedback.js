/* 意见反馈：提交 GitHub issue（预填内容）/ 复制 / 保存本机 */
function bindFeedback() {
  $("btn-open-feedback").addEventListener("click", () => {
    $("fb-text").value = "";
    $("modal-feedback").classList.remove("hidden");
    $("fb-text").focus();
  });
  $("btn-fb-close").addEventListener("click", () => $("modal-feedback").classList.add("hidden"));

  $("btn-fb-issue").addEventListener("click", () => {
    const text = $("fb-text").value.trim();
    if (!text) return toast("请先填写反馈内容");
    const title = encodeURIComponent("[用户反馈] " + text.slice(0, 40));
    const body = encodeURIComponent(text + "\n\n---\n（由药鉴 APP 反馈入口生成）");
    window.open(`https://github.com/yuyuyuuyuyuy/yaojian/issues/new?title=${title}&body=${body}`, "_blank");
  });

  $("btn-fb-copy").addEventListener("click", async () => {
    const text = $("fb-text").value.trim();
    if (!text) return toast("请先填写反馈内容");
    await copyText(text);
    toast("已复制，可粘贴到任意渠道发给开发者");
  });

  $("btn-fb-local").addEventListener("click", async () => {
    const text = $("fb-text").value.trim();
    if (!text) return toast("请先填写反馈内容");
    const r = await API.post("/api/feedback", { content: text });
    if (r.ok) {
      $("modal-feedback").classList.add("hidden");
      toast(`反馈已保存到本机（${r.path}）`, 6000);
    } else toast("保存失败：" + (r.error || ""), 5000);
  });
}
