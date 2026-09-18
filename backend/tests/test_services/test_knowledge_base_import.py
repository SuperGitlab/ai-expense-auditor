"""
KnowledgeBaseManager 制度导入方法测试（Fake store 注入，不碰真实向量库）
核心安全断言：replace 模式只清 policies，绝不触碰 similar_cases
"""
from app.rag.knowledge_base import KnowledgeBaseManager


class FakeStore:
    """记录reset/add调用的假向量库"""

    def __init__(self):
        self.reset_calls = 0
        self.added = []

    def reset(self):
        self.reset_calls += 1
        return True

    def add_documents(self, texts, metadatas, ids):
        self.added.append((texts, metadatas, ids))
        return len(texts)


def _manager() -> tuple[KnowledgeBaseManager, FakeStore, FakeStore]:
    """绕过__init__（不连真实Milvus），注入两个Fake store"""
    m = KnowledgeBaseManager.__new__(KnowledgeBaseManager)
    m.policies_store = FakeStore()
    m.cases_store = FakeStore()
    return m, m.policies_store, m.cases_store


def test_import_policy_document_append():
    """追加模式：不清空，直接切块入库；metadata带doc_id/imported_at"""
    m, policies, cases = _manager()
    added, cleared = m.import_policy_document(
        [{"title": "第一章", "content": "a" * 600}], "新制度"
    )
    assert added == 2  # 600字按500/50滑窗切成2块
    assert cleared is False
    assert policies.reset_calls == 0
    assert cases.reset_calls == 0

    texts, metadatas, ids = policies.added[0]
    assert len(texts) == 2
    meta = metadatas[0]
    assert meta["source"] == "新制度"
    assert meta["section"] == "第一章"
    assert meta["doc_id"]
    assert meta["imported_at"]


def test_import_policy_document_replace_never_touches_cases():
    """替换模式：先清policies再写入；similar_cases的reset从未被调（关键安全断言）"""
    m, policies, cases = _manager()
    added, cleared = m.import_policy_document(
        [{"title": "s", "content": "内容"}], "src", replace=True
    )
    assert cleared is True
    assert policies.reset_calls == 1
    assert policies.added  # 清空后仍有写入
    assert cases.reset_calls == 0


def test_clear_policies_only_policies():
    """clear_policies 只重置制度库"""
    m, policies, cases = _manager()
    assert m.clear_policies() is True
    assert policies.reset_calls == 1
    assert cases.reset_calls == 0
