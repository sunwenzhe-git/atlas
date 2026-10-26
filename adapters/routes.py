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

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.layout import load_layout  # noqa: E402

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
    """从资产根/stack-profile.yaml 读 apps（path / role），供状态标注与 --app 过滤。"""
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


# ---- D82：识别完整性（两形态）+ 出声（2026-10-16，issue #15；RFC-20261016-01）----
#
# 病根：候选文件判据是**文件名**（含 `rout` 或父目录 `router`）⇒ 模块入口表（文件名 `index.*`）
# 被静默排除；且 JSX `<Route>` 形态没有解析器。同文件对「常量路径」有 WARN（出声道具在手
# 边），却在候选闸上静默少报 —— 不完整的事实表冒充 `structure ⇔ 代码` 对账基准。
_JSX_ANY_ROUTE_RE = re.compile(r"<\s*/?\s*Route\b")
_JSX_ATTR_STR = r"""['"`]([^'"`]+)['"`]|\{\s*['"`]([^'"`]+)['"`]\s*\}"""
_JSX_PATH_RE = re.compile(rf"\bpath\s*=\s*(?:{_JSX_ATTR_STR})")
_JSX_COMP_RE = re.compile(r"""\b(?:component|element)\s*=\s*\{\s*<\s*([A-Za-z_$][\w$.]*)""")
_BASENAME_LIT_RE = re.compile(rf"\bbasename\s*=\s*(?:{_JSX_ATTR_STR})")
_BASENAME_ANY_RE = re.compile(r"\bbasename\s*=")
# 本文件是否**挂载了自己的 router**（子路由的本地证据；站点级表只声明数组、在别处被消费）。
# 名字含 `Router` 的元素都算（`HashRouter` / `RouterWrapper` / `RouterProvider` …），
# 但不含 `Route`（单条路由不是挂载）。
_ROUTER_MOUNT_RE = re.compile(r"<\s*[A-Za-z_$][\w$.]*[Rr]outer[\w$]*\b")
_LAZY_IMPORT_RE = re.compile(
    r"""(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:[A-Za-z_$][\w$.]*\.)?lazy\s*\(\s*"""
    r"""(?:\(\s*\)\s*=>\s*)?import\s*\(\s*['"]([^'"]+)['"]\s*\)""")
_PLAIN_IMPORT_RE = re.compile(
    r"""(?:^|\n)\s*import\s+([A-Za-z_$][\w$]*)\s*(?:,\s*\{[^}]*\}\s*)?from\s*['"]([^'"]+)['"]""")


def _iter_jsx_route_tags(src: str):
    """按出现顺序产出 `(是否闭合, 属性文本, 是否自闭合)`。

    为何不用 `[^>]*?`（2026-10-16）：`element={<X />}` 里的 `>` 属**表达式内部**，朴素写法会在
    那提前截断 ⇒ 标签边界算错、自闭合判错、嵌套栈错位 ⇒ 后续**兄弟**条目被多带一层前缀
    （假路径，比缺口更糟）。故用括号 / 引号感知的小扫描器找标签真正的结束。
    """
    i, n = 0, len(src)
    while i < n:
        i = src.find("<", i)
        if i < 0:
            return
        m = re.match(r"<\s*(/?)\s*Route\b", src[i:])
        if not m:
            i += 1
            continue
        off = i
        closing = m.group(1) == "/"
        j = i + m.end()
        brace, quote = 0, None
        while j < n:
            ch = src[j]
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "'\"`":
                quote = ch
            elif ch == "{":
                brace += 1
            elif ch == "}":
                brace = max(0, brace - 1)
            elif ch == ">" and brace == 0:
                break
            j += 1
        attrs = src[i + m.end(): j]
        yield closing, attrs, attrs.rstrip().endswith("/"), off
        i = j + 1


def parse_jsx_routes(text: str, rel: str) -> tuple[list[dict], int, str | None]:
    """JSX `<Route>` 形态 → `(items, 非常量路径条目数, 本文件 router 的 basename)`。

    带**嵌套深度栈**：`<Route path="a">…<Route path="b"/></Route>` ⇒ 子路径 `a/b`（同文件内前缀
    直接合成）。`path` 只认字面量（含 `path={"x"}` 这种带引号的表达式）；非常量 ⇒ 计数出声后
    跳过（与数组形态同纪律：宁缺不产假路径）。

    basename 返回三元：字面量值 / `None` 但**有形**（非常量：`{basename}` 之类）/ 根本没有 ⇒
    调用方靠它区分「模块级子路由但基名不可求值（必须降级+出声）」与「站点级表」。
    """
    items: list[dict] = []
    n_const = 0
    stack: list[str] = []
    for closing, attrs, selfclose, off in _iter_jsx_route_tags(text):
        if closing:
            if stack:
                stack.pop()
            continue
        pm = _JSX_PATH_RE.search(attrs)
        if pm is None:
            if _BASENAME_ANY_RE.search(attrs):
                pass  # 非 Route 上的 basename，不参与
            if re.search(r"\bpath\s*=", attrs):
                n_const += 1
            if not selfclose:
                stack.append("")
            continue
        local = pm.group(1) or pm.group(2) or ""
        segs = [s for s in (stack if stack else []) + [local] if s and s != "/"]
        full = "/" + "/".join(s.strip("/") for s in segs) if segs else "/"
        cm = _JSX_COMP_RE.search(attrs)
        items.append({
            "path": full,
            "name": None,
            "component": cm.group(1) if cm else None,
            "auth": None,
            "params": re.findall(r":([A-Za-z_]\w*)", full) or None,
            "source_file": f"{rel}:{text.count(chr(10), 0, off) + 1}",
            "status": None,
        })
        if not selfclose:
            stack.append(local)
    bm = _BASENAME_LIT_RE.search(text)
    # 字面量 → 值；有形但非常量 → None 且“有形”标志由第二个返回值表达（basename_declared）
    return items, n_const, (bm.group(1) or bm.group(2)) if bm else None


def _basename_declared(text: str) -> bool:
    """本文件是否**声明了** router 的 basename（不论能不能求值）。"""
    return bool(_BASENAME_ANY_RE.search(text))


def _symbol_specs(text: str) -> dict[str, str]:
    """同文件内的「组件符号 → 模块标识符」表（挂载边的首要输入）。"""
    out: dict[str, str] = {}
    for rx in (_LAZY_IMPORT_RE, _PLAIN_IMPORT_RE):
        for m in rx.finditer(text):
            out.setdefault(m.group(1), m.group(2))
    return out


def resolve_spec(spec: str, from_rel: str, known: set[str]) -> str | None:
    """模块标识符 → 文件（唯一命中才返回；否则 None = 未解析）。

    评审 F1 把口径改成可判定的：**不是**拿 `spec` 的尾段去与 relpath 字面相等（那恒不命中），
    也不只看目录命中（同目录下 `index.*` / `routes.*` 会多命中）——而是
    ① 相对标识符按文件目录做路径运算（唯一存在者）；
    ② 别名标识符丢掉首个 `/` 前的段得 `tail`，候选 = relpath 里含 `/{tail}/` 的项
       ⇓ **再用「该文件也声明了路由表」过滤**；
    ③ 过滤后仍不唯一 ⇒ None。
    """
    def pick(prefix: str) -> str | None:
        base = posixpath.normpath(prefix) if prefix else ""
        cands = [r for r in known if r == base or r.startswith(base + "/")]
        for suf in ("", ".tsx", ".ts", ".jsx", ".js", "/index.tsx", "/index.ts",
                    "/index.jsx", "/index.js"):
            hit = [c for c in cands if c == base + suf]
            if len(hit) == 1:
                return hit[0]
        return None

    if spec.startswith("."):
        return pick(posixpath.join(posixpath.dirname(from_rel), spec))
    tail = spec.split("/", 1)[1] if "/" in spec else spec
    if not tail:
        return None
    hits = sorted(r for r in known if ("/" + tail + "/") in r or r.startswith(tail + "/"))
    hits = [r for r in hits if r.endswith(("/index.tsx", "/index.ts", "/index.jsx", "/index.js"))]
    return hits[0] if len(hits) == 1 else None


def compose_prefix(prefix: str, local: str) -> str:
    """前缀 + 本地路径 → 全站路径（规范化：折叠重复斜杠；前缀 `/` 视作空；保留 `:param`）。"""
    p = (prefix or "").strip("/")
    lp = (local or "").strip("/")
    if not p:
        return "/" + lp if lp else "/"
    return "/" + f"{p}/{lp}" if lp else "/" + p


def collect_js_routes(root: Path, apps: list[dict], app_path: str | None,
                      relpaths: list[str] | None = None) -> tuple[list[dict], dict]:
    """**声明式路由表**识别（React Router / Vue Router 同族约定）—— 两形态 + 挂载前缀合成。

    为何候选判据从「文件名」改成「内容」（2026-10-16，issue #15；D82）：文件名闸（含 `rout`
    或父目录 `router`）会静默排除模块入口表（文件名 `index.*`）——实测一次接入：11 个声明
    路由表的文件只扫到 1 个（19 条 vs 實际 ~54 条）。廉价预筛保留，但**不再承担正确性**。

    为何必须做挂载前缀合成（D83，评审 F1/F2）：模块级表的路径是**模块相对**的（`/create`），
    而 C 类契约是**全站总表**、渲染层行键是 `(应用, 页面/路由)` —— 多个模块的同名 `/create`
    会撞成同一行键被 `dedup_by_row_key` 折叠 ⇒ **不是少报，而是多报假事实**。故：
    站点级表（无入边且无 basename 声明）路径原样；模块级表用挂载前缀合成；
    **前缀求不出的文件：条目全部丢弃 + 计数出声**（宁缺不产假路径）。

    返回 `(items, route_coverage)`。
    """
    suffixes = (".tsx", ".ts", ".jsx", ".js")
    if relpaths is None:
        relpaths = [f.relative_to(root).as_posix()
                    for f in iter_files(root, suffixes, app_path)]
    rels = sorted(r for r in relpaths if r.endswith(suffixes))

    # ① 内容判据：声明路由表（数组形态 或 JSX 形态）；生成的路由树跳过（与文件式路由同口径）
    tables: dict[str, dict] = {}
    for rel in rels:
        if posixpath.basename(rel).startswith("routeTree"):
            continue
        try:
            raw = (root / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        if "rout" not in raw.lower():          # 廉价预筛（只省解析，不承担正确性）
            continue
        src = strip_js_comments(raw)
        arr = _route_array_starts(src)
        jsx = bool(_JSX_ANY_ROUTE_RE.search(src))
        if not arr and not jsx:
            continue
        tables[rel] = {"src": raw, "arr": bool(arr), "jsx": jsx}

    known = set(rels)
    items: list[dict] = []
    coverage = {"declared": len(tables), "site_level": 0, "mounted": 0,
                "skipped_items": 0, "skipped": []}

    # ② 每文件解析（数组形态沿用 parse_js_router；JSX 形态走 parse_jsx_routes）
    parsed: dict[str, dict] = {}
    for rel, info in tables.items():
        its: list[dict] = []
        n_const = 0
        if info["arr"]:
            got, nc = parse_js_router(info["src"], rel)
            its += got
            n_const += nc
        if info["jsx"]:
            got, nc, base = parse_jsx_routes(strip_js_comments(info["src"]), rel)
            its += got
            n_const += nc
        else:
            base = None
        parsed[rel] = {"items": its, "n_const": n_const, "base": base, "src": info["src"]}
        if n_const:
            print(f"[{ADAPTER}] WARN: {rel} 有 {n_const} 条常量路径（path 非字面量，"
                  f"静态不可求值）已跳过——取证范围少报这些条目", file=sys.stderr)

    # ③ 挂载边：站点级表的 `(前缀, 目标文件)`；目标必须是**也声明表**的文件
    edges: dict[str, list[str]] = {}
    for rel, info in parsed.items():
        syms = _symbol_specs(info["src"])
        for it in info["items"]:
            comp = it.get("component")
            if not comp:
                continue
            spec = comp if (comp.startswith(".") or "/" in comp) else syms.get(comp)
            if not spec:
                continue
            tgt = resolve_spec(spec, rel, set(parsed) & known)
            if not tgt or tgt == rel:
                continue
            edges.setdefault(tgt, []).append(it["path"])

    # ④ 前缀取值：恰好 1 条入边才可用；多入边 / 成环 ⇒ 未解析（评审 F2）
    prefix: dict[str, str] = {}
    unresolved: dict[str, str] = {}
    for rel in parsed:
        ins = sorted(set(edges.get(rel, [])))
        if len(ins) > 1:
            unresolved[rel] = f"挂载前缀不唯一（候选：{'、'.join(ins)}）"
        elif len(ins) == 1:
            prefix[rel] = ins[0]

    # ⑤ 站点级 / 模块级：入边优先；无入边时用**本地证据**判（是否挂载了自己的 router）
    #
    # 为何不能只看 basename（2026-10-16 变异取证）：模块表写了**字面量 basename** 时，别名解析
    # 失效会被 basename 兜住 ⇒ 缺陷不可观测；而模块表既无入边又无 basename 时，只看 basename
    # 会把它误判成站点级、把模块相对路径静默泄成全站路径。两条都是假事实 / 静默漏。
    # 故本地证据 = 「本文件挂载了自己的 router」（子路由）而**不是**「有没有 basename」。
    for rel, info in parsed.items():
        if rel in unresolved or rel in prefix:
            continue
        src = strip_js_comments(info["src"])
        if not _basename_declared(src) and not _ROUTER_MOUNT_RE.search(src):
            prefix[rel] = ""                      # 站点级：路径原样
        elif info["base"]:
            prefix[rel] = info["base"]           # 本地字面量基名（备选 C）
        else:
            unresolved[rel] = "基名不可求值（子路由无字面量 basename）且无挂载方"

    # ⑥ 成环体检：有入边前缀但该前缀又由自己挂着（自环 / 互环）
    for rel in list(prefix):
        seen, cur = set(), rel
        while cur and cur in prefix and prefix[cur]:
            if cur in seen:
                unresolved[rel] = "挂载关系成环"
                break
            seen.add(cur)
            nxt = next((k for k, v in edges.items() if cur in v), None)
            cur = nxt or ""
        if rel in unresolved:
            prefix.pop(rel, None)

    # ⑦ 交叉自证（D83 条 7）：模块自己写了字面量 basename ⇒ 与合成前缀比对；
    # 不一致 ⇒ WARN（两个值都写进文案）并采用挂载前缀（公开路径由挂载方定义）。
    for rel in sorted(prefix):
        pre, base = prefix[rel], parsed[rel].get("base")
        if pre and base and pre.rstrip("/") != base.rstrip("/"):
            print(f"[{ADAPTER}] WARN: {rel} 自身 basename=\"{base}\" 与挂载前缀 \"{pre}\" "
                  f"不一致——采用挂载前缀（公开路径由挂载方定义）", file=sys.stderr)

    # ⑧ 合成 + 计数出声
    for rel, info in parsed.items():
        if rel in unresolved:
            coverage["skipped_items"] += len(info["items"])
            coverage["skipped"].append({"file": rel, "reason": unresolved[rel],
                                        "items": len(info["items"])})
            continue
        pre = prefix.get(rel, "")
        coverage["site_level" if pre == "" else "mounted"] += 1
        for it in info["items"]:
            it = dict(it)
            if pre:
                # 只对**模块级**表合成；站点级表（pre == ""）的路径**原样保留**
                # —— 它们已经是全站视角的写法（也含「把 URL 当路由写在表里」这类既有形态）。
                it["path"] = compose_prefix(pre, it["path"])
                it["params"] = re.findall(r":([A-Za-z_]\w*)", it["path"]) or None
            it["status"] = "已实现" if landing(rel, apps) else None
            items.append(it)
    return items, coverage


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
        die("--backend graph 但 profile 未声明 graph 段（先在资产根/stack-profile.yaml 声明）")
    relpaths, backend_used, fallback = resolve_relpaths(root, app_path, backend, cfg,
                                                        explicit=args.backend != "auto")

    js_items, route_coverage = collect_js_routes(root, apps, app_path, relpaths)
    items = (collect_file_routes(root, apps, app_path, relpaths)
             + collect_file_based_routes(root, apps, app_path, relpaths)
             + js_items)
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
        "route_coverage": route_coverage,
    }
    if fallback:
        out["backend_fallback"] = fallback
    dst = Path(args.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    tag = f"backend={backend_used}" + (f"（降级：{fallback}）" if fallback else "")
    cov = route_coverage
    print(f"[{ADAPTER}] {len(items)} 条路由 / {len(source_files)} 个源文件（{tag}） -> {dst}")
    # 出声（D82 条 3）：声明数 / 站点级 / 已挂载 / 丢弃 —— 覆盖率不得静默
    print(f"[{ADAPTER}] 覆盖：声明路由表的文件 {cov['declared']} 个 → 站点级 {cov['site_level']}、"
          f"已挂载 {cov['mounted']}、未解析 {len(cov['skipped'])}（丢弃 {cov['skipped_items']} 条）")
    for s in cov["skipped"]:
        print(f"[{ADAPTER}]   ↳ {s['file']}：{s['reason']}（{s['items']} 条未产出）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
