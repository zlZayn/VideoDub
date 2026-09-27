"""后端适配器 contract 测试 — 全部 mock 模型，不调用真实推理

通过向 sys.modules 注入假模型包（funasr / faster_whisper / modelscope / voxcpm），
不依赖这些包是否安装。
"""

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from videodub.backends.asr_funasr import FunAsrTranscriber
from videodub.backends.asr_whisper import WhisperTranscriber
from videodub.backends.base import Synthesizer, Transcriber
from videodub.backends.registry import get_synthesizer, get_transcriber
from videodub.backends.tts_api import ApiSynthesizer
from videodub.backends.tts_voxcpm import VoxCpmSynthesizer
from videodub.config.job_spec import ASRBackend, TranscriptSpec, TTSMode, TTSSpec


def _inject_module(monkeypatch, name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


class _FakeAutoModel:
    """可注入的 AutoModel：接受任意构造参数，generate 返回注入的 results"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def generate(self, input=None, **kwargs):
        raise NotImplementedError


class _FakeClient:
    """带上下文协议的假 httpx.Client"""

    def __init__(self, response):
        self.response = response
        self.last_args = ()
        self.last_kwargs = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, *args, **kwargs):
        self.last_args = args
        self.last_kwargs = kwargs
        return self.response


# ── FunASR ──

def test_funasr_diarization_transcript(monkeypatch):
    class FakeAutoModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def generate(self, input=None, **kwargs):
            return [{"sentence_info": [
                {"sentence": "你好", "start": 100, "end": 800, "spk": 0},
                {"sentence": "再见", "start": 900, "end": 1500, "spk": 1},
                {"sentence": "", "start": 1600, "end": 1700, "spk": 0},
            ]}]

    _inject_module(monkeypatch, "funasr", AutoModel=FakeAutoModel)
    transcriber = FunAsrTranscriber(enable_diarization=True, max_speakers=2)

    transcript = transcriber.transcribe("audio.wav")

    assert isinstance(transcriber, Transcriber)
    assert transcript.source == "funasr"
    assert len(transcript.segments) == 2  # 空文本被过滤
    assert transcript.segments[0].id == "seg_0001"
    assert transcript.segments[0].range.start == 0.1
    assert transcript.segments[0].range.end == 0.8
    assert transcript.segments[0].speaker == "SPEAKER_0"
    assert transcript.segments[1].speaker == "SPEAKER_1"
    assert transcript.speakers == ("SPEAKER_0", "SPEAKER_1")


def test_funasr_diarization_splits_at_inner_silence(monkeypatch):
    """句内静音 >= 阈值处细切：说话人继承、时间取片内首尾字符时间戳"""
    class FakeAutoModel(_FakeAutoModel):
        def generate(self, input=None, **kwargs):
            # "我们这里是药店，买酒到隔壁，" 12 个非标点字符；"药店"后 300ms 静音
            return [{
                "sentence_info": [
                    {"text": "我们这里是药店，买酒到隔壁，", "start": 400, "end": 3000, "spk": 1},
                ],
                "timestamp": [
                    [400, 600], [600, 800], [800, 1000], [1000, 1200], [1200, 1400], [1400, 1600],
                    [1600, 1800],
                    [2100, 2300], [2300, 2500], [2500, 2700], [2700, 2900], [2900, 3000],
                ],
            }]

    _inject_module(monkeypatch, "funasr", AutoModel=FakeAutoModel)
    transcriber = FunAsrTranscriber(enable_diarization=True, split_silence_ms=200)

    transcript = transcriber.transcribe("audio.wav")

    assert len(transcript.segments) == 2
    assert transcript.segments[0].text == "我们这里是药店，"
    assert transcript.segments[0].range.start == 0.4
    assert transcript.segments[0].range.end == 1.8
    assert transcript.segments[1].text == "买酒到隔壁，"
    assert transcript.segments[1].range.start == 2.1
    assert transcript.segments[1].range.end == 3.0
    assert transcript.segments[0].speaker == "SPEAKER_1"  # 说话人继承
    assert transcript.segments[1].speaker == "SPEAKER_1"


def test_funasr_diarization_silence_split_skips_misaligned(monkeypatch):
    """时间戳数与字符数不一致时该句不切（宁可漏切不可错切）"""
    class FakeAutoModel(_FakeAutoModel):
        def generate(self, input=None, **kwargs):
            return [{
                "sentence_info": [
                    {"text": "我们这里是药店买酒到隔壁", "start": 400, "end": 3000, "spk": 0},
                ],
                "timestamp": [[400, 600], [600, 800]],  # 只有 2 个时间戳，字符 11 个
            }]

    _inject_module(monkeypatch, "funasr", AutoModel=FakeAutoModel)
    transcriber = FunAsrTranscriber(enable_diarization=True, split_silence_ms=200)

    transcript = transcriber.transcribe("audio.wav")

    assert len(transcript.segments) == 1
    assert transcript.segments[0].text == "我们这里是药店买酒到隔壁"
    assert transcript.segments[0].range.end == 3.0  # 原始时间不变


def test_funasr_no_diarization_timestamp_split(monkeypatch):
    class FakeAutoModel(_FakeAutoModel):
        def generate(self, input=None, **kwargs):
            return [{
                "text": "你 好 世 界 再 见",
                "timestamp": [[0, 200], [200, 400], [400, 600], [600, 800], [900, 1100], [1100, 1300]],
            }]

    _inject_module(monkeypatch, "funasr", AutoModel=FakeAutoModel)
    transcriber = FunAsrTranscriber(min_silence_ms=300)  # 400-600 与 600-800 间隙 100ms，不切

    transcript = transcriber.transcribe("audio.wav")

    assert len(transcript.segments) == 1
    assert transcript.segments[0].text == "你好世界再见"


def test_funasr_no_timestamps_fallback(monkeypatch):
    class FakeAutoModel(_FakeAutoModel):
        def generate(self, input=None, **kwargs):
            return [{"text": "整 句", "timestamp": []}]

    _inject_module(monkeypatch, "funasr", AutoModel=FakeAutoModel)
    transcript = FunAsrTranscriber().transcribe("audio.wav")
    assert len(transcript.segments) == 1
    assert transcript.segments[0].range.start == 0.0
    assert transcript.segments[0].range.end == 0.0


def test_funasr_empty_result(monkeypatch):
    class FakeAutoModel(_FakeAutoModel):
        def generate(self, input=None, **kwargs):
            return []

    _inject_module(monkeypatch, "funasr", AutoModel=FakeAutoModel)
    transcript = FunAsrTranscriber().transcribe("audio.wav")
    assert transcript.segments == ()


# ── faster-whisper ──

def test_whisper_transcribe(monkeypatch):
    def fake_model_init(self, model_path, device=None, compute_type=None):
        self.path = model_path

    def fake_transcribe(self, audio, language=None, beam_size=None, vad_filter=None, vad_parameters=None):
        info = SimpleNamespace(language="zh", language_probability=0.95)
        segments = [
            SimpleNamespace(start=0.0, end=1.2, text=" 第一句 "),
            SimpleNamespace(start=2.0, end=3.5, text="第二句"),
        ]
        return iter(segments), info

    fake_whisper = SimpleNamespace(WhisperModel=type(
        "FakeWhisper", (), {"__init__": fake_model_init, "transcribe": fake_transcribe}
    ))
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_whisper)
    _inject_module(monkeypatch, "modelscope")
    _inject_module(monkeypatch, "modelscope.hub")
    _inject_module(
        monkeypatch, "modelscope.hub.snapshot_download",
        snapshot_download=lambda model_id: f"/models/{model_id}",
    )

    transcriber = WhisperTranscriber(device="cpu", compute_type="int8")
    transcript = transcriber.transcribe("audio.wav")

    assert isinstance(transcriber, Transcriber)
    assert transcript.language == "zh"
    assert transcript.source == "whisper"
    assert len(transcript.segments) == 2
    assert transcript.segments[0].text == "第一句"  # 去空白


def test_whisper_unknown_model_raises(monkeypatch):
    with pytest.raises(ValueError, match="不支持的 whisper 模型"):
        WhisperTranscriber(model_name="nope").transcribe("audio.wav")


# ── VoxCPM 本地 ──

def test_voxcpm_synthesize_ok(monkeypatch, tmp_path):
    fake_voxcpm = SimpleNamespace(VoxCPM=SimpleNamespace(
        from_pretrained=lambda *a, **kw: SimpleNamespace(
            generate=lambda **kw: np.zeros((48000,), dtype=np.float32),
            tts_model=SimpleNamespace(sample_rate=48000),
        ),
    ))
    monkeypatch.setitem(sys.modules, "voxcpm", fake_voxcpm)

    synthesizer = VoxCpmSynthesizer(device="cpu", inference_steps=10)
    assert isinstance(synthesizer, Synthesizer)
    synthesizer.load()
    output = str(tmp_path / "out.wav")
    ok = synthesizer.synthesize("你好", ref_audio="ref.wav", output_path=output)

    assert ok is True
    assert Path(output).exists()
    synthesizer.unload()
    assert synthesizer._model is None


def test_voxcpm_synthesize_before_load(monkeypatch, tmp_path):
    synthesizer = VoxCpmSynthesizer()
    ok = synthesizer.synthesize("你好", None, str(tmp_path / "out.wav"))
    assert ok is False


def test_voxcpm_generate_error(monkeypatch, tmp_path):
    def boom(**kwargs):
        raise RuntimeError("模型崩溃")

    fake_voxcpm = SimpleNamespace(VoxCPM=SimpleNamespace(
        from_pretrained=lambda *a, **kw: SimpleNamespace(generate=boom, tts_model=SimpleNamespace(sample_rate=48000)),
    ))
    monkeypatch.setitem(sys.modules, "voxcpm", fake_voxcpm)

    synthesizer = VoxCpmSynthesizer()
    synthesizer.load()
    ok = synthesizer.synthesize("你好", None, str(tmp_path / "out.wav"))
    assert ok is False


# ── TTS API ──

def test_tts_api_synthesize_ok(tmp_path):
    ref_file = tmp_path / "ref.wav"
    ref_file.write_bytes(b"fake-audio")
    output = tmp_path / "out.wav"

    fake_client = _FakeClient(SimpleNamespace(status_code=200, content=b"RIFF...data"))
    with patch("httpx.Client", return_value=fake_client):
        synthesizer = ApiSynthesizer(base_url="http://localhost:8000", api_key="k", model_name="voxcpm2")
        assert isinstance(synthesizer, Synthesizer)
        ok = synthesizer.synthesize("你好", str(ref_file), str(output))

    assert ok is True
    assert output.read_bytes() == b"RIFF...data"
    # ref_audio 被编码为 data URL
    payload = fake_client.last_kwargs["json"]
    assert payload["ref_audio"].startswith("data:audio/wav;base64,")
    assert fake_client.last_args[0] == "http://localhost:8000/v1/audio/speech"


def test_tts_api_http_error(tmp_path):
    fake_client = _FakeClient(SimpleNamespace(status_code=500, text="boom"))
    with patch("httpx.Client", return_value=fake_client):
        synthesizer = ApiSynthesizer("http://x", "k", "m")
        ok = synthesizer.synthesize("你好", None, str(tmp_path / "out.wav"))
    assert ok is False


def test_tts_api_ref_audio_passthrough_url(tmp_path):
    fake_client = _FakeClient(SimpleNamespace(status_code=200, content=b"data"))
    with patch("httpx.Client", return_value=fake_client):
        synthesizer = ApiSynthesizer("http://x", "k", "m")
        synthesizer.synthesize("你好", "http://host/ref.wav", str(tmp_path / "out.wav"))
    payload = fake_client.last_kwargs["json"]
    assert payload["ref_audio"] == "http://host/ref.wav"


# ── 注册表 ──

def test_registry_transcriber_funasr():
    spec = TranscriptSpec(backend=ASRBackend.FUNASR, diarize=True, max_speakers=3, model_name="paraformer-zh")
    adapter = get_transcriber(spec)
    assert isinstance(adapter, FunAsrTranscriber)
    assert adapter.enable_diarization is True
    assert adapter.max_speakers == 3


def test_registry_transcriber_whisper():
    spec = TranscriptSpec(backend=ASRBackend.WHISPER, compute_type="int8", language="en")
    adapter = get_transcriber(spec)
    assert isinstance(adapter, WhisperTranscriber)
    assert adapter.compute_type == "int8"
    assert adapter.source_language_code == "en"


def test_registry_synthesizer_local():
    spec = TTSSpec(mode=TTSMode.LOCAL, device="cuda", inference_steps=20)
    adapter = get_synthesizer(spec)
    assert isinstance(adapter, VoxCpmSynthesizer)
    assert adapter.device == "cuda"
    assert adapter.inference_steps == 20


def test_registry_synthesizer_api():
    spec = TTSSpec(mode=TTSMode.API, api_base_url="http://srv:8000", api_model_name="m2")
    adapter = get_synthesizer(spec)
    assert isinstance(adapter, ApiSynthesizer)
    assert adapter.base_url == "http://srv:8000"


def test_registry_unknown_raises(monkeypatch):
    from videodub.backends import registry
    monkeypatch.delitem(registry.TRANSCRIBER_REGISTRY, "funasr")
    with pytest.raises(ValueError, match="不支持的 ASR 后端"):
        get_transcriber(TranscriptSpec(backend=ASRBackend.FUNASR))