"""统一测试入口 — 薄壳：等价于 `python -m pytest -q tests`

运行方式：
  .venv/Scripts/python.exe tests/run_all_tests.py
"""

import sys

import pytest

if __name__ == "__main__":
    sys.exit(pytest.main(["-q", "tests"]))