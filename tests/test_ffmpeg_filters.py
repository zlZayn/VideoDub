"""FFmpeg 混音命令 golden 测试 — 纯函数断言，不执行 ffmpeg

命令结构一旦变化即红，保护渲染管线不被无意改动。
"""

from pathlib import Path

from videodub.domain.models import MixMode, MixPlan, PlacedClip
from videodub.domain.transcript import TimeRange
from videodub.ffmpeg.filters import build_mix_invocation, build_mute_expression
from videodub.ffmpeg.ops import build_atempo_chain
from videodub.ffmpeg.render_mix import build_render_command

# ── 纯工具 ──

def test_build_mute_expression_single_range():
    assert build_mute_expression((TimeRange(1.234, 3.010),)) == "between(t,1.234,3.010)"


def test_build_mute_expression_multiple_ranges():
    expr = build_mute_expression((TimeRange(1.2345, 3.0), TimeRange(8.44, 10.02)))
    assert expr == "between(t,1.234,3.000)+between(t,8.440,10.020)"


def test_build_mute_expression_empty():
    assert build_mute_expression(()) == "0"


def test_build_atempo_chain_normal():
    assert build_atempo_chain(1.18) == ["atempo=1.1800"]


def test_build_atempo_chain_cascade_slow():
    assert build_atempo_chain(4.5) == ["atempo=2.0", "atempo=2.0", "atempo=1.1250"]


def test_build_atempo_chain_cascade_fast():
    assert build_atempo_chain(0.25) == ["atempo=0.5", "atempo=0.5000"]


# ── mix invocation ──

def _plan(mode, clips=(), bg_ratio=None):
    return MixPlan(mode=mode, clips=clips, background_volume_ratio=bg_ratio)


def test_full_replace_invocation_golden():
    plan = _plan(
        MixMode.FULL_REPLACE,
        clips=(
            PlacedClip("seg_0001", Path("a.wav"), 1.23, 3.01),
            PlacedClip("seg_0002", Path("b.wav"), 8.44, 10.02),
        ),
    )
    inputs, filters, label = build_mix_invocation(plan, duration=10.0)
    assert inputs == [
        "-f", "lavfi", "-t", "10.000", "-i", "anullsrc=48000:cl=mono",
        "-i", "a.wav",
        "-i", "b.wav",
    ]
    assert filters == [
        "[1:a]acopy[base]",
        "[2:a]adelay=1230|1230,acopy[d0]",
        "[3:a]adelay=8440|8440,acopy[d1]",
        "[base][d0][d1]amix=inputs=3:duration=longest:dropout_transition=0[aout]",
    ]
    assert label == "[aout]"


def test_keep_background_invocation_golden():
    plan = _plan(MixMode.KEEP_BACKGROUND, clips=(PlacedClip("s1", Path("a.wav"), 1.0, 2.0),), bg_ratio=0.2)
    _, filters, _ = build_mix_invocation(plan, duration=10.0)
    assert filters[0] == (
        "[0:a]aformat=sample_rates=48000:channel_layouts=mono,volume=0.2[base]"
    )
    assert filters[1] == "[1:a]adelay=1000|1000,acopy[d0]"
    assert filters[-1] == "[base][d0]amix=inputs=2:duration=longest:dropout_transition=0[aout]"


def test_partial_replace_invocation_golden():
    plan = _plan(
        MixMode.PARTIAL_REPLACE,
        clips=(
            PlacedClip("seg_0001", Path("a.wav"), 1.23, 3.01),
            PlacedClip("seg_0003", Path("c.wav"), 8.44, 10.02),
        ),
    )
    _, filters, _ = build_mix_invocation(plan, duration=10.0)
    assert filters[0] == (
        "[0:a]aformat=sample_rates=48000:channel_layouts=mono,"
        "volume=enable='between(t,1.230,3.010)+between(t,8.440,10.020)':volume=0[base]"
    )


def test_single_input_passthrough():
    plan = _plan(MixMode.FULL_REPLACE)
    inputs, filters, label = build_mix_invocation(plan, duration=5.0)
    assert filters == ["[1:a]acopy[base]", "[base]acopy[aout]"]
    assert label == "[aout]"
    assert inputs[5] == "anullsrc=48000:cl=mono"


# ── render command ──

def test_render_video_command_golden():
    plan = _plan(MixMode.FULL_REPLACE, clips=(PlacedClip("s1", Path("a.wav"), 1.0, 2.0),))
    cmd = build_render_command(
        plan, "input.mp4", "out.mp4", duration=10.0,
        audio_only=False, video_codec="copy", audio_codec="aac", audio_bitrate="192k",
    )
    assert cmd == [
        "-y", "-i", "input.mp4",
        "-f", "lavfi", "-t", "10.000", "-i", "anullsrc=48000:cl=mono",
        "-i", "a.wav",
        "-filter_complex",
        "[1:a]acopy[base];[2:a]adelay=1000|1000,acopy[d0];[base][d0]amix=inputs=2:duration=longest:dropout_transition=0[aout]",
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "out.mp4",
    ]


def test_render_audio_only_command_golden():
    plan = _plan(MixMode.KEEP_BACKGROUND, clips=(PlacedClip("s1", Path("a.wav"), 1.0, 2.0),), bg_ratio=0.3)
    cmd = build_render_command(
        plan, "input.mp4", "out.wav", duration=10.0, audio_only=True,
    )
    assert cmd == [
        "-y", "-i", "input.mp4",
        "-i", "a.wav",
        "-filter_complex",
        ("[0:a]aformat=sample_rates=48000:channel_layouts=mono,volume=0.3[base];"
        "[1:a]adelay=1000|1000,acopy[d0];"
        "[base][d0]amix=inputs=2:duration=longest:dropout_transition=0[aout]"),
        "-map", "[aout]",
        "-c:a", "pcm_s16le", "-ar", "48000",
        "out.wav",
    ]