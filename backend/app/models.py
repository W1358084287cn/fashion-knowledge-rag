# -*- coding: utf-8 -*-
"""
MySQL 数据表模型（SQLAlchemy ORM）
------------------------------------------------------------
包含：管理员、知识库文件、Agent 配置、对话历史、商品结构化数据。
建表语句与 backend/sql/init.sql 保持一致，二者任选其一都能完成初始化。
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, Integer, String, Text, Index
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Admin(Base):
    """管理员账号表：固定账号 admin / 密码 123456（初始化时写入哈希值）。"""
    __tablename__ = "admins"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, comment="管理员账号")
    password_hash = ***(String(128), nullable=False, comment="SHA256 密码摘要")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")


class KbFile(Base):
    """知识库文件表：记录上传文件与离线处理状态。"""
    __tablename__ = "kb_files"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    file_name = Column(String(255), nullable=False, comment="原始文件名")
    stored_name = Column(String(255), nullable=False, comment="磁盘存储文件名")
    file_path = Column(String(500), nullable=False, comment="文件绝对路径")
    file_type = Column(String(20), nullable=False, comment="扩展名")
    source_type = Column(String(20), default="文档", comment="来源类型：文档/聊天记录/表格数据")
    file_size = Column(BigInteger, default=0, comment="文件大小（字节）")
    status = Column(String(20), default="pending", comment="pending/parsing/chunking/tagging/embedding/kg/done/failed")
    progress = Column(Integer, default=0, comment="处理进度 0~100")
    chunk_count = Column(Integer, default=0, comment="切片数量")
    triple_count = Column(Integer, default=0, comment="知识图谱三元组数量")
    error_msg = Column(Text, nullable=True, comment="失败原因")
    # ---------- 新增：切片策略与自动清洗 / 召回测试 ----------
    chunk_strategy = Column(String(20), default="semantic", comment="切片策略：semantic/paragraph/chapter")
    clean_stats = Column(Text, nullable=True, comment="自动清洗统计（JSON 字符串）")
    recall_status = Column(String(20), default="pending", comment="召回测试：pending/running/passed/failed")
    recall_score = Column(Integer, default=0, comment="召回准确度 0~100")
    recall_detail = Column(Text, nullable=True, comment="召回测试明细（JSON 字符串）")
    created_at = Column(DateTime, default=datetime.now, comment="上传时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")


class AgentConfig(Base):
    """Agent 模型配置表：管理端可热更新，密钥只保存在后端。"""
    __tablename__ = "agent_configs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    agent_key = Column(String(30), unique=True, nullable=False, comment="agent1/agent2/agent3")
    agent_name = Column(String(100), nullable=False, comment="Agent 名称")
    description = Column(Text, nullable=False, comment="功能说明")
    llm_url = Column(String(500), default="", comment="LLM 接口地址（OpenAI 兼容）")
    llm_api_key = ***(String(500), default="", comment="LLM 密钥（仅后端使用）")
    llm_model = Column(String(100), default="Qwen/Qwen2.5-7B-Instruct", comment="LLM 模型名")
    embedding_url = Column(String(500), default="", comment="Embedding 接口地址")
    embedding_api_key = ***(String(500), default="", comment="Embedding 密钥（仅后端使用）")
    embedding_model = Column(String(100), default="BAAI/bge-m3", comment="Embedding 模型名")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")


class ChatHistory(Base):
    """对话历史表：通过 user_type 区分管理员对话与普通用户对话。"""
    __tablename__ = "chat_history"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String(64), nullable=False, comment="会话ID")
    user_type = Column(String(10), default="user", comment="admin/user")
    role = Column(String(10), nullable=False, comment="user/assistant")
    content = Column(Text, nullable=False, comment="消息内容")
    # 新增：记录提问用户，管理端可按用户查看提问记录
    user_id = Column(BigInteger, nullable=True, comment="用户ID（普通用户登录后写入）")
    username = Column(String(50), nullable=True, comment="用户账号（冗余存储，便于展示）")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    __table_args__ = (
        Index("idx_chat_session", "session_id"),
        Index("idx_chat_created", "created_at"),
        Index("idx_chat_user", "user_id"),
    )


class Goods(Base):
    """商品结构化数据表：用于演示"MySQL 商品数据接入知识库"。"""
    __tablename__ = "goods"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    goods_no = Column(String(50), unique=True, nullable=False, comment="商品款号")
    name = Column(String(200), nullable=False, comment="商品名称")
    fabric = Column(String(500), default="", comment="面料成分")
    sizes = Column(String(200), default="", comment="可选尺码")
    colors = Column(String(200), default="", comment="可选颜色")
    care = Column(String(500), default="", comment="保养方式")
    after_sale = Column(String(500), default="", comment="售后政策")
    activity = Column(String(500), default="", comment="活动信息")
    report_no = Column(String(100), default="", comment="检测报告编号")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")


class UserAccount(Base):
    """普通用户账号表：演示环境使用固定账号一键登录，后续可扩展注册。"""
    __tablename__ = "user_accounts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, comment="登录账号")
    password_hash = ***(String(128), nullable=False, comment="SHA256 密码摘要")
    display_name = Column(String(50), default="", comment="展示昵称")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    last_login_at = Column(DateTime, nullable=True, comment="最近登录时间")


class RetrievalLog(Base):
    """检索日志表：留存每次提问的检索命中情况与召回质量，管理端可查。"""
    __tablename__ = "retrieval_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(String(64), default="", comment="会话ID")
    user_id = Column(BigInteger, nullable=True, comment="用户ID")
    username = Column(String(50), default="", comment="用户账号")
    user_type = Column(String(10), default="user", comment="admin/user")
    question = Column(String(500), nullable=False, comment="用户提问")
    doc_count = Column(Integer, default=0, comment="命中文档片段数")
    triple_count = Column(Integer, default=0, comment="命中图谱三元组数")
    top_score = Column(Float, default=0.0, comment="最高向量相似度")
    hit = Column(Boolean, default=False, comment="是否命中知识库")
    accuracy = Column(Integer, default=0, comment="召回准确度评分 0~100")
    accuracy_level = Column(String(10), default="miss", comment="high/medium/low/miss")
    latency_ms = Column(Integer, default=0, comment="检索耗时（毫秒）")
    filters = Column(String(200), default="", comment="检索时使用的标签过滤条件")
    degraded = Column(String(200), default="", comment="降级原因")
    sources = Column(Text, nullable=True, comment="召回结果快照（JSON）")
    created_at = Column(DateTime, default=datetime.now, comment="提问时间")

    __table_args__ = (
        Index("idx_retrieval_user", "user_id"),
        Index("idx_retrieval_created", "created_at"),
    )


class OperationLog(Base):
    """操作日志表：管理员与用户的关键操作全量留存。"""
    __tablename__ = "operation_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    actor_type = Column(String(10), default="admin", comment="admin/user/system")
    actor = Column(String(50), default="", comment="操作人")
    action = Column(String(50), nullable=False, comment="操作类型")
    target = Column(String(200), default="", comment="操作对象")
    detail = Column(Text, nullable=True, comment="操作详情")
    ip = Column(String(64), default="", comment="来源 IP")
    created_at = Column(DateTime, default=datetime.now, comment="操作时间")

    __table_args__ = (
        Index("idx_op_created", "created_at"),
    )


class RecallTest(Base):
    """召回测试记录表：保存自动召回测试的每一轮结果，便于答辩展示自愈过程。"""
    __tablename__ = "recall_tests"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    file_id = Column(BigInteger, nullable=False, comment="知识库文件ID")
    strategy = Column(String(20), default="semantic", comment="本轮切片策略")
    iteration = Column(Integer, default=1, comment="第几轮测试")
    question = Column(String(500), default="", comment="自动生成的测试问题")
    hit = Column(Boolean, default=False, comment="是否召回命中")
    score = Column(Float, default=0.0, comment="最高相似度")
    doc_count = Column(Integer, default=0, comment="召回片段数")
    detail = Column(Text, nullable=True, comment="召回明细（JSON）")
    created_at = Column(DateTime, default=datetime.now, comment="测试时间")

    __table_args__ = (
        Index("idx_recall_file", "file_id"),
    )
