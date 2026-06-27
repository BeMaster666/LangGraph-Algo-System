"""
入库脚本 — 将 books/ 目录下的算法书（.md / .pdf）向量化存入 ChromaDB。

用法：
    cd LangGraph-Algo-System\mind
    python ingest.py
"""

from knowledge_engine import KnowledgeEngine
from config import BOOKS_DIR

if __name__ == "__main__":
    print(f"入库目录: {BOOKS_DIR}")
    engine = KnowledgeEngine()
    engine.ingest_books(BOOKS_DIR)
