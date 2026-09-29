# VideoDub

视频音色替换 —— 本地 VoxCPM2 音色克隆 + 逐句时长对齐对口型。

支持单说话人全局换音色、分角色配音（说话人分离）、部分替换（一人换一人保留）、保留背景音。

## 原理（为什么能对口型）

1. ASR 识别每句台词的精确起止时间（毫秒级）
2. VoxCPM2 用参考音频克隆音色，逐句生成新配音（48kHz）
3. 时域拉伸（保音高变时长）把每句新配音调整到与原句完全相同的时长
4. 音量匹配 + 首尾淡入淡出后，每句精确放置回原始时间点

## 快速开始

### 准备材料

- 输入视频：要替换人声的 mp4 等文件
- 参考音频：3-10 秒干净人声，无背景噪音、单人说话；m4a/mp3 会自动转 WAV

### 一次完整配音

```bash
# 首次使用先装包（pyproject 骨架只装引擎本体，ASR/TTS 后端依赖按需安装）
uv sync                       # 或 pip install -e .
videodub run input.mp4 --ref-audio ref.wav -o output.mp4
```

Windows 下用 `.\\.venv\\Scripts\\videodub.exe` 或 `.\\.venv\\Scripts\\python.exe -m videodub`。

跑完终端显示"全部完成"，得到 `output.mp4`。
报告在 `<输出同目录>/.videodub/run-*/report.json`（阶段耗时 / 逐句结果 / 警告）。
同一输入再跑一次命中缓存，秒级完成。

### 常用变体

```bash
# 仅输出配音音频（-o 扩展名自动识别）
videodub run input.mp4 --ref-audio ref.wav -o output.wav

# 分角色：说话人0换音色A，说话人1保留原声
# 注意：--ref-audio-0/1 与 --ref-audio 二选一，不能同时用
videodub run input.mp4 --ref-audio-0 voice_a.wav -o output.mp4

# 保留背景音
videodub run input.mp4 --ref-audio ref.wav --keep-bg -o output.mp4
```

### JobSpec 最小示例

```toml
[input]
path = "input.mp4"

[output]
path = "output/dubbed.mp4"

[transcript]
source = "asr"
backend = "funasr"      # 或 whisper
language = "zh"

[voice]
ref_audio = "assets/ref_voice_clean.wav"

[mix]
policy = "full_replace"  # full_replace / keep_background / partial_replace
```

运行：`videodub run --job job.toml`。全字段注释模板见 `examples/demo_job.toml`；单说话人 / 双说话人 / 部分替换示例在 `examples/`。

### 手动调速（先看台词再配音）

```bash
videodub transcribe input.mp4 -o segments.json       # 先识别，检查台词与时间戳
videodub run input.mp4 --segments-json segments.json --ref-audio ref.wav -o output.mp4  # 复用台词
```

环境有问题先跑 `videodub doctor`；输出不理想看 `report.json` 与 `--print-ffmpeg`（回显实际执行的 ffmpeg 命令）。

## 命令

| 命令 | 用途 |
|------|------|
| `videodub run` | 执行配音任务（CLI 参数 > job.toml > 默认值） |
| `videodub transcribe` | 仅语音识别，输出台词 JSON |
| `videodub inspect <file>` | 探测媒体信息 |
| `videodub doctor` | 检查运行环境与依赖 |

run 常用参数：

- 台词来源：`--segments-json` / `--subtitle`（SRT/ASS）/ 默认 FunASR；`--diarize`、`--max-speakers`、`--asr-backend whisper`
- 混音：`--keep-bg`（保留背景音）、`--bg-volume`
- 运行控制：`--dry-run`（只出计划）、`--no-cache`、`--keep-temp`、`--print-ffmpeg`
- TTS：`--tts-mode api`（OpenAI 兼容服务）、`--tts-device`、`--tts-steps`、`--api-key`

## 目录结构

```
VideoDub/
├── .agents/notes/     # 决策记录（历史决策与替代方案）
├── assets/            # 参考音频素材（*.wav 不入库，clone 后自备）
├── docs/              # 架构文档
├── examples/          # JobSpec 示例 TOML
├── src/videodub/      # 引擎源码（cli / pipeline / backends / ffmpeg / config / domain）
└── tests/             # pytest 测试
```

## 输出与产物

- 每次运行在 `<输出同目录>/.videodub/run-<时间戳>/` 生成 report.json（阶段耗时 / 逐片段结果 / 缓存命中 / 警告）、transcript.json、voice_plan.json、mix_plan.json、config.snapshot.json
- 重产物（TTS/对齐 wav）默认清理，`--keep-temp` 保留
- ASR/TTS 结果缓存在 `.cache/videodub/`，相同输入自动复用；`--no-cache` 关闭，手动清缓存删目录即可

## 开发

```bash
python -m pytest -q            # 全部测试（单元/契约/golden/集成/真 ffmpeg e2e）
python tests/run_all_tests.py  # 薄壳，等价上一行
```

## 安全说明

- 模型密钥（TTS API key）只走 JobSpec TOML / CLI 参数（`--api-key`），不进代码、不入库；`.env*` 已由 .gitignore 兜底
- `assets/*.wav` 参考音色（真人声音）被 .gitignore 忽略，不入库；clone 后需自备
- 作品输出 `output/` 整体忽略，不入库

## 文档

- 架构（开发者）→ [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 模块手册 → [src/videodub/README.md](src/videodub/README.md)
- 维护索引（规则/验证快照/待办/坑）→ [AGENTS.md](AGENTS.md)
- 子目录双件：assets / examples / src/videodub / tests（README 文档层 + AGENTS 规则层）
- 决策记录 → [.agents/notes/](.agents/notes/)
