# -*- coding: utf-8 -*-
"""
文本切片策略（3 种可选）
------------------------------------------------------------
1. semantic  语义切分：按段落 / 句号 / 问号等自然语义边界递归切分（默认）
2. paragraph 段落切分：以空行分段，再把相邻段落合并到目标长度
3. chapter   章节切分：识别“第X章 / 一、 / 1.1 / Markdown 标题”等章节标题，
              以章节为最小单位，超长章节再按段落 / 句子二次切分

所有策略最终都输出 10~chunk_size 左右的文本片段，并限制单文件最大片段数，
避免超大文件拖垮演示环境。
"""
import re
from typing import List

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..config import settings

# 策略标识 -> 中文名称（管理端展示）
STRATEGY_LABELS = {
    "semantic": "语义切分",
    "paragraph": "段落切分",
    "chapter": "章节切分",
}
STRATEGIES = ["semantic", "paragraph", "chapter"]
DEFAULT_STRATEGY = "semantic"

# 章节标题：第X章/节/篇/部分、一、、1.、1.1、Markdown #、【标题】
CHAPTER_PATTERN = re.compile(
    r"^\s*(?:#{1,6}\s+\S|"
    r"第[一二三四五六七八九十百千\d]+[章节篇部]\s*\S*|"
    r"[一二三四五六七八九十]+[、.．]\s*\S+|"
    r"\d+(?:\.\d+)*[、.．]\s*\S+|"
    r"【.+?】\s*$)"
)


def normalize_strategy(strategy: str) -> str:
    """校验策略标识，非法值回退为默认策略。"""
    value = (strategy or "").strip().lower()
    return value if value in STRATEGY_LABELS else DEFAULT_STRATEGY


def _semantic_split(text: str, chunk_size: int, overlap: int) -> List[str]:
    """语义切分：优先在段落、句号等自然边界断开。"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        length_function=len,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
    )
    return [c.strip() for c in splitter.split_text(text) if c.strip()]


def _split_long_block(block: str, chunk_size: int, overlap: int) -> List[str]:
    """超长段落 / 章节二次切分：先按句子，再由语义切分兜底。"""
    if len(block) <= chunk_size:
        return [block]
    sentences = re.split(r"(?<=[。！？；\n])", block)
    pieces: List[str] = []
    buffer = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(buffer) + len(sentence) <= chunk_size:
            buffer += sentence
        else:
            if buffer.strip():
                pieces.append(buffer.strip())
            buffer = sentence
    if buffer.strip():
        pieces.append(buffer.strip())
    # 仍超长的片段交给语义切分
    result: List[str] = []
    for piece in pieces:
        if len(piece) > chunk_size:
            result.extend(_semantic_split(piece, chunk_size, overlap))
        else:
            result.append(piece)
    return result


def _paragraph_units(text: str) -> List[str]:
    """把文本按空行拆成段落；若没有空行，则按单行拆。"""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) <= 1:
        blocks = [line.strip() for line in text.splitlines() if line.strip()]
    return blocks or [text.strip()]


def _merge_units(units: List[str], chunk_size: int, overlap: int) -> List[str]:
    """把段落合并为目标长度的切片，并保留一小段重叠上下文。"""
    chunks: List[str] = []
    buffer = ""
    for unit in units:
        if len(unit) > chunk_size:
            if buffer.strip():
                chunks.append(buffer.strip())
                buffer = ""
            chunks.extend(_split_long_block(unit, chunk_size, overlap))
            continue
        if not buffer:
            buffer = unit
        elif len(buffer) + len(unit) + 1 <= chunk_size:
            buffer = f"{buffer}\n{unit}"
        else:
            chunks.append(buffer.strip())
            # 重叠：保留上一片段末尾 overlap 个字符作为上下文
            tail = buffer[-overlap:] if overlap and len(buffer) > overlap else ""
            buffer = f"{tail}\n{unit}".strip()
    if buffer.strip():
        chunks.append(buffer.strip())
    return chunks


def _chapter_split(text: str, chunk_size: int, overlap: int) -> List[str]:
    """章节切分：识别章节标题，把每个章节作为一个整体，超长再二次切分。"""
    lines = text.splitlines()
    sections: List[List[str]] = []
    current: List[str] = []
    has_heading = False

    for line in lines:
        if CHAPTER_PATTERN.match(line):
            has_heading = True
            if current and any(x.strip() for x in current):
                sections.append(current)
            current = [line]
        else:
            current.append(line)
    if current and any(x.strip() for x in current):
        sections.append(current)

    # 没有任何章节标题时，回退到段落切分，保证一定能切出片段
    if not has_heading:
        return _merge_units(_paragraph_units(text), chunk_size, overlap)

    result: List[str] = []
    for section in sections:
        block = "\n".join(line for line in section if line.strip()).strip()
        if not block:
            continue
        result.extend(_split_long_block(block, chunk_size, overlap))
    return result


def split_text(text: str, strategy: str = DEFAULT_STRATEGY) -> List[str]:
    """
    统一切片入口。
    返回清洗后、长度合理的片段列表（单文件最多 MAX_CHUNKS_PER_FILE 个）。
    """
    strategy = normalize_strategy(strategy)
    chunk_size = max(100, int(settings.CHUNK_SIZE))
    overlap = max(0, min(int(settings.CHUNK_OVERLAP), chunk_size // 2))
    text = (text or "").strip()
    if not text:
        return []

    if strategy == "paragraph":
        chunks = _merge_units(_paragraph_units(text), chunk_size, overlap)
    elif strategy == "chapter":
        chunks = _chapter_split(text, chunk_size, overlap)
    else:
        chunks = _semantic_split(text, chunk_size, overlap)
        # 语义切片也可能出现超长片段，统一做一次长度兜底
        normalized: List[str] = []
        for chunk in chunks:
            normalized.extend(_split_long_block(chunk, chunk_size, overlap))
        chunks = normalized

    # 去掉过短碎片与完全重复片段，避免污染检索
    cleaned: List[str] = []
    seen = set()
    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < 10:
            continue
        key = chunk[:120]
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(chunk)
    return cleaned[: settings.MAX_CHUNKS_PER_FILE]
