# assets/ — 规则层

继承根规则，见 [../AGENTS.md](../AGENTS.md)。

assets/ 特有约束：

- 媒体素材（*.wav 等）被根 [../.gitignore](../.gitignore) 忽略，不入库；clone 后需自备素材
- 新增素材必须在 [README.md](README.md) 登记：名称 / 来源 / 用途 / 规格
- 参考音频规格：干净人声、无背景噪音、单人说话；3-10 秒效果最佳；m4a/mp3 由引擎自动转 WAV（VoxCPM2 只认 WAV/FLAC/OGG）
- 素材命名 snake_case（如 `ref_voice_clean.wav`），不缩写到无法理解
- 不写"有什么文件/怎么改"，那是 [README.md](README.md) 的职责