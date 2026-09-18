"""
应用入口
FastAPI应用创建、中间件配置与路由挂载
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    启动时初始化资源，关闭时清理资源
    """
    logger.info("正在初始化应用...")

    # 确保文件上传目录存在
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

    # 连接池状态（池随 app.database 的 import 创建；连接懒建立，此刻应为0根）
    from app.database import engine
    logger.info(f"连接池已创建: {engine.pool.status()}")

    # 数据库连接检查（失败仅告警，不阻塞启动，便于排查配置问题）
    try:
        from sqlalchemy import text
        with engine.connect() as conn:  # ← 池里第一根连接在此诞生，用完还回池
            conn.execute(text("SELECT 1"))
        logger.info(f"数据库连接正常: {engine.pool.status()}")
    except Exception as e:
        logger.warning(f"数据库连接失败（请检查MySQL是否启动）: {e}")

    # 知识库加载校验：启动时打印制度/案例库存量统计（复用workflow的模块级单例）；
    # Milvus不可用时count返回-1、此处异常仅告警，均不阻塞启动
    try:
        from app.agents.workflow import knowledge_base
        knowledge_base.load_knowledge_bases()
    except Exception as e:
        logger.warning(f"知识库加载失败（RAG检索将返回空结果）: {e}")

    logger.info("应用初始化完成，开始运行...")

    yield

    # 关闭时清理
    logger.info("正在关闭应用...")
    logger.info(f"关闭时连接池: {engine.pool.status()}（连接随进程退出由系统回收）")


# 配置CORS中间件
app = FastAPI(
    title="AI Agent财务审核报销系统",
    description="基于LLM、RAG、LangGraph的AI Agent财务报销审核系统",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 可信主机中间件
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.ALLOWED_HOSTS,
)


# 统一异常响应：未捕获异常返回JSON而非500裸文本
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(f"未处理异常 [{request.method} {request.url.path}]: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请稍后重试"},
    )


@app.get("/")
async def root():
    """
    根路径健康检查
    """
    return {
        "message": "AI Agent财务审核报销系统",
        "status": "running",
        "version": "1.0.0",
    }


@app.get("/health")
async def health_check():
    """
    健康检查接口
    """
    return {
        "status": "healthy",
        "message": "应用运行正常",
    }


# ---------- 路由挂载 ----------
from app.api.endpoints import (agent, approvals, auth, categories, expenses,  # noqa: E402
                               notifications, reports, rule_import, rules,
                               uploads, users)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(expenses.router)
app.include_router(approvals.router)
app.include_router(rules.router)
app.include_router(rule_import.router)
app.include_router(agent.router)
app.include_router(reports.router)
app.include_router(categories.router)
app.include_router(notifications.router)
app.include_router(uploads.router)

# 上传文件静态服务（无鉴权：路径含uuid不可猜测，演示项目可接受）
# mount构造即校验目录存在，须先mkdir；lifespan里的mkdir保留，二者幂等
Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")
