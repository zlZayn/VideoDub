"""JobSpec — 一次配音任务的完整描述（Pydantic 边界模型）

分工：本模块负责"用户输入边界"的解析与校验；
领域模型（domain/）负责内部产物契约，不混用。
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

AUDIO_ONLY_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a"}


class ASRBackend(str, Enum):
    FUNASR = "funasr"
    WHISPER = "whisper"


class TTSMode(str, Enum):
    LOCAL = "local"
    API = "api"


class TranscriptSource(str, Enum):
    ASR = "asr"
    JSON = "json"
    SUBTITLE = "subtitle"


class MixPolicy(str, Enum):
    """auto = 按旧规则自动检测（keep_background 优先，有保留段则 partial，否则 full）"""

    AUTO = "auto"
    FULL_REPLACE = "full_replace"
    KEEP_BACKGROUND = "keep_background"
    PARTIAL_REPLACE = "partial_replace"


class InputSpec(BaseModel):
    path: Path

    @model_validator(mode="after")
    def _check_exists(self) -> "InputSpec":
        if not self.path.exists():
            raise ValueError(f"输入媒体不存在: {self.path}")
        return self


class OutputSpec(BaseModel):
    path: Path
    audio_only: bool | None = None
    video_codec: str = "copy"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"

    @model_validator(mode="after")
    def _resolve_audio_only(self) -> "OutputSpec":
        if self.audio_only is None:
            self.audio_only = self.path.suffix.lower() in AUDIO_ONLY_EXTENSIONS
        return self


class TranscriptSpec(BaseModel):
    source: TranscriptSource = TranscriptSource.ASR
    path: Path | None = None
    backend: ASRBackend = ASRBackend.FUNASR
    model_name: str | None = None
    device: str = "cpu"
    compute_type: str = "float16"
    language: str | None = None
    diarize: bool = False
    max_speakers: int = Field(default=2, ge=1, le=20)

    @model_validator(mode="after")
    def _check_source_path(self) -> "TranscriptSpec":
        if self.source in (TranscriptSource.JSON, TranscriptSource.SUBTITLE):
            if self.path is None:
                raise ValueError(f"台词来源 {self.source.value} 需要指定 path")
            if not self.path.exists():
                raise ValueError(f"台词文件不存在: {self.path}")
        return self


class VoiceSpec(BaseModel):
    """参考音色：全局一个（ref_audio）或按说话人映射（speaker_map）"""

    ref_audio: Path | None = None
    speaker_map: dict[str, Path | None] = {}

    @model_validator(mode="before")
    @classmethod
    def _coerce_empty_speaker_map(cls, data):
        """TOML 没有 null：speaker_map 值空字符串归一为 None（表示保留原声）"""
        if isinstance(data, dict) and isinstance(data.get("speaker_map"), dict):
            data = {
                **data,
                "speaker_map": {k: (None if v == "" else v) for k, v in data["speaker_map"].items()},
            }
        return data

    @model_validator(mode="after")
    def _check_paths_exist(self) -> "VoiceSpec":
        paths = [self.ref_audio] if self.ref_audio else []
        paths += [p for p in self.speaker_map.values() if p is not None]
        missing = [str(p) for p in paths if not p.exists()]
        if missing:
            raise ValueError(f"参考音频不存在: {', '.join(missing)}")
        return self


class TTSSpec(BaseModel):
    mode: TTSMode = TTSMode.LOCAL
    device: str = "cpu"
    inference_steps: int = Field(default=10, ge=1, le=100)
    api_base_url: str = "http://localhost:8000"
    api_key: str = "sk-empty"
    api_model_name: str = "voxcpm2"


class AlignSpec(BaseModel):
    enable_post_process: bool = True
    target_volume_db: float = -10.7
    fade_in_ms: int = Field(default=50, ge=0)
    fade_out_ms: int = Field(default=50, ge=0)


class MixSpec(BaseModel):
    policy: MixPolicy = MixPolicy.AUTO
    background_volume_ratio: float = Field(default=0.2, ge=0.0, le=1.0)


class RuntimeSpec(BaseModel):
    cache: bool = True
    resume: bool = False
    keep_temp: bool = False
    dry_run: bool = False
    verbose: bool = False


class JobSpec(BaseModel):
    input: InputSpec
    output: OutputSpec
    transcript: TranscriptSpec = TranscriptSpec()
    voice: VoiceSpec = VoiceSpec()
    tts: TTSSpec = TTSSpec()
    align: AlignSpec = AlignSpec()
    mix: MixSpec = MixSpec()
    runtime: RuntimeSpec = RuntimeSpec()

    @model_validator(mode="after")
    def _check_voice_refs(self) -> "JobSpec":
        has_ref = self.voice.ref_audio is not None
        has_map = bool(self.voice.speaker_map)
        if has_ref and has_map:
            raise ValueError("ref_audio 与 speaker_map 二选一，不能同时指定")
        if not has_ref and not has_map:
            raise ValueError("必须指定参考音色：ref_audio（全局）或 speaker_map（分角色）")
        return self


def resolve_model_name(backend: ASRBackend, model_name: str | None) -> str:
    """按后端取默认模型名（None 时）"""
    if model_name:
        return model_name
    return "paraformer-zh" if backend is ASRBackend.FUNASR else "distil-large-v3"