"""
Diagnosis Node — 意图分类器（XML 标签驱动，纯正则剥离）。

职责：
- 仅判定用户意图（error / teach / generate）
- 输出 ≤100 字的核心诊断（错误原因 or 教学痛点）
- 不生成教学内容，不写代码，不提供完整解法

[TODO] 审阅场景：后续可拆出独立的 review intent。

变更记录：
- 抛弃 JSON 解析，改用 <intent>/<reason> XML 标签 + re.search 剥离
- 输入源改为 current_query + long_focus_context，不再读 error_message
- metadata 不再展开 state 全量，只写 diagnosis 专有字段
"""

import re
import time
from langchain_openai import ChatOpenAI
from state import AgentState
from config import MODEL, OPENAI_API_KEY, OPENAI_BASE_URL

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = ChatOpenAI(
            model=MODEL, api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL
        )
    return _model


SYSTEM_PROMPT = """你是意图分类器。仅判定用户意图，输出 XML 标签。

三种意图：
  error    - 用户有代码 + 报错，需要 debug
  teach    - 用户想学习、求思路引导，无报错
  generate - 用户直接要答案/解法，无报错

输出格式（严格以下格式，不要 JSON，不要额外文字）：
<intent>error或teach或generate</intent>
<reason>分类依据：一句话说明从用户输入中看到了哪些信号，导致这个分类（≤100字，不涉及代码级解法）</reason>
<sufficiency>0.0到1.0之间的浮点数</sufficiency>

规则：
- <intent> 必须是 error / teach / generate 之一
- <reason> 写你基于用户输入中的哪些信号做出了这个分类
  example: "用户提供了代码和报错信息" → intent=error
  example: "用户请求讲解思路"        → intent=teach
  example: "用户明确要求写代码"       → intent=generate
  example: "仅有题号无动作描述"       → sufficiency 应偏低
- <sufficiency> 代表"当前意图分类置信度"：范围[0.0,1.0]，表示你对自己分类结果的把握
- <reason> 严禁写代码级诊断、教学痛点或解法方向——那是专家的领域"""


def run(state: AgentState) -> dict:
    _start = time.time()
    code = state.get("source_code", "").strip()
    user_desc = state.get("current_query", "").strip()
    detail = state.get("problem_detail", "").strip()
    pid = state.get("target_id", "").strip()
    long_focus_context = state.get("long_focus_context", "").strip()

    # 使用 XML 标签组装 Prompt
    parts = []
    if long_focus_context:
        parts.append(f"<global_long_focus_context> {long_focus_context} </global_long_focus_context>")
    parts.append(f"<problem_info> {pid} {detail} </problem_info>")
    parts.append(
        "<current_input>\n"
        + (f"代码:\n{code}\n" if code else "")
        + (f"描述:\n{user_desc}\n" if user_desc else "")
        + "</current_input>"
    )

    user_prompt = "\n".join(parts)

    model = _get_model()
    resp = model.invoke(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
    )
    latency = round(time.time() - _start, 3)

    raw = (resp.content or "").strip()

    # 正则剥离 <intent>、<reason>、<sufficiency> 标签
    # re.search 返回 None 时直接赋兜底值，永不调用 .group(1) 避免 AttributeError
    intent_match = re.search(r"<intent>\s*(.*?)\s*</intent>", raw, re.DOTALL)
    reason_match = re.search(r"<reason>\s*(.*?)\s*</reason>", raw, re.DOTALL)
    sufficiency_match = re.search(r"<sufficiency>\s*(.*?)\s*</sufficiency>", raw, re.DOTALL)

    intent = (intent_match.group(1).strip().lower() if intent_match else "")
    if intent not in ("error", "teach", "generate"):
        intent = "generate"

    reason = (reason_match.group(1).strip() if reason_match else "")

    sufficiency_str = sufficiency_match.group(1).strip() if sufficiency_match and sufficiency_match.group(1).strip() else "0.5"
    try:
        sufficiency = float(sufficiency_str)
    except (ValueError, TypeError):
        sufficiency = 0.5
    sufficiency = max(0.0, min(1.0, sufficiency))

    # fallback 状态判断
    if not intent_match or not reason_match:
        status = "fallback"
    else:
        status = "success"

    return {
        "intent": intent,
        "expert_diagnosis": reason or "用户意图已捕获，详细原因待分析。",
        "sufficiency": sufficiency,
        "metadata": {
            "diagnosis": {
                "node_name": "diagnosis",
                "latency": latency,
                "status": status,
                "sufficiency": sufficiency,
            },
        },
    }
