#!/usr/bin/env python3
"""`check_history_prefix` 纯函数夹具（RFC-20261111-03 §1.1.3 ⑦ / T-33，B-0）。

假绿证明：`[a] → [a,b] → [a]` 必须 `Err`——按「某前版本」实现（`[a]` 是 `[a]` 的
前缀）会返回 `Ok` ⇒ 本文件断言红。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "_atlas_solution_history_prefix_test", PKG_ROOT / "_support" / "solution.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = _load()


def entry(name: str) -> dict:
    return {"from": "2026-11-05T00:00:00Z", "to": name, "commit": "c0ffee"}


A, B, C = entry("a"), entry("b"), entry("c")


def is_err(versions) -> tuple[str, dict] | None:
    err = core.check_history_prefix(versions)
    return None if err is None else (err.code, err.detail)


def test_empty_and_single_version_are_ok() -> None:
    assert is_err([]) is None
    assert is_err([[]]) is None
    assert is_err([[A]]) is None


def test_empty_is_zero_item_prefix_but_one_way() -> None:
    assert is_err([[], [A]]) is None
    code, detail = is_err([[A], []])
    assert code == "exemption_start_history_broken"
    assert detail["kind"] == "not_prefix"


def test_monotonic_append_is_ok() -> None:
    assert is_err([[], [A], [A, B], [A, B, C]]) is None


def test_rollback_is_err() -> None:
    """`[a] → [a,b] → [a]`：紧邻前版本 `[a,b]` 不是 `[a]` 的前缀。"""
    code, detail = is_err([[A], [A, B], [A]])
    assert code == "exemption_start_history_broken"
    assert detail["kind"] == "not_prefix"
    assert detail["index"] == 2


def test_rewrite_is_err() -> None:
    code, _ = is_err([[A], [A, B], [A, C]])
    assert code == "exemption_start_history_broken"


def test_single_version_add_two_items_is_err() -> None:
    code, detail = is_err([[], [A, B]])
    assert code == "exemption_start_history_broken"
    assert detail["kind"] == "multiple_appended"


def test_missing_key_recorded_as_empty_bucket() -> None:
    """「缺键 ⇒ `[]`」由构造层负责；喂进来的空桶按零项前缀处理。"""
    assert is_err([[], []]) is None
    assert is_err([[], [], [A]]) is None
