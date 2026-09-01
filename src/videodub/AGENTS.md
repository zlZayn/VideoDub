# videodub/ — 规则层

继承根规则，见 [../../AGENTS.md](../../AGENTS.md)。

本包特有约束：

- 模块分层单向：cli → pipeline → backends/ffmpeg/config → domain/，禁止反向引用
- 新增 ASR/TTS 后端必须在 [backends/registry.py](backends/registry.py) 登记，并补 contract 测试
- 数据契约一律用 [domain/](domain/) 类型，模块之间禁止传裸 dict / None 语义
- 对外可见接口（函数签名、CLI 参数、JobSpec 字段、输出格式）变更时，同步 [../../docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) 契约节
- 不写"有什么文件/怎么改"，那是 [README.md](README.md) 的职责