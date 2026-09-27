"""结果缓存 — .cache/videodub/{asr,tts}/<sha256>.<ext>

粒度两级：
- ASR：输入音频 hash + 后端/模型/语言/说话人分离参数 → transcript.json
- TTS：文本 + 参考音频 hash + 模型/推理参数 → 配音 wav

命中即复用，miss 即写入；report 统计命中数。
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from videodub.utils.logger import log


def audio_hash(path: Path | str) -> str:
    """文件 sha256（分块读，适配大文件）"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_hash(*parts: str) -> str:
    """多段文本拼接的 sha256 短哈希"""
    payload = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def asr_cache_key(
    media_path: str,
    *,
    backend: str,
    model: str,
    language: str | None,
    diarize: bool,
    max_speakers: int,
) -> str:
    """ASR 缓存键：输入媒体 hash + 识别参数"""
    _ASR_CACHE_VERSION = "v3"  # 升版以失效旧缓存（v3：diarize 增加句内静音细切）
    return text_hash(
        _ASR_CACHE_VERSION,
        audio_hash(media_path),
        backend,
        model,
        language or "",
        str(diarize),
        str(max_speakers),
    )


def tts_cache_key(
    text: str, ref_audio: str | None, *, mode: str, model: str, steps: int, device: str
) -> str:
    """TTS 缓存键：文本 + 参考音频 hash + 模型参数"""
    ref_hash = audio_hash(ref_audio) if ref_audio else ""
    return text_hash(text, ref_hash, mode, model, str(steps), device)


class Cache:
    """轻量文件缓存"""

    def __init__(
        self, root: Path = Path(".cache/videodub"), enabled: bool = True
    ) -> None:
        self.root = root
        self.enabled = enabled
        self.hits: list[tuple[str, str]] = []  # (group, key)

    def get(self, group: str, key: str, suffix: str = "") -> Path | None:
        """命中返回缓存路径，miss 返回 None。suffix 例如 '.wav' / '.json'"""
        if not self.enabled:
            return None
        candidate = self.root / group / f"{key}{suffix}"
        if candidate.exists():
            self.hits.append((group, key))
            log("缓存", f"命中 {group}: {key[:12]}...")
            return candidate
        return None

    def put(self, group: str, key: str, source: Path, suffix: str = "") -> Path:
        """把产物拷入缓存，返回缓存路径"""
        if not self.enabled:
            return source
        target = self.root / group / f"{key}{suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(source, target)
        return target
