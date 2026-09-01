"""统一日志输出

格式: [阶段] [时间] 内容
所有模块统一使用本工具输出，避免格式混乱。
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from datetime import datetime


def _current_time() -> str:
    """获取当前时间字符串 HH:MM:SS"""
    return datetime.now().strftime("%H:%M:%S")


def log(stage: str, message: str) -> None:
    """统一日志输出

    Args:
        stage: 阶段标签（如 ASR、TTS、对齐、合成）
        message: 日志内容
    """
    print(f"[{stage}] [{_current_time()}] {message}")


def log_stage_header(stage: str, description: str) -> None:
    """输出阶段标题（分隔线 + 阶段名 + 描述）"""
    print(f"\n{'='*50}")
    print(f"  [{stage}] [{_current_time()}] {description}")
    print(f"{'='*50}")


def log_progress(current: int, total: int, message: str = "") -> None:
    """输出进度信息"""
    progress = f"[{current}/{total}]"
    if message:
        print(f"[进度] [{_current_time()}] {progress} {message}")
    else:
        print(f"[进度] [{_current_time()}] {progress}")


def log_error(message: str) -> None:
    """输出错误信息到 stderr"""
    print(f"[错误] [{_current_time()}] {message}", file=sys.stderr)


def log_warning(message: str) -> None:
    """输出警告信息"""
    print(f"[警告] [{_current_time()}] {message}")


def log_success(message: str) -> None:
    """输出成功信息"""
    print(f"[完成] [{_current_time()}] {message}")


def log_elapsed(stage: str, start_time: float, message: str = "") -> None:
    """输出阶段用时"""
    elapsed = time.time() - start_time
    if elapsed < 60:
        time_str = f"{elapsed:.1f}秒"
    else:
        minutes = int(elapsed // 60)
        seconds = elapsed % 60
        time_str = f"{minutes}分{seconds:.1f}秒"
    suffix = f" {message}" if message else ""
    print(f"[{stage}] [{_current_time()}] 用时 {time_str}{suffix}")


@contextmanager
def timed_stage(stage: str, description: str):
    """计时阶段上下文管理器：进入输出标题，退出输出用时"""
    log_stage_header(stage, description)
    start_time = time.time()
    try:
        yield
    finally:
        log_elapsed(stage, start_time)