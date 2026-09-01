# tests/ — 规则层

继承根规则，见 [../AGENTS.md](../AGENTS.md)。

tests/ 特有约束：

- 不调用真实模型：模型调用一律 mock（sys.modules 注入或 unittest.mock.patch）
- 不依赖外部媒体：e2e 用 ffmpeg 现场生成合成视频；机器无 ffmpeg 时整模块自动跳过（有 skipif 标记）
- pytest basetemp 指到工作区 `.pytest-tmp/`（根 pyproject 配置），勿改回 %TEMP%
- 用例增删后同步 [README.md](README.md) 文件表与根 [../AGENTS.md](../AGENTS.md) 验证快照数字；数字漂移先报告，不擅自改写
- 命令结构变化跑 golden（test_ffmpeg_filters）、后端新增跑 contract（test_backends）、流程变化跑集成（test_pipeline）
- 不写"有什么文件/怎么改"，那是 [README.md](README.md) 的职责