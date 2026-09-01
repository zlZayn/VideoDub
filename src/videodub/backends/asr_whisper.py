"""faster-whisper 适配器 — 多语言识别（模型走魔搭社区）

行为与旧 core/speech_recognizer.recognize_with_whisper 保持一致；
输出改为统一 Transcript 模型。
"""

from __future__ import annotations

from videodub.domain.transcript import Transcript
from videodub.utils.logger import log, log_stage_header

# ModelScope 模型 ID 映射（国内可直连）
_WHISPER_MODELSCOPE_REGISTRY = {
    "tiny": "Systran/faster-whisper-tiny",
    "tiny.en": "Systran/faster-whisper-tiny.en",
    "base": "Systran/faster-whisper-base",
    "base.en": "Systran/faster-whisper-base.en",
    "small": "Systran/faster-whisper-small",
    "small.en": "Systran/faster-whisper-small.en",
    "medium": "Systran/faster-whisper-medium",
    "medium.en": "Systran/faster-whisper-medium.en",
    "large-v3": "Systran/faster-whisper-large-v3",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
    "distil-medium.en": "Systran/faster-whisper-distil-medium.en",
    "distil-small.en": "Systran/faster-whisper-distil-small.en",
}


class WhisperTranscriber:
    """faster-whisper 语音识别（多语言，中文精度不如 FunASR）"""

    backend = "whisper"

    def __init__(
        self,
        model_name: str = "distil-large-v3",
        device: str = "cpu",
        compute_type: str = "float16",
        source_language_code: str | None = None,
        beam_size: int = 5,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.source_language_code = source_language_code
        self.beam_size = beam_size

    def transcribe(self, audio_path: str) -> Transcript:
        """识别音频，返回统一 Transcript"""
        modelscope_id = _WHISPER_MODELSCOPE_REGISTRY.get(self.model_name)
        if not modelscope_id:
            raise ValueError(
                f"不支持的 whisper 模型: {self.model_name}\n"
                f"可选: {', '.join(_WHISPER_MODELSCOPE_REGISTRY.keys())}"
            )

        from faster_whisper import WhisperModel
        from modelscope.hub.snapshot_download import snapshot_download

        log_stage_header("ASR", f"faster-whisper ({self.model_name}), 设备: {self.device}/{self.compute_type}")

        log("ASR", "从魔搭社区下载/加载模型 ...")
        local_model_path = snapshot_download(modelscope_id)
        whisper_model = WhisperModel(local_model_path, device=self.device, compute_type=self.compute_type)

        log("ASR", "识别中 ...")
        segments_iterator, recognition_info = whisper_model.transcribe(
            audio_path,
            language=self.source_language_code,
            beam_size=self.beam_size,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=200),
        )

        recognized_segments = []
        for segment in segments_iterator:
            recognized_segments.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
            })

        language = getattr(recognition_info, "language", None)
        probability = getattr(recognition_info, "language_probability", None)
        log("ASR", f"检测语言: {language}"
            + (f" (置信度 {probability:.0%})" if probability is not None else ""))
        log("ASR", f"识别到 {len(recognized_segments)} 句台词:")
        for seg in recognized_segments:
            log("ASR", f"  [{seg['start']:6.2f}s - {seg['end']:6.2f}s] {seg['text']}")

        return Transcript.from_dicts(recognized_segments, language=language, source="whisper")