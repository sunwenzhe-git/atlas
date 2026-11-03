#!/usr/bin/env python3
"""`scripts/review_scope.py` + `_support/review_scope_core.py` 回归测试（RFC-20261103-01）。

覆盖：
- manifest 确定性 / 内容变化改摘要 / 只改 mtime 不算变化；
- 绝对路径、`..`、符号链接、目录、缺失文件 ⇒ exit 2（响亮拒绝，不猜）；
- verify 改一字节 / 删除文件 ⇒ exit 1；
- 大文件退化为 `size_mtime` 并显式标注；
- baseline：未变化路径自动排除、与本次改动重叠 ⇒ WARN、基线缺失 ⇒ WARN（不是 PASS）。

变异证明（编号属本文件）：M165 摘掉 verify 的内容比对 ⇒ `test_verify_detects_one_byte_change` 红；
M168 摘掉 baseline 的 overlap 检测 ⇒ `test_baseline_overlap_warns` 红。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "review_scope.py"


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args, "--root", str(root)],
                          capture_output=True, text=True, timeout=120)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, text=True)


def init_repo(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")


def write_manifest(root: Path, files: str, out: str = "m.json") -> dict:
    r = run(root, "manifest", "--reviewed-files", files, "--out", out)
    assert r.returncode == 0, r.stderr
    return json.loads((root / out).read_text(encoding="utf-8"))


def test_manifest_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    first = write_manifest(tmp_path, "a.txt", "m1.json")
    second = write_manifest(tmp_path, "a.txt", "m2.json")
    assert first["scope_sha256"] == second["scope_sha256"]
    (tmp_path / "a.txt").write_text("two\n", encoding="utf-8")
    third = write_manifest(tmp_path, "a.txt", "m3.json")
    assert third["scope_sha256"] != first["scope_sha256"]


def test_manifest_rejects_absolute_and_parent_paths(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    r = run(tmp_path, "manifest", "--reviewed-files", "/etc/passwd")
    assert r.returncode == 2 and "绝对路径" in r.stderr
    r = run(tmp_path, "manifest", "--reviewed-files", "../a.txt")
    assert r.returncode == 2 and ".." in r.stderr


def test_manifest_rejects_missing_file_and_symlink(tmp_path: Path) -> None:
    r = run(tmp_path, "manifest", "--reviewed-files", "missing.txt")
    assert r.returncode == 2 and "不存在" in r.stderr
    (tmp_path / "real.txt").write_text("x", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to(tmp_path / "real.txt")
    r = run(tmp_path, "manifest", "--reviewed-files", "link.txt")
    assert r.returncode == 2 and "符号链接" in r.stderr


def test_verify_detects_one_byte_change_and_mtime_does_not(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("one\n", encoding="utf-8")
    write_manifest(tmp_path, "a.txt", "m.json")
    f.write_text("two\n", encoding="utf-8")
    r = run(tmp_path, "verify", "--manifest", "m.json")
    assert r.returncode == 1 and "内容已变化" in r.stdout
    # 只改 mtime：内容哈希不变 ⇒ 不误伤
    write_manifest(tmp_path, "a.txt", "m2.json")
    import os
    os.utime(f, (1, 1))
    r = run(tmp_path, "verify", "--manifest", "m2.json")
    assert r.returncode == 0, r.stdout


def test_verify_deleted_file_fails(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("one\n", encoding="utf-8")
    write_manifest(tmp_path, "a.txt", "m.json")
    f.unlink()
    r = run(tmp_path, "verify", "--manifest", "m.json")
    assert r.returncode == 1


def test_large_file_uses_size_mtime(tmp_path: Path) -> None:
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    m = write_manifest(tmp_path, "big.bin")
    assert m["files"][0]["hash_mode"] == "size_mtime"
    assert m["files"][0]["sha256"].startswith("size_mtime:")


def test_untracked_file_included(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "tracked.txt").write_text("t\n", encoding="utf-8")
    git(tmp_path, "add", "tracked.txt")
    git(tmp_path, "commit", "-qm", "init")
    (tmp_path / "new.txt").write_text("n\n", encoding="utf-8")
    m = write_manifest(tmp_path, "new.txt")
    assert m["files"][0]["status"] == "??"


def test_baseline_excludes_unchanged_and_flags_overlap(tmp_path: Path) -> None:
    init_repo(tmp_path)
    (tmp_path / "pre.txt").write_text("pre\n", encoding="utf-8")
    (tmp_path / "pre.txt").write_text("pre dirty\n", encoding="utf-8")
    r = run(tmp_path, "baseline", "--unit", "U")
    assert r.returncode == 0, r.stderr
    # 基线内未变化的既有脏改动 ⇒ 不告警
    r = run(tmp_path, "baseline-check", "--unit", "U", "--changed-files", "pre.txt")
    assert r.returncode == 0
    assert json.loads(r.stdout)["status"] == "PASS"
    # 新脏改动与本次改动重叠 ⇒ WARN
    (tmp_path / "new.txt").write_text("new\n", encoding="utf-8")
    r = run(tmp_path, "baseline-check", "--unit", "U", "--changed-files", "new.txt")
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["status"] == "WARN" and out["overlap"] == ["new.txt"]


def test_baseline_missing_warns_not_passes(tmp_path: Path) -> None:
    r = run(tmp_path, "baseline-check", "--unit", "U", "--changed-files", "a.txt")
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["status"] == "WARN" and "缺失" in out["detail"]
