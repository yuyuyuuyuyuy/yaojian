# -*- coding: utf-8 -*-
"""F8 考研场景包冒烟测试（考点标记 CRUD、pending、模式切换，隔离临时库，零 API 费用）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from backend import exam, store


def setup_module(module):
    tmp = tempfile.mkdtemp(prefix="yaojian_exam_test_")
    config.DATA_DIR = tmp
    config.CHAT_DB_PATH = os.path.join(tmp, "chat.db")
    store.init_db()
    store.add_kb("kb_exam", "药学综合", builtin=0)


def test_set_and_list():
    exam.set_tags("kb_exam", "2024真题.pdf", ["色谱分析", "酸碱滴定", "重金属检查法"])
    tags = exam.list_tags("kb_exam")
    assert len(tags) == 3
    assert {t["tag"] for t in tags} == {"色谱分析", "酸碱滴定", "重金属检查法"}


def test_replace_and_manual():
    # 重新分析=替换（先删后插），不叠加
    exam.set_tags("kb_exam", "2024真题.pdf", ["色谱分析"])
    assert len(exam.list_tags("kb_exam")) == 1
    # 手动加
    exam.add_tag("kb_exam", "2024真题.pdf", "滴定终点判断")
    assert len(exam.list_tags("kb_exam")) == 2
    # 删除
    tid = exam.list_tags("kb_exam")[0]["id"]
    exam.delete_tag(tid)
    assert len(exam.list_tags("kb_exam")) == 1


def test_zz_pending_files():
    # 排序最后运行：此时 2024真题.pdf 已有标签（前面测试写入）
    docs = ["2024真题.pdf", "讲义.pdf", "课件.pptx"]
    pending = exam.pending_files("kb_exam", docs)
    assert pending == ["讲义.pdf", "课件.pptx"]


def test_kb_exam_switch():
    store.set_kb_exam("kb_exam", True)
    assert store.get_kb("kb_exam")["exam"] == 1
    store.set_kb_exam("kb_exam", False)
    assert store.get_kb("kb_exam")["exam"] == 0


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
