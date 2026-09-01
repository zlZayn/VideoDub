# examples/ — 示例配置与演示

以 `job.toml` 搭配 `uv run videodub run` 使用（在项目根目录运行）：

| 文件 | 场景 | 命令 |
|------|------|------|
| `single_speaker.toml` | 单说话人，全局音色替换 | `uv run videodub run examples/single_speaker.toml` |
| `two_speakers.toml` | 两人都换（diarize + speaker_map） | `uv run videodub run examples/two_speakers.toml` |
| `partial_replace.toml` | 只换一人，另一人保留原声 | `uv run videodub run examples/partial_replace.toml` |
| `demo_job.toml` | 全字段注释模板 | `uv run videodub run examples/demo_job.toml` |

说明：

- 所有路径相对项目根目录解析，示例文件里的 `input.mp4` / `assets/...` 需要按实际位置调整
- CLI 参数可覆盖 TOML 配置，如 `uv run videodub run examples/single_speaker.toml --keep-bg`
- 无配置文件也可直接跑：`uv run videodub run input.mp4 --ref-audio ref.wav -o out.mp4`

参考：[AGENTS.md](AGENTS.md)（示例编写规则）· [../AGENTS.md](../AGENTS.md)（根索引）· [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)（配置字段语义）