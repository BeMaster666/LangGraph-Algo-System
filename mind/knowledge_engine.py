"""
知识引擎 — 系统公共检索引擎，不关心具体的业务 State。

职责隔离：
- 这是一个基础设施模块，不是 LangGraph 节点
- 不导入 state.py，不依赖 AgentState
- 只做三件事：初始化 ChromaDB、导入笔记、向量检索

特色：
- 手写 Markdown 切分器，绝对禁止在代码块中间切断
- 元数据增强：入库时自动标注 problem_id / algorithm_type / difficulty
- 检索时支持题号硬过滤 + 双重距离阈值（0.6）
"""

import os
import re

# ── ChromaDB 持久化路径 ─────────────────────────────────
_ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_ENGINE_DIR, "knowledge_db")
MANIFEST_PATH = os.path.join(_ENGINE_DIR, "ALGO_MANIFEST.json")
BOOKS_DIR = os.path.join(_ENGINE_DIR, "books")
_INDEX_READ_MAX = 5000  # 硬索引读取每个文件的字符上限

# ── 算法类型关键词映射 ──────────────────────────────────
_ALGO_KEYWORDS = {
    "DP": ["动态规划", "dp", "递推", "状态转移", "背包", "knapsack", "子序列", "子数组", "最长公共", "编辑距离"],
    "Sort": ["排序", "sort", "快速排序", "归并排序", "冒泡排序", "选择排序", "插入排序", "堆排序"],
    "Tree": ["树", "tree", "二叉树", "bst", "avl", "遍历", "前序", "中序", "后序", "层序", "递归遍历"],
    "Graph": ["图", "graph", "dfs", "bfs", "拓扑", "拓扑排序", "邻接", "并查集", "union find"],
    "Backtracking": ["回溯", "backtrack", "全排列", "组合", "子集", "permu", "n皇后", "数独"],
    "Binary Search": ["二分", "binary search", "二分查找", "二分搜索"],
    "Sliding Window": ["滑动窗口", "sliding window", "滑窗"],
    "Two Pointers": ["双指针", "two pointers", "快慢指针", "左右指针"],
    "Greedy": ["贪心", "greedy", "最优", "局部最优"],
    "Hash Table": ["哈希", "hash", "散列", "map", "set"],
    "Linked List": ["链表", "linked list", "listnode"],
    "Stack/Queue": ["栈", "stack", "队列", "queue", "单调栈", "单调队列", "优先队列"],
    "Heap": ["堆", "heap", "priority"],
    "String": ["字符串", "string", "子串", "kmp", "匹配"],
    "Math": ["数学", "math", "位运算", "xor", "素数", "gcd", "最大公约"],
}

_DIFFICULTY_PATTERNS = [
    (r"\bEasy\b", "Easy"),
    (r"\bMedium\b", "Medium"),
    (r"\bHard\b", "Hard"),
    (r"\b简单\b", "Easy"),
    (r"\b中等\b", "Medium"),
    (r"\b困难\b", "Hard"),
]


class KnowledgeEngine:
    """向量检索引擎。封装了 ChromaDB + Ollama Embedding 的完整生命周期。"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.collection = None

        try:
            import chromadb
            from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

            self.client = chromadb.PersistentClient(path=self.db_path)
            self.embed_fn = OllamaEmbeddingFunction(
                model_name="nomic-embed-text",
                url="http://localhost:11434/api/embeddings",
            )
            self.collection = self.client.get_or_create_collection(
                name="algorithm_notes",
                embedding_function=self.embed_fn,
            )
        except Exception as e:
            print(f"[KnowledgeEngine] 初始化失败: {e}")
            self.collection = None

    # ═══════════════════════════════════════════════════
    #  元数据提取
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _extract_problem_id(filename: str, content: str = "") -> str:
        """从文件名中提取题号。支持 `NNNN.title.md` 格式。"""
        m = re.match(r"(\d{4,5})[.．\s]", filename)
        if m:
            return m.group(1)
        # 退而求其次：从内容中搜索 LeetCode 题号
        m = re.search(r"(?:LeetCode|力扣)\s*[#:]?\s*(\d{1,4})", content)
        if m:
            return m.group(1)
        return ""

    @staticmethod
    def _extract_difficulty(content: str) -> str:
        """从内容中提取难度标签。"""
        for pattern, label in _DIFFICULTY_PATTERNS:
            if re.search(pattern, content):
                return label
        return ""

    @staticmethod
    def _classify_algorithm_type(content: str) -> str:
        """基于关键词匹配算法类型。匹配最多关键词的类型胜出。"""
        content_lower = content.lower()
        best_type = ""
        best_score = 0
        for algo, keywords in _ALGO_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in content_lower)
            if score > best_score:
                best_score = score
                best_type = algo
        return best_type

    @classmethod
    def _enrich_metadata(cls, content: str, source_file: str = "", header: str = "") -> dict:
        """为单个 chunk 组装增强元数据。"""
        meta = {"source": source_file, "header": header}
        pid = cls._extract_problem_id(source_file, content)
        if pid:
            meta["problem_id"] = pid
        diff = cls._extract_difficulty(content)
        if diff:
            meta["difficulty"] = diff
        algo = cls._classify_algorithm_type(content)
        if algo:
            meta["algorithm_type"] = algo
        return meta

    # ═══════════════════════════════════════════════════
    #  Markdown 切分器（手写，禁止截断代码块）
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _split_markdown(text: str, source_file: str = "", max_chars: int = 2000) -> list[dict]:
        """
        手写 Markdown 切分器。

        规则：
        - 按 ## 或 ### 标题物理切断
        - 绝对禁止在 ```python ... ``` 代码块中间切断
        - 超过 max_chars 的 chunk 在段落边界处截断
        - 每个 chunk 附带增强元数据（problem_id / algorithm_type / difficulty）
        """
        lines = text.split("\n")
        chunks = []
        current_lines = []
        in_code = False
        current_header = ""

        def flush():
            if current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    meta = KnowledgeEngine._enrich_metadata(content, source_file, current_header)
                    chunks.append({"content": content, "metadata": meta})
                current_lines.clear()

        def tail_chunk():
            """如果当前积累内容超过 max_chars，在非代码块内截断。"""
            if in_code:
                return
            acc = "".join(current_lines)
            if len(acc) > max_chars:
                cutoff = max_chars
                for j in range(max_chars, max_chars // 2, -1):
                    if j < len(acc) and acc[j] == "\n" and j > cutoff - 500:
                        cutoff = j
                        break
                before = "".join(current_lines)[:cutoff]
                after = "".join(current_lines)[cutoff:]
                chunk = before.strip()
                if chunk:
                    meta = KnowledgeEngine._enrich_metadata(chunk, source_file, current_header)
                    chunks.append({"content": chunk, "metadata": meta})
                current_lines.clear()
                current_lines.append(after)

        for line in lines:
            if line.strip().startswith("```"):
                in_code = not in_code
                current_lines.append(line)
                continue

            if not in_code and re.match(r"^#{2,3}\s", line):
                flush()
                current_header = line.strip()
                current_lines.append(line)
            else:
                current_lines.append(line)
                tail_chunk()

        flush()
        return chunks

    # ═══════════════════════════════════════════════════
    #  入库
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _clean_markdown(text: str) -> str:
        """Markdown 降噪：移除图片链接、网页按钮等无用内容。"""
        text = re.sub(r"!\[.*?\]\(.*?\)", "", text)         # 图片 ![]()
        text = re.sub(r"\[.*?\]\(.*?\)", "", text)          # 链接 []()（含按钮）
        text = re.sub(r"<https?://\S+>", "", text)           # 裸 URL
        text = re.sub(r"---+\s*", "", text)                  # 分隔线
        text = re.sub(r"\n{3,}", "\n\n", text)              # 连续空行压缩
        return text.strip()

    def ingest_books(self, books_dir: str):
        """
        递归扫描 books_dir 下所有 .md，只过滤黑名单文件，不删其他内容。
        自动降噪 + 元数据增强（problem_id / algorithm_type / difficulty）。
        """
        if self.collection is None:
            print("[KnowledgeEngine] 集合未初始化，跳过入库。")
            return

        if not os.path.isdir(books_dir):
            print(f"[KnowledgeEngine] 目录不存在: {books_dir}")
            return

        BLACKLIST = {"README.md", "LICENSE", "index.md", "readme.md", "license"}

        # 清空旧库
        try:
            existing = self.collection.get()
            if existing["ids"]:
                self.collection.delete(ids=existing["ids"])
                print(f"[KnowledgeEngine] 已清空 {len(existing['ids'])} 条旧数据\n")
        except Exception as e:
            print(f"[KnowledgeEngine] 清空旧数据失败（可能为空库）: {e}\n")

        # 扫描所有 .md 文件，跳过黑名单
        md_files = []
        for root, _, files in os.walk(books_dir):
            for fname in sorted(files):
                if fname in BLACKLIST:
                    continue
                if fname.endswith(".md"):
                    md_files.append(os.path.join(root, fname))

        total = len(md_files)
        if total == 0:
            print("[KnowledgeEngine] 目录下未发现 .md 文件。")
            return

        print(f"\n[KnowledgeEngine] 共发现 {total} 个 .md 文件\n")

        all_chunks = []
        batch_size = 5
        file_count = 0

        def _flush_batch():
            if not all_chunks:
                return
            ids = [f"chunk_{i}" for i in range(len(all_chunks))]
            docs = [c["content"] for c in all_chunks]
            metas = [c["metadata"] for c in all_chunks]
            try:
                self.collection.add(ids=ids, documents=docs, metadatas=metas)
                print(f"  -> 入库 {len(all_chunks)} 个片段")
            except Exception as e:
                print(f"  -> 入库失败: {e}")
            all_chunks.clear()

        for fpath in md_files:
            fname = os.path.basename(fpath)
            file_count += 1
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                content = self._clean_markdown(content)
                chunks = self._split_markdown(content, source_file=fname)
                all_chunks.extend(chunks)
                # 打印元数据概览
                sample_meta = chunks[0]["metadata"] if chunks else {}
                pid = sample_meta.get("problem_id", "")
                algo = sample_meta.get("algorithm_type", "")
                diff = sample_meta.get("difficulty", "")
                tags = f" pid={pid}" if pid else ""
                tags += f" algo={algo}" if algo else ""
                tags += f" diff={diff}" if diff else ""
                print(f"[{file_count}/{total}] {fname} -> {len(chunks)} 片段{tags}")
                if len(all_chunks) >= batch_size:
                    _flush_batch()
            except Exception as e:
                print(f"[{file_count}/{total}] {fname} -> 读取失败: {e}")

        _flush_batch()
        print("\n[KnowledgeEngine] 全部入库完成。")

    # ═══════════════════════════════════════════════════
    #  双模检索（硬索引拦截 + 向量库退化）
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _extract_query_problem_id(query: str) -> str:
        """从 Query 中提取题号。"""
        m = re.search(r"(?:^|\s)(\d{1,4})(?:\s|题|$|[.。，,\n])", query)
        if m:
            return m.group(1)
        return ""

    @staticmethod
    def _get_books_dir() -> str:
        return BOOKS_DIR

    @staticmethod
    def _load_manifest() -> dict:
        """加载 ALGO_MANIFEST.json，返回 manifest 字典。"""
        try:
            import json as _json
            if os.path.isfile(MANIFEST_PATH):
                with open(MANIFEST_PATH, "r", encoding="utf-8") as _f:
                    return _json.load(_f).get("manifest", {})
        except Exception:
            pass
        return {}

    @classmethod
    def _index_lookup(cls, query: str, intent: str = "") -> str:
        """
        第一优先级：硬索引拦截。
        从 query 中提取题号 → 查 ALGO_MANIFEST.json → 读物理文件。
        返回内容头部标注 [SOURCE: INDEX]；未命中返回空字符串。
        """
        pid = cls._extract_query_problem_id(query)
        if not pid:
            return ""

        manifest = cls._load_manifest()
        if not manifest:
            return ""

        # 零填充至 4 位以匹配 manifest key 格式（207 → 0207）
        pid_padded = pid.zfill(4)
        entry = manifest.get(pid) or manifest.get(pid_padded)
        if not entry:
            return ""

        # 意图干预：teach 模式下优先选 explanation_heavy 类型
        if intent == "teach" and entry.get("content_type") != "explanation_heavy":
            return ""

        rel_path = entry.get("path", "")
        if not rel_path:
            return ""

        full_path = os.path.normpath(os.path.join(BOOKS_DIR, rel_path))
        if not os.path.isfile(full_path):
            return ""

        # 读取文件（上限 _INDEX_READ_MAX 防内存抖动）
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read(_INDEX_READ_MAX)
        except Exception:
            return ""

        if not content.strip():
            return ""

        # 标注来源
        return f"[SOURCE: INDEX] {entry.get('title', '')}\n\n{content.strip()}"

    def search(self, query: str, top_k: int = 2, min_similarity: float = 0.6, intent: str = "") -> str:
        """
        双模检索：硬索引拦截 + 向量库退化。

        参数：
          query: 查询文本
          top_k: 向量库返回片段数
          min_similarity: 向量库相似度阈值 (0~1)
          intent: 意图标签（teach / error / generate），用于干预索引选择

        返回：
          拼接后的文本，头部标注 [SOURCE: INDEX] / [SOURCE: VECTOR]。
        """
        if not query or not query.strip():
            return "[KnowledgeEngine] 查询内容为空。"

        parts = []

        # ── Phase 1: 硬索引拦截 ──
        index_result = self._index_lookup(query, intent)
        if index_result:
            parts.append(index_result)

        # ── Phase 2: 向量库退化 ──
        if self.collection is not None:
            try:
                pid = self._extract_query_problem_id(query)
                where_filter = {"problem_id": pid} if pid else None

                results = self.collection.query(
                    query_texts=[query],
                    n_results=top_k,
                    where=where_filter,
                )

                if not results or not results["documents"] or not results["documents"][0]:
                    # 题号过滤无结果 → 降级到无过滤重试
                    if where_filter:
                        results = self.collection.query(query_texts=[query], n_results=top_k)

                if results and results.get("documents") and results["documents"][0]:
                    distances = results.get("distances", [[]])[0]
                    vector_parts = []
                    for i, doc in enumerate(results["documents"][0]):
                        dist = distances[i] if i < len(distances) else 1.0
                        similarity = 1.0 / (1.0 + dist)
                        if min_similarity > 0 and similarity < min_similarity:
                            continue
                        meta = results["metadatas"][0][i] if results["metadatas"] else {}
                        source = meta.get("source", "未知来源")
                        header = meta.get("header", "")
                        vector_parts.append(f"--- 来源: {source} | {header} ---\n{doc}")

                    if vector_parts:
                        vector_text = "\n\n".join(vector_parts)
                        parts.append(f"[SOURCE: VECTOR]\n{vector_text}")

            except Exception:
                pass

        if not parts:
            return ""

        return "\n\n".join(parts)
