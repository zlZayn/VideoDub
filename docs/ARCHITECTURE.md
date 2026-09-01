# VideoDub 架构说明

## 1. 设计哲学

- 一次任务 = 一个 Job：用户提交 JobSpec，系统产出 Plan，Steps 执行并产出 Artifacts
- 计划与执行分离：TTS 前有 VoicePlan，渲染前有 MixPlan；渲染层不猜业务
- 显式胜过推断：混音模式、保留原声、生成失败都是显式状态，不用 None 承载多重含义
- 每跑必有记录：workdir 根目录保留 report.json 与其他 JSON 产物，可复现、可排查
- 本地 CLI 工具：无数据库、无服务化、无重型编排框架，新增后端 = 一个 adapter + 注册

## 2. 分层与依赖

```
cli/          参数解析 → JobSpec → run_job；子命令 run/transcribe/label/inspect/doctor
  ↓
pipeline/     编排（runner）· 计划（planning）· 合成（synthesis）
              · 工作目录（workspace）· 缓存（cache）· 报告（report）· 台词加载
  ↓
backends/     ASR/TTS 适配器（registry 注册）     ffmpeg/  runner/probe/ops/filters/render_mix
config/       JobSpec（Pydantic）与 TOML 加载
  ↓
domain/       稳定数据契约（无任何外部依赖）
```

- 单向依赖，禁止反向引用；跨模块组合只在 pipeline/runner 出现
- 契约：模块间只传 `domain/` 类型，裸 dict 只出现在 JSON 序列化边界

## 3. 核心数据契约

### 3.1 台词

- `TimeRange(start, end)`：时间范围，`.duration`
- `Segment(id, range, text, speaker?, language?, confidence?)`：统一 ASR/字幕/JSON 输出
- `speaker` 一律字符串标号 `SPEAKER_0`（ASR 的 int 在边界归一化）
- `Transcript`：`segments` 元组 + 语言 + source（asr/json/subtitle）
- 说话人标注两条路径，输出同构：自动 `transcribe --diarize`（CAM++ 聚类 + 句内静音≥200ms 细切，`asr_funasr._split_segments_by_silence`，时间戳与字符数不对齐的句子不切）；或 `label` 子命令人工指定/校正（逐句审阅流 + rich 排版：光标句窗口式高亮、Enter 前进、`0/1/2` 改当前句说话人并前进，命令支持批量/区间改人 `13=0`、`m` 合并可带文本、`x` 拆分、`d` 删除、试听、快照撤销；另有 `--apply` 稀疏回填）
- 输出目录约定：每个视频一个 `output/<输入名>/`，产物按阶段编号 `01_transcript.json` → `02_labeled.json` → `03_成品.mp4`，`.videodub/` 收报告与中间产物；三个子命令的默认输出都遵循此约定（`-o` 可覆盖）

### 3.2 配音计划与结果（消灭 None 多语义）

| 类型 | 含义 |
|------|------|
| `VoiceAssignment(segment_id, action, profile_id?)` | 计划：synthesize / keep_original / skipped |
| `SynthesisResult(segment_id, status, audio_path?, duration?, error?)` | 结果：ok / failed / keep_original / skipped |
| `AlignedClip(segment_id, status, audio_path?, stretch_ratio?, warning?)` | 对齐结果 + 拉伸比与警告 |

- 旧设计的 `None` 同时表示"保留原声"与"生成失败"，已拆成计划与结果两层显式枚举

### 3.3 混音

- `MixPlan(mode, clips, background_volume_ratio, output_sample_rate, mute_padding_ms)`：渲染层唯一输入
- `PlacedClip(segment_id, audio_path, start, end)`：放到时间轴上的配音片段
- `mode ∈ full_replace / keep_background / partial_replace`（枚举值向后兼容旧版）
- 混音模式解析：显式 policy 优先；auto = 存在保留段 → partial_replace，否则 full_replace
- `--keep-bg` = policy keep_background（旧 `preserve_background_audio` 旗标被显式策略取代）

## 4. 流水线

```
resolve_media → load_transcript → build_voice_plan → synthesize → align → build_mix_plan → render → report
                                      ↑ dry-run 到此为止
```

- 阶段函数返回结构化产物，写入 workspace 根目录（transcript.json / voice_plan.json / mix_plan.json / config.snapshot.json / report.json）
- dry-run：解析媒体 + 计划，不加载模型、不渲染
- 失败不中断：单句 TTS 失败 → status=failed 进报告；极端拉伸（<0.5 / >2.0）→ warning 进报告

## 5. 渲染（混音）设计

- `filters.build_mix_invocation(plan, duration)` 纯函数：MixPlan → 输入参数 + filter_complex
- 单次 ffmpeg 调用完成混音，不再预生成中间 wav：
  - full_replace：lavfi `anullsrc` 内联静音基底（旧版先写 silence_base.wav）
  - keep_background / partial_replace：原音轨就地 `aformat + volume`（旧版先提取再处理）
- 视频输出：`-map 0:v -c:v copy` 视频流不重编码；音频 `aac 192k`
- filter 命令结构有 golden 测试保护（test_ffmpeg_filters），改动即红

## 6. 缓存与工作目录

- 缓存：`.cache/videodub/{asr,tts}/<sha256>`；粒度两级
  - ASR key：输入媒体 hash + backend/model/language/diarize/max_speakers
  - TTS key：文本 + 参考音频 hash + mode/model/steps/device
  - 命中进 `report.json` 的 cache 统计；`--no-cache` 关闭
- 工作目录：`<输出同目录>/.videodub/run-<时间戳>/`
  - 重产物子目录（asr/tts/align/mix）默认清理；根目录 JSON 产物始终保留
  - `--keep-temp` 保留全部（调试用）
- 设计取舍：不做对齐级缓存（秒级操作，收益低）；resume 语义由缓存达成

## 7. 测试策略

| 层级 | 位置 | 内容 |
|------|------|------|
| 单元 | tests/test_domain_models 等 | 纯数据模型 / 配置 / 计划（不碰模型与 ffmpeg） |
| contract | tests/test_backends | 全部适配器满足同一接口（sys.modules 注入假模型） |
| golden | tests/test_ffmpeg_filters | 命令结构快照，改动即红 |
| 集成 | tests/test_pipeline | 假后端全链 mock 跑通 + 报告断言 |
| e2e | tests/test_e2e_ffmpeg | 真实 ffmpeg + 假 TTS（full/partial/keep_bg 三模式） |

- 统一 pytest：项目根目录 `uv run pytest -q`（自动同步 pyproject 骨架）
- pytest basetemp 配置在工作区 `.pytest-tmp/`（本机 %TEMP%\pytest-of-* 有 ACL 遗留问题）

## 8. 关键决策（含替代方案）

- JobSpec 用 Pydantic v2（输入边界校验）；领域模型用 frozen dataclass（内部产物）
  替代方案：全 dataclass 手写校验 —— 缺少类型转换与错误信息，维护成本高；全 Pydantic —— 内部流水线过重
- TOML 配置（标准库 tomllib），CLI 优先级 > TOML > 默认值
- 不构建 ports/抽象基类层：只有 2+2 个后端，注册表 dict + contract 测试足够
  替代方案：ABC 基类 —— 增加仪式却不提升保障
- 删除 dub.py 只留 videodub 子命令（用户拍板，不保兼容）
- 说话人人数参数：FunASR 新版不接受 `spk_kwargs["max_num_speakers"]`，改走 `generate(preset_spk_num=...)`（聚类 oracle）；短片段快速轮流对话时 CAM++ 仍会串人，故新增 `label` 子命令人工校正兜底
- 详细决策记录见 [../.agents/notes/](../.agents/notes/)（决策记录不写索引，git 历史即索引）

## 9. 防错清单

- 控制台输出按 GBK 解码；ffprobe/ffmpeg 的 stdout/stderr 必须显式 UTF-8 解码（曾经 GBK 误读导致 JSON 解析失败）
- VoxCPM2 输出采样率 48kHz；denoiser 已禁用（cudnn 符号不兼容）；参考音频须 WAV/FLAC/OGG（m4a/mp3 自动转）
- 中文视频用 FunASR，faster-whisper 中文易乱码
- 音量匹配用 volumedetect + volume，不用 loudnorm（单遍不准确）；默认目标 -10.7 dB
- TOML 里 Windows 路径必须用正斜杠或转义反斜杠（tomllib 转义规则）
- pytest basetemp 已指到工作区（见第 7 节），不要在 %TEMP% 下重建 pytest-of-*
- 换行统一 LF（check-line-endings.py 兜底）
- 缓存键必须包含影响结果的全部参数，改模型默认值不会自动失效旧缓存（需要时手动清 .cache/）