"""VoxCPM2 音色克隆适配器 — 本地推理

行为与旧 core/voice_cloner 保持一致：
- 输出 48kHz（不是 24kHz）
- denoiser 禁用（cudnn 兼容问题）
- load() 由 pipeline 在 TTS 阶段前调用，unload() 后释放显存
"""

from __future__ import annotations

import soundfile as sf

from videodub.utils.logger import log, log_stage_header, log_warning

# VoxCPM2 输出采样率（注意：是 48000，不是 24000）
VOXCPM2_SAMPLE_RATE = 48000


class VoxCpmSynthesizer:
    """本地 VoxCPM2 音色克隆"""

    mode = "local"

    def __init__(self, device: str = "cpu", inference_steps: int = 10) -> None:
        self.device = device
        self.inference_steps = inference_steps
        self._model = None

    def load(self) -> None:
        """加载 VoxCPM2 模型（幂等）"""
        if self._model is not None:
            return
        from voxcpm import VoxCPM

        log_stage_header("TTS", f"加载 VoxCPM2 模型, 设备: {self.device}")
        self._model = VoxCPM.from_pretrained(
            "openbmb/VoxCPM2", device=self.device, load_denoiser=False
        )
        log("TTS", "VoxCPM2 模型加载完成（已禁用 denoiser）")

    def unload(self) -> None:
        """卸载模型（释放显存）"""
        self._model = None

    def synthesize(self, text: str, ref_audio: str | None, output_path: str) -> bool:
        """克隆单句语音到 output_path，成功返回 True"""
        if self._model is None:
            log_warning("VoxCPM2 模型未加载，请先调用 load()")
            return False
        try:
            generate_kwargs = {"text": text, "inference_timesteps": self.inference_steps}
            if ref_audio:
                generate_kwargs["reference_wav_path"] = ref_audio
            waveform = self._model.generate(**generate_kwargs)
            actual_sample_rate = self._model.tts_model.sample_rate
            sf.write(output_path, waveform, actual_sample_rate)
            return True
        except Exception as error:  # noqa: BLE001 — 覆盖本地推理全量异常（torch / cudnn / 显存）与 soundfile 落盘，收窄等于赌第三方异常面
            log_warning(f"生成失败: {error}")
            return False