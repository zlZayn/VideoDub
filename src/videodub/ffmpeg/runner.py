"""FFmpeg 命令执行 — 统一 subprocess 入口

所有模块不得直接调用 subprocess 执行 ffmpeg，一律走本模块。
支持命令回显（--print-ffmpeg 用）。
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from videodub.utils.logger import log, log_error

# 为 True 时每条 ffmpeg 命令打印完整参数（CLI --print-ffmpeg 设置）
echo_commands: bool = False


def set_command_echo(enabled: bool) -> None:
    """开关 ffmpeg 命令回显"""
    global echo_commands
    echo_commands = enabled


def ensure_ffmpeg_available() -> None:
    """检查 ffmpeg 是否在系统 PATH 中，不存在则退出"""
    if not shutil.which("ffmpeg"):
        log_error("未找到 ffmpeg，请先安装 FFmpeg 并加入系统 PATH")
        sys.exit(1)


def run_ffmpeg_command(command_arguments: list[str], step_label: str = "") -> None:
    """执行 FFmpeg 命令，失败时打印错误并退出

    Args:
        command_arguments: 完整的命令参数列表（不含 ffmpeg 本身）
        step_label: 当前步骤的人类可读描述，用于日志输出
    """
    if step_label:
        log("FFmpeg", step_label)
    if echo_commands:
        log("FFmpeg", "命令: " + " ".join(["ffmpeg", *command_arguments]))
    result = subprocess.run(["ffmpeg", *command_arguments], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        log_error(f"FFmpeg 执行失败: {' '.join(command_arguments[:4])}...")
        print(result.stderr[-800:])
        sys.exit(1)