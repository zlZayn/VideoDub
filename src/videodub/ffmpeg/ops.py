"""音频操作 — 时域拉伸 / 音量匹配 / 格式转换

行为与旧 core/audio_io.py 保持一致（已随重构验证）。
"""

from __future__ import annotations

import os
import shutil

from videodub.ffmpeg.probe import probe_duration
from videodub.ffmpeg.runner import run_ffmpeg_command
from videodub.utils.logger import log


def build_atempo_chain(speed_ratio: float) -> list[str]:
    """构建 atempo 滤镜链（单个 atempo 范围 [0.5, 2.0]，超出级联）"""
    filter_chain = []
    remaining_ratio = speed_ratio
    while remaining_ratio > 2.0:
        filter_chain.append("atempo=2.0")
        remaining_ratio /= 2.0
    while remaining_ratio < 0.5:
        filter_chain.append("atempo=0.5")
        remaining_ratio /= 0.5
    filter_chain.append(f"atempo={remaining_ratio:.4f}")
    return filter_chain


def stretch_audio_to_duration(
    input_audio_path: str,
    output_audio_path: str,
    target_duration_seconds: float,
) -> None:
    """时域拉伸：保持音高不变，将输入音频时长调整为目标时长

    差异在 3% 以内直接复制，不做处理（避免不必要的音质损失）。
    """
    current_duration = probe_duration(input_audio_path)
    if current_duration <= 0:
        shutil.copy2(input_audio_path, output_audio_path)
        return

    speed_ratio = current_duration / target_duration_seconds

    # 差异在 3% 以内，直接复制
    if abs(speed_ratio - 1.0) < 0.03:
        shutil.copy2(input_audio_path, output_audio_path)
        return

    run_ffmpeg_command(
        ["-y", "-i", input_audio_path,
         "-filter:a", ",".join(build_atempo_chain(speed_ratio)),
         "-vn", output_audio_path],
        f"时域拉伸 ×{1/speed_ratio:.2f}"
    )


def measure_average_volume(audio_file_path: str) -> float:
    """测量音频的平均音量（dB），使用 volumedetect 滤镜，失败返回 0.0"""
    import subprocess
    result = subprocess.run(
        ["ffmpeg", "-i", audio_file_path, "-af", "volumedetect",
         "-vn", "-sn", "-dn", "-f", "null", "NUL"],
        capture_output=True, text=True, check=False
    )
    output = result.stderr + result.stdout
    for line in output.split("\n"):
        if "mean_volume" in line:
            try:
                return float(line.split("mean_volume:")[1].strip().split(" ")[0])
            except (ValueError, IndexError):
                pass
    return 0.0


def post_process_audio(
    input_audio_path: str,
    output_audio_path: str,
    target_volume_db: float = -10.7,
    fade_in_ms: int = 50,
    fade_out_ms: int = 50,
) -> None:
    """音频后处理：精确音量匹配 + 首尾淡入淡出

    先测量平均音量，再用 volume 滤镜精确放大到目标音量（比 loudnorm 单遍准确）。
    """
    audio_duration = probe_duration(input_audio_path)
    if audio_duration <= 0:
        shutil.copy2(input_audio_path, output_audio_path)
        return

    current_volume = measure_average_volume(input_audio_path)
    volume_gain_db = target_volume_db - current_volume

    filter_chain = []
    if abs(volume_gain_db) > 0.1:
        filter_chain.append(f"volume={volume_gain_db:.2f}dB")
    if fade_in_ms > 0 and audio_duration > fade_in_ms / 1000.0:
        filter_chain.append(f"afade=t=in:st=0:d={fade_in_ms/1000.0:.3f}")
    if fade_out_ms > 0 and audio_duration > fade_out_ms / 1000.0:
        fade_start = max(0, audio_duration - fade_out_ms / 1000.0)
        filter_chain.append(f"afade=t=out:st={fade_start:.3f}:d={fade_out_ms/1000.0:.3f}")

    if not filter_chain:
        shutil.copy2(input_audio_path, output_audio_path)
        return

    run_ffmpeg_command(
        ["-y", "-i", input_audio_path,
         "-filter:a", ",".join(filter_chain),
         "-vn", output_audio_path],
        f"音量匹配(当前{current_volume:.1f}dB→目标{target_volume_db:.1f}dB, 增益{volume_gain_db:+.1f}dB)"
        f" + 淡入{fade_in_ms}ms/淡出{fade_out_ms}ms"
    )


# soundfile 库可直接读取的格式（VoxCPM2 依赖）
_SOUNDFILE_SUPPORTED_EXTENSIONS = {".wav", ".flac", ".ogg"}


def convert_audio_to_wav(
    input_audio_path: str,
    output_wav_path: str,
    sample_rate: int = 48000,
    channels: int = 1,
) -> None:
    """转换音频格式为 WAV（m4a/mp3/aac 等 → pcm_s16le）"""
    run_ffmpeg_command(
        ["-y", "-i", input_audio_path,
         "-acodec", "pcm_s16le",
         "-ar", str(sample_rate),
         "-ac", str(channels),
         output_wav_path],
        f"音频格式转换 → WAV ({sample_rate}Hz, {channels}声道)"
    )


def ensure_wav_format(audio_path: str, working_directory: str) -> str:
    """确保音频是 soundfile 支持的格式（WAV/FLAC/OGG），不支持则转临时 WAV"""
    ext = os.path.splitext(audio_path)[1].lower()
    if ext in _SOUNDFILE_SUPPORTED_EXTENSIONS:
        return audio_path

    basename = os.path.splitext(os.path.basename(audio_path))[0]
    converted_path = os.path.join(working_directory, f"{basename}_converted.wav")
    convert_audio_to_wav(audio_path, converted_path)
    log("音频", f"参考音频格式 {ext} 不支持 soundfile，已自动转换为 WAV: {os.path.basename(converted_path)}")
    return converted_path