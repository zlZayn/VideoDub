"""transcribe 子命令 — 仅语音识别，输出台词 JSON

用法：
  videodub transcribe input.mp4 --backend funasr --diarize
  → 默认输出 output/<输入名>/01_transcript.json（阶段编号即流程顺序，见根 README）
"""

from __future__ import annotations

import json
from pathlib import Path

from videodub.backends.registry import get_transcriber
from videodub.config.job_spec import TranscriptSpec, resolve_model_name
from videodub.ffmpeg.runner import ensure_ffmpeg_available, run_ffmpeg_command
from videodub.pipeline.cache import Cache, asr_cache_key
from videodub.pipeline.workspace import Workspace
from videodub.utils.logger import log_success


def build_parser(parser) -> None:
    parser.add_argument("input", help="输入视频/音频路径")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="台词 JSON 输出路径（默认 output/<输入名>/01_transcript.json）",
    )
    parser.add_argument(
        "--backend",
        default=None,
        choices=["funasr", "whisper"],
        help="ASR 后端（默认 funasr）",
    )
    parser.add_argument("--model", default=None, help="ASR 模型名")
    parser.add_argument(
        "--device", default=None, choices=["cpu", "cuda"], help="推理设备（默认 cpu）"
    )
    parser.add_argument(
        "--compute-type", default=None, help="whisper 计算精度（默认 float16）"
    )
    parser.add_argument("--language", default=None, help="源语言代码（whisper 用）")
    parser.add_argument("--diarize", action="store_true", help="启用说话人分离")
    parser.add_argument(
        "--max-speakers", type=int, default=None, help="最大说话人数（默认 2）"
    )
    parser.add_argument("--no-cache", action="store_true", help="禁用 ASR 结果缓存")
    parser.add_argument("--keep-temp", action="store_true", help="保留运行目录")

    parser.set_defaults(func=_run)


def _default_output(input_path: str) -> Path:
    """目录约定：每个视频一个文件夹，产物按阶段编号（01 识别 → 02 校对 → 03 成品）"""
    return Path("output") / Path(input_path).stem / "01_transcript.json"


def _run(args) -> int:
    output_path = Path(args.output) if args.output else _default_output(args.input)
    spec = TranscriptSpec(
        backend=args.backend or "funasr",
        model_name=args.model,
        device=args.device or "cpu",
        compute_type=args.compute_type or "float16",
        language=args.language,
        diarize=args.diarize,
        max_speakers=args.max_speakers or 2,
    )
    model_name = resolve_model_name(spec.backend, spec.model_name)

    ensure_ffmpeg_available()
    ws = Workspace(output_path.parent / ".videodub" / "transcribe", keep=args.keep_temp)
    cache = Cache(enabled=not args.no_cache)

    key = asr_cache_key(
        args.input,
        backend=spec.backend.value,
        model=model_name,
        language=spec.language,
        diarize=spec.diarize,
        max_speakers=spec.max_speakers,
    )
    cached = cache.get("asr", key, ".json")
    if cached is not None:
        items = json.loads(cached.read_text(encoding="utf-8"))
        _write(output_path, items)
        log_success(f"台词 JSON（缓存命中）: {output_path}")
        return 0

    extracted = ws.file("asr", "extracted_audio.wav")
    run_ffmpeg_command(
        [
            "-y",
            "-i",
            args.input,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(extracted),
        ],
        "提取音轨 (16kHz mono)",
    )
    transcript = get_transcriber(spec).transcribe(str(extracted))

    items = transcript.to_dicts()
    transcript_file = ws.file("asr", "transcript.json")
    transcript_file.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cache.put("asr", key, transcript_file, ".json")
    _write(output_path, items)
    log_success(f"台词 JSON: {output_path}")
    return 0


def _write(output_path, items) -> None:
    Path(output_path).write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
