# src/videodub/backends/ — 规则层

继承根规则，见 [../../../AGENTS.md](../../../AGENTS.md)。

src/videodub/backends/ 特有约束：
- 重后端按需安装、惰性导入；用例里一律 mock 注入
- 新后端必须在 registry 注册，否则运行期取不到
