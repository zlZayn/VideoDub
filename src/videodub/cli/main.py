"""videodub 命令行入口 — 子命令分发（argparse）"""

from __future__ import annotations

import argparse
import sys

from videodub.cli import doctor as doctor_cmd
from videodub.cli import inspect as inspect_cmd
from videodub.cli import label as label_cmd
from videodub.cli import run as run_cmd
from videodub.cli import transcribe as transcribe_cmd
from videodub.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="videodub",
        description="视频音色替换 — 本地 VoxCPM2 音色克隆 + 逐句时长对齐对口型",
    )
    parser.add_argument("--version", action="version", version=f"videodub {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="执行配音任务", description=run_cmd.__doc__)
    run_cmd.build_parser(run_parser)

    transcribe_parser = subparsers.add_parser("transcribe", help="仅语音识别输出台词 JSON")
    transcribe_cmd.build_parser(transcribe_parser)

    label_parser = subparsers.add_parser("label", help="人工校对说话人与断句")
    label_cmd.build_parser(label_parser)

    inspect_parser = subparsers.add_parser("inspect", help="探测媒体信息")
    inspect_cmd.build_parser(inspect_parser)

    doctor_parser = subparsers.add_parser("doctor", help="检查运行环境与依赖")
    doctor_cmd.build_parser(doctor_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    """入口，返回进程退出码"""
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())