#!/usr/bin/env python3
"""嵌套包仓（`atlas/` 内嵌 `.git`）的 gitlink 守卫 —— 红线 1 的机器化。

背景（`ATLAS-UPSTREAM.md` 红线 1 / `3508 §207` 覆盖事故族）：源包工作树 `atlas/` 内含
独立 `.git`（发布线）；父仓正常追踪其下文件。误执行 `git add atlas/` ⇒ 父仓 index 把整棵
树转成一条 gitlink（mode `160000`）⇒ 百份文件跟踪面被指针替换。
「靠人记住红线」正是 atlas 最反对的形态（`§B92` 族）⇒ 升格为出厂套件的机器门。

- 前置不满足（无 git / 无嵌套 `atlas/.git` / 父仓未跟踪 `atlas/`）⇒ `SKIP` 带原因，不是通过。
- 检查面 = `git ls-files -s`（**index**）：`git add` 后未提交的 gitlink 就已可见（不漏半拍）。
- 本文件自带**沙箱举证**：注入式 gitlink ⇒ 必红；松散跟踪 + 后出现的嵌套仓 ⇒ 不误报（正反控）。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
PARENT = PKG_ROOT.parent
GITLINK_MODE = "160000"


def check_gitlink(parent_root: Path) -> tuple[str, str]:
    """返回（PASS | FAIL | SKIP, 说明）。语义见模块头注。"""
    if not shutil.which("git"):
        return "SKIP", "无 git 可执行文件"
    nested = parent_root / "atlas"
    if not (nested / ".git").exists():
        return "SKIP", f"无嵌套源包仓（{nested}/.git 不存在）——非双树布局"
    try:
        top = subprocess.run(["git", "-C", str(parent_root), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "SKIP", f"git 不可用：{type(exc).__name__}"
    if top.returncode != 0:
        return "SKIP", "父目录不在 git 工作树内"
    toplevel = Path(top.stdout.strip())
    try:
        rel = nested.relative_to(toplevel).as_posix()
    except ValueError:
        return "SKIP", "嵌套仓不在父仓工作树内"
    try:
        ls = subprocess.run(["git", "-C", str(toplevel), "ls-files", "-s", "--", rel],
                            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "FAIL", f"git ls-files 调用失败：{type(exc).__name__}"
    if ls.returncode != 0:
        return "FAIL", f"git ls-files 失败：{(ls.stderr or '').strip()[:120]}"
    lines = [l for l in ls.stdout.splitlines() if l.strip()]
    if not lines:
        return "SKIP", f"父仓未跟踪 {rel}/（无 gitlink 风险面）"
    links = [l.split("\t", 1)[-1] for l in lines if l.startswith(GITLINK_MODE)]
    if links:
        return "FAIL", (
            f"父仓 index 出现 gitlink（mode {GITLINK_MODE}）：{links[:3]} —— `git add {rel}/` 把嵌套仓"
            f"转成了指针；补救：`git rm --cached {rel} && git reset -- {rel}`（若已提交需回退提交；"
            "红线见 ATLAS-UPSTREAM.md 红线 1）")
    return "PASS", f"父仓跟踪 {rel}/ {len(lines)} 条目，无 gitlink"


def test_real_tree_has_no_gitlink() -> None:
    """真实双树现场：父仓 index 不得有 gitlink（前置不满足即 SKIP 带原因）。"""
    status, detail = check_gitlink(PARENT)
    if status == "SKIP":
        pytest.skip(detail)
    assert status == "PASS", detail


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=60)


def test_guard_bites_on_staged_gitlink(tmp_path: Path) -> None:
    """沙箱反控：父仓 + 先存在的嵌套 `atlas/.git`，`git add atlas` ⇒ 守卫必红（M-咬）。"""
    if not shutil.which("git"):
        pytest.skip("无 git 可执行文件")
    parent, nested = tmp_path / "proj", tmp_path / "proj" / "atlas"
    nested.mkdir(parents=True)
    (nested / "f.txt").write_text("x", encoding="utf-8")
    assert _git(nested, "init", "-q").returncode == 0
    assert _git(nested, "add", "f.txt").returncode == 0
    assert _git(nested, "commit", "-q", "-m", "init").returncode == 0
    assert _git(parent, "init", "-q").returncode == 0
    assert _git(parent, "add", "atlas").returncode == 0  # gitlink 入 index（未提交也已可见）
    status, detail = check_gitlink(parent)
    assert status == "FAIL", f"注入 gitlink 后守卫未咬：{status} / {detail}"
    assert GITLINK_MODE in detail


def test_guard_passes_on_loose_tracking(tmp_path: Path) -> None:
    """沙箱正控：先松散跟踪文件、后出现嵌套仓 ⇒ 不误报（105 文件历史跟踪的真实现场形态）。"""
    if not shutil.which("git"):
        pytest.skip("无 git 可执行文件")
    parent, nested = tmp_path / "proj2", tmp_path / "proj2" / "atlas"
    nested.mkdir(parents=True)
    (nested / "f.txt").write_text("x", encoding="utf-8")
    assert _git(parent, "init", "-q").returncode == 0
    assert _git(parent, "add", "atlas/f.txt").returncode == 0
    assert _git(nested, "init", "-q").returncode == 0  # 嵌套仓后出现（.git 落地）
    status, detail = check_gitlink(parent)
    assert status == "PASS", f"松散跟踪被误报：{status} / {detail}"


def test_guard_skips_without_nested_repo(tmp_path: Path) -> None:
    """前置缺（无嵌套仓）⇒ SKIP 带原因（不是通过）。"""
    parent = tmp_path / "bare"
    (parent / "atlas").mkdir(parents=True)
    status, detail = check_gitlink(parent)
    assert status == "SKIP" and "嵌套" in detail
