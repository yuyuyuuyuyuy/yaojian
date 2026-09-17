# -*- coding: utf-8 -*-
"""F13 数据备份与迁移：全量数据包导出 / 覆盖式恢复（本机文件操作，零网络）。

设计要点（PRD F13 验收）：
①导出用 SQLite backup API 在线快照（导出时数据库正在写也不损坏）；
②备份包不含 settings.json——API Key 等凭据永不进备份包；
③恢复=覆盖式：覆盖前旧数据目录改名保留（逃生通道），恢复后沿用当前 settings（Key 与偏好不丢）；
④zip 解压做路径穿越防护（zip slip）。
"""
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
import zipfile

import config

# token -> 暂存目录（进程内存；apply 后弹出）
STAGING = {}


def export_backup():
    """生成备份 zip 到系统临时目录，返回 zip 路径。"""
    tmp_dir = tempfile.mkdtemp(prefix="yaojian_bak_")
    zip_path = os.path.join(
        tempfile.gettempdir(),
        "yaojian-backup-%s.zip" % time.strftime("%Y%m%d-%H%M%S"),
    )
    # chat.db 在线快照（backup API 保证一致性）
    if os.path.exists(config.CHAT_DB_PATH):
        src = sqlite3.connect(config.CHAT_DB_PATH)
        dst = sqlite3.connect(os.path.join(tmp_dir, "chat.db"))
        src.backup(dst)
        dst.close()
        src.close()
    # 知识库全量（docs 源文件 + 索引 + 台账）
    if os.path.exists(config.KBS_DIR):
        shutil.copytree(config.KBS_DIR, os.path.join(tmp_dir, "kbs"))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(tmp_dir):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, tmp_dir))
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return zip_path


def stage_import(zip_path):
    """校验备份包并暂存解压内容，返回 (token, 摘要)。无效包抛 ValueError。"""
    stage = tempfile.mkdtemp(prefix="yaojian_restore_")
    try:
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                if name.startswith("/") or name.startswith("\\") or ".." in name:
                    raise ValueError("备份包内容异常（路径不安全）")
            z.extractall(stage)
        if not os.path.exists(os.path.join(stage, "chat.db")):
            raise ValueError("无效备份包：缺少 chat.db")
        kb_count = 0
        kbs_dir = os.path.join(stage, "kbs")
        if os.path.isdir(kbs_dir):
            kb_count = len([d for d in os.listdir(kbs_dir)
                            if os.path.isdir(os.path.join(kbs_dir, d))])
        try:
            db = sqlite3.connect(os.path.join(stage, "chat.db"))
            conv_count = db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
            db.close()
        except Exception:
            conv_count = -1
        token = uuid.uuid4().hex[:16]
        STAGING[token] = stage
        return token, {"kb_count": kb_count, "conv_count": conv_count}
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def apply_backup(token):
    """覆盖式恢复：旧数据目录改名保留（逃生通道）→ 暂存数据复制到位 → 沿用当前 settings。"""
    stage = STAGING.pop(token, None)
    if not stage:
        raise ValueError("恢复会话不存在或已过期，请重新上传备份包")
    settings_content = None
    if os.path.exists(config.SETTINGS_PATH):
        with open(config.SETTINGS_PATH, "rb") as f:
            settings_content = f.read()
    data_dir = config.DATA_DIR.rstrip("\\/")
    old_dir = data_dir + "_old_" + time.strftime("%Y%m%d-%H%M%S")
    if os.path.exists(data_dir):
        shutil.move(data_dir, old_dir)
    os.makedirs(data_dir, exist_ok=True)
    for item in os.listdir(stage):
        src = os.path.join(stage, item)
        dst = os.path.join(data_dir, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    # 沿用当前配置（Key/模型/主题），恢复只替换数据
    if settings_content:
        os.makedirs(data_dir, exist_ok=True)
        with open(config.SETTINGS_PATH, "wb") as f:
            f.write(settings_content)
    shutil.rmtree(stage, ignore_errors=True)
    return old_dir
