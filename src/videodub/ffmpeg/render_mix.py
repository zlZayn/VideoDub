"""混音渲染 — MixPlan + 媒体 → 最终输出（视频 / 纯音频）

build_render_command 是纯函数（可 golden 测试、--print-ffmpeg 复用）；
render 负责探测时长并执行。
"""

from __future__ import annotations

from videodub.domain.models import MixPlan
from videodub.ffmpeg.filters import build_mix_invocation
from videodub.ffmpeg.probe import probe_duration
from videodub.ffmpeg.runner import run_ffmpeg_command
from videodub.utils.logger import log_stage_header, log_success


def build_render_command(
    plan: MixPlan,
    media_path: str,
    output_path: str,
    duration: float,
    *,
    audio_only: bool,
    video_codec: str = "copy",
    audio_codec: str = "aac",
    audio_bitrate: str = "192k",
) -> list[str]:
    """构建最终渲染命令（不含 ffmpeg 前缀）

    视频输出：视频流随主媒体 copy，音频走混音滤镜；
    音频输出：只输出混音结果（pcm_s16le / 48kHz）。
    """
    extra_inputs, filter_expressions, final_label = build_mix_invocation(plan, duration)
    command = [
        "-y",
        "-i",
        media_path,
        *extra_inputs,
        "-filter_complex",
        ";".join(filter_expressions),
    ]
    if audio_only:
        command += [
            "-map",
            final_label,
            "-c:a",
            "pcm_s16le",
            "-ar",
            str(plan.output_sample_rate),
            output_path,
        ]
    else:
        command += [
            "-map",
            "0:v",
            "-map",
            final_label,
            "-c:v",
            video_codec,
            "-c:a",
            audio_codec,
            "-b:a",
            audio_bitrate,
            "-shortest",
            output_path,
        ]
    return command


def render(
    plan: MixPlan,
    media_path: str,
    output_path: str,
    *,
    audio_only: bool,
    video_codec: str = "copy",
    audio_codec: str = "aac",
    audio_bitrate: str = "192k",
) -> None:
    """执行混音渲染（探测时长 + 单次 ffmpeg 调用）"""
    duration = probe_duration(media_path)
    if duration <= 0:
        raise ValueError(f"无法探测媒体时长: {media_path}")
    command = build_render_command(
        plan,
        media_path,
        output_path,
        duration,
        audio_only=audio_only,
        video_codec=video_codec,
        audio_codec=audio_codec,
        audio_bitrate=audio_bitrate,
    )
    log_stage_header("合成", f"混音合成, 模式: {plan.mode.value}")
    run_ffmpeg_command(command, "合成最终输出")
    log_success(f"输出: {output_path}")
