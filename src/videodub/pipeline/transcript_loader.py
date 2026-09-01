"""台词加载 — JSON / 字幕 → Transcript（跳过 ASR 的来源）

注意：旧文档声称支持 VTT，但代码只解析 SRT/ASS/SSA，此处沿用代码行为。
"""

from __future__ import annotations

import json
import re

from videodub.domain.transcript import Transcript
from videodub.utils.logger import log, log_error


def load_json_transcript(json_path: str) -> Transcript:
    """从已识别台词 JSON 加载（recognized_segments.json 格式）"""
    with open(json_path, "r", encoding="utf-8") as f:
        items = json.load(f)
    log("台词", f"从 JSON 加载 {len(items)} 句台词:")
    for seg in items:
        log("台词", f"  [{float(seg['start']):6.2f}s - {float(seg['end']):6.2f}s] {seg['text']}")
    return Transcript.from_dicts(items, source="json")


# ── SRT 解析 ──

_SRT_PATTERN = re.compile(
    r"(\d+)\s*\n"
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*\n"
    r"((?:[^\n]+\n?)+?)(?=\n*\d+\s*\n|\Z)",
    re.MULTILINE,
)


def _parse_srt(content: str) -> list[dict]:
    segments = []
    for match in _SRT_PATTERN.finditer(content):
        start = (int(match.group(2)) * 3600 + int(match.group(3)) * 60
                 + int(match.group(4)) + int(match.group(5)) / 1000)
        end = (int(match.group(6)) * 3600 + int(match.group(7)) * 60
               + int(match.group(8)) + int(match.group(9)) / 1000)
        text = match.group(10).strip().replace("\n", " ")
        if text:
            segments.append({"start": start, "end": end, "text": text})
    return segments


# ── ASS / SSA 解析 ──

_ASS_PATTERN = re.compile(
    r"Dialogue:\s*\d+,"
    r"(\d):(\d{2}):(\d{2})\.(\d{2}),"
    r"(\d):(\d{2}):(\d{2})\.(\d{2}),"
    r"[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,(.*)",
)


def _parse_ass(content: str) -> list[dict]:
    segments = []
    for match in _ASS_PATTERN.finditer(content):
        start = (int(match.group(1)) * 3600 + int(match.group(2)) * 60
                 + int(match.group(3)) + int(match.group(4)) / 100)
        end = (int(match.group(5)) * 3600 + int(match.group(6)) * 60
               + int(match.group(7)) + int(match.group(8)) / 100)
        text = re.sub(r"\{[^}]*\}", "", match.group(9)).strip()
        text = text.replace("\\N", " ").replace("\\n", " ")
        if text:
            segments.append({"start": start, "end": end, "text": text})
    return segments


def load_subtitle_transcript(subtitle_path: str) -> Transcript:
    """自动检测字幕格式并解析为 Transcript（.srt / .ass / .ssa）"""
    extension = subtitle_path.lower().rsplit(".", 1)[-1]
    with open(subtitle_path, "r", encoding="utf-8") as f:
        content = f.read()

    if extension == "srt":
        segments = _parse_srt(content)
    elif extension in ("ass", "ssa"):
        segments = _parse_ass(content)
    else:
        log_error(f"不支持的字幕格式 .{extension}，请使用 .srt 或 .ass")
        raise ValueError(f"不支持的字幕格式: .{extension}")

    if not segments:
        log_error(f"字幕文件为空或解析失败 → {subtitle_path}")
        raise ValueError(f"字幕文件为空或解析失败: {subtitle_path}")

    log("字幕", f"解析完成: {len(segments)} 个片段")
    for segment in segments:
        log("字幕", f"  [{segment['start']:.1f}s - {segment['end']:.1f}s] {segment['text']}")
    return Transcript.from_dicts(segments, source="subtitle")