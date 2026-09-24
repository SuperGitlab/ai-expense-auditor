"""
检索器模块
面向审核场景的两路检索：财务制度 / 历史相似案例
"""
import logging
from typing import Optional

from app.rag.vectorstore import VectorStore

logger = logging.getLogger(__name__)

# 集合名称常量（knowledge_base与retriever共用）
POLICIES_COLLECTION = "policies"
CASES_COLLECTION = "similar_cases"


class ExpenseRetriever:
    """
    报销审核检索器：
    - retrieve_policies: 检索公司财务制度相关段落
    - retrieve_similar_cases: 检索历史相似报销案例
    """

    def __init__(self):
        self.policies_store = VectorStore(POLICIES_COLLECTION)
        self.cases_store = VectorStore(CASES_COLLECTION)

    def retrieve_policies(self, query: str, k: int = 3) -> list[dict]:
        """
        检索财务制度段落

        Returns: [{content, source, section, distance}]
        """
        results = self.policies_store.query(query, k=k)
        return [
            {
                "content": r["document"],
                "source": r["metadata"].get("source", "公司财务制度"),
                "section": r["metadata"].get("section", ""),
                "distance": r["distance"],
            }
            for r in results
        ]

    def retrieve_similar_cases(self, query: str, k: int = 3) -> list[dict]:
        """
        检索历史相似案例

        Returns: [{content, expense_id, title, status, risk_level, distance}]
        """
        results = self.cases_store.query(query, k=k)
        return [
            {
                "content": r["document"],
                "expense_id": r["metadata"].get("expense_id"),
                "title": r["metadata"].get("title", ""),
                "status": r["metadata"].get("status", ""),
                "risk_level": r["metadata"].get("risk_level", ""),
                "distance": r["distance"],
            }
            for r in results
        ]
