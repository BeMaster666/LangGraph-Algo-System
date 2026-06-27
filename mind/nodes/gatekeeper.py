"""
Gatekeeper Node — 第一级检查：sufficiency + 基础材料存在性。
不跨轮传话，不越权代庖。
"""

import time
from langchain_openai import ChatOpenAI
from state import AgentState
from config import MODEL, OPENAI_API_KEY, OPENAI_BASE_URL
import os

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = ChatOpenAI(
            model=MODEL, api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL
        )
    return _model


SYSTEM_PROMPT = """按 sufficiency 和角色材料标准决策，决定放行或追问。

输入：
- intent: error / teach / generate
- sufficiency: 0.0 ~ 1.0
- source_code: 有 / 无
- current_query: 有 / 无
- problem_detail: 有 / 无
- error_message: 有 / 无

决策规则：

【sufficiency < 0.5】
→ 直接 ask，不检查材料。信息太少，无法判断需要什么。

【sufficiency ≥ 0.5】
→ 按角色检查材料是否足够支撑执行：

  error:
    必要: source_code 有实质代码（不是空串/仅注释）
    或:   error_message 有具体报错内容
    → 足够 → proceed
    → 不足 → ask

  teach:
    必要: current_query 表达了明确的学习请求
    注意: 仅有题号（如"394"）不是明确的学习请求
    → 足够 → proceed
    → 不足 → ask

  generate:
    必要: current_query 表达了指向具体题目的动作诉求
    （如 "做 394 题"、"实现快速排序"、"求 206 题代码" 等）
    注意: 仅有动作诉求词但无具体指向（如 "帮我做道题"、"写代码"、"求代码"），判定为不足
    注意: 仅有题号（如"394"）或仅有单个词，判定为不足
    → 足够 → proceed
    → 不足 → ask

【sufficiency > 0.8】
→ 此情况已被上游路由拦截，你不会收到。

输出 JSON（严格，不要额外文字）：
{"verdict": "proceed", "final_report": "", "reason": "材料齐全，放行"}
{"verdict": "ask", "final_report": "具体的追问文本，指出缺少什么", "reason": "缺少代码且报错信息为空"}

输出示例：
"帮我做道题"且没有题号或代码 →
  {"verdict": "ask", "final_report": "你想做哪道题？请告诉我题号或贴一下具体问题", "reason": "有动作诉求但无具体指向"}
"394 题怎么做" →
  {"verdict": "proceed", "final_report": "", "reason": "有题号有明确学习请求，放行"}
"""


def run(state: AgentState) -> dict:
    _start = time.time()
    intent = state.get("intent", "")
    expert_diagnosis = state.get("expert_diagnosis", "")
    sufficiency = state.get("sufficiency", 0.5)
    code = state.get("source_code", "")
    query = state.get("current_query", "")
    detail = state.get("problem_detail", "")

    existing_meta = state.get("metadata", {}) or {}

    user_prompt = (
        f"intent: {intent}\n"
        f"expert_diagnosis: {expert_diagnosis}\n"
        f"sufficiency: {sufficiency}\n"
        f"source_code: {'有' if code else '无'}\n"
        f"current_query: {query[:200] if query else '无'}\n"
        f"problem_detail: {'有' if detail else '无'}"
    )

    import json

    try:
        model = _get_model()
        resp = model.invoke([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ])
        raw = (resp.content or "").strip()
        # 清理可能的 ```json 包裹
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("\n", 1)[0] if raw.rstrip().endswith("```") else raw
        parsed = json.loads(raw)
        verdict = str(parsed.get("verdict", "proceed")).strip().lower()
        if verdict not in ("proceed", "ask"):
            verdict = "proceed"
        ask_text = str(parsed.get("final_report", "")).strip()
        reason = str(parsed.get("reason", "")).strip()
        status = "success"
    except Exception:
        # 异常时保守放行，不阻塞系统
        verdict = "proceed"
        ask_text = ""
        reason = ""
        status = "fallback"

    latency = round(time.time() - _start, 3)

    # Debug 模式检测（与 format.py 一致）
    meta = state.get("metadata", {}) or {}
    is_debug = (
        meta.get("debug") is True
        or os.environ.get("FRAME_DEBUG", "").lower() in ("1", "true", "yes")
    )

    result = {
        "gatekeeper_verdict": verdict,
        "metadata": {
            **existing_meta,
            "gatekeeper": {
                "node_name": "gatekeeper",
                "latency": latency,
                "status": status,
                "verdict": verdict,
                "passed_check": verdict == "proceed",
                "ask_reason": reason if verdict == "ask" and is_debug else None,
            },
        },
    }

    if verdict == "ask" and ask_text:
        result["final_report"] = ask_text

    return result
