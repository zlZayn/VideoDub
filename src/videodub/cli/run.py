"""run 子命令 — 执行配音任务

用法：
  videodub run input.mp4 --ref-audio ref.wav -o output.mp4
  videodub run --job job.toml [--set 覆盖]
  videodub run input.mp4 --ref-audio-0 a.wav --ref-audio-1 b.wav -o output.mp4
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from videodub.config.load_job import load_job
from videodub.ffmpeg.runner import set_command_echo
from videodub.pipeline.runner import run_job
from videodub.utils.logger import log_error


def build_parser(parser) -> None:
    """run 子命令参数（CLI 优先级 > job.toml > 默认值）"""
    parser.add_argument(
        "input", nargs="?", default=None, help="输入视频/音频路径（--job 提供时可省略）"
    )
    parser.add_argument("--job", default=None, help="job.toml 配置文件路径")

    out_group = parser.add_argument_group("输出")
    out_group.add_argument(
        "-o",
        "--output",
        default=None,
        help="输出路径（默认 output/<输入名>/03_成品.mp4；.wav 后缀出音频）",
    )
    out_group.add_argument("--audio-only", action="store_true", help="仅输出配音音频")

    voice_group = parser.add_argument_group("参考音色（二选一）")
    voice_group.add_argument(
        "--ref-audio", default=None, help="全局参考音频路径（所有说话人同一音色）"
    )
    voice_group.add_argument(
        "--ref-audio-0",
        default=None,
        help="说话人 SPEAKER_0 的参考音频（不指定则保留原声）",
    )
    voice_group.add_argument(
        "--ref-audio-1",
        default=None,
        help="说话人 SPEAKER_1 的参考音频（不指定则保留原声）",
    )

    src_group = parser.add_argument_group("台词来源（三选一，默认 ASR）")
    src_group.add_argument(
        "--segments-json", default=None, help="已识别台词 JSON（跳过 ASR）"
    )
    src_group.add_argument(
        "--subtitle", default=None, help="字幕文件 SRT/ASS（跳过 ASR）"
    )

    asr_group = parser.add_argument_group("ASR 参数")
    asr_group.add_argument(
        "--asr-backend",
        default=None,
        choices=["funasr", "whisper"],
        help="ASR 后端（默认 funasr）",
    )
    asr_group.add_argument(
        "--asr-model",
        default=None,
        help="ASR 模型名（默认 paraformer-zh / distil-large-v3）",
    )
    asr_group.add_argument(
        "--asr-device",
        default=None,
        choices=["cpu", "cuda"],
        help="ASR 设备（默认 cpu）",
    )
    asr_group.add_argument(
        "--asr-compute-type", default=None, help="whisper 计算精度（默认 float16）"
    )
    asr_group.add_argument(
        "--language", default=None, help="源语言代码（zh/en/ja...，whisper 用）"
    )
    asr_group.add_argument("--diarize", action="store_true", help="启用说话人分离")
    asr_group.add_argument(
        "--max-speakers", type=int, default=None, help="最大说话人数（默认 2）"
    )

    tts_group = parser.add_argument_group("TTS 参数")
    tts_group.add_argument(
        "--tts-mode",
        default=None,
        choices=["local", "api"],
        help="音色克隆模式（默认 local）",
    )
    tts_group.add_argument(
        "--tts-device",
        default=None,
        choices=["cpu", "cuda"],
        help="TTS 设备（默认 cpu）",
    )
    tts_group.add_argument(
        "--tts-steps", type=int, default=None, help="VoxCPM2 推理步数（默认 10）"
    )
    tts_group.add_argument("--api-base", default=None, help="TTS API 地址（api 模式）")
    tts_group.add_argument("--api-key", default=None, help="TTS API 密钥（api 模式）")
    tts_group.add_argument(
        "--api-model", default=None, help="TTS API 模型名（api 模式）"
    )

    mix_group = parser.add_argument_group("混音参数")
    mix_group.add_argument(
        "--keep-bg",
        action="store_true",
        help="保留原背景音（变相 mix.policy=keep_background）",
    )
    mix_group.add_argument(
        "--bg-volume", type=float, default=None, help="背景音量比例（默认 0.2）"
    )

    run_group = parser.add_argument_group("运行控制")
    run_group.add_argument(
        "--dry-run", action="store_true", help="只出计划，不跑重模型不渲染"
    )
    run_group.add_argument(
        "--resume", action="store_true", help="启用缓存复用（等价 --cache 开）"
    )
    run_group.add_argument(
        "--no-cache", action="store_true", help="禁用 ASR/TTS 结果缓存"
    )
    run_group.add_argument(
        "--keep-temp", action="store_true", help="保留运行目录重产物"
    )
    run_group.add_argument(
        "--print-ffmpeg", action="store_true", help="回显每条 ffmpeg 命令"
    )
    run_group.add_argument(
        "--verbose", action="store_true", help="冗余日志（暂未启用额外输出）"
    )

    parser.set_defaults(func=_run)


def _default_output(input_path: str) -> str:
    """目录约定：每个视频一个文件夹，产物按阶段编号（01 识别 → 02 校对 → 03 成品）"""
    return str(Path("output") / Path(input_path).stem / "03_成品.mp4")


def _build_overrides(args) -> dict:
    """CLI 参数 → JobSpec 同构 dict（只含显式给出的键）"""
    overrides: dict = {}

    if args.input:
        overrides["input"] = {"path": args.input}
    if args.output:
        overrides["output"] = {"path": args.output}
    elif args.input:
        overrides["output"] = {"path": _default_output(args.input)}
    if args.audio_only:
        overrides.setdefault("output", {})["audio_only"] = True

    if args.ref_audio:
        overrides["voice"] = {"ref_audio": args.ref_audio}
    elif args.ref_audio_0 is not None or args.ref_audio_1 is not None:
        speaker_map = {}
        if args.ref_audio_0 is not None:
            speaker_map["SPEAKER_0"] = args.ref_audio_0
        if args.ref_audio_1 is not None:
            speaker_map["SPEAKER_1"] = args.ref_audio_1
        overrides["voice"] = {"speaker_map": speaker_map}

    transcript: dict = {}
    if args.segments_json:
        transcript.update(source="json", path=args.segments_json)
    elif args.subtitle:
        transcript.update(source="subtitle", path=args.subtitle)
    else:
        if args.asr_backend:
            transcript["backend"] = args.asr_backend
        if args.asr_model:
            transcript["model_name"] = args.asr_model
        if args.asr_device:
            transcript["device"] = args.asr_device
        if args.asr_compute_type:
            transcript["compute_type"] = args.asr_compute_type
        if args.language:
            transcript["language"] = args.language
        if args.diarize:
            transcript["diarize"] = True
        if args.max_speakers is not None:
            transcript["max_speakers"] = args.max_speakers
    if transcript:
        overrides["transcript"] = transcript

    tts: dict = {}
    if args.tts_mode:
        tts["mode"] = args.tts_mode
    if args.tts_device:
        tts["device"] = args.tts_device
    if args.tts_steps is not None:
        tts["inference_steps"] = args.tts_steps
    if args.api_base:
        tts["api_base_url"] = args.api_base
    if args.api_key:
        tts["api_key"] = args.api_key
    if args.api_model:
        tts["api_model_name"] = args.api_model
    if tts:
        overrides["tts"] = tts

    mix: dict = {}
    if args.keep_bg:
        mix["policy"] = "keep_background"
    if args.bg_volume is not None:
        mix["background_volume_ratio"] = args.bg_volume
    if mix:
        overrides["mix"] = mix

    runtime: dict = {}
    if args.dry_run:
        runtime["dry_run"] = True
    if args.resume:
        runtime["cache"] = True
    if args.no_cache:
        runtime["cache"] = False
    if args.keep_temp:
        runtime["keep_temp"] = True
    if args.verbose:
        runtime["verbose"] = True
    if runtime:
        overrides["runtime"] = runtime

    return overrides


def _run(args) -> int:
    """run 子命令执行体"""
    if not args.input and not args.job:
        raise SystemExit(
            "必须提供输入文件或 --job 配置（videodub run <input> 或 videodub run --job job.toml）"
        )

    try:
        job = load_job(args.job, _build_overrides(args))
    except ValidationError as error:
        log_error(f"配置无效: {error}")
        return 1

    set_command_echo(args.print_ffmpeg)
    run_job(job)
    return 0
