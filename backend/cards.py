# -*- coding: utf-8 -*-
"""F5 背得会：记忆卡片——SM-2 简化调度 + 防积压队列 + 埋点。

调度（PRD 四键自评）：忘记=当天重现（ease 降）；困难=间隔减半；正常=按 ease 推进
（首次 1 天）；轻松=1.3 倍加速。防积压：每日复习上限（settings.card_daily_limit，
默认 20），到期卡超上限当日按上限出队、剩余顺延（不改变 due、不惩罚）。
"""
import sqlite3
import time
from datetime import datetime, timedelta

import config
from backend import events

RATINGS = ("again", "hard", "good", "easy")


def _connect():
    db = sqlite3.connect(config.CHAT_DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def add_cards(note_id, pairs, kb_id=None):
    """批量入库卡对（pairs=[{q,a}]）；新卡当日到期。返回张数。"""
    now = _now()
    db = _connect()
    for p in pairs:
        db.execute(
            "INSERT INTO cards(question, answer, source_note_id, source_kb_id, created_at, due_at) "
            "VALUES(?,?,?,?,?,?)",
            (p["q"], p["a"], note_id, kb_id, now, now),
        )
    db.commit()
    db.close()
    events.record("card_created", count=len(pairs))
    return len(pairs)


def due_queue(limit):
    """到期队列：按上限取卡（防积压），并返回总到期数（剩余顺延不改变 due）。"""
    db = _connect()
    rows = db.execute(
        "SELECT * FROM cards WHERE due_at <= ? ORDER BY due_at, id LIMIT ?",
        (_now(), limit),
    ).fetchall()
    total = db.execute(
        "SELECT COUNT(*) AS n FROM cards WHERE due_at <= ?", (_now(),)
    ).fetchone()["n"]
    db.close()
    return [dict(r) for r in rows], total


def review(card_id, rating):
    """四键自评 → SM-2 简化调度；返回更新后的调度信息。"""
    if rating not in RATINGS:
        raise ValueError("无效的自评等级")
    db = _connect()
    row = db.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
    if row is None:
        db.close()
        return None
    ease, reps, interval, lapses = row["ease"], row["reps"], row["interval_days"], row["lapses"]
    if rating == "again":
        reps, interval = 0, 0
        lapses += 1
        ease = max(1.3, ease - 0.2)
    else:
        reps += 1
        if rating == "hard":
            ease = max(1.3, ease - 0.1)
            interval = max(1.0, interval * 0.5)
        elif rating == "good":
            interval = 1 if reps == 1 else max(1, round(interval * ease))
        else:  # easy
            ease = min(2.5, ease + 0.1)
            interval = 1 if reps == 1 else max(1, round(interval * ease * 1.3))
    due = datetime.now() if interval == 0 else datetime.now() + timedelta(days=interval)
    due_str = due.strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "UPDATE cards SET reps=?, interval_days=?, ease=?, lapses=?, due_at=? WHERE id=?",
        (reps, interval, ease, lapses, due_str, card_id),
    )
    db.commit()
    db.close()
    events.record("card_reviewed", count=1, rating=rating)
    return {"interval_days": interval, "due_at": due_str, "reps": reps}


def stats():
    """总卡数 / 今日到期数 / 今日已复习数。"""
    db = _connect()
    total = db.execute("SELECT COUNT(*) AS n FROM cards").fetchone()["n"]
    due = db.execute(
        "SELECT COUNT(*) AS n FROM cards WHERE due_at <= ?", (_now(),)
    ).fetchone()["n"]
    reviewed_today = db.execute(
        "SELECT COUNT(*) AS n FROM events WHERE event='card_reviewed' AND ts >= ?",
        (datetime.now().strftime("%Y-%m-%d 00:00:00"),),
    ).fetchone()["n"]
    db.close()
    return {"total": total, "due": due, "reviewed_today": reviewed_today}


def count_by_note(note_id):
    db = _connect()
    n = db.execute(
        "SELECT COUNT(*) AS n FROM cards WHERE source_note_id=?", (note_id,)
    ).fetchone()["n"]
    db.close()
    return n


def default_daily_limit(settings):
    return int(settings.get("card_daily_limit") or config.DEFAULT_SETTINGS["card_daily_limit"])
