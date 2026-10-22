# -*- coding: utf-8 -*-
"""
FastAPI 应用入口
------------------------------------------------------------
- 启动时等待 MySQL、建表、初始化 Qdrant 集合与 Neo4j 约束
- 恢复上次未完成的离线任务
- 同时托管 Vue 构建产物：/ 客户端、/admin 管理端
"""
import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db, wait_for_mysql
from .routers import admin, agents, auth, chat, health, kb
from .services import neo4j_store, qdrant_store
from .services.jobs import resume_unfinished

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

app = FastAPI(
    title="基于 LangChain + 知识图谱双引擎的服装多源文档智能客服系统",
    description="毕业设计演示项目：Agent1 文档预处理 / Agent2 知识抽取 / Agent3 问答推理",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# 本地演示 / 手机局域网访问：允许跨域（无 Cookie 依赖，故不开启 credentials）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册接口
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(auth.user_router)
app.include_router(admin.router)
app.include_router(kb.router)
app.include_router(agents.router)
app.include_router(chat.router)


# ------------------------------------------------------------------
# 统一异常处理：保证前端永远拿到 {code,msg,data}
# ------------------------------------------------------------------
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code_map = {401: 1002, 403: 1002, 404: 2001, 422: 1001}
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code_map.get(exc.status_code, 2001), "msg": str(exc.detail), "data": None},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    兜底异常处理：任何未捕获异常都返回统一结构，避免前端只看到裸 500。
    注意：这里只做日志记录与友好提示，不泄露堆栈细节。
    """
    logging.exception("接口未捕获异常：%s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"code": 2001, "msg": "服务器处理异常，请查看后端日志或稍后重试", "data": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    msg = first.get("msg", "参数不合法")
    return JSONResponse(
        status_code=422,
        content={"code": 1001, "msg": f"参数不合法：{field} {msg}".strip(), "data": None},
    )


# ------------------------------------------------------------------
# 启动事件
# ------------------------------------------------------------------
@app.on_event("startup")
def on_startup():
    """服务启动初始化：数据库 -> 向量库 -> 图谱 -> 恢复任务。"""
    if not wait_for_mysql(max_retry=30, interval=2):
        # 不直接抛异常退出：保证前端页面仍可访问，健康检查接口会明确提示 MySQL 未连接，
        # 便于在小白用户的机器上第一时间看到"哪里没启动"，而不是整个服务直接挂掉。
        logging.error(
            "MySQL 连接失败：登录、知识库、对话历史等功能不可用。"
            "请先执行 docker compose up -d，或检查 .env 中的 MySQL 配置。"
        )
        return
    init_db()

    # 向量库 / 图谱初始化失败不阻断服务启动（在线问答会给出降级提示）
    try:
        qdrant_store.ensure_collection_sync()
    except Exception as exc:  # noqa: BLE001
        logging.error("Qdrant 初始化失败：%s", exc)
    try:
        neo4j_store.ensure_constraints_sync()
    except Exception as exc:  # noqa: BLE001
        logging.error("Neo4j 初始化失败：%s", exc)

    resume_unfinished()


# ------------------------------------------------------------------
# 前端静态资源托管
# ------------------------------------------------------------------
DIST_DIR = settings.DIST_DIR
INDEX_FILE = os.path.join(DIST_DIR, "index.html")
ADMIN_FILE = os.path.join(DIST_DIR, "admin.html")

if os.path.isdir(os.path.join(DIST_DIR, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST_DIR, "assets")), name="assets")

PLACEHOLDER = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>服装智能客服</title></head>
<body style="font-family:system-ui;padding:40px;line-height:1.8;color:#333">
<h2>前端尚未构建</h2>
<p>请先在 frontend 目录执行：</p>
<pre style="background:#f5f5f5;padding:16px;border-radius:8px">npm install
npm run build</pre>
<p>或直接运行项目根目录的一键启动脚本 start.bat。</p>
</body></html>"""


NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}


@app.get("/", include_in_schema=False)
def client_page():
    """客户端 H5（免登录聊天页）。"""
    if os.path.exists(INDEX_FILE):
        # 入口 HTML 不缓存，确保重新构建后无需手动硬刷新即可加载新资源
        return FileResponse(INDEX_FILE, headers=NO_CACHE)
    return HTMLResponse(PLACEHOLDER)


@app.get("/admin", include_in_schema=False)
@app.get("/admin.html", include_in_schema=False)
def admin_page():
    """管理端 H5（登录 + 三个 Tab）。"""
    if os.path.exists(ADMIN_FILE):
        return FileResponse(ADMIN_FILE, headers=NO_CACHE)
    return HTMLResponse(PLACEHOLDER)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """避免浏览器请求 favicon 时产生 404 日志。"""
    return JSONResponse(status_code=204, content=None)
