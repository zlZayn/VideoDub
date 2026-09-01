# 决策：说话人人工标注 label 子命令 + 分离参数修复（2026-08-31）

已实施

## 问题

1. `--diarize --max-speakers 2` 在 31 秒双人视频上分出 3 个说话人，且前半段快速轮流对话被并进同一个聚类。
2. 排查发现安装版 FunASR 里 `spk_kwargs={"max_num_speakers": N}` 没有任何代码读取，该参数被静默忽略。

## 决策

- **修复分离参数**：`asr_funasr.py` 改为在 `model.generate(..., preset_spk_num=N)` 传聚类 oracle 数，`--max-speakers 2` 现在真正产出 2 个聚类。
- **人工校正兜底**：新增 `videodub label` 子命令，对话吧的自动分离结果做逐句修正：
  - 默认交互模式：逐句显示时间+文本+当前说话人，输入编号改写、Enter 保留、s 跳过、q 提前保存。
  - `--apply 改好的.json` 文件模式：按位置稀疏合并，没填的保留原标注（适合只改几处）。
  - 编号任意整数，输出统一归一为 `SPEAKER_0 / SPEAKER_1 / ...`，与自动分离输出同构，可直接给 `run --segments-json` 用。
- 缓存键升版（`_ASR_CACHE_VERSION = "v2"`）失效旧结果，避免修复前缓存污染。

## 替代方案 / 未采用

- 无 diarize 的纯文字靠停顿分段后手动标注：停顿分段会跨说话人并句（本视频 5.63-13.69s 一段混了顾客+药师），不如"自动分离起底 + 人工修正"。
- pyannote/WhisperX 换分离后端：精度更高但需 HF token，回归取舍更大，先靠人工兜底。

## 验证

- 修复前：3 个说话人（0:9 / 1:6 / 2:3），前半段顾客+药师混在 SPEAKER_0。
- 修复后：2 个说话人（0:9 / 1:9）。
- `videodub label --apply` 修正两处误标后：SPEAKER_0: 7 句、SPEAKER_1: 11 句。
- 单测：test_cli.py 新增 label 3 组用例（回填归一化 / 稀疏合并 / 数量不一致报错 / 交互指派），全量 105 passed。