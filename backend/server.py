# -*- coding: utf-8 -*-
"""Flask 后端：静态前端 + /api 路由（薄壳，逻辑都在 backend 各模块）。"""
import json
import os
import time

import flask
from flask import Flask, Response, jsonify, request

import config
from . import chat, export, kb as kb_mod, ocr, parser, search, store
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
            s["api_key"] = data["api_key"].strip()
        for k in ("llm_model", "embed_model", "top_k", "score_threshold", "ocr_model", "theme"):
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
        return jsonify({"ok": True, "id": kb_id})

    @app.patch("/api/kbs/<kb_id>")
    def rename_kb(kb_id):
        data = request.get_json(force=True) or {}
        name = (data.get("name") or "").strip()
        if name:
            store.rename_kb(kb_id, name)
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
                settings = load_settings()
                client = make_client(settings)
                history = store.recent_history(conv_id)
                # 多轮追问改写：只用于检索（把「它」「该法」补全成具体对象），回答仍用原问题+历史
                search_question = chat.rewrite_question(client, settings, question, history)
                vec = search.query_vector(client, search_question, settings["embed_model"])
                hits = _gather_hits(kb_ids, vec, settings["top_k"], settings["score_threshold"], settings)
                if not hits:
                    answer = chat.REFUSAL_TEXT
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

    # ---- 知识笔记（三期：关键词 → 结构化笔记） ----
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
            note = chat.generate_note(client, settings, keyword, hits)
            citations = chat.extract_citations(note, hits)
            return jsonify({"ok": True, "note": note, "citations": citations, "hits_count": len(hits)})
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
        return jsonify({"ok": True, "path": path})

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
