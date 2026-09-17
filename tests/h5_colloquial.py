# -*- coding: utf-8 -*-
"""H5 离线验证：口语化问法 vs 书面化问法的检索表现对比。

假设：口语化问法（"重金属怎么测"）比书面化问法（"重金属检查法有哪些方法"）的
检索未命中率显著更高（H5，对应痛点 P7）。
方法：取验收集 10 道书面题 + 每题 3 条口语化改写（共 40 条查询），对内置 QC 库
跑检索（top_k=6、阈值 0.3），对比零命中率与平均最高分。
判定：口语化版未命中率 >30% 或明显高于书面版 → H5 成立 → A7 需求升级 P0。
用法：python tests/h5_colloquial.py（依赖 app venv；费用约 40 条 embedding，<0.1 元）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from backend import embeddings, kb, search
from backend.server import load_settings

# (书面题, [口语化改写 x3])
QA_PAIRS = [
    ("电子天平使用有哪些注意事项？", [
        "天平用的时候要注意啥？",
        "用电子天平称东西有什么讲究吗？",
        "称量的时候天平有哪些注意事项？"]),
    ("标准氯化钠溶液和标准铅溶液的浓度是多少？各用于什么检查？", [
        "氯化钠标准溶液浓度是多少来着？",
        "配氯化钠和铅的标准液浓度要多少？",
        "氯化钠标准液和铅标准液浓度各是多少？干什么用的？"]),
    ("检测药物内一般杂质的基础项目和合格范围是什么？", [
        "药物里一般杂质要查哪些？合格标准是什么？",
        "药品的一般杂质都检测啥？限度多少算合格？",
        "一般杂质检查包括哪些项目？合格范围是啥？"]),
    ("重金属检查法有几种方法？各适用什么情况？", [
        "重金属怎么测？有几种方法？",
        "重金属检查怎么做？有哪些方法？",
        "测重金属有哪几种方法？分别什么时候用？"]),
    ("干燥失重测定法的操作要点和恒重定义是什么？", [
        "干燥失重怎么操作？什么算恒重？",
        "干燥失重测的时候要注意什么？恒重是什么意思？",
        "干燥失重咋做？恒重怎么判断？"]),
    ("氯化物检查法的原理和结果判断方法？", [
        "氯化物怎么检查？结果怎么判断？",
        "氯化物检查的原理是什么？怎么看结果合不合格？",
        "氯化物检查怎么做？怎么算合格？"]),
    ("HPLC系统适用性试验包括哪些项目？合格标准是什么？", [
        "HPLC系统适用性要测哪些指标？多少算合格？",
        "高效液相的系统适用性试验包括啥？合格标准是什么？",
        "跑液相之前系统适用性怎么检查？有哪些项目？"]),
    ("微生物限度检查包括哪些项目？", [
        "微生物限度要检查哪些？",
        "微生物限度检查包括什么项目？",
        "药品微生物限度检查都查啥？"]),
    ("无菌检查法的培养基和培养条件是什么？", [
        "无菌检查用什么培养基？培养条件是什么？",
        "无菌检查怎么做？培养基和培养温度有什么要求？",
        "无菌检查的培养基是啥？要培养多久？"]),
    ("计算机化系统验证的基本原则是什么？", [
        "计算机化系统验证的原则是什么？",
        "计算机系统的验证要遵循什么原则？",
        "计算机化系统怎么验证？基本原则是啥？"]),
]

TOP_K, THRESHOLD = 6, 0.3


def run_one(client, store, q, model):
    vec = search.query_vector(client, q, model)
    hits = search.search_store(store, vec, TOP_K, THRESHOLD)
    if not hits:
        return None, None  # 零命中
    return hits[0]["score"], len(hits)


def main():
    settings = load_settings()
    client = embeddings.make_client(settings)
    embed_model = settings["embed_model"]
    kb.ensure_data_dirs()
    store = kb.open_store(config.BUILTIN_KB_ID)

    written_miss, written_scores = 0, []
    collo_miss, collo_scores = 0, []
    rows = []
    for w, variants in QA_PAIRS:
        ws, wn = run_one(client, store, w, embed_model)
        written_scores.append(ws if ws is not None else 0.0)
        written_miss += 1 if ws is None else 0
        row = [f"W  {w}", f"top1={ws if ws is None else round(ws,3)} hits={wn}"]
        rows.append(row)
        for c in variants:
            cs, cn = run_one(client, store, c, embed_model)
            collo_scores.append(cs if cs is not None else 0.0)
            collo_miss += 1 if cs is None else 0
            rows.append([f"  C {c}", f"top1={cs if cs is None else round(cs,3)} hits={cn}"])

    n_w, n_c = 10, 30
    lines = []
    lines.append("=" * 60)
    lines.append("H5 口语化 vs 书面化 检索实验报告")
    lines.append(f"检索参数：top_k={TOP_K} 阈值={THRESHOLD} 库=内置 QC 检验知识库")
    lines.append("=" * 60)
    lines.append(f"书面版：{n_w} 条，零命中 {written_miss} 条，未命中率 {written_miss/n_w:.0%}，平均最高分 {sum(written_scores)/n_w:.3f}")
    lines.append(f"口语版：{n_c} 条，零命中 {collo_miss} 条，未命中率 {collo_miss/n_c:.0%}，平均最高分 {sum(collo_scores)/n_c:.3f}")
    lines.append("-" * 60)
    for r in rows:
        lines.append(f"{r[0]:<58} {r[1]}")
    lines.append("=" * 60)
    verdict = ("H5 成立：口语化未命中率 >30% 或明显高于书面版 → A7 需求升级 P0"
               if (collo_miss/n_c > 0.30 or collo_miss/n_c > written_miss/n_w + 0.10)
               else "H5 不成立：口语化与书面版检索表现无明显差距 → A7 维持 P1")
    lines.append(verdict)
    report = "\n".join(lines)
    print(report)
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval_reports", "h5_colloquial.txt")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print("\n报告已写入", out_path)


if __name__ == "__main__":
    main()
