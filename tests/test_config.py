"""JobSpec / TOML 加载测试

用 tmp_path 建真实文件，不碰模型与 FFmpeg。
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from videodub.config.job_spec import (
    ASRBackend,
    MixPolicy,
    TranscriptSource,
    TTSMode,
    resolve_model_name,
)
from videodub.config.load_job import load_job

SAMPLE_TOML = """
[input]
path = "input.mp4"

[output]
path = "output_dub.mp4"

[transcript]
source = "asr"
backend = "whisper"
language = "zh"
diarize = true
max_speakers = 3

[voice]
ref_audio = "ref.wav"

[tts]
mode = "api"
inference_steps = 20

[mix]
policy = "keep_background"
background_volume_ratio = 0.3

[runtime]
cache = false
keep_temp = true
"""


@pytest.fixture
def media_files(tmp_path, monkeypatch):
    (tmp_path / "input.mp4").write_bytes(b"fake")
    (tmp_path / "ref.wav").write_bytes(b"fake")
    # 相对路径按 CWD 解析（与真实 CLI 使用一致）
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_job(tmp_path, text=SAMPLE_TOML) -> str:
    path = tmp_path / "job.toml"
    path.write_text(text, encoding="utf-8")
    return str(path)


# ── TOML 加载 ──


def test_toml_load_full_job(media_files):
    job = load_job(_write_job(media_files))
    assert job.input.path.name == "input.mp4"
    assert job.transcript.source is TranscriptSource.ASR
    assert job.transcript.backend is ASRBackend.WHISPER
    assert job.transcript.diarize is True
    assert job.transcript.max_speakers == 3
    assert job.voice.ref_audio.name == "ref.wav"
    assert job.tts.mode is TTSMode.API
    assert job.tts.inference_steps == 20
    assert job.mix.policy is MixPolicy.KEEP_BACKGROUND
    assert job.mix.background_volume_ratio == 0.3
    assert job.runtime.cache is False
    assert job.runtime.keep_temp is True
    # 未在 TOML 中出现的字段走默认值
    assert job.align.target_volume_db == -10.7
    assert job.runtime.dry_run is False


def test_cli_overrides_toml_deep(media_files):
    job_path = _write_job(media_files)
    job = load_job(
        job_path,
        cli_overrides={
            "mix": {"policy": "full_replace"},
            "transcript": {"diarize": False},
            "output": {"path": "out_x.mp4"},
        },
    )
    assert job.mix.policy is MixPolicy.FULL_REPLACE
    assert job.transcript.diarize is False
    assert job.output.path.name == "out_x.mp4"
    # 未被覆盖的 TOML 值保留
    assert job.tts.mode is TTSMode.API


def test_cli_only_minimal(media_files):
    job = load_job(
        None,
        cli_overrides={
            "input": {"path": str(media_files / "input.mp4")},
            "output": {"path": "out.mp4"},
            "voice": {"ref_audio": str(media_files / "ref.wav")},
        },
    )
    assert job.transcript.backend is ASRBackend.FUNASR
    assert job.mix.policy is MixPolicy.AUTO


def test_speaker_map_in_toml(media_files):
    (media_files / "ref_a.wav").write_bytes(b"fake")
    job = load_job(
        _write_job(
            media_files,
            """
[input]
path = "input.mp4"

[output]
path = "out.mp4"

[voice.speaker_map]
SPEAKER_0 = "ref_a.wav"
SPEAKER_1 = "ref.wav"
""",
        )
    )
    assert job.voice.speaker_map == {
        "SPEAKER_0": Path("ref_a.wav"),
        "SPEAKER_1": Path("ref.wav"),
    }


def test_speaker_map_empty_string_means_keep_original(media_files):
    """TOML 没有 null：空字符串 = 保留原声（None），不再被当作路径校验"""
    job = load_job(
        _write_job(
            media_files,
            """
[input]
path = "input.mp4"

[output]
path = "out.mp4"

[voice.speaker_map]
SPEAKER_0 = "ref.wav"
SPEAKER_1 = ""
""",
        )
    )
    assert job.voice.speaker_map == {"SPEAKER_0": Path("ref.wav"), "SPEAKER_1": None}


# ── 校验错误 ──


def test_missing_voice_reference_raises(media_files):
    with pytest.raises(ValidationError, match="必须指定参考音色"):
        load_job(
            None,
            cli_overrides={
                "input": {"path": str(media_files / "input.mp4")},
                "output": {"path": "out.mp4"},
            },
        )


def test_both_refs_raises(media_files):
    with pytest.raises(ValidationError, match="二选一"):
        load_job(
            None,
            cli_overrides={
                "input": {"path": str(media_files / "input.mp4")},
                "output": {"path": "out.mp4"},
                "voice": {
                    "ref_audio": str(media_files / "ref.wav"),
                    "speaker_map": {"SPEAKER_0": str(media_files / "ref.wav")},
                },
            },
        )


def test_missing_input_file_raises(tmp_path):
    with pytest.raises(ValidationError, match="输入媒体不存在"):
        load_job(
            None,
            cli_overrides={
                "input": {"path": "no_such.mp4"},
                "output": {"path": "out.mp4"},
                "voice": {"ref_audio": str(tmp_path / "no_ref.wav")},
            },
        )


def test_transcript_source_requires_path(media_files):
    with pytest.raises(ValidationError, match="需要指定 path"):
        load_job(
            None,
            cli_overrides={
                "input": {"path": str(media_files / "input.mp4")},
                "output": {"path": "out.mp4"},
                "voice": {"ref_audio": str(media_files / "ref.wav")},
                "transcript": {"source": "json"},
            },
        )


# ── 派生规则 ──


def test_audio_only_from_extension(media_files):
    job = load_job(
        None,
        cli_overrides={
            "input": {"path": str(media_files / "input.mp4")},
            "output": {"path": "out.wav"},
            "voice": {"ref_audio": str(media_files / "ref.wav")},
        },
    )
    assert job.output.audio_only is True


def test_audio_only_explicit_mp4(media_files):
    job = load_job(
        None,
        cli_overrides={
            "input": {"path": str(media_files / "input.mp4")},
            "output": {"path": "out.mp4", "audio_only": True},
            "voice": {"ref_audio": str(media_files / "ref.wav")},
        },
    )
    assert job.output.audio_only is True


def test_resolve_model_name_defaults():
    assert resolve_model_name(ASRBackend.FUNASR, None) == "paraformer-zh"
    assert resolve_model_name(ASRBackend.WHISPER, None) == "distil-large-v3"
    assert resolve_model_name(ASRBackend.FUNASR, "custom") == "custom"
