"""后端注册表 — 按配置取 ASR / TTS 适配器

新增后端：加一个适配器文件 + 在此登记 + 跑 contract 测试，流水线不改。
"""

from __future__ import annotations

from videodub.backends.asr_funasr import FunAsrTranscriber
from videodub.backends.asr_whisper import WhisperTranscriber
from videodub.backends.base import Synthesizer, Transcriber
from videodub.backends.tts_api import ApiSynthesizer
from videodub.backends.tts_voxcpm import VoxCpmSynthesizer
from videodub.config.job_spec import (
    ASRBackend,
    TranscriptSpec,
    TTSMode,
    TTSSpec,
    resolve_model_name,
)

TRANSCRIBER_REGISTRY: dict[str, type[Transcriber]] = {
    "funasr": FunAsrTranscriber,
    "whisper": WhisperTranscriber,
}

SYNTHESIZER_REGISTRY: dict[str, type[Synthesizer]] = {
    "local": VoxCpmSynthesizer,
    "api": ApiSynthesizer,
}


def get_transcriber(spec: TranscriptSpec) -> Transcriber:
    """按 TranscriptSpec 构建 ASR 适配器"""
    backend = spec.backend.value
    try:
        adapter_class = TRANSCRIBER_REGISTRY[backend]
    except KeyError:
        raise ValueError(f"不支持的 ASR 后端: {backend}，可选: {', '.join(TRANSCRIBER_REGISTRY)}") from None

    model_name = resolve_model_name(spec.backend, spec.model_name)
    if spec.backend is ASRBackend.FUNASR:
        return adapter_class(
            model_name=model_name,
            device=spec.device,
            enable_diarization=spec.diarize,
            max_speakers=spec.max_speakers,
        )
    return adapter_class(
        model_name=model_name,
        device=spec.device,
        compute_type=spec.compute_type,
        source_language_code=spec.language,
    )


def get_synthesizer(spec: TTSSpec) -> Synthesizer:
    """按 TTSSpec 构建 TTS 适配器"""
    mode = spec.mode.value
    try:
        adapter_class = SYNTHESIZER_REGISTRY[mode]
    except KeyError:
        raise ValueError(f"不支持的 TTS 模式: {mode}，可选: {', '.join(SYNTHESIZER_REGISTRY)}") from None

    if spec.mode is TTSMode.LOCAL:
        return adapter_class(device=spec.device, inference_steps=spec.inference_steps)
    return adapter_class(base_url=spec.api_base_url, api_key=spec.api_key, model_name=spec.api_model_name)