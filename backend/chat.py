# -*- coding: utf-8 -*-
"""对话编排：检索命中 → 拼装防幻觉提示词 → 流式生成 → 引用解析。

无命中时由调用方直接返回拒答语，不发 API（省钱的第二道防线）。
"""
import re

import config


def load_system_prompt():
    try:
        with open(config.PROMPT_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "你是「药鉴」。只能依据【参考资料】回答，每个结论后紧跟引用编号 [n]，查不到就说“资料中未找到相关内容”。"


MODULE_POOL = [
    ("definition", "定义与概述", "关键词是什么、所属学科/章节"),
    ("points", "核心要点", "主要知识点分点列出"),
    ("formula", "公式与数据", "公式、常数、限度数值，注明符号含义与适用条件"),
    ("method", "原理与机制", "背后的原理、反应机制、工作原理"),
    ("operation", "操作方法", "操作步骤、实验方法、流程"),
    ("scope", "适用范围与条件", "适用/不适用的情况、限定条件"),
    ("pitfall", "易错与注意", "易混点、注意事项、限定条件"),
    ("mnemonic", "记忆技巧", "口诀、联想、记忆方法"),
]

MODULE_ANALYZE_PROMPT = """你是「药鉴」的笔记模块分析助手。用户要整理主题「{keyword}」，下面是检索到的参考资料。

请判断以下候选模块中，哪些在参考资料中有实质内容（≥1 条可写的内容）：
{pool}

只输出 JSON 数组（不要任何其他文字），格式：[{{"key": "模块key", "desc": "该模块将包含什么的一句话描述"}}]。
只列出有实质内容的模块；参考资料完全没有相关内容时输出 []。"""


def analyze_modules(client, settings, keyword, hits):
    """关键词 → 检索内容 → 动态判断该主题实际具备哪些模块（F6 两步式第一步）。"""
    pool_text = "\n".join(f"- {key}（{title}）：{desc}" for key, title, desc in MODULE_POOL)
    prompt = MODULE_ANALYZE_PROMPT.format(keyword=keyword, pool=pool_text)
    resp = client.chat.completions.create(
        model=settings["llm_model"],
        messages=[
            {"role": "system", "content": "只输出 JSON 数组，不要任何其他文字。"},
            {"role": "user", "content": build_user_content(prompt, hits, [])},
        ],
        temperature=0,
        max_tokens=600,
    )
    raw = (resp.choices[0].message.content or "").strip()
    try:
        import json as _json
        start, end = raw.find("["), raw.rfind("]")
        if start >= 0 and end > start:
            raw = raw[start:end + 1]
        items = _json.loads(raw)
    except Exception:
        return []
    titles = {k: t for k, t, _d in MODULE_POOL}
    return [
        {"key": it["key"], "title": titles.get(it["key"], it["key"]), "desc": it.get("desc", "")}
        for it in items
        if isinstance(it, dict) and it.get("key") in titles
    ]


def generate_note(client, settings, keyword, hits, modules=None, outline=False):
    """关键词 → 结构化知识笔记（非流式）。

    modules：选定的模块 key 列表（None=全部候选）；outline：True=层级大纲格式（思维导图用）。
    """
    try:
        with open(config.NOTE_PROMPT_PATH, encoding="utf-8") as f:
            template = f.read().strip()
    except Exception:
        template = "把用户关键词整理成结构化知识笔记，只依据参考资料，每个结论带引用编号 [n]。"
    chosen = [m for m in MODULE_POOL if modules is None or m[0] in modules]
    modules_text = "\n".join(f"### {title}\n（{desc}）" for _k, title, desc in chosen) or "（全部候选模块）"
    fmt = ("用 Markdown 层级结构输出（## 主题 → ### 模块 → 缩进要点列表），"
           "每个要点尽量一句话，适合渲染成思维导图树形；不要写大段正文。"
           if outline else
           "用 Markdown 正文格式输出（## 主题 → ### 模块 → 分点列表，要点可带简短解释）。")
    system = template.replace("{modules}", modules_text).replace("{format_instruction}", fmt)
    resp = client.chat.completions.create(
        model=settings["llm_model"],
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": build_user_content(keyword, hits, [])},
        ],
        temperature=0,
        max_tokens=2500,
    )
    return (resp.choices[0].message.content or "").strip()


CARD_GEN_PROMPT = """你是「药鉴」的卡片制作助手。把下面的知识笔记内容转成问答记忆卡片。

铁律：
1. 只依据笔记内容出题，不得编造、不得补充笔记中没有的知识；
2. 每张卡：正面=问题（简洁，指向一个知识点）；背面=答案（简短，保留引用编号 [n]）；
3. 输出 JSON 数组：[{{"q":"问题","a":"答案 [n]"}}]，不要任何其他文字；
4. 最多 {max_cards} 张，宁缺毋滥（笔记内容少就少出）。

笔记内容：
{content}"""

CARD_TEXT_PROMPT = """你是「药鉴」的卡片制作助手。用户选中了笔记中的一段文字，要为它做一张记忆卡片。

铁律：背面答案必须就是用户选中的文段（可微调格式），不得改写含义、不得编造；正面=一个指向该文段核心内容的问题。

输出 JSON：{{"q":"问题","a":"答案（含引用编号）"}}，不要任何其他文字。

选中文段：
{text}"""


def _parse_card_json(raw):
    import json as _json
    try:
        start, end = raw.find("["), raw.rfind("]")
        if start >= 0 and end > start:
            raw = raw[start:end + 1]
        return _json.loads(raw)
    except Exception:
        return []


def generate_cards(client, settings, content, max_cards=15):
    """整篇笔记 → 问答卡对列表 [{q, a}]（F5 一键生成模式）。"""
    prompt = CARD_GEN_PROMPT.format(max_cards=max_cards, content=content[:6000])
    resp = client.chat.completions.create(
        model=settings["llm_model"],
        messages=[
            {"role": "system", "content": "只输出 JSON 数组，不要任何其他文字。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_tokens=2000,
    )
    items = _parse_card_json((resp.choices[0].message.content or "").strip())
    return [
        {"q": str(it.get("q", "")).strip(), "a": str(it.get("a", "")).strip()}
        for it in items
        if isinstance(it, dict) and it.get("q") and it.get("a")
    ]


def generate_card_from_text(client, settings, text):
    """选中一段文字 → 1 张卡（答案=选中文段，F5 选段制卡模式）。"""
    resp = client.chat.completions.create(
        model=settings["llm_model"],
        messages=[
            {"role": "system", "content": "只输出 JSON，不要任何其他文字。"},
            {"role": "user", "content": CARD_TEXT_PROMPT.format(text=text[:3000])},
        ],
        temperature=0,
        max_tokens=600,
    )
    raw = (resp.choices[0].message.content or "").strip()
    import json as _json
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start:end + 1]
        it = _json.loads(raw)
    except Exception:
        return None
    if not it.get("q") or not it.get("a"):
        return None
    return {"q": str(it["q"]).strip(), "a": str(it["a"]).strip()}


def build_user_content(question, hits, history):
    """拼装用户消息：对话历史（仅助指代）+ 参考资料（编号）+ 问题。"""
    parts = []
    if history:
        lines = ["【对话历史】（仅用于理解「它」「该法」等指代，答案内容只能来自下方参考资料）"]
        for p in history:
            lines.append(f"问：{p['q']}")
            if p["a"]:
                lines.append(f"答：{p['a']}")
        parts.append("\n".join(lines))
    if hits:
        refs = []
        for i, h in enumerate(hits, 1):
            src = h.get("meta", {})
            page = src.get("page")
            tag = "｜".join(x for x in (src.get("kb", ""), src.get("category", ""), src.get("source", ""), f"第{page}页" if page else "") if x)
            refs.append(f"[{i}]（来源：{tag}）\n{h['text']}")
        parts.append("【参考资料】\n" + "\n\n".join(refs))
    else:
        parts.append("【参考资料】\n（空：本轮未检索到相关内容）")
    parts.append(f"【用户问题】\n{question}")
    return "\n\n".join(parts)


def stream_answer(client, settings, question, hits, history):
    """流式返回答案文本增量（generator of str）。"""
    messages = [
        {"role": "system", "content": load_system_prompt()},
        {"role": "user", "content": build_user_content(question, hits, history)},
    ]
    stream = client.chat.completions.create(
        model=settings["llm_model"],
        messages=messages,
        stream=True,
        temperature=settings.get("temperature", 0),
        max_tokens=1500,
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def extract_citations(answer, hits):
    """解析回答中的 [n]，按首次出现顺序返回引用列表（附原文供前端展示）。"""
    seen, out = set(), []
    for n in re.findall(r"\[(\d+)\]", answer):
        n = int(n)
        if 1 <= n <= len(hits) and n not in seen:
            seen.add(n)
            h = hits[n - 1]
            meta = h.get("meta", {})
            file = h.get("file", "")
            if file.endswith(".ocr.json"):
                file = file[: -len(".ocr.json")]  # sidecar 显示为原 PDF 名
            out.append(
                {
                    "n": n,
                    "text": h["text"],
                    "score": h["score"],
                    "file": file,
                    "kb_name": h.get("kb_name") or meta.get("kb", ""),
                    "source": meta.get("source", ""),
                    "category": meta.get("category", ""),
                    "page": meta.get("page", ""),
                }
            )
    return out


REFUSAL_TEXT = "资料中未找到相关内容。"

# F9：拒答附原因与建议（规则模板，不调模型——零命中保持零成本，与 F4 一致）
REFUSAL_FULL = (
    REFUSAL_TEXT + "所选知识库中没有与这个问题相关的资料。\n"
    "建议：①换一个关键词试试；②先在侧边栏新建知识库并导入相关课件/笔记；"
    "③如果资料里确实没有，我可以帮你生成一篇知识笔记（📝 知识笔记）。"
)


REWRITE_SYSTEM = (
    "你是追问改写助手。把用户的追问改写为独立完整的问题："
    "把「它」「该法」「第三种」等指代词替换为对话历史中提到的具体对象。"
    "只输出改写后的问题本身，不要任何解释、不要引号。"
)


def rewrite_question(client, settings, question, history):
    """多轮追问改写：把「它分几种方法？」改成「重金属检查法分几种方法？」，用于检索。
    改写失败时返回原问题（降级不阻塞问答）。"""
    if not history:
        return question
    hist_lines = []
    for p in history[-3:]:
        hist_lines.append(f"问：{p['q']}")
        if p["a"]:
            hist_lines.append(f"答：{p['a']}")
    try:
        resp = client.chat.completions.create(
            model=settings["llm_model"],
            messages=[
                {"role": "system", "content": REWRITE_SYSTEM},
                {"role": "user", "content": "\n".join(hist_lines) + f"\n\n追问：{question}"},
            ],
            temperature=0,
            max_tokens=120,
        )
        out = (resp.choices[0].message.content or "").strip()
        return out if out else question
    except Exception:
        return question
