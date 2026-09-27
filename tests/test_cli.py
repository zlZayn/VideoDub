"""CLI 测试 — 不调用真实模型与 ffmpeg（run 用假 pipeline，transcribe 用假转录器）"""

import json
from pathlib import Path

import pytest

from videodub.cli.main import main
from videodub.config.job_spec import MixPolicy

# ── run ──

def _media(tmp_path):
    (tmp_path / "input.mp4").write_bytes(b"media")
    (tmp_path / "ref.wav").write_bytes(b"ref")
    return tmp_path


def test_run_minimal_flags_build_job(tmp_path, monkeypatch):
    tmp_path = _media(tmp_path)
    captured = []
    import videodub.cli.run as run_cmd
    monkeypatch.setattr(run_cmd, "run_job", lambda job: captured.append(job))

    code = main([
        "run", str(tmp_path / "input.mp4"),
        "--ref-audio", str(tmp_path / "ref.wav"),
        "-o", str(tmp_path / "out.mp4"),
        "--diarize", "--max-speakers", "3",
        "--language", "zh",
    ])

    assert code == 0
    job = captured[0]
    assert job.input.path == tmp_path / "input.mp4"
    assert job.output.path == tmp_path / "out.mp4"
    assert job.output.audio_only is False
    assert job.voice.ref_audio == tmp_path / "ref.wav"
    assert job.transcript.diarize is True
    assert job.transcript.max_speakers == 3
    assert job.transcript.language == "zh"
    assert job.transcript.backend.value == "funasr"


def test_run_speaker_map_flags(tmp_path, monkeypatch):
    tmp_path = _media(tmp_path)
    (tmp_path / "a.wav").write_bytes(b"a")
    (tmp_path / "b.wav").write_bytes(b"b")
    captured = []
    import videodub.cli.run as run_cmd
    monkeypatch.setattr(run_cmd, "run_job", lambda job: captured.append(job))

    main([
        "run", str(tmp_path / "input.mp4"),
        "--ref-audio-0", str(tmp_path / "a.wav"),
        "--ref-audio-1", str(tmp_path / "b.wav"),
        "-o", str(tmp_path / "out.mp4"),
    ])
    job = captured[0]
    assert job.voice.speaker_map == {
        "SPEAKER_0": tmp_path / "a.wav",
        "SPEAKER_1": tmp_path / "b.wav",
    }


def test_run_keep_bg_maps_to_policy(tmp_path, monkeypatch):
    tmp_path = _media(tmp_path)
    captured = []
    import videodub.cli.run as run_cmd
    monkeypatch.setattr(run_cmd, "run_job", lambda job: captured.append(job))

    main([
        "run", str(tmp_path / "input.mp4"),
        "--ref-audio", str(tmp_path / "ref.wav"),
        "-o", str(tmp_path / "out.mp4"),
        "--keep-bg", "--bg-volume", "0.5",
    ])
    job = captured[0]
    assert job.mix.policy is MixPolicy.KEEP_BACKGROUND
    assert job.mix.background_volume_ratio == 0.5


def test_run_job_toml_with_cli_override(tmp_path, monkeypatch):
    tmp_path = _media(tmp_path)
    job_file = tmp_path / "job.toml"
    _posix = lambda p: str(p).replace("\\", "/")
    job_file.write_text(f"""
[input]
path = "{_posix(tmp_path / "input.mp4")}"

[output]
path = "{_posix(tmp_path / "out.mp4")}"

[voice]
ref_audio = "{_posix(tmp_path / "ref.wav")}"

[mix]
policy = "keep_background"
""", encoding="utf-8")
    captured = []
    import videodub.cli.run as run_cmd
    monkeypatch.setattr(run_cmd, "run_job", lambda job: captured.append(job))

    main(["run", "--job", str(job_file), "--tts-steps", "25"])
    job = captured[0]
    assert job.mix.policy is MixPolicy.KEEP_BACKGROUND  # TOML 保留
    assert job.tts.inference_steps == 25  # CLI 覆盖


def test_run_without_input_or_job_exits(tmp_path):
    with pytest.raises(SystemExit):
        main(["run", "-o", str(tmp_path / "out.mp4")])


def test_run_invalid_config_returns_1(tmp_path, capsys):
    tmp_path = _media(tmp_path)
    code = main([
        "run", str(tmp_path / "input.mp4"),
        "-o", str(tmp_path / "out.mp4"),
    ])
    assert code == 1
    assert "必须指定参考音色" in capsys.readouterr().err


# ── transcribe ──

def test_transcribe_command(tmp_path, monkeypatch):
    (tmp_path / "input.mp4").write_bytes(b"media")

    class FakeTranscriber:
        def transcribe(self, audio_path):
            import videodub.domain.transcript as tr
            return tr.Transcript.from_dicts(
                [{"start": 0.0, "end": 1.2, "text": "你好"}], source="funasr"
            )

    import videodub.cli.transcribe as tc
    monkeypatch.setattr(tc, "get_transcriber", lambda spec: FakeTranscriber())
    monkeypatch.setattr(tc, "run_ffmpeg_command", lambda *a, **kw: None)
    monkeypatch.setattr(tc, "ensure_ffmpeg_available", lambda: None)

    output = tmp_path / "transcript.json"
    code = main([
        "transcribe", str(tmp_path / "input.mp4"),
        "--backend", "funasr", "-o", str(output),
    ])

    assert code == 0
    items = json.loads(output.read_text(encoding="utf-8"))
    assert items[0]["text"] == "你好"


def test_transcribe_default_output_stage_numbering(tmp_path, monkeypatch):
    """无 -o 时默认落 output/<输入名>/01_transcript.json"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "video.mp4").write_bytes(b"media")

    class FakeTranscriber:
        def transcribe(self, audio_path):
            import videodub.domain.transcript as tr
            return tr.Transcript.from_dicts(
                [{"start": 0.0, "end": 1.2, "text": "你好"}], source="funasr"
            )

    import videodub.cli.transcribe as tc
    monkeypatch.setattr(tc, "get_transcriber", lambda spec: FakeTranscriber())
    monkeypatch.setattr(tc, "run_ffmpeg_command", lambda *a, **kw: None)
    monkeypatch.setattr(tc, "ensure_ffmpeg_available", lambda: None)

    code = main(["transcribe", "video.mp4"])

    assert code == 0
    expected = tmp_path / "output" / "video" / "01_transcript.json"
    assert expected.exists()


def test_run_default_output_stage_numbering(tmp_path, monkeypatch):
    """run 无 -o 时默认落 output/<输入名>/03_成品.mp4"""
    tmp_path = _media(tmp_path)
    monkeypatch.chdir(tmp_path)
    captured = []
    import videodub.cli.run as run_cmd
    monkeypatch.setattr(run_cmd, "run_job", lambda job: captured.append(job))

    code = main(["run", "input.mp4", "--ref-audio", "ref.wav"])

    assert code == 0
    assert captured[0].output.path == Path("output") / "input" / "03_成品.mp4"


# ── label ──

def _unlabeled_transcript(tmp_path):
    path = tmp_path / "transcript.json"
    path.write_text(json.dumps([
        {"id": "seg_0001", "start": 0.0, "end": 1.0, "text": "你好"},
        {"id": "seg_0002", "start": 1.0, "end": 2.0, "text": "再见"},
        {"id": "seg_0003", "start": 2.0, "end": 3.0, "text": "谢谢"},
    ], ensure_ascii=False), encoding="utf-8")
    return path


def test_label_apply_backfills_and_normalizes(tmp_path, capsys):
    src = _unlabeled_transcript(tmp_path)
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps([
        {"speaker": 0},
        {"speaker": 1},
        {"speaker": "SPEAKER_1"},
    ]), encoding="utf-8")
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "--apply", str(edited), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert [seg["speaker"] for seg in items] == ["SPEAKER_0", "SPEAKER_1", "SPEAKER_1"]
    assert "2 个说话人" in capsys.readouterr().out


def test_label_apply_sparse_merge_keeps_existing(tmp_path, capsys):
    """只改部分句子，未填写的保留原始标注"""
    src = tmp_path / "transcript.json"
    src.write_text(json.dumps([
        {"id": "seg_0001", "start": 0.0, "end": 1.0, "text": "你好", "speaker": "SPEAKER_0"},
        {"id": "seg_0002", "start": 1.0, "end": 2.0, "text": "再见", "speaker": "SPEAKER_1"},
        {"id": "seg_0003", "start": 2.0, "end": 3.0, "text": "谢谢", "speaker": "SPEAKER_0"},
    ], ensure_ascii=False), encoding="utf-8")
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps([
        {},
        {"speaker": 0},  # 只改这一句：SPEAKER_1 → SPEAKER_0
        {},
    ]), encoding="utf-8")
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "--apply", str(edited), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert [seg["speaker"] for seg in items] == ["SPEAKER_0", "SPEAKER_0", "SPEAKER_0"]


def test_label_apply_keeps_unlabeled_with_warning(tmp_path, capsys):
    """全部未标注时保留原始 speaker（如果有），发出警告"""
    src = tmp_path / "transcript.json"
    src.write_text(json.dumps([
        {"id": "seg_0001", "start": 0.0, "end": 1.0, "text": "你好", "speaker": "SPEAKER_0"},
        {"id": "seg_0002", "start": 1.0, "end": 2.0, "text": "再见"},
    ], ensure_ascii=False), encoding="utf-8")
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps([{}, {}]), encoding="utf-8")
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "--apply", str(edited), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert items[0]["speaker"] == "SPEAKER_0"
    assert items[1].get("speaker") is None
    assert "仍未标注" in capsys.readouterr().out


def test_label_apply_count_mismatch_returns_1(tmp_path, capsys):
    src = _unlabeled_transcript(tmp_path)
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps([{"speaker": 0}, {"speaker": 1}]), encoding="utf-8")

    code = main(["label", str(src), "--apply", str(edited)])

    assert code == 1
    assert "不一致" in capsys.readouterr().err


def test_label_interactive_assigns_speakers(tmp_path, monkeypatch, capsys):
    src = _unlabeled_transcript(tmp_path)
    answers = iter(["2=1", "w"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    speakers = [seg.get("speaker") for seg in items]
    assert speakers == [None, "SPEAKER_1", None]
    assert "2 个说话人" not in capsys.readouterr().out


def test_label_interactive_batch_and_range(tmp_path, monkeypatch):
    """13,17=0 逗号列表 与 1-2=0 区间语法"""
    src = _unlabeled_transcript(tmp_path)
    answers = iter(["1,3=0", "1-2=1", "w"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert [seg["speaker"] for seg in items] == ["SPEAKER_1", "SPEAKER_1", "SPEAKER_0"]


def test_label_walk_single_digit_assigns_and_advances(tmp_path, monkeypatch):
    """逐句审阅流：单数字改光标句说话人并自动前进到下一句"""
    src = _unlabeled_transcript(tmp_path)
    answers = iter(["1", "0", "w"])  # 第1句→人1，光标前进到2；第2句→人0
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert [seg.get("speaker") for seg in items] == ["SPEAKER_1", "SPEAKER_0", None]


def test_label_walk_enter_advances_cursor(tmp_path, monkeypatch):
    """空行回车 = 跳到下一句（不改动，也不报错）"""
    src = _unlabeled_transcript(tmp_path)
    answers = iter(["", "", "w"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert all(seg.get("speaker") is None for seg in items)


def test_label_help_supports_both_question_marks(tmp_path, monkeypatch, capsys):
    """? 和全角 ？ 都展开帮助表格，且不报错不修改数据"""
    src = _unlabeled_transcript(tmp_path)
    answers = iter(["?", "？", "w"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    assert "命令帮助" in capsys.readouterr().out
    items = json.loads(out.read_text(encoding="utf-8"))
    assert all(seg.get("speaker") is None for seg in items)


def test_label_walk_end_enter_prompts_restart(tmp_path, monkeypatch, capsys):
    """末尾 Enter 提示 r 从头审阅 / w 保存退出；r 回第 1 句后可继续改"""
    src = _unlabeled_transcript(tmp_path)
    # 3 句：Enter 到末尾（3 次）→ Enter 触发提示 → r 回第 1 句 → 1 改人1 → w 保存
    answers = iter(["", "", "", "", "r", "1", "w"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    assert "已到末尾" in capsys.readouterr().out
    items = json.loads(out.read_text(encoding="utf-8"))
    assert [seg.get("speaker") for seg in items] == ["SPEAKER_1", None, None]


def test_label_walk_multi_digit_jumps_to_segment(tmp_path, monkeypatch):
    """l 编号 跳转到指定句，然后 1 改当前句说话人并前进"""
    src = _unlabeled_transcript(tmp_path)
    answers = iter(["l 3", "1", "w"])  # l 3→跳到第3句；1→当前句(第3句)改人1
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert [seg.get("speaker") for seg in items] == [None, None, "SPEAKER_1"]


def test_label_walk_bare_range_jumps_to_segment(tmp_path, monkeypatch):
    """直接输入区间/列表（如 2-3 · 1,3）= 定位跳转，不改人"""
    src = _unlabeled_transcript(tmp_path)
    answers = iter(["2-3", "1", "w"])  # 2-3→跳到第2句；1→当前句(第2句)改人1
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert [seg.get("speaker") for seg in items] == [None, "SPEAKER_1", None]


def test_label_walk_highlighted_digit_still_assigns(tmp_path, monkeypatch):
    """单数字 0/1/2 均作为改当前句说话人（含 0），不变更序号语义"""
    src = _unlabeled_transcript(tmp_path)
    answers = iter(["0", "0", "w"])  # 句1→人0、句2→人0
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert [seg.get("speaker") for seg in items] == ["SPEAKER_0", "SPEAKER_0", None]


def test_label_walk_undo_restores_last_edit(tmp_path, monkeypatch):
    """撤销只回滚最后一次操作：句1→人1 保留，句2→人0 回退"""
    src = _unlabeled_transcript(tmp_path)
    answers = iter(["1", "0", "u", "w"])  # 句1→人1、句2→人0、撤销(句2)、保存
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert [seg.get("speaker") for seg in items] == ["SPEAKER_1", None, None]


def test_label_interactive_undo_restores(tmp_path, monkeypatch):
    src = _unlabeled_transcript(tmp_path)
    answers = iter(["2=1", "u", "w"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert all(seg.get("speaker") is None for seg in items)


def test_label_interactive_quit_discards(tmp_path, monkeypatch):
    src = _unlabeled_transcript(tmp_path)
    answers = iter(["2=1", "q", "y", "w", "q", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    assert not out.exists()


def test_label_default_output_follows_stage_numbering(tmp_path, monkeypatch):
    """输入 01_*.json 时默认输出同目录 02_labeled.json"""
    src = tmp_path / "01_transcript.json"
    src.write_text(json.dumps([
        {"id": "seg_0001", "start": 0.0, "end": 1.0, "text": "你好"},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda prompt="": "w")

    code = main(["label", str(src)])

    assert code == 0
    assert (tmp_path / "02_labeled.json").exists()


def test_label_default_output_inplace_for_labeled(tmp_path, monkeypatch):
    """输入已是 xx_labeled.json 时默认就地覆盖（不产生 _labeled_labeled）"""
    src = tmp_path / "02_labeled.json"
    src.write_text(json.dumps([
        {"id": "seg_0001", "start": 0.0, "end": 1.0, "text": "你好", "speaker": "SPEAKER_0"},
    ], ensure_ascii=False), encoding="utf-8")
    answers = iter(["w"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    code = main(["label", str(src)])

    assert code == 0
    assert src.exists()
    assert not (tmp_path / "02_labeled_labeled.json").exists()


# ── label 断句结构编辑（m 合并 / x 拆分 / d 删除）──

def _labeled_transcript(tmp_path):
    path = tmp_path / "transcript.json"
    path.write_text(json.dumps([
        {"id": "seg_0001", "start": 0.0, "end": 1.0, "text": "你好，"},
        {"id": "seg_0002", "start": 1.0, "end": 2.0, "text": "再见。", "speaker": "SPEAKER_1"},
        {"id": "seg_0003", "start": 2.0, "end": 3.0, "text": "谢谢"},
    ], ensure_ascii=False), encoding="utf-8")
    return path


def test_label_merge_segments(tmp_path, monkeypatch):
    src = _labeled_transcript(tmp_path)
    answers = iter(["m 1,2", "w"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert len(items) == 2
    assert items[0]["text"] == "你好，再见。"
    assert items[0]["start"] == 0.0
    assert items[0]["end"] == 2.0
    assert items[0]["speaker"] == "SPEAKER_1"  # 取第一个非空说话人
    assert [seg["id"] for seg in items] == ["seg_0001", "seg_0002"]  # id 按位置重排


def test_label_merge_with_custom_text(tmp_path, monkeypatch):
    """m 带合并后完整文本：合并顺带修标点"""
    src = _labeled_transcript(tmp_path)
    answers = iter(["m 1,2 你好，再见！", "w"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert len(items) == 2
    assert items[0]["text"] == "你好，再见！"
    assert items[0]["start"] == 0.0
    assert items[0]["end"] == 2.0


def test_label_merge_range_and_rejects_gap(tmp_path, monkeypatch):
    """m 1,3 非连续报错不动；m 1-3 区间合法"""
    src = _labeled_transcript(tmp_path)
    answers = iter(["m 1,3", "m 1-3", "w"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert len(items) == 1
    assert items[0]["text"] == "你好，再见。谢谢"


def test_label_split_by_text_ratio(tmp_path, monkeypatch):
    """x 1 你好|再见：切分点按字数比例（0-2s 的 2:2 → 1.0s）"""
    src = tmp_path / "transcript.json"
    src.write_text(json.dumps([
        {"id": "seg_0001", "start": 0.0, "end": 2.0, "text": "你好再见", "speaker": "SPEAKER_0"},
    ], ensure_ascii=False), encoding="utf-8")
    answers = iter(["x 1 你好|再见", "w"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert len(items) == 2
    assert items[0]["text"] == "你好"
    assert items[0]["end"] == 1.0
    assert items[1]["text"] == "再见"
    assert items[1]["start"] == 1.0
    assert [seg["speaker"] for seg in items] == ["SPEAKER_0", "SPEAKER_0"]  # 两半继承说话人
    assert [seg["id"] for seg in items] == ["seg_0001", "seg_0002"]


def test_label_split_explicit_time(tmp_path, monkeypatch):
    src = tmp_path / "transcript.json"
    src.write_text(json.dumps([
        {"id": "seg_0001", "start": 0.0, "end": 2.0, "text": "你好再见"},
    ], ensure_ascii=False), encoding="utf-8")
    answers = iter(["x 1 0.5 你好|再见", "w"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert items[0]["end"] == 0.5
    assert items[1]["start"] == 0.5


def test_label_delete_segments(tmp_path, monkeypatch):
    src = _labeled_transcript(tmp_path)
    answers = iter(["d 2", "w"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert [seg["text"] for seg in items] == ["你好，", "谢谢"]
    assert [seg["id"] for seg in items] == ["seg_0001", "seg_0002"]


def test_label_undo_structural_edit(tmp_path, monkeypatch):
    """结构操作（删除）可撤销"""
    src = _labeled_transcript(tmp_path)
    answers = iter(["d 2", "u", "w"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    out = tmp_path / "labeled.json"

    code = main(["label", str(src), "-o", str(out)])

    assert code == 0
    items = json.loads(out.read_text(encoding="utf-8"))
    assert len(items) == 3
    assert [seg["text"] for seg in items] == ["你好，", "再见。", "谢谢"]


# ── inspect / doctor ──

def test_inspect_command(tmp_path, monkeypatch, capsys):
    import videodub.cli.inspect as ic
    from videodub.domain.models import MediaAsset
    monkeypatch.setattr(ic, "probe_media", lambda p: MediaAsset(
        path=Path(p), kind="video", duration=12.5, has_video=True, has_audio=True,
        audio_sample_rate=48000, audio_channels=2,
    ))
    code = main(["inspect", "x.mp4"])
    out = capsys.readouterr().out
    assert code == 0
    assert "时长: 12.500 秒" in out
    assert "48000Hz / 2声道" in out


def test_doctor_command(monkeypatch):
    import videodub.cli.doctor as dc
    monkeypatch.setattr(dc.shutil, "which", lambda name: "C:/tools/" + name)  # ffmpeg/ffprobe 可用
    monkeypatch.setattr(dc, "_torch_info", lambda: "2.0.0 (CUDA: 不可用)")
    monkeypatch.setattr(dc, "_import_version", lambda name: "1.0.0")
    code = main(["doctor"])
    assert code == 0


def test_unknown_command_exits():
    with pytest.raises(SystemExit):
        main(["bogus"])