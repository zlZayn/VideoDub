"""inspect 子命令 — 探测媒体信息

用法：videodub inspect input.mp4
"""

from __future__ import annotations

from videodub.ffmpeg.probe import probe_media


def build_parser(parser) -> None:
    parser.add_argument("input", help="输入视频/音频路径")
    parser.set_defaults(func=_run)


def _run(args) -> int:
    asset = probe_media(args.input)
    print(f"路径: {asset.path}")
    print(f"类型: {asset.kind}")
    print(f"时长: {asset.duration:.3f} 秒")
    print(f"视频流: {'有' if asset.has_video else '无'}")
    print(f"音频流: {'有' if asset.has_audio else '无'}")
    if asset.audio_sample_rate:
        print(f"音频: {asset.audio_sample_rate}Hz / {asset.audio_channels}声道")
    return 0