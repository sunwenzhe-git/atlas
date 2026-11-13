#!/usr/bin/env python3
"""运行期输出目录分配器（`_support/run_workspace.py`，DESIGN D194）的回归测试。

守护四件事：
  ① **每次 run 独立目录**（两次分配必不同），且都在仓库外——结构上消除仓内受限写 EACCES
     与同仓并发 run 互相清空产物；
  ② 两次 run 的产物**互不影响**（写入互不可见、互不覆盖）；
  ③ 清理策略只保留最近 N 次，且只在分配根内动作；
  ④ 旧仓内 `.atlas-run` **只提示不删除**（用户文件不归本工具清）。

    python3 -m pytest tests/test_run_workspace.py
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))


def load():
    spec = importlib.util.spec_from_file_location(
        "run_workspace", PKG_ROOT / "_support" / "run_workspace.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rw = load()


def _repo(td: Path) -> Path:
    root = td / "repo"
    (root / "product" / "e2e" / "scripts").mkdir(parents=True)
    return root


def test_two_runs_get_distinct_dirs_outside_repo(monkeypatch) -> None:
    """D194 核心钉：两次 run 的 outputDir 不同、都在仓库外。"""
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as cache:
        monkeypatch.setenv("ATLAS_RUN_ROOT", cache)
        root = _repo(Path(td))
        first = rw.new_run_dir(root)
        second = rw.new_run_dir(root)
        assert first != second
        assert first.is_dir() and second.is_dir()
        for path in (first, second):
            assert root.resolve() not in path.resolve().parents, f"运行目录落进仓内：{path}"
        assert first.parent == second.parent  # 同一 slug 下并列，不嵌套


def test_two_runs_do_not_clobber_each_other(monkeypatch) -> None:
    """两次 run 的产物互不影响（旧实现共用 `.atlas-run`，后起跑会清空前一次）。"""
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as cache:
        monkeypatch.setenv("ATLAS_RUN_ROOT", cache)
        root = _repo(Path(td))
        first = rw.new_run_dir(root)
        second = rw.new_run_dir(root)
        (first / "results.json").write_text('{"run": 1}', encoding="utf-8")
        (second / "results.json").write_text('{"run": 2}', encoding="utf-8")
        assert (first / "results.json").read_text(encoding="utf-8") == '{"run": 1}'
        assert (second / "results.json").read_text(encoding="utf-8") == '{"run": 2}'
        assert rw.latest_run_dir(root, exclude=second) == first


def test_prune_keeps_recent_n_only(monkeypatch) -> None:
    """清理策略：只保留最近 N 个 run 目录，且不越过 `<cache>/atlas-e2e/<slug>/runs`。"""
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as cache:
        monkeypatch.setenv("ATLAS_RUN_ROOT", cache)
        root = _repo(Path(td))
        runs = [rw.new_run_dir(root) for _ in range(5)]
        sentinel = rw.workspace_root(root) / "evidence" / "keep-me"
        sentinel.mkdir(parents=True)
        rw.prune(root, keep=2)
        left = sorted(p for p in (rw.workspace_root(root) / "runs").iterdir() if p.is_dir())
        assert len(left) == 2
        assert set(left).issubset(set(runs))
        assert sentinel.is_dir(), "prune 不得动 runs/ 之外的内容"


def test_workspace_root_honors_override_and_has_stable_slug(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as cache:
        monkeypatch.setenv("ATLAS_RUN_ROOT", cache)
        root = _repo(Path(td))
        ws = rw.workspace_root(root)
        assert ws.parent == Path(cache) / "atlas-e2e"
        assert ws == rw.workspace_root(root), "同一仓两次解析必须同 slug"
        other = _repo(Path(td) / "other")
        assert rw.workspace_root(other) != ws, "不同仓不得共用 slug"


def test_legacy_repo_run_dir_is_reported_but_never_deleted(monkeypatch) -> None:
    """兼容性：旧仓内 `.atlas-run` 存在时只提示，不删用户文件。"""
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as cache:
        monkeypatch.setenv("ATLAS_RUN_ROOT", cache)
        root = _repo(Path(td))
        legacy = root / "product" / "e2e" / "scripts" / ".atlas-run"
        legacy.mkdir(parents=True)
        (legacy / "trace.zip").write_bytes(b"user-data")
        assert rw.legacy_run_dir(root) == legacy
        rw.new_run_dir(root)
        rw.prune(root, keep=1)
        assert (legacy / "trace.zip").read_bytes() == b"user-data", "旧仓内产物不得被清理"
