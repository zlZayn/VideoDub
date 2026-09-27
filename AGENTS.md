# VideoDub — 维护索引

## 全局规则

- 架构设计 → [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 模块手册 → [src/videodub/README.md](src/videodub/README.md) · 规则层 → [src/videodub/AGENTS.md](src/videodub/AGENTS.md)
- 测试手册 → [tests/README.md](tests/README.md) · 示例手册 → [examples/README.md](examples/README.md) · 素材手册 → [assets/README.md](assets/README.md)
- 决策记录 → [.agents/notes/](.agents/notes/)
- 分层单向：cli → pipeline → backends/ffmpeg/config → domain；跨模块组合只在 pipeline/runner；模块之间只传 domain 类型，禁止裸 dict / None 语义；契约变更同步架构文档
- 模型密钥只走 JobSpec TOML / CLI 参数（`--api-key`），禁止进代码与 git；`.env*` 已忽略兜底
- 参考音色 assets/*.wav 不入库；新增素材在 [assets/README.md](assets/README.md) 登记
- 双件分离：AGENTS.md 只写规则，README.md 只写是什么/怎么改

## 常用命令（活文档）

- 完整配音：`videodub run <视频> --ref-audio <参考音频> -o <输出>`
- 仅输出音频：`-o out.wav`（扩展名自动识别）或 `--audio-only`
- 分角色（说话人0换、1保留）：`videodub run <视频> --ref-audio-0 <音色A> -o <输出>`；两人都换加 `--ref-audio-1 <B>`
- TOML 任务：`videodub run --job job.toml`；Windows 路径在 TOML 里用正斜杠
- 仅识别：`videodub transcribe <视频> --diarize -o transcript.json`；人工校对：`videodub label`
- 检查环境：`videodub doctor`；探测媒体：`videodub inspect <视频>`
- 运行测试：`python -m pytest -q`（或 `python tests/run_all_tests.py` 薄壳）
- Lint：`uv run ruff check .`（ruff 默认规则集，列宽默认 88）
- 格式化：`uv run ruff format .`（`--check` 只看不改）

## 验证快照

- Python 3.12.10（`.python-version` 钉住）；`.python-version` + `uv.lock` 已补（2026-09-27），包管理三件套齐了。
  dev 组只有 ruff，**运行时依赖仍是刻意的空清单**（后端按需安装，见 [pyproject.toml](pyproject.toml) 注释），
  锁文件因此不含后端
- lint：`uv run ruff check .` → All checks passed!（2026-09-27，ruff 0.16.9）
- pytest：132 passed / 0 failed（2026-09-27 复跑，含真 ffmpeg e2e；无 skip）。**口径要说清**：
  uv 环境只装 dev 组（ruff），这条命令是回落到 PATH 上本机全局的 pytest 9.0.3（系统 Python 3.12，
  另有 pydantic / rich / numpy / soundfile / httpx / faster-whisper / torch）；modelscope / voxcpm 未装，
  重后端在用例里是 mock 注入的 —— 复现它靠的是本机全局环境，不是锁文件

## 待办

- [ ] pyproject 依赖清单补全（faster-whisper / modelscope / voxcpm / soundfile / httpx / numpy / pydantic）——
  骨架与锁文件已就位，缺的只是把后端写进 `dependencies`（现在后端靠本机全局安装 + 用例 mock）
- [ ] 词级对齐（v2 候选，架构预留）
- [ ] 翻译配音（v2 候选，架构预留）

## 活跃坑

- ffprobe/ffmpeg 输出必须显式 UTF-8 解码（Windows GBK 误读会弄坏 JSON 解析）
- pytest basetemp 指到工作区 `.pytest-tmp/`；%TEMP%\pytest-of-* 有 ACL 问题勿改回
- TOML 字符串里 Windows 反斜杠是转义符，路径用 `/`
- VoxCPM2 输出采样率 48kHz；denoiser 已禁用；参考音频须 WAV/FLAC/OGG（m4a/mp3 自动转）
- 音量匹配用 volumedetect + volume，不用 loudnorm；默认目标 -10.7 dB
- 中文视频用 FunASR，faster-whisper 中文易乱码
- 混音模式显式 policy 优先；auto = 有保留段 → partial_replace，否则 full_replace
- 缓存键含影响结果的全部参数；改模型默认值不会自动失效旧缓存，手动清 `.cache/videodub/`