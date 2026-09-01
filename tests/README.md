# tests/ — 测试目录

## 运行方式

所有命令在项目根目录运行（相对路径，不写死本机位置）：

```powershell
uv run pytest -q        # 全部测试（单元/契约/golden/集成/真 ffmpeg e2e）
uv run pytest -q tests/test_ffmpeg_filters.py   # 单个文件
```

`tests/run_all_tests.py` 是薄壳，等价 `uv run pytest -q tests`。

## 测试文件与覆盖

| 文件 | 覆盖 | 说明 |
|------|------|------|
| `test_domain_models.py` | domain 数据契约 | 时间范围/台词/计划/混音计划纯逻辑 |
| `test_config.py` | JobSpec + TOML 加载 | 合并优先级、校验错误、audio_only 推断 |
| `test_backends.py` | ASR/TTS 适配器 contract | sys.modules 注入假模型，不依赖真实安装 |
| `test_ffmpeg_filters.py` | 混音命令 golden | 命令结构快照，改动即红 |
| `test_pipeline.py` | 缓存/工作目录/计划/全链 | 假后端跑完整流水线 + 报告断言 |
| `test_cli.py` | 子命令 | run 配置合并与默认输出、transcribe 默认路径、label 面板（逐句审阅流改人/空间进/定位跳转/撤销、批量区间改人、合并/拆分/删除/结构撤销、--apply）、doctor、inspect |
| `test_e2e_ffmpeg.py` | 真实 ffmpeg e2e | full/partial/keep_bg 三模式渲染（无 ffmpeg 时跳过） |
| `test_logger.py` / `test_subtitle_loader.py` | 日志 / 字幕解析 | 从旧 core 移植（videodub.utils / pipeline.transcript_loader） |

## 变更影响路由

- 改 domain 契约 → test_domain_models + 全链回归
- 改混音渲染 → test_ffmpeg_filters（golden）+ test_e2e_ffmpeg（真 ffmpeg）
- 改缓存键 → test_pipeline 缓存用例
- 测试数字更新后同步 [../AGENTS.md](../AGENTS.md) 验证快照

参考：[AGENTS.md](AGENTS.md)（测试规范）· [../AGENTS.md](../AGENTS.md)（根索引）· [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)（测试策略节）