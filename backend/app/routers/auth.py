# -*- coding: utf-8 -*-
"""
管理员登录接口 + 普通用户（客户端）登录接口
------------------------------------------------------------
管理员：账号固定 admin / 密码 123456（初始化 SQL 写入哈希）
普通用户：演示账号 demo / 123456，客户端登录页自动预填，一键登录
- 登录前置做频率限制
- 成功后返回 JWT，前端存 localStorage
"""
from datetime import datetime

from fastapi import APIRouter, Request

from ..api_utils import fail, ok
from ..config import settings
from ..db import SessionLocal
from ..models import Admin, UserAccount
from ..schemas import LoginRequest, UserLoginRequest
from ..security import (
    create_token, get_current_admin, get_current_user, login_limiter, verify_password,
)
from ..services.audit import write_operation

router = APIRouter(prefix="/api/admin", tags=["管理员"])
user_router = APIRouter(prefix="/api/user", tags=["普通用户"])


@router.post("/login")
def login(payload: LoginRequest, request: Request):
    """管理员登录。"""
    ip = request.client.host if request.client else "unknown"

    # 1. 频率限制：防止脚本暴力猜测密码
    wait = login_limiter.check(ip)
    if wait is not None:
        return fail(2001, f"尝试过于频繁，请 {wait} 秒后再试", status_code=429)

    username = (payload.username or "").strip()
    password = *** or ""
    if not username or not password:
        return fail(1001, "请输入账号和密码")

    # 2. 数据库校验（密码以 SHA256 摘要存储）
    db = SessionLocal()
    try:
        admin = db.query(Admin).filter(Admin.username == username).first()
        if not admin or not verify_password(password, admin.password_hash):
            login_limiter.record_failure(ip)
            return fail(1002, "账号或密码错误", status_code=401)
    finally:
        db.close()

    # 3. 签发 JWT
    login_limiter.reset(ip)
    token = ***(username)
    return ok({
        "token": token,
        "username": username,
        "expires_in": settings.JWT_EXPIRE_MINUTES * 60,
    }, msg="登录成功")


@router.get("/me")
def me(request: Request):
    """校验登录态并返回当前管理员信息（前端刷新页面时使用）。"""
    payload = get_current_admin(request)
    return ok({"username": payload.get("sub", settings.ADMIN_USERNAME)})


@user_router.post("/login")
def user_login(payload: UserLoginRequest, request: Request):
    """普通用户登录：演示环境账号 demo / 123456，登录页自动预填。"""
    ip = request.client.host if request.client else "unknown"
    wait = login_limiter.check(ip)
    if wait is not None:
        return fail(2001, f"尝试过于频繁，请 {wait} 秒后再试", status_code=429)

    username = (payload.username or "").strip()
    password = *** or ""
    if not username or not password:
        return fail(1001, "请输入账号和密码")

    db = SessionLocal()
    try:
        user = db.query(UserAccount).filter(UserAccount.username == username).first()
        if not user or not verify_password(password, user.password_hash):
            login_limiter.record_failure(ip)
            return fail(1002, "账号或密码错误", status_code=401)
        user.last_login_at = datetime.now()
        db.commit()
        user_id = int(user.id)
        display_name = user.display_name or username
    finally:
        db.close()

    login_limiter.reset(ip)
    token = ***(username, role="user", user_id=user_id)
    write_operation("user", username, "用户登录", target=username, ip=ip)
    return ok({
        "token": token,
        "username": username,
        "display_name": display_name,
        "user_id": user_id,
        "expires_in": settings.JWT_EXPIRE_MINUTES * 60,
    }, msg="登录成功")


@user_router.get("/me")
def user_me(request: Request):
    """校验普通用户登录态。"""
    payload = get_current_user(request)
    return ok({
        "username": payload.get("sub", ""),
        "user_id": payload.get("uid"),
    })
