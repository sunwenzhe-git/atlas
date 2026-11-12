#!/usr/bin/env python3
"""RFC §6 B / D-40（v19/重要 3、v20/重要 5）：发版门。

`PRD_SCHEMA_2_FROM` 是 `prd_schema_too_low` 的锚点常量，必须等于 0.4.0 发布 tag
的 UTC 日期。skip 语义写死：

- 无 `GITHUB_REF_TYPE` / 不是 `tag` ⇒ skip（未在发布 tag 上运行）；
- `GITHUB_REF_NAME` 不是 `v0.4.0*` ⇒ skip（不是 0.4.0 发版）；
- `PRD_SCHEMA_2_FROM is None` ⇒ skip（常量未武装）；
- 仅 `tag` 且名字匹配 `v0.4.0*` 时断言：常量非 None 且等于 tag 的 UTC 日期。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]


def _load_core():
    path = PKG_ROOT / "_support" / "solution.py"
    spec = importlib.util.spec_from_file_location("_atlas_release_gate_core", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = _load_core()


def tag_utc_date(ref: str) -> str:
    """tag 指向提交的 UTC 日期（`%cI` ⇒ UTC）。"""
    out = subprocess.run(
        ["git", "-C", str(PKG_ROOT), "log", "-1", "--format=%cI", ref, "--"],
        check=True, capture_output=True, text=True).stdout.strip()
    return datetime.fromisoformat(out).astimezone(timezone.utc).date().isoformat()


def test_prd_schema_constant_matches_release_tag() -> None:
    ref_type = os.environ.get("GITHUB_REF_TYPE")
    ref_name = os.environ.get("GITHUB_REF_NAME", "")
    if ref_type != "tag":
        pytest.skip("未在发布 tag 上运行（GITHUB_REF_TYPE != tag）")
    if not ref_name.startswith("v0.4.0"):
        pytest.skip(f"不是 0.4.0 发版（GITHUB_REF_NAME={ref_name!r}）")
    if core.PRD_SCHEMA_2_FROM is None:
        pytest.skip("PRD_SCHEMA_2_FROM 未武装（发布时必须填发布日）")
    expected = tag_utc_date(os.environ.get("GITHUB_SHA") or f"refs/tags/{ref_name}")
    assert core.PRD_SCHEMA_2_FROM == expected, (
        f"PRD_SCHEMA_2_FROM={core.PRD_SCHEMA_2_FROM!r} 与 tag {ref_name} 的 UTC 日期 "
        f"{expected!r} 不一致")
