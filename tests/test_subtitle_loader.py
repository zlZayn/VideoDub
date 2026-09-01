"""测试字幕文件解析（videodub.pipeline.transcript_loader）

不调用任何模型，仅测试 SRT/ASS 解析逻辑与错误路径。
"""

import pytest

from videodub.pipeline.transcript_loader import load_subtitle_transcript


def test_parse_srt_basic(tmp_path):
    path = tmp_path / "a.srt"
    path.write_text("""1
00:00:01,000 --> 00:00:03,500
你好世界

2
00:00:04,000 --> 00:00:06,000
测试字幕
""", encoding="utf-8")
    transcript = load_subtitle_transcript(str(path))
    assert len(transcript.segments) == 2
    assert transcript.segments[0].range.start == 1.0
    assert transcript.segments[0].range.end == 3.5
    assert transcript.segments[0].text == "你好世界"
    assert transcript.segments[1].range.start == 4.0
    assert transcript.source == "subtitle"


def test_parse_srt_multiline(tmp_path):
    path = tmp_path / "a.srt"
    path.write_text("""1
00:00:01,000 --> 00:00:03,000
第一行
第二行
""", encoding="utf-8")
    transcript = load_subtitle_transcript(str(path))
    assert len(transcript.segments) == 1
    assert "第一行" in transcript.segments[0].text
    assert "第二行" in transcript.segments[0].text


def test_parse_ass_basic(tmp_path):
    path = tmp_path / "a.ass"
    path.write_text("""[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,你好世界
Dialogue: 0,0:00:04.00,0:00:06.00,Default,,0,0,0,,测试字幕
""", encoding="utf-8")
    transcript = load_subtitle_transcript(str(path))
    assert len(transcript.segments) == 2
    assert transcript.segments[0].range.start == 1.0
    assert transcript.segments[0].range.end == 3.5
    assert transcript.segments[0].text == "你好世界"


def test_empty_subtitle_raises(tmp_path):
    path = tmp_path / "empty.srt"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="字幕文件为空"):
        load_subtitle_transcript(str(path))


def test_unsupported_format_raises(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("test", encoding="utf-8")
    with pytest.raises(ValueError, match="不支持的字幕格式"):
        load_subtitle_transcript(str(path))