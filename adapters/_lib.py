#!/usr/bin/env python3
"""适配器共用工具。**不是适配器本体**，不会被 `stack-profile.adapters` 解析。

提供：确定性文件遍历（剪依赖/构建目录）、`stack-profile.yaml` 的 apps 解析、
统一报错与 JSON 落盘。框架识别仍留在各适配器内部。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", "site-packages", "dist", "build",
    ".next", ".turbo", ".mypy_cache", ".pytest_cache", ".pyxle-build",
    "coverage", ".coverage", ".venv", "venv",
}


def die(adapter: str, msg: str) -> None:
    print(f"ERROR[{adapter}]: {msg}", file=sys.stderr)
    sys.exit(1)


def iter_files(root: Path, suffixes: tuple[str, ...], app_path: str | None = None):
    """遍历 root（或某 app）下指定后缀的文件，剪掉依赖/构建/VCS 目录，顺序确定。"""
    base = root / app_path if app_path else root
    if not base.exists():
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in IGNORE_DIRS and not d.startswith(".venv") and not d.endswith(".venv")
        )
        for name in sorted(filenames):
            if name.endswith(suffixes):
                yield Path(dirpath) / name


def load_apps(root: Path) -> list[dict]:
    """读 product/stack-profile.yaml 的 apps（name / path / role）。"""
    p = root / "product" / "stack-profile.yaml"
    if not p.is_file():
        return []
    apps: list[dict] = []
    cur: dict | None = None
    in_apps = False
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("apps:"):
            in_apps = True
            continue
        if in_apps and line[:1] not in (" ", "\t"):
            in_apps = False
            cur = None
            continue
        if not in_apps:
            continue
        m = re.match(r"^\s*-\s*name:\s*(.+?)\s*$", line)
        if m:
            cur = {"name": m.group(1).strip().strip("'\"")}
            apps.append(cur)
            continue
        m = re.match(r"^\s+(path|role):\s*(.+?)\s*$", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2).strip().strip("'\"")
    return apps


def resolve_app(root: Path, apps: list[dict], name: str | None, adapter: str) -> str | None:
    """--app 名 → apps[].path；返回单 app 遍历根，None 表示整项目。"""
    if not name:
        return None
    hit = next((a for a in apps if a.get("name") == name), None)
    if hit is None:
        die(adapter, f"--app {name} 不在 stack-profile.apps 中")
    return hit.get("path") or hit.get("name")


def write_json(adapter: str, out: str, payload: dict) -> None:
    dst = Path(out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    n = len(payload.get("items", []))
    print(f"[{adapter}] {n} 项 / {len(payload.get('source_files', []))} 个源文件 -> {dst}")
