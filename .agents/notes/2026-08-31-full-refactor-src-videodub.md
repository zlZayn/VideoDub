# 决策：全量重构为 src/videodub（2026-08-31）

已实施。

## 问题

旧 `core/*.py + dub.py` 结构功能可用但契约弱：
`None` 同时表示"保留原声"与"生成失败"；混音模式靠自动检测；无缓存与报告；
单入口参数膨胀；无 git 历史。

## 决策

- 重构为 `src/videodub/`：domain（稳定契约）/ config（JobSpec）/ pipeline（编排/缓存/报告）/ backends（注册表）/ ffmpeg（纯函数 filter）/ cli（多子命令）
- 数据契约显式化：VoiceAssignment（计划）与 SynthesisResult（结果）分离，消灭 None 多语义
- MixPlan 驱动渲染：单一 ffmpeg 调用（lavfi 静音基底 / aformat 就地滤波），命令结构有 golden 测试
- 缓存两级（ASR/TTS，sha256 键）；每次运行产出 report.json
- CLI：`videodub run/transcribe/inspect/doctor`，删除 dub.py（维护者拍板不保兼容）
- JobSpec 用 Pydantic v2；领域模型用 frozen dataclass
- 测试迁移 pytest；真 ffmpeg e2e 作为渲染保护的基线

## 替代方案

- A 轻量重构（只加数据契约 + 缓存，不动布局）：体感提升有限，CLI 与混音推断问题未解决
- C 只做数据契约：1-2 天可完成，但无缓存/报告，5 分钟级重复体验不变
- ports/adapters 四层 + Step 类：对 2+2 个后端是仪式，注册表 + contract 测试已足够
- 全 Pydantic：领域模型过重；全 dataclass：输入边界校验缺类型转换与错误信息

## 影响

- 收益：契约可测、缓存复用（相同输入二次跑秒级）、每次运行可排查、新后端加 adapter 即可
- 代价：一次性的布局/命令/文档迁移（本次完成）；旧命令 dub.py 不可用
- 已知取舍：TOML 合并只有 CLI > 文件 > 默认三级，无逐字段 --set；对齐不做缓存（秒级操作）