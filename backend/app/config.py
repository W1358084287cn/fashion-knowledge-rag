# -*- coding: utf-8 -*-
"""
全局配置模块
------------------------------------------------------------
所有可变参数统一从环境变量 / .env 文件读取，避免把账号密码写死在代码里。
默认值与 docker-compose.yml 中定义的基础设施保持一致，做到"开箱即用"。
"""
import os
from functools import lru_cache

from dotenv import load_dotenv

# 先加载项目根目录的 .env，再加载 backend/.env（后者优先级更高，覆盖前者）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # backend/
ROOT_DIR = os.path.dirname(BASE_DIR)                                        # 项目根目录
load_dotenv(os.path.join(ROOT_DIR, ".env"))
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)


def _get_int(name: str, default: int) -> int:
    """读取整数型环境变量，解析失败时回退默认值，避免因配置笔误导致启动崩溃。"""
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class Settings:
    """项目配置对象（单例）。"""

    # ---------------- MySQL 业务库 ----------------
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT: int = _get_int("MYSQL_PORT", 3306)
    MYSQL_USER: str = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD: str = os.getenv("MYSQL_PASSWORD", "123456")
    MYSQL_DB: str = os.getenv("MYSQL_DB", "fashion_cs")

    # ---------------- Qdrant 向量库 ----------------
    QDRANT_URL: str = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
    QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "fashion_kb")

    # ---------------- Neo4j 图数据库 ----------------
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "***")

    # ---------------- 管理员账号（固定需求） ----------------
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "123456")

    # ---------------- JWT 登录态 ----------------
    JWT_SECRET: str = os.getenv("JWT_SECRET", "fashion-cs-demo-secret-2026")
    JWT_EXPIRE_MINUTES: int = _get_int("JWT_EXPIRE_MINUTES", 480)

    # ---------------- 离线处理参数 ----------------
    # 注意：如果 .env 里写成 UPLOAD_DIR=（空值），os.getenv 会返回空字符串，
    # 这里统一做兜底，避免后续 os.makedirs("") 报错导致服务启动失败。
    UPLOAD_DIR: str = (os.getenv("UPLOAD_DIR", "").strip()
                       or os.path.join(BASE_DIR, "uploads"))
    MAX_UPLOAD_MB: int = _get_int("MAX_UPLOAD_MB", 50)          # 单文件大小上限
    CHUNK_SIZE: int = _get_int("CHUNK_SIZE", 600)               # 文本切片长度
    CHUNK_OVERLAP: int = _get_int("CHUNK_OVERLAP", 80)          # 切片重叠长度
    MAX_CHUNKS_PER_FILE: int = _get_int("MAX_CHUNKS_PER_FILE", 300)  # 单文件切片上限，防止超大文件拖垮演示
    OCR_MIN_CHARS_PER_PAGE: int = _get_int("OCR_MIN_CHARS_PER_PAGE", 30)

    # ---------------- 在线问答参数 ----------------
    EMBEDDING_DIM: int = _get_int("EMBEDDING_DIM", 1024)        # 硅基流动 BAAI/bge-m3 默认维度
    CACHE_TTL_SECONDS: int = _get_int("CACHE_TTL_SECONDS", 600) # 高频问题缓存有效期
    CACHE_MAX_SIZE: int = _get_int("CACHE_MAX_SIZE", 200)       # 缓存条数上限
    TOP_K_EACH: int = _get_int("TOP_K_EACH", 20)                # 稠密/稀疏各自召回数量
    TOP_K_FINAL: int = _get_int("TOP_K_FINAL", 5)               # RRF 融合后最终保留片段数（3~6）
    LLM_TIMEOUT_SECONDS: int = _get_int("LLM_TIMEOUT_SECONDS", 90)

    # ---------------- 前端静态资源 ----------------
    DIST_DIR: str = os.getenv("DIST_DIR", os.path.join(ROOT_DIR, "frontend", "dist"))

    @property
    def database_url(self) -> str:
        """SQLAlchemy 连接串（使用 PyMySQL 驱动）。"""
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}?charset=utf8mb4"
        )


@lru_cache()
def get_settings() -> Settings:
    """带缓存的配置获取，避免重复读取 .env。"""
    return Settings()


settings = get_settings()

# 保证上传目录存在（首次启动即可用）
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
