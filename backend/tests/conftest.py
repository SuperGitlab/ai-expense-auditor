"""
pytest测试配置
- 使用独立的测试数据库（expense_db_test，勿与开发库混用）
- DB不可达时API用例自动跳过；纯函数用例（规则引擎等）始终执行
- LLM真实调用用例标记llm，默认跳过（uv run pytest -m llm 可启用）
"""
import os
import sys
from pathlib import Path

import pytest

# 将backend/加入路径（pytest从backend/运行：uv run pytest）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 测试库连接串（必须在import app之前设置环境变量）
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "mysql+pymysql://user:password@localhost:3306/expense_db_test?charset=utf8mb4",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
# API测试中关闭提交自动AI审核（避免真实LLM调用；工作流专项用例用llm标记单独跑）
os.environ["AGENT_REVIEW_ON_SUBMIT"] = "False"
# TestClient默认Host为testserver，不在可信主机列表会被TrustedHostMiddleware拦成400，测试前补入
os.environ["ALLOWED_HOSTS"] = "localhost,127.0.0.1,testserver"
# 测试会话不写日志文件（app.main import 时会按 LOG_FILE 初始化文件 handler）
os.environ["LOG_FILE"] = ""

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.database import get_db  # noqa: E402
from app.models import Base  # noqa: E402

# 探测测试DB是否可达（不可达则跳过DB相关用例）
_db_available = False
try:
    _engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    with _engine.connect() as _conn:
        _conn.execute(text("SELECT 1"))
    _db_available = True
except Exception:
    _db_available = False

requires_db = pytest.mark.skipif(
    not _db_available, reason="测试数据库不可达（检查TEST_DATABASE_URL配置）"
)


@pytest.fixture(scope="session")
def db_engine():
    """session级engine：建表一次"""
    Base.metadata.create_all(bind=_engine)
    yield _engine
    _engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    """function级会话：每个用例清空数据表后重建种子类别（保证隔离）"""
    from app.models import Category

    Session = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    session = Session()
    # 按外键依赖倒序清表
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    # MySQL的DELETE不重置自增计数：重置后种子数据id稳定从1开始（业务测试payload硬编码category_id）
    for table in Base.metadata.sorted_tables:
        if any(
            c.autoincrement and c.type.python_type is int
            for c in table.primary_key.columns
        ):
            session.execute(text(f"ALTER TABLE {table.name} AUTO_INCREMENT = 1"))
    session.commit()
    # 测试用基础类别（与业务测试payload中的category_id对应）
    session.add_all([
        Category(name="差旅费", code="travel", max_amount=5000),
        Category(name="餐饮费", code="meal", max_amount=500),
    ])
    session.commit()
    yield session
    session.close()


@pytest.fixture()
def client(db_session):
    """测试客户端：覆盖get_db依赖指向测试会话"""
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ===== 公共注册/登录辅助 =====
def register_and_login(client_: TestClient, username: str, role: str = "employee") -> dict:
    """注册并登录返回Authorization头"""
    resp = client_.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "pass123456",
            "full_name": username,
            "department": "测试部",
            "role": role,
        },
    )
    assert resp.status_code == 201, resp.text
    resp = client_.post(
        "/api/auth/login-json", json={"username": username, "password": "pass123456"}
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
