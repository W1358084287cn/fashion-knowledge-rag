# -*- coding: utf-8 -*-
"""
LLM 调用封装（LangChain + OpenAI 兼容接口）
------------------------------------------------------------
- 统一把「完整接口地址」规范化为 base_url（去掉 /chat/completions）
- Agent1 / Agent2 的 JSON 结果做健壮解析（兼容 ```json 代码块）
- Agent3 使用 LangChain 的 ChatPromptTemplate + ChatOpenAI 做流式输出
- 所有异常转换为带中文提示的 LLMError，避免前端看到原始堆栈
"""
import json
import re
from typing import Any, AsyncIterator, Dict, Optional

from langchain_core.messages import AIMessageChunk
from langchain_openai import ChatOpenAI

from ..config import settings
from ..prompts import AGENT3_CHAT_PROMPT


class LLMError(Exception):
    """大模型调用异常（提示信息可直接展示给用户）。"""


def normalize_llm_base_url(url: str) -> str:
    """
    把用户填写的地址统一成 OpenAI SDK 需要的 base_url。
    例如：
      https://api.siliconflow.cn/v1/chat/completions
      -> https://api.siliconflow.cn/v1
    """
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    for suffix in ("/chat/completions", "/completions"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url.rstrip("/")


def _build_llm(cfg, streaming: bool = False, temperature: float = 0.1, max_tokens: int = 800) -> ChatOpenAI:
    """根据 Agent 配置动态创建 LangChain ChatOpenAI 实例（支持热更新）。"""
    api_key = (getattr(cfg, "llm_api_key", "") or "").strip()
    base_url = normalize_llm_base_url(getattr(cfg, "llm_url", ""))
    model = (getattr(cfg, "llm_model", "") or "Qwen/Qwen2.5-7B-Instruct").strip()

    if not api_key:
        raise LLMError("尚未配置 LLM ApiKey，请先在管理端「Agent 模型配置」中填写并保存")
    if not base_url:
        raise LLMError("尚未配置 LLM 接口 URL，请先在管理端填写并保存")

    try:
        return ChatOpenAI(
            model=model,
            api_key=***,
            base_url=base_url,
            temperature=temperature,
            max_tokens=***,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=1,
            streaming=streaming,
        )
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"LLM 初始化失败：{exc}") from exc


def _friendly_error(exc: Exception) -> str:
    """把底层异常翻译成用户能看懂的中文提示。"""
    msg = str(exc)
    lower = msg.lower()
    if "401" in msg or "invalid api key" in lower or "unauthorized" in lower:
        return "LLM 密钥无效，请在管理端重新配置 ApiKey"
    if "404" in msg:
        return "LLM 接口地址或模型名不正确，请检查配置"
    if "timeout" in lower or "timed out" in lower:
        return "LLM 响应超时，请稍后重试或检查网络"
    if "connection" in lower or "connect" in lower:
        return "无法连接 LLM 服务，请检查接口地址与服务器网络"
    if "429" in msg or "rate limit" in lower:
        return "LLM 调用频率超限，请稍后重试"
    return f"LLM 调用失败：{msg[:200]}"


def chat_text_sync(
    cfg,
    prompt: str,
    temperature: float = 0.0,
    max_tokens: int = 800,
) -> str:
    """
    同步调用 LLM 并返回纯文本。
    离线 Agent（打标签、抽三元组）在后台线程中使用此方法。
    """
    llm = _build_llm(cfg, streaming=False, temperature=temperature, max_tokens=max_tokens)
    try:
        result = llm.invoke(prompt)
        content = result.content if hasattr(result, "content") else str(result)
        return str(content).strip()
    except Exception as exc:  # noqa: BLE001
        raise LLMError(_friendly_error(exc)) from exc


def _clean_json_text(text: str) -> str:
    """去掉 ```json 代码块、前后说明文字，尽量还原纯 JSON。"""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出中解析 JSON 对象，失败返回 None（由调用方走兜底逻辑）。"""
    cleaned = _clean_json_text(text)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    # 兜底：截取第一个 { 到最后一个 } 之间的内容
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            value = json.loads(cleaned[start:end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def parse_json_array(text: str):
    """从模型输出中解析 JSON 数组，失败返回空列表（表示没有可抽取内容）。"""
    cleaned = _clean_json_text(text)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start != -1 and end > start:
        try:
            value = json.loads(cleaned[start:end + 1])
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []
    return []


async def stream_answer(cfg, doc_chunks: str, kg_triples: str, question: str) -> AsyncIterator[str]:
    """
    Agent3 流式问答：
    LangChain 提示模板 + ChatOpenAI 流式输出，逐 token 产出文本。
    """
    llm = _build_llm(cfg, streaming=True, temperature=0.1, max_tokens=800)
    chain = AGENT3_CHAT_PROMPT | llm
    inputs = {
        "doc_chunks": doc_chunks or "（无）",
        "kg_triples": kg_triples or "（无）",
        "user_question": question,
    }
    try:
        async for chunk in chain.astream(inputs):
            content = chunk.content if isinstance(chunk, AIMessageChunk) or hasattr(chunk, "content") else str(chunk)
            if content:
                yield str(content)
    except Exception as exc:  # noqa: BLE001
        raise LLMError(_friendly_error(exc)) from exc
