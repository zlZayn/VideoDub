"""测试统一日志工具

不调用任何模型，仅测试日志输出格式（videodub.utils.logger 与原 core.logger 同 API）。
"""

from io import StringIO
from unittest.mock import patch

from videodub.utils.logger import (
    log,
    log_error,
    log_progress,
    log_stage_header,
    log_success,
    log_warning,
)


def test_log_output_format():
    """测试 log 输出格式: [阶段] [时间] 内容"""
    with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        log("ASR", "识别到 5 句台词")
        output = mock_stdout.getvalue().strip()
    assert output.startswith("[ASR] [")
    assert "] 识别到 5 句台词" in output


def test_log_stage_header():
    """测试阶段标题输出包含分隔线"""
    with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        log_stage_header("TTS", "加载模型")
        output = mock_stdout.getvalue()
    assert "=" * 50 in output
    assert "[TTS]" in output
    assert "加载模型" in output


def test_log_progress():
    """测试进度输出"""
    with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        log_progress(3, 10, "生成中")
        output = mock_stdout.getvalue().strip()
    assert "[进度]" in output
    assert "[3/10]" in output
    assert "生成中" in output


def test_log_error_to_stderr():
    """测试错误输出到 stderr"""
    with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
        log_error("测试错误")
        output = mock_stderr.getvalue().strip()
    assert "[错误]" in output
    assert "测试错误" in output


def test_log_warning():
    """测试警告输出"""
    with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        log_warning("测试警告")
        output = mock_stdout.getvalue().strip()
    assert "[警告]" in output
    assert "测试警告" in output


def test_log_success():
    """测试成功输出"""
    with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
        log_success("完成")
        output = mock_stdout.getvalue().strip()
    assert "[完成]" in output
    assert "完成" in output