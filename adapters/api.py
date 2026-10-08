#!/usr/bin/env python3
"""atlas 事实抽取适配器 —— api（D 类：接口清单）。

契约见 `.atlas/shared/stack-profile.md` §3（调用方式 / 输出 JSON / items 字段）
与 §3.5（D 类条件形态）。本文件是**框架知识的合法落点**。

两种形态（按 app 自动判定，不得混写）：
- **有机器可读描述**（自带描述文件，或框架运行时自动生成 schema）→ 只给
  `spec_entry`（真相源入口）+ `source_files`，**不产 items**；
- **无描述** → 从源码抽取端点（`@action` 类 RPC、装饰器路由）。

用法：
    python3 api.py --root <代码根> [--app <name>] --out <json 路径>
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import (  # noqa: E402
    die, iter_files, load_apps, resolve_app, write_json,
)

ADAPTER = "api"
VERSION = "0.1.0"

DESCRIPTOR_FILES = {"openapi.json", "openapi.yaml", "openapi.yml", "swagger.json", "swagger.yaml"}
# 运行时自动生成 schema 的框架信号（框架知识仅允许在适配器出现）
SCHEMA_MARKERS = (re.compile(r"\bAPIRouter\s*\("), re.compile(r"\bFastAPI\s*\("))
DECO_RE = re.compile(r"@(\w+)\.(get|post|put|delete|patch|options|head)\(\s*['\"]([^'\"]*)['\"]")
PREFIX_RE = re.compile(r"(\w+)\s*=\s*\w+\([^)]*prefix\s*=\s*['\"]([^'\"]+)['\"]")
JS_RE = re.compile(r"\b(?:app|router)\.(get|post|put|delete|patch)\(\s*['\"]([^'\"]+)['\"]")
ACTION_DEF_RE = re.compile(r"\b(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(")


def join_path(prefix: str, path: str) -> str:
    if prefix:
        p = prefix.rstrip("/") + "/" + path.lstrip("/")
    else:
        p = path
    if not p.startswith("/"):
        p = "/" + p
    return p


def extract_actions(root: Path, f: Path) -> list[dict]:
    """`@action` 之后定义的函数 → POST /api/__actions/{page}/{name}。"""
    rel = f.relative_to(root).as_posix()
    if f.parent.name != "pages":
        return []
    page = "/".join(f.relative_to(f.parent).with_suffix("").parts)
    lines = f.read_text(encoding="utf-8").splitlines()
    items: list[dict] = []
    for i, ln in enumerate(lines):
        if not re.match(r"^\s*@action\b", ln):
            continue
        for j in range(i + 1, min(i + 4, len(lines))):
            m = ACTION_DEF_RE.search(lines[j])
            if m:
                items.append({
                    "method": "POST",
                    "path": f"/api/__actions/{page}/{m.group(1)}",
                    "summary": None,
                    "source_module": rel,
                    "source_file": f"{rel}:{i + 1}",
                })
                break
    return items


def extract_py_routes(root: Path, f: Path) -> list[dict]:
    rel = f.relative_to(root).as_posix()
    text = f.read_text(encoding="utf-8")
    prefixes = {m.group(1): m.group(2) for m in PREFIX_RE.finditer(text)}
    items: list[dict] = []
    for i, ln in enumerate(text.splitlines(), 1):
        if ln.lstrip().startswith("#"):
            continue
        m = DECO_RE.search(ln)
        if not m:
            continue
        obj, method, path = m.group(1), m.group(2).upper(), m.group(3)
        items.append({
            "method": method,
            "path": join_path(prefixes.get(obj, ""), path),
            "summary": None,
            "source_module": rel,
            "source_file": f"{rel}:{i}",
        })
    return items


def extract_js_routes(root: Path, f: Path) -> list[dict]:
    rel = f.relative_to(root).as_posix()
    items: list[dict] = []
    for i, raw in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        ln = raw.split("//", 1)[0]
        if ln.lstrip().startswith(("*", "/*")):
            continue
        for m in JS_RE.finditer(ln):
            items.append({
                "method": m.group(1).upper(),
                "path": join_path("", m.group(2)),
                "summary": None,
                "source_module": rel,
                "source_file": f"{rel}:{i}",
            })
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True)
    ap.add_argument("--app", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        die(ADAPTER, f"--root 不是目录: {root}")
    apps = load_apps(root)
    app_path = resolve_app(root, apps, args.app, ADAPTER)

    desc_files: list[str] = []
    schema_sources: list[str] = []
    items: list[dict] = []
    for f in iter_files(root, (".py", ".pyxl", ".js", ".ts"), app_path):
        rel = f.relative_to(root).as_posix()
        if f.name in DESCRIPTOR_FILES:
            desc_files.append(rel)
            continue
        if f.suffix == ".py":
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            if any(mk.search(text) for mk in SCHEMA_MARKERS):
                schema_sources.append(rel)
            items.extend(extract_py_routes(root, f))
        elif f.suffix == ".pyxl":
            items.extend(extract_actions(root, f))
        else:
            items.extend(extract_js_routes(root, f))

    if desc_files or schema_sources:
        payload = {
            "category": "api",
            "spec_entry": desc_files[0] if desc_files else "/openapi.json",
            "source_files": sorted(set(desc_files + schema_sources)),
            "adapter_version": VERSION,
        }
    else:
        items.sort(key=lambda i: (i["source_file"], i["path"], i["method"]))
        payload = {
            "category": "api",
            "items": items,
            "source_files": sorted({i["source_module"] for i in items}),
            "adapter_version": VERSION,
        }
    write_json(ADAPTER, args.out, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
