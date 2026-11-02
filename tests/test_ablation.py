#!/usr/bin/env python3
"""消融事务工具（P3 首切片）回归测试。

覆盖：begin/restore/status、项目外快照、active/marker、删除恢复、冲突零写入、
备份损坏、dirty 面、state-root/ID/补丁边界、baseline/smoke、hash_only。
变异：M164（属本文件）restore 退回无条件写回 ⇒ 冲突用例红。
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ablation.py"

MODIFY = """diff --git a/a.txt b/a.txt
--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-old
+new
"""

DELETE = """diff --git a/b.txt b/b.txt
deleted file mode 100644
--- a/b.txt
+++ /dev/null
@@ -1 +0,0 @@
-bee
"""

NEW_FILE = """diff --git a/c.txt b/c.txt
new file mode 100644
--- /dev/null
+++ b/c.txt
@@ -0,0 +1 @@
+new
"""

MODE_ONLY = """diff --git a/a.txt b/a.txt
old mode 100644
new mode 100755
"""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "a@b.c")
    _git(root, "config", "user.name", "t")
    (root / "a.txt").write_text("old\n", encoding="utf-8")
    (root / "b.txt").write_text("bee\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    return root


def _patch(tmp_path: Path, body: str, name: str = "p.patch") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _env(state: Path) -> dict:
    return {**os.environ, "ATLAS_ABLATION_HOME": str(state)}


def run(root: Path, state: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args, "--root", str(root)],
                          cwd=str(root), env=_env(state),
                          capture_output=True, text=True, timeout=120)


def begin(root: Path, state: Path, patch: Path, *, ident: str = "t1",
          extra: list[str] | None = None) -> subprocess.CompletedProcess:
    return run(root, state, "begin", "--id", ident, "--patch", str(patch),
               "--scope", "test", "--timebox", "60",
               "--smoke", "true", *(extra or []))


def _state_dir(root: Path, state: Path) -> Path:
    h = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    return state / "roots" / h


def _result(root: Path, state: Path, ident: str = "t1") -> dict:
    return json.loads((_state_dir(root, state) / ident / "result.json").read_text())


def test_begin_and_restore_roundtrip(tmp_path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    p = begin(root, state, _patch(tmp_path, MODIFY))
    assert p.returncode == 0, p.stdout + p.stderr
    assert (root / "a.txt").read_text() == "new\n"
    active = json.loads((_state_dir(root, state) / "active.json").read_text())
    assert active["status"] == "active" and active["id"] == "t1"
    assert (root / ".atlas/ABLATION").is_file()
    p2 = run(root, state, "restore", "--id", "t1")
    assert p2.returncode == 0, p2.stdout + p2.stderr
    assert (root / "a.txt").read_text() == "old\n"
    assert not (root / ".atlas/ABLATION").exists()
    assert not (_state_dir(root, state) / "active.json").exists()
    assert _result(root, state)["status"] == "completed_hash_only"


def test_delete_restores_file(tmp_path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    p = begin(root, state, _patch(tmp_path, DELETE))
    assert p.returncode == 0, p.stdout + p.stderr
    assert not (root / "b.txt").exists()
    now = (root / "b.txt")
    p2 = run(root, state, "restore", "--id", "t1")
    assert p2.returncode == 0, p2.stdout + p2.stderr
    assert (root / "b.txt").read_text() == "bee\n"


def test_third_party_change_conflicts_without_writes(tmp_path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    assert begin(root, state, _patch(tmp_path, MODIFY)).returncode == 0
    (root / "a.txt").write_text("third\n", encoding="utf-8")
    p = run(root, state, "restore", "--id", "t1")
    assert p.returncode == 2
    assert (root / "a.txt").read_text() == "third\n"       # 冲突时零写入
    id_dir = _state_dir(root, state) / "t1"
    assert (id_dir / "conflict.json").is_file()
    assert (_state_dir(root, state) / "active.json").is_file()
    assert _result(root, state)["status"] == "aborted"


def test_corrupt_backup_refuses_restore(tmp_path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    assert begin(root, state, _patch(tmp_path, MODIFY)).returncode == 0
    backup = _state_dir(root, state) / "t1" / "before" / "a.txt"
    backup.write_text("corrupt\n", encoding="utf-8")
    p = run(root, state, "restore", "--id", "t1")
    assert p.returncode == 2
    assert (root / "a.txt").read_text() == "new\n"          # 不写坏备份
    assert (_state_dir(root, state) / "active.json").is_file()
    assert _result(root, state)["status"] == "restore_failed"


def test_touched_tracked_dirty_is_refused(tmp_path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    (root / "a.txt").write_text("dirty\n", encoding="utf-8")
    p = begin(root, state, _patch(tmp_path, MODIFY))
    assert p.returncode == 2
    assert not (_state_dir(root, state) / "active.json").exists()


def test_untouched_dirty_requires_allow_dirty(tmp_path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    (root / "b.txt").write_text("dirty\n", encoding="utf-8")
    patch = _patch(tmp_path, MODIFY)
    assert begin(root, state, patch).returncode == 2
    p = begin(root, state, patch, extra=["--allow-dirty"])
    assert p.returncode == 0, p.stdout + p.stderr
    assert run(root, state, "restore", "--id", "t1").returncode == 0


def test_state_root_inside_project_and_bad_id_are_refused(tmp_path) -> None:
    root = _repo(tmp_path)
    patch = _patch(tmp_path, MODIFY)
    p = run(root, tmp_path / "repo" / "state", "begin", "--id", "t1",
            "--patch", str(patch), "--scope", "test", "--smoke", "true")
    assert p.returncode == 2
    p2 = run(root, tmp_path / "state", "begin", "--id", "../x",
             "--patch", str(patch), "--scope", "test", "--smoke", "true")
    assert p2.returncode == 2


def test_unsupported_patch_forms_are_refused(tmp_path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    for body, name in ((NEW_FILE, "new.patch"), (MODE_ONLY, "mode.patch")):
        p = begin(root, state, _patch(tmp_path, body, name))
        assert p.returncode == 2, (name, p.stdout, p.stderr)


def test_duplicate_active_is_refused(tmp_path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    patch = _patch(tmp_path, MODIFY)
    assert begin(root, state, patch).returncode == 0
    p = run(root, state, "begin", "--id", "t2", "--patch", str(patch),
            "--scope", "test", "--smoke", "true")
    assert p.returncode == 2
    assert (_state_dir(root, state) / "active.json").is_file()


def test_no_smoke_hash_only(tmp_path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    p = run(root, state, "begin", "--id", "t1", "--patch",
            str(_patch(tmp_path, MODIFY)), "--scope", "test")
    assert p.returncode == 0, p.stdout + p.stderr
    p2 = run(root, state, "restore", "--id", "t1")
    assert p2.returncode == 0, p2.stdout + p2.stderr
    assert _result(root, state)["status"] == "completed_hash_only"


def _smoke_script(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "smoke.py"
    path.write_text(body, encoding="utf-8")
    return path


def _smoke_cmd(script: Path, counter: Path) -> str:
    return shlex.join([sys.executable, str(script), str(counter)])


def test_smoke_failure_keeps_active(tmp_path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    counter = tmp_path / "count.txt"
    script = _smoke_script(tmp_path, (
        "import pathlib,sys\n"
        "c=pathlib.Path(sys.argv[1]); n=int(c.read_text()) if c.exists() else 0\n"
        "c.write_text(str(n+1)); sys.exit(0 if n==0 else 1)\n"))
    p = run(root, state, "begin", "--id", "t1", "--patch",
            str(_patch(tmp_path, MODIFY)), "--scope", "test",
            "--smoke", _smoke_cmd(script, counter))
    assert p.returncode == 0, p.stdout + p.stderr
    p2 = run(root, state, "restore", "--id", "t1")
    assert p2.returncode == 2
    assert (root / "a.txt").read_text() == "old\n"          # 哈希已还原
    assert (_state_dir(root, state) / "active.json").is_file()
    assert _result(root, state)["status"] == "restore_failed"


def test_smoke_mutation_is_detected(tmp_path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    counter = tmp_path / "count.txt"
    script = _smoke_script(tmp_path, (
        "import pathlib,sys\n"
        "c=pathlib.Path(sys.argv[1]); n=int(c.read_text()) if c.exists() else 0\n"
        "if n>=1: (pathlib.Path.cwd()/'a.txt').write_text('mutated\\n')\n"
        "c.write_text(str(n+1)); sys.exit(0)\n"))
    p = run(root, state, "begin", "--id", "t1", "--patch",
            str(_patch(tmp_path, MODIFY)), "--scope", "test",
            "--smoke", _smoke_cmd(script, counter))
    assert p.returncode == 0, p.stdout + p.stderr
    p2 = run(root, state, "restore", "--id", "t1")
    assert p2.returncode == 2
    assert (_state_dir(root, state) / "active.json").is_file()
    assert _result(root, state)["status"] == "restore_failed"


def test_status_reports_active_and_remaining(tmp_path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    assert begin(root, state, _patch(tmp_path, MODIFY)).returncode == 0
    p = run(root, state, "status")
    assert p.returncode == 0
    assert "t1" in p.stdout and "remaining_min=" in p.stdout
    assert run(root, state, "restore", "--id", "t1").returncode == 0


def test_restore_when_already_before_is_noop(tmp_path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    assert begin(root, state, _patch(tmp_path, MODIFY)).returncode == 0
    (root / "a.txt").write_text("old\n", encoding="utf-8")   # 手工先还原
    p = run(root, state, "restore", "--id", "t1")
    assert p.returncode == 0, p.stdout + p.stderr
    assert (root / "a.txt").read_text() == "old\n"
    assert _result(root, state)["status"] == "completed_hash_only"


def test_restore_without_active_is_refused(tmp_path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    p = run(root, state, "restore", "--id", "none")
    assert p.returncode == 2


def test_patch_outside_root_is_refused(tmp_path) -> None:
    root = _repo(tmp_path)
    state = tmp_path / "state"
    body = ("diff --git a/../outside.txt b/../outside.txt\n"
            "--- a/../outside.txt\n+++ b/../outside.txt\n"
            "@@ -1 +1 @@\n-x\n+y\n")
    p = begin(root, state, _patch(tmp_path, body, "outside.patch"))
    assert p.returncode == 2


def test_after_manifest_write_failure_keeps_before_and_active(tmp_path, monkeypatch) -> None:
    """B1：apply 成功后 after manifest 写失败 ⇒ before/active 必须保留。"""
    import argparse
    import importlib.util
    spec = importlib.util.spec_from_file_location("ablation_mod", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    root = _repo(tmp_path)
    state = tmp_path / "state"
    patch = _patch(tmp_path, MODIFY)
    original = mod._atomic_json

    def failing(path, data):
        if path.name == "manifest.after.json":
            raise OSError("injected after-manifest failure")
        return original(path, data)

    monkeypatch.setattr(mod, "_atomic_json", failing)
    args = argparse.Namespace(id="t1", root=str(root), patch=str(patch),
                              scope="test", state_root=str(state), timebox=60,
                              smoke="true", owner="tester", allow_dirty=False)
    try:
        mod.cmd_begin(args)
    except (OSError, mod.AblationError):
        pass
    else:
        raise AssertionError("expected injected failure")
    id_dir = _state_dir(root, state) / "t1"
    assert (id_dir / "before" / "a.txt").read_text() == "old\n"
    assert (id_dir / "manifest.before.json").is_file()
    assert (_state_dir(root, state) / "active.json").is_file()
    assert (root / "a.txt").read_text() == "new\n"           # apply 已发生但现场保留
