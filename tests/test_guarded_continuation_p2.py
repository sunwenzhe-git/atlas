#!/usr/bin/env python3
"""Guarded Continuation P2 业务写链（`atlas workflow finish` 纳入治理链）三层测试。

覆盖方案 §8 P2 六条硬前置 + 四项独立测试（commit 指纹 / archive 证书路径 / dir_fsync / 崩溃恢复）：
  1. 纯 Python 层：plan 顺序门、preflight 零写盘、共享 flock 互斥与禁 O_TRUNC/unlink、
     dir_fsync 实证、WAL 截断与 UNKNOWN 只读恢复；
  2. CLI 层：atlas_continue.py 全写链（preflight → deferred → commit → archive → audit）、
     post-commit hook 篡改触发 UNKNOWN、归档守恒复核与证书归档路径；
  3. bun 假宿主 + 真扩展：M3 开户门槛、两段 UI 确认（二段拒签零落盘）、lock-hold 锁对抗、
     codemode 直调/跨扩展防绕过、writeStarted→UNKNOWN 不可覆写与 revoke 拒洗白、
     recover 只诊断零重放、净化启动器与双 git 包装器闭包（PYTHONDONTWRITEBYTECODE=1）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support import guarded_continuation as gc  # noqa: E402
from _support.workflow_finish import (  # noqa: E402
    FinishError,
    archive_task,
    finish_task,
    preflight_finish,
)
from _support.workflow_plan import load_tasks  # noqa: E402

CONTINUE_CLI = PKG_ROOT / "scripts" / "atlas_continue.py"
WORKFLOW_CLI = PKG_ROOT / "scripts" / "atlas_workflow.py"


def _init_onboarded_repo(
    root: Path,
    unit: str = "TASK-P2-1",
    *,
    actions: list[dict] | None = None,
    stage_code: bool = True,
    review_ok: bool = True,
    pre_existing: bool = False,
    onboarded: bool = True,
    fresh_baseline: bool = True,
) -> Path:
    """构造带完整（或半）开户结构基线、任务卡、审查 PASS 证明与暂存改动的隔离 git 仓。"""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Tester"], check=True)

    (root / "product" / "prd").mkdir(parents=True, exist_ok=True)
    (root / "product" / "prd" / "prd.md").write_text("# PRD\n\n## AC-1\nok\n", encoding="utf-8")
    (root / "product" / "reviews" / f"2026-11-27-impl-review-{unit}").mkdir(parents=True, exist_ok=True)

    atlas = root / ".atlas"
    (atlas / "scripts").mkdir(parents=True, exist_ok=True)
    (atlas / "tasks" / unit).mkdir(parents=True, exist_ok=True)
    (atlas / "spec" / "structure").mkdir(parents=True, exist_ok=True)

    # 拷贝执行链依赖脚本（含 refresh_structure 以供 check_structure_freshness 解析）
    for name in ("atlas_continue.py", "atlas_workflow.py", "refresh_structure.py"):
        shutil.copy2(PKG_ROOT / "scripts" / name, atlas / "scripts" / name)
    shutil.copytree(PKG_ROOT / "_support", atlas / "_support", dirs_exist_ok=True)
    for pycache in (atlas / "_support").rglob("__pycache__"):
        shutil.rmtree(pycache)

    (atlas / "config.yaml").write_text("workflow:\n  receipt_mode: shadow\n", encoding="utf-8")
    (atlas / "tasks" / unit / "task.json").write_text(
        json.dumps({"id": unit, "title": "P2 task", "status": "in_progress", "acs": ["AC-1"]}, indent=2) + "\n",
        encoding="utf-8",
    )
    (atlas / "tasks" / unit / "notes.txt").write_text("extra card note\n", encoding="utf-8")

    default_actions = [
        {"id": "pre", "tool": "atlas_workflow_finish_preflight", "args": {"unit": unit}, "guard": {"kind": "always"}},
        {"id": "def", "tool": "atlas_workflow_finish_deferred", "args": {"unit": unit},
         "guard": {"kind": "all_of", "refs": ["pre.exit_code", "pre.json_ok"]}},
        {"id": "com", "tool": "atlas_workflow_finish_commit", "args": {"unit": unit},
         "guard": {"kind": "all_of", "refs": ["def.exit_code", "def.json_ok"]}},
        {"id": "arc", "tool": "atlas_workflow_finish_archive", "args": {"unit": unit},
         "guard": {"kind": "all_of", "refs": ["com.exit_code", "com.json_ok"]}},
    ]
    (atlas / "tasks" / unit / "continuation.json").write_text(
        json.dumps({
            "schema": 1,
            "unit": unit,
            "author": "human",
            "actions": actions if actions is not None else default_actions,
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()

    if onboarded:
        baseline_commit = head if fresh_baseline else "0" * 40
        (atlas / "spec" / "structure" / "_meta.json").write_text(
            json.dumps({"schema_version": 1, "baseline": {"commit": baseline_commit}}, indent=2) + "\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(root), "add", ".atlas/spec/structure/_meta.json"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "onboard"], check=True)
        if fresh_baseline:
            head2 = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
            meta = json.loads((atlas / "spec" / "structure" / "_meta.json").read_text(encoding="utf-8"))
            meta["baseline"]["commit"] = head2
            # .atlas/ 属于 clean_exempt_prefixes，同 refresh_structure --advance-baseline 一致重锚到当前 HEAD
            (atlas / "spec" / "structure" / "_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    if stage_code:
        (root / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "app.py"], check=True)

    checks = []
    if pre_existing:
        checks.append({
            "check": "style", "target": "app.py", "level": "Minor",
            "pre_existing": True, "disposition": "open", "detail": "legacy comment",
        })
    (root / "product" / "reviews" / f"2026-11-27-impl-review-{unit}" / "review.json").write_text(
        json.dumps({
            "unit": unit,
            "status": "PASS" if review_ok else "FAIL",
            "ok": review_ok,
            "round": 1,
            "checks": checks,
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    return root / ".atlas" / "tasks" / unit


# ────────────────────────────────────────────────────────────── 1. 纯 Python 层


def test_p2_plan_schema_and_order_M260(tmp_path: Path) -> None:
    """M260：写链动作必须以 preflight 起始、严格递增且不重复；禁止 force 与 extra args。"""
    t_dir = tmp_path / ".atlas" / "tasks" / "U-1"
    t_dir.mkdir(parents=True)
    plan_file = t_dir / "continuation.json"

    bad_cases = [
        # 缺 preflight 直接 commit
        [{"id": "c", "tool": "atlas_workflow_finish_commit", "args": {"unit": "U-1"}, "guard": {"kind": "always"}}],
        # archive 先于 commit
        [
            {"id": "p", "tool": "atlas_workflow_finish_preflight", "args": {"unit": "U-1"}, "guard": {"kind": "always"}},
            {"id": "a", "tool": "atlas_workflow_finish_archive", "args": {"unit": "U-1"}, "guard": {"kind": "always"}},
            {"id": "c", "tool": "atlas_workflow_finish_commit", "args": {"unit": "U-1"}, "guard": {"kind": "always"}},
        ],
        # 重复 write 动作
        [
            {"id": "p", "tool": "atlas_workflow_finish_preflight", "args": {"unit": "U-1"}, "guard": {"kind": "always"}},
            {"id": "c1", "tool": "atlas_workflow_finish_commit", "args": {"unit": "U-1"}, "guard": {"kind": "always"}},
            {"id": "c2", "tool": "atlas_workflow_finish_commit", "args": {"unit": "U-1"}, "guard": {"kind": "always"}},
        ],
        # 携带 extra 参数
        [
            {"id": "p", "tool": "atlas_workflow_finish_preflight", "args": {"unit": "U-1", "force": True}, "guard": {"kind": "always"}},
        ],
    ]
    for actions in bad_cases:
        plan_file.write_text(json.dumps({"schema": 1, "unit": "U-1", "author": "human", "actions": actions}), encoding="utf-8")
        with pytest.raises(gc.PlanError):
            gc.load_plan(tmp_path, "U-1")

    # 顶层 force 也必须拒
    plan_file.write_text(json.dumps({
        "schema": 1, "unit": "U-1", "author": "human", "force": True,
        "actions": [{"id": "p", "tool": "atlas_workflow_finish_preflight", "args": {"unit": "U-1"}, "guard": {"kind": "always"}}],
    }), encoding="utf-8")
    with pytest.raises(gc.PlanError):
        gc.load_plan(tmp_path, "U-1")


def test_p2_preflight_pure_readonly_no_writes(tmp_path: Path) -> None:
    """硬前置 1（RFC preflight 零写盘判别检查）：成功或失败路径均不得写入 deferred/attempts/task.json/receipt。"""
    t_dir = _init_onboarded_repo(tmp_path, "UNIT-PRE", pre_existing=True)
    task = load_tasks(tmp_path / ".atlas" / "tasks")[0]

    res = preflight_finish(tmp_path, task, require_full_onboarding=True)
    assert res["ok"] is True
    assert res["deferred_plan"]["registered"] == 1
    assert not (t_dir / "deferred.md").exists(), "preflight 不得写入 deferred.md"
    assert not (t_dir / "attempts.jsonl").exists(), "preflight 不得写入 attempts.jsonl"
    assert not (tmp_path / ".atlas" / "runs" / "workflow-receipt.json").exists()
    assert json.loads((t_dir / "task.json").read_text(encoding="utf-8"))["status"] == "in_progress"

    # 失败路径（陈旧 baseline）同样零写盘
    t_dir2 = _init_onboarded_repo(tmp_path / "stale", "UNIT-STALE", pre_existing=True, fresh_baseline=False)
    task2 = load_tasks(tmp_path / "stale" / ".atlas" / "tasks")[0]
    with pytest.raises(FinishError) as exc_info:
        preflight_finish(tmp_path / "stale", task2, require_full_onboarding=True)
    assert exc_info.value.cause == "freshness_fail"
    assert not (t_dir2 / "deferred.md").exists()
    assert not (t_dir2 / "attempts.jsonl").exists()


def test_p2_shared_write_lock_cross_process_M261(tmp_path: Path) -> None:
    """M261（硬前置 2）：所有写者共享 flock，禁 O_TRUNC 毁锁 / 禁 unlink；崩溃退即释放；重入不自死锁。"""
    t_dir = _init_onboarded_repo(tmp_path, "UNIT-LCK")
    run_id = "gc-lock-test-1"
    token = "tok-" + "a" * 24

    proc = subprocess.Popen(
        [sys.executable, "-B", str(CONTINUE_CLI), "lock-hold",
         "--root", str(tmp_path), "--unit", "UNIT-LCK", "--run-dir", run_id],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        proc.stdin.write(json.dumps({"token": token}) + "\n")
        proc.stdin.flush()
        ready = proc.stdout.readline().strip()
        assert ready == "LOCKED", f"lock-hold 未就绪: {ready} err={proc.stderr.read()}"

        lock_file = tmp_path / gc.WRITE_LOCK_REL
        assert lock_file.is_file()
        meta_before = json.loads(lock_file.read_text(encoding="utf-8"))
        assert meta_before["pid"] == proc.pid
        assert token not in lock_file.read_text(encoding="utf-8"), "写锁文件严禁落盘明文 token"

        # 租约校验通过 & 错误 token 失败
        gc.verify_write_lock_lease(tmp_path, run_id, "UNIT-LCK", token)
        with pytest.raises(gc.WriteLockError):
            gc.verify_write_lock_lease(tmp_path, run_id, "UNIT-LCK", "wrong-token")

        # 持锁期间，同进程 / 外部 workflow CLI finish 均立即被拒且不得 O_TRUNC 原锁元数据
        with pytest.raises(gc.WriteLockError):
            gc.WriteLock(tmp_path, holder="intruder").acquire()
        assert json.loads(lock_file.read_text(encoding="utf-8")) == meta_before

        ext_finish = subprocess.run(
            [sys.executable, "-B", str(WORKFLOW_CLI), "--root", str(tmp_path), "finish", "--unit", "UNIT-LCK"],
            capture_output=True, text=True, timeout=30,
        )
        assert ext_finish.returncode == 2
        assert "互斥锁" in (ext_finish.stderr + ext_finish.stdout)
        assert json.loads(lock_file.read_text(encoding="utf-8")) == meta_before

        # 模拟宿主崩溃（SIGKILL lock-hold）：内核立即回收并释放 flock，inode 不 unlink
        ino_before = lock_file.stat().st_ino
        proc.kill()
        proc.wait(timeout=5)
        assert lock_file.exists() and lock_file.stat().st_ino == ino_before

        with gc.WriteLock(tmp_path, holder="after-crash", unit="UNIT-LCK"):
            pass
        assert lock_file.exists() and lock_file.stat().st_ino == ino_before
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    # finish_task → archive_task 嵌套重入不得自死锁（_lock_held=True）
    task = load_tasks(tmp_path / ".atlas" / "tasks")[0]
    res = finish_task(tmp_path, task)
    assert res["status"] == "completed"
    assert res["archived"]["status"] == "moved"


def test_p2_dir_fsync_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """硬前置 5（独立 test_dir_fsync）：原子落盘、WAL 与 archive_task 必须对目录执行 os.fsync。"""
    t_dir = _init_onboarded_repo(tmp_path, "UNIT-FSYNC")
    fsync_calls: list[int] = []
    real_fsync = os.fsync

    def spy_fsync(fd: int) -> None:
        fsync_calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(gc.os, "fsync", spy_fsync)
    dir_targets: list[Path] = []
    real_fsync_dir = gc.fsync_dir

    def spy_fsync_dir(p: Path) -> None:
        dir_targets.append(Path(p).resolve())
        real_fsync_dir(p)

    monkeypatch.setattr(gc, "fsync_dir", spy_fsync_dir)
    import _support.workflow_finish as wf
    monkeypatch.setattr(wf, "fsync_dir", spy_fsync_dir)

    run = gc.run_dir(tmp_path, "gc-fsync-1")
    gc.append_wal(run, {"phase": "INTENT", "action_index": 1, "action_id": "a1", "tool": "atlas_workflow_finish_commit"})
    gc.write_json_exclusive(run / "raw-receipts" / "1-abc.json", {"canonical_hash": "abc", "result": {}})
    gc.atomic_write_json_durable(t_dir / "task.json", {"id": "UNIT-FSYNC", "status": "completed"})

    tasks_root = (tmp_path / ".atlas" / "tasks").resolve()
    arch = archive_task(tmp_path, tasks_root, t_dir, "UNIT-FSYNC")
    assert arch["status"] == "moved"

    assert len(fsync_calls) >= 4
    expected_dirs = {
        run.resolve(),
        (run / "raw-receipts").resolve(),
        t_dir.resolve(),
        tasks_root,
        (tasks_root / "archive").resolve(),
        (tasks_root / "archive" / date.today().strftime("%Y-%m")).resolve(),
    }
    for d in expected_dirs:
        assert d in dir_targets, f"缺少 dir_fsync：{d}（实测={dir_targets}）"


def test_p2_wal_and_crash_recovery_M263(tmp_path: Path) -> None:
    """M263（硬前置 4/5 独立 crash recovery）：WAL 半行/悬空 INTENT ⇒ UNKNOWN，diagnose 只读且禁止自动重放。"""
    _init_onboarded_repo(tmp_path, "UNIT-CRASH")
    run = gc.run_dir(tmp_path, "gc-crash-1")
    gc.append_wal(run, {
        "phase": "INTENT",
        "action_index": 2,
        "action_id": "com",
        "tool": "atlas_workflow_finish_commit",
        "target_paths": [".atlas/tasks/UNIT-CRASH/task.json"],
    })
    # 模拟崩溃在 write 后未 COMMITTED，还留下尾部未换行半行
    with (gc.wal_path(run)).open("a", encoding="utf-8") as fh:
        fh.write('{"phase":"COMMITTED","trunc')

    entries, truncated = gc.read_wal(run)
    assert len(entries) == 1 and truncated is True
    summary = gc.wal_state_summary(entries, truncated)
    assert summary["is_unknown"] is True
    assert len(summary["dangling_intents"]) == 1

    # 尾部半行时严禁继续追加写
    with pytest.raises(gc.PlanError):
        gc.append_wal(run, {"phase": "COMMITTED", "action_index": 2})

    diag = gc.diagnose_unknown(tmp_path, run, "UNIT-CRASH")
    assert diag["auto_replay_allowed"] is False
    assert diag["has_truncated_tail"] is True
    assert diag["active_task_exists"] is True
    assert diag["dangling_intents"][0]["tool"] == "atlas_workflow_finish_commit"


# ────────────────────────────────────────────────────────────── 2. CLI 与包装器工具

_READONLY_LAUNCHER_TPL = """#!/bin/sh
set -u
GC_LOG="$1"; SCRIPT="$2"; shift 2
[ -n "$GC_LOG" ] || exit 126
[ -f "$SCRIPT" ] || exit 126
GITDIR=$(dirname "$(command -v git)")
export PATH="__BIN__:$GITDIR:/usr/bin:/bin"
exec env -i PATH="$PATH" HOME="$HOME" LANG="${LC_ALL:-en_US.UTF-8}" \\
  PYTHONDONTWRITEBYTECODE=1 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \\
  GIT_OPTIONAL_LOCKS=0 ATLAS_GC_LOG="$GC_LOG" ATLAS_GC_ROOT="__ROOT__" \\
  __PYTHON__ -I -B "$SCRIPT" "$@"
"""

_WRITE_LAUNCHER_TPL = """#!/bin/sh
set -u
GC_LOG="$1"; SCRIPT="$2"; shift 2
[ -n "$GC_LOG" ] || exit 126
[ -f "$SCRIPT" ] || exit 126
GITDIR=$(dirname "$(command -v git)")
export PATH="__WBIN__:$GITDIR:/usr/bin:/bin"
exec env -i PATH="$PATH" HOME="$HOME" LANG="${LC_ALL:-en_US.UTF-8}" \\
  PYTHONDONTWRITEBYTECODE=1 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \\
  GIT_OPTIONAL_LOCKS=0 ATLAS_GC_LOG="$GC_LOG" ATLAS_GC_ROOT="__ROOT__" \\
  __PYTHON__ -I -B "$SCRIPT" "$@"
"""

_READONLY_GIT_TPL = """#!/bin/sh
set -u
GC_LOG=${ATLAS_GC_LOG:-}
argv_sha=$(printf '%s\\n' "$*" | shasum -a 256 | cut -d' ' -f1)
deny() {
  printf '{"argv_sha256":"%s","rc":126}\\n' "$argv_sha" >> "$GC_LOG" 2>/dev/null
  echo "atlas-readonly-git: denied: $*" >&2
  exit 126
}
a1=${1:-}; a2=${2:-}; a3=${3:-}; a4=${4:-}; a5=${5:-}; a6=${6:-}
allow_dash_c=0
[ "$a1|$a2|$a3" = "-c|core.quotePath=false|diff" ] && allow_dash_c=1
[ "$a1|$a2|$a3" = "-c|core.quotePath=false|ls-files" ] && allow_dash_c=1
allow_dash_C=0
if [ "$a1" = "-C" ] && [ -n "$a2" ] && [ -n "${ATLAS_GC_ROOT:-}" ]; then
  r_arg=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$a2" 2>/dev/null || echo "")
  r_root=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$ATLAS_GC_ROOT" 2>/dev/null || echo "")
  [ -n "$r_arg" ] && [ "$r_arg" = "$r_root" ] && allow_dash_C=1
fi
for a in "$@"; do
  case "$a" in
    --config-env*|--exec-path*|--git-dir*|--work-tree*|--output*|--ext-diff*|--textconv*|*";"*|*"|"*) deny "$@" ;;
    -c*) [ "$allow_dash_c" = "1" ] || deny "$@" ;;
    -C*) [ "$allow_dash_C" = "1" ] || deny "$@" ;;
  esac
done
case "$#|$a1|$a2|$a3|$a4|$a5|$a6" in
  '5|diff|--cached|--name-only|--diff-filter=ACDMRT|-z|') : ;;
  '5|diff|--cached|--name-only|-z|--no-renames|') : ;;
  '6|diff|--cached|--raw|-z|--no-renames|--abbrev=40'|'6|diff|--cached|--raw|-z|--no-renames|--abbrev=64') : ;;
  '6|diff|--cached|--quiet|HEAD|--|'* )
    case "$a6" in ""|-*) deny "$@" ;; esac ;;
  '6|diff|--cached|-U0|--no-renames|--|'* )
    case "$a6" in ""|-*) deny "$@" ;; esac ;;
  '2|diff|--name-only||||') : ;;
  '5|diff|--name-only|-z|'* )
    case "$a4" in ""|-*) deny "$@" ;; esac
    case "$a5" in ""|-*) deny "$@" ;; esac ;;
  '4|-c|core.quotePath=false|diff|--name-only||') : ;;
  '5|-c|core.quotePath=false|ls-files|--others|--exclude-standard|') : ;;
  '2|ls-files|-z||||') : ;;
  '4|ls-files|--error-unmatch|--|'*'||' )
    case "$a4" in ""|-*) deny "$@" ;; esac ;;
  '2|rev-parse|HEAD||||') : ;;
  '3|rev-parse|--verify|'*'|||' )
    case "$a3" in ""|-*) deny "$@" ;; esac ;;
  '2|rev-parse|--is-inside-work-tree||||') : ;;
  '2|rev-parse|--show-object-format||||') : ;;
  '2|rev-parse|--git-dir||||') : ;;
  '2|rev-parse|'*'^{tree}||||')
    case "$a2" in -*) deny "$@" ;; esac ;;
  '2|show|'*'||||' )
    case "$a2" in ""|-*) deny "$@" ;; esac ;;
  '6|-C|'*'|status|--porcelain|-z|--untracked-files=all' ) : ;;
  '4|-C|'*'|show|'*'||' )
    case "$a4" in ""|-*) deny "$@" ;; esac ;;
  '3|cat-file|-e|'*'|||' )
    case "$a3" in ""|-*) deny "$@" ;; esac ;;
  '5|diff-tree|--no-commit-id|--name-only|-r|'*'|' )
    case "$a5" in ""|-*) deny "$@" ;; esac ;;
  '5|ls-tree|-r|-z|--name-only|'*'|' )
    case "$a5" in ""|-*) deny "$@" ;; esac ;;
  '3|checkout-index|--all|--prefix='*'|||')
    pref="${a3#--prefix=}"
    python3 -c 'import os,sys; p=os.path.realpath(sys.argv[1]); ok=p.startswith("/tmp/") or p.startswith("/private/tmp/"); sys.exit(0 if ok else 1)' "$pref" || deny "$@"
    ;;
  *) deny "$@" ;;
esac
REAL_GIT="${ATLAS_GC_REAL_GIT:-/usr/bin/git}"
"$REAL_GIT" "$@"
rc=$?
printf '{"argv_sha256":"%s","rc":%d}\\n' "$argv_sha" "$rc" >> "$GC_LOG" 2>/dev/null
exit $rc
"""

_WRITE_GIT_TPL = """#!/bin/sh
set -u
GC_LOG=${ATLAS_GC_LOG:-}
argv_sha=$(printf '%s\\n' "$*" | shasum -a 256 | cut -d' ' -f1)
deny() {
  printf '{"argv_sha256":"%s","rc":126}\\n' "$argv_sha" >> "$GC_LOG" 2>/dev/null
  echo "atlas-write-git: denied: $*" >&2
  exit 126
}
a1=${1:-}; a2=${2:-}; a3=${3:-}
case "$#|$a1|$a2|$a3" in
  '1|write-tree||') : ;;
  '3|hash-object|-w|--stdin') : ;;
  '3|commit|-m|'*)
    case "$a3" in -*) deny "$@" ;; esac
    unset GIT_INDEX_FILE GIT_WORK_TREE GIT_DIR
    ;;
  '3|rev-parse|--verify|HEAD^') : ;;
  '3|rev-parse|--verify|HEAD^{tree}') : ;;
  *)
    exec "__RO_GIT__" "$@"
    ;;
esac
REAL_GIT="${ATLAS_GC_REAL_GIT:-/usr/bin/git}"
"$REAL_GIT" "$@"
rc=$?
printf '{"argv_sha256":"%s","rc":%d}\\n' "$argv_sha" "$rc" >> "$GC_LOG" 2>/dev/null
exit $rc
"""


def _freeze_p2_launchers(base: Path, repo_root: Path) -> tuple[Path, Path]:
    py = shutil.which("python3") or "/usr/bin/python3"
    ro_bin = base / "ro-bin"
    wr_bin = base / "wr-bin"
    ro_bin.mkdir(parents=True, exist_ok=True)
    wr_bin.mkdir(parents=True, exist_ok=True)

    ro_git = ro_bin / "git"
    ro_git.write_text(_READONLY_GIT_TPL, encoding="utf-8")
    wr_git = wr_bin / "git"
    wr_git.write_text(_WRITE_GIT_TPL.replace("__RO_GIT__", str(ro_git)), encoding="utf-8")

    ro_sh = base / "ro-launcher.sh"
    ro_sh.write_text(
        _READONLY_LAUNCHER_TPL.replace("__BIN__", str(ro_bin))
        .replace("__ROOT__", str(repo_root)).replace("__PYTHON__", py),
        encoding="utf-8",
    )
    wr_sh = base / "wr-launcher.sh"
    wr_sh.write_text(
        _WRITE_LAUNCHER_TPL.replace("__WBIN__", str(wr_bin))
        .replace("__ROOT__", str(repo_root)).replace("__PYTHON__", py),
        encoding="utf-8",
    )
    for f in (ro_git, wr_git, ro_sh, wr_sh):
        f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return ro_sh, wr_sh


def test_p2_cli_full_write_chain_post_commit_and_archive_cert_M262(tmp_path: Path) -> None:
    """M262（硬前置 5 独立测试：提交后指纹校验 + 归档后证书路径 + 守恒校验）。"""
    repo = tmp_path / "repo"
    unit = "TASK-P2-CLI"
    t_dir = _init_onboarded_repo(repo, unit, pre_existing=True)
    run_id = "gc-cli-p2-1"
    lock_token = "lease-" + "x" * 24

    head_before = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    lock_proc = subprocess.Popen(
        [sys.executable, "-B", str(repo / ".atlas" / "scripts" / "atlas_continue.py"),
         "lock-hold", "--root", str(repo), "--unit", unit, "--run-dir", run_id],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        lock_proc.stdin.write(json.dumps({"token": lock_token}) + "\n")
        lock_proc.stdin.flush()
        assert lock_proc.stdout.readline().strip() == "LOCKED"

        c_cli = str(repo / ".atlas" / "scripts" / "atlas_continue.py")
        prep = subprocess.run([sys.executable, "-B", c_cli, "prepare", "--root", str(repo), "--unit", unit, "--run-dir", run_id],
                              capture_output=True, text=True, check=True)
        prep_out = json.loads(prep.stdout)

        run = gc.run_dir(repo, run_id)
        obs = []
        steps = [
            (1, "pre", "atlas_workflow_finish_preflight", ["preflight", "--root", str(repo), "--unit", unit], False),
            (2, "def", "atlas_workflow_finish_deferred",
             ["write-deferred", "--root", str(repo), "--unit", unit, "--run-dir", run_id, "--action-index", "2", "--action-id", "def"], True),
            (3, "com", "atlas_workflow_finish_commit",
             ["write-commit", "--root", str(repo), "--unit", unit, "--run-dir", run_id, "--action-index", "3", "--action-id", "com"], True),
            (4, "arc", "atlas_workflow_finish_archive",
             ["write-archive", "--root", str(repo), "--unit", unit, "--run-dir", run_id, "--action-index", "4", "--action-id", "arc"], True),
        ]
        archived_dir = ""
        for idx, aid, tool, argv, mutating in steps:
            subprocess.run([sys.executable, "-B", c_cli, "verify", "--root", str(repo), "--unit", unit, "--run-dir", run_id],
                           capture_output=True, text=True, check=True)
            stdin_data = json.dumps({"lock_token": lock_token}) if mutating else None
            r = subprocess.run([sys.executable, "-B", c_cli] + argv, input=stdin_data, capture_output=True, text=True, check=True)
            body = json.loads(r.stdout.strip().splitlines()[-1])
            if tool == "atlas_workflow_finish_archive":
                archived_dir = body["archived_task_dir"]
            if mutating:
                subprocess.run(
                    [sys.executable, "-B", c_cli, "wal-commit", "--root", str(repo), "--unit", unit, "--run-dir", run_id,
                     "--action-index", str(idx), "--action-id", aid, "--tool", tool,
                     "--detail-json", json.dumps(body.get("wal_commit_payload") or {})],
                    capture_output=True, text=True, check=True,
                )
            res_obj = {"content": [{"type": "text", "text": "ok"}], "details": {"tool": tool, "exit_code": 0, "json_ok": True}, "isError": False}
            r_sha, f_sha = gc.write_raw_receipt(run, idx, res_obj, {"tool": tool})
            ev = run / "evidence" / f"callP_{idx}.json"
            ev.write_text(json.dumps({"result_hash_observed": r_sha}), encoding="utf-8")
            obs.append({
                "action_index": idx, "action_id": aid, "tool": tool, "child_tool_call_id": f"callP/{idx}",
                "guard_result": True, "guard_refs": [], "exit_code": 0, "json_ok": True, "ok": True,
                "cli_duration_ms": 1, "host_duration_ms": 2,
                "result_sha256": r_sha, "raw_receipt_sha256": f_sha,
                "raw_receipt_path": str(gc.raw_receipt_path(run, idx, r_sha[:16])),
            })

        # 归档后活跃卡消失、归档目录完整且 status == completed
        assert not t_dir.exists()
        assert archived_dir and (repo / archived_dir / "task.json").is_file()
        assert (repo / archived_dir / "deferred.md").is_file()
        assert (repo / archived_dir / "notes.txt").read_text(encoding="utf-8") == "extra card note\n"
        assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD^"], text=True).strip() == head_before

        # 归档后 verify 依然可通过（从 wal.archived_task_dir 解析 task/continuation）
        subprocess.run([sys.executable, "-B", c_cli, "verify", "--root", str(repo), "--unit", unit, "--run-dir", run_id],
                       capture_output=True, text=True, check=True)

        parent_res = {"content": [{"type": "text", "text": "ok"}], "details": {"actions_ok": True}, "isError": False}
        exp_hash = gc.canonical_result_hash(parent_res)
        rec_payload = run / "receipt-payload.json"
        rec_payload.write_text(json.dumps({
            "run_id": run_id, "unit": unit, "plan_sha256": gc.load_plan(repo, unit)["plan_sha256"],
            "status": "RECORDED", "terminal_reason": "chain_ok", "session_id": "s-cli",
            "parent_tool_call_id": "callP", "parent_tool_name": "atlas_continue",
            "expected_parent_result_sha256": exp_hash,
            "input_manifest_sha256": prep_out["input_manifest_sha256"],
            "actions": obs,
        }), encoding="utf-8")
        subprocess.run([sys.executable, "-B", c_cli, "record", "--root", str(repo), "--unit", unit, "--run-dir", run_id,
                        "--receipt-json", str(rec_payload)], check=True, capture_output=True, text=True)

        sess_file = tmp_path / "sess.jsonl"
        sess_file.write_text("\n".join([
            json.dumps({"type": "custom", "id": "seal-1", "customType": "atlas-continuation-seal",
                        "data": {"parentToolCallId": "callP", "expectedParentResultHash": exp_hash}}),
            json.dumps({"type": "message", "id": "msg-1",
                        "message": {"role": "toolResult", "toolCallId": "callP", **parent_res}}),
        ]) + "\n", encoding="utf-8")
        host_rec = run / "host-record.json"
        host_rec.write_text(json.dumps({"nestedCalls": {"complete": True, "calls": [{"name": s[2]} for s in steps]}}), encoding="utf-8")

        aud = subprocess.run([sys.executable, "-B", c_cli, "audit", "--root", str(repo), "--unit", unit, "--run-dir", run_id,
                              "--session", str(sess_file), "--host-record", str(host_rec)],
                             capture_output=True, text=True, check=True)
        aud_out = json.loads(aud.stdout.strip().splitlines()[-1])
        assert aud_out["verdict"] == "SUCCEEDED"
        cert = json.loads((run / "certificate.json").read_text(encoding="utf-8"))
        assert cert["archived_task_dir"] == archived_dir
        assert cert["plan_path_after_archive"] == f"{archived_dir}/continuation.json"
        assert cert["certificate_path"] == str(run / "certificate.json")
        assert cert.get("wal_manifest_sha256")
    finally:
        lock_proc.kill()
        lock_proc.wait(timeout=5)


def test_p2_cli_post_commit_hook_tamper_triggers_unknown_M264(tmp_path: Path) -> None:
    """M264（硬前置 4/5）：pre-commit hook 篡改非授权文件 ⇒ write-commit 转 UNKNOWN，audit 拒签 SUCCEEDED 证书。"""
    repo = tmp_path / "repo"
    unit = "TASK-HOOK"
    _init_onboarded_repo(repo, unit)
    # 注入 pre-commit hook 篡改非授权磁盘文件
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho tampered > unexpected_side.txt\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    run_id = "gc-hook-1"
    tok = "tok-" + "h" * 24
    lock_proc = subprocess.Popen(
        [sys.executable, "-B", str(repo / ".atlas" / "scripts" / "atlas_continue.py"),
         "lock-hold", "--root", str(repo), "--unit", unit, "--run-dir", run_id],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        lock_proc.stdin.write(json.dumps({"token": tok}) + "\n")
        lock_proc.stdin.flush()
        assert lock_proc.stdout.readline().strip() == "LOCKED"
        c_cli = str(repo / ".atlas" / "scripts" / "atlas_continue.py")
        subprocess.run([sys.executable, "-B", c_cli, "prepare", "--root", str(repo), "--unit", unit, "--run-dir", run_id], check=True)
        wc = subprocess.run(
            [sys.executable, "-B", c_cli, "write-commit", "--root", str(repo), "--unit", unit, "--run-dir", run_id,
             "--action-index", "3", "--action-id", "com"],
            input=json.dumps({"lock_token": tok}), capture_output=True, text=True,
        )
        assert wc.returncode == 2
        wc_json = json.loads(wc.stdout.strip().splitlines()[-1])
        assert wc_json["cause"] == "post_commit_unknown"

        run = gc.run_dir(repo, run_id)
        entries, trunc = gc.read_wal(run)
        assert trunc is False
        assert any(e.get("phase") == "UNKNOWN" for e in entries)

        aud = subprocess.run(
            [sys.executable, "-B", c_cli, "audit", "--root", str(repo), "--unit", unit, "--run-dir", run_id,
             "--session", str(tmp_path / "empty.jsonl"), "--host-record", str(tmp_path / "empty.json")],
            capture_output=True, text=True,
        )
        assert aud.returncode == 2
        assert json.loads(aud.stdout.strip().splitlines()[-1])["verdict"] == "UNKNOWN"
        assert not (run / "certificate.json").exists()
        assert (run / "unknown-diagnosis.json").is_file()
    finally:
        lock_proc.kill()
        lock_proc.wait(timeout=5)


# ────────────────────────────────────────────────────────────── 3. bun 假宿主 + 真扩展

_PI_P2_DRIVER = r"""
import { mkdirSync, writeFileSync, copyFileSync, existsSync, readFileSync } from "node:fs";
import { execSync, spawnSync } from "node:child_process";
import { join } from "node:path";
import ext from "__PI_TS__";

const MODE = "__MODE__"; // full-pass | reject-second-confirm | half-onboarded | hook-unknown
const ROOT = "__ROOT__";
const SESSION_FILE = "__SESSION__";
const WORKFLOW_CLI = "__WORKFLOW__";

const handlers: Record<string, any[]> = {};
const tools: any[] = [];
const commands: Record<string, any> = {};
const appended: any[] = [];
const notified: string[] = [];
const confirmTitles: string[] = [];

const pi: any = {
  registerTool: (t: any) => tools.push(t),
  registerCommand: (n: string, def: any) => { commands[n] = def.handler; },
  on: (ev: string, fn: any) => { (handlers[ev] ||= []).push(fn); },
  appendEntry: (customType: string, data: unknown) => appended.push({ customType, data }),
  exec: async () => ({ code: 0, stdout: "", stderr: "" }),
  getAllTools: () => tools, getActiveTools: () => [], setActiveTools: () => {},
};
ext(pi);

const branch: any[] = [];
let nested = 0;
let lockBusyProbeResult: { rc: number; stderr: string } | null = null;
let confirmIndex = 0;

const ctx: any = {
  cwd: ROOT,
  hasUI: true,
  ui: {
    confirm: async (title: string) => {
      confirmTitles.push(title);
      confirmIndex += 1;
      if (MODE === "reject-second-confirm" && confirmIndex === 2) return false;
      return true;
    },
    notify: (m: string) => notified.push(String(m)),
  },
  sessionManager: {
    getSessionId: () => "sess-p2",
    getSessionFile: () => SESSION_FILE,
    getBranch: () => branch,
  },
};

ctx.executeTool = async (name: string, args: any, opts?: any) => {
  nested += 1;
  const toolCallId = `callP/${nested}`;
  // 在首个写动作前测试共享写锁对抗：外部 CLI finish 必须被拒
  if (MODE === "full-pass" && name === "atlas_workflow_finish_commit" && !lockBusyProbeResult) {
    const probe = spawnSync("python3", ["-B", WORKFLOW_CLI, "--root", ROOT, "finish", "--unit", args.unit], { encoding: "utf8" });
    lockBusyProbeResult = { rc: probe.status ?? -1, stderr: probe.stderr ?? "" };
  }
  const tool = tools.find((t) => t.name === name);
  for (const h of handlers["tool_call"] ?? []) {
    const block = await h({ toolName: name, toolCallId, input: args, parentToolCallId: "callP" }, ctx);
    if (block?.block) return { toolCall: { id: toolCallId, name, arguments: args }, result: { content: [{ type: "text", text: "BLOCKED" }] }, isError: true };
  }
  const result = await tool.execute(toolCallId, args, opts?.signal, null, ctx);
  for (const h of handlers["tool_result"] ?? []) {
    await h({ toolName: name, toolCallId, input: args, parentToolCallId: "callP", content: result.content, details: result.details, isError: result.isError }, ctx);
  }
  for (const h of handlers["tool_execution_end"] ?? []) {
    h({ toolCallId, toolName: name, parentToolCallId: "callP", durationMs: 2, isError: result.isError });
  }
  return { toolCall: { id: toolCallId, name, arguments: args }, result, isError: result.isError, durationMs: 2 };
};

const out: Record<string, any> = { mode: MODE };
const unit = "TASK-BUN-P2";

if (MODE === "half-onboarded") {
  await commands.atlas(`approve-continuation ${unit}`, ctx);
  out.marker_exists = existsSync(join(ROOT, ".atlas", "runs", "continuations", "isolated", `${unit}.json`));
  out.notifies = notified;
  console.log("P2DRIVER " + JSON.stringify(out));
  process.exit(0);
}

if (MODE === "reject-second-confirm") {
  await commands.atlas(`approve-continuation ${unit}`, ctx);
  out.confirm_count = confirmTitles.length;
  out.marker_exists = existsSync(join(ROOT, ".atlas", "runs", "continuations", "isolated", `${unit}.json`));
  console.log("P2DRIVER " + JSON.stringify(out));
  process.exit(0);
}

// 1) 两段确认 approve
await commands.atlas(`approve-continuation ${unit}`, ctx);
out.confirm_count = confirmTitles.length;
const markerPath = join(ROOT, ".atlas", "runs", "continuations", "isolated", `${unit}.json`);
if (!existsSync(markerPath)) {
  console.error("APPROVE_DID_NOT_ARM notifies=", JSON.stringify(notified));
}
const markerArmed = JSON.parse(readFileSync(markerPath, "utf-8"));
out.armed_state = markerArmed.state;
out.armed_run_id = markerArmed.run_id;

// 2) 直调 / codemode 直调 P2 子工具必须被 tool_call 与 execute 双重拦截
let directChildBlock: any = null;
for (const h of handlers["tool_call"] ?? []) {
  directChildBlock = await h({ toolName: "atlas_workflow_finish_commit", toolCallId: "dc-1", input: { unit }, parentToolCallId: undefined }, ctx);
}
out.direct_child_blocked = Boolean(directChildBlock?.block);
const commitChild = tools.find((t) => t.name === "atlas_workflow_finish_commit");
const directExec = await commitChild.execute("dc-exec", { unit }, undefined, null, ctx);
out.direct_child_exec_denied = directExec.isError === true;

// 3) 执行父工具 atlas_continue
const parentTool = tools.find((t) => t.name === "atlas_continue");
const ret = await parentTool.execute("callP", { unit }, undefined, null, ctx);
out.parent_is_error = ret.isError === true;
out.parent_actions_ok = ret.details?.actions_ok === true;
out.lock_busy_probe = lockBusyProbeResult;

const runId = appended[0]?.data?.runId ?? markerArmed.run_id;
branch.push({ type: "custom", customType: appended[0]?.customType, data: appended[0]?.data, id: "e-seal", parentId: "e0" });
const nestedCalls = {
  calls: (ret.details?.observations ?? []).map((o: any, i: number) => ({
    id: o.child_tool_call_id ?? `callP/${i + 1}`, name: o.tool, status: o.ok ? "ok" : "error", durationMs: 2,
  })),
  complete: true,
};
branch.push({
  type: "message", id: "e1", parentId: "e-seal",
  message: { role: "toolResult", toolCallId: "callP", toolName: "atlas_continue", content: ret.content, details: ret.details, isError: ret.isError, nestedCalls },
});
writeFileSync(SESSION_FILE, branch.map((b) => JSON.stringify(b)).join("\n") + "\n");

for (const h of handlers["agent_settled"] ?? []) await h({}, ctx);

const finalMarker = JSON.parse(readFileSync(join(ROOT, ".atlas", "runs", "continuations", "isolated", `${unit}.json`), "utf-8"));
out.final_state = finalMarker.state;
out.cert_exists = existsSync(join(ROOT, ".atlas", "runs", "continuations", runId, "certificate.json"));
out.wal_text = existsSync(join(ROOT, ".atlas", "runs", "continuations", runId, "wal.jsonl"))
  ? readFileSync(join(ROOT, ".atlas", "runs", "continuations", runId, "wal.jsonl"), "utf-8") : "";

if (MODE === "hook-unknown") {
  // revoke 严禁洗白 UNKNOWN
  await commands.atlas(`revoke-continuation ${unit}`, ctx);
  out.state_after_revoke = JSON.parse(readFileSync(join(ROOT, ".atlas", "runs", "continuations", "isolated", `${unit}.json`), "utf-8")).state;
  // recover 只做只读诊断，人类确认后写 CLOSED_FAILED 终态，严禁重放
  await commands.atlas(`recover-continuation ${unit}`, ctx);
  const recMarker = JSON.parse(readFileSync(join(ROOT, ".atlas", "runs", "continuations", "isolated", `${unit}.json`), "utf-8"));
  out.state_after_recover = recMarker.state;
  out.resolved_from_unknown = recMarker.resolved_from_unknown === true;
}

// 结束后锁已释放，新 CLI 写者应不再被锁住（仅 check write.lock 未占用；-B 防测针污染 __pycache__）
out.lock_released_probe = spawnSync("python3", ["-B", "-c", `
import sys; sys.path.insert(0, '${ROOT}/.atlas')
from _support.guarded_continuation import WriteLock
with WriteLock('${ROOT}', holder='probe-after'):
    pass
print('UNLOCKED')
`], { encoding: "utf8" }).stdout.trim();

console.log("P2DRIVER " + JSON.stringify(out));
"""


def test_p2_bun_fake_host_write_chain_and_security(tmp_path: Path) -> None:
    """层 3（bun 可用时）：真扩展 P2 写链全环、M3 开户门、二段拒签、锁对抗、直调拦截、UNKNOWN 与 recover 零重放。"""
    bun = shutil.which("bun")
    if not bun:
        pytest.skip("无 bun ⇒ pi 扩展 P2 执行级跳过")
    if not shutil.which("shasum"):
        pytest.skip("无 shasum ⇒ git 包装器不可冻结，跳过")

    unit = "TASK-BUN-P2"
    scenarios = ("full-pass", "reject-second-confirm", "half-onboarded", "hook-unknown")
    for idx, mode in enumerate(scenarios):
        case_dir = tmp_path / f"case-{idx}-{mode}"
        repo = case_dir / "repo"
        _init_onboarded_repo(repo, unit, onboarded=(mode != "half-onboarded"))
        if mode == "hook-unknown":
            hook = repo / ".git" / "hooks" / "pre-commit"
            hook.write_text("#!/bin/sh\necho hook_tamper > rogue_hook_file.txt\n", encoding="utf-8")
            hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        ro_sh, wr_sh = _freeze_p2_launchers(case_dir / "frozen", repo)
        env = dict(os.environ)
        env["ATLAS_GC_LAUNCHER"] = str(ro_sh)
        env["ATLAS_GC_WRITE_LAUNCHER"] = str(wr_sh)

        sess = case_dir / "session.jsonl"
        drv = case_dir / "driver.ts"
        drv.write_text(
            _PI_P2_DRIVER.replace("__PI_TS__", (PKG_ROOT / "extensions" / "pi.ts").as_posix())
            .replace("__MODE__", mode)
            .replace("__ROOT__", str(repo))
            .replace("__SESSION__", str(sess))
            .replace("__WORKFLOW__", str(WORKFLOW_CLI)),
            encoding="utf-8",
        )
        run = subprocess.run([bun, "run", str(drv)], capture_output=True, text=True, timeout=180, env=env)
        assert run.returncode == 0, (mode, run.stdout, run.stderr)
        line = [l for l in run.stdout.splitlines() if l.startswith("P2DRIVER ")][-1]
        data = json.loads(line.split(" ", 1)[1])

        # 验证 PYTHONDONTWRITEBYTECODE=1 生效：被跑过的 _support 下零 __pycache__
        assert not list((repo / ".atlas" / "_support").rglob("*.pyc")), "净化启动器不得产出 .pyc"

        if mode == "half-onboarded":
            assert data["marker_exists"] is False
            assert any("开户" in n for n in data["notifies"]), data
        elif mode == "reject-second-confirm":
            assert data["confirm_count"] == 2
            assert data["marker_exists"] is False, "二段拒签必须零落盘"
            assert not (repo / ".atlas" / "runs" / "continuations").exists()
        elif mode == "full-pass":
            assert data["confirm_count"] == 2
            assert data["armed_state"] == "ARMED"
            assert data["direct_child_blocked"] is True
            assert data["direct_child_exec_denied"] is True
            assert data["parent_is_error"] is False and data["parent_actions_ok"] is True
            assert data["lock_busy_probe"]["rc"] == 2, data["lock_busy_probe"]
            assert data["final_state"] == "SUCCEEDED", data
            assert data["cert_exists"] is True, data
            assert data["lock_released_probe"] == "UNLOCKED", data
            wal_lines = [json.loads(l) for l in data["wal_text"].splitlines() if l.strip()]
            assert [e["phase"] for e in wal_lines] == ["INTENT", "COMMITTED", "INTENT", "COMMITTED", "INTENT", "COMMITTED"]
        elif mode == "hook-unknown":
            assert data["parent_is_error"] is True
            assert data["final_state"] == "UNKNOWN", "UNKNOWN 不得被 RECORDED/AUDIT_FAILED 覆写"
            assert data["cert_exists"] is False
            assert data["state_after_revoke"] == "UNKNOWN", "revoke 严禁洗白 UNKNOWN"
            assert data["state_after_recover"] == "CLOSED_FAILED"
            assert data["resolved_from_unknown"] is True
            assert data["lock_released_probe"] == "UNLOCKED", data
