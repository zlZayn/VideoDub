"""TTS API 适配器 — OpenAI 兼容 /v1/audio/speech 接口（vllm-omni）

行为与旧 core/voice_cloner 的 API 模式保持一致。
"""

from __future__ import annotations

import base64

from videodub.utils.logger import log_warning

_MIME_TYPE_MAP = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
}


def _encode_audio_to_base64_data_url(audio_file_path: str) -> str:
    """将本地音频编码为 data URL（API 模式传参考音频用）"""
    file_extension = audio_file_path.lower().rsplit(".", 1)[-1]
    mime_type = _MIME_TYPE_MAP.get(file_extension, "audio/wav")
    with open(audio_file_path, "rb") as f:
        base64_content = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime_type};base64,{base64_content}"


class ApiSynthesizer:
    """HTTP API 音色克隆（需部署 vllm-omni 服务）"""

    mode = "api"

    def __init__(self, base_url: str, api_key: str, model_name: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model_name = model_name

    def load(self) -> None:
        """无模型加载（无状态服务）"""

    def unload(self) -> None:
        """无模型卸载"""

    def synthesize(self, text: str, ref_audio: str | None, output_path: str) -> bool:
        """请求 API 合成单句语音，成功返回 True"""
        import httpx

        request_payload = {
            "model": self.model_name,
            "input": text,
            "voice": "default",
            "response_format": "wav",
            "stream": True,
        }
        if ref_audio:
            if ref_audio.startswith(("http://", "https://", "data:")):
                request_payload["ref_audio"] = ref_audio
            else:
                request_payload["ref_audio"] = _encode_audio_to_base64_data_url(ref_audio)

        api_endpoint = f"{self.base_url}/v1/audio/speech"
        try:
            with httpx.Client(timeout=300) as client:
                response = client.post(
                    api_endpoint,
                    json=request_payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
            if response.status_code != 200:
                log_warning(f"TTS 错误 {response.status_code}: {response.text[:200]}")
                return False
            with open(output_path, "wb") as f:
                f.write(response.content)
            return True
        except Exception as error:
            log_warning(f"TTS 异常: {error}")
            return False