"""
应用配置管理
使用 Pydantic 进行配置验证和管理
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode

# 项目根目录：backend/app/config.py 向上三级
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """
    应用配置类
    """

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # 应用基础配置
    APP_NAME: str = "Expense Audit System"
    APP_ENV: str = "development"  # 可选值: development, production
    DEBUG: bool = True
    SECRET_KEY: str
    # NoDecode：跳过pydantic-settings对复杂类型的JSON解码，改为下方验证器解析
    ALLOWED_HOSTS: Annotated[list[str], NoDecode] = ["localhost", "127.0.0.1"]  # 可配置允许的主机列表

    # 数据库配置
    DATABASE_URL: str = "mysql+pymysql://user:password@localhost:3306/dbname?charset=utf8mb4"

    # Redis配置
    REDIS_URL: str = "redis://localhost:6379/0"

    # Celery任务队列（AI审核）：db1做broker、db2存任务结果（db0已被报表缓存占用）
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # LLM配置（Kimi for Coding订阅，OpenAI兼容端点）
    LLM_API_KEY: str
    # 必须显式指定，否则ChatOpenAI会静默指向api.openai.com导致401。
    # 注意sk-kimi-开头的密钥只属于Kimi for Coding订阅端点(/coding/v1)，
    # 与api.moonshot.cn、api.kimi.com/v1通用API互不相认
    LLM_API_BASE: str = "https://api.kimi.com/coding/v1"
    MODEL_NAME: str = "k3"  # 可配置使用的模型名称（K3原生多模态，对话/图片理解同款）
    # K3是思考型模型（思考token计入MAX_TOKENS），low/high/max；
    # 审核流水线多Agent串行+solo worker单并发，low平衡时延
    LLM_REASONING_EFFORT: str = "low"
    TEMPERATURE: float = 0.3  # 预留：K3思考模型仅允许temperature=1，当前不传不生效
    MAX_TOKENS: int = 8192  # 思考模型的推理token会挤占回复空间，2048会导致正文为空

    # RAG向量检索配置
    # milvus=启用两路检索+案例回填（需可达的MILVUS_URI+嵌入服务）
    # off=停用（审核链路只用Kimi；RAG节点在画布保留但返回空）
    RAG_PROVIDER: str = "milvus"

    # RAG嵌入配置：本机Ollama跑Qwen3-Embedding（OpenAI兼容/v1/embeddings端点）
    # key为占位值——Ollama不校验，但OpenAI SDK要求非空；换回云API时改base+key+模型名即可
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_API_BASE: str = "http://localhost:11434/v1"
    EMBEDDING_MODEL_NAME: str = "qwen3-embedding:8b"  # 可配置使用的嵌入模型名称
    EMBEDDING_DIMENSIONS: int = 4096  # 嵌入向量维度（Qwen3-Embedding-8B默认4096，可32-4096）
    LLM_TIMEOUT_SECONDS: int = 300  # 单次LLM调用超时：solo worker单并发，无界挂起会冻住整个审核队列
    LLM_MAX_RETRIES: int = 1  # LLM调用失败重试次数（重试放大时延，保守取1）

    # OCR混合流水线配置
    OCR_PROVIDER: str = "hybrid"  # hybrid=混合流水线; off=保持占位行为
    VLM_MODEL_NAME: str = "k3"  # OCR的VLM兜底模型（K3原生支持图片输入）
    OCR_MIN_CONFIDENCE: float = 0.85  # RapidOCR分支的路由阈值(平均置信度)

    # AI审核策略配置
    AGENT_REVIEW_ON_SUBMIT: bool = True  # 提交报销单时是否自动触发AI审核
    RISK_LOW_MAX: int = 40  # 风险分低于此值视为低风险（可自动通过）
    RISK_HIGH_MIN: int = 70  # 风险分高于此值视为高风险（强制人工审批）

    # 向量数据库配置（Milvus独立服务，地址指向已部署的standalone实例）
    MILVUS_URI: str = "http://localhost:19530"

    # 文件存储配置
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 10485760  # 10MB
    ALLOWED_EXTENSIONS: Annotated[list[str], NoDecode] = [".pdf", ".jpg", ".jpeg", ".png", ".docx"]

    # JWT配置
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24

    # 邮件配置
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None

    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "./logs/app.log"

    # CORS配置
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:3000", "http://localhost:5173"]


    @field_validator("ALLOWED_HOSTS", "ALLOWED_ORIGINS", "ALLOWED_EXTENSIONS", mode="before")
    @classmethod
    def _parse_list(cls, v: Any) -> Any:
        """
        支持.env/环境变量中用逗号分隔的列表写法：
        ALLOWED_HOSTS=localhost,127.0.0.1
        同时兼容JSON格式：ALLOWED_HOSTS=["localhost","127.0.0.1"]
        """
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                return json.loads(v)
            return [item.strip() for item in v.split(",") if item.strip()]
        return v


@lru_cache()
def get_settings() -> Settings:
    """
    获取配置实例（单例模式）
    使用缓存避免重复加载配置
    """
    return Settings()


# 全局配置实例
settings = get_settings()
