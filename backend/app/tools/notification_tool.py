"""
通知工具
审核结果通知（SMTP可用时发邮件，否则降级为日志记录）
"""
import logging
import smtplib
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


def notify(user_email: str | None, title: str, content: str) -> bool:
    """
    发送通知

    Args:
        user_email: 收件人邮箱（可为空）
        title: 通知标题
        content: 通知内容

    Returns:
        bool: 是否发送成功（未配置SMTP时记录日志并返回False）
    """
    if not settings.SMTP_HOST or not settings.SMTP_USER or not user_email:
        logger.info(f"[通知-降级日志] 收件人={user_email or 'N/A'} 标题={title} 内容={content}")
        return False

    try:
        msg = MIMEText(content, "plain", "utf-8")
        msg["Subject"] = title
        msg["From"] = settings.SMTP_USER
        msg["To"] = user_email

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_USER, [user_email], msg.as_string())
        logger.info(f"通知已发送至 {user_email}: {title}")
        return True
    except Exception as e:
        logger.warning(f"通知发送失败（不影响主流程）: {e}")
        return False
