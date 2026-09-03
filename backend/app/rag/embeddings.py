"""
向量嵌入模块
通过GLM的OpenAI兼容接口生成文本向量（embedding-3）
"""
from functools import lru_cache

from langchain_openai import OpenAIEmbeddings

from app.config import settings


@lru_cache()
def get_embeddings() -> OpenAIEmbeddings:
    """
    获取嵌入模型实例（单例）

    关键参数：
    - check_embedding_ctx_length=False：禁用tiktoken分块（OpenAI词表对GLM无效，
      长中文文本会被错误切分成多次请求），分块由knowledge_base按字符数控制
    """
    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL_NAME,
        api_key=settings.GLM_API_KEY,
        base_url=settings.GLM_API_BASE,
        check_embedding_ctx_length=False,
        dimensions=settings.EMBEDDING_DIMENSIONS,
    )
