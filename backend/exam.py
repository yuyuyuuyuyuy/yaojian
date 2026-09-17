# -*- coding: utf-8 -*-
"""F8 考研场景包：考点标记——AI 自动提取 + 人工修正（标注可见可改，不强迫信任）。"""
import json
import sqlite3
import time

import config

TAG_ANALYZE_PROMPT = """你是「药鉴」的考点分析助手。下面是一份考研真题/讲义的内容。请提取其中的考点标签（3~8 个），标签=简短的专业术语（如「色谱分析」「酸碱滴定」「重金属检查法」），用于「考点分布」整理。

只输出 JSON 数组：["考点1","考点2"]，不要任何其他文字。内容太少或无明确考点时输出 []。

内容：
{content}"""


def _connect():
    db = sqlite3.connect(config.CHAT_DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def analyze_content(client, settings, content):
    """LLM 提取考点标签（JSON 数组），失败/空返回 []。"""
    resp = client.chat.completions.create(
        model=settings["llm_model"],
        messages=[
            {"role": "system", "content": "只输出 JSON 数组，不要任何其他文字。"},
            {"role": "user", "content": TAG_ANALYZE_PROMPT.format(content=content[:5000])},
        ],
        temperature=0,
        max_tokens=400,
    )
    raw = (resp.choices[0].message.content or "").strip()
    try:
        start, end = raw.find("["), raw.rfind("]")
        if start >= 0 and end > start:
            raw = raw[start:end + 1]
        items = json.loads(raw)
        return [str(x).strip() for x in items if str(x).strip()][:8]
    except Exception:
        return []


def set_tags(kb_id, file_name, tags):
    """分析完成后替换该文件的标签（先删后插）。"""
    db = _connect()
    db.execute("DELETE FROM exam_tags WHERE kb_id=? AND file_name=?", (kb_id, file_name))
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for t in tags:
        db.execute("INSERT INTO exam_tags(kb_id, file_name, tag, created_at) VALUES(?,?,?,?)",
                   (kb_id, file_name, t, now))
    db.commit()
    db.close()


def add_tag(kb_id, file_name, tag):
    tag = (tag or "").strip()
    if not tag:
        return
    db = _connect()
    db.execute("INSERT INTO exam_tags(kb_id, file_name, tag, created_at) VALUES(?,?,?,?)",
               (kb_id, file_name, tag, time.strftime("%Y-%m-%d %H:%M:%S")))
    db.commit()
    db.close()


def delete_tag(tag_id):
    db = _connect()
    db.execute("DELETE FROM exam_tags WHERE id=?", (tag_id,))
    db.commit()
    db.close()


def list_tags(kb_id):
    """考点总览：按文件分组的标签列表。"""
    db = _connect()
    rows = db.execute(
        "SELECT * FROM exam_tags WHERE kb_id=? ORDER BY file_name, id", (kb_id,)
    ).fetchall()
    db.close()
    out = []
    for r in rows:
        out.append({"id": r["id"], "file_name": r["file_name"], "tag": r["tag"]})
    return out


def pending_files(kb_id, docs):
    """有文档但还没有标签的文件（docs 为该库 docs 目录下的文件名列表）。"""
    db = _connect()
    tagged = {r["file_name"] for r in db.execute(
        "SELECT DISTINCT file_name FROM exam_tags WHERE kb_id=?", (kb_id,)
    ).fetchall()}
    db.close()
    return [d for d in docs if d not in tagged]
