"""
LLM客户端超时配置锁
solo worker单并发，无界LLM调用会冻住worker、排队任务全部滞留
（2026-09-17实例：风险评估节点LLM调用11分钟，后续三单排队15分钟画布全显"待执行"）
仿test_registration锁include配置的写法：锁住三个LLM客户端的超时/重试来源
"""
import pytest

from app.agents.workflow import document_agent
from app.config import settings
from app.ocr.vlm_provider import _build_llm
from app.rag.embeddings import get_embeddings


def test_agent_llm_timeout_bounded():
    assert document_agent.llm.request_timeout == settings.LLM_TIMEOUT_SECONDS
    assert document_agent.llm.max_retries == settings.LLM_MAX_RETRIES


def test_vlm_llm_timeout_bounded():
    llm = _build_llm()
    assert llm.request_timeout == settings.LLM_TIMEOUT_SECONDS
    assert llm.max_retries == settings.LLM_MAX_RETRIES


def test_embeddings_timeout_bounded():
    # RAG停用时无嵌入配置（EMBEDDING_API_KEY可空），嵌入客户端不存在也就无超时可锁
    if settings.RAG_PROVIDER == "off":
        pytest.skip("RAG停用（RAG_PROVIDER=off），嵌入客户端未配置")
    emb = get_embeddings()
    assert emb.request_timeout == settings.LLM_TIMEOUT_SECONDS
    assert emb.max_retries == settings.LLM_MAX_RETRIES
