"""
Reviewer Node — 修复代码 + 复杂度校验。

主权边界：
- 只基于 expert_diagnosis 和 standard_solution 给出修改方案
- 不重新诊断错误
- 输出 JSON 格式的修复建议和复杂度分析
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


SYSTEM_PROMPT = """你是一个 LeetCode 代码审查专家。基于错误诊断和标准解法模板，给出最小改动修复方案。

【约束】
系统已为你准备了参考资料（位于 standard_solution 字段）。你必须将其作为权威背景，将其核心逻辑吸收进你的讲解或代码中，严禁简单复读。
- 优先输出 Python 解法
- 最小改动：只修有问题的部分，不要重写用户代码
- 基于标准模板但不照搬模板

【输出格式】
严格 JSON，不要额外文字：
{
    "fix": "修正后的完整 Python 函数代码",
    "explanation": "一句话解释改了什么",
    "complexity": "原复杂度 vs 修改后复杂度",
    "confidence": 0.95,
    "internal_thought": "判断依据（用户代码的哪个具体问题让你给出这个修复）"
}"""


def run(state: AgentState) -> dict:
    """读 source_code + expert_diagnosis + standard_solution → 写 fix_suggestion + complexity_analysis"""
    _start = time.time()
    code = state.get("source_code", "")
    expert_diagnosis = state.get("expert_diagnosis", "")
    solution = state.get("standard_solution", "")

    if not code or not expert_diagnosis:
        return {
            "fix_suggestion": "缺少用户代码或诊断信息，无法生成修复方案。",
            "complexity_analysis": "",
            "metadata": {**(state.get("metadata") or {}), "reviewer": {"node_name": "reviewer", "confidence": None, "internal_thought": "缺少前置信息，跳过", "latency": round(time.time() - _start, 3)}},
        }

    user_prompt = f"""【用户代码】
    {code}

    【错误诊断】
    {expert_diagnosis}

    【标准解法参考】
    {solution}"""

    model = _get_model()
    resp = model.invoke([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ])
    latency = round(time.time() - _start, 3)

    import json
    raw = (resp.content or "").strip()
    try:
        # 去掉 ```json / ```python ... ``` 包裹
        cleaned = raw
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("\n", 1)[0] if cleaned.rstrip().endswith("```") else cleaned
        cleaned = cleaned.strip()
        parsed = json.loads(cleaned)
        code = parsed.get("fix", "")
        code = code.replace("\\n", "\n")
        explanation = parsed.get("explanation", "").replace("\\n", "\n")
        complexity = parsed.get("complexity", "")
        confidence = parsed.get("confidence", None)
        internal_thought = str(parsed.get("internal_thought", ""))
        formatted = f"```python\n{code}\n```"
        if explanation:
            formatted += f"\n\n{explanation}"
        return {
            "fix_suggestion": formatted,
            "complexity_analysis": complexity or "未知",
            "metadata": {**(state.get("metadata") or {}), "reviewer": {"node_name": "reviewer", "confidence": confidence if isinstance(confidence, (int, float)) and 0 <= confidence <= 1 else None, "internal_thought": internal_thought, "latency": latency}},
        }
    except Exception:
        return {
            "fix_suggestion": "【系统保护】大模型修复建议生成格式异常，请重试。",
            "complexity_analysis": "未知",
            "metadata": {**(state.get("metadata") or {}), "reviewer": {"node_name": "reviewer", "confidence": None, "internal_thought": "LLM 返回内容无法解析，触发降级", "latency": latency}},
        }
