"""计划构建 — VoicePlan（这句怎么配）与 MixPlan（怎么混）"""

from __future__ import annotations

from videodub.config.job_spec import MixPolicy, MixSpec, VoiceSpec
from videodub.domain.models import (
    AlignedClip,
    MixMode,
    MixPlan,
    PlacedClip,
    SynthStatus,
    VoiceAction,
    VoiceAssignment,
)
from videodub.domain.transcript import Transcript

DEFAULT_PROFILE_ID = "default"


def build_voice_plan(transcript: Transcript, voice: VoiceSpec) -> tuple[VoiceAssignment, ...]:
    """逐句决定动作：
    - speaker_map 模式：映射为 None → 保留原声；映射为路径 → 用该音色合成；不在映射 → 保留原声
    - 全局 ref_audio 模式：全部合成
    """
    assignments = []
    if voice.speaker_map:
        for segment in transcript.segments:
            if segment.speaker is not None and segment.speaker in voice.speaker_map:
                ref = voice.speaker_map[segment.speaker]
                if ref is None:
                    assignments.append(VoiceAssignment(segment.id, VoiceAction.KEEP_ORIGINAL))
                else:
                    assignments.append(VoiceAssignment(segment.id, VoiceAction.SYNTHESIZE, segment.speaker))
            else:
                assignments.append(VoiceAssignment(segment.id, VoiceAction.KEEP_ORIGINAL))
    else:
        for segment in transcript.segments:
            assignments.append(VoiceAssignment(segment.id, VoiceAction.SYNTHESIZE, DEFAULT_PROFILE_ID))
    return tuple(assignments)


def build_mix_plan(transcript: Transcript, aligned_clips: tuple[AlignedClip, ...], mix: MixSpec) -> MixPlan:
    """按混音策略与对齐结果构建 MixPlan（渲染层唯一输入）"""
    segments_by_id = {segment.id: segment for segment in transcript.segments}

    ok_clips = [clip for clip in aligned_clips if clip.status is SynthStatus.OK and clip.audio_path]
    placed = tuple(
        PlacedClip(
            segment_id=clip.segment_id,
            audio_path=clip.audio_path,
            start=clip.target_start,
            end=clip.target_end,
        )
        for clip in ok_clips
    )

    mode = _resolve_mode(mix, aligned_clips)
    return MixPlan(
        mode=mode,
        clips=placed,
        background_volume_ratio=mix.background_volume_ratio if mode is MixMode.KEEP_BACKGROUND else None,
    )


def _resolve_mode(mix: MixSpec, aligned_clips: tuple[AlignedClip, ...]) -> MixMode:
    """auto = 旧规则：存在保留段 → partial_replace，否则 full_replace；显式策略优先"""
    if mix.policy is MixPolicy.KEEP_BACKGROUND:
        return MixMode.KEEP_BACKGROUND
    if mix.policy is MixPolicy.FULL_REPLACE:
        return MixMode.FULL_REPLACE
    if mix.policy is MixPolicy.PARTIAL_REPLACE:
        return MixMode.PARTIAL_REPLACE
    has_kept = any(clip.status is not SynthStatus.OK for clip in aligned_clips)
    return MixMode.PARTIAL_REPLACE if has_kept else MixMode.FULL_REPLACE