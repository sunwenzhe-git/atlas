#!/usr/bin/env python3
"""运行期输出目录（`.atlas-run` 替代）：把一次 run 的产物放到**仓库外**。

为什么：控制台与 Playwright 曾把 `results.json` / `.last-run.json` / trace 写进
`<e2e>/scripts/.atlas-run`；在某些受限写上下文里即使目录属主正常也会 EACCES，且同仓并发 run
会互相清空产物（Playwright 启动即清空 outputDir）。结构修复 = 每次 run 独立目录、仓库外、唯一。

布局（可用 `ATLAS_RUN_ROOT` 覆盖根）：

    <cache>/atlas-e2e/<repo-slug>/runs/<run-id>/
        results.json / .last-run.json / *.png / *.webm / *.trace
    <cache>/atlas-e2e/<repo-slug>/evidence/<archive-id>/...

`<cache>` 取值顺序：`ATLAS_RUN_ROOT` → macOS `~/Library/Caches` → `$XDG_CACHE_HOME` →
`~/.cache` → 系统临时目录。仓库内旧 `.atlas-run` **只读提示，不删除**。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

DEFAULT_KEEP = 10
RUN_DIRNAME = "runs"
EVIDENCE_DIRNAME = "evidence"
LEGACY_RUN_DIRNAME = ".atlas-run"


def _cache_base() -> Path:
    override = os.environ.get("ATLAS_RUN_ROOT")
    if override:
        return Path(override).expanduser()
    home = Path.home()
    if sys_platform() == "darwin":
        return home / "Library" / "Caches"
    xdg = os.environ.get("XDG_CACHE_HOME")
    return Path(xdg).expanduser() if xdg else home / ".cache"


def sys_platform() -> str:
    import sys
    return sys.platform


def repo_slug(root: Path | str) -> str:
    """稳定 slug：目录名（安全字符）+ 绝对路径短哈希，避免同名仓互撞。"""
    root = Path(root).resolve()
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip(".-") or "repo"
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:8]
    return f"{name}-{digest}"


def workspace_root(root: Path | str) -> Path:
    """`<cache>/atlas-e2e/<repo-slug>`；不可写 ⇒ 回落系统临时目录（仍在本仓之外）。"""
    root = Path(root).resolve()
    candidate = _cache_base() / "atlas-e2e" / repo_slug(root)
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return candidate
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "atlas-e2e" / repo_slug(root)
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def new_run_dir(root: Path | str) -> Path:
    """新建唯一 run 目录（时间戳 + pid + 随机后缀）；两次调用必不同。"""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    suffix = f"{os.getpid()}-{os.urandom(2).hex()}"
    run_dir = workspace_root(root) / RUN_DIRNAME / f"{stamp}-{suffix}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def evidence_root(root: Path | str) -> Path:
    path = workspace_root(root) / EVIDENCE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_run_dir(root: Path | str) -> Path:
    """旧仓内运行目录（只用于提示，不清理）。"""
    import sys
    sup = Path(__file__).resolve().parent
    if str(sup.parent) not in sys.path:
        sys.path.insert(0, str(sup.parent))
    from _support.layout import load_layout
    return load_layout(Path(root)).e2e_scripts_dir / LEGACY_RUN_DIRNAME


def latest_run_dir(root: Path | str, exclude: Path | None = None) -> Path | None:
    runs = workspace_root(root) / RUN_DIRNAME
    if not runs.is_dir():
        return None
    for path in sorted((p for p in runs.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        if exclude is None or path.resolve() != Path(exclude).resolve():
            return path
    return None


def prune(root: Path | str, keep: int = DEFAULT_KEEP) -> list[Path]:
    """只保留最近 `keep` 个 run 目录；仅在本模块管理的 `<cache>/atlas-e2e/<slug>` 下动作。"""
    try:
        runs = workspace_root(root) / RUN_DIRNAME
        if not runs.is_dir():
            return []
        dirs = sorted((p for p in runs.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
        removed: list[Path] = []
        for old in dirs[max(1, keep):]:
            shutil.rmtree(old, ignore_errors=True)
            removed.append(old)
        return removed
    except OSError:
        return []
