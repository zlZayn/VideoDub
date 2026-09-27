"""doctor 子命令 — 检查运行环境与依赖

用法：videodub doctor
"""

from __future__ import annotations

import shutil
import sys


def build_parser(parser) -> None:
    parser.set_defaults(func=_run)


def _check(label: str, ok: bool, detail: str = "") -> bool:
    status = "OK" if ok else "失败"
    print(f"[{status}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def _import_version(name: str) -> str | None:
    """返回可导入包的版本号，导入失败返回 None"""
    try:
        module = __import__(name)
        return getattr(module, "__version__", "")
    except ImportError:
        return None


def _torch_info() -> str | None:
    """torch 版本 + CUDA 可用性，未安装返回 None"""
    try:
        import torch

        cuda = torch.cuda.is_available()
        return f"{torch.__version__} (CUDA: {'可用' if cuda else '不可用'})"
    except ImportError:
        return None


def _run(args) -> int:
    print(f"videodub doctor — Python {sys.version.split()[0]}")
    critical_failed = False

    critical_failed = not _check("Python >= 3.11", sys.version_info >= (3, 11))
    critical_failed |= not _check("ffmpeg", shutil.which("ffmpeg") is not None)
    critical_failed |= not _check("ffprobe", shutil.which("ffprobe") is not None)

    torch_version = _torch_info()
    _check("torch", torch_version is not None, torch_version or "")

    for name in (
        "funasr",
        "faster_whisper",
        "voxcpm",
        "soundfile",
        "httpx",
        "pydantic",
    ):
        version = _import_version(name)
        _check(name, version is not None, version or "")

    return 1 if critical_failed else 0
