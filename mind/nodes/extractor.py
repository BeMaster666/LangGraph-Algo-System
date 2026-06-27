"""
Extractor Node — 前台提取器（增强版）。

职责：
- START 后第一个节点
- 从用户当前输入和对话历史中提取 target_id, source_code, error_message, current_query
- 如果当前输入没写题号，从历史消息中继承
- 正则优先（快路径），正则遗漏时由 LLM 互补
- 后置物理校验：数字检查、代码块清洗
- 向 metadata 写入提取状态
"""

import json
import re
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


# ──────────────────────────────────────────────
#  Phase 1: 正则快路径
# ──────────────────────────────────────────────

def _find_code_blocks(text: str) -> str:
    """提取 ```...``` 包裹的代码块，优先取最长块。"""
    blocks = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    if blocks:
        return max(blocks, key=len).strip()
    indented = re.findall(r"(?:^[ \t]{4,}.*\n?)+", text, re.MULTILINE)
    if indented:
        return max(indented, key=len).strip()
    return ""


def _find_number(text: str) -> str:
    """提取题号：支持 '207题'、'第207题'、'LeetCode 207'、'207' 等格式。"""
    m = re.search(r"[第#]?\s*(\d{1,4})\s*[题号]", text)
    if m:
        return m.group(1)
    m = re.search(r"(?:LeetCode|lc|leet)\s*[#:]?\s*(\d{1,4})", text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"(?:^|\s)(\d{1,4})(?:\s|$|[.。，,\n])", text)
    if m:
        return m.group(1)
    return ""


def _find_error(text: str) -> str:
    """提取报错信息。"""
    patterns = [
        r"(?:报错|错误|error|exception|traceback)[：:\s]*(.*?)(?:\n\n|$)",
        r"(?:Traceback|Error|Exception).*?(?:\n(?:  .*)?)*",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if m:
            return m.group(0).strip()
    return ""


def _inherit_number(state: AgentState) -> str:
    """从历史 messages 中继承最后出现的题号。"""
    for msg in reversed(state.get("messages", []) or []):
        content = getattr(msg, "content", "") or ""
        n = _find_number(str(content))
        if n:
            return n
    return ""


# ──────────────────────────────────────────────
#  Phase 2: LLM 互补提取
# ──────────────────────────────────────────────

EXTRACT_PROMPT = """你是一个结构化信息提取器。从用户输入中提取以下三个字段，严格遵循规则。

【提取字段】
1. target_id: 题号。纯数字字符串（如 "207"），未找到时返回 ""。严禁返回"用户未提供"等汉字。
2. source_code: 代码。只返回代码本身，不要包含```包裹，不要包含自然语言解释、评价、或任何中文/英文注释说明。未找到时返回 ""。
3. error_message: 报错信息。只返回报错原文，未找到时返回 ""。

【输出格式】
严格 JSON，无额外文字：
{"target_id":"","source_code":"","error_message":""}"""


def _llm_extract(text: str) -> dict:
    """调用 LLM 提取字段，返回 dict。"""
    try:
        model = _get_model()
        resp = model.invoke([
            {"role": "system", "content": EXTRACT_PROMPT},
            {"role": "user", "content": f"从以下内容中提取信息：\n\n{text[:2000]}"},
        ])
        raw = (resp.content or "").strip()
        # 清理 json 包裹
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("\n", 1)[0] if raw.rstrip().endswith("```") else raw
        return json.loads(raw)
    except Exception:
        return {}


# ──────────────────────────────────────────────
#  Phase 3: 后置物理校验
# ──────────────────────────────────────────────

def _validate_number(num: str) -> str:
    """强制数字校验：非纯数字 → ""。"""
    if num and num.strip().isdigit():
        return num.strip()
    return ""


def _clean_code(code: str) -> str:
    """清洗 Markdown 代码块包裹。"""
    code = code.strip()
    if code.startswith("```"):
        # 去掉开头的 ``` 和语言标识
        code = re.sub(r"^```\w*\n?", "", code)
        # 去掉结尾的 ```
        code = re.sub(r"\n?```$", "", code)
    return code.strip()


def _build_description(raw: str, code: str, error: str) -> str:
    """从原始输入中去掉代码块、题号、报错后得到纯描述。"""
    desc = raw
    if code:
        desc = desc.replace(code, "")
    desc = re.sub(r"```.*?```", "", desc, flags=re.DOTALL)
    desc = re.sub(r"^\s*\d{1,4}\s*[题号.。，,\s]*", "", desc)
    if error:
        desc = desc.replace(error, "")
    return desc.strip()


# ──────────────────────────────────────────────
#  Phase 4: 主流程
# ──────────────────────────────────────────────

def run(state: AgentState) -> dict:
    _start = time.time()
    messages = state.get("messages", []) or []

    # 取最新一条用户消息作为当前输入
    current_input = ""
    for msg in reversed(messages):
        if getattr(msg, "type", "") == "human":
            current_input = str(getattr(msg, "content", "") or "")
            break

    if not current_input:
        return {
            "metadata": {
                **(state.get("metadata") or {}),
                "extractor": {
                    "node_name": "extractor",
                    "confidence": None,
                    "internal_thought": "无用户输入",
                    "latency": round(time.time() - _start, 3),
                    "has_code": False,
                    "has_id": False,
                    "extraction_method": "none",
                },
            },
        }

    # ── Step 1: 正则快路径 ──
    re_number = _find_number(current_input)
    re_code = _find_code_blocks(current_input)
    re_error = _find_error(current_input)

    # ── Step 2: 决定是否需要 LLM ──
    # 豁免：简短追问（≤15 字）或纯疑问句，不调 LLM
    is_short_followup = len(current_input) <= 15 or bool(re.match(r"^(为什么|怎么|能不能|那|然后|继续|还有|那)", current_input))
    needs_llm = False
    if not is_short_followup:
        has_code_signal = bool(re.findall(r"(?:def |class |import |#|```|function|var |let |const |int |str |print)", current_input, re.IGNORECASE))
        needs_llm = (not re_code and has_code_signal) or (not re_number and not re_code and len(current_input) > 30)

    llm_number = ""
    llm_code = ""
    llm_error = ""
    method = "regex"

    if needs_llm or (not re_number and not re_code and current_input):
        method = "llm"
        llm_result = _llm_extract(current_input)
        if llm_result:
            llm_number = llm_result.get("target_id", "")
            llm_code = llm_result.get("source_code", "")
            llm_error = llm_result.get("error_message", "")
            if re_number == "" and llm_number:
                method = "regex+llm"

    # 合并：正则优先，LLM 补充
    final_number = _validate_number(re_number or llm_number)
    final_code = _clean_code(re_code or llm_code)
    final_error = (re_error or llm_error).strip()

    # 如果 LLM 也未找到 code，但 re_code 有值，就保留 re_code
    if not final_code and re_code:
        final_code = _clean_code(re_code)

    # ── Step 3: 题号继承 ──
    if not final_number:
        final_number = _validate_number(_inherit_number(state))

    # ── Step 4: 构建描述 ──
    current_query = _build_description(current_input, final_code, final_error) or current_input[:500]

    latency = round(time.time() - _start, 3)

    return {
        "target_id": final_number,
        "source_code": final_code,
        "error_message": final_error,
        "current_query": current_query,
        "fact_ledger": [{
            "target_id": final_number,
            "current_query": current_query,
            "source_code": final_code,
        }],
        "metadata": {
            **(state.get("metadata") or {}),
            "extractor": {
                "node_name": "extractor",
                "confidence": None,
                "internal_thought": f"题号={final_number or '(继承)'} 代码={'有' if final_code else '无'} 报错={'有' if final_error else '无'} 方法={method}",
                "latency": latency,
                "has_code": bool(final_code),
                "has_id": bool(final_number),
                "extraction_method": method,
            },
        },
    }
