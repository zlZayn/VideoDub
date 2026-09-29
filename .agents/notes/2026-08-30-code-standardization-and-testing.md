# 2026-08-30 代码规范化与测试补全

状态：生效

## 背景

项目功能已跑通（完整配音流程、说话人分离、分角色配音），但存在以下问题：
- 各模块日志输出格式不统一（有的用 `print(f"  >> ...")`，有的用 `print(f"  阶段 X: ...")`）
- 文档中使用复杂 ASCII 流程图，可读性差
- 缺少单元测试，重构时无法快速验证
- 部分边界逻辑存在 bug（测试中发现）

## 决策

### 1. 统一日志输出格式

**选择**：创建 `core/logger.py`，所有模块统一使用。

**格式**：`[阶段] [时间] 内容`
- 阶段标签：ASR / TTS / 对齐 / 合成 / FFmpeg / 流程 / 字幕 / 进度 等
- 时间：`HH:MM:SS` 格式
- 内容：简洁描述

**提供的函数**：
- `log(stage, message)` — 普通日志
- `log_stage_header(stage, description)` — 阶段标题（带分隔线）
- `log_progress(current, total, message)` — 进度信息
- `log_error(message)` — 错误（输出到 stderr）
- `log_warning(message)` — 警告
- `log_success(message)` — 成功

**理由**：统一格式便于日志解析和问题定位；时间戳帮助排查性能问题；阶段标签快速定位当前处理阶段。

### 2. 文档移除复杂 ASCII 图

**选择**：README.md 和 docs/ARCHITECTURE.md 中的复杂流程图改为文字描述，仅保留目录树（简单 ASCII tree）。

**理由**：
- 复杂 ASCII 图在不同终端/编辑器中容易错位
- 文字描述更易于维护和搜索
- 目录树是结构化信息，简单 ASCII 树可读性好

### 3. 补全单元测试（mock，不调用模型）

**选择**：创建 `tests/` 目录，用 `unittest.mock` 模拟模型调用和 FFmpeg 调用。

**测试覆盖**：
- `test_logger.py` — 日志工具（6个测试）
- `test_subtitle_loader.py` — 字幕解析（5个测试）
- `test_audio_mixer.py` — 混音模式检测（6个测试）
- `test_voice_cloner.py` — 音色克隆映射（5个测试）
- `test_time_aligner.py` — 时间对齐（4个测试）

**运行方式**：`.venv/Scripts/python.exe tests/run_all_tests.py`

**理由**：模型调用耗时且依赖 GPU/大模型，不适合单元测试；mock 可以快速验证纯逻辑部分；测试驱动发现了3个真实 bug。

### 4. 禁止硬编码路径

**选择**：代码中不使用绝对路径，全部通过参数传入或使用相对路径。

**理由**：项目可移植性；不同用户的目录结构不同；硬编码路径容易在环境变化时失效。

## 替代方案

- **各模块继续各自 `print`**：格式不统一、无时间戳与阶段标签，日志无法解析与检索——统一到 `core/logger.py`。
- **保留复杂 ASCII 流程图**：跨终端/编辑器易错位、难搜索、难维护——改为文字描述，仅保留目录树（简单 ASCII tree 例外）。
- **单元测试直连真实模型 / FFmpeg**：模型调用耗时、依赖 GPU 与大模型，不适合单测——一律 `unittest.mock` 模拟（该约定后续被 tests/AGENTS 固化为规则）。
- **允许硬编码路径**：换环境即失效、不可移植——路径一律参数传入或相对路径。

## 测试中发现并修复的 Bug

### Bug 1: 混音模式优先级错误

**问题**：`_detect_mix_mode()` 中先检查 `has_none` 再检查 `preserve_background_audio`，导致用户明确指定 `--keep-bg` 但有部分句子不替换时，返回 `partial_replace` 而非 `keep_background`。

**修复**：调整优先级，先检查 `preserve_background_audio`，再检查 `has_none`。

**优先级**：`--keep-bg` > 部分替换（有None） > 完全替换

### Bug 2: SRT 多行字幕解析不完整

**问题**：SRT 正则表达式使用非贪婪匹配 `((?:.*(?:\n|$))+?)`，导致多行文本只捕获第一行。

**修复**：改为 `((?:[^\n]+\n?)+?)(?=\n*\d+\s*\n|\Z)`，用正向预查匹配到下一个字幕块或文件末尾。

### Bug 3: ASS 字幕解析文本前多逗号

**问题**：ASS 正则表达式中 End 之后只有5个 `[^,]*` 字段，但实际 ASS Dialogue 行有6个字段（Style, Name, MarginL, MarginR, MarginV, Effect），导致 Text 字段前多了一个逗号。

**修复**：增加一个 `[^,]*`，从5个改为6个。

## 验证结果

- 语法检查：14个文件全部通过
- 单元测试：26个测试全部通过
- 测试发现的3个 bug 已全部修复

## 后续待办

- [ ] 端到端验证分角色配音（只换说话人0，说话人1保留原声）
- [ ] 增加 ASR 模块的单元测试（mock FunASR/whisper）
- [ ] 增加 dubbing_workflow 集成测试（mock 所有子模块）
