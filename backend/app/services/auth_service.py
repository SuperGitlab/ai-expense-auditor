"""
认证服务
密码哈希、JWT令牌的生成与校验、用户注册与登录验证
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User, UserRole
from app.schemas.user import UserCreate

logger = logging.getLogger(__name__)

# bcrypt哈希上下文（注意：bcrypt必须为4.x，5.x与passlib不兼容会抛ValueError）
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """密码哈希"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验密码与哈希是否匹配"""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def create_access_token(user: User) -> str:
    """
    生成JWT访问令牌

    Args:
        user: 用户对象

    Returns:
        str: 编码后的JWT令牌
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRATION_HOURS)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value if isinstance(user.role, UserRole) else str(user.role),
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """
    解码JWT令牌

    Returns:
        dict: 令牌载荷；无效/过期返回None
    """
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        logger.debug(f"JWT解码失败: {e}")
        return None


def register_user(db: Session, user_in: UserCreate) -> User:
    """
    注册新用户

    Raises:
        ValueError: 用户名或邮箱已存在
    """
    if db.query(User).filter(User.username == user_in.username).first():
        raise ValueError(f"用户名 {user_in.username} 已存在")
    if db.query(User).filter(User.email == user_in.email).first():
        raise ValueError(f"邮箱 {user_in.email} 已被注册")

    user = User(
        username=user_in.username,
        email=user_in.email,
        hashed_password=hash_password(user_in.password),
        full_name=user_in.full_name,
        phone=user_in.phone,
        department=user_in.department,
        position=user_in.position,
        role=user_in.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"新用户注册: {user.username} ({user.role.value})")
    return user


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """
    用户名密码验证

    Returns:
        User: 验证成功（并更新最后登录时间）；失败返回None
    """
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return user
