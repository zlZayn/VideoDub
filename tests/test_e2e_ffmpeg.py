"""端到端测试 — 真实 ffmpeg 执行 + 假 TTS 后端

验证新渲染链路（单次调用混音 / aformat 就地滤波 / 视频 copy）在真实 ffmpeg 下成立。
需要 ffmpeg + ffprobe 在 PATH 中，缺失则跳过。
"""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from videodub.config.job_spec import JobSpec
from videodub.ffmpeg.probe import probe_duration, probe_media

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="需要 ffmpeg/ffprobe",
)


class _SineSynthesizer:
    """假 TTS：1 秒 440Hz 正弦，48kHz 单声道真实 wav"""

    def __init__(self, **kwargs):
        pass

    def load(self):
        pass

    def unload(self):
        pass

    def synthesize(self, text, ref_audio, output_path):
        wave = 0.3 * np.sin(2 * np.pi * 440 * np.arange(48000) / 48000).astype(np.float32)
        sf.write(output_path, wave, 48000)
        return True


@pytest.fixture
def media(tmp_path):
    """3 秒合成视频（testsrc2 画面 + 300Hz 正弦音）"""
    video = tmp_path / "input.mp4"
    subprocess_cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000",
        "-t", "3", "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", str(video),
    ]
    import subprocess
    result = subprocess.run(subprocess_cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-500:]
    (tmp_path / "ref.wav").write_bytes(b"ref")


def _job(tmp_path, segments, *, voice, output_name="out.mp4", cache=False, mix=None):
    seg_file = tmp_path / "segments.json"
    seg_file.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
    job = {
        "input": {"path": str(tmp_path / "input.mp4")},
        "output": {"path": str(tmp_path / output_name)},
        "transcript": {"source": "json", "path": str(seg_file)},
        "voice": voice,
        "runtime": {"cache": cache},
    }
    if mix:
        job["mix"] = mix
    return JobSpec.model_validate(job)


SEGMENTS = [
    {"start": 0.5, "end": 1.2, "text": "第一句"},
    {"start": 1.5, "end": 2.6, "text": "第二句", "speaker": 0},
]


def test_e2e_full_replace_real_ffmpeg(tmp_path, media, monkeypatch):
    import videodub.pipeline.synthesis as synthesis
    from videodub.pipeline.runner import run_job

    monkeypatch.setattr(synthesis, "get_synthesizer", lambda spec: _SineSynthesizer())

    report = run_job(_job(tmp_path, SEGMENTS, voice={"ref_audio": str(tmp_path / "ref.wav")}))

    output = tmp_path / "out.mp4"
    assert output.exists()
    assert abs(probe_duration(str(output)) - 3.0) < 0.5
    asset = probe_media(str(output))
    assert asset.has_video and asset.has_audio
    assert report["summary"]["synth_ok"] == 2
    assert report["segments"][0]["align_status"] == "ok"


def test_e2e_partial_replace_keeps_original(tmp_path, media, monkeypatch):
    """说话人 0 换、说话人 1 保留 → partial_replace 模式，原音轨静音段被替换"""
    import videodub.pipeline.synthesis as synthesis
    from videodub.pipeline.runner import run_job

    monkeypatch.setattr(synthesis, "get_synthesizer", lambda spec: _SineSynthesizer())
    segments = [
        {"start": 0.5, "end": 1.2, "text": "第一句", "speaker": 0},
        {"start": 1.5, "end": 2.6, "text": "第二句", "speaker": 1},
    ]
    report = run_job(_job(
        tmp_path, segments,
        voice={"speaker_map": {"SPEAKER_0": str(tmp_path / "ref.wav")}},
    ))

    output = tmp_path / "out.mp4"
    assert output.exists()
    assert report["summary"]["keep_original"] == 1
    assert report["summary"]["synth_ok"] == 1
    run_dir = tmp_path / ".videodub"
    mix_plan = json.loads(next(run_dir.glob("run-*/mix_plan.json")).read_text(encoding="utf-8"))
    assert mix_plan["mode"] == "partial_replace"
    assert len(mix_plan["clips"]) == 1


def test_e2e_keep_background_real_ffmpeg(tmp_path, media, monkeypatch):
    import videodub.pipeline.synthesis as synthesis
    from videodub.pipeline.runner import run_job

    monkeypatch.setattr(synthesis, "get_synthesizer", lambda spec: _SineSynthesizer())
    report = run_job(_job(
        tmp_path, SEGMENTS,
        voice={"ref_audio": str(tmp_path / "ref.wav")},
        output_name="bg.mp4",
        mix={"policy": "keep_background", "background_volume_ratio": 0.5},
    ))

    output = tmp_path / "bg.mp4"
    assert output.exists()
    assert abs(probe_duration(str(output)) - 3.0) < 0.5
    run_dir = tmp_path / ".videodub"
    mix_plan = json.loads(next(run_dir.glob("run-*/mix_plan.json")).read_text(encoding="utf-8"))
    assert mix_plan["mode"] == "keep_background"