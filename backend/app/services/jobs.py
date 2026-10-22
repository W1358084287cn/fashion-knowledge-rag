# -*- coding: utf-8 -*-
"""
离线任务调度
------------------------------------------------------------
- 使用线程池在后台执行文件解析 / OCR / 切片 / 向量化 / 图谱抽取
- 上传接口立即返回，不阻塞问答
- 服务重启后自动续跑未完成的文件
"""
import threading
from concurrent.futures import ThreadPoolExecutor

from ..db import SessionLocal
from ..models import KbFile
from .pipeline import process_file

# 最多同时处理 2 个文件，避免本地演示机被 OCR / LLM 调用压垮
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="offline-agent")
_running: set = set()
_lock = threading.Lock()


def _run(file_id: int) -> None:
    try:
        process_file(file_id)
    except Exception as exc:  # noqa: BLE001
        # process_file 内部已做失败落库，这里只兜底打印，防止线程静默退出
        print(f"[离线任务] 文件 {file_id} 线程异常：{exc}")
    finally:
        with _lock:
            _running.discard(file_id)


# 召回测试与文件处理共用线程池，但单独记录运行状态，避免互相阻塞重复触发
_recall_running: set = set()
_recall_lock = threading.Lock()


def _run_recall(file_id: int) -> None:
    try:
        from .recall_eval import run_recall_for_existing_file
        summary = run_recall_for_existing_file(file_id)
        if summary.get("error"):
            print(f"[召回测试] 文件 {file_id} 失败：{summary['error']}")
    except Exception as exc:  # noqa: BLE001
        print(f"[召回测试] 文件 {file_id} 线程异常：{exc}")
    finally:
        with _recall_lock:
            _recall_running.discard(file_id)


def enqueue_recall(file_id: int) -> bool:
    """提交一次召回测试任务；已在测试中返回 False。"""
    with _recall_lock:
        if file_id in _recall_running:
            return False
        _recall_running.add(file_id)
    executor.submit(_run_recall, file_id)
    return True


def enqueue_file(file_id: int) -> bool:
    """
    提交离线任务。
    返回 True 表示本次成功入队；False 表示该文件已在处理中（防重复触发）。
    """
    with _lock:
        if file_id in _running:
            return False
        _running.add(file_id)
    executor.submit(_run, file_id)
    return True


def resume_unfinished() -> int:
    """服务启动时，把上次未处理完的文件重新加入队列。"""
    db = SessionLocal()
    try:
        rows = db.query(KbFile).filter(
            KbFile.status.in_(["pending", "parsing", "chunking", "tagging", "embedding", "kg"])
        ).all()
        ids = [int(r.id) for r in rows]
    finally:
        db.close()

    count = 0
    for file_id in ids:
        if enqueue_file(file_id):
            count += 1
    if count:
        print(f"[离线任务] 已恢复 {count} 个未完成文件")
    return count
