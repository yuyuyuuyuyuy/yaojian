# -*- coding: utf-8 -*-
"""H5 补跑：口语化 vs 书面化在【自建库】上的检索表现（内置库已跑过，见 h5_colloquial.py）。

局限说明：内置 QC 库语料是精心编写的行级知识点，对问法鲁棒；学生主要使用的
是自建课程库（自然段落文本）。本脚本用「手写笔记验收」库（物化笔记，OCR 入库）
补跑，题目主题取自该库已验收的命中主题。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import embeddings, kb, search
from backend.server import load_settings

KB_ID = "05362fa5"  # 手写笔记验收（物化笔记）

QA_PAIRS = [
    ("道尔顿分压定律的内容是什么？", [
        "道尔顿分压定律讲的是啥？",
        "分压定律是什么意思？",
        "道尔顿分压定律怎么理解？"]),
    ("体积功的定义式是什么？", [
        "体积功的公式是什么？",
        "体积功怎么算？",
        "求体积功的公式是哪个？"]),
    ("波义尔定律的内容是什么？", [
        "波义尔定律说的是什么？",
        "波义尔定律是啥意思？",
        "波义尔定律讲什么？"]),
    ("热力学第一定律的数学表达式是什么？", [
        "热力学第一定律的公式？",
        "热一公式是啥？",
        "热力学第一定律怎么写？"]),
    ("理想气体状态方程是什么？", [
        "理想气体的公式是什么？",
        "理想气体状态方程怎么表示？",
        "理想气体方程是啥？"]),
]

TOP_K, THRESHOLD = 6, 0.3


def run_one(client, store, q, model):
    vec = search.query_vector(client, q, model)
    hits = search.search_store(store, vec, TOP_K, THRESHOLD)
    if not hits:
        return None, 0
    return hits[0]["score"], len(hits)


def main():
    settings = load_settings()
    client = embeddings.make_client(settings)
    embed_model = settings["embed_model"]
    kb.ensure_data_dirs()
    store = kb.open_store(KB_ID)

    w_miss = w_scores = c_miss = c_scores = 0
    lines = ["=" * 60, f"H5 补跑报告（自建库：{KB_ID} 手写笔记验收）",
             f"检索参数：top_k={TOP_K} 阈值={THRESHOLD}", "=" * 60]
    n_w = n_c = 0
    for w, variants in QA_PAIRS:
        ws, wn = run_one(client, store, w, embed_model)
        if ws is None:
            lines.append(f"[剔除] 书面题不在库中：{w}")
            continue
        n_w += 1
        w_scores += ws
        w_miss += 1 if ws is None else 0
        lines.append(f"W  {w:<40} top1={ws:.3f} hits={wn}")
        for c in variants:
            cs, cn = run_one(client, store, c, embed_model)
            n_c += 1
            c_scores += cs if cs is not None else 0
            c_miss += 1 if cs is None else 0
            lines.append(f"  C {c:<40} top1={cs if cs is not None else 0:.3f} hits={cn}")

    lines.append("-" * 60)
    lines.append(f"书面版：{n_w} 条，零命中 {w_miss}，未命中率 {w_miss/n_w:.0%}，平均最高分 {w_scores/n_w:.3f}")
    lines.append(f"口语版：{n_c} 条，零命中 {c_miss}，未命中率 {c_miss/n_c:.0%}，平均最高分 {c_scores/n_c:.3f}")
    verdict = ("H5 在自建库成立：口语化未命中率 >30% 或明显高于书面版"
               if (c_miss/n_c > 0.30 or c_miss/n_c > w_miss/max(n_w,1) + 0.10)
               else "H5 在自建库不成立：口语化与书面版无显著差距")
    lines.append(verdict)
    report = "\n".join(lines)
    print(report)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_reports", "h5_colloquial2_自建库.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print("\n报告已写入", out)


if __name__ == "__main__":
    main()
