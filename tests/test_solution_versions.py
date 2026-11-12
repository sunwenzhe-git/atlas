#!/usr/bin/env python3
"""`build_lock_versions` 纯函数夹具（RFC-20261111-03 §1.1.3 ⑦ 数组 C，B-0）。

假绿证明：本文件第一条断言 `len(versions) == 2`——若实现把「某版本没有该路径」
记成 `[]` 空版本（而不是跳过），长度变 3 ⇒ 必红。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "_atlas_solution_versions_test", PKG_ROOT / "_support" / "solution.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = _load()


def lock_text(entries=None, *, seal_anchors: str = "", extra: str = "") -> str:
    """构造最小锁原文；`seal_anchors=""` 使用默认 dict。"""
    if seal_anchors:
        anchors = seal_anchors
    elif entries is None:
        anchors = '{"exemption_start_history": []}'
    else:
        items = ", ".join(
            '{"from": "%s", "to": "%s", "commit": "%s"}' % (e[0], e[1], e[2])
            for e in entries)
        anchors = '{"exemption_start_history": [%s]}' % items
    return '{"schema_version": 2, "seal_anchors": %s%s}' % (anchors, extra)


def test_deleted_commit_is_skipped_not_recorded_as_empty_version() -> None:
    """c1 / c2 有锁、c3 删除 ⇒ 恰两版；记成 `[]` 会变三版（假绿证明）。"""
    c1 = lock_text([])
    c2 = lock_text([("a", "b", "c0ffee")])
    texts = {"c1": c1, "c2": c2, "c3": None}
    versions = core.build_lock_versions(
        ["c1", "c2", "c3"], texts.__getitem__, None, head_has_path=False)
    assert len(versions) == 2, versions
    assert versions[0] == [] and len(versions[1]) == 1


def test_merge_duplicate_sha_is_deduped() -> None:
    """`-m --full-history` 的多父重复按 `%H` 去重（构造层清理，不产生判据）。"""
    text = lock_text([("a", "b", "c0ffee")])
    versions = core.build_lock_versions(
        ["c1", "c2", "c1"], {"c1": text, "c2": text}.__getitem__, None,
        head_has_path=False)
    assert len(versions) == 2


def test_worktree_appended_only_when_head_has_path_and_bytes_differ() -> None:
    head = lock_text([])
    worktree = lock_text([("a", "b", "c0ffee")])
    versions = core.build_lock_versions(
        ["c1"], {"c1": head}.__getitem__, worktree, head_has_path=True)
    assert len(versions) == 2 and len(versions[-1]) == 1

    same = core.build_lock_versions(
        ["c1"], {"c1": head}.__getitem__, head, head_has_path=True)
    assert len(same) == 1


def test_head_without_path_does_not_append_worktree_version() -> None:
    """锁未跟踪 / HEAD 无该路径 ⇒ 不追加工作树版（`versions == []`）。"""
    versions = core.build_lock_versions(
        ["c1"], {"c1": None}.__getitem__, lock_text([]), head_has_path=True)
    assert versions == []


def test_worktree_removed_does_not_append() -> None:
    """HEAD 有该路径、工作树被 `rm` ⇒ 不追加（没有可比对象）。"""
    versions = core.build_lock_versions(
        ["c1"], {"c1": lock_text([])}.__getitem__, None, head_has_path=True)
    assert len(versions) == 1


def test_delete_then_rebuild_byte_identical_is_ok() -> None:
    """c1 有锁、c2 删除、c3 与 c1 逐字节相同 ⇒ 两版且前缀判据 `Ok`。"""
    text = lock_text([("a", "b", "c0ffee")])
    versions = core.build_lock_versions(
        ["c1", "c2", "c3"], {"c1": text, "c2": None, "c3": text}.__getitem__,
        None, head_has_path=False)
    assert len(versions) == 2, versions
    assert core.check_history_prefix(versions) is None


def test_boundary_inputs_never_raise() -> None:
    """四边界：缺键 / `seal_anchors` 为 null 或非 dict / `exemption_start_history` 非 list。"""
    for text in (
        '{"schema_version": 2}',
        '{"schema_version": 2, "seal_anchors": null}',
        '{"schema_version": 2, "seal_anchors": []}',
        '{"schema_version": 2, "seal_anchors": {"exemption_start_history": null}}',
        '{"schema_version": 2, "seal_anchors": {"exemption_start_history": 7}}',
    ):
        versions = core.build_lock_versions(
            ["c1"], {"c1": text}.__getitem__, None, head_has_path=False)
        assert versions == [[]], text
