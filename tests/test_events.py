# -*- coding: utf-8 -*-
"""埋点模块冒烟测试（S6 落地验收）：
record 落库/白名单/超长截断/静默失败、有效会话口径、导出无对话内容、清空。
测试用临时数据库（隔离，不污染真实数据），零 API 费用。
"""
import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from backend import events


def setup_module(module):
    tmp = tempfile.mkdtemp(prefix="yaojian_events_test_")
    config.DATA_DIR = tmp
    config.CHAT_DB_PATH = os.path.join(tmp, "chat.db")
    db = sqlite3.connect(config.CHAT_DB_PATH)
    db.executescript(
        """CREATE TABLE events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,
            event TEXT, conv_id TEXT, kb_id TEXT, payload TEXT, version TEXT);"""
    )
    db.commit()
    db.close()


def _rows():
    db = sqlite3.connect(config.CHAT_DB_PATH)
    rows = db.execute("SELECT event, conv_id, kb_id, payload FROM events ORDER BY id").fetchall()
    db.close()
    return rows


def test_record_basic():
    events.record("question_asked", conv_id="c1", kb_id="k1", scope_type="single")
    rows = _rows()
    assert rows[-1][0] == "question_asked" and rows[-1][1] == "c1" and rows[-1][2] == "k1"
    assert json.loads(rows[-1][3])["scope_type"] == "single"


def test_whitelist_rejects_unknown():
    n0 = len(_rows())
    events.record("not_an_event")
    assert len(_rows()) == n0


def test_payload_truncated():
    events.record("question_asked", conv_id="c1", long=("x" * 2000))
    rows = _rows()
    assert len(rows[-1][3]) <= events.MAX_PAYLOAD


def test_record_never_raises():
    # 白名单事件 + 极端 payload 也不该抛（静默失败纪律）
    events.record("answer_done", conv_id="c1", weird=object())


def test_effective_sessions_koujing():
    """北极星口径：成功回答（hit=1）会话算有效；拒答（hit=0）不算；note_generated 算。"""
    events.clear_events()
    events.record("answer_done", conv_id="conv_hit", hit=True)
    events.record("answer_done", conv_id="conv_miss", hit=False, refused=True)
    events.record("note_generated", conv_id="conv_note")
    s = events.compute_stats()
    assert s["week_effective_sessions"] == 2  # conv_hit + conv_note


def test_last_answer():
    events.clear_events()
    events.record("answer_done", conv_id="c9", hit=False, refused=True)
    ts, hit = events.last_answer("c9")
    assert hit is False and ts
    ts2, hit2 = events.last_answer("c_none")
    assert ts2 is None


def test_export_no_chat_content():
    """导出只含事件流（行为），不含任何对话文本。"""
    events.clear_events()
    events.record("question_asked", conv_id="c1", kb_id="k1")
    p = events.export_payload()
    assert isinstance(p["events"], list) and len(p["events"]) == 1
    blob = json.dumps(p["events"], ensure_ascii=False)
    assert "question_asked" in blob and "c1" in blob
    # 模拟对话内容混入 payload 的尝试（长文本会被截断到 500 字符内）
    assert len(p["events"][0]["payload"]) <= 500
    assert "指标,值" in p["summary_csv"] and "有效学习会话" in p["summary_csv"]


def test_clear():
    events.record("app_launch")
    events.clear_events()
    assert len(_rows()) == 0


def test_stats_counts():
    events.clear_events()
    events.record("question_asked", conv_id="c1")
    events.record("question_asked", conv_id="c1")
    s = events.compute_stats()
    assert s["week_counts"]["question_asked"] == 2
    assert s["total_events"] == 2


if __name__ == "__main__":
    # 简易运行器（不依赖 pytest 也可直接跑）
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
