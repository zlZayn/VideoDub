# assets/ — 参考音频素材

## 素材登记

| 文件 | 来源 | 用途 | 规格 |
|------|------|------|------|
| `ref_voice.wav` | 用户提供的 `8月30日 横沥镇 2.m4a` 转换 | 完整参考（保留原始长度） | 22.44 秒，16kHz mono |
| `ref_voice_clean.wav` | 上述音频截取能量最高片段 | 音色克隆（clean 版，示例默认） | 3 秒切片，16kHz mono |
| `ref_voice_3mm.wav` | 另一段用户参考音频 | 分角色配音的 SPEAKER_1 音色（examples/two_speakers.toml 使用） | 16kHz mono |
| `recognized_segments.json` | FunASR 实测输出 | 跳过 ASR 的台词导入演示（examples 与 e2e 使用） | 7 句，带 start/end |

## 说明

- 素材文件被 `.gitignore` 忽略，不入库；clone 后需自备
- 参考音频要求：干净人声、无背景噪音、单人说话；m4a/mp3 会被引擎自动转 WAV
- 使用约束与工作偏好 → 见 [AGENTS.md](AGENTS.md)
- 变更影响：换素材 → 音色变化（不需要动代码）；改 `recognized_segments.json` 结构 → 同步 [../src/videodub/pipeline/transcript_loader.py](../src/videodub/pipeline/transcript_loader.py) 契约（test_subtitle_loader 回归）

参考：[AGENTS.md](AGENTS.md)（素材规则）· [../AGENTS.md](../AGENTS.md)（根索引）· [../examples/two_speakers.toml](../examples/two_speakers.toml)（分角色用法）