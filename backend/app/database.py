"""
数据库连接管理
SQLAlchemy引擎与会话工厂，提供FastAPI依赖注入用的get_db
"""
import logging
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Base  # noqa: F401 确保建表时所有模型已注册

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # 取连接前ping，避免数据库重启后拿到死连接
    pool_recycle=3600,   # MySQL的wait_timeout会杀闲置连接，每小时主动换新
    pool_size=5,
    max_overflow=10,
    echo=False,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI依赖：提供数据库会话，请求结束自动关闭
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
