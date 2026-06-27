"""
Tutor Node — 苏格拉底式教学专家。

接收 intent=teach 时触发，基于 expert_diagnosis 的核心痛点生成结构化教学。
调 LLM，输出 Markdown 格式的教学内容。
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


SYSTEM_PROMPT = """你是一个苏格拉底式算法导师。

输入：一条诊断信息，指出用户在某个算法概念上的核心痛点。
任务：以启发式教学生成结构化 Markdown 教学内容。
系统已为你准备了参考资料（位于 standard_solution 字段）。你必须将其作为权威背景，将其核心逻辑吸收进你的讲解或代码中，严禁简单复读。

教学框架：
1. **痛点定位** — 一句话点明用户当前的理解误区或盲区
2. **核心概念** — 用类比或图示解释关键原理（不要直接给代码）
3. **引导思考** — 提出 1~2 个启发式问题，引导用户自己推导出解法
4. **参考实现** — 给出 Python 代码（附关键行注释），作为对照
5. **复杂度分析** — 一句话说明时间/空间复杂度

风格要求：
- 用「问题 → 思考 → 答案」的节奏推进
- 适当使用 Markdown 块引用、列表、分隔线
- 语气耐心、鼓励，像一对一辅导
- 不评价用户代码好坏，只引导正确思路"""


def run(state: AgentState) -> dict:
    _start = time.time()
    expert_diagnosis = state.get("expert_diagnosis", "")
    detail = state.get("problem_detail", "")
    code = state.get("source_code", "")
    pid = state.get("target_id", "")

    if not expert_diagnosis:
        return {"tutor_output": "暂无诊断信息，无法生成教学内容。", "metadata": {**(state.get("metadata") or {}), "tutor": {"node_name": "tutor", "confidence": None, "internal_thought": "无诊断信息", "latency": round(time.time() - _start, 3)}}}

    parts = [f"【诊断痛点】{expert_diagnosis}"]
    if pid:
        parts.append(f"【题号】{pid}")
    if detail:
        parts.append(f"【题目】{detail}")
    if code:
        parts.append(f"【用户代码】\n{code}")

    user_prompt = "基于以下诊断信息，生成苏格拉底式教学：\n" + "\n".join(parts)

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
            output = "## 教学引导\n\n基于当前诊断，请尝试重新审视你的解题思路。"
        # 基于输出质量推断 confidence
        inferred_confidence = min(1.0, len(output) / 500) if output else 0.0
        return {
            "tutor_output": output,
            "metadata": {**(state.get("metadata") or {}), "tutor": {"node_name": "tutor", "confidence": round(inferred_confidence, 2), "internal_thought": f"生成教学共 {len(output)} 字符", "latency": latency}},
        }
    except Exception:
        latency = round(time.time() - _start, 3)
        return {
            "tutor_output": "【系统保护】教学生成异常，请稍后重试或简化你的问题。",
            "metadata": {**(state.get("metadata") or {}), "tutor": {"node_name": "tutor", "confidence": None, "internal_thought": "LLM 调用异常，触发降级", "latency": latency}},
        }
