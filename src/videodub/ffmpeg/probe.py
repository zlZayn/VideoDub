"""媒体探测 — 时长与流信息（ffprobe）"""

from __future__ import annotations

import json
import subprocess

from videodub.domain.models import MediaAsset


def probe_duration(media_path: str) -> float:
    """探测媒体时长（秒），失败返回 0.0"""
    command = [
        "ffprobe",
        "-v",
        "quiet",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        media_path,
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    out = result.stdout.decode("utf-8", errors="replace").strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def probe_media(media_path: str) -> MediaAsset:
    """探测媒体完整信息，无法解析时抛 ValueError"""
    command = [
        "ffprobe",
        "-v",
        "quiet",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        media_path,
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    # ffprobe 输出是 UTF-8；Windows 下默认编码是 GBK，必须显式解码
    out = result.stdout.decode("utf-8", errors="replace")
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace")
        raise ValueError(f"ffprobe 无法解析媒体: {media_path}\n{err[-400:]}")
    info = json.loads(out)

    video_streams = [
        s for s in info.get("streams", []) if s.get("codec_type") == "video"
    ]
    audio_streams = [
        s for s in info.get("streams", []) if s.get("codec_type") == "audio"
    ]

    duration = float(info.get("format", {}).get("duration") or 0.0)
    if duration <= 0 and audio_streams:
        duration = float(audio_streams[0].get("duration") or 0.0)
    if duration <= 0 and video_streams:
        duration = float(video_streams[0].get("duration") or 0.0)

    audio = audio_streams[0] if audio_streams else None
    return MediaAsset(
        path=media_path,
        kind="video" if video_streams else "audio",
        duration=duration,
        has_video=bool(video_streams),
        has_audio=bool(audio_streams),
        audio_sample_rate=int(audio["sample_rate"])
        if audio and audio.get("sample_rate")
        else None,
        audio_channels=audio.get("channels"),
    )
