"""运行报告 — report.json 的收集与写入

每次运行必产 report.json（重产物清理后仍保留），用于排查：
阶段耗时 / 每片段结果 / 缓存命中 / 警告 / 混音计划 / 渲染命令。
"""

from __future__ import annotations

import json
from pathlib import Path

from videodub.domain.transcript import Transcript


class Report:
    """友好收集器，最终 as_dict() 交给 write_report"""

    def __init__(self) -> None:
        self._stages: list[dict] = []
        self._warnings: list[str] = []
        self._segments: list[dict] = []

    def add_stage(self, name: str, seconds: float, detail: dict | None = None) -> None:
        row = {"name": name, "seconds": round(seconds, 2)}
        if detail:
            row["detail"] = detail
        self._stages.append(row)

    def add_warning(self, message: str) -> None:
        self._warnings.append(message)

    def add_segment_rows(
        self, transcript: Transcript, assignments=(), results=(), aligned=()
    ) -> None:
        """汇合逐片段计划/合成/对齐三份数据到一行"""
        voice_by = {a.segment_id: a for a in assignments}
        synth_by = {r.segment_id: r for r in results}
        align_by = {c.segment_id: c for c in aligned}
        for segment in transcript.segments:
            row = {
                "id": segment.id,
                "start": segment.range.start,
                "end": segment.range.end,
                "text": segment.text,
                "speaker": segment.speaker,
            }
            assignment = voice_by.get(segment.id)
            if assignment:
                row["plan_action"] = assignment.action.value
                row["profile_id"] = assignment.profile_id
            synth = synth_by.get(segment.id)
            if synth:
                row["synth_status"] = synth.status.value
                row["synth_error"] = synth.error
            clip = align_by.get(segment.id)
            if clip:
                row["align_status"] = clip.status.value
                row["stretch_ratio"] = clip.stretch_ratio
                row["warning"] = clip.warning
            self._segments.append(row)

    def as_dict(self, **extra) -> dict:
        return {
            **extra,
            "stages": self._stages,
            "segments": self._segments,
            "warnings": self._warnings,
        }


def write_report(root: Path, data: dict) -> Path:
    """写 report.json 到运行目录根"""
    path = root / "report.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
