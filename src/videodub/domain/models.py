"""配音与混音契约 — VoiceAssignment / SynthesisResult / AlignedClip / MixPlan

消灭旧契约的 None 多语义（"保留原声"与"生成失败"混用同一个 None）：
- VoiceAssignment 是计划：这句应该 synthesize / keep_original / skip
- SynthesisResult 是结果：实际 ok / failed / keep_original / skipped
- MixPlan 只描述怎么混，渲染层不再理解业务，只执行计划
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .transcript import TimeRange


class VoiceAction(str, Enum):
    """配音计划动作"""

    SYNTHESIZE = "synthesize"
    KEEP_ORIGINAL = "keep_original"
    SKIPPED = "skipped"


class SynthStatus(str, Enum):
    """配音/对齐执行结果状态"""

    OK = "ok"
    FAILED = "failed"
    KEEP_ORIGINAL = "keep_original"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class VoiceAssignment:
    """该片段应该怎么处理"""

    segment_id: str
    action: VoiceAction
    profile_id: str | None = None


@dataclass(frozen=True)
class SynthesisResult:
    """TTS 合成结果（每片段一条）"""

    segment_id: str
    status: SynthStatus
    audio_path: Path | None = None
    duration: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class AlignedClip:
    """时间对齐结果（每片段一条）"""

    segment_id: str
    status: SynthStatus
    audio_path: Path | None = None
    target_start: float = 0.0
    target_end: float = 0.0
    original_duration: float | None = None
    aligned_duration: float | None = None
    stretch_ratio: float | None = None
    warning: str | None = None
    error: str | None = None


class MixMode(str, Enum):
    """混音模式（枚举值保持与旧版一致，golden 兼容）"""

    FULL_REPLACE = "full_replace"
    KEEP_BACKGROUND = "keep_background"
    PARTIAL_REPLACE = "partial_replace"


@dataclass(frozen=True)
class PlacedClip:
    """放置到时间轴上的配音片段"""

    segment_id: str
    audio_path: Path
    start: float
    end: float


@dataclass(frozen=True)
class MixPlan:
    """混音计划：渲染层唯一输入"""

    mode: MixMode
    clips: tuple[PlacedClip, ...] = ()
    background_volume_ratio: float | None = None
    output_sample_rate: int = 48000
    target_volume_db: float = -10.7
    mute_padding_ms: int = 30

    @property
    def mute_ranges(self) -> tuple[TimeRange, ...]:
        """被替换的段落（partial_replace 时原音轨需静音的区域）"""
        return tuple(TimeRange(clip.start, clip.end) for clip in self.clips)


@dataclass(frozen=True)
class MediaAsset:
    """媒体探测结果"""

    path: Path
    kind: str  # "video" | "audio"
    duration: float
    has_video: bool = False
    has_audio: bool = False
    audio_sample_rate: int | None = None
    audio_channels: int | None = None