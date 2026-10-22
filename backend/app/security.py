# -*- coding: utf-8 -*-
"""
安全与鉴权
------------------------------------------------------------
- 管理员密码使用 SHA256 摘要存储，不落明文
- 登录成功后签发 JWT，默认 8 小时有效
- 登录接口内置简单的 IP 频率限制，抵御暴力破解
- 普通用户聊天接口无需登录，由接口内部标记 user_type=user
"""
import hashlib
import time
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import HTTPException, Request

from .config import settings


def hash_password(raw: str) -> str:
    """密码摘要（毕业设计演示足够；生产环境建议 bcrypt + 随机盐）。"""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_password(raw: str, hashed: str) -> bool:
    """恒定时间比较，避免时序攻击。"""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest() == hashed


def create_token(username: str, role: str = "admin", user_id: Optional[int] = None) -> str:
    """签发登录 JWT；role=admin 为管理员，role=user 为普通用户。"""
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
        "iat": datetime.utcnow(),
    }
    if user_id is not None:
        payload["uid"] = int(user_id)
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    """解析 JWT，失败（过期 / 篡改）返回 None。"""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def token_from_request(request: Request, token_query: Optional[str] = None) -> Optional[str]:
    """
    从请求中提取 token：
    1. Authorization: Bearer xxx（管理端 fetch 使用）
    2. ?token=xxx（EventSource 降级场景）
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    if token_query:
        return token_query.strip()
    return None


def get_current_admin(request: Request) -> dict:
    """FastAPI 依赖：校验管理员身份，失败抛出 401（支持 ?token= 便于直接下载文件）。"""
    payload = decode_token(token_from_request(request, request.query_params.get("token")) or "")
    if not payload or payload.get("role") != "admin":
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return payload


def get_current_user(request: Request) -> dict:
    """FastAPI 依赖：校验普通用户身份，失败抛出 401。"""
    payload = decode_token(token_from_request(request, request.query_params.get("token")) or "")
    if not payload or payload.get("role") != "user":
        raise HTTPException(status_code=401, detail="请先登录后再使用")
    return payload


def get_identity_optional(request: Request, token_query: Optional[str] = None) -> Optional[dict]:
    """
    尝试解析当前请求的身份（不抛异常）。
    返回 {role, username, user_id}；未登录返回 None。
    """
    payload = decode_token(token_from_request(request, token_query) or "")
    if not payload:
        return None
    role = payload.get("role")
    if role not in ("admin", "user"):
        return None
    return {
        "role": role,
        "username": payload.get("sub", ""),
        "user_id": payload.get("uid"),
    }


class LoginRateLimiter:
    """
    简单的内存登录限流器：
    同一 IP 在 window_seconds 内最多尝试 max_attempts 次，超过则暂时锁定。
    仅用于演示环境，生产可替换为 Redis。
    """

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._records: dict = {}  # {ip: [timestamp, ...]}

    def check(self, ip: str) -> Optional[int]:
        """返回剩余等待秒数；None 表示允许尝试。"""
        now = time.time()
        records = [t for t in self._records.get(ip, []) if now - t < self.window_seconds]
        self._records[ip] = records
        if len(records) >= self.max_attempts:
            return int(self.window_seconds - (now - records[0])) + 1
        return None

    def record_failure(self, ip: str) -> None:
        """记录一次失败尝试。"""
        self._records.setdefault(ip, []).append(time.time())

    def reset(self, ip: str) -> None:
        """登录成功后清空该 IP 的失败记录。"""
        self._records.pop(ip, None)


login_limiter = LoginRateLimiter()
