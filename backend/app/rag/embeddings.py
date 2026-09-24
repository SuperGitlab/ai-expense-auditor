"""
向量嵌入模块
通过本机Ollama的OpenAI兼容接口生成文本向量（Qwen3-Embedding-8B，MTEB榜一）
"""
from functools import lru_cache

from langchain_openai import OpenAIEmbeddings

from app.config import settings


@lru_cache()
def get_embeddings() -> OpenAIEmbeddings:
    """
    获取嵌入模型实例（单例）

    关键参数：
    - check_embedding_ctx_length=False：禁用tiktoken分块（OpenAI词表对Qwen3无效，
      长中文文本会被错误切分成多次请求），分块由knowledge_base按字符数控制
    """
    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL_NAME,
        api_key=settings.EMBEDDING_API_KEY,
        base_url=settings.EMBEDDING_API_BASE,
        check_embedding_ctx_length=False,
        dimensions=settings.EMBEDDING_DIMENSIONS,
        # 嵌入调用同样要有界：检索节点挂死会拖住整条审核流水线（solo worker单并发）
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=settings.LLM_MAX_RETRIES,
    )
