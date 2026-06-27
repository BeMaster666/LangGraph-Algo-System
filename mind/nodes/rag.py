"""
RAG Node — 意图感知检索引擎。

主权边界：
- 从 state 提取 intent + expert_diagnosis，构建意图感知 Query
- 相似度阈值过滤：低于 0.7 时写入空字符串，不传递噪音
- 不关心知识引擎内部实现（ChromaDB / 切分器 / Embedding）
- 知识引擎未就绪时返回提示信息，不影响管线继续执行
"""

import time
from state import AgentState

# 引擎单例（避免每次调用重新初始化 ChromaDB）
_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        try:
            from knowledge_engine import KnowledgeEngine
            _engine = KnowledgeEngine()
        except Exception as e:
            print(f"[RAG] 知识引擎初始化失败: {e}")
            return None
    return _engine


# 意图 → Query 前缀映射
_INTENT_QUERY_PREFIX = {
    "teach": "算法原理和类比",
    "error": "标准实现和常见坑点",
    "generate": "最优解法",
}


def run(state: AgentState) -> dict:
    """读 intent + 原始材料 → 意图感知检索 → 写 standard_solution"""

    _start = time.time()
    intent = state.get("intent", "").strip().lower()
    existing_meta = state.get("metadata", {}) or {}

    raw_material = state.get("current_query", "") or ""
    code = state.get("source_code", "") or ""

    if not raw_material and not code:
        return {"standard_solution": "", "metadata": {**existing_meta, "rag": {"node_name": "rag", "confidence": None, "internal_thought": "无诊断信息，跳过检索", "latency": round(time.time() - _start, 3)}}}

    engine = _get_engine()
    if engine is None:
        return {"standard_solution": "[RAG] 知识引擎未就绪，跳过检索。", "metadata": {**existing_meta, "rag": {"node_name": "rag", "confidence": None, "internal_thought": "知识引擎未就绪", "latency": round(time.time() - _start, 3)}}}

    # 根据 intent 和原始材料构建感知 Query（不再依赖 expert_diagnosis 语义）
    prefix = _INTENT_QUERY_PREFIX.get(intent, "")
    search_content = code if code else raw_material
    query = f"{prefix} {search_content[:300]}" if prefix else search_content[:300]

    result = engine.search(query=query, top_k=2, min_similarity=0.6, intent=intent)
    latency = round(time.time() - _start, 3)
    has_result = bool(result and result.strip())

    return {
        "standard_solution": result,
        "metadata": {
            **existing_meta,
            "rag": {
                "node_name": "rag",
                "confidence": None,
                "internal_thought": f"intent={intent} query_prefix={prefix or '无'} 命中={'有' if has_result else '无(低于阈值)'}",
                "latency": latency,
            },
        },
    }
