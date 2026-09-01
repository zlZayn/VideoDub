"""混音过滤器 — MixPlan → FFmpeg filter_complex（纯函数，可 golden 测试）

改进（相对旧 audio_mixer._build_mix_filter_complex）：
- 由 MixPlan 驱动，渲染层不再理解业务
- 原音轨就地滤波（aformat + volume），不再预提取中间 wav
- FULL_REPLACE 用 lavfi anullsrc 内联静音基底，不再生成 silence_base.wav
- 一次 ffmpeg 调用完成混音
"""

from __future__ import annotations

from videodub.domain.models import MixMode, MixPlan, TimeRange


def build_mute_expression(ranges: tuple[TimeRange, ...]) -> str:
    """构建 volume enable 表达式：被替换段落静音，如 between(t,1.230,3.010)+..."""
    parts = [f"between(t,{r.start:.3f},{r.end:.3f})" for r in ranges]
    return "+".join(parts) if parts else "0"


def build_mix_invocation(
    plan: MixPlan,
    duration: float,
) -> tuple[list[str], list[str], str]:
    """构建混音输入参数与 filter_complex

    Args:
        plan: 混音计划（唯一业务输入）
        duration: 主媒体时长（秒），FULL_REPLACE 静音基底长度用

    Returns:
        (input_arguments, filter_expressions, final_audio_label)
        主媒体（输入 0）由调用方提供，本函数补充基底与片段输入。
    """
    input_arguments: list[str] = []
    filter_expressions: list[str] = []
    mix_labels: list[str] = []
    next_index = 1  # 0 是主媒体输入

    if plan.mode is MixMode.FULL_REPLACE:
        sample_rate = plan.output_sample_rate
        input_arguments += [
            "-f", "lavfi", "-t", f"{duration:.3f}", "-i", f"anullsrc={sample_rate}:cl=mono",
        ]
        filter_expressions.append("[1:a]acopy[base]")
        mix_labels.append("[base]")
        next_index = 2
    elif plan.mode is MixMode.KEEP_BACKGROUND:
        ratio = plan.background_volume_ratio if plan.background_volume_ratio is not None else 0.2
        filter_expressions.append(
            f"[0:a]aformat=sample_rates={plan.output_sample_rate}:channel_layouts=mono,"
            f"volume={ratio}[base]"
        )
        mix_labels.append("[base]")
    else:  # PARTIAL_REPLACE
        mute_expr = build_mute_expression(plan.mute_ranges)
        filter_expressions.append(
            f"[0:a]aformat=sample_rates={plan.output_sample_rate}:channel_layouts=mono,"
            f"volume=enable='{mute_expr}':volume=0[base]"
        )
        mix_labels.append("[base]")

    # 每句新配音：adelay 精确定位到原始时间位置
    for index, clip in enumerate(plan.clips):
        input_arguments += ["-i", str(clip.audio_path)]
        delay_ms = int(clip.start * 1000)
        filter_expressions.append(
            f"[{next_index}:a]adelay={delay_ms}|{delay_ms},acopy[d{index}]"
        )
        mix_labels.append(f"[d{index}]")
        next_index += 1

    # 多轨混音（单输入时直接透传 acopy）
    total_inputs = len(mix_labels)
    if total_inputs == 1:
        filter_expressions.append(f"{mix_labels[0]}acopy[aout]")
    else:
        filter_expressions.append(
            f"{''.join(mix_labels)}amix=inputs={total_inputs}:duration=longest:"
            f"dropout_transition=0[aout]"
        )

    return input_arguments, filter_expressions, "[aout]"