# src/videodub/ffmpeg/ — 规则层

继承根规则，见 [../../../AGENTS.md](../../../AGENTS.md)。

src/videodub/ffmpeg/ 特有约束：
- ffprobe/ffmpeg 输出必须显式 UTF-8 解码（Windows GBK 误读会坏 JSON 解析）
