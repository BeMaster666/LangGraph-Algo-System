"""
交互式终端 — 多轮对话，带记忆折叠 + Redis 持久化的算法助手。

用法：
    python chat.py                            # 用户模式（MemorySaver）
    REDIS_URL=redis://localhost:6379 python chat.py   # Redis 持久化
    python chat.py --debug                    # 显示节点日志 + 追踪块

输入：
  Enter        换行
  Alt+Enter    提交（或 Esc 松开后按 Enter）
  Ctrl+C       退出
  直接粘贴    支持任意多行代码
"""

import sys
import os
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from langchain_core.messages import HumanMessage, AIMessage
from graph import build_app
from state import AgentState

DEBUG = "--debug" in sys.argv

# Debug 模式：设置环境变量让 format.py 追加追踪块
if DEBUG:
    os.environ["FRAME_DEBUG"] = "1"

# build_app 自动根据 REDIS_URL 选择 checkpointer
app = build_app()
thread = {"configurable": {"thread_id": "1"}}

# 初始 state（空字段，由 extractor 逐轮填充）
state = AgentState(
    messages=[],
    target_id="",
    source_code="",
    error_message="",
    current_query="",
    problem_detail="",
    default_template="",
    expert_diagnosis="",
    long_focus_context="",
    intent="",
    standard_solution="",
    fix_suggestion="",
    complexity_analysis="",
    final_report="",
    tutor_output="",
    generator_output="",
    metadata={},
)

# ── prompt_toolkit 键绑定 ────────────────────────────
bindings = KeyBindings()


@bindings.add("escape", "enter")
def _(event):
    """Alt+Enter 或 Esc+Enter 提交多行输入"""
    event.current_buffer.validate_and_handle()


session = PromptSession(
    key_bindings=bindings,
    multiline=True,
    prompt_continuation="... ",
)

print("输入你的算法问题（Alt+Enter 提交，Ctrl+C 退出）\n")

while True:
    try:
        user_input = session.prompt(">>> ")
    except KeyboardInterrupt:
        break

    if not user_input:
        continue
    if user_input.strip().lower() in ("exit", "quit"):
        break

    # 追加用户消息到对话历史
    state["messages"] = list(state.get("messages", []) or []) + [
        HumanMessage(content=user_input)
    ]

    for chunk in app.stream(state, thread):
        for name, out in chunk.items():
            if name == "__end__":
                continue
            # Debug 日志
            if DEBUG:
                if out:
                    for k, v in out.items():
                        if not v:
                            continue
                        if k == "metadata" and isinstance(v, dict):
                            self_meta = v.get(name, {})
                            print(f"[{name}] metadata = {self_meta}")
                        else:
                            print(f"[{name}] {k} = {str(v)[:160]}")
                # 报告输出（format 的最终报告 或 gatekeeper 的追问）
                if out and out.get("final_report") and name in ("format", "gatekeeper"):
                    print(f"\n{out['final_report']}")

    # 把本轮报告追加到对话历史
    final_report = state.get("final_report", "") or ""
    if final_report:
        state["messages"].append(AIMessage(content=final_report))
