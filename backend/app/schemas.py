# -*- coding: utf-8 -*-
"""
接口出入参模型（Pydantic）
"""
from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """管理员登录入参。"""
    username: str = Field(default="", max_length=50)
    password: str = Field(default="", max_length=100)


class UserLoginRequest(BaseModel):
    """普通用户登录入参（演示环境由登录页自动预填）。"""
    username: str = Field(default="", max_length=50)
    password: str = Field(default="", max_length=100)


class AgentConfigUpdate(BaseModel):
    """Agent 配置更新入参；api_key 为空表示保持原值不变。"""
    llm_url: Optional[str] = None
    llm_api_key: ***[str] = None
    llm_model: Optional[str] = None
    embedding_url: Optional[str] = None
    embedding_api_key: ***[str] = None
    embedding_model: Optional[str] = None


class ChatRequest(BaseModel):
    """流式问答入参。"""
    question: str = Field(default="", max_length=500)
    session_id: Optional[str] = Field(default=None, max_length=64)


class HistorySaveRequest(BaseModel):
    """对话历史保存入参。"""
    session_id: str = Field(..., max_length=64)
    role: str = Field(default="user", max_length=10)
    content: str = Field(default="", max_length=20000)
    token: ***[str] = Field(default=None, max_length=2000)
