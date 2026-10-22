# -*- coding: utf-8 -*-
"""
文本通用工具
------------------------------------------------------------
职责：
1. 文本清洗（过滤脏数据、页码、URL、控制字符、重复空行）
2. 商品款号识别
3. 内容分类识别（面料 / 尺码 / 售后 / 保养 / 活动）
4. 问题关键词提取（jieba 分词 + 停用词）
5. 稀疏向量构造（本地词频哈希，用于 Qdrant 关键词检索）
"""
import hashlib
import html
import re
import zlib
from typing import Dict, List, Tuple

import jieba

# 中文停用词（精简版，覆盖客服场景高频无意义词）
STOPWORDS = {
    "的", "了", "和", "是", "在", "有", "我", "你", "他", "她", "它", "们",
    "这", "那", "这个", "那个", "请问", "一下", "可以", "能否", "是否", "怎么",
    "如何", "什么", "为什么", "哪些", "多少", "吗", "呢", "啊", "呀", "吧",
    "就", "都", "也", "还", "又", "很", "非常", "比较", "一个", "一些",
    "需要", "想", "要", "会", "能", "把", "被", "对", "与", "及", "或",
    "以及", "如果", "但是", "然后", "所以", "因为", "关于", "进行", "通过",
    "您好", "你好", "谢谢", "麻烦", "咨询", "问下", "想问", "了解",
}

# 内容分类关键词映射：用于问题侧标签过滤 & 打标签失败时的兜底
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "面料": ["面料", "材质", "成分", "羊毛", "羊绒", "棉", "聚酯", "氨纶", "锦纶",
             "透气", "弹力", "凉感", "克重", "起球", "里布", "水洗", "环保"],
    "尺码": ["尺码", "码数", "尺寸", "身高", "体重", "大小", "偏大", "偏小",
             "s码", "m码", "l码", "xl", "xxl", "肩宽", "胸围", "腰围", "裤长"],
    "售后": ["售后", "退换", "退货", "换货", "维修", "质量", "开线", "掉扣",
             "运费", "退款", "保修", "无理由", "质检"],
    "保养": ["保养", "清洗", "洗涤", "机洗", "手洗", "干洗", "熨烫", "晾晒",
             "缩水", "褪色", "存放", "收纳", "烘干", "漂白"],
    "活动": ["活动", "优惠", "折扣", "赠品", "满减", "半价", "会员", "促销",
             "截止", "下单", "立减", "赠送"],
}

# 商品款号正则：支持 FY2026-001 / A12345 / X-2026-01 等常见写法
GOODS_NO_PATTERN = re.compile(r"[A-Za-z]{1,10}[-_]?\d{2,}[A-Za-z0-9_-]*")

# 需要过滤的 URL / 邮箱 / 控制字符
URL_PATTERN = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"\S+@\S+\.\S+")
CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MULTI_BLANK_PATTERN = re.compile(r"\n{3,}")
MULTI_PUNCT_PATTERN = re.compile(r"([，。！？；：、,.!?;:])\1{2,}")
PAGE_NUMBER_PATTERN = re.compile(
    r"^\s*(?:[-—\s]*\d{1,4}[-—\s]*"
    r"|第\s*\d{1,4}\s*页(?:\s*(?:/|共)\s*\d{1,4}\s*页)?"
    r"|Page\s*\d{1,4}(?:\s*of\s*\d{1,4})?)\s*$",
    re.IGNORECASE,
)


def clean_text(raw: str) -> str:
    """
    对原始文本做统一清洗（兼容旧调用）：
    返回清洗后的文本，详细统计请使用 clean_text_with_stats。
    """
    return clean_text_with_stats(raw)[0]


def clean_text_with_stats(raw: str) -> Tuple[str, Dict[str, object]]:
    """
    自动清洗原始脏数据，并返回清洗统计（管理端展示“程序自动清洗了多少脏数据”）。

    清洗项：
    - HTML 反转义、去标签 / script / style
    - 去 URL、邮箱、控制字符
    - 去页码行、分隔线
    - 去连续重复行、压缩空行、重复标点

    除数量统计外，还会保留被剔除内容的示例（samples），
    管理端可直接展示“到底清洗掉了什么”，避免只有数字看不出效果。
    """
    stats: Dict[str, object] = {
        "original_chars": len(str(raw or "")),
        "cleaned_chars": 0,
        "removed_chars": 0,
        "url_count": 0,
        "email_count": 0,
        "control_count": 0,
        "page_number_lines": 0,
        "separator_lines": 0,
        "duplicate_lines": 0,
        "blank_lines": 0,
        # 每类最多保留 3 条示例，便于前端展示“清洗了什么”
        "samples": {k: [] for k in (
            "url", "email", "page_number", "separator", "duplicate", "html"
        )},
    }
    samples: Dict[str, List[str]] = stats["samples"]  # type: ignore[assignment]

    def _keep(key: str, value: str, limit: int = 120) -> None:
        """记录被剔除内容的示例（去重、最多 3 条）。"""
        value = (value or "").strip().replace("\n", " ")
        if not value:
            return
        bucket = samples[key]
        if len(bucket) < 3 and value[:limit] not in bucket:
            bucket.append(value[:limit])

    if not raw:
        return "", stats
    text = html.unescape(str(raw))
    html_hits = re.findall(r"<(script|style|div|p|br|table|td|a)[^>]*>", text, flags=re.IGNORECASE)
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    for tag in html_hits[:3]:
        _keep("html", f"<{tag}> 标签")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = text.replace("\u200b", "").replace("\ufeff", "")

    stats["control_count"] = len(CONTROL_PATTERN.findall(text))
    for hit in URL_PATTERN.findall(text)[:3]:
        _keep("url", str(hit))
    for hit in EMAIL_PATTERN.findall(text)[:3]:
        _keep("email", str(hit))
    stats["url_count"] = len(URL_PATTERN.findall(text))
    stats["email_count"] = len(EMAIL_PATTERN.findall(text))
    text = CONTROL_PATTERN.sub("", text)
    text = URL_PATTERN.sub(" ", text)
    text = EMAIL_PATTERN.sub(" ", text)

    lines: List[str] = []
    prev = None
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line:
            stats["blank_lines"] += 1
            lines.append("")
            continue
        # 过滤纯页码 / 分隔线
        if PAGE_NUMBER_PATTERN.match(line):
            stats["page_number_lines"] += 1
            _keep("page_number", line)
            continue
        if re.fullmatch(r"[-=_*·—\s]{3,}", line):
            stats["separator_lines"] += 1
            _keep("separator", line)
            continue
        # 过滤连续完全重复的行（表格转文本时常见）
        if line == prev:
            stats["duplicate_lines"] += 1
            _keep("duplicate", line)
            continue
        lines.append(line)
        prev = line

    text = "\n".join(lines)
    text = MULTI_BLANK_PATTERN.sub("\n\n", text)
    text = MULTI_PUNCT_PATTERN.sub(r"\1", text)
    text = text.strip()
    stats["cleaned_chars"] = len(text)
    stats["removed_chars"] = max(0, stats["original_chars"] - stats["cleaned_chars"])
    return text, stats


def detect_goods_no(text: str) -> str:
    """从文本中提取第一个商品款号，没有则返回空字符串。"""
    match = GOODS_NO_PATTERN.search(text or "")
    return match.group(0).upper() if match else ""


def detect_category(text: str) -> str:
    """
    基于关键词命中次数推断内容分类，用于：
    - 问题侧的 Qdrant payload 标签过滤
    - LLM 打标签失败时的兜底
    """
    lower = (text or "").lower()
    scores = {cat: 0 for cat in CATEGORY_KEYWORDS}
    for cat, words in CATEGORY_KEYWORDS.items():
        for w in words:
            if w.lower() in lower:
                scores[cat] += 1
    best_cat, best_score = max(scores.items(), key=lambda x: x[1])
    return best_cat if best_score > 0 else ""


def extract_keywords(text: str, limit: int = 12) -> List[str]:
    """
    问题关键词提取：jieba 搜索模式分词，去掉停用词与单字，保留款号。
    返回结果用于 Neo4j 实体匹配与稀疏向量构造。
    """
    text = (text or "").strip()
    if not text:
        return []

    keywords: List[str] = []
    goods_no = detect_goods_no(text)
    if goods_no:
        keywords.append(goods_no)

    for token in jieba.lcut_for_search(text.lower()):
        token = ***()
        if len(token) < 2:
            continue
        if token in STOPWORDS:
            continue
        if re.fullmatch(r"[\W_]+", token):
            continue
        if token not in keywords:
            keywords.append(token)

    # 分类词优先（例如“售后”是图谱实体的重要线索）
    for cat in CATEGORY_KEYWORDS:
        if cat in text and cat not in keywords:
            keywords.insert(0, cat)

    return keywords[:limit]


def _sparse_tokens(text: str) -> List[str]:
    """稀疏向量分词：中文用 jieba，英文数字保留完整词。"""
    tokens: List[str] = []
    for token in jieba.lcut((text or "").lower()):
        token = ***()
        if len(token) < 1:
            continue
        if token in STOPWORDS:
            continue
        if re.fullmatch(r"[\W_]+", token):
            continue
        tokens.append(token)
    return tokens


def build_sparse_vector(text: str) -> Tuple[List[int], List[float]]:
    """
    构造稀疏向量（Term Frequency 加权 + 稳定哈希映射）。
    不依赖额外模型，部署简单；与稠密向量在 Qdrant 中混合检索，再做 RRF 融合。
    返回：indices（去重后的哈希下标）、values（对应权重）。
    """
    tokens = ***(text)
    if not tokens:
        return [], []

    tf: Dict[str, int] = {}
    for token in tokens:
        tf[token] = tf.get(token, 0) + 1

    index_weight: Dict[int, float] = {}
    for token, count in tf.items():
        # 用 crc32 生成稳定下标，避免 Python hash 随进程变化
        idx = zlib.crc32(token.encode("utf-8")) % 2000000000 + 1
        # 次线性词频：抑制长文本中高频词的权重
        weight = 1.0 + (count ** 0.5)
        index_weight[idx] = max(index_weight.get(idx, 0.0), weight)

    indices = list(index_weight.keys())
    values = [index_weight[i] for i in indices]
    return indices, values


def text_fingerprint(text: str) -> str:
    """文本指纹：用于对话缓存 key、切片去重。"""
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def normalize_question(question: str) -> str:
    """问题归一化：去首尾空白、压缩空格、限制长度，防止超长 Prompt 注入。"""
    q = re.sub(r"\s+", " ", (question or "").strip())
    return q[:200]
