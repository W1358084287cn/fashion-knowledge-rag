# -*- coding: utf-8 -*-
"""
数据库连接与初始化
------------------------------------------------------------
- 创建 SQLAlchemy 引擎 / 会话工厂
- 首次启动自动建表并写入默认数据（管理员、3 个 Agent 配置、演示商品）
- 提供 wait_for_mysql，解决 docker 容器刚启动、MySQL 尚未就绪的问题
"""
import time
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from .config import settings
from .models import Admin, AgentConfig, Base, Goods, UserAccount
from .security import hash_password

def ensure_database_exists() -> None:
    """
    确保业务库存在（本机已有 MySQL、但还没建 fashion_cs 时也能一键启动）。
    只负责建库，不建表；建表由 init_db() 完成。
    连接失败时静默返回，由 wait_for_mysql 给出更明确的等待日志。
    """
    server_url = (
        f"mysql+pymysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}"
        f"@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/?charset=utf8mb4"
    )
    try:
        tmp_engine = create_engine(server_url, pool_pre_ping=True)
        with tmp_engine.connect() as conn:
            conn.execute(text(
                f"CREATE DATABASE IF NOT EXISTS `{settings.MYSQL_DB}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            ))
        tmp_engine.dispose()
    except Exception as exc:  # noqa: BLE001
        print(f"[MySQL] 自动建库跳过：{exc}")


# 注意：必须先确保数据库存在，再用带库名的连接串创建引擎
ensure_database_exists()

# pool_pre_ping：连接池取连接前先探活，避免 MySQL 8 小时断开导致的报错
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=10,
    max_overflow=20,
    echo=False,
)
# expire_on_commit=False：会话提交后对象属性仍可读取，
# 避免「在 session 内读取 Agent 配置、session 关闭后再调用模型」时触发 DetachedInstanceError
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                           expire_on_commit=False)


@contextmanager
def session_scope():
    """会话上下文：自动 commit / rollback / close，避免连接泄漏。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def wait_for_mysql(max_retry: int = 30, interval: int = 2) -> bool:
    """等待 MySQL 就绪（docker 首次启动初始化较慢）。"""
    for i in range(max_retry):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[MySQL] 等待连接中 ({i + 1}/{max_retry})：{exc}")
            time.sleep(interval)
    return False


# ------------------------------------------------------------------
# 默认 Agent 配置：硅基流动（SiliconFlow）的 OpenAI 兼容接口
# 说明：硅基流动提供免费额度，注册后在控制台创建 ApiKey 即可直接使用；
#       LLM 与 Embedding 都走同一个域名，只是路径不同。
# ------------------------------------------------------------------
DEFAULT_LLM_URL = "https://api.siliconflow.cn/v1/chat/completions"
DEFAULT_EMBEDDING_URL = "https://api.siliconflow.cn/v1/embeddings"
DEFAULT_LLM_MODEL = "Qwen/Qwen2.5-7B-Instruct"       # 免费模型，适合答辩演示
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"              # 1024 维，与 EMBEDDING_DIM 一致

# 旧版本默认值：用于启动时的一次性迁移（把已入库的 DashScope 默认配置换成硅基流动）
LEGACY_LLM_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
LEGACY_EMBEDDING_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"

DEFAULT_AGENTS = [
    {
        "agent_key": "agent1",
        "agent_name": "文档预处理 Agent",
        "description": (
            "离线执行。上传文件后自动触发，负责多源文件解析、文本清洗、LangChain 切片、"
            "调用 LLM 打元标签（来源类型 / 商品款号 / 内容分类），并写入 Qdrant 向量库。"
        ),
        "llm_url": DEFAULT_LLM_URL,
        "llm_model": DEFAULT_LLM_MODEL,
        "embedding_url": DEFAULT_EMBEDDING_URL,
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
    },
    {
        "agent_key": "agent2",
        "agent_name": "知识抽取 Agent",
        "description": (
            "离线执行，与文档预处理同步运行。读取清洗后的文本，抽取服装领域实体与关系三元组，"
            "写入 Neo4j 知识图谱，供问答时做事实约束。"
        ),
        "llm_url": DEFAULT_LLM_URL,
        "llm_model": DEFAULT_LLM_MODEL,
        "embedding_url": DEFAULT_EMBEDDING_URL,
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
    },
    {
        "agent_key": "agent3",
        "agent_name": "问答推理 Agent",
        "description": (
            "在线执行。用户提问后并行查询 Neo4j 图谱与 Qdrant 混合检索（稠密 + 稀疏 RRF 融合 + 标签过滤），"
            "组装强约束 Prompt，通过 SSE 流式返回答案。"
        ),
        "llm_url": DEFAULT_LLM_URL,
        "llm_model": DEFAULT_LLM_MODEL,
        "embedding_url": DEFAULT_EMBEDDING_URL,
        "embedding_model": DEFAULT_EMBEDDING_MODEL,
    },
]

# 演示商品数据：既用于管理端"导入商品数据"，也用于答辩时展示图谱与向量检索效果
DEMO_GOODS = [
    {
        "goods_no": "FY2026-001",
        "name": "轻暖羊毛混纺大衣",
        "fabric": "面料成分为 70% 羊毛、25% 聚酯纤维、5% 羊绒，里布为 100% 聚酯纤维。",
        "sizes": "S、M、L、XL",
        "colors": "燕麦色、深灰色、黑色",
        "care": "建议干洗，不可漂白，低温熨烫，悬挂存放避免重压。",
        "after_sale": "支持 7 天无理由退换，非质量问题运费由买家承担；出现开线、掉扣等质量问题支持 30 天内免费维修。",
        "activity": "新品上市期间，购买任意大衣赠送同色系防尘袋一个。",
        "report_no": "JC2026-WL-0188",
    },
    {
        "goods_no": "FY2026-002",
        "name": "凉感冰丝短袖衬衫",
        "fabric": "面料成分为 88% 锦纶、12% 氨纶，具有凉感与四面弹性能。",
        "sizes": "S、M、L、XL、XXL",
        "colors": "雾蓝色、米白色、浅灰色",
        "care": "可机洗，建议使用洗衣袋，水温不超过 30 摄氏度，禁止烘干与高温熨烫。",
        "after_sale": "支持 7 天无理由退换；洗涤后出现严重缩水可凭订单申请质检。",
        "activity": "第二件半价，活动截止到本月底。",
        "report_no": "JC2026-LG-0203",
    },
    {
        "goods_no": "FY2026-003",
        "name": "高腰直筒牛仔裤",
        "fabric": "面料成分为 98% 棉、2% 氨纶，采用环保水洗工艺。",
        "sizes": "25、26、27、28、29、30",
        "colors": "浅蓝、深蓝、复古黑",
        "care": "建议翻面冷水手洗，避免暴晒，首次洗涤可能有轻微浮色属正常现象。",
        "after_sale": "支持 7 天无理由退换；裤长可提供一次免费修改服务。",
        "activity": "会员下单立减 20 元。",
        "report_no": "JC2026-NZ-0311",
    },
]


# 演示用普通用户：客户端登录页会自动填入这组账号密码，点击即可登录
DEMO_USER = {
    "username": "demo",
    "password": "123456",
    "display_name": "演示用户",
}


def init_db() -> None:
    """建表 + 幂等写入默认数据（可重复执行）。"""
    Base.metadata.create_all(bind=engine)
    _ensure_new_columns()

    with session_scope() as db:
        # 1. 默认管理员
        admin = db.query(Admin).filter(Admin.username == settings.ADMIN_USERNAME).first()
        if not admin:
            db.add(Admin(
                username=settings.ADMIN_USERNAME,
                password_hash=***(settings.ADMIN_PASSWORD),
            ))
            print(f"[MySQL] 已创建默认管理员：{settings.ADMIN_USERNAME}")

        # 2. 三个 Agent 的默认配置（只补缺失项，不覆盖管理员已修改的配置）
        for item in DEFAULT_AGENTS:
            exists = db.query(AgentConfig).filter(AgentConfig.agent_key == item["agent_key"]).first()
            if not exists:
                db.add(AgentConfig(**item))
                print(f"[MySQL] 已写入默认配置：{item['agent_key']}")

        # 2.1 一次性迁移：把旧版本默认的 DashScope 地址替换为硅基流动地址。
        #     只在「接口地址仍等于旧默认值」时替换，不会覆盖管理员手工填过的配置；
        #     密钥字段保持原样，不需要重新填写（仍需填写硅基流动自己的 ApiKey）。
        migrated = 0
        for cfg in db.query(AgentConfig).all():
            if (cfg.llm_url or "").strip() == LEGACY_LLM_URL:
                cfg.llm_url = DEFAULT_LLM_URL
                cfg.llm_model = DEFAULT_LLM_MODEL
                migrated += 1
            if (cfg.embedding_url or "").strip() == LEGACY_EMBEDDING_URL:
                cfg.embedding_url = DEFAULT_EMBEDDING_URL
                cfg.embedding_model = DEFAULT_EMBEDDING_MODEL
                migrated += 1
        if migrated:
            print(f"[MySQL] 已将 {migrated} 处旧版默认接口地址迁移为硅基流动")

        # 3. 演示商品数据
        if db.query(Goods).count() == 0:
            for g in DEMO_GOODS:
                db.add(Goods(**g))
            print("[MySQL] 已写入演示商品数据")

        # 4. 演示用普通用户：客户端登录页预填 账号/密码，一键登录
        demo = db.query(UserAccount).filter(UserAccount.username == DEMO_USER["username"]).first()
        if not demo:
            db.add(UserAccount(
                username=DEMO_USER["username"],
                password_hash=***(DEMO_USER["password"]),
                display_name=DEMO_USER["display_name"],
            ))
            print(f"[MySQL] 已创建演示用户：{DEMO_USER['username']}")

    print("[MySQL] 数据表初始化完成")


def _ensure_new_columns() -> None:
    """
    轻量级表结构迁移：
    create_all 只建新表，不会给已存在的表补字段；这里按需 ALTER TABLE，
    保证老库升级到新版本时，新增的用户/日志/召回字段可以直接使用。
    """
    from sqlalchemy import inspect

    plans = {
        "kb_files": [
            ("chunk_strategy", "VARCHAR(20) DEFAULT 'semantic'"),
            ("clean_stats", "TEXT NULL"),
            ("recall_status", "VARCHAR(20) DEFAULT 'pending'"),
            ("recall_score", "INT DEFAULT 0"),
            ("recall_detail", "TEXT NULL"),
        ],
        "chat_history": [
            ("user_id", "BIGINT NULL"),
            ("username", "VARCHAR(50) NULL"),
        ],
    }
    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
        with engine.begin() as conn:
            for table, columns in plans.items():
                if table not in existing_tables:
                    continue
                existing = {c["name"] for c in inspector.get_columns(table)}
                for name, ddl in columns:
                    if name in existing:
                        continue
                    conn.execute(text(f"ALTER TABLE `{table}` ADD COLUMN `{name}` {ddl}"))
                    print(f"[MySQL] 已补充字段：{table}.{name}")
    except Exception as exc:  # noqa: BLE001
        # 迁移失败不阻断启动：新表已由 create_all 创建，旧表只是缺少可选项
        print(f"[MySQL] 字段迁移跳过：{exc}")


def get_agent_config(db, agent_key: str) -> AgentConfig:
    """按 key 获取 Agent 配置，不存在则回退到默认值（保证接口不会 500）。"""
    cfg = db.query(AgentConfig).filter(AgentConfig.agent_key == agent_key).first()
    if cfg:
        return cfg
    default = next((x for x in DEFAULT_AGENTS if x["agent_key"] == agent_key), DEFAULT_AGENTS[0])
    return AgentConfig(**default)
