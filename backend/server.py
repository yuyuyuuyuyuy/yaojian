# -*- coding: utf-8 -*-
"""Flask 后端：静态前端 + /api 路由（薄壳，逻辑都在 backend 各模块）。"""
import json
import os
import tempfile
import time
import uuid

import flask
from flask import Flask, Response, jsonify, request

import config
from . import backup, cards as cards_mod, chat, events, exam, export, kb as kb_mod, ocr, parser, search, store
from .embeddings import make_client

# ---------------- 设置 ----------------

def load_settings():
    s = dict(config.DEFAULT_SETTINGS)
    if os.path.exists(config.SETTINGS_PATH):
        try:
            with open(config.SETTINGS_PATH, encoding="utf-8") as f:
                s.update(json.load(f))
        except Exception:
            pass
    # 设置文件里的空 Key 不覆盖内置 Key（保证开箱即用）
    if not s.get("api_key"):
        s["api_key"] = config.DEFAULT_SETTINGS.get("api_key", "")
    return s


def save_settings(s):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(config.SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def settings_public(s):
    out = {k: v for k, v in s.items() if k != "api_key"}
    out["has_key"] = bool(s.get("api_key"))
    out["data_dir"] = config.DATA_DIR
    return out


def _parse_kb_ids(data):
    """请求体的知识库作用域：kb_ids 数组优先，兼容旧 kb_id 单值；统一返回 id 列表（"all"=全部）。"""
    ids = data.get("kb_ids")
    if isinstance(ids, list) and ids:
        return [str(x) for x in ids]
    return [str(data.get("kb_id") or "all")]


def _gather_hits(kb_ids, vec, top_k, threshold, settings):
    """按作用域检索：kb_ids 为 id 列表（含 "all" 表示全部库），统一走多库合并检索。"""
    kbs = store.list_kbs()
    targets = kbs if "all" in kb_ids else [row for row in kbs if row["id"] in kb_ids]
    stores = []
    for row in targets:
        st = kb_mod.open_store(row["id"])
        if st is not None:
            stores.append((row["id"], row["name"], st))
    try:
        return search.search_multi(stores, vec, top_k, threshold)
    finally:
        for st in stores:
            st[2].close()


def _sse(obj):
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


# ---------------- 应用 ----------------

def create_app():
    app = Flask(__name__, static_folder=None)  # 禁用 Flask 内置 static 路由，用自己的 /static
    # 上传限制：单文件 ≤20MB，一次请求最多 4 个文件
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_FILE_MB * 4 * 1024 * 1024
    frontend_dir = os.path.join(config.BASE_DIR, "frontend")

    @app.get("/")
    def index():
        return flask.send_file(os.path.join(frontend_dir, "index.html"))

    @app.get("/static/<path:rel>")
    def static_files(rel):
        return flask.send_from_directory(frontend_dir, rel)

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "app": config.APP_NAME, "version": config.VERSION})

    # ---- 设置 ----
    @app.get("/api/settings")
    def get_settings():
        return jsonify(settings_public(load_settings()))

    @app.post("/api/settings")
    def post_settings():
        data = request.get_json(force=True) or {}
        s = load_settings()
        if data.get("api_key"):
            new_key = data["api_key"].strip()
            if new_key != s.get("api_key"):
                events.record("key_replaced")  # 用户自填/替换 Key（H8 代理指标）
            s["api_key"] = new_key
        for k in ("llm_model", "embed_model", "top_k", "score_threshold", "ocr_model", "theme", "card_daily_limit"):
            if k in data:
                s[k] = data[k]
        if data.get("onboarding_done") is not None:
            s["onboarding_done"] = bool(data["onboarding_done"])
        s["first_run"] = False
        save_settings(s)
        return jsonify({"ok": True, "settings": settings_public(s)})

    # ---- 知识库 ----
    @app.get("/api/kbs")
    def list_kbs():
        out = []
        for row in store.list_kbs():
            d = dict(row)
            st = kb_mod.open_store(row["id"])
            d["indexed"] = st is not None
            d["chunks"] = st.count() if st else 0
            if st:
                st.close()
            d["docs"] = len(kb_mod.list_docs(row["id"]))
            d["ingest"] = kb_mod.get_ingest_status(row["id"]) or {"running": False}
            d["ocr"] = kb_mod.get_ocr_status(row["id"]) or {"running": False}
            out.append(d)
        return jsonify({"kbs": out})

    @app.post("/api/kbs")
    def create_kb():
        data = request.get_json(force=True) or {}
        name = (data.get("name") or "").strip() or "未命名知识库"
        kb_id = kb_mod.create_kb(name)
        events.record("kb_created", kb_id=kb_id)
        return jsonify({"ok": True, "id": kb_id})

    @app.patch("/api/kbs/<kb_id>")
    def rename_kb(kb_id):
        data = request.get_json(force=True) or {}
        name = (data.get("name") or "").strip()
        if name:
            store.rename_kb(kb_id, name)
        if data.get("exam") is not None:
            store.set_kb_exam(kb_id, bool(data["exam"]))
        return jsonify({"ok": True})

    @app.delete("/api/kbs/<kb_id>")
    def remove_kb(kb_id):
        try:
            kb_mod.delete_kb(kb_id)
            return jsonify({"ok": True})
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.get("/api/kbs/<kb_id>/docs")
    def list_docs(kb_id):
        return jsonify({"docs": kb_mod.list_docs(kb_id)})

    @app.get("/api/kbs/<kb_id>/stats")
    def kb_stats(kb_id):
        """语料质量台账：上次索引统计（持久化）+ 每文件块数 + 未进入索引的文件。"""
        if store.get_kb(kb_id) is None:
            return jsonify({"ok": False, "error": "知识库不存在"}), 404
        persisted = kb_mod.load_ingest_stats(kb_id)
        files = []
        st = kb_mod.open_store(kb_id)
        if st is not None:
            for rel, (md5, n) in st.get_files().items():
                files.append({"rel": rel, "md5": md5, "chunks": n})
            st.close()
        indexed = {f["rel"] for f in files}
        missing = []
        for d in kb_mod.list_docs(kb_id):
            rel = d["rel"]
            if rel in indexed or rel + parser.OCR_SIDECAR_EXT in indexed:
                continue  # 扫描版 PDF 由 sidecar 索引，视为已入库
            missing.append(rel)
        return jsonify({"ok": True, "ledger": persisted, "files": files, "missing": missing})

    @app.post("/api/kbs/<kb_id>/import")
    def import_docs(kb_id):
        data = request.get_json(force=True) or {}
        if data.get("folder"):
            n = kb_mod.import_folder(kb_id, data["folder"])
        else:
            n = kb_mod.import_files(kb_id, data.get("paths") or [])
        if n:
            kb_mod.start_ingest(kb_id, load_settings())
        return jsonify({"ok": True, "imported": n})

    @app.post("/api/kbs/<kb_id>/ingest")
    def ingest_kb(kb_id):
        kb_mod.start_ingest(kb_id, load_settings())
        return jsonify({"ok": True})

    @app.post("/api/kbs/<kb_id>/upload")
    def upload_docs(kb_id):
        row = store.get_kb(kb_id)
        if row is None:
            return jsonify({"ok": False, "error": "知识库不存在"}), 404
        if row["builtin"]:
            return jsonify({"ok": False, "error": "内置知识库不可修改"}), 400
        docs_dir = kb_mod.kb_paths(kb_id)["docs"]
        os.makedirs(docs_dir, exist_ok=True)
        imported = 0
        for f in request.files.getlist("files"):
            if not f.filename:
                continue
            ext = os.path.splitext(f.filename)[1].lower()
            if ext not in parser.SUPPORTED_EXTS:
                continue
            f.save(os.path.join(docs_dir, os.path.basename(f.filename)))
            imported += 1
        if imported:
            kb_mod.start_ingest(kb_id, load_settings())
        return jsonify({"ok": True, "imported": imported})

    # ---- OCR ----
    @app.post("/api/ocr")
    def ocr_images():
        files = [f for f in request.files.getlist("files") if f.filename]
        if not files:
            return jsonify({"ok": False, "error": "未收到图片"}), 400
        settings = load_settings()
        try:
            client = make_client(settings)
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        results = []
        for f in files:
            name = os.path.basename(f.filename) or "未命名"
            data = f.read()
            if len(data) > config.MAX_FILE_MB * 1024 * 1024:
                results.append({"name": name, "text": "", "error": "图片超过 20MB"})
                continue
            uri = ocr.preprocess_image(data)
            if uri is None:
                results.append({"name": name, "text": "", "error": "无法解析图片（仅支持常见图片格式）"})
                continue
            try:
                text = ocr.recognize_image(client, settings["ocr_model"], uri)
                results.append({"name": name, "text": text, "error": None})
            except Exception as e:
                results.append({"name": name, "text": "", "error": str(e)})
        ok_count = sum(1 for r in results if r["error"] is None)
        if ok_count:
            events.record("ocr_recognized", count=ok_count)
        return jsonify({"ok": True, "results": results})

    @app.post("/api/kbs/<kb_id>/ocr-pdf")
    def ocr_pdf(kb_id):
        row = store.get_kb(kb_id)
        if row is None:
            return jsonify({"ok": False, "error": "知识库不存在"}), 404
        if row["builtin"]:
            return jsonify({"ok": False, "error": "内置知识库不可修改"}), 400
        data = request.get_json(force=True) or {}
        rel = (data.get("rel") or "").strip()
        if not rel:
            return jsonify({"ok": False, "error": "缺少文件名"}), 400
        try:
            kb_mod.start_pdf_ocr(kb_id, rel, load_settings())
            return jsonify({"ok": True})
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.post("/api/kbs/<kb_id>/ocr-save")
    def ocr_save(kb_id):
        row = store.get_kb(kb_id)
        if row is None:
            return jsonify({"ok": False, "error": "知识库不存在"}), 404
        if row["builtin"]:
            return jsonify({"ok": False, "error": "内置知识库不可修改"}), 400
        data = request.get_json(force=True) or {}
        text = (data.get("text") or "").strip()
        name = (data.get("name") or "").strip() or "OCR笔记"
        if not text:
            return jsonify({"ok": False, "error": "识别文本为空"}), 400
        fname = kb_mod.save_text_doc(kb_id, name, text)
        kb_mod.start_ingest(kb_id, load_settings())
        events.record("note_saved_to_kb", kb_id=kb_id)
        return jsonify({"ok": True, "file": fname})

    # ---- 对话 ----
    @app.get("/api/conversations")
    def list_conversations():
        return jsonify({"conversations": store.list_conversations(request.args.get("kb_id"))})

    @app.post("/api/conversations")
    def create_conversation():
        data = request.get_json(force=True) or {}
        kb_ids = _parse_kb_ids(data)
        conv_id = store.new_conversation(kb_ids)
        return jsonify({"ok": True, "id": conv_id})

    @app.get("/api/conversations/<conv_id>/messages")
    def get_messages(conv_id):
        return jsonify({"messages": store.get_messages(conv_id)})

    @app.delete("/api/conversations/<conv_id>")
    def delete_conversation(conv_id):
        store.delete_conversation(conv_id)
        return jsonify({"ok": True})

    @app.post("/api/conversations/<conv_id>/messages")
    def append_message(conv_id):
        """补存一条消息（停止生成时保存半截回答，保持历史问答配对）。"""
        data = request.get_json(force=True) or {}
        content = (data.get("content") or "").strip()
        role = data.get("role") if data.get("role") in ("user", "assistant") else "assistant"
        if content:
            store.add_message(conv_id, role, content, data.get("citations") or [])
        return jsonify({"ok": True})

    @app.post("/api/chat")
    def chat_route():
        data = request.get_json(force=True) or {}
        question = (data.get("question") or "").strip()
        kb_ids = _parse_kb_ids(data)
        conv_id = data.get("conv_id")
        if not question:
            return jsonify({"ok": False, "error": "问题不能为空"}), 400
        if not conv_id:
            conv_id = store.new_conversation(kb_ids, question[:24])
        elif not store.get_messages(conv_id):
            store.set_conversation_title(conv_id, question[:24])
        if not data.get("regenerate"):
            store.add_message(conv_id, "user", question)
        else:
            # 重新生成：删掉上一条助手回答，不重复存用户问题
            store.delete_last_assistant(conv_id)

        def gen():
            try:
                events.record("question_asked", conv_id=conv_id,
                              kb_id=(kb_ids[0] if len(kb_ids) == 1 else None),
                              scope_type="multi" if len(kb_ids) > 1 else ("all" if kb_ids == ["all"] else "single"))
                # 拒答后 10 分钟内继续提问 = 拒答没有劝退用户（H2 联动）
                last_ts, last_hit = events.last_answer(conv_id)
                if last_ts is not None and not last_hit:
                    try:
                        gap = (time.time() - time.mktime(time.strptime(last_ts, "%Y-%m-%d %H:%M:%S"))) / 60
                        if gap <= 10:
                            events.record("refusal_followup", conv_id=conv_id)
                    except Exception:
                        pass
                settings = load_settings()
                client = make_client(settings)
                history = store.recent_history(conv_id)
                # 多轮追问改写：只用于检索（把「它」「该法」补全成具体对象），回答仍用原问题+历史
                search_question = chat.rewrite_question(client, settings, question, history)
                vec = search.query_vector(client, search_question, settings["embed_model"])
                hits = _gather_hits(kb_ids, vec, settings["top_k"], settings["score_threshold"], settings)
                if not hits:
                    answer = chat.REFUSAL_FULL  # F9：拒答附原因与建议（规则模板）
                    events.record("answer_done", conv_id=conv_id, hit=False, refused=True)
                    yield _sse({"delta": answer})
                    store.add_message(conv_id, "assistant", answer, [])
                    yield _sse({"done": True, "citations": [], "conv_id": conv_id})
                    return
                parts = []
                for delta in chat.stream_answer(client, settings, question, hits, history):
                    parts.append(delta)
                    yield _sse({"delta": delta})
                answer = "".join(parts)
                citations = chat.extract_citations(answer, hits)
                events.record("answer_done", conv_id=conv_id, hit=True,
                              citation_count=len(citations))
                store.add_message(conv_id, "assistant", answer, citations)
                yield _sse({"done": True, "citations": citations, "conv_id": conv_id})
            except Exception as e:
                yield _sse({"error": str(e)})

        return Response(
            gen(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ---- 召回调试 ----
    @app.post("/api/search")
    def debug_search():
        data = request.get_json(force=True) or {}
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"ok": False, "error": "问题不能为空"}), 400
        kb_ids = _parse_kb_ids(data)
        top_k = int(data.get("top_k") or 8)
        threshold = float(data.get("threshold") if data.get("threshold") is not None else 0.0)
        settings = load_settings()
        try:
            client = make_client(settings)
            vec = search.query_vector(client, question, settings["embed_model"])
            hits = _gather_hits(kb_ids, vec, top_k, threshold, settings)
            return jsonify({"ok": True, "hits": hits})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    # ---- 知识笔记（F6：两步式——先模块分析，再按勾选生成） ----
    @app.post("/api/notes/modules")
    def note_modules():
        """第一步：检索并分析该主题实际具备哪些知识模块（动态，不硬凑空模块）。"""
        data = request.get_json(force=True) or {}
        keyword = (data.get("keyword") or "").strip()
        if not keyword:
            return jsonify({"ok": False, "error": "关键词不能为空"}), 400
        kb_ids = _parse_kb_ids(data)
        settings = load_settings()
        try:
            client = make_client(settings)
            vec = search.query_vector(client, keyword, settings["embed_model"])
            hits = _gather_hits(kb_ids, vec, 16, float(settings["score_threshold"]), settings)
            if not hits:
                return jsonify({"ok": True, "empty": True,
                                "message": f"所选知识库中未找到「{keyword}」相关内容。"})
            modules = chat.analyze_modules(client, settings, keyword, hits)
            return jsonify({"ok": True, "modules": modules, "hits_count": len(hits)})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.post("/api/notes/generate")
    def generate_note():
        data = request.get_json(force=True) or {}
        keyword = (data.get("keyword") or "").strip()
        if not keyword:
            return jsonify({"ok": False, "error": "关键词不能为空"}), 400
        kb_ids = _parse_kb_ids(data)
        settings = load_settings()
        try:
            client = make_client(settings)
            vec = search.query_vector(client, keyword, settings["embed_model"])
            # 笔记场景只加大检索条数；阈值保持用户设置（0.3 是验证过的拒答线，
            # 放宽会漏进无关文本、白白调 LLM——实测 0.25 时无关关键词命中 16 条）
            hits = _gather_hits(kb_ids, vec, 16, float(settings["score_threshold"]), settings)
            if not hits:
                return jsonify({"ok": True, "empty": True,
                                "message": f"所选知识库中未找到「{keyword}」相关内容。"})
            modules = data.get("modules")  # 选定的模块 key 列表；None=全部候选（兼容旧版）
            outline = data.get("format") == "outline"  # 思维导图=层级大纲
            note = chat.generate_note(client, settings, keyword, hits, modules=modules, outline=outline)
            citations = chat.extract_citations(note, hits)
            events.record("note_generated", kb_id=kb_ids[0] if len(kb_ids) == 1 else None,
                          module_count=len(modules) if modules else None,
                          outline=outline, keyword_len=len(keyword))
            return jsonify({"ok": True, "note": note, "citations": citations,
                            "hits_count": len(hits), "outline": outline})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.get("/api/notes")
    def list_notes():
        return jsonify({"notes": store.list_notes()})

    @app.post("/api/notes/save")
    def save_note():
        data = request.get_json(force=True) or {}
        content = (data.get("content") or "").strip()
        keyword = (data.get("keyword") or "").strip() or "未命名"
        if not content:
            return jsonify({"ok": False, "error": "笔记内容为空"}), 400
        nid = store.save_note(keyword, _parse_kb_ids(data), content)
        return jsonify({"ok": True, "id": nid})

    @app.delete("/api/notes/<int:note_id>")
    def delete_note(note_id):
        store.delete_note(note_id)
        return jsonify({"ok": True})

    @app.post("/api/notes/export")
    def export_note_text():
        data = request.get_json(force=True) or {}
        title = (data.get("title") or "知识笔记").strip()
        content = (data.get("content") or "").strip()
        fmt = data.get("format") if data.get("format") in ("md", "docx") else "md"
        if not content:
            return jsonify({"ok": False, "error": "笔记内容为空"}), 400
        try:
            path = export.export_note_text(title, content, fmt)
            return jsonify({"ok": True, "path": path})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.post("/api/kbs/<kb_id>/note-save")
    def note_to_kb(kb_id):
        """把整理好的知识笔记存为 txt 加入自建知识库（参与问答）。"""
        row = store.get_kb(kb_id)
        if row is None:
            return jsonify({"ok": False, "error": "知识库不存在"}), 404
        if row["builtin"]:
            return jsonify({"ok": False, "error": "内置知识库不可修改"}), 400
        data = request.get_json(force=True) or {}
        text = (data.get("text") or "").strip()
        name = (data.get("name") or "").strip() or "知识笔记"
        if not text:
            return jsonify({"ok": False, "error": "笔记内容为空"}), 400
        fname = kb_mod.save_text_doc(kb_id, name, text)
        kb_mod.start_ingest(kb_id, load_settings())
        events.record("note_saved_to_kb", kb_id=kb_id)
        return jsonify({"ok": True, "file": fname})

    # ---- 意见反馈（产品化：真实用户反馈闭环） ----
    @app.post("/api/feedback")
    def save_feedback():
        """意见反馈：追加保存到数据目录 feedback.txt（本机存档，便于用户转交开发者）。"""
        data = request.get_json(force=True) or {}
        content = (data.get("content") or "").strip()
        if not content:
            return jsonify({"ok": False, "error": "反馈内容为空"}), 400
        path = os.path.join(config.DATA_DIR, "feedback.txt")
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n===== " + time.strftime("%Y-%m-%d %H:%M") + " =====\n" + content + "\n")
        events.record("feedback_submitted", channel=data.get("channel") or "local")
        return jsonify({"ok": True, "path": path})

    # ---- 使用数据埋点（S6：本机记录、用户可见可导出可删除） ----
    @app.post("/api/events/citation")
    def event_citation():
        """引用徽章被点击（信任过程指标：新用户前 3 次问答核对率）。"""
        data = request.get_json(force=True) or {}
        events.record("citation_clicked", conv_id=data.get("conv_id"),
                      session_order=data.get("session_order"), ref_index=data.get("ref_index"))
        return jsonify({"ok": True})

    @app.get("/api/events/stats")
    def event_stats():
        return jsonify({"ok": True, "stats": events.compute_stats()})

    @app.get("/api/usage")
    def usage_estimate():
        """本月用量与费用估算（F14）：读本机埋点事件估算，单价区间标注「以控制台账单为准」。"""
        import sqlite3
        month_start = time.strftime("%Y-%m-01 00:00:00")
        db = sqlite3.connect(config.CHAT_DB_PATH)
        rows = db.execute(
            "SELECT event, payload FROM events WHERE ts >= ?", (month_start,)
        ).fetchall()
        db.close()
        qa = note = img = pdf_pages = exam_files = 0
        for ev, pl in rows:
            if ev == "question_asked":
                qa += 1
            elif ev == "note_generated":
                note += 1
            elif ev == "ocr_recognized":
                try:
                    p = json.loads(pl or "{}")
                except Exception:
                    p = {}
                img += int(p.get("count") or 0)
                pdf_pages += int(p.get("pdf_pages") or 0)
            elif ev == "exam_tag_analyzed":
                exam_files += 1
        # 估算单价区间（元/次，公开价粗算）：问答 0.005~0.02；笔记 0.02~0.05；OCR 图 0.01~0.02、PDF 页 0.005~0.02；考点分析 0.005~0.02/文件
        low = round(qa * 0.005 + note * 0.02 + img * 0.01 + pdf_pages * 0.005 + exam_files * 0.005, 2)
        high = round(qa * 0.02 + note * 0.05 + img * 0.02 + pdf_pages * 0.02 + exam_files * 0.02, 2)
        return jsonify({"ok": True, "usage": {
            "month_start": month_start[:7], "qa": qa, "note": note,
            "ocr_images": img, "ocr_pdf_pages": pdf_pages, "exam_files": exam_files,
            "cost_low": low, "cost_high": high,
        }})

    @app.get("/api/events/export")
    def event_export():
        payload = events.export_payload()
        events.record("events_exported", count=len(payload["events"]))
        return jsonify({"ok": True, **payload})

    @app.delete("/api/events")
    def event_clear():
        events.clear_events()
        return jsonify({"ok": True})

    # ---- 备份与迁移（F13：本机文件操作，备份包不含 Key） ----
    @app.get("/api/backup/export")
    def backup_export():
        zip_path = backup.export_backup()
        return flask.send_file(zip_path, as_attachment=True,
                               download_name=os.path.basename(zip_path))

    @app.post("/api/backup/import")
    def backup_import():
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"ok": False, "error": "未收到备份文件"}), 400
        tmp = os.path.join(tempfile.gettempdir(), "yaojian_upload_%s.zip" % uuid.uuid4().hex[:8])
        f.save(tmp)
        try:
            token, summary = backup.stage_import(tmp)
        except Exception as e:
            if os.path.exists(tmp):
                os.remove(tmp)
            return jsonify({"ok": False, "error": str(e)}), 400
        if os.path.exists(tmp):
            os.remove(tmp)
        return jsonify({"ok": True, "token": token, "summary": summary})

    @app.post("/api/backup/apply")
    def backup_apply():
        data = request.get_json(force=True) or {}
        try:
            old_dir = backup.apply_backup(data.get("token"))
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        return jsonify({"ok": True, "message": "恢复完成，请重启应用生效", "old_dir": old_dir})

    # ---- 考研场景包（F8：考点标记——AI 自动+人工修正） ----
    @app.get("/api/kbs/<kb_id>/tags")
    def exam_tags_list(kb_id):
        if store.get_kb(kb_id) is None:
            return jsonify({"ok": False, "error": "知识库不存在"}), 404
        tags = exam.list_tags(kb_id)
        by_file = {}
        for t in tags:
            by_file.setdefault(t["file_name"], []).append({"id": t["id"], "tag": t["tag"]})
        doc_names = [d["rel"] for d in kb_mod.list_docs(kb_id)]
        pending = exam.pending_files(kb_id, doc_names)
        return jsonify({"ok": True, "tags": by_file, "pending": pending})

    @app.post("/api/kbs/<kb_id>/tags/analyze")
    def exam_tags_analyze(kb_id):
        """AI 提取考点（指定文件或全部未分析文件）；逐个失败静默跳过。"""
        data = request.get_json(force=True) or {}
        settings = load_settings()
        client = make_client(settings)
        docs = [d["rel"] for d in kb_mod.list_docs(kb_id)]
        targets = data.get("files") or exam.pending_files(kb_id, docs)
        done = 0
        for rel in targets:
            if rel not in docs:
                continue
            path = kb_mod.kb_paths(kb_id)["docs"]
            full = os.path.join(path, rel)
            try:
                with open(full, "rb") as f:
                    raw = f.read()
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("gbk", errors="ignore")
                tags = exam.analyze_content(client, settings, text)
            except Exception:
                tags = None  # 失败降级：跳过，面板显示「待分析」可重试
            if tags:
                exam.set_tags(kb_id, rel, tags)
                done += 1
            events.record("exam_tag_analyzed", kb_id=kb_id, file=rel, tags=len(tags) if tags else 0)
        return jsonify({"ok": True, "analyzed": done})

    @app.post("/api/kbs/<kb_id>/tags")
    def exam_tag_add(kb_id):
        data = request.get_json(force=True) or {}
        exam.add_tag(kb_id, data.get("file_name") or "", data.get("tag") or "")
        return jsonify({"ok": True})

    @app.delete("/api/kbs/<kb_id>/tags/<int:tag_id>")
    def exam_tag_delete(kb_id, tag_id):
        exam.delete_tag(tag_id)
        return jsonify({"ok": True})

    # ---- 背得会（F5：记忆卡片——双模式生成 + SM-2 调度 + 防积压） ----
    @app.post("/api/cards/generate")
    def cards_generate():
        """一键生成：整篇笔记 → 问答卡（≤max 张）。"""
        data = request.get_json(force=True) or {}
        note_id = int(data.get("note_id") or 0)
        note = store.get_note(note_id)
        if note is None:
            return jsonify({"ok": False, "error": "笔记不存在"}), 404
        settings = load_settings()
        try:
            client = make_client(settings)
            pairs = chat.generate_cards(client, settings, note["content"], max_cards=int(data.get("max") or 15))
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        if not pairs:
            return jsonify({"ok": True, "count": 0, "message": "笔记内容不足以生成卡片"})
        count = cards_mod.add_cards(note_id, pairs)
        return jsonify({"ok": True, "count": count})

    @app.post("/api/cards/from-text")
    def cards_from_text():
        """选段制卡：笔记里选中一段文字 → 1 张卡（答案=选中文段）。"""
        data = request.get_json(force=True) or {}
        note_id = int(data.get("note_id") or 0)
        text = (data.get("text") or "").strip()
        if not text:
            return jsonify({"ok": False, "error": "选中文字为空"}), 400
        note = store.get_note(note_id)
        if note is None:
            return jsonify({"ok": False, "error": "笔记不存在"}), 404
        settings = load_settings()
        try:
            client = make_client(settings)
            pair = chat.generate_card_from_text(client, settings, text)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        if pair is None:
            return jsonify({"ok": False, "error": "生成失败，请重试"}), 500
        cards_mod.add_cards(note_id, [pair])
        return jsonify({"ok": True, "count": 1})

    @app.get("/api/cards/due")
    def cards_due():
        """今日到期队列（防积压：按每日上限取，剩余顺延）。"""
        settings = load_settings()
        limit = cards_mod.default_daily_limit(settings)
        queue, total_due = cards_mod.due_queue(limit)
        return jsonify({"ok": True, "queue": queue, "total_due": total_due, "limit": limit})

    @app.post("/api/cards/<int:card_id>/review")
    def cards_review(card_id):
        data = request.get_json(force=True) or {}
        try:
            result = cards_mod.review(card_id, data.get("rating"))
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        if result is None:
            return jsonify({"ok": False, "error": "卡片不存在"}), 404
        return jsonify({"ok": True, **result})

    @app.get("/api/cards/stats")
    def cards_stats():
        return jsonify({"ok": True, "stats": cards_mod.stats()})

    # ---- 笔记导出 ----
    @app.post("/api/export")
    def export_note():
        data = request.get_json(force=True) or {}
        conv_id = data.get("conv_id")
        fmt = data.get("format") if data.get("format") in ("md", "docx") else "md"
        out_path = data.get("path") or None
        convs = store.list_conversations()
        conv = next((c for c in convs if c["id"] == conv_id), None)
        if conv is None:
            return jsonify({"ok": False, "error": "对话不存在"}), 404
        messages = store.get_messages(conv_id)
        if not messages:
            return jsonify({"ok": False, "error": "对话为空，无可导出内容"}), 400
        try:
            path = export.export_conversation(conv, messages, fmt, out_path)
            return jsonify({"ok": True, "path": path})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    return app
