# -*- coding: utf-8 -*-
"""
统一响应格式
------------------------------------------------------------
所有接口返回：{ code, msg, data }
code=0 成功；非 0 失败，前端只需判断 code。
"""
from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any = None, msg: str = "") -> dict:
    """成功响应。"""
    return {"code": 0, "msg": msg, "data": data}


def fail(code: int = 2001, msg: str = "操作失败", data: Any = None, status_code: int = 200) -> JSONResponse:
    """失败响应（HTTP 状态码默认仍为 200，业务错误由 code 区分）。"""
    return JSONResponse(status_code=status_code, content={"code": code, "msg": msg, "data": data})
