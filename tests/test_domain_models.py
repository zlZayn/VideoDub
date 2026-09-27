"""领域契约测试 — TimeRange / Segment / Transcript / Voice / MixPlan

不调用模型、不调用 FFmpeg，纯数据模型逻辑。
"""

import pytest

from videodub.domain.models import (
    AlignedClip,
    MixMode,
    MixPlan,
    PlacedClip,
    SynthesisResult,
    SynthStatus,
    VoiceAction,
)
from videodub.domain.transcript import Segment, TimeRange, Transcript, normalize_speaker

# ── TimeRange ──

def test_time_range_duration():
    assert TimeRange(1.0, 3.5).duration == 2.5


def test_time_range_to_dict_rounds():
    assert TimeRange(1.23456, 3.99999).to_dict() == {"start": 1.235, "end": 4.0}


# ── speaker 规范化 ──

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        (0, "SPEAKER_0"),
        (1, "SPEAKER_1"),
        ("SPEAKER_0", "SPEAKER_0"),
        ("customer", "SPEAKER_customer"),  # 非标号字符串按原样加前缀（边界行为）
    ],
)
def test_normalize_speaker(raw, expected):
    assert normalize_speaker(raw) == expected


# ── Segment ──

def test_segment_from_dict_legacy_shape():
    segment = Segment.from_dict({"start": 1.0, "end": 2.5, "text": "你好", "speaker": 0}, index=0)
    assert segment.id == "seg_0001"
    assert segment.range.duration == 1.5
    assert segment.speaker == "SPEAKER_0"


def test_segment_from_dict_keeps_explicit_id_and_meta():
    segment = Segment.from_dict(
        {"id": "seg_x", "start": 0.0, "end": 1.0, "text": "t", "custom": "v"}, index=5
    )
    assert segment.id == "seg_x"
    assert segment.meta == {"custom": "v"}


def test_segment_to_dict_round_trip():
    segment = Segment(
        id="seg_0001", range=TimeRange(1.0, 2.0), text="你好",
        speaker="SPEAKER_0", language="zh", confidence=0.98,
    )
    data = segment.to_dict()
    assert data["speaker"] == "SPEAKER_0"
    assert data["language"] == "zh"
    rebuilt = Segment.from_dict(data, index=0)
    assert rebuilt == segment


def test_segment_to_dict_omits_none_fields():
    data = Segment(id="s1", range=TimeRange(1.0, 2.0), text="t").to_dict()
    assert "speaker" not in data
    assert "confidence" not in data


# ── Transcript ──

def test_transcript_from_dicts_generates_ids():
    transcript = Transcript.from_dicts(
        [{"start": 0.0, "end": 1.0, "text": "a"}, {"start": 2.0, "end": 3.0, "text": "b", "speaker": 1}]
    )
    assert transcript.segments[0].id == "seg_0001"
    assert transcript.segments[1].id == "seg_0002"


def test_transcript_speakers_dedup_in_order():
    transcript = Transcript(segments=(
        Segment(id="s1", range=TimeRange(0, 1), text="a", speaker="SPEAKER_0"),
        Segment(id="s2", range=TimeRange(1, 2), text="b", speaker="SPEAKER_1"),
        Segment(id="s3", range=TimeRange(2, 3), text="c", speaker="SPEAKER_0"),
        Segment(id="s4", range=TimeRange(3, 4), text="d"),
    ))
    assert transcript.speakers == ("SPEAKER_0", "SPEAKER_1")


def test_transcript_round_trip():
    original = Transcript.from_dicts(
        [{"start": 0.0, "end": 1.0, "text": "a", "speaker": 0}], language="zh", source="asr"
    )
    rebuilt = Transcript.from_dicts(original.to_dicts(), language="zh", source="asr")
    assert rebuilt == original


# ── Voice 计划 / 结果 ──

def test_voice_assignment_actions_mutually_exclusive():
    actions = {a.value for a in VoiceAction}
    assert actions == {"synthesize", "keep_original", "skipped"}
    statuses = {s.value for s in SynthStatus}
    assert statuses == {"ok", "failed", "keep_original", "skipped"}


def test_synthesis_failure_is_explicit_not_none():
    result = SynthesisResult(segment_id="seg_0001", status=SynthStatus.FAILED, error="模型崩溃")
    assert result.audio_path is None
    assert result.status is SynthStatus.FAILED


# ── 对齐结果 ──

def test_aligned_clip_stretch_metrics():
    clip = AlignedClip(
        segment_id="seg_0001", status=SynthStatus.OK,
        original_duration=2.0, aligned_duration=1.6, stretch_ratio=0.8,
    )
    assert clip.stretch_ratio == 0.8


# ── MixPlan ──

def test_mix_plan_mute_ranges_from_clips():
    plan = MixPlan(
        mode=MixMode.PARTIAL_REPLACE,
        clips=(PlacedClip("seg_0001", None, 1.0, 3.0), PlacedClip("seg_0002", None, 8.0, 9.0)),
    )
    ranges = plan.mute_ranges
    assert len(ranges) == 2
    assert ranges[0].duration == 2.0
    assert ranges[1].start == 8.0


def test_mix_mode_values_preserved():
    assert MixMode.FULL_REPLACE.value == "full_replace"
    assert MixMode.KEEP_BACKGROUND.value == "keep_background"
    assert MixMode.PARTIAL_REPLACE.value == "partial_replace"