"""
模型配置 — 所有节点的 LLM 调用共享同一组配置。
"""

import os
from dotenv import load_dotenv

# 从 config.py 所在目录加载 .env
_config_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_config_dir, ".env"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.siliconflow.cn/v1")
MODEL = os.getenv("AGENT_MODEL", "deepseek-ai/DeepSeek-V3")

# ── 知识库路径 ─────────────────────────────────────────────
# 把你的算法 PDF / MD 书放进这个目录，然后运行：
#   from knowledge_engine import KnowledgeEngine
#   KnowledgeEngine().ingest_books(NOTES_DIR)
BOOKS_DIR = os.path.join(_config_dir, "books")

# ── Checkpointer 配置 ─────────────────────────────────────
# 设置 REDIS_URL 环境变量以启用 Redis 持久化，否则使用 MemorySaver
# 格式: redis://[[username]:[password]]@localhost:6379/0
# 或   rediss://... (SSL), redis+sentinel://... (Sentinel)
REDIS_URL = os.getenv("REDIS_URL", "")
