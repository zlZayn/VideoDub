"""任务加载 — TOML 文件 + CLI 覆盖合并为 JobSpec

合并优先级：CLI > TOML > 默认值。
CLI 覆盖以嵌套 dict 传入（与 JobSpec 字段同构，缺失键不覆盖）。
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from .job_spec import JobSpec


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并两个 dict，override 优先（叶子键替换）"""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_toml(job_path: Path) -> dict:
    """读取 job.toml 为 dict（标准库 tomllib）"""
    with open(job_path, "rb") as handle:
        return tomllib.load(handle)


def load_job(job_path: Path | None, cli_overrides: dict | None = None) -> JobSpec:
    """构建 JobSpec：job_path 缺失时只用 CLI 覆盖与默认值"""
    data: dict = {}
    if job_path is not None:
        data = load_toml(job_path)
    if cli_overrides:
        data = _deep_merge(data, cli_overrides)
    return JobSpec.model_validate(data)