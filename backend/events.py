# -*- coding: utf-8 -*-
"""使用数据埋点（S6 方案落地）：行为事件只写本机 SQLite，绝不上传。

设计纪律：①事件名白名单（防事件膨胀）②payload 禁存大段文本（≤500 字符）
③埋点失败静默（绝不影响主流程）④只记行为不记内容（导出文件不含对话正文）。
北极星口径（2026-09-17 修正）：有效会话 = 会话内有成功回答（命中且非拒答）
或生成笔记或卡片复习或自测完成。
"""
import json
import sqlite3
import time
from datetime import datetime, timedelta

import config

EVENT_WHITELIST = {
    "app_launch", "kb_created", "doc_imported", "question_asked", "answer_done",
    "citation_clicked", "refusal_followup", "note_generated", "note_saved_to_kb",
    "ocr_recognized", "exam_tag_analyzed", "card_created", "card_reviewed", "quiz_started", "quiz_completed",
    "quiz_rated", "quiz_card_rated", "key_replaced", "feedback_submitted",
    "events_exported",
}

MAX_PAYLOAD = 500

# 有效会话判定用的事件名（直接计有效）
_EFFECTIVE_EVENTS = {"note_generated", "card_reviewed", "quiz_completed"}


def record(event, conv_id=None, kb_id=None, **payload):
    """写入一条事件。事件名不在白名单则忽略；payload 超长截断；任何异常静默。"""
    if event not in EVENT_WHITELIST:
        return
    try:
        db = sqlite3.connect(config.CHAT_DB_PATH)
        text = json.dumps(payload, ensure_ascii=False)[:MAX_PAYLOAD]
        db.execute(
            "INSERT INTO events(ts, event, conv_id, kb_id, payload, version) "
            "VALUES(?,?,?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), event, conv_id, kb_id, text, config.VERSION),
        )
        db.commit()
        db.close()
    except Exception:
        pass  # 埋点失败不影响主流程


def _week_start_str():
    """本周一 00:00 的时间字符串。"""
    now = datetime.now()
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday.strftime("%Y-%m-%d %H:%M:%S")


def compute_stats():
    """统计摘要：总量、本周有效学习会话数（北极星）、关键行为计数。"""
    db = sqlite3.connect(config.CHAT_DB_PATH)
    db.row_factory = sqlite3.Row
    total = db.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    week_start = _week_start_str()
    week_rows = db.execute(
        "SELECT event, conv_id FROM events WHERE ts >= ?", (week_start,)
    ).fetchall()
    effective_convs = set()
    counts = {}
    for r in week_rows:
        counts[r["event"]] = counts.get(r["event"], 0) + 1
        if r["event"] in _EFFECTIVE_EVENTS and r["conv_id"]:
            effective_convs.add(r["conv_id"])
    # 成功回答（answer_done 且 hit）的会话也算有效
    for r in db.execute(
        "SELECT conv_id, payload FROM events WHERE ts >= ? AND event='answer_done'",
        (week_start,),
    ).fetchall():
        try:
            if json.loads(r["payload"] or "{}").get("hit"):
                effective_convs.add(r["conv_id"])
        except Exception:
            pass
    db.close()
    return {
        "total_events": total,
        "week_start": week_start[:10],
        "week_effective_sessions": len(effective_convs),
        "week_counts": counts,
    }


def last_answer(conv_id):
    """该会话最近一次 answer_done 的 (ts, hit)；无记录返回 (None, None)。"""
    db = sqlite3.connect(config.CHAT_DB_PATH)
    row = db.execute(
        "SELECT ts, payload FROM events WHERE conv_id=? AND event='answer_done' "
        "ORDER BY id DESC LIMIT 1", (conv_id,),
    ).fetchone()
    db.close()
    if not row:
        return None, None
    try:
        hit = json.loads(row[1] or "{}").get("hit")
    except Exception:
        hit = None
    return row[0], hit


def export_payload():
    """导出数据：事件流 JSON（events 表本身不存对话文本）+ 摘要 CSV。"""
    db = sqlite3.connect(config.CHAT_DB_PATH)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT ts, event, conv_id, kb_id, payload, version FROM events ORDER BY id"
    ).fetchall()
    db.close()
    events = [dict(r) for r in rows]
    stats = compute_stats()
    lines = [
        "指标,值",
        f"事件总数,{stats['total_events']}",
        f"本周起始,{stats['week_start']}",
        f"本周有效学习会话数,{stats['week_effective_sessions']}",
    ]
    for k in sorted(stats["week_counts"]):
        lines.append(f"本周事件:{k},{stats['week_counts'][k]}")
    return {"events": events, "summary_csv": "\n".join(lines), "stats": stats}


def clear_events():
    db = sqlite3.connect(config.CHAT_DB_PATH)
    db.execute("DELETE FROM events")
    db.commit()
    db.close()
