# videodub/ — 配音引擎手册

- 职责：JobSpec 驱动的本地配音任务引擎（CLI + 流水线 + 适配器）
- 分层：cli → pipeline → backends / ffmpeg / config → domain，单向依赖

## 目录结构

```
src/videodub/
├── cli/           # 子命令入口（run / transcribe / label / inspect / doctor）
├── config/        # JobSpec 模型（Pydantic）与 TOML/CLI 合并加载
├── domain/        # 稳定数据契约：台词 / 配音计划 / 混音计划 / 媒体
├── pipeline/      # 流水线编排 + 工作目录 / 缓存 / 报告 / 台词加载
├── backends/      # ASR/TTS 适配器 + 注册表（新增后端在此登记）
├── ffmpeg/        # 命令执行 / 探测 / 音频操作 / 混音渲染（纯函数 filter）
└── utils/         # 统一日志
```

各文件职责、关键导出与变更路由见下表。

## 文件索引（职责 / 关键导出 / 被谁依赖 / 改后必测）

| 模块 | 职责 | 关键导出 | 被谁依赖 | 改后必测 |
|------|------|---------|---------|---------|
| `domain/transcript.py` | 台词契约 | `TimeRange` `Segment` `Transcript` `normalize_speaker` | 全部模块 | test_domain_models |
| `domain/models.py` | 配音/混音契约 | `VoiceAssignment` `SynthesisResult` `AlignedClip` `MixPlan` `MediaAsset` | 全部模块 | test_domain_models |
| `config/job_spec.py` | JobSpec 模型与校验 | `JobSpec` 及子 Spec、`resolve_model_name` | cli / pipeline | test_config |
| `config/load_job.py` | TOML/CLI 合并 | `load_job` `load_toml` | cli/run | test_config |
| `backends/registry.py` | 适配器注册表 | `get_transcriber` `get_synthesizer` | pipeline/cli | test_backends |
| `backends/asr_*.py` | ASR 适配器 | `FunAsrTranscriber` `WhisperTranscriber` | registry | test_backends |
| `backends/tts_*.py` | TTS 适配器 | `VoxCpmSynthesizer` `ApiSynthesizer` | registry | test_backends |
| `ffmpeg/runner.py` | ffmpeg 执行 | `run_ffmpeg_command` `set_command_echo` | 全部 ffmpeg/pipeline | test_e2e_ffmpeg |
| `ffmpeg/probe.py` | 媒体探测 | `probe_media` `probe_duration` | pipeline | test_e2e_ffmpeg |
| `ffmpeg/ops.py` | 拉伸/音量/转换 | `stretch_audio_to_duration` `post_process_audio` | pipeline/synthesis | test_ffmpeg_filters |
| `ffmpeg/filters.py` | MixPlan → filter 图 | `build_mix_invocation` | render_mix | test_ffmpeg_filters |
| `ffmpeg/render_mix.py` | 混音渲染 | `render` `build_render_command` | pipeline/runner | test_ffmpeg_filters |
| `pipeline/runner.py` | 流水线编排 | `run_job` | cli/run | test_pipeline |
| `pipeline/planning.py` | 配音/混音计划 | `build_voice_plan` `build_mix_plan` | runner | test_pipeline |
| `pipeline/synthesis.py` | TTS 与对齐 | `synthesize_segments` `align_segments` `prepare_refs` | runner | test_pipeline |
| `pipeline/cache.py` | 结果缓存 | `Cache` `asr_cache_key` `tts_cache_key` | runner/cli | test_pipeline |
| `pipeline/workspace.py` | 运行目录 | `Workspace` `create_workspace` | runner | test_pipeline |
| `pipeline/report.py` | 运行报告 | `Report` `write_report` | runner | test_pipeline |
| `pipeline/transcript_loader.py` | 台词加载 | `load_json_transcript` `load_subtitle_transcript` | runner | test_subtitle_loader |
| `cli/main.py` | 子命令分发 | `main` | videodub 入口 | test_cli |
| `cli/run.py` | run 子命令 | `build_parser` | main | test_cli |
| `cli/transcribe.py` | transcribe 子命令 | `build_parser` | main | test_cli |
| `cli/label.py` | label 子命令（人工校对说话人/断句；逐句审阅流 + rich 排版） | `build_parser` `_run_repl` | main | test_cli |
| `cli/inspect.py` `cli/doctor.py` | 探测/体检 | `build_parser` | main | test_cli |

## 变更影响路由

- 改 domain 契约 → 全模块连锁，同步 [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) 契约节
- 改 JobSpec 字段 → 同步 CLI 参数（cli/run）、示例（[../../examples/](../../examples/)）、架构文档
- 改混音渲染 → 跑 test_ffmpeg_filters（golden）+ test_e2e_ffmpeg（真 ffmpeg）
- 改缓存键 → 缓存失效语义变化，写进架构文档缓存节
- 使用约束与工作偏好 → 见 [AGENTS.md](AGENTS.md)