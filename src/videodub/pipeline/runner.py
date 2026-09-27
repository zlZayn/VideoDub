"""流水线编排 — run_job：JobSpec → 产物与报告

阶段：解析媒体 → 获取台词 → 构建配音计划 → 合成 → 对齐 → 混音计划 → 渲染 → 报告
dry_run：只解析媒体 + 计划，不碰重模型、不渲染。
"""

from __future__ import annotations

import contextlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from videodub.config.job_spec import JobSpec, resolve_model_name
from videodub.domain.transcript import Transcript
from videodub.ffmpeg.probe import probe_media
from videodub.ffmpeg.render_mix import render
from videodub.ffmpeg.runner import ensure_ffmpeg_available, run_ffmpeg_command
from videodub.pipeline.cache import Cache, asr_cache_key
from videodub.pipeline.planning import build_mix_plan, build_voice_plan
from videodub.pipeline.report import Report, write_report
from videodub.pipeline.synthesis import (
    align_segments,
    prepare_refs,
    synthesize_segments,
)
from videodub.pipeline.transcript_loader import (
    load_json_transcript,
    load_subtitle_transcript,
)
from videodub.pipeline.workspace import Workspace, create_workspace
from videodub.utils.logger import log, log_stage_header, log_success


def _load_transcript(job: JobSpec, ws: Workspace, cache: Cache) -> dict:
    """获取台词（JSON / 字幕 / ASR 三选一），返回 {transcript, cached}"""
    spec = job.transcript
    if spec.source.value == "json":
        return {"transcript": load_json_transcript(str(spec.path)), "cached": False}
    if spec.source.value == "subtitle":
        return {"transcript": load_subtitle_transcript(str(spec.path)), "cached": False}

    # ASR：先查缓存，miss 再提取音轨 + 识别
    media_path = str(job.input.path)
    key = asr_cache_key(
        media_path,
        backend=spec.backend.value,
        model=resolve_model_name(spec.backend, spec.model_name),
        language=spec.language,
        diarize=spec.diarize,
        max_speakers=spec.max_speakers,
    )
    cached = cache.get("asr", key, ".json")
    if cached is not None:
        with open(cached, "r", encoding="utf-8") as f:
            transcript = json.load(f)
        return {"transcript": Transcript.from_dicts(transcript, source="asr"), "cached": True}

    extracted = ws.file("asr", "extracted_audio.wav")
    run_ffmpeg_command(
        ["-y", "-i", media_path,
         "-vn", "-acodec", "pcm_s16le",
         "-ar", "16000", "-ac", "1", str(extracted)],
        "提取视频音轨 (16kHz mono)",
    )
    from videodub.backends.registry import get_transcriber
    transcriber = get_transcriber(spec)
    transcript = transcriber.transcribe(str(extracted))

    transcript_file = ws.file("asr", "transcript.json")
    transcript_file.write_text(
        json.dumps(transcript.to_dicts(), ensure_ascii=False, indent=2), encoding="utf-8",
    )
    cache.put("asr", key, transcript_file, ".json")
    return {"transcript": transcript, "cached": False}


def _log_transcript_summary(transcript) -> None:
    log("台词", f"共 {len(transcript.segments)} 句")
    if transcript.speakers:
        log("台词", f"说话人: {', '.join(transcript.speakers)}")


def run_job(job: JobSpec, *, workspace: Workspace | None = None) -> dict:
    """执行配音任务，返回报告 dict（report.json 内容）"""
    ensure_ffmpeg_available()
    ws = workspace or create_workspace(str(job.output.path), job.runtime.keep_temp)
    cache = Cache(enabled=job.runtime.cache)
    report = Report()

    try:
        log_stage_header("流程", "视频音色替换（全流程）")

        # 阶段 0: 解析媒体
        with _stage(report, "resolve_media"):
            media = probe_media(str(job.input.path))
        log("媒体", f"{media.kind}, 时长 {media.duration:.1f}s, 音频 {media.audio_sample_rate}Hz/{media.audio_channels}ch")

        # 阶段 1: 获取台词
        with _stage(report, "load_transcript"):
            loaded = _load_transcript(job, ws, cache)
        transcript = loaded["transcript"]
        _log_transcript_summary(transcript)
        ws.write_artifact("transcript.json", transcript.to_dicts())
        ws.write_artifact("config.snapshot.json", job.model_dump(mode="json"))

        # 阶段 2: 配音计划
        with _stage(report, "build_voice_plan"):
            assignments = build_voice_plan(transcript, job.voice)
        ws.write_artifact("voice_plan.json", [
            {"segment_id": a.segment_id, "action": a.action.value, "profile_id": a.profile_id}
            for a in assignments
        ])

        # dry_run：到此为止
        if job.runtime.dry_run:
            log_stage_header("计划", "dry-run: 不执行合成/对齐/渲染")
            synthesized = sum(1 for a in assignments if a.action.value == "synthesize")
            kept = sum(1 for a in assignments if a.action.value == "keep_original")
            log("计划", f"合成 {synthesized} 句，保留原声 {kept} 句")
            summary = _summarize(job, media, transcript, assignments, (), (), ws, cache, report)
            return summary

        # 阶段 3: TTS 合成
        refs = prepare_refs(job, ws)
        with _stage(report, "synthesize"):
            results = synthesize_segments(assignments, transcript, job.tts, refs, ws, cache)

        # 阶段 4: 对齐 + 后处理
        with _stage(report, "align"):
            aligned = align_segments(results, transcript, job.align, ws)

        # 阶段 5: 混音计划
        with _stage(report, "build_mix_plan"):
            mix_plan = build_mix_plan(transcript, aligned, job.mix)
        ws.write_artifact("mix_plan.json", {
            "mode": mix_plan.mode.value,
            "clips": [
                {"segment_id": c.segment_id, "audio_path": str(c.audio_path),
                 "start": c.start, "end": c.end}
                for c in mix_plan.clips
            ],
            "background_volume_ratio": mix_plan.background_volume_ratio,
        })
        log("合成", f"混音模式: {mix_plan.mode.value}, 配音片段 {len(mix_plan.clips)} 个")

        # 阶段 6: 渲染输出
        with _stage(report, "render"):
            render(
                mix_plan, str(job.input.path), str(job.output.path),
                audio_only=job.output.audio_only,
                video_codec=job.output.video_codec,
                audio_codec=job.output.audio_codec,
                audio_bitrate=job.output.audio_bitrate,
            )

        log_stage_header("完成", f"全部完成! 输出文件: {job.output.path}")
        return _summarize(job, media, transcript, assignments, results, aligned, ws, cache, report)
    finally:
        ws.cleanup()


def _summarize(job, media, transcript, assignments, results, aligned, ws: Workspace, cache: Cache, report) -> dict:
    """汇总报告并写入 report.json"""
    report.add_segment_rows(transcript, assignments, results, aligned)

    media_dict = asdict(media)
    media_dict["path"] = str(media_dict["path"])
    tts_hits = sum(1 for group, _ in cache.hits if group == "tts")
    asr_hits = sum(1 for group, _ in cache.hits if group == "asr")
    data = report.as_dict(
        job=job.model_dump(mode="json"),
        media=media_dict,
        output={"path": str(job.output.path), "exists": Path(job.output.path).exists()},
        dry_run=job.runtime.dry_run,
        transcript={"source": transcript.source, "count": len(transcript.segments),
                    "speakers": list(transcript.speakers)},
        cache={"asr_hits": asr_hits, "tts_hits": tts_hits},
        summary={
            "synthesize": sum(1 for a in assignments if a.action.value == "synthesize"),
            "keep_original": sum(1 for a in assignments if a.action.value == "keep_original"),
            "synth_ok": sum(1 for r in results if r.status.value == "ok") if results else 0,
            "failed": sum(1 for r in results if r.status.value == "failed") if results else 0,
        },
    )
    report_path = write_report(ws.root, data)
    log_success(f"报告: {report_path}")
    return data


@contextlib.contextmanager
def _stage(report: Report, name: str):
    """阶段计时：进入记录开始，退出向 report 登记秒数"""
    start = time.monotonic()
    yield start
    report.add_stage(name, time.monotonic() - start)