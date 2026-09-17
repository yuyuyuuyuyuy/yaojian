# -*- coding: utf-8 -*-
"""知识库管理：注册表（chat.db）+ 磁盘布局 kbs/<id>/{docs/, index.sqlite}。

索引进度存在内存 INGEST_STATUS（单机单用户应用，够用）。
"""
import json
import os
import shutil
import threading
import time
import uuid

import config
from . import ingest, ocr, parser, store
from .embeddings import make_client
from .vector_store import VectorStore

INGEST_STATUS = {}  # kb_id -> {running, pct, message, error, stats}
OCR_STATUS = {}     # kb_id -> {running, pct, message, current, error}（扫描版 PDF 整本 OCR）

# 防止同一知识库并发建索引：两个 build_index 同时写同一个 .tmp 会互相踩踏
# （实测：连续两次 ocr-save 触发两个索引进程 → UNIQUE constraint failed: chunks.id）
INGEST_LOCKS = {}    # kb_id -> threading.Lock
INGEST_PENDING = {}  # kb_id -> bool（锁占用期间的调用：本轮结束后自动补跑一次）


def ensure_data_dirs():
    os.makedirs(config.KBS_DIR, exist_ok=True)
    store.init_db()
    store.ensure_builtin_kb()


def kb_paths(kb_id):
    """内置库的文档目录在程序包内（只读），索引在用户数据目录；用户库两者都在数据目录。"""
    if kb_id == config.BUILTIN_KB_ID:
        return {
            "base": os.path.join(config.KBS_DIR, kb_id),
            "docs": config.BUILTIN_DOCS_DIR,
            "index": os.path.join(config.KBS_DIR, kb_id, "index.sqlite"),
        }
    base = os.path.join(config.KBS_DIR, kb_id)
    return {
        "base": base,
        "docs": os.path.join(base, "docs"),
        "index": os.path.join(base, "index.sqlite"),
    }


def create_kb(name):
    kb_id = uuid.uuid4().hex[:8]
    p = kb_paths(kb_id)
    os.makedirs(p["docs"], exist_ok=True)
    store.add_kb(kb_id, name, builtin=0)
    return kb_id


def delete_kb(kb_id):
    row = store.get_kb(kb_id)
    if row is None:
        return
    if row["builtin"]:
        raise ValueError("内置知识库不可删除")
    store.delete_kb_row(kb_id)
    shutil.rmtree(kb_paths(kb_id)["base"], ignore_errors=True)
    INGEST_STATUS.pop(kb_id, None)


def index_exists(kb_id):
    return os.path.exists(kb_paths(kb_id)["index"])


def open_store(kb_id):
    p = kb_paths(kb_id)
    if not os.path.exists(p["index"]):
        return None
    return VectorStore(p["index"])


def list_docs(kb_id):
    """列出知识库当前文档（相对路径 + 大小 + 修改时间）。"""
    docs_dir = kb_paths(kb_id)["docs"]
    out = []
    for abs_path, rel in ingest.scan_docs(docs_dir):
        st = os.stat(abs_path)
        out.append(
            {"rel": rel, "size": st.st_size, "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))}
        )
    return out


def import_files(kb_id, src_paths):
    """把用户选择的文件复制进知识库 docs 目录（同名覆盖），返回复制数量。"""
    docs_dir = kb_paths(kb_id)["docs"]
    copied = 0
    for src in src_paths:
        if not os.path.isfile(src):
            continue
        ext = os.path.splitext(src)[1].lower()
        if ext not in parser.SUPPORTED_EXTS:
            continue
        dst = os.path.join(docs_dir, os.path.basename(src))
        shutil.copy2(src, dst)
        copied += 1
    return copied


def import_folder(kb_id, folder):
    """把文件夹里所有支持的文档复制进知识库（递归），返回复制数量。"""
    files = [os.path.join(root, name)
             for root, _dirs, names in os.walk(folder)
             for name in names
             if os.path.splitext(name)[1].lower() in parser.SUPPORTED_EXTS]
    return import_files(kb_id, files)


def save_text_doc(kb_id, name, text):
    """把一段文本存为知识库内的 txt 文档（OCR 校对保存、知识笔记入库共用），返回文件名。

    文件名清洗非法字符，同名自动加序号，永不覆盖已有文档。
    """
    import re

    safe = re.sub(r'[\\/:*?"<>|\r\n]', "_", (name or "未命名").strip()) or "未命名"
    if safe.lower().endswith(".txt"):
        safe = safe[:-4]
    docs_dir = kb_paths(kb_id)["docs"]
    os.makedirs(docs_dir, exist_ok=True)
    path = os.path.join(docs_dir, safe + ".txt")
    n = 2
    while os.path.exists(path):
        path = os.path.join(docs_dir, f"{safe}({n}).txt")
        n += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return os.path.basename(path)


def _stats_path(kb_id):
    """语料统计台账路径（每次索引覆盖更新，重启不丢）。"""
    return os.path.join(kb_paths(kb_id)["base"], "ingest_stats.json")


def load_ingest_stats(kb_id):
    """读取上次索引的统计台账；从未索引过返回 None。"""
    try:
        with open(_stats_path(kb_id), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_ingest_stats(kb_id, payload):
    """原子写入索引统计（成功统计或失败原因），供设置页「语料统计」展示。"""
    os.makedirs(kb_paths(kb_id)["base"], exist_ok=True)
    tmp = _stats_path(kb_id) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _stats_path(kb_id))


def start_ingest(kb_id, settings):
    """后台线程重建索引（增量）。同一库的并发调用自动合并（本轮结束补跑一次）。"""
    p = kb_paths(kb_id)
    os.makedirs(os.path.dirname(p["index"]), exist_ok=True)
    row = store.get_kb(kb_id)
    kb_name = row["name"] if row else kb_id
    lock = INGEST_LOCKS.setdefault(kb_id, threading.Lock())
    if lock.locked():
        # 已有索引任务在跑：标记待补跑（增量索引幂等，最后跑一次覆盖全部变更）
        INGEST_PENDING[kb_id] = True
        return
    lock.acquire()

    def cb(pct, message):
        INGEST_STATUS[kb_id] = {
            "running": True, "pct": pct, "message": message,
            "error": None, "stats": None, "updated_at": time.time(),
        }

    def work():
        try:
            try:
                stats = ingest.build_index(p["index"], p["docs"], kb_name, settings, cb)
                INGEST_STATUS[kb_id] = {
                    "running": False, "pct": 100, "message": "索引完成",
                    "error": None, "stats": stats, "updated_at": time.time(),
                }
                save_ingest_stats(kb_id, {
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "kb_name": kb_name, "error": None, "stats": stats,
                })
                from . import events
                events.record("doc_imported", kb_id=kb_id,
                              succeeded=int(stats.get("succeeded", 0) or 0),
                              failed=int(stats.get("failed", 0) or 0))
            except Exception as e:
                INGEST_STATUS[kb_id] = {
                    "running": False, "pct": 0, "message": "索引失败",
                    "error": str(e), "stats": None, "updated_at": time.time(),
                }
                save_ingest_stats(kb_id, {
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "kb_name": kb_name, "error": str(e), "stats": None,
                })
        finally:
            lock.release()
            if INGEST_PENDING.pop(kb_id, False):
                start_ingest(kb_id, settings)

    INGEST_STATUS[kb_id] = {
        "running": True, "pct": 0, "message": "启动中",
        "error": None, "stats": None, "updated_at": time.time(),
    }
    threading.Thread(target=work, daemon=True).start()


def get_ingest_status(kb_id):
    return INGEST_STATUS.get(kb_id)


def get_ocr_status(kb_id):
    return OCR_STATUS.get(kb_id)


def start_pdf_ocr(kb_id, rel, settings):
    """后台线程整本 OCR：逐页渲染 → 并发识别 → 写 sidecar → 重建索引。

    rel 为 docs 目录内的相对路径（如 「讲义.pdf」）。结果写到「讲义.pdf.ocr.json」，
    增量索引会自动发现并按其分页文本建块（原 pdf 跳过直接解析）。
    """
    p = kb_paths(kb_id)
    abs_path = os.path.normpath(os.path.join(p["docs"], rel))
    if not os.path.isfile(abs_path) or not rel.lower().endswith(".pdf"):
        raise ValueError("文件不存在（仅支持知识库内的 PDF）")
    if OCR_STATUS.get(kb_id, {}).get("running"):
        raise ValueError("该知识库已有 OCR 任务进行中，请稍候")

    import pymupdf

    doc = pymupdf.open(abs_path)
    try:
        total = len(doc)
    finally:
        doc.close()
    if total <= 0:
        raise ValueError("PDF 没有页面")
    if total > config.MAX_PDF_PAGES:
        raise ValueError(f"页数过多（{total} 页，上限 {config.MAX_PDF_PAGES} 页）")

    def work():
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            client = make_client(settings)
            model = settings["ocr_model"]
            doc = pymupdf.open(abs_path)

            def do_page(pageno):
                page = doc[pageno]
                pix = page.get_pixmap(dpi=150)
                uri = ocr.preprocess_image(pix.tobytes("png"))
                if uri is None:
                    raise RuntimeError("页面渲染失败")
                last = None
                for attempt in range(3):
                    try:
                        text = ocr.recognize_image(client, model, uri)
                        return {"page": pageno + 1, "text": text}
                    except Exception as e:
                        last = e
                        time.sleep(1.5 * (attempt + 1))
                raise RuntimeError(f"识别失败：{last}")

            try:
                results = {}
                with ThreadPoolExecutor(max_workers=2) as ex:
                    futs = {ex.submit(do_page, i): i for i in range(total)}
                    done = 0
                    for fut in as_completed(futs):
                        i = futs[fut]
                        try:
                            results[i] = fut.result()
                        except Exception as e:
                            results[i] = {"page": i + 1, "text": "", "error": str(e)}
                        done += 1
                        OCR_STATUS[kb_id] = {
                            "running": True, "pct": int(60 * done / total),
                            "message": f"识别中 {done}/{total} 页",
                            "current": rel, "error": None, "updated_at": time.time(),
                        }
            finally:
                doc.close()

            pages_list = [results[i] for i in range(total)]
            sidecar = abs_path + parser.OCR_SIDECAR_EXT
            tmp = sidecar + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"file": os.path.basename(rel), "pages": pages_list}, f, ensure_ascii=False, indent=1)
            os.replace(tmp, sidecar)

            OCR_STATUS[kb_id] = {
                "running": True, "pct": 90, "message": "识别完成，正在建立索引",
                "current": rel, "error": None, "updated_at": time.time(),
            }
            start_ingest(kb_id, settings)
            from . import events
            events.record("ocr_recognized", kb_id=kb_id, pdf_pages=total)
            OCR_STATUS[kb_id] = {
                "running": False, "pct": 100, "message": "OCR 完成",
                "current": rel, "error": None, "updated_at": time.time(),
            }
        except Exception as e:
            OCR_STATUS[kb_id] = {
                "running": False, "pct": 0, "message": "OCR 失败",
                "current": rel, "error": str(e), "updated_at": time.time(),
            }

    OCR_STATUS[kb_id] = {
        "running": True, "pct": 0, "message": "准备中",
        "current": rel, "error": None, "updated_at": time.time(),
    }
    threading.Thread(target=work, daemon=True).start()
