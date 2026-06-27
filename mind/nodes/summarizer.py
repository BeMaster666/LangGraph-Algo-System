"""
Summarizer Node — 前置背景生成器（物理降级版）。

职责：
- 在 extractor 之后、fetcher 之前运行
- 遍历 fact_ledger 中累积的历史事实，用 Python 字符串拼接生成对话背景
- 将背景存入 state["long_focus_context"]，供 expert_diagnosis 做意图判定
- 不调 LLM，不修改 messages
"""

import time
from state import AgentState


def run(state: AgentState) -> dict:
    _start = time.time()
    ledger = state.get("fact_ledger", []) or []
    existing_meta = state.get("metadata", {}) or {}

    if not ledger:
        return {
            "long_focus_context": "",
            "metadata": {
                **existing_meta,
                "summarizer": {
                    "node_name": "summarizer",
                    "confidence": None,
                    "internal_thought": "fact_ledger 为空，跳过拼接",
                    "latency": round(time.time() - _start, 3),
                },
            },
        }

    # 纯字符串拼接：遍历每轮事实
    parts = []
    for i, entry in enumerate(ledger, start=1):
        line_parts = [f"[第{i}轮]"]
        num = entry.get("target_id", "") or ""
        desc = entry.get("current_query", "") or ""
        code = entry.get("source_code", "") or ""
        if num:
            line_parts.append(f"题号={num}")
        if desc:
            line_parts.append(f"描述={desc[:200]}")
        if code:
            line_parts.append(f"代码:\n{code[:300]}")
        parts.append(" ".join(line_parts))

    long_focus_context = "\n".join(parts)

    latency = round(time.time() - _start, 3)
    return {
        "long_focus_context": long_focus_context,
        "metadata": {
            **existing_meta,
            "summarizer": {
                "node_name": "summarizer",
                "confidence": None,
                "internal_thought": f"拼接 {len(ledger)} 轮事实，摘要 {len(long_focus_context)} 字符",
                "latency": latency,
            },
        },
    }
