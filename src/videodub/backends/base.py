"""适配器协议 — ASR / TTS 的最小接口契约

注册表 + contract 测试保证一致性，不引入抽象基类的仪式。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from videodub.domain.transcript import Transcript


@runtime_checkable
class Transcriber(Protocol):
    """ASR 适配器：音频 → Transcript"""

    backend: str

    def transcribe(self, audio_path: str) -> Transcript: ...


@runtime_checkable
class Synthesizer(Protocol):
    """TTS 适配器：文本 + 参考音频 → WAV 文件（48kHz）"""

    mode: str

    def load(self) -> None: ...
    def unload(self) -> None: ...
    def synthesize(
        self, text: str, ref_audio: str | None, output_path: str
    ) -> bool: ...
