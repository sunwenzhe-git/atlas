#!/usr/bin/env python3
"""atlas 事实抽取适配器 —— api（D 类：接口清单）。

契约见 `.atlas/shared/stack-profile.md` §3（调用方式 / 输出 JSON / items 字段）
与 §3.5（D 类条件形态）。本文件是**框架知识的合法落点**。

两种形态（按 app 自动判定，不得混写）：
- **有机器可读描述**（自带描述文件，或框架运行时自动生成 schema）→ 只给
  `spec_entry`（真相源入口）+ `source_files`，**不产 items**；
- **无描述** → 从源码抽取端点（`@action` 类 RPC、装饰器路由、**TS 的点分方法名调用**）。

**TS 的 RPC / action 形态**（2026-10-15 补）：首参是**点分方法名**字符串字面量，形如
`request('zeldaEasy.platform-console.provider.addProvider', {...})` 或
`mcpFetch<In, Out>('zeldaEasy.platform-infrastructure.mcp.create', params)`——正是 §3.5
「无描述（如 action / RPC 形态）」那一支（原文见 `rings/structure/reference.md` §4 D）。
`path` 记**方法名本身**（不合成 URL——合成即编事实），`method` 记 `RPC`（调用点不带动词，
传输动词不可取证）。**为何要它**：缺它时前端项目的 `api` 产出恒为 **0 条**（既不认装饰器
也不认 `app.get(`），而 `api` 判定为「接」（§6.2），⇒ agent 只能手写端点清单（实测手写会产
类型解析瑕疵，如泛型尾部多 `>`）。**与 D42 的关系**：D42 的「不收前端 client 调用」以
「存在后端 / 描述侧真相源」为前提，纯前端无描述态下调用点即 D 类唯一机械可抽源（见 DESIGN.md D42）。

用法：
    python3 api.py --root <代码根> [--app <name>] --out <json 路径>
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lib import (  # noqa: E402
    IGNORE_DIRS, die, iter_files, load_apps, resolve_app, strip_js_comments, write_json,
)

ADAPTER = "api"
VERSION = "0.2.0"

DESCRIPTOR_FILES = {"openapi.json", "openapi.yaml", "openapi.yml", "swagger.json", "swagger.yaml"}
# 运行时自动生成 schema 的框架信号（框架知识仅允许在适配器出现）
SCHEMA_MARKERS = (re.compile(r"\bAPIRouter\s*\("), re.compile(r"\bFastAPI\s*\("))
DECO_RE = re.compile(r"@(\w+)\.(get|post|put|delete|patch|options|head)\(\s*['\"]([^'\"]*)['\"]")
PREFIX_RE = re.compile(r"(\w+)\s*=\s*\w+\([^)]*prefix\s*=\s*['\"]([^'\"]+)['\"]")
JS_RE = re.compile(r"\b(?:app|router)\.(get|post|put|delete|patch)\(\s*['\"]([^'\"]+)['\"]")
ACTION_DEF_RE = re.compile(r"\b(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(")

# TS 的 RPC / action 调用：`callee<泛型…>('点分方法名', …)`。
# 判据 = **调用名 request/fetch/rpc/invoke 系** + 首参是 ≥3 段的点分标识串。两条缺一不可：
# 只看字符串形态会把无关的点分串收进来（实测：OTel 属性键 `attributes.gen_ai.input.messages`）。
_RPC_CALL_RE = re.compile(
    r"(?<![\w$.])(?P<callee>[A-Za-z_$][\w$]*)\s*"
    r"(?:<[^(){};\n]*>\s*)?"
    r"\(\s*['\"](?P<name>[A-Za-z_][\w-]*(?:\.[\w-]+){2,})['\"]"
)
_RPC_CALLEE_RE = re.compile(r"(?i)(request|fetch|rpc|invoke)")


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
    text = strip_js_comments(f.read_text(encoding="utf-8"))
    items: list[dict] = []
    for i, ln in enumerate(text.splitlines(), 1):
        for m in JS_RE.finditer(ln):
            items.append({
                "method": m.group(1).upper(),
                "path": join_path("", m.group(2)),
                "summary": None,
                "source_module": rel,
                "source_file": f"{rel}:{i}",
            })
    return items


def extract_ts_rpc(root: Path, f: Path) -> list[dict]:
    """TS/TSX 里的 RPC / action 调用 → 端点清单（D 类「无描述」形态）。

    `path` = 方法名本身（`a.b.c` 形态的端点标识），**不合成 URL**；`method` = **`RPC`**
    ——调用点看不出传输动词，写 `POST` 就是不可取证的猜测（契约 §3.2 备注；同文件里
    `.pyxl` 的 `@action` 分支写 `POST` 是因为那是**框架事实**，不是这里的先例）；
    `summary` 留空（JSDoc 到调用点之间隔着函数声明，硬挂会错配 ⇒ 宁缺，用途列由 agent 补）。
    """
    rel = f.relative_to(root).as_posix()
    text = strip_js_comments(f.read_text(encoding="utf-8"))
    items: list[dict] = []
    for m in _RPC_CALL_RE.finditer(text):
        if not _RPC_CALLEE_RE.search(m.group("callee")):
            continue
        line = text.count("\n", 0, m.start()) + 1
        items.append({
            "method": "RPC",
            "path": m.group("name"),
            "summary": None,
            "source_module": rel,
            "source_file": f"{rel}:{line}",
        })
    return items


def find_descriptors(root: Path) -> list[str]:
    """按**文件名**找机器可读描述文件（§3.5 的「有描述」探测）。

    为何不能搭源码那圈遍历：`iter_files` 只枚举源码后缀（`.py` / `.ts` …），
    `openapi.json` / `swagger.yaml` 永远不会被 yield ⇒ 该分支曾是不可达的死代码
    （2026-10-15 实测：项目根放 `openapi.json` 仍返回 `spec_entry=null` + `items=[]`，
    即 §6.2 的「把缺口伪装成配门」——接上线后事实表空着，对账却给绿灯）。

    为何**整项目**找而不按 `--app` 收窄：描述文件通常就在仓库根（`spec_entry` 是
    项目级真相源入口），按 app 收窄会让 `--app` 调用整支探测失明。
    """
    if not root.exists():
        return []
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in IGNORE_DIRS and not d.startswith(".venv") and not d.endswith(".venv")
        )
        for name in sorted(filenames):
            if name in DESCRIPTOR_FILES:
                out.append((Path(dirpath) / name).relative_to(root).as_posix())
    return out


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

    desc_files: list[str] = find_descriptors(root)
    schema_sources: list[str] = []
    items: list[dict] = []
    for f in iter_files(root, (".py", ".pyxl", ".js", ".jsx", ".ts", ".tsx"), app_path):
        rel = f.relative_to(root).as_posix()
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
            items.extend(extract_ts_rpc(root, f))

    if desc_files or schema_sources:
        # 转指针形态 = 整体丢弃已抽到的 items ⇒ 必须出声，绝不静默清空
        # （2026-10-15 补：任何 `.py` 文本含 `APIRouter(`/`FastAPI(` 都会走到这里，
        # 演示脚本也算；不出声的话用户看到的是「接口清单是空的」而无从查因）。
        entry = desc_files[0] if desc_files else "/openapi.json"
        if items:
            print(f"WARN[{ADAPTER}]: 探测到机器可读描述（{entry}）⇒ 按 D 类指针形态只记"
                  f"真相源入口，已丢弃源码抽到的 {len(items)} 条端点（契约 §3.5：两种形态"
                  f"不得都写）", file=sys.stderr)
        payload = {
            "category": "api",
            "spec_entry": entry,
            "source_files": sorted(set(desc_files + schema_sources)),
            "adapter_version": VERSION,
        }
    else:
        # **适配器不去重**（2026-10-15 复核改判）：items 的粒度 = 代码里的事实，同一端点被
        # 两个域各调一次是**两条合法事实**——渲染期按 `source_file` 分域，它们各自进自己的
        # `apis.md`（实测真项目 25 个重复键**全部跨域**，零个落进同一张表）。在适配器里按
        # (方法, 路径) 全局去重会把另一个域唯一的那条抹掉。**重复行键的折叠是渲染层的事**
        # （D69：行键级合并；`refresh_structure.py` 按目标文件折叠）。
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
