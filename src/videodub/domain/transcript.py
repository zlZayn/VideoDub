"""台词契约 — TimeRange / Segment / Transcript

统一 ASR、字幕、JSON 三种台词来源的输出模型。
旧格式 dict（{start, end, text, speaker?}）只在序列化边界出现。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TimeRange:
    """时间范围（秒）"""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {"start": round(self.start, 3), "end": round(self.end, 3)}


def normalize_speaker(speaker) -> str | None:
    """说话人标号统一为字符串：0 → 'SPEAKER_0'；已是标号则原样返回"""
    if speaker is None:
        return None
    if isinstance(speaker, str) and speaker.startswith("SPEAKER_"):
        return speaker
    return f"SPEAKER_{speaker}"


@dataclass(frozen=True)
class Segment:
    """一段台词"""

    id: str
    range: TimeRange
    text: str
    speaker: str | None = None
    language: str | None = None
    confidence: float | None = None
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        result = {"id": self.id, **self.range.to_dict(), "text": self.text}
        if self.speaker is not None:
            result["speaker"] = self.speaker
        if self.language is not None:
            result["language"] = self.language
        if self.confidence is not None:
            result["confidence"] = self.confidence
        return result

    @classmethod
    def from_dict(cls, data: dict, index: int) -> Segment:
        """从旧格式 dict 构建（兼容 ASR 输出 / 字幕 / recognized_segments.json）"""
        return cls(
            id=data.get("id") or f"seg_{index + 1:04d}",
            range=TimeRange(float(data["start"]), float(data["end"])),
            text=str(data["text"]),
            speaker=normalize_speaker(data.get("speaker")),
            language=data.get("language"),
            confidence=float(data["confidence"]) if data.get("confidence") is not None else None,
            meta={
                key: value
                for key, value in data.items()
                if key not in ("id", "start", "end", "text", "speaker", "language", "confidence")
            },
        )


@dataclass(frozen=True)
class Transcript:
    """识别结果（ASR / 字幕 / JSON 统一模型）"""

    segments: tuple[Segment, ...] = ()
    language: str | None = None
    source: str = "asr"
    meta: dict = field(default_factory=dict)

    @property
    def speakers(self) -> tuple[str, ...]:
        """去重后的说话人列表（按出现顺序）"""
        seen: list[str] = []
        for segment in self.segments:
            if segment.speaker is not None and segment.speaker not in seen:
                seen.append(segment.speaker)
        return tuple(seen)

    @classmethod
    def from_dicts(cls, items: list[dict], *, language: str | None = None, source: str = "asr") -> Transcript:
        return cls(
            segments=tuple(Segment.from_dict(item, index) for index, item in enumerate(items)),
            language=language,
            source=source,
        )

    def to_dicts(self) -> list[dict]:
        return [segment.to_dict() for segment in self.segments]