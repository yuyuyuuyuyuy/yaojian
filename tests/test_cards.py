# -*- coding: utf-8 -*-
"""F5 背得会冒烟测试（调度/防积压/队列，隔离临时库，零 API 费用）。"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from backend import cards, store


def setup_module(module):
    tmp = tempfile.mkdtemp(prefix="yaojian_cards_test_")
    config.DATA_DIR = tmp
    config.CHAT_DB_PATH = os.path.join(tmp, "chat.db")
    store.init_db()


def test_add_and_due():
    cards.add_cards(1, [
        {"q": "第一法是什么？", "a": "硫代乙酰胺法 [1]"},
        {"q": "第二法是什么？", "a": "炽灼后检查法 [2]"},
    ])
    queue, total = cards.due_queue(20)
    assert total == 2 and len(queue) == 2
    assert cards.stats()["total"] == 2 and cards.stats()["due"] == 2


def test_daily_limit_no_snowball():
    """防积压：到期 5 张、上限 2 → 队列 2 张、total_due 5；剩余不改变 due（顺延不惩罚）。"""
    cards.add_cards(1, [
        {"q": f"问题{i}", "a": f"答案{i}"} for i in range(3)
    ])
    queue, total = cards.due_queue(2)
    assert len(queue) == 2 and total == 5


def test_review_scheduling():
    """SM-2 简化：again 当天重现、good 首次 1 天、easy 加速、hard 减半。"""
    db = sqlite3.connect(config.CHAT_DB_PATH)
    cid = db.execute("SELECT id FROM cards LIMIT 1").fetchone()[0]
    db.close()
    # good（首次）：interval=1
    r = cards.review(cid, "good")
    assert r["interval_days"] == 1 and r["reps"] == 1
    # easy：加速（1*2.5*1.3≈3）
    r = cards.review(cid, "easy")
    assert r["interval_days"] >= 3
    # hard：减半（3*0.5=1.5）
    r = cards.review(cid, "hard")
    assert r["interval_days"] == 1.5
    # again：当天重现（interval=0）、lapses+1
    db = sqlite3.connect(config.CHAT_DB_PATH)
    lapses0 = db.execute("SELECT lapses FROM cards WHERE id=?", (cid,)).fetchone()[0]
    db.close()
    r = cards.review(cid, "again")
    assert r["interval_days"] == 0 and r["reps"] == 0
    db = sqlite3.connect(config.CHAT_DB_PATH)
    lapses1 = db.execute("SELECT lapses FROM cards WHERE id=?", (cid,)).fetchone()[0]
    db.close()
    assert lapses1 == lapses0 + 1


def test_review_invalid_rating():
    try:
        cards.review(1, "excellent")
        assert False, "should raise"
    except ValueError:
        pass


def test_zz_count_by_note():
    # 排序最后运行：此时已添加 5 张（2+3）
    assert cards.count_by_note(1) == 5
    assert cards.count_by_note(999) == 0


def test_stats_reviewed():
    s = cards.stats()
    assert s["reviewed_today"] >= 4  # scheduling 测试触发的 4 次 card_reviewed 事件
    assert s["total"] == 5


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    setup_module(None)
    passed = 0
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
            passed += 1
        except AssertionError as e:
            print("FAIL", fn.__name__, "->", e)
    print(f"{passed}/{len(fns)} 项通过")
