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

    # LLM配置(GLM)
    GLM_API_KEY: str
    # GLM官方OpenAI兼容API地址；必须显式指定，否则ChatOpenAI会静默指向api.openai.com导致401
    GLM_API_BASE: str = "https://open.bigmodel.cn/api/paas/v4"
    MODEL_NAME: str = "glm-5.1"  # 可配置使用的模型名称
    EMBEDDING_MODEL_NAME: str = "embedding-3"  # 可配置使用的嵌入模型名称
    TEMPERATURE: float = 0.3  # 审核场景需要稳定输出，温度不宜过高
    MAX_TOKENS: int = 2048  # 可配置最大token数

    # OCR混合流水线配置
    OCR_PROVIDER: str = "hybrid"  # hybrid=混合流水线; off=保持占位行为
    VLM_MODEL_NAME: str = "glm-4.1v-flash"  # OCR的VLM兜底模型
    OCR_MIN_CONFIDENCE: float = 0.85  # RapidOCR分支的路由阈值(平均置信度)

    # AI审核策略配置
    AGENT_REVIEW_ON_SUBMIT: bool = True  # 提交报销单时是否自动触发AI审核
    RISK_LOW_MAX: int = 40  # 风险分低于此值视为低风险（可自动通过）
    RISK_HIGH_MIN: int = 70  # 风险分高于此值视为高风险（强制人工审批）
    EMBEDDING_DIMENSIONS: int = 1024  # embedding-3支持的向量维度(256/512/1024/2048)

    # 向量数据库配置
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    CHROMA_COLLECTION: str = "expense_knowledge"

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
