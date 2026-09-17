# -*- coding: utf-8 -*-
"""全局配置：路径、默认设置。本文件是纯常量，不含任何密钥。"""
import os
import sys

APP_NAME = "药鉴"
VERSION = "0.4.0"

# 代码目录（打包后是程序目录，开发时是 app 目录）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 内置语料目录（随程序打包，只读）
BUILTIN_DOCS_DIR = os.path.join(BASE_DIR, "res", "builtin_kb", "docs")
# 防幻觉系统提示词文件
PROMPT_PATH = os.path.join(BASE_DIR, "prompts", "qa_system.txt")
# 知识笔记整理提示词文件（三期：关键词 → 结构化笔记）
NOTE_PROMPT_PATH = os.path.join(BASE_DIR, "prompts", "note_system.txt")

# 用户数据目录：程序目录只放只读内容，一切可变数据放这里
def _data_dir():
    if sys.platform == "win32":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(root, "LabAssistant")
    elif sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "LabAssistant")
    else:
        return os.path.join(os.path.expanduser("~"), ".lab_assistant")

DATA_DIR = _data_dir()
KBS_DIR = os.path.join(DATA_DIR, "kbs")          # 每个知识库一个子文件夹
CHAT_DB_PATH = os.path.join(DATA_DIR, "chat.db") # 会话/消息/知识库元数据
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

BUILTIN_KB_ID = "builtin_qc"
BUILTIN_KB_NAME = "QC检验知识库（内置）"

def _load_local_key():
    """内置 Key 从本地文件读取（该文件不进 git 仓库）；打包时随包分发，开箱即用。"""
    try:
        with open(os.path.join(BASE_DIR, "local_key.txt"), encoding="utf-8") as f:
            key = f.read().strip()
            return key or ""
    except OSError:
        return ""


# 默认设置（api_key 为内置共享 Key，开箱即用；设置页可替换成自己的）
DEFAULT_SETTINGS = {
    "api_key": _load_local_key(),
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "llm_model": "qwen-plus",
    "embed_model": "text-embedding-v4",
    "temperature": 0,          # 防幻觉：固定为 0，设置页展示但不可改
    "top_k": 6,                # 检索条数
    "score_threshold": 0.3,    # 相似度阈值，低于则视为未命中
    "ocr_model": "qwen3-vl-plus",  # OCR 多模态模型（手写/公式优先；印刷体可换 qwen-vl-ocr-latest 更省）
    "theme": "auto",           # 外观主题：auto / light / dark
    "card_daily_limit": 20,    # 背得会：每日复习卡量上限（防积压，K11 教训）
    "first_run": True,         # 首次启动向导（旧版标记，保留兼容）
    "onboarding_done": False,  # 首次使用引导（分步向导）是否已完成，完成/跳过后不再显示
}

# 单文件上传限制
MAX_FILE_MB = 20
MAX_PDF_PAGES = 200

# 百炼控制台余额查询地址（提示用户用）
BAILIAN_CONSOLE_URL = "https://bailian.console.aliyun.com/"

