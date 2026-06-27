"""
Fetcher Node — 将用户输入转换为 State 格式（I/O 防火墙版）。

查找策略（三优先级）：
  ① slug_map.json（本地精确，零网络）
  ② doocs/leetcode + LeetCode GraphQL（仅当前请求，超时 5s）
  ③ 纯题号降级

容错约束：
  - 所有 urllib 请求设 timeout=5
  - 全局异常拦截，15 秒内必有确定返回
  - 全部源失败时写入兜底声明，不崩 Graph

fetcher 只读映射，不写映射。（后续由 Sync Node 统一同步）
"""

import json
import os
import time
import urllib.request
import urllib.error
from state import AgentState

_SLUG_MAP = None
_SLUG_PATH = None

HTTP_TIMEOUT = 5  # 所有外部请求统一超时


def _map_path() -> str:
    global _SLUG_PATH
    if _SLUG_PATH is None:
        _SLUG_PATH = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "slug_map.json"
        )
    return _SLUG_PATH


def _load_map() -> dict:
    global _SLUG_MAP
    if _SLUG_MAP is not None:
        return _SLUG_MAP
    try:
        p = _map_path()
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                _SLUG_MAP = json.load(f)
        else:
            _SLUG_MAP = {}
    except Exception:
        _SLUG_MAP = {}
    return _SLUG_MAP


def _range_dir(pid: str) -> str:
    n = int(pid)
    start = (n // 100) * 100
    return f"{start:04d}-{start + 99:04d}"


def _doocs_slug(pid: str) -> str | None:
    """通过 doocs/leetcode GitHub API 查找题号对应的 slug（超时 5s）。"""
    try:
        url = f"https://api.github.com/repos/doocs/leetcode/contents/solution/{_range_dir(pid)}"
        req = urllib.request.Request(url, headers={"User-Agent": "lc-agent"})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            items = json.loads(r.read())
        prefix = f"{int(pid):04d}."
        for item in items:
            if item.get("type") == "dir" and item.get("name", "").startswith(prefix):
                return item["name"].split(".", 1)[1]
    except Exception:
        pass
    return None


def _leetcode_title(slug: str) -> str | None:
    """通过 LeetCode GraphQL 获取标题（超时 5s）。"""
    try:
        query = """query($s:String!){question(titleSlug:$s){questionId title}}"""
        data = json.dumps({"query": query, "variables": {"s": slug}}).encode()
        req = urllib.request.Request(
            "https://leetcode.com/graphql", data=data,
            headers={"Content-Type": "application/json", "User-Agent": "lc-agent"},
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            d = json.loads(r.read())
            title = d.get("data", {}).get("question", {}).get("title", "")
            return title if title else None
    except Exception:
        pass
    return None


def _fetch_external(pid: str) -> tuple[str, str]:
    """尝试外部来源查找，返回 (标题, 来源标签)。
       单一入口，两条网络调用串联，任一环节抛异常即整体失败。"""
    slug = _doocs_slug(pid)
    if slug:
        title = _leetcode_title(slug)
        if title:
            return title, "doocs+graphql"
    return "", ""


# ── 兜底文案 ──────────────────────────────────────────
FALLBACK_TEMPLATE = "【系统提示】网络查询超时，未能获取题目官方描述，将仅基于用户提供的代码和描述进行推演。"


# ── 主逻辑 ────────────────────────────────────────────

def run(state: AgentState) -> dict:
    """从 state 读 target_id → 查题目详情 → 写 problem_detail + metadata。"""
    _start = time.time()
    pid = state.get("target_id", "").strip()
    existing_meta = state.get("metadata", {}) or {}

    # 无题号 → 直接返回空
    if not pid:
        return {
            "problem_detail": "",
            "metadata": {
                **existing_meta,
                "fetcher": {
                    "node_name": "fetcher",
                    "confidence": None,
                    "internal_thought": "无题号，跳过抓取",
                    "latency": round(time.time() - _start, 3),
                    "source": "none",
                    "status": "skipped",
                },
            },
        }

    source = ""
    status = "success"

    try:
        slug_map = _load_map()

        # ① 本地映射（零网络）
        title = slug_map.get(pid, "")
        if title:
            source = "slug_map_local"
            detail = f"LeetCode {pid}: {title}"
            return _result(detail, source, status, _start, existing_meta)

        # ② 外部网络查找
        title, net_source = _fetch_external(pid)
        if title:
            source = net_source
            detail = f"LeetCode {pid}: {title}"
            return _result(detail, source, status, _start, existing_meta)

        # ③ 纯题号降级（仅返回无描述）
        source = "none"
        detail = f"LeetCode {pid}"
        return _result(detail, source, status, _start, existing_meta)

    except Exception:
        # 全局兜底：上面任何环节抛异常都不崩 Graph
        status = "timeout_fallback"
        return _result(FALLBACK_TEMPLATE, "none", status, _start, existing_meta)


def _result(detail: str, source: str, status: str, _start: float, existing_meta: dict) -> dict:
    """组装统一返回格式。"""
    latency = round(time.time() - _start, 3)
    return {
        "problem_detail": detail,
        "metadata": {
            **existing_meta,
            "fetcher": {
                "node_name": "fetcher",
                "confidence": None,
                "internal_thought": f"source={source} status={status} len={len(detail)}",
                "latency": latency,
                "source": source,
                "status": status,
            },
        },
    }
