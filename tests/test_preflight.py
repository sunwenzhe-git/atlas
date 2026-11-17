#!/usr/bin/env python3
"""批次预检的出厂测试（2026-11-17 账本设计案步 5 / 审计 F1）。

钉住四件事：
  1. 反查命中：模块名 / 相对路径 / 文件名任一出现即命中（过近似方向）；
  2. 窄集：账本正文、装配面各自的固定落点；
  3. 无覆盖必须显式列出，不许静默放过（也不许假装通过）；
  4. 批次范围 = 提交 + 工作树 + 未跟踪；空批次 exit 2 而不是退回 HEAD~1。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PKG_ROOT = TESTS_DIR.parent
for extra in (TESTS_DIR, PKG_ROOT / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import preflight  # noqa: E402

NARROW = ("test_canonical_consistency.py", "test_map_anchors.py",
          "test_ledger_snapshot.py", "test_gate_registry.py",
          "test_assembly_surface.py", "test_cli_commands.py",
          "test_project_wiring.py")


def _mk_root(tmp: Path) -> Path:
    for d in ("tests", "scripts", "validators", "_support", "docs/map",
              "shared", "bin", ".github/workflows"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    (tmp / "tests" / "test_a.py").write_text(
        'from x import load_module\n'
        'M = load_module("foo")\n'
        'P = "validators/bar.py"\n'
        'Q = "install.py"\n', encoding="utf-8")
    (tmp / "tests" / "test_b.py").write_text(
        'def test_b():\n    assert True\n', encoding="utf-8")
    for name in NARROW:
        (tmp / "tests" / name).write_text(
            'def test_placeholder():\n    pass\n', encoding="utf-8")
    (tmp / "scripts" / "foo.py").write_text("x = 1\n", encoding="utf-8")
    (tmp / "validators" / "bar.py").write_text("y = 1\n", encoding="utf-8")
    (tmp / "install.py").write_text("z = 1\n", encoding="utf-8")
    return tmp


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t",
                    "-c", "user.name=t", *args],
                   capture_output=True, text=True, check=True)


def test_maps_module_name_and_path_references(tmp_path):
    root = _mk_root(tmp_path)
    mapping, uncovered = preflight.select(
        root, ["scripts/foo.py", "validators/bar.py"])
    assert mapping["scripts/foo.py"] == ["tests/test_a.py"]
    assert mapping["validators/bar.py"] == ["tests/test_a.py"]
    assert uncovered == []


def test_changed_test_file_runs_itself(tmp_path):
    root = _mk_root(tmp_path)
    mapping, uncovered = preflight.select(root, ["tests/test_b.py"])
    assert mapping["tests/test_b.py"] == ["tests/test_b.py"]
    assert uncovered == []


def test_ledger_and_assembly_narrow_sets(tmp_path):
    root = _mk_root(tmp_path)
    mapping, _ = preflight.select(
        root, ["DESIGN.md", "shared/gates.md", "docs/map/index.md",
               "install.py", ".github/workflows/tests.yml"])
    ledger = ["tests/test_canonical_consistency.py", "tests/test_ledger_snapshot.py",
              "tests/test_map_anchors.py", "tests/test_gate_registry.py"]
    assembly = ["tests/test_assembly_surface.py", "tests/test_cli_commands.py",
                "tests/test_project_wiring.py"]
    assert mapping["DESIGN.md"] == sorted(ledger)
    assert mapping["shared/gates.md"] == sorted(ledger)
    assert mapping["install.py"] == sorted(assembly)
    assert mapping[".github/workflows/tests.yml"] == sorted(assembly)


def test_uncovered_file_is_explicit(tmp_path, capsys):
    root = _mk_root(tmp_path)
    rc = preflight.main(["--root", str(root), "--files", "scripts/brand_new.py",
                         "--list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[无覆盖]" in out and "scripts/brand_new.py" in out


def test_empty_batch_exits_2(tmp_path, capsys):
    root = _mk_root(tmp_path)
    assert preflight.main(["--root", str(root), "--files"]) == 2
    assert "批次为空" in capsys.readouterr().out


def test_list_does_not_run_pytest(tmp_path, capsys, monkeypatch):
    root = _mk_root(tmp_path)

    def _boom(*a, **k):  # 一旦调用就说明 --list 失效
        raise AssertionError("--list 不应执行 pytest")
    monkeypatch.setattr(preflight.subprocess, "run", _boom)
    assert preflight.main(["--root", str(root), "--files", "scripts/foo.py",
                           "--list"]) == 0
    assert "tests/test_a.py" in capsys.readouterr().out


def test_changed_files_covers_commit_worktree_and_untracked(tmp_path):
    root = _mk_root(tmp_path)
    (root / "tests" / "test_a.py").write_text("x = 0\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    (root / "tests" / "test_a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "scripts" / "new_untracked.py").write_text("n = 1\n", encoding="utf-8")
    assert preflight.changed_files(root, "HEAD") == [
        "scripts/new_untracked.py", "tests/test_a.py"]
    _git(root, "add", "tests/test_a.py")
    _git(root, "commit", "-q", "-m", "batch")
    assert preflight.changed_files(root, "HEAD~1") == [
        "scripts/new_untracked.py", "tests/test_a.py"]
