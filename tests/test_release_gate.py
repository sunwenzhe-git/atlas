#!/usr/bin/env python3
"""RFC §6 B / D-40（v19/重要 3、v20/重要 5）：发版门。

`PRD_SCHEMA_2_FROM` 是 `prd_schema_too_low` 的锚点常量，必须等于 0.4.0 发布 tag
的 UTC 日期。skip 语义写死：

- 无 `GITHUB_REF_TYPE` / 不是 `tag` ⇒ skip（未在发布 tag 上运行）；
- `GITHUB_REF_NAME` 不是 `v0.4.0*` ⇒ skip（不是 0.4.0 发版）；
- `PRD_SCHEMA_2_FROM is None` ⇒ skip（常量未武装）；
- 仅 `tag` 且名字匹配 `v0.4.0*` 时断言：常量非 None 且等于 tag 的 UTC 日期。

另含发版提交白名单门（2026-11-21 复盘 R5，`scripts/release.py
check_release_commit_scope`）：`chore(release)` 提交只准含版本落点——治 G1
（`787dd42` 经「手工预制发版提交」旁路夹带 install.py/golden/specs 20 文件，
10-25 守卫只查工作树、查不到已提交内容）。
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


def test_seal_upstream_bind_constant_matches_first_d_tag() -> None:
    """D-48：`SEAL_UPSTREAM_BIND_FROM` == D 批首个 tag 的 UTC 日期。

    与 D-40 同构：非 tag 环境 / 常量未武装 ⇒ skip；武装后只认「引入该常量值
    的提交被最早一个 tag 包含」的日期——后期 tag 不会误判。
    """
    if os.environ.get("GITHUB_REF_TYPE") != "tag":
        pytest.skip("未在发布 tag 上运行（GITHUB_REF_TYPE != tag）")
    if core.SEAL_UPSTREAM_BIND_FROM is None:
        pytest.skip("SEAL_UPSTREAM_BIND_FROM 未武装（D 批发版时必须填首个 tag 的 UTC 日期）")
    log = subprocess.run(
        ["git", "-C", str(PKG_ROOT), "log", "--format=%H", "-S",
         'SEAL_UPSTREAM_BIND_FROM: str | None = "', "--", "_support/solution.py"],
        capture_output=True, text=True)
    commits = [c for c in log.stdout.split() if c] if log.returncode == 0 else []
    if not commits:
        pytest.skip("找不到写入常量值的提交（浅克隆？）")
    introducing = commits[-1]  # newest-first ⇒ 最后一条是最早写入该值的提交
    tags = subprocess.run(
        ["git", "-C", str(PKG_ROOT), "tag", "--contains", introducing,
         "--sort=creatordate"],
        capture_output=True, text=True)
    names = [t for t in tags.stdout.split() if t] if tags.returncode == 0 else []
    if not names:
        pytest.skip(f"引入常量的提交 {introducing[:12]} 尚未被任何 tag 包含")
    first = names[0]
    expected = tag_utc_date(first)
    assert core.SEAL_UPSTREAM_BIND_FROM == expected, (
        f"SEAL_UPSTREAM_BIND_FROM={core.SEAL_UPSTREAM_BIND_FROM!r} 与 D 批首个 tag "
        f"{first} 的 UTC 日期 {expected!r} 不一致")


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


# ── 发版提交白名单（复盘 R5；判据与反例见模块 docstring）───────────────────────

def _load_release():
    path = PKG_ROOT / "scripts" / "release.py"
    spec = importlib.util.spec_from_file_location("_atlas_release_scope", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


release = _load_release()


def _git(tmp: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(tmp), *args],
                       capture_output=True, text=True, check=True)
    return r.stdout


def _mk_repo(tmp: Path) -> Path:
    """最小 git 仓：已含 package.json / README 两落点的初始提交。"""
    subprocess.run(["git", "init", "-q", str(tmp)], check=True)
    _git(tmp, "config", "user.email", "t@example.com")
    _git(tmp, "config", "user.name", "t")
    (tmp / "package.json").write_text('{"version": "0.0.1"}', encoding="utf-8")
    (tmp / "README.md").write_text("x", encoding="utf-8")
    _git(tmp, "add", "-A")
    _git(tmp, "commit", "-q", "-m", "init")
    return tmp


def test_release_commit_with_targets_only_passes(tmp_path) -> None:
    """发版 chore 只含版本落点 ⇒ 放行（不抛）。"""
    _mk_repo(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text("# 更新日志\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "chore(release): v0.0.2")
    release.check_release_commit_scope(tmp_path)


def test_release_commit_carrying_code_must_fail(tmp_path) -> None:
    """反例（G1 形态）：发版 chore 夹带代码文件 ⇒ 必红；拆出后复绿。

    `787dd42` 实证：预制发版提交 + 复用发版旁路绕过了 10-25 工作树守卫——
    本门查的是提交内容本身，工作树是否干净无关。
    """
    _mk_repo(tmp_path)
    (tmp_path / "install.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "chore(release): v0.0.2")
    with pytest.raises(RuntimeError, match="夹带"):
        release.check_release_commit_scope(tmp_path)
    # 拆成独立提交后必须复绿
    (tmp_path / "install.py").write_text("", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "feat: 拆出的独立提交")
    release.check_release_commit_scope(tmp_path)


def test_non_release_head_is_out_of_scope(tmp_path) -> None:
    """复用普通功能提交发版是既有路径，不在本判据内（不抛）。"""
    _mk_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "feat: x")
    release.check_release_commit_scope(tmp_path)
