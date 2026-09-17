# -*- coding: utf-8 -*-
"""F13 备份迁移冒烟测试（隔离临时数据目录，零 API 费用）：
导出（backup API 快照、不含 settings/Key）、校验（摘要、无效包、zip slip）、
覆盖恢复（数据完好、settings 沿用、逃生通道保留）。"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from backend import backup, store

TMP_ROOT = None


def setup_module(module):
    global TMP_ROOT
    TMP_ROOT = tempfile.mkdtemp(prefix="yaojian_backup_test_")
    config.DATA_DIR = os.path.join(TMP_ROOT, "data")
    config.KBS_DIR = os.path.join(config.DATA_DIR, "kbs")
    config.CHAT_DB_PATH = os.path.join(config.DATA_DIR, "chat.db")
    config.SETTINGS_PATH = os.path.join(config.DATA_DIR, "settings.json")
    os.makedirs(config.KBS_DIR, exist_ok=True)
    store.init_db()
    conv = store.new_conversation(["all"], "测试对话")
    store.add_message(conv, "user", "测试问题")
    os.makedirs(os.path.join(config.KBS_DIR, "kb1", "docs"), exist_ok=True)
    with open(os.path.join(config.KBS_DIR, "kb1", "docs", "note.txt"), "w", encoding="utf-8") as f:
        f.write("测试文档")
    with open(config.SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump({"api_key": "sk-secret-should-not-export"}, f)


def test_export_no_settings():
    zip_path = backup.export_backup()
    assert os.path.exists(zip_path)
    names = zipfile.ZipFile(zip_path).namelist()
    assert "chat.db" in names
    assert any(n.startswith("kbs/kb1/") for n in names)
    assert "settings.json" not in names  # Key 永不进备份包
    blob = b"".join(zipfile.ZipFile(zip_path).open(n).read() for n in names if n.endswith(".txt") or n == "chat.db")
    assert b"sk-secret-should-not-export" not in blob


def test_stage_and_apply():
    zip_path = backup.export_backup()
    token, summary = backup.stage_import(zip_path)
    assert summary["kb_count"] == 1 and summary["conv_count"] >= 1
    # 恢复前再写一条新数据（将被覆盖——覆盖式语义）
    store.add_message(store.new_conversation(["all"], "恢复后不该存在的对话"), "user", "新数据")
    old_dir = backup.apply_backup(token)
    assert os.path.exists(old_dir)  # 逃生通道
    # 数据被恢复包覆盖：新对话消失
    db = sqlite3.connect(config.CHAT_DB_PATH)
    n = db.execute("SELECT COUNT(*) FROM conversations WHERE title=?", ("恢复后不该存在的对话",)).fetchone()[0]
    db.close()
    assert n == 0
    # settings 沿用（Key 保留在本地配置，未被覆盖）
    with open(config.SETTINGS_PATH, encoding="utf-8") as f:
        assert json.load(f)["api_key"] == "sk-secret-should-not-export"


def test_invalid_zip():
    bad = os.path.join(TMP_ROOT, "bad.zip")
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("README.txt", "not a backup")
    try:
        backup.stage_import(bad)
        assert False, "should raise"
    except ValueError as e:
        assert "chat.db" in str(e)


def test_zip_slip_guard():
    evil = os.path.join(TMP_ROOT, "evil.zip")
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("chat.db", "")
        z.writestr("../evil.txt", "x")
    try:
        backup.stage_import(evil)
        assert False, "should raise"
    except ValueError as e:
        assert "路径不安全" in str(e)


def test_apply_bad_token():
    try:
        backup.apply_backup("no_such_token")
        assert False, "should raise"
    except ValueError as e:
        assert "不存在或已过期" in str(e)


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
