# -*- coding: utf-8 -*-
"""chat.db（SQLite）：会话、消息、知识库注册表。"""
import json
import sqlite3
import time
import uuid

import config


def _connect():
    db = sqlite3.connect(config.CHAT_DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    db = _connect()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS conversations(
            id TEXT PRIMARY KEY, kb_id TEXT, title TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id TEXT,
            role TEXT, content TEXT, citations TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS kbs(
            id TEXT PRIMARY KEY, name TEXT, builtin INTEGER DEFAULT 0, created_at TEXT);
        CREATE TABLE IF NOT EXISTS notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT, keyword TEXT,
            kb_ids TEXT, content TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT,
            event TEXT, conv_id TEXT, kb_id TEXT, payload TEXT, version TEXT);
        CREATE TABLE IF NOT EXISTS cards(
            id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, answer TEXT,
            source_note_id INTEGER, source_kb_id TEXT, created_at TEXT,
            interval_days REAL DEFAULT 0, ease REAL DEFAULT 2.5,
            reps INTEGER DEFAULT 0, due_at TEXT, lapses INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS exam_tags(
            id INTEGER PRIMARY KEY AUTOINCREMENT, kb_id TEXT, file_name TEXT,
            tag TEXT, created_at TEXT);
        """
    )
    try:
        db.execute("ALTER TABLE kbs ADD COLUMN exam INTEGER DEFAULT 0")
    except Exception:
        pass  # 列已存在
    db.commit()
    db.close()


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ---------- 会话 ----------

def parse_scope(value):
    """kb_id 列可能是 "all"、单个 id、或 JSON 数组字符串（二期多选库）；统一解析为 id 列表。"""
    if not value:
        return ["all"]
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list) and parsed:
            return [str(x) for x in parsed]
    except Exception:
        pass
    return [str(value)]


def new_conversation(kb_ids, title=None):
    """kb_ids 可为 id 列表或旧式 "all"/单 id 字符串；列表序列化为 JSON 存入 kb_id 列。"""
    scope = json.dumps([str(x) for x in kb_ids], ensure_ascii=False) if isinstance(kb_ids, list) else str(kb_ids or "all")
    conv_id = uuid.uuid4().hex[:12]
    db = _connect()
    db.execute(
        "INSERT INTO conversations(id, kb_id, title, created_at) VALUES (?,?,?,?)",
        (conv_id, scope, title or "新对话", now()),
    )
    db.commit()
    db.close()
    return conv_id


def list_conversations(kb_id=None):
    db = _connect()
    rows = db.execute("SELECT * FROM conversations ORDER BY created_at DESC").fetchall()
    db.close()
    out = []
    for r in rows:
        d = dict(r)
        d["kb_ids"] = parse_scope(d["kb_id"])
        out.append(d)
    if kb_id:
        out = [d for d in out if "all" in d["kb_ids"] or kb_id in d["kb_ids"]]
    return out


def delete_last_assistant(conv_id):
    """删除会话最后一条助手消息（重新生成时用，保证历史问答配对不重复）。"""
    db = _connect()
    db.execute(
        "DELETE FROM messages WHERE id = (SELECT MAX(id) FROM messages WHERE conv_id=? AND role='assistant')",
        (conv_id,),
    )
    db.commit()
    db.close()


def set_conversation_title(conv_id, title):
    db = _connect()
    db.execute("UPDATE conversations SET title=? WHERE id=?", (title, conv_id))
    db.commit()
    db.close()


def delete_conversation(conv_id):
    db = _connect()
    db.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
    db.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
    db.commit()
    db.close()


def add_message(conv_id, role, content, citations=None):
    db = _connect()
    db.execute(
        "INSERT INTO messages(conv_id, role, content, citations, created_at) VALUES (?,?,?,?,?)",
        (conv_id, role, content, json.dumps(citations or [], ensure_ascii=False), now()),
    )
    db.commit()
    db.close()


def get_messages(conv_id):
    db = _connect()
    rows = db.execute(
        "SELECT * FROM messages WHERE conv_id=? ORDER BY id", (conv_id,)
    ).fetchall()
    db.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["citations"] = json.loads(d["citations"] or "[]")
        except Exception:
            d["citations"] = []
        out.append(d)
    return out


def recent_history(conv_id, max_turns=6):
    """最近若干轮问答（用于多轮上下文），返回 [{"q":..., "a":...}]。"""
    msgs = get_messages(conv_id)
    pairs = []
    for m in msgs:
        if m["role"] == "user":
            pairs.append({"q": m["content"], "a": ""})
        elif pairs and m["role"] == "assistant":
            pairs[-1]["a"] = m["content"]
    return pairs[-max_turns:]


# ---------- 知识库注册表 ----------

def ensure_builtin_kb():
    db = _connect()
    row = db.execute("SELECT id FROM kbs WHERE builtin=1").fetchone()
    if row is None:
        db.execute(
            "INSERT INTO kbs(id, name, builtin, created_at) VALUES (?,?,1,?)",
            (config.BUILTIN_KB_ID, config.BUILTIN_KB_NAME, now()),
        )
        db.commit()
    db.close()


def add_kb(kb_id, name, builtin=0):
    db = _connect()
    db.execute(
        "INSERT INTO kbs(id, name, builtin, created_at) VALUES (?,?,?,?)",
        (kb_id, name, builtin, now()),
    )
    db.commit()
    db.close()


def list_kbs():
    db = _connect()
    rows = db.execute("SELECT * FROM kbs ORDER BY builtin DESC, created_at").fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_kb(kb_id):
    db = _connect()
    row = db.execute("SELECT * FROM kbs WHERE id=?", (kb_id,)).fetchone()
    db.close()
    return dict(row) if row else None


def rename_kb(kb_id, name):
    db = _connect()
    db.execute("UPDATE kbs SET name=? WHERE id=?", (name, kb_id))
    db.commit()
    db.close()


def set_kb_exam(kb_id, exam):
    """F8：知识库用途切换（普通 0 / 考研 1）。"""
    db = _connect()
    db.execute("UPDATE kbs SET exam=? WHERE id=?", (1 if exam else 0, kb_id))
    db.commit()
    db.close()


def delete_kb_row(kb_id):
    db = _connect()
    db.execute("DELETE FROM kbs WHERE id=?", (kb_id,))
    db.commit()
    db.close()


# ---------- 知识笔记（三期） ----------

def save_note(keyword, kb_ids, content):
    """保存一篇整理好的知识笔记，返回笔记 id。"""
    db = _connect()
    cur = db.execute(
        "INSERT INTO notes(keyword, kb_ids, content, created_at) VALUES (?,?,?,?)",
        (keyword, json.dumps([str(x) for x in kb_ids], ensure_ascii=False), content, now()),
    )
    db.commit()
    db.close()
    return cur.lastrowid


def list_notes():
    """全部笔记（含全文，便于直接渲染查看），按创建时间倒序。"""
    db = _connect()
    rows = db.execute("SELECT * FROM notes ORDER BY id DESC").fetchall()
    db.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["kb_ids"] = json.loads(d["kb_ids"] or "[]")
        except Exception:
            d["kb_ids"] = []
        out.append(d)
    return out


def get_note(note_id):
    """按 id 取一篇笔记；不存在返回 None。"""
    db = _connect()
    row = db.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
    db.close()
    if row is None:
        return None
    d = dict(row)
    try:
        d["kb_ids"] = json.loads(d["kb_ids"] or "[]")
    except Exception:
        d["kb_ids"] = []
    return d


def delete_note(note_id):
    db = _connect()
    db.execute("DELETE FROM notes WHERE id=?", (note_id,))
    db.commit()
    db.close()
