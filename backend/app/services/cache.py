# -*- coding: utf-8 -*-
"""
高频问题缓存
------------------------------------------------------------
- 内存 TTL + LRU：命中率优先，过期自动清除
- key 由「归一化问题 + Agent3 配置版本」组成，配置热更新后旧缓存自动失效
- 只缓存非空且长度合理的问答结果
"""
import threading
import time
from collections import OrderedDict
from typing import Optional


class TTLCache:
    """简单的线程安全 TTL/LRU 缓存（演示环境足够，生产可换 Redis）。"""

    def __init__(self, max_size: int = 200, ttl: int = 600):
        self.max_size = max_size
        self.ttl = ttl
        self._data: "OrderedDict[str, tuple]" = OrderedDict()  # key -> (expire_at, value)
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            expire_at, value = item
            if time.time() > expire_at:
                self._data.pop(key, None)
                return None
            # LRU：命中后移到队尾
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: str) -> None:
        if not value:
            return
        with self._lock:
            self._data[key] = (time.time() + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


# 全局问答缓存实例：Agent3 使用，Agent 配置更新时由管理端接口清空
from ..config import settings as _settings  # noqa: E402

answer_cache = TTLCache(max_size=_settings.CACHE_MAX_SIZE, ttl=_settings.CACHE_TTL_SECONDS)
