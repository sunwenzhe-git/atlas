#!/usr/bin/env python3
"""atlas 事实抽取适配器 —— routes（C 类：路由 / 页面清单）。

契约见 `.atlas/shared/stack-profile.md` §3（调用方式 / 输出 JSON / items 字段）。
本文件是**框架知识的合法落点**：适配器内部可识别具体栈；atlas 核心不认任何框架。

做法：扫描代码根内已识别的**路由源签名**（文件即路由的页面目录 / **文件式路由 `routes/`** /
前端 router 定义文件），机械产出 `items[]`；用途 / 交互等语义列由 structure 环的 agent 补。

前端 router 定义文件 = **声明式路由表**：含 `rout` 的数组绑定（`routes` / `routesList` /
`otherRouters` / `adminSubRoutes` …），值是 `{ path: …, element/component: … }` 对象数组；
一个文件可有多张表，`element: <X />` 与 `titleKey` 一并收（2026-10-15 补，见下）。

文件枚举二通道（2026-10-05 图谱批 1）：

* `--backend regex`（缺省）：`os.walk` 遍历（纯标准库，零依赖）。
* `--backend graph`：文件清单来自代码图谱（`_graph.py`，用前现刷），派生逻辑同一份。
  profile 声明 `graph.backend` 且未显式给旗标 ⇒ 自动走 graph；后端不可用 ⇒ **显式降级**
  （stderr WARN + 输出 JSON 的 `backend_fallback` 字段），绝不静默。显式 `--backend graph`
  而后端不可用 ⇒ 硬错。

用法：
    python3 routes.py --root <代码根> [--app <name>] --out <json 路径> [--backend auto|regex|graph]
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import sys
from pathlib import Path

ADAPTER = "routes"
VERSION = "0.3.0"

# 文件枚举的全量后缀池（三识别方式各自再过滤）；graph 通道一次枚举共用。
_ENUM_SUFFIXES = (".pyxl", ".tsx", ".ts", ".jsx", ".js")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _graph  # noqa: E402  # 同包隔离层（唯一后端接触面）
from _lib import strip_js_comments  # noqa: E402  # 同包共用工具（引号感知的注释剥离）

IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", "site-packages", "dist", "build",
    ".pyxle-build", ".next", ".turbo", ".mypy_cache", ".pytest_cache",
}


def die(msg: str) -> None:
    print(f"ERROR[{ADAPTER}]: {msg}", file=sys.stderr)
    sys.exit(1)


def iter_files(root: Path, suffixes: tuple[str, ...], app_path: str | None = None):
    """遍历 root 下的候选源文件，剪掉依赖 / 构建 / VCS 目录。确定性（排序）。"""
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
    """从 product/stack-profile.yaml 读 apps（path / role），供状态标注与 --app 过滤。"""
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
        if re.match(r"^apps:\s*$", line):
            in_apps = True
            continue
        if in_apps and re.match(r"^\S", line):
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


def app_of(rel: str, apps: list[dict]) -> dict | None:
    best = None
    for a in apps:
        ap = (a.get("path") or "").strip("/")
        if ap and (rel == ap or rel.startswith(ap + "/")):
            if best is None or len(ap) > len(best.get("path") or ""):
                best = a
    return best


def landing(rel: str, apps: list[dict]) -> bool:
    a = app_of(rel, apps)
    return bool(a and a.get("role") == "landing")


# ------------------------------------------------------------------ 页面目录路由

def pyxle_route(pages_dir: Path, f: Path) -> tuple[str, list[str]] | None:
    """文件即路由：index→/、[x]→:x、layout/_* 跳过。返回 (path, params) 或 None。"""
    stem = f.stem
    if stem == "layout" or stem.startswith("_"):
        return None
    parts = list(f.relative_to(pages_dir).with_suffix("").parts)
    if parts and parts[-1] == "index":
        parts = parts[:-1]
    segs, params = [], []
    for seg in parts:
        m = re.fullmatch(r"\[(.+?)\]", seg)
        if m:
            segs.append(":" + m.group(1))
            params.append(m.group(1))
        else:
            segs.append(seg)
    path = "/" + "/".join(segs)
    return (path if path != "/" else "/"), params


def collect_file_routes(root: Path, apps: list[dict], app_path: str | None,
                        relpaths: list[str] | None = None) -> list[dict]:
    items: list[dict] = []
    files = ([root / r for r in relpaths if r.endswith(".pyxl")]
             if relpaths is not None else iter_files(root, (".pyxl",), app_path))
    for f in files:
        if f.parent.name != "pages":
            continue
        r = pyxle_route(f.parent, f)
        if r is None:
            continue
        path, params = r
        rel = f.relative_to(root).as_posix()
        items.append({
            "path": path,
            "name": None,
            "component": None,
            "auth": None,
            "params": params or None,
            "source_file": rel,
            "status": "已实现" if landing(rel, apps) else None,
        })
    return items


# ------------------------------------------------------------------ 前端 router 文件

def _balanced(text: str, start: int, opener: str, closer: str) -> int:
    depth = 0
    i = start
    quote = ""
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _top_level_objects(text: str) -> list[tuple[int, str]]:
    """取数组文本中 depth==1 的 {...} 块，返回 (绝对偏移, 块文本)。"""
    out: list[tuple[int, str]] = []
    i, n = 0, len(text)
    quote = ""
    depth = 0
    obj_start = -1
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start >= 0:
                out.append((obj_start, text[obj_start:i + 1]))
                obj_start = -1
        i += 1
    return out


# 路由数组的绑定名判据（**廉价信号**）：绑定名含 `rout`（大小写不敏感）且值是对象数组。
# 不加名字闸就会把配置里任意 `{ path: … }` 数组误收成路由——那比漏收更糟（把缺口伪装成配门）。
_ROUT_NAME_RE = re.compile(r"rout", re.I)
# 对象里**有 `path` 键**（值不是字面量 ⇒ 常量路径，静态不可求值）
_PATH_KEY_RE = re.compile(r"(?<![\w$])path\s*:")
# 声明式：`const routesList: RouteConfig[] = [` / `export const routes = [`（类型标注可省）
_DECL_ARRAY_RE = re.compile(
    r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*"
    r"(?::[^=\n]{0,120}?)?=\s*\["
)
# 对象字面量式：`createRouter({ routes: [...] })` / 裸 `routes = [`
_OBJ_ARRAY_RE = re.compile(r"(?<![\w$.])(rout[\w$]*)\s*[:=]\s*\[", re.I)


def _route_array_starts(text: str) -> list[int]:
    """文件里所有「路由数组」字面量的 `[` 偏移，去重升序（一个文件可有多张表）。"""
    starts: set[int] = set()
    for m in _DECL_ARRAY_RE.finditer(text):
        if _ROUT_NAME_RE.search(m.group(1)):
            starts.add(m.end() - 1)
    for m in _OBJ_ARRAY_RE.finditer(text):
        starts.add(m.end() - 1)
    return sorted(starts)


def parse_js_router(text: str, rel: str) -> tuple[list[dict], int]:
    """声明式路由表 → (items[], 常量路径条目数)。

    `name?` 收 `name` 与 `titleKey` 两键（后者是主流前端同族的展示标题键，语义列由 agent 定）；
    `component?` 依次看 `import(…)` → `element: <X …>` → `component: X`。
    `path` **只认字符串字面量**（单引号 / 双引号 / 反引号）：`path: SOME_CONST` 无法静态求值
    ⇒ 跳过（宁缺，不产假路径），但**计数出声**（2026-10-15 补）：静默跳过会让 §9 报告的
    「取证范围」少报——若整个文件都是常量路径，它连 `source_files` 都进不去。
    """
    src = strip_js_comments(text)
    items: list[dict] = []
    n_const = 0
    for arr_start in _route_array_starts(src):
        arr_end = _balanced(src, arr_start, "[", "]")
        if arr_end < 0:
            continue
        body = src[arr_start:arr_end + 1]
        for off, obj in _top_level_objects(body):
            pm = re.search(r"""path\s*:\s*['"`]([^'"`]+)['"`]""", obj)
            if not pm:
                if _PATH_KEY_RE.search(obj):     # 有 path 键、值不是字面量 ⇒ 常量路径
                    n_const += 1
                continue
            path = pm.group(1)
            nm = re.search(r"""(?:name|titleKey)\s*:\s*['"`]([^'"`]+)['"`]""", obj)
            comp = None
            im = re.search(r"""import\(\s*['"`]([^'"`]+)['"`]\s*\)""", obj)
            if im:
                imp = im.group(1)
                if imp.startswith("."):
                    comp = posixpath.normpath(posixpath.join(posixpath.dirname(rel), imp))
                else:
                    comp = imp
            else:
                cm = (re.search(r"component\s*:\s*([A-Za-z_$][\w$.]*)", obj)
                      or re.search(r"element\s*:\s*<\s*([A-Za-z_$][\w$.]*)", obj))
                if cm:
                    comp = cm.group(1)
            line = src.count("\n", 0, arr_start + off) + 1
            items.append({
                "path": path,
                "name": nm.group(1) if nm else None,
                "component": comp,
                "auth": None,
                "params": re.findall(r":([A-Za-z_]\w*)", path) or None,
                "source_file": f"{rel}:{line}",
                "status": None,
            })
    return items, n_const


def collect_file_based_routes(root: Path, apps: list[dict], app_path: str | None,
                              relpaths: list[str] | None = None) -> list[dict]:
    """**文件式路由**（TanStack / Next / Remix 同族约定）：目录段 `routes` 下的文件即路由。

    命名约定（机械可判，不需要认识具体框架）：
      * `index.*` → 父路径；`$x` → `:x`；
      * `_` / `__` 前缀段 = **路径无关**（layout / 根），不成路由；
      * 目录段逐级拼接；`routeTree.gen.*` 等生成物跳过。

    为何要它（2026-09-28 实测，`3509 §B118`）：本栈用文件式路由（`frontend/src/routes/`），
    而原适配器只认 `pages/` 页面目录与 JS `routes: [...]` 声明 ⇒ 对真实项目产出 **0 条**。
    """
    items: list[dict] = []
    files = ([root / r for r in relpaths]
             if relpaths is not None else iter_files(root, (".tsx", ".ts", ".jsx", ".js"), app_path))
    for f in files:
        if f.suffix not in (".tsx", ".ts", ".jsx", ".js"):
            continue
        rel = f.relative_to(root).as_posix()
        parts = rel.split("/")
        if "routes" not in parts[:-1]:
            continue
        idx = max(i for i, p in enumerate(parts[:-1]) if p == "routes")
        stem = f.stem
        if stem.startswith("_") or stem.startswith("routeTree"):
            continue
        # 文件名的 `.` = **段分隔**（TanStack 约定）：`projects.$id` → `projects` / `:id`
        segs = parts[idx + 1:-1] + [p for p in stem.split(".") if p]
        path_segs: list[str] = []
        for s in segs:
            if s.startswith("_") or s == "index":
                continue
            path_segs.append(re.sub(r"\$(\w+)", r":\1", s))
        path = "/" + "/".join(path_segs) if path_segs else "/"
        items.append({
            "path": path,
            "name": None,
            "component": rel,
            "auth": None,
            "params": re.findall(r":([A-Za-z_]\w*)", path) or None,
            "source_file": f"{rel}:1",
            "status": None,
        })
    return items


def collect_js_routes(root: Path, apps: list[dict], app_path: str | None,
                      relpaths: list[str] | None = None) -> list[dict]:
    """**声明式路由表**识别（React Router / Vue Router 同族约定）。

    为何去掉「父目录必须叫 `router`」与「只认 `.js`/`.ts`」（2026-10-15 实测）：
    真实接入项目把路由表放在 `src/entry/main/routes.tsx`——父目录 `main`、后缀 `.tsx`、
    绑定名 `routesList`（另有 `otherRouters` / `adminSubRoutes`）。三道闸叠加 ⇒ **0 条**，
    而该栈正是 adopt 的主力形态（`3509 §B118` 同族：适配器认不认本栈必须先有判据）。

    改判据：候选文件 = **文件名含 `rout`** 或落在 `router/` 目录里（廉价闸，避免全量读
    `.ts`/`.tsx`）；命中与否交给 `parse_js_router` 的数组判据，不再要求固定目录名。
    """
    items: list[dict] = []
    suffixes = (".tsx", ".ts", ".jsx", ".js")
    files = ([root / r for r in relpaths if r.endswith(suffixes)]
             if relpaths is not None else iter_files(root, suffixes, app_path))
    for f in files:
        if "rout" not in f.name.lower() and f.parent.name != "router":
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = f.relative_to(root).as_posix()
        parsed, n_const = parse_js_router(text, rel)
        if n_const:
            print(f"[{ADAPTER}] WARN: {rel} 有 {n_const} 条常量路径（path 非字面量，"
                  f"静态不可求值）已跳过——取证范围少报这些条目", file=sys.stderr)
        for it in parsed:
            it["status"] = "已实现" if landing(rel, apps) else None
            items.append(it)
    return items


# ------------------------------------------------------------------ main

def resolve_relpaths(root: Path, app_path: str | None, backend: str, cfg: dict | None,
                     explicit: bool = False) -> tuple[list[str], str | None, str | None]:
    """文件枚举二通道。返回 (relpaths, 实际 backend, 降级原因)。

    graph 通道：文件清单来自代码图谱（用前现刷），后端不可用 ⇒ 响亮降级回 regex；
    **显式** `--backend graph` 而后端不可用 ⇒ 硬错（显式要求不得被静默改道）；
    auto 解析出的 graph 通道在后端不可用时降级（auto = profile 偏好，不是用户显式要求）。
    """
    if backend == "regex":
        return _walk_relpaths(root, app_path), "regex", None
    det = _graph.detect(root, cfg)
    if det is None:
        if explicit:
            _graph.die("--backend graph 显式要求，但 cgc 不可用（未安装或探测失败）")
        _graph.warn(f"profile 声明了 graph.backend 但 cgc 不可用——显式降级为 regex 枚举"
                    f"（安装 cgc 或移除 profile 的 graph 段后恢复 graph 通道）")
        return _walk_relpaths(root, app_path), "regex", "cgc 不可用（未安装或探测失败）"
    _graph.ensure_index(root, cfg, version=det["version"])
    return _prune(_graph.file_paths(root, prefix=app_path, cfg=cfg)), "graph", None


def _prune(relpaths: list[str]) -> list[str]:
    """把图谱枚举结果剪成与 regex 通道**同一范围**（确定性排序）。

    为何必须剪（2026-10-15 复核补，`3509 §B92` 同族）：regex 通道走 `iter_files`，
    天然剪掉 `IGNORE_DIRS`（`node_modules` / `dist` / `build` …）与 `.venv*`；graph
    通道拿的是后端 File 节点，而 `cgc index` **不带任何 exclude 旗标**——后端若不理
    gitignore，依赖与构建目录里的 `.tsx`/`.ts` 会整批进枚举池并产出**假路由**。
    枚举范围不等价 ⇒ 两条通道的结果不可对等，而「两通道全等」正是
    `tests/test_routes_graph_backend.py` 的立身之本。
    """
    out: list[str] = []
    for rel in relpaths:
        if not rel.endswith(_ENUM_SUFFIXES):
            continue
        if any(p in IGNORE_DIRS or p.startswith(".venv") or p.endswith(".venv")
               for p in rel.split("/")[:-1]):
            continue
        out.append(rel)
    return sorted(out)


def _walk_relpaths(root: Path, app_path: str | None) -> list[str]:
    base = root / app_path if app_path else root
    if not base.exists():
        return []
    out: list[str] = []
    for f in iter_files(root, _ENUM_SUFFIXES, app_path):
        out.append(f.relative_to(root).as_posix())
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True)
    ap.add_argument("--app", default=None, help="只看该 app（按 stack-profile 的 path 匹配）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--backend", default="auto", choices=("auto", "regex", "graph"),
                    help="文件枚举通道：auto = profile 声明 graph 则 graph，否则 regex")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        die(f"--root 不是目录: {root}")

    apps = load_apps(root)
    app_path = None
    if args.app:
        hit = next((a for a in apps if a.get("name") == args.app), None)
        if hit is None:
            die(f"--app {args.app} 不在 stack-profile.apps 中")
        app_path = hit.get("path") or hit.get("name")

    cfg = _graph.load_graph_config(root)
    backend = args.backend
    if backend == "auto":
        backend = "graph" if cfg else "regex"
    elif backend == "graph" and cfg is None:
        die("--backend graph 但 profile 未声明 graph 段（先在 product/stack-profile.yaml 声明）")
    relpaths, backend_used, fallback = resolve_relpaths(root, app_path, backend, cfg,
                                                        explicit=args.backend != "auto")

    items = (collect_file_routes(root, apps, app_path, relpaths)
             + collect_file_based_routes(root, apps, app_path, relpaths)
             + collect_js_routes(root, apps, app_path, relpaths))
    # 去重（同一 path + 同一源文件只留一份）：三种识别方式可能对同一文件各命一次。
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for it in items:
        k = (it["path"], it["source_file"])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(it)
    items = deduped
    items.sort(key=lambda i: (i["source_file"], i["path"]))
    source_files = sorted({i["source_file"].split(":", 1)[0] for i in items})

    out = {
        "category": "routes",
        "items": items,
        "source_files": source_files,
        "adapter_version": VERSION,
        "backend": backend_used,
    }
    if fallback:
        out["backend_fallback"] = fallback
    dst = Path(args.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    tag = f"backend={backend_used}" + (f"（降级：{fallback}）" if fallback else "")
    print(f"[{ADAPTER}] {len(items)} 条路由 / {len(source_files)} 个源文件（{tag}） -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
