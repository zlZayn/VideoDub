"""合成与对齐 — 逐句 TTS + 时域拉伸/音量/淡入淡出

参考音频按 profile_id 预转换（m4a/mp3 → wav），TTS 结果缓存命中直接复用。
"""

from __future__ import annotations

from pathlib import Path

from videodub.backends.registry import get_synthesizer
from videodub.config.job_spec import AlignSpec, JobSpec, TTSSpec
from videodub.domain.models import (
    AlignedClip,
    SynthStatus,
    SynthesisResult,
    VoiceAction,
    VoiceAssignment,
)
from videodub.domain.transcript import Transcript
from videodub.ffmpeg.ops import (
    ensure_wav_format,
    post_process_audio,
    stretch_audio_to_duration,
)
from videodub.ffmpeg.probe import probe_duration
from videodub.pipeline.cache import Cache, tts_cache_key
from videodub.pipeline.planning import DEFAULT_PROFILE_ID
from videodub.pipeline.workspace import Workspace
from videodub.utils.logger import log, log_stage_header


def prepare_refs(job: JobSpec, ws: Workspace) -> dict[str, str | None]:
    """参考音频预处理：profile_id → 可被 soundfile 读取的路径（自动转 wav）"""
    refs: dict[str, str | None] = {}
    if job.voice.ref_audio is not None:
        refs[DEFAULT_PROFILE_ID] = ensure_wav_format(str(job.voice.ref_audio), str(ws.dir("refs")))
    else:
        for speaker, path in job.voice.speaker_map.items():
            refs[speaker] = ensure_wav_format(str(path), str(ws.dir("refs"))) if path else None
    return refs


def synthesize_segments(
    assignments: tuple[VoiceAssignment, ...],
    transcript: Transcript,
    tts_spec: TTSSpec,
    refs: dict[str, str | None],
    ws: Workspace,
    cache: Cache,
) -> tuple[SynthesisResult, ...]:
    """逐句合成（KEEP_ORIGINAL 直通；OK 记录时长；失败显式标记）"""
    log_stage_header("TTS", f"模式: {tts_spec.mode.value}, 推理步数: {tts_spec.inference_steps}")
    synthesizer = get_synthesizer(tts_spec)
    synthesizer.load()
    results = []
    try:
        for index, (segment, assignment) in enumerate(zip(transcript.segments, assignments)):
            if assignment.action is not VoiceAction.SYNTHESIZE:
                log("TTS", f"[{index+1}/{len(transcript.segments)}] {segment.id}: 保留原声")
                results.append(SynthesisResult(segment.id, SynthStatus.KEEP_ORIGINAL))
                continue

            ref_audio = refs.get(assignment.profile_id)
            cache_key = tts_cache_key(
                segment.text, ref_audio,
                mode=tts_spec.mode.value,
                model=tts_spec.api_model_name if tts_spec.mode.value == "api" else "voxcpm2",
                steps=tts_spec.inference_steps,
                device=tts_spec.device,
            )
            cached = cache.get("tts", cache_key, ".wav")
            if cached is not None:
                duration = probe_duration(str(cached))
                results.append(SynthesisResult(
                    segment.id, SynthStatus.OK, audio_path=cached, duration=duration,
                ))
                log("TTS", f"[{index+1}/{len(transcript.segments)}] {segment.id}: 缓存命中（{duration:.2f}s）")
                continue

            output = ws.file("tts", f"tts_{index:04d}.wav")
            ok = synthesizer.synthesize(segment.text, ref_audio, str(output))
            if ok:
                stored = cache.put("tts", cache_key, output, ".wav")
                duration = probe_duration(str(output))
                results.append(SynthesisResult(
                    segment.id, SynthStatus.OK, audio_path=stored, duration=duration,
                ))
                log("TTS", f"[{index+1}/{len(transcript.segments)}] {segment.id}: 合成完成（{duration:.2f}s）")
            else:
                log("TTS", f"[{index+1}/{len(transcript.segments)}] {segment.id}: 生成失败")
                results.append(SynthesisResult(segment.id, SynthStatus.FAILED, error="TTS 生成失败"))
    finally:
        synthesizer.unload()
    return tuple(results)


def align_segments(
    results: tuple[SynthesisResult, ...],
    transcript: Transcript,
    align_spec: AlignSpec,
    ws: Workspace,
) -> tuple[AlignedClip, ...]:
    """对齐：OK 片段时域拉伸到原句时长 + 后处理；其余状态直通"""
    log_stage_header("对齐", "时域拉伸，保音高 + 音量归一化 + 淡入淡出")
    clips = []
    for index, (segment, result) in enumerate(zip(transcript.segments, results)):
        target_duration = segment.range.duration
        if result.status is not SynthStatus.OK:
            clips.append(AlignedClip(
                segment_id=segment.id,
                status=result.status,
                target_start=segment.range.start,
                target_end=segment.range.end,
                error=result.error,
            ))
            continue

        output = ws.file("align", f"aligned_{index:04d}.wav")
        if align_spec.enable_post_process:
            stretched = ws.file("align", f"stretched_{index:04d}.wav")
            stretch_audio_to_duration(str(result.audio_path), str(stretched), target_duration)
            post_process_audio(
                str(stretched), str(output),
                target_volume_db=align_spec.target_volume_db,
                fade_in_ms=align_spec.fade_in_ms,
                fade_out_ms=align_spec.fade_out_ms,
            )
        else:
            stretch_audio_to_duration(str(result.audio_path), str(output), target_duration)

        aligned_duration = probe_duration(str(output))
        ratio = target_duration / result.duration if result.duration else None
        warning = None
        if ratio is not None and (ratio > 2.0 or ratio < 0.5):
            warning = f"极端拉伸 ×{ratio:.2f}"
        clips.append(AlignedClip(
            segment_id=segment.id,
            status=SynthStatus.OK,
            audio_path=Path(output),
            target_start=segment.range.start,
            target_end=segment.range.end,
            original_duration=result.duration,
            aligned_duration=aligned_duration,
            stretch_ratio=ratio,
            warning=warning,
        ))
    return tuple(clips)