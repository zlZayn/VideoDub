# examples/ — 规则层

继承根规则，见 [../AGENTS.md](../AGENTS.md)。

examples/ 特有约束：

- 示例 TOML 必须能被 tomllib 解析：说明文字一律 `#` 注释前缀，不写裸文本行
- TOML 没有 null，"保留原声"用空字符串 `""` 表示（由 JobSpec 归一为 None）
- 示例字段必须与 JobSpec 契约对齐；改动示例 = 校验配置契约，跑 test_config
- 示例路径一律相对运行目录，不写死本机路径
- 新增示例必须在 [README.md](README.md) 登记场景与命令
- 不写"有什么文件/怎么改"，那是 [README.md](README.md) 的职责