"""
Mirror Node — 审计镜像导出器。

职责：
- 在 format 节点之后、END 之前执行
- 只写不读：将本轮状态写到磁盘文件，不返回任何业务字段
- 写入失败绝不中断 Graph

输出文件：
  storage/memory/{thread_id}_internal.json  — AI 结构化账本
  storage/logs/{thread_id}_chat.md          — 人类可读会话记录
"""

import json
import os
import time
import traceback
from state import AgentState

# ── 存储根目录 ──────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_MEMORY = os.path.join(PROJECT_ROOT, "storage", "memory")
STORAGE_LOGS = os.path.join(PROJECT_ROOT, "storage", "logs")


def _ensure_dirs():
    """惰性创建存储目录。"""
    os.makedirs(STORAGE_MEMORY, exist_ok=True)
    os.makedirs(STORAGE_LOGS, exist_ok=True)


def _resolve_thread_id(config: dict | None) -> str:
    """从 RunnableConfig 中提取 thread_id。"""
    if config and isinstance(config, dict):
        thread_id = config.get("configurable", {}).get("thread_id", "")
        if thread_id:
            return str(thread_id)
    return "default_session"


def _write_internal_audit(state: AgentState, thread_id: str):
    """镜像一：AI 结构化账本。"""
    payload = {
        "thread_id": thread_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "fact_ledger": state.get("fact_ledger", []),
        "long_focus_context": state.get("long_focus_context", ""),
        "metadata": state.get("metadata", {}),
        "_summary": {
            "intent": state.get("intent", ""),
            "expert_diagnosis": state.get("expert_diagnosis", ""),
        },
    }
    path = os.path.join(STORAGE_MEMORY, f"{thread_id}_internal.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _write_chat_log(state: AgentState, thread_id: str):
    """镜像二：人类会话记录。"""
    messages = state.get("messages", []) or []
    final_report = state.get("final_report", "") or ""

    lines = []
    last_is_human = False

    for msg in messages:
        role = getattr(msg, "type", "")
        content = str(getattr(msg, "content", "") or "")
        if role == "human":
            lines.append(f"用户：{content}\n\n")
            last_is_human = True
        elif role == "ai":
            lines.append(f"ai:{{{{ {content} }}}}\n\n")
            last_is_human = False
        # system 类型消息跳过

    # 若最后一条消息是 Human，追加本轮的 final_report 作为 AI 应答
    if last_is_human and final_report:
        lines.append(f"ai:{{{{ {final_report} }}}}\n\n")

    path = os.path.join(STORAGE_LOGS, f"{thread_id}_chat.md")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def run(state: AgentState, config: dict | None = None) -> dict:
    """只写不读：导出审计存档后返回空 dict，不覆写任何 state 字段。"""
    _start = time.time()
    try:
        _ensure_dirs()
        thread_id = _resolve_thread_id(config)

        _write_internal_audit(state, thread_id)
        _write_chat_log(state, thread_id)

        latency = round(time.time() - _start, 3)
        print(f"[Mirror] 审计写入完成: thread={thread_id} latency={latency}s")

    except Exception:
        # 副作用约束：磁盘写入失败绝不中断 Graph
        pass

    return {}
