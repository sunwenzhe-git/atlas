#!/usr/bin/env python3
"""`path_at` 单源 + 三态夹具（RFC-20261111-03 §1.1.3 ⑦ / V-24，B-0）。

假绿证明：`test_single_probe_is_shared_by_both_call_sites` 用计数包装 `path_at`；
若任一侧另写一套探测（不经过 `path_at`），计数停在 1 ⇒ 断言红。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
LOCK = "atlas.solution.lock.json"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_atlas_solution_path_at_test", PKG_ROOT / "_support" / "solution.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = _load()


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], check=True,
                         capture_output=True, text=True)
    return out.stdout.strip()


def make_repo(path: Path) -> Path:
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.email", "a@b")
    git(path, "config", "user.name", "a")
    return path


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


def write_lock(repo: Path, text: str = '{"schema_version": 2}') -> None:
    (repo / LOCK).write_text(text, encoding="utf-8")


def test_absent_path_returns_absent(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    head = commit(repo, "init")
    assert core.path_at(repo, head) == (core.ABSENT, None)


def test_blob_path_returns_bytes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    write_lock(repo)
    head = commit(repo, "lock")
    state, text = core.path_at(repo, head)
    assert state == core.BLOB
    assert text == '{"schema_version": 2}'


def test_missing_commit_object_is_chain_unverifiable(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    write_lock(repo)
    commit(repo, "lock")
    with pytest.raises(core.ChainUnverifiable):
        core.path_at(repo, "0" * 40)


def test_symlink_is_non_blob_on_both_sides(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    (repo / "real.json").write_text('{"schema_version": 2}', encoding="utf-8")
    os.symlink("real.json", repo / LOCK)
    head = commit(repo, "symlink")
    with pytest.raises(core.LockHistoryUnparsable):
        core.path_at(repo, head)
    with pytest.raises(core.LockParseError):
        core.path_at(repo, head, current=True)


def test_tree_is_non_blob_not_absent(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    (repo / LOCK).mkdir()
    (repo / LOCK / "inner.txt").write_text("x\n", encoding="utf-8")
    head = commit(repo, "tree")
    with pytest.raises(core.LockHistoryUnparsable):
        core.path_at(repo, head)


def test_single_probe_is_shared_by_both_call_sites(
        tmp_path: Path, monkeypatch) -> None:
    """`build_lock_versions` 的 `fetch` 与 ⓪-1 历史循环必须走同一个 `path_at`。"""
    repo = make_repo(tmp_path / "repo")
    write_lock(repo, '{"schema_version": 2, "n": 1}')
    commit(repo, "lock")
    calls: list[tuple] = []
    real = core.path_at

    def counting(root, commit_sha, path=core.LOCK_PATH, **kwargs):
        calls.append((commit_sha, path))
        return real(root, commit_sha, path, **kwargs)

    monkeypatch.setattr(core, "path_at", counting)
    history = list(core.iter_lock_history(repo))
    fetched = core._history_fetch(repo)("HEAD")
    assert len(history) == 1 and fetched == '{"schema_version": 2, "n": 1}'
    assert len(calls) >= 2, calls


def test_shallow_clone_missing_object_is_chain_unverifiable(tmp_path: Path) -> None:
    """V-24 第三洞（浅仓）：浅边界外的提交对象本地缺失 ⇒ `ChainUnverifiable`。"""
    src = make_repo(tmp_path / "src")
    write_lock(src)
    old = commit(src, "lock")
    (src / "later.txt").write_text("x\n", encoding="utf-8")
    commit(src, "later")
    clone = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1",
                    f"file://{src}", str(clone)], check=True)
    assert subprocess.run(["git", "-C", str(clone), "rev-parse", "--is-shallow-repository"],
                          capture_output=True, text=True).stdout.strip() == "true"
    with pytest.raises(core.ChainUnverifiable):
        core.path_at(clone, old)


def test_load_lock_strict_maps_current_vs_history(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(core.LockParseError):
        core.load_lock_strict(root, "{not json", current=True)
    with pytest.raises(core.LockHistoryUnparsable):
        core.load_lock_strict(root, "{not json", current=False)
    with pytest.raises(core.LockParseError):
        core.load_lock_strict(root, '{"schema_version": 1.0, "members": [], '
                                    '"contracts": []}', current=True)


def test_load_lock_strict_rejects_bad_historical_root(tmp_path: Path) -> None:
    """历史根只做 lexical：`../x` 两侧都拒；中文 / 空格的合法根不拒。"""
    root = tmp_path / "repo"
    root.mkdir()
    bad = ('{"schema_version": 2, "assets_root_history": '
           '[{"root": "../x", "review": null, "commit": null}]}')
    with pytest.raises(core.LockHistoryUnparsable):
        core.load_lock_strict(root, bad, current=False)
    good = ('{"schema_version": 2, "assets_root_history": '
            '[{"root": "产品 资料", "review": null, "commit": null}]}')
    assert core.load_lock_strict(root, good, current=False)["schema_version"] == 2
