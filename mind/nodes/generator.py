"""
Generator Node — 编码专家引擎。

接收 intent=generate 时触发，基于 expert_diagnosis 的解题思路生成最优代码。
调 LLM，输出 Python 代码 + 精简注释。
"""

import time
from langchain_openai import ChatOpenAI
from state import AgentState
from config import MODEL, OPENAI_API_KEY, OPENAI_BASE_URL

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = ChatOpenAI(model=MODEL, api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    return _model


SYSTEM_PROMPT = """你是一个高效的代码生成引擎。

输入：一道算法题的解题思路（核心解法方向）。
任务：生成最优 Python 代码，附带精简注释。

约束：
- 输出完整可运行的 Python 函数，包含 from typing import List 等必要导入
- 在关键步骤写行内注释（# 解释），不要大段文档字符串
- 优先时间最优，空间次优
- 不展开讲解，不写教学文案，代码即交付物
- 如果题目有经典解法（DP / 双指针 / 回溯等），优先使用

输出格式（严格 Markdown 代码块）：
```python
def solution(...):
    # 注释
    ...
```"""


def run(state: AgentState) -> dict:
    _start = time.time()
    expert_diagnosis = state.get("expert_diagnosis", "")
    detail = state.get("problem_detail", "")
    pid = state.get("target_id", "")

    if not expert_diagnosis:
        return {"generator_output": "暂无诊断信息，无法生成代码。", "metadata": {**(state.get("metadata") or {}), "generator": {"node_name": "generator", "confidence": None, "internal_thought": "无诊断信息", "latency": round(time.time() - _start, 3)}}}

    parts = [f"【解题方向】{expert_diagnosis}"]
    if pid:
        parts.append(f"【题号】{pid}")
    if detail:
        parts.append(f"【题目】{detail}")

    user_prompt = "根据以下解题方向生成代码：\n" + "\n".join(parts)

    import json
    try:
        model = _get_model()
        resp = model.invoke([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ])
        latency = round(time.time() - _start, 3)
        output = (resp.content or "").strip()
        if not output:
            output = "```python\ndef solution():\n    pass\n```"
        inferred_confidence = min(1.0, len(output) / 300) if output else 0.0
        return {
            "generator_output": output,
            "metadata": {**(state.get("metadata") or {}), "generator": {"node_name": "generator", "confidence": round(inferred_confidence, 2), "internal_thought": f"生成代码共 {len(output)} 字符", "latency": latency}},
        }
    except Exception:
        latency = round(time.time() - _start, 3)
        return {
            "generator_output": "【系统保护】代码生成异常，请稍后重试。",
            "metadata": {**(state.get("metadata") or {}), "generator": {"node_name": "generator", "confidence": None, "internal_thought": "LLM 调用异常，触发降级", "latency": latency}},
        }
