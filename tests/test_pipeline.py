"""流水线测试 — cache / workspace / 计划 / 合成对齐 / 全链集成（全 mock，不跑真模型与 ffmpeg）"""

import json
import sys
from pathlib import Path

import pytest

from videodub.config.job_spec import (
    AlignSpec,
    JobSpec,
    MixPolicy,
    MixSpec,
    TranscriptSource,
    VoiceSpec,
)
from videodub.domain.models import (
    AlignedClip,
    MixMode,
    SynthStatus,
    SynthesisResult,
    VoiceAction,
    VoiceAssignment,
)
from videodub.domain.transcript import Segment, TimeRange, Transcript
from videodub.pipeline.cache import Cache, asr_cache_key, audio_hash, text_hash, tts_cache_key
from videodub.pipeline.planning import build_mix_plan, build_voice_plan
from videodub.pipeline.synthesis import align_segments
from videodub.pipeline.workspace import Workspace


# ── cache ──

def test_cache_put_get_roundtrip(tmp_path):
    cache = Cache(root=tmp_path / "cache", enabled=True)
    source = tmp_path / "src.wav"
    source.write_bytes(b"audio-data")
    stored = cache.put("tts", "key123", source, ".wav")
    assert stored.name == "key123.wav"
    assert cache.get("tts", "key123", ".wav") == stored


def test_cache_disabled_noop(tmp_path):
    cache = Cache(enabled=False)
    assert cache.get("tts", "k", ".wav") is None
    assert cache.put("tts", "k", tmp_path / "src.wav", ".wav") == tmp_path / "src.wav"


def test_cache_miss_records_no_hit(tmp_path):
    cache = Cache(root=tmp_path / "cache")
    assert cache.get("asr", "nope", ".json") is None
    assert cache.hits == []


def test_text_hash_deterministic_and_sensitive():
    assert text_hash("a", "b") == text_hash("a", "b")
    assert text_hash("a", "b") != text_hash("a", "c")


def test_audio_hash_changes_with_content(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"x" * 1000)
    b.write_bytes(b"y" * 1000)
    assert audio_hash(a) == audio_hash(a)
    assert audio_hash(a) != audio_hash(b)


def test_asr_cache_key_param_sensitive(tmp_path):
    media = str(tmp_path / "m.mp4")
    Path(media).write_bytes(b"media")
    base = asr_cache_key(media, backend="funasr", model="paraformer-zh", language="zh",
                         diarize=True, max_speakers=2)
    assert base != asr_cache_key(media, backend="funasr", model="paraformer-zh", language="zh",
                                 diarize=False, max_speakers=2)
    assert base != asr_cache_key(media, backend="whisper", model="paraformer-zh", language="zh",
                                 diarize=True, max_speakers=2)


def test_tts_cache_key_text_and_ref_sensitive(tmp_path):
    ref_a = tmp_path / "a.wav"
    ref_b = tmp_path / "b.wav"
    ref_a.write_bytes(b"a")
    ref_b.write_bytes(b"b")
    base = tts_cache_key("你好", str(ref_a), mode="local", model="voxcpm2", steps=10, device="cpu")
    assert base != tts_cache_key("你好", str(ref_b), mode="local", model="voxcpm2", steps=10, device="cpu")
    assert base != tts_cache_key("再见", str(ref_a), mode="local", model="voxcpm2", steps=10, device="cpu")


# ── workspace ──

def test_workspace_file_and_cleanup(tmp_path):
    ws = Workspace(tmp_path / "run", keep=False)
    path = ws.file("asr", "extracted_audio.wav")
    assert path.parent.exists()
    path.write_bytes(b"data")
    ws.write_artifact("report.json", {"ok": True})

    ws.cleanup()

    assert not (tmp_path / "run" / "asr").exists()  # 重产物清理
    assert (tmp_path / "run" / "report.json").exists()  # 根产物保留


def test_workspace_keep_preserves_all(tmp_path):
    ws = Workspace(tmp_path / "run", keep=True)
    path = ws.file("tts", "x.wav")
    path.write_bytes(b"d")
    ws.cleanup()
    assert path.exists()


# ── 配音计划 ──

def _transcript(*items):
    return Transcript(segments=tuple(
        Segment(id=f"seg_{i + 1:04d}", range=TimeRange(s, e), text=t, speaker=spk)
        for i, (s, e, t, spk) in enumerate(items)
    ))


def test_voice_plan_global_ref(tmp_path):
    (tmp_path / "r.wav").write_bytes(b"ref")
    transcript = _transcript((0.0, 1.0, "a", None), (1.0, 2.0, "b", None))
    plan = build_voice_plan(transcript, VoiceSpec(ref_audio=tmp_path / "r.wav"))
    assert all(a.action is VoiceAction.SYNTHESIZE for a in plan)
    assert all(a.profile_id == "default" for a in plan)


def test_voice_plan_speaker_map_keep_and_unmapped(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"ref")
    transcript = _transcript(
        (0.0, 1.0, "a", "SPEAKER_0"),
        (1.0, 2.0, "b", "SPEAKER_1"),
        (2.0, 3.0, "c", "SPEAKER_2"),
        (3.0, 4.0, "d", None),
    )
    voice = VoiceSpec(speaker_map={
        "SPEAKER_0": tmp_path / "a.wav", "SPEAKER_1": None,
    })
    plan = build_voice_plan(transcript, voice)
    assert plan[0].action is VoiceAction.SYNTHESIZE and plan[0].profile_id == "SPEAKER_0"
    assert plan[1].action is VoiceAction.KEEP_ORIGINAL
    assert plan[2].action is VoiceAction.KEEP_ORIGINAL  # 不在映射 → 保留
    assert plan[3].action is VoiceAction.KEEP_ORIGINAL  # 无 speaker → 保留


# ── 混音计划 ──

def _aligned(*statuses):
    return tuple(
        AlignedClip(segment_id=f"seg_{i + 1:04d}", status=st, audio_path=Path(f"a{i}.wav") if st is SynthStatus.OK else None,
                    target_start=i, target_end=i + 1)
        for i, st in enumerate(statuses)
    )


def test_mix_plan_auto_full_replace():
    transcript = _transcript((0.0, 1.0, "a", None), (1.0, 2.0, "b", None))
    aligned = _aligned(SynthStatus.OK, SynthStatus.OK)
    plan = build_mix_plan(transcript, aligned, MixSpec())
    assert plan.mode is MixMode.FULL_REPLACE
    assert len(plan.clips) == 2


def test_mix_plan_auto_partial_when_kept():
    transcript = _transcript((0.0, 1.0, "a", None), (1.0, 2.0, "b", None))
    aligned = _aligned(SynthStatus.OK, SynthStatus.KEEP_ORIGINAL)
    plan = build_mix_plan(transcript, aligned, MixSpec())
    assert plan.mode is MixMode.PARTIAL_REPLACE
    assert len(plan.clips) == 1
    assert len(plan.mute_ranges) == 1


def test_mix_plan_explicit_keep_background():
    transcript = _transcript((0.0, 1.0, "a", None))
    aligned = _aligned(SynthStatus.OK)
    plan = build_mix_plan(transcript, aligned, MixSpec(policy=MixPolicy.KEEP_BACKGROUND, background_volume_ratio=0.4))
    assert plan.mode is MixMode.KEEP_BACKGROUND
    assert plan.background_volume_ratio == 0.4


def test_mix_plan_explicit_full_wins_over_kept():
    transcript = _transcript((0.0, 1.0, "a", None), (1.0, 2.0, "b", None))
    aligned = _aligned(SynthStatus.OK, SynthStatus.KEEP_ORIGINAL)
    plan = build_mix_plan(transcript, aligned, MixSpec(policy=MixPolicy.FULL_REPLACE))
    assert plan.mode is MixMode.FULL_REPLACE
    assert len(plan.clips) == 1  # 保留段不参与混音


# ── 对齐 ──

def test_align_results_and_extreme_warning(tmp_path, monkeypatch):
    import videodub.pipeline.synthesis as synthesis

    monkeypatch.setattr(synthesis, "stretch_audio_to_duration", lambda src, dst, target: Path(dst).write_bytes(b"x"))
    monkeypatch.setattr(synthesis, "post_process_audio", lambda src, dst, **kw: Path(dst).write_bytes(b"x"))
    monkeypatch.setattr(synthesis, "probe_duration", lambda p: 0.5)

    transcript = _transcript((0.0, 2.0, "很长的一句话", None))
    results = (SynthesisResult("seg_0001", SynthStatus.OK, audio_path=Path("tts.wav"), duration=5.0),)
    ws = Workspace(tmp_path / "run")

    aligned = align_segments(results, transcript, AlignSpec(), ws)

    clip = aligned[0]
    assert clip.status is SynthStatus.OK
    assert clip.stretch_ratio == 0.4  # target 2.0 / original 5.0
    assert clip.warning == "极端拉伸 ×0.40"


def test_align_passes_through_non_ok(tmp_path):
    import videodub.pipeline.synthesis as synthesis
    transcript = _transcript((0.0, 1.0, "a", None))
    results = (SynthesisResult("seg_0001", SynthStatus.FAILED, error="炸了"),)
    ws = Workspace(tmp_path / "run")
    aligned = align_segments(results, transcript, AlignSpec(), ws)
    assert aligned[0].status is SynthStatus.FAILED
    assert aligned[0].error == "炸了"


# ── 全链集成（假后端跑完整流程） ──

class _FakeSynth:
    def __init__(self, **kwargs):
        self.calls = 0

    def load(self):
        pass

    def unload(self):
        pass

    def synthesize(self, text, ref_audio, output_path):
        self.calls += 1
        Path(output_path).write_bytes(f"RIFF{self.calls}".encode())
        return True


def _make_job(tmp_path, *, cache=False):
    (tmp_path / "input.mp4").write_bytes(b"media")
    (tmp_path / "ref.wav").write_bytes(b"ref")
    (tmp_path / "segments.json").write_text(json.dumps([
        {"start": 0.0, "end": 1.0, "text": "第一句"},
        {"start": 2.0, "end": 3.0, "text": "第二句", "speaker": 0},
    ], ensure_ascii=False), encoding="utf-8")
    return JobSpec.model_validate({
        "input": {"path": str(tmp_path / "input.mp4")},
        "output": {"path": str(tmp_path / "out.mp4")},
        "transcript": {"source": TranscriptSource.JSON.value, "path": str(tmp_path / "segments.json")},
        "voice": {"ref_audio": str(tmp_path / "ref.wav")},
        "runtime": {"cache": cache},
    })


def test_run_job_full_fake_pipeline(tmp_path, monkeypatch):
    import videodub.pipeline.runner as runner
    from videodub.pipeline.cache import Cache as RealCache
    from videodub.ffmpeg.probe import MediaAsset

    monkeypatch.setattr(runner, "probe_media", lambda p: MediaAsset(
        path=Path(p), kind="video", duration=5.0, has_video=True, has_audio=True,
        audio_sample_rate=48000, audio_channels=2,
    ))
    monkeypatch.setattr(runner, "render", lambda *a, **kw: Path(a[2]).write_bytes(b"final"))
    monkeypatch.setattr(runner, "ensure_ffmpeg_available", lambda: None)
    monkeypatch.setattr(runner, "Cache", lambda enabled: RealCache(root=tmp_path / ".cache", enabled=enabled))
    monkeypatch.setattr("videodub.pipeline.synthesis.get_synthesizer", lambda spec: _FakeSynth())
    monkeypatch.setattr("videodub.pipeline.synthesis.probe_duration", lambda p: 0.5)
    monkeypatch.setattr("videodub.pipeline.synthesis.stretch_audio_to_duration",
                        lambda src, dst, target: Path(dst).write_bytes(b"x"))
    monkeypatch.setattr("videodub.pipeline.synthesis.post_process_audio",
                        lambda src, dst, **kw: Path(dst).write_bytes(b"x"))

    job = _make_job(tmp_path, cache=True)
    report = runner.run_job(job)

    # 报告内容
    assert [s["name"] for s in report["stages"]] == [
        "resolve_media", "load_transcript", "build_voice_plan", "synthesize",
        "align", "build_mix_plan", "render",
    ]
    assert len(report["segments"]) == 2
    row = report["segments"][0]
    assert row["plan_action"] == "synthesize"
    assert row["synth_status"] == "ok"
    assert row["align_status"] == "ok"
    assert report["summary"]["synth_ok"] == 2
    assert report["output"]["exists"] is True
    assert report["job"]["voice"]["ref_audio"].endswith("ref.wav")

    # 工件文件
    run_dir = next((tmp_path / "out.mp4").parent.glob(".videodub/run-*"))
    for name in ("report.json", "transcript.json", "voice_plan.json", "config.snapshot.json", "mix_plan.json"):
        assert (run_dir / name).exists(), name
    assert not (run_dir / "tts").exists()  # 重产物默认清理

    # 第二次运行：TTS 缓存命中
    report2 = runner.run_job(_make_job(tmp_path, cache=True))
    assert report2["cache"]["tts_hits"] == 2
    assert report2["cache"]["asr_hits"] == 0


def test_run_job_dry_run_skips_heavy_steps(tmp_path, monkeypatch):
    import videodub.pipeline.runner as runner
    from videodub.ffmpeg.probe import MediaAsset

    monkeypatch.setattr(runner, "probe_media", lambda p: MediaAsset(
        path=Path(p), kind="video", duration=5.0, has_video=True, has_audio=True,
        audio_sample_rate=48000, audio_channels=2,
    ))
    monkeypatch.setattr(runner, "ensure_ffmpeg_available", lambda: None)

    job = _make_job(tmp_path)
    job.runtime.dry_run = True
    report = runner.run_job(job)

    assert report["dry_run"] is True
    assert [s["name"] for s in report["stages"]] == ["resolve_media", "load_transcript", "build_voice_plan"]
    assert report["segments"][0]["plan_action"] == "synthesize"
    assert "synth_status" not in report["segments"][0]