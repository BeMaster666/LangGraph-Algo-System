"""
图拓扑 — 条件路由 + 前置 RAG + Gatekeeper 决策层。

架构：
  START → extractor → summarizer → fetcher → diagnosis → (sufficiency > 0.8 Flash 快路径)
    ├─ > 0.8 → rag → (intent 路由)
    └─ ≤ 0.8 → gatekeeper → (verdict 判断)
        ├─ ask → mirror → END
        └─ proceed → rag → (intent 路由)
           ├─ error    → reviewer → format → mirror → END
           ├─ teach    → tutor → format → mirror → END
           └─ generate → generator → format → mirror → END

RAG 在所有生成节点之前运行，确保 standard_solution 已被填充。
"""

import os
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from state import AgentState
from nodes.extractor import run as extractor
from nodes.summarizer import run as summarizer
from nodes.fetcher import run as fetcher
from nodes.diagnosis import run as diagnosis
from nodes.gatekeeper import run as gatekeeper
from nodes.rag import run as rag
from nodes.reviewer import run as reviewer
from nodes.tutor import run as tutor
from nodes.generator import run as generator
from nodes.format import run as format
from nodes.mirror import run as mirror
from config import REDIS_URL


def _create_checkpointer():
    redis_url = os.environ.get("REDIS_URL", "")
    if redis_url:
        try:
            from langgraph.checkpoint.redis import RedisSaver
            saver = RedisSaver(redis_url=redis_url)
            host = redis_url.split('@')[-1] if '@' in redis_url else 'local'
            print(f"[Checkpointer] RedisSaver ← {host}")
            return saver
        except Exception as e:
            print(f"[Checkpointer] Redis 初始化失败: {e}，降级到 MemorySaver")
    saver = MemorySaver()
    print("[Checkpointer] MemorySaver")
    return saver


def _route_after_diagnosis(state: AgentState) -> str:
    """sufficiency > 0.8 快路径直通 rag；否则走 gatekeeper 审核。"""
    sufficiency = state.get("sufficiency", 0.0)
    if sufficiency > 0.8:
        return state.get("intent", "generate")
    return "gatekeeper"


def _route_after_gatekeeper(state: AgentState) -> str:
    """gatekeeper 的 verdict 为 ask 时走 mirror；否则按 intent 走 rag。"""
    verdict = state.get("gatekeeper_verdict", "proceed")
    if verdict == "ask":
        return "mirror"
    return state.get("intent", "generate")


def _route_after_rag(state: AgentState) -> str:
    """原有的 intent 路由，不变。"""
    return state.get("intent", "generate")


def build_app(checkpointer=None):
    builder = StateGraph(AgentState)

    builder.add_node("extractor", extractor)
    builder.add_node("summarizer", summarizer)
    builder.add_node("fetcher", fetcher)
    builder.add_node("diagnosis", diagnosis)
    builder.add_node("gatekeeper", gatekeeper)
    builder.add_node("rag", rag)
    builder.add_node("reviewer", reviewer)
    builder.add_node("tutor", tutor)
    builder.add_node("generator", generator)
    builder.add_node("format", format)
    builder.add_node("mirror", mirror)

    # 前置链路
    builder.add_edge(START, "extractor")
    builder.add_edge("extractor", "summarizer")
    builder.add_edge("summarizer", "fetcher")
    builder.add_edge("fetcher", "diagnosis")

    # diagnosis → 条件路由：sufficiency > 0.8 快路径 → rag；否则 → gatekeeper
    builder.add_conditional_edges(
        "diagnosis", _route_after_diagnosis,
        {"gatekeeper": "gatekeeper", "error": "rag", "teach": "rag", "generate": "rag"},
    )

    # gatekeeper → 条件路由：ask → mirror；proceed → rag
    builder.add_conditional_edges(
        "gatekeeper", _route_after_gatekeeper,
        {"mirror": "mirror", "error": "rag", "teach": "rag", "generate": "rag"},
    )

    # rag → 条件路由（基于 intent 分流到具体生成节点）
    builder.add_conditional_edges(
        "rag", _route_after_rag,
        {"error": "reviewer", "teach": "tutor", "generate": "generator"},
    )

    # 三条路径汇聚到 format → mirror → END
    builder.add_edge("reviewer", "format")
    builder.add_edge("tutor", "format")
    builder.add_edge("generator", "format")
    builder.add_edge("format", "mirror")
    builder.add_edge("mirror", END)

    if checkpointer is None:
        checkpointer = _create_checkpointer()

    return builder.compile(checkpointer=checkpointer)
