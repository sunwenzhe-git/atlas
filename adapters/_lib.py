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

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.layout import load_layout  # noqa: E402

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
    """读资产根/stack-profile.yaml 的 apps（name / path / role）。"""
    p = load_layout(root).stack_profile
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


def strip_js_comments(text: str) -> str:
    """去掉 JS/TS 的 `//` 与 `/* */` 注释，**保留换行**（行号据此稳定）。

    必须懂引号：`'https://x'` 里的 `//` 不是注释——朴素 `split("//")` 会把 URL 砍断。
    注释同样是**源码事实的敌人**：被注掉的条目/字段若仍被当活事实收走，产出的就是假事实
    （2026-10-15 实测：被 `//` 注掉的路由条目仍被收进清单）。
    """
    out: list[str] = []
    i, n = 0, len(text)
    quote = ""
    while i < n:
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            i = text.find("\n", i)
            if i < 0:
                break
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.extend(c for c in text[i:end] if c == "\n")
            i = end
            continue
        out.append(ch)
        i += 1
    return "".join(out)
