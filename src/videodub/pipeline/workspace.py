"""工作目录 — output 旁 .videodub/run-<ts>/ 管理临时产物与报告

- 重产物（asr/tts/align/mix）默认清理，根目录 JSON 产物（报告/快照/计划）始终保留
- keep_temp=True 保留全部
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from videodub.utils.logger import log


class Workspace:
    """一次运行的产物目录"""

    _HEAVY_SUBDIRS = ("asr", "tts", "align", "mix")

    def __init__(self, root: Path, keep: bool = False) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.keep = keep

    def dir(self, name: str) -> Path:
        """获取（并创建）子目录"""
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def file(self, group: str, name: str) -> Path:
        """获取（并创建）分组文件路径"""
        return self.dir(group) / name

    def write_artifact(self, name: str, data: dict | list) -> Path:
        """把结构化产物写入根目录 JSON"""
        path = self.root / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def cleanup(self) -> None:
        """清理重产物目录；keep=True 时什么都不删"""
        if self.keep:
            return
        for name in self._HEAVY_SUBDIRS:
            shutil.rmtree(self.root / name, ignore_errors=True)
        log("工作目录", f"已清理重产物，保留: {self.root}")


def create_workspace(output_path: str, keep_temp: bool) -> Workspace:
    """按输出文件位置创建运行目录：<输出同目录>/.videodub/run-<时间戳>"""
    output = Path(output_path)
    base = output.parent / ".videodub"
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    root = base / f"run-{timestamp}"
    return Workspace(root, keep=keep_temp)