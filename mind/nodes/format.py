"""
Format Node — 双模板引擎：组装 Markdown 报告 + 调试追踪。

按 intent 选择模板：error / teach / generate。
若检测到 debug 信号，在报告末尾追加 `## [DEVELOPER TRACE]` 区块。
"""

import json
import os
import re
from state import AgentState


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&[a-z]+;", "", text)
    return text


def _safe_gbk(text: str) -> str:
    return text.encode("gbk", errors="replace").decode("gbk")


def _safe(val: str, default: str = "（无）") -> str:
    return val if val and val.strip() else default


def _check_health(state: AgentState) -> dict:
    """L3 Validation — 及格线检查。"""
    health = {}
    intent = state.get("intent", "")

    if intent == "error":
        fix = state.get("fix_suggestion", "")
        # error 路径必须有代码块
        if "```" not in fix:
            health["health"] = "FAIL"
            health["health_reason"] = "error 路径缺少代码块，fix_suggestion 可能为空或格式异常"
        else:
            health["health"] = "PASS"

    elif intent == "teach":
        tutor = state.get("tutor_output", "")
        if len(tutor) < 100:
            health["health"] = "WARNING"
            health["health_reason"] = f"teach 输出仅 {len(tutor)} 字，可能内容不足"
        else:
            health["health"] = "PASS"

    elif intent == "generate":
        gen = state.get("generator_output", "")
        if not gen or "```" not in gen:
            health["health"] = "WARNING"
            health["health_reason"] = "generate 输出缺少代码块"
        else:
            health["health"] = "PASS"

    else:
        health["health"] = "UNKNOWN"

    return health


def _build_trace_block(full_meta: dict) -> str:
    """构建调试追踪区块。"""
    # 移除 debug 控制字段（不污染追踪输出）
    meta_copy = {k: v for k, v in full_meta.items() if k != "debug"}
    trace_lines = ["\n---\n## [DEVELOPER TRACE]\n"]
    trace_lines.append("```json\n")
    trace_lines.append(json.dumps(meta_copy, ensure_ascii=False, indent=2))
    trace_lines.append("\n```\n")
    return "".join(trace_lines)


def run(state: AgentState) -> dict:
    intent = state.get("intent", "error")
    metadata = state.get("metadata", {}) or {}
    is_debug = (
        metadata.get("debug") is True
        or os.environ.get("FRAME_DEBUG", "").lower() in ("1", "true", "yes")
    )

    lines = []

    if intent == "error":
        lines.append("# 错误诊断报告\n")
        lines.append(f"- **题号**: {_safe(state.get('target_id', ''))}\n")

        detail = state.get("problem_detail", "")
        if detail:
            lines.append("## 题目\n" + _safe_gbk(_strip_html(detail)) + "\n")

        code = state.get("source_code", "")
        if code:
            lines.append("## 用户代码\n```python\n" + code + "\n```\n")

        error = state.get("error_message", "")
        if error:
            lines.append("## 报错信息\n```\n" + error + "\n```\n")

        diag = state.get("expert_diagnosis", "")
        if diag:
            lines.append("## 诊断\n" + _safe_gbk(_strip_html(diag)) + "\n")

        sol = state.get("standard_solution", "")
        if sol:
            lines.append("## 参考解法\n" + _safe_gbk(_strip_html(sol)) + "\n")

        fix = state.get("fix_suggestion", "")
        if fix:
            lines.append("## 修复建议\n" + _safe_gbk(fix) + "\n")

        comp = state.get("complexity_analysis", "")
        if comp:
            lines.append("## 复杂度\n" + _safe_gbk(comp) + "\n")

    elif intent == "teach":
        lines.append("# 分步教学\n")
        detail = state.get("problem_detail", "")
        if detail:
            lines.append("## 题目\n" + _safe_gbk(_strip_html(detail)) + "\n")

        diag = state.get("expert_diagnosis", "")
        if diag:
            lines.append("## 思路\n" + _safe_gbk(_strip_html(diag)) + "\n")

        tutor = state.get("tutor_output", "")
        if tutor:
            lines.append(tutor + "\n")

    elif intent == "generate":
        lines.append("# 解法\n")
        detail = state.get("problem_detail", "")
        if detail:
            lines.append("## 题目\n" + _safe_gbk(_strip_html(detail)) + "\n")

        diag = state.get("expert_diagnosis", "")
        if diag:
            lines.append("## 思路\n" + _safe_gbk(_strip_html(diag)) + "\n")

        gen = state.get("generator_output", "")
        if gen:
            lines.append(gen + "\n")

    # L3 Validation — 及格线检查
    health = _check_health(state)

    final_report = "\n".join(lines)

    # Debug 模式追加追踪区块
    full_meta = {**(state.get("metadata") or {}), "format": health}
    if is_debug:
        final_report += _build_trace_block(full_meta)

    return {"final_report": final_report, "metadata": full_meta}
