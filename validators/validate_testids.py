#!/usr/bin/env python3
"""atlas 校验器 —— testid 双向集合校验。

按 `rings/e2e/reference.md` §8.1（E1，2026-09-28：抽取源统一为前端源码）：
  * **抽取源 = 前端源码**（`stack-profile.apps` 里 `kind ∈ {frontend, fullstack}` 的路径）的
    `data-testid`——应然侧 = 用例分片（`testid:` 声明 ∪ step/expected 派生）；
    **模板字面量** `data-testid={`…${slug}…`}` 按可枚举词表展开（页 slug = 页面表；
    其余占位符 = 同文件静态属性；不可枚举 ⇒ 不猜跳过，2026-10-04）；
  * **页清单 = 索引页面表**（契约 §3.2，唯一真相源；无表才退化为「分片名 ∪ testid 首段」）；
  * **分页等价**：`实现状态 = 已实现` 的页两集合必须相等（多/少即 **FAIL**）；`实现中` / `未开始`
    的页同形缺口降 **WARN** + 逐页清单（实现粒度是页内特性，`3509 §B106`）；词表外状态值 **FAIL**；
  * **未实现的页**（前端无该页任何 testid）→ **SKIP**（不算失败；检查点搭便车于必然存在的工件，
    `3508 §94` 推论③）；前端扫到 0 个 testid ⇒ 全部 SKIP + WARN；
  * 命名规范 `^[a-z0-9]+(-[a-z0-9]+)+$` 且首段 == 该页 slug；
  * 全站唯一（跨页重复 / 同页多次出现均 FAIL）；
  * 归不到任何用例页的前端 testid → WARN（命名违规或缺分片）；
  * 门控态（无前端 app 路径或无用例目录）记 `N/A`。

- **框架无关**：本文件不得出现任何具体框架名。纯标准库。
- 判定：`PASS`/`WARN` → 退出码 0；`FAIL` → 1。

用法：
    python3 validate_testids.py --root <项目根> [--json]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from pathlib import Path

# 随包内核引导（`_support/`，2026-10-12 单源批）：用例块解析取单源实现
# （`落点` 键与 `step`/`expected`/`testid` 同源解析，见 `_support/case_block.py`）。
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.siblings import load_module  # noqa: E402

parse_block = load_module("case_block").parse_block


def _format_list(items: list[str] | set[str], max_show: int = 20) -> str:
    lst = sorted(items) if isinstance(items, set) else list(items)
    if not lst:
        return ""
    if len(lst) <= max_show:
        return f"{lst}"
    return f"{lst[:max_show]} (共 {len(lst)} 项，截断前 {max_show} 项)"


def _load_stub_generator():
    """F32：定位随包的 `gen_testid_stub`（副本态 = `.atlas` 同级装配；包态 = 源包同级）。"""
    here = Path(__file__).resolve()
    for cand in (here.parents[1] / "scripts" / "gen_testid_stub.py",):
        if cand.is_file():
            spec = importlib.util.spec_from_file_location("atlas_gen_testid_stub", cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None

TESTID_ATTR = re.compile(r"""data-testid\s*=\s*(?:\{\s*)?["']([a-zA-Z0-9_\-]+)["'](?:\s*\})?""")
# 模板字面量 testid（2026-10-04）：`data-testid={`…${ident}…`}`——共享外壳按页派生前缀的
# 合法形态（页 slug 与索引页面表逐字一致，可静态枚举），此前被字面量正则漏扫 ⇒
# 「页面表状态如实升『已实现』必然 FAIL」与「状态停在旧值 ⇒ 最严门自动降 WARN」互锁。
TEMPLATE_TESTID_ATTR = re.compile(r"""data-testid\s*=\s*\{\s*`([^`]+)`\s*\}""")
# 命令式注入 testid（F22，2026-10-15；v0.1.0-beta.14）：原生 JS / Web Components 常见注入形态
# 识别 `el.dataset.testid = "..."`、`el.dataset['testid'] = "..."` 与 `el.setAttribute("data-testid", "...")`，消除假桩诱因
# setAttribute 允许尾逗号（Prettier `trailingComma: all` 会把多行调用写成 `...,\n)`；2026-10-23 D135）
DATASET_TESTID = re.compile(r"""(?:\.dataset\.testid|\.dataset\[["']testid["']\])\s*=\s*["']([a-zA-Z0-9_\-]+)["']""")
SETATTR_TESTID = re.compile(r"""\.setAttribute\(\s*["']data-testid["']\s*,\s*["']([a-zA-Z0-9_\-]+)["']\s*,?\s*\)""")
DATASET_TESTID_TPL = re.compile(r"""(?:\.dataset\.testid|\.dataset\[["']testid["']\])\s*=\s*`([^`]+)`""")
SETATTR_TESTID_TPL = re.compile(r"""\.setAttribute\(\s*["']data-testid["']\s*,\s*`([^`]+)`\s*,?\s*\)""")
# 同文件静态字符串常量 + 单层引用（issue #19，2026-10-16）：`const X = 'a-b-c'; … data-testid={X}`。
# 值仍**静态可枚举**（单跳、同文件），且字面量仍只出现在常量声明处**一处** ⇒ 与字面量同档：
# 计入声明处计数（跨文件重名照报）、参与双向集合两侧判罚。
# **跨文件导入不解析**（无模块图，宁缺不猜）：共享常量请把字面量落在使用点文件内的常量或占位分支。
# 非静态初始化（函数调用 / 三元 / 拼接 / 未在本文件声明的标识符）**不解析** ⇒ 报缺失（不猜）。
CONST_DECL = re.compile(
    r"""(?:^|[^\w$])(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::\s*[^=;\n]+)?=\s*["']([a-zA-Z0-9_\-]+)["']""",
    re.M)
IDENT_TESTID_ATTR = re.compile(r"""data-testid\s*=\s*\{\s*([A-Za-z_$][\w$]*)\s*\}""")


def strip_comments(text: str) -> str:
    """剥离 HTML 注释与 JS/TS 块注释/行注释，防止注释中的陈旧 testid 产生幻影报错。"""
    # 剥离 HTML 注释
    text = re.sub(r"<!--[\s\S]*?-->", "", text)
    # 剥离 JS/TS 块注释
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    # 剥离 JS/TS 行注释（排除协议头 http:// 或 https:// 等）
    text = re.sub(r"(?<!:)\/\/[^\n]*", "", text)
    return text
PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")
MAX_EXPANSION = 64  # 展开组合数上限——超出 = 词表不可枚举，按不猜整体跳过
SLUG_IDENTS = ("slug", "pageSlug", "page")  # `${slug}` 族 = 页面表词表（collect_testids 的 pages）
# 形态（`stack-profile.yaml` 的 `origin`）。词表与 `validate_stack_profile.py` 同源，出厂测试守恒。
ORIGINS = ("greenfield", "adopt")
DEFAULT_ORIGIN = "greenfield"
FRONTEND_KINDS = ("frontend", "fullstack")
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", "coverage", "__pycache__",
             ".venv", "venv", "vendor", ".cache", "out", "target"}
# 测试文件/目录**不入实然集合**（issue #27/#33，2026-10-19）：单元测试与夹具里的
# `querySelector('[data-testid=x]')` 是页面元素的**回声**，不是声明处 —— 计进「声明处计数」
# 会把「真实元素 + 自身测试文件里的同名字符串」判成全站重复假红（同文件重复 WARN 同理）。
TEST_SKIP_DIRS = {"__tests__", "test", "tests", "__mocks__", "__snapshots__", "e2e", "fixtures"}
TEST_FILE_MARKS = (".test.", ".spec.", ".cy.", ".stories.")
MAX_SCAN_BYTES = 2 * 1024 * 1024
CASE_BLOCK = re.compile(r"```atlas-case\s*\n(.*?)```", re.S)
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)+$")
# 页面表（契约 §3.2）：行形如 `| login | /login | 域 | 实现状态 |`；其 slug 列 = 页清单唯一真相源。
PAGE_ROW = re.compile(r"^\|\s*([a-z0-9][a-z0-9-]*)\s*\|\s*(/\S*)\s*\|")
PAGE_STATES = ("已实现", "实现中", "未开始")
# 缺状态列 ⇒ 按最严处理：**缺列不得静默放宽**判据（fail-closed）。
DEFAULT_PAGE_STATE = "已实现"


def index_page_states(root: Path) -> dict[str, str] | None:
    """页清单 + 实现状态 ← 索引**页面表**（契约 §3.2，E1 起页 ↔ 路由的唯一真相源）。

    返回 `{slug: 状态}`；**无页面表 ⇒ `None`**（调用方退化为分片名并记 WARN）。
    状态列缺失 ⇒ 该页取 `DEFAULT_PAGE_STATE`（已实现）——缺列不得静默放宽（`3509 §B106`）。
    """
    idx = root / "product" / "e2e" / "e2e-index.md"
    if not idx.is_file():
        return None
    states: dict[str, str] = {}
    for ln in idx.read_text(encoding="utf-8").splitlines():
        m = PAGE_ROW.match(ln)
        if not m or m.group(1) == "页面":
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        state = cells[3] if len(cells) > 3 and cells[3] and cells[3] != "---" else DEFAULT_PAGE_STATE
        states[m.group(1)] = state
    return states or None


class Result:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, check: str, level: str, detail: str = "") -> None:
        self.checks.append({"check": check, "level": level, "detail": detail})

    @property
    def status(self) -> str:
        levels = {c["level"] for c in self.checks}
        if "FAIL" in levels:
            return "FAIL"
        if "WARN" in levels:
            return "WARN"
        if self.checks and levels <= {"N/A"}:
            return "N/A"
        return "PASS"


_AFTER_RE = re.compile(r"^after:\d+\s+")


def page_of(path: Path) -> str:
    return path.stem


def read_origin(root: Path) -> str:
    """读 `product/stack-profile.yaml` 顶层的 `origin:`（单标量，不引第三方 YAML）。

    缺省 = `greenfield`：与 `validate_stack_profile.py` 同一默认，**保持既有行为**
    （不因未声明而静默切换形态）。词表与那个校验器同源，出厂测试守恒。
    """
    p = root / "product" / "stack-profile.yaml"
    if not p.is_file():
        return DEFAULT_ORIGIN
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if line.startswith("origin:"):
            v = line.split(":", 1)[1].strip().strip("'\"")
            return v if v in ORIGINS else DEFAULT_ORIGIN
    return DEFAULT_ORIGIN


def app_globs(root: Path) -> list[str]:
    """`stack-profile.yaml` 里 `kind ∈ {frontend, fullstack}` 的 app **路径**（真 UI 源文件的搜索根）。

    手写行级解析（不引第三方 YAML）：只认 `apps:` 段内由 `- name:` 开启的块里的 `path` / `kind`。
    """
    p = root / "product" / "stack-profile.yaml"
    if not p.is_file():
        return []
    out: list[dict] = []
    cur = None
    in_apps = False
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = re.sub(r"\s+#.*$", "", raw.rstrip())
        s = line.strip()
        if not s:
            continue
        if not line[:1].isspace():
            in_apps = (s == "apps:")
            cur = None
            continue
        if not in_apps:
            continue
        m = re.match(r"^\s*-\s*name:\s*(.+?)\s*$", line)
        if m:
            cur = {"name": m.group(1), "path": None, "kind": None}
            out.append(cur)
            continue
        m = re.match(r"^\s+(path|kind):\s*(.*?)\s*$", line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2).strip().strip("'\"")
    return [a["path"] for a in out
            if a.get("kind") in FRONTEND_KINDS and a.get("path")]


def _scan_files(roots: list) -> list:
    """框架无关地列出可扫描文件：**不限扩展名**，只跳过依赖 / 产物目录与超大文件。"""
    out = []
    for r in roots:
        if not r.exists():
            continue
        cands = [r] if r.is_file() else sorted(r.rglob("*"))
        for p in cands:
            if not p.is_file() or any(part in SKIP_DIRS for part in p.parts):
                continue
            if any(part in TEST_SKIP_DIRS for part in p.parent.parts) or any(m in p.name for m in TEST_FILE_MARKS):
                continue  # 测试面与夹具不是页面声明处（issue #27/#33）
            try:
                if p.stat().st_size > MAX_SCAN_BYTES:
                    continue
            except OSError:
                continue
            out.append(p)
    return out


def _prop_vocab(src: str, prop: str) -> list[str]:
    """`${item.key}` 类占位符的同文件词表：静态对象属性的字面量值（确定性枚举，不猜运行时）。"""
    return sorted(set(re.findall(rf"""\b{re.escape(prop)}\s*:\s*["']([^"']+)["']""", src)))


def expand_template_testid(body: str, src: str, pages: list[str]) -> list[str] | None:
    """把模板 testid 展开为具体 id 集合；任一占位符词表不可枚举 ⇒ `None`（不猜，整条跳过）。

    * `${slug}` / `${pageSlug}` / `${page}` → **页面表词表**（`pages`；页 slug 与页面表
      逐字一致是共享外壳的实现契约，见项目内 page-slug 模块）；
    * 其余标识符（含 `item.key` 点号形态）→ **同文件静态属性字面量**（`key: "…"`）；
    * 组合数超 `MAX_EXPANSION` ⇒ `None`。
    """
    segs: list[list[str]] = []
    total = 1
    pos = 0
    for m in PLACEHOLDER.finditer(body):
        segs.append([body[pos:m.start()]])
        expr = m.group(1).strip()
        if expr in SLUG_IDENTS:
            vals = pages
        else:
            vals = _prop_vocab(src, expr.split(".")[-1])
        vals = sorted(set(vals))
        if not vals:
            return None
        total *= len(vals)
        if total > MAX_EXPANSION:
            return None
        segs.append(vals)
        pos = m.end()
    segs.append([body[pos:]])
    out = [""]
    for seg in segs:
        out = [a + b for a in out for b in seg]
    return sorted({s for s in out if s})


def template_static_patterns(clean_text: str) -> list[re.Pattern]:
    """模板 testid 的**结构模式**（诊断用，D113，2026-10-19）。

    与 `expand_template_testid` 的分工：后者求**展开值**——占位符词表不可枚举时返回 `None`、
    整条丢弃；本函数求**结构**：`${…}` 段换成 `.+?`、字面段转义 ⇒ **不依赖词表**，不可枚举的模板也有模式。
    用途 = 诊断：某个「缺失名」命中某模板结构 ⇒ 该名来自**模板派生**，而非「实现真漏了」。

    **为何不用「静态前缀」**：模板以占位符开头时前缀为空（如 `` `${slug}-row-${idx}` `` 的首个
    占位符前没有字面量）—— 而这恰是最常见的形态，前缀判据对它完全失效。
    **只保留字面总长 ≥ 3 的模板**：全占位符的模板退化成 `^.+?$`（匹配一切名字），
    留下来会把「真漏实现」误判成「模板派生」。
    """
    out: list[re.Pattern] = []
    for body in (
        TEMPLATE_TESTID_ATTR.findall(clean_text)
        + DATASET_TESTID_TPL.findall(clean_text)
        + SETATTR_TESTID_TPL.findall(clean_text)
    ):
        parts: list[str] = []
        literals = 0
        pos = 0
        for m in PLACEHOLDER.finditer(body):
            lit = body[pos:m.start()]
            parts.append(re.escape(lit))
            literals += len(lit)
            parts.append(".+?")
            pos = m.end()
        tail = body[pos:]
        parts.append(re.escape(tail))
        literals += len(tail)
        if literals < 3:
            continue
        out.append(re.compile("^" + "".join(parts) + "$"))
    return out


def template_pattern_hit(name: str, patterns: list[re.Pattern]) -> bool:
    """`name` 是否命中某个模板结构模式（D113 诊断判据）。"""
    return any(p.match(name) for p in patterns)


def collect_testids(root: Path,
                    globs: list | None = None) -> tuple[dict[str, set[str]], dict[str, int], list[str]]:
    """兼容入口（3 元组）：模板展开值集合见 `collect_testids_expanded`。"""
    per_page, counts, files, _expanded, *rest = collect_testids_expanded(root, globs)
    return per_page, counts, files


def file_testid_decls(clean_text: str, pages: list[str] | None = None) -> tuple[set[str], list[str], set[str]]:
    """单文件**可解析**的 testid 声明：返回 `(声明集合, 静态属性同形态出现序列, 模板展开值集合)`。

    **单源**：`collect_testids_expanded`（全量抽取）与「应然落点」门共用本函数 —— 落点校验
    与全量抽取必须同一口径，否则会出现「抽取器看到了、落点门看不到」的新半通状态（issue #20）。
    已剥注释的文本为入口（调用方先 `strip_comments`）。

    **模板展开值单列**：双向集合门对它们**只判缺失、不判多余**（共享外壳的挂载范围静态未知），
    故不能并入声明集合（并入会被计入「声明处计数」，从而对它启用「多余」判罚）。
    落点门的成员判定 = **声明 ∪ 展开**（模板形态也是合法声明）。
    """
    raw_lits = (
        TESTID_ATTR.findall(clean_text)
        + DATASET_TESTID.findall(clean_text)
        + SETATTR_TESTID.findall(clean_text)
    )
    # 同文件静态常量解析（issue #19）：未在本文件声明的标识符不解析（跨文件导入 / 非静态初始化）。
    consts = dict(CONST_DECL.findall(clean_text))
    ident_tids = [consts[i] for i in IDENT_TESTID_ATTR.findall(clean_text) if i in consts]
    tpl_values: set[str] = set()
    if pages:
        for body in (
            TEMPLATE_TESTID_ATTR.findall(clean_text)
            + DATASET_TESTID_TPL.findall(clean_text)
            + SETATTR_TESTID_TPL.findall(clean_text)
        ):
            tpl_values.update(expand_template_testid(body, clean_text, pages) or [])
    # 静态属性同形态出现序列：供「同文件重复声明」计数（R6.3 收窄）。
    return set(raw_lits) | set(ident_tids), TESTID_ATTR.findall(clean_text) + ident_tids, tpl_values


def shard_landings(cases: Path, proto_pages: list[str] | None = None) -> dict[str, dict[str, list[str]]]:
    """分片声明的 testid 落点 → `{页 slug: {tid: [路径, ...]}}`（契约 §5.5 的 `落点:` 行）。

    `落点:` 行形态：`- <tid> <相对项目根的路径>`。
    **归页口径与 `shard_testids` 同规**：按 testid 的**归属页**（`tid_owner` 最长前缀）归集，
    不按分片文件名 —— 否则共享元素在市场分片里登记、却要按 app 页查（口径不一 = 新的半通）。
    """
    pages = proto_pages or []
    out: dict[str, dict[str, list[str]]] = {}
    for md in sorted(cases.glob("*.md")):
        home = page_of(md)
        for block in CASE_BLOCK.findall(md.read_text(encoding="utf-8", errors="ignore")):
            for line in parse_block(block).get("落点") or []:
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                tid, path = parts[0].strip(), parts[1].strip().strip("`")
                owner = tid_owner(tid, pages) or home
                out.setdefault(owner, {}).setdefault(tid, []).append(path)
    return out


def collect_testids_expanded(
    root: Path, globs: list | None = None, tpl_patterns_out: list[re.Pattern] | None = None,
) -> tuple[dict[str, set[str]], dict[str, int], list[str], set[str], dict[str, list[str]]]:
    """扫**前端源码**取 testid 实然集合（E1 统一，不再按 origin 分流）：
    `(按页归集, 全站声明文件数计数, 扫到的源文件, 模板展开值全集, 同文件字面量重复清单)`。

    `tpl_patterns_out`（D113，2026-10-19）：**可选出参**，给定时同时收集各源文件模板 testid 的
    **结构模式**（见 `template_static_patterns`），供诊断的结构判定使用。默认 `None` ⇒ 行为与
    返回元数不变（调用方零改动）；放在出参而非返回元组，是因为后者已被 4 处调用方按 5 元解包。

    前端源文件的**文件名不是页 slug**（如页面组件 / 路由文件），按 **testid 自身的页前缀**归属；
    **页清单 = 索引页面表（契约 §3.2，唯一真相源）∪ 分片名**——无页面表时才退化为
    「分片名 ∪ testid 首段」（旧口径会把 `error-component` 这类非页 testid 当成页，`3509 §B106`）。
    归不到页的归入 `""`（仍参与全站唯一性，不参与分页等价）。
    **模板字面量**（2026-10-04）：`data-testid={`…${slug}…`}` 按可枚举词表展开入按页归集
    （`${slug}` = 页面表；其余 = 同文件静态属性）；`counts` 只计**声明文件数**（F22，2026-10-15）——
    全站唯一是「跨文件重复」判据，同文件内模板壳与命令式赋值混用不误伤；同文件字面量重复单独 WARN 报警。
    **展开值的挂载范围静态未知**（外壳可能只挂载部分页），故展开值**只参与「缺失」判罚、不参与「多余」判罚**。
    """
    cases = root / "product" / "e2e" / "cases"
    shard_pages = sorted(p.stem for p in cases.glob("*.md")) if cases.is_dir() else []
    files = _scan_files([root / g for g in (globs or [])])
    texts = [(f, f.read_text(encoding="utf-8", errors="ignore")) for f in files]
    all_tids: set[str] = set()
    for _f, text in texts:
        clean = strip_comments(text)
        all_tids.update(TESTID_ATTR.findall(clean))
        all_tids.update(DATASET_TESTID.findall(clean))
        all_tids.update(SETATTR_TESTID.findall(clean))
    states = index_page_states(root)
    if states:
        pages = sorted(set(states) | set(shard_pages))
    else:
        pages = sorted(set(shard_pages) | {t.split("-", 1)[0] for t in all_tids})
    per_page: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    expanded: set[str] = set()
    same_file_dups: dict[str, list[str]] = {}
    for f, text in texts:
        clean_text = strip_comments(text)
        rel = f.relative_to(root).as_posix()
        # 单源：与「应然落点」门共用（见 file_testid_decls）
        file_unique, static_occ, tpl_values = file_testid_decls(clean_text, pages)
        for tid in file_unique:
            counts[tid] = counts.get(tid, 0) + 1
            per_page.setdefault(tid_owner(tid, pages) or "", set()).add(tid)

        # 模板结构模式（诊断用，D113）：与展开值**同点位**收集（同一批已剥注释文本，零额外 IO）。
        # 不可枚举的模板不产生展开值（见 file_testid_decls），但它的结构模式在这里收得到。
        if tpl_patterns_out is not None:
            tpl_patterns_out.extend(template_static_patterns(clean_text))

        # 同文件重复声明（R6.3 收窄）：只对**静态属性同形态重复**报警——
        # 同名静态 testid 在同文件出现 ≥2 次 = 运行期 strict-mode 歧义真信号；
        # 「静态属性 + 命令式赋值（dataset/setAttribute）混用」与「多处渲染函数重复赋值」
        # 是 vanilla JS 的合法惯用法（R6 现网实证：主沙箱三条 WARN 全为此形态），豁免不报。
        file_counts = Counter(static_occ)
        dups = [t for t, cnt in file_counts.items() if cnt > 1]
        if dups:
            same_file_dups[rel] = sorted(dups)

        # 模板字面量形态的展开值：**只参与「缺失」判罚、不参与「多余」判罚**（单源：file_testid_decls）
        for tid in tpl_values:
            expanded.add(tid)
            per_page.setdefault(tid_owner(tid, pages) or "", set()).add(tid)
    return per_page, counts, [f.relative_to(root).as_posix() for f, _t in texts], expanded, same_file_dups


def tid_owner(tid: str, pages: list[str]) -> str | None:
    """按原型页 slug 判 testid 归属（最长前缀；`audio-assets-x` 归 `audio-assets` 而非 `audio`）。"""
    hits = [p for p in pages if tid == p or tid.startswith(p + "-")]
    return max(hits, key=len) if hits else None


def shard_testids(cases: Path, proto_pages: list[str] | None = None) -> dict[str, set[str]]:
    """分片侧（用例侧）testid 集合 = **`testid:` 声明 ∪ `step`/`expected` 派生**，**按 testid 归属页归集**。

    两处 2026-09-25 修正：
      * 派生这一半（3509 §B40 / §B64）：`testid:` 块「必须补齐」纯属派生信息（第二处正文），
        改为派生后作者只在「被引用但断言面不在 step/expected」时才需要写清单。
      * 按**归属页**归集（原按分片文件名）：跨页断言是常态（`E2E-LOGIN-001` 断言登录后的
        `home-page`、`E2E-HOME-006` 断言跳转后的 `projects-title`）⇒ 旧口径会把它们算作
        「本页缺失(原型无)」。归属页取自原型页 slug 的最长前缀。
    **双向集合校验的强度不变**：原型上有、用例侧完全没有的，仍报「多余（用例未引）」。
    """
    pages = proto_pages or []
    per_page: dict[str, set[str]] = {}
    for md in sorted(cases.glob("*.md")):
        home = page_of(md)
        for _cid, used, listed in case_testid_usage(md):
            for t in used | listed:
                per_page.setdefault(tid_owner(t, pages) or home, set()).add(t)
    return per_page



# 契约 §5.5：这两个动作没有 testid（`goto` 取路径、`refresh` 无参）。
_NO_TID_VERBS = {"goto", "refresh"}


def case_testid_usage(md: Path) -> list[tuple[str, set[str], set[str]]]:
    """每条用例的 `(id, step/expected 里用到的 testid, testid: 清单里声明的 testid)`。

    3509 §B40 / 2026-09-25 §B64：用例侧集合原先**只**从 `testid:` 块抽取 ⇒
    ① 「断言了某 testid 却没在清单里列」时，门对该 testid 的判定落到**别的**用例头上（定位错人）；
    ② 每改一条用例都要人肉补清单（纯派生信息，属 `shared/single-source.md §2` 判定的漂移面）。
    现在用例侧集合 = **声明 ∪ 派生**（见 `shard_testids`）：清单只用于「被引用但断言面不落在
    step/expected 的元素」，不再是必须补齐的义务。
    """
    out: list[tuple[str, set[str], set[str]]] = []
    for block in CASE_BLOCK.findall(md.read_text(encoding="utf-8")):
        # 单源解析（2026-10-16，issue #20）：改用 `_support/case_block.parse_block`，
        # 不再手写行扫描 —— 手写版只认 `step`/`expected`/`testid` 三个小节键，
        # 新增一个数组键（如 `落点`）就会把它的条目误吸进 testid 集合（本轮实测踩到：
        # 「testid 命名规范」报 `home-title web/src/home.html` 为违规名）。
        block_dict = parse_block(block)
        cid = block_dict.get("id") if isinstance(block_dict.get("id"), str) else ""
        if not cid:
            continue
        used: set[str] = set()
        for section in ("step", "expected"):
            for item in block_dict.get(section) or []:
                code = item.split("#", 1)[0].strip()
                # 行首前缀都要先剥（豁免通道 `initial:` / `unchanged:`，以及步骤锚 `after:<N>`）——
                # 否则 `after:2 visible X` 会把**动词**当成 testid（实测踩到：本门报「原型无 visible」）。
                m = _AFTER_RE.match(code)
                if m:
                    code = code[m.end():].strip()
                if code.startswith(("initial:", "unchanged:")):
                    code = code.split(":", 1)[1].strip()
                parts = code.split()
                if len(parts) >= 2 and parts[0] not in _NO_TID_VERBS:
                    raw_tid = parts[1]
                    base_tid = re.sub(r"\[\d+\]$", "", raw_tid)
                    used.add(base_tid)
        listed = {i.strip() for i in (block_dict.get("testid") or [])}
        out.append((cid, used, listed))
    return out


def validate(root: Path) -> Result:
    res = Result()
    cases = root / "product" / "e2e" / "cases"
    globs = app_globs(root)

    # 门控态：抽取源或用例目录缺一 —— 本环无输入（本环比的是**两个集合**，缺一侧就没得比）。
    # 注意抽取源要**真的在磁盘上**（只看 globs 已声明会把「刚接入、代码还没落地」误判为有输入）。
    has_src = any((root / g).exists() for g in globs)
    if not has_src or not cases.is_dir():
        res.add("门控态", "N/A",
                f"抽取源={has_src} 用例目录={cases.is_dir()}")
        return res

    # 实现期薄桩（契约 §4.1）：缺失 ⇒ **机器兜底生成**（F32，2026-10-15；与 R6 基线
    # 报告同哲学——缺失的派生工件由就近工具自动补齐），FAIL 只留给"生成不了"的真错。
    stub = root / ".trellis" / "spec" / "conventions" / "testid.md"
    if stub.is_file():
        res.add("实现期薄桩存在", "PASS", "")
    else:
        gen = _load_stub_generator()
        if gen is not None:
            try:
                text, _n = gen.render(root, globs)
                stub.parent.mkdir(parents=True, exist_ok=True)
                stub.write_text(text, encoding="utf-8")
                res.add("实现期薄桩存在", "PASS",
                        "缺失已由本器自动生成（F32 机器兜底；规范正文见 "
                        "rings/e2e/reference.md §4.1）")
            except Exception as exc:  # noqa: BLE001 — 生成失败才给红
                res.add("实现期薄桩存在", "FAIL",
                        f"薄桩缺失且自动生成失败：{exc}（可手动跑 "
                        "`python3 .atlas/scripts/gen_testid_stub.py --root .`）")
        else:
            res.add("实现期薄桩存在", "FAIL",
                    "缺 .trellis/spec/conventions/testid.md 且无法定位生成器 —— 跑 "
                    "`python3 .atlas/scripts/gen_testid_stub.py --root .` 生成"
                    "（rings/e2e/reference.md §4.1）")

    tpl_patterns: list[re.Pattern] = []
    src_ids, counts, sources, expanded, same_file_dups = collect_testids_expanded(
        root, globs, tpl_patterns)
    states = index_page_states(root)
    # 归属页词表：有页面表则以它为准（唯一真相源）；否则沿用「前端前缀 ∪ 分片名」（`3509 §B106`）
    attr_pages = (sorted(set(states) | {p.stem for p in cases.glob("*.md")}) if states
                  else sorted((set(src_ids) - {""}) | {p.stem for p in cases.glob("*.md")}))
    shard_ids = shard_testids(cases, attr_pages)
    if not src_ids and not shard_ids:
        res.add("门控态", "N/A", "前端无 testid 且无分片引用")
        return res

    # 命名规范（2026-10-13 修：存量实然豁免，与契约 §4「既有实现保持现有 data-testid」对齐）。
    # 分两层判：
    #   ① 分片应然（声明侧）：`shard_ids` 里声明的 testid 必须守规范——**除非该名已存在于
    #      源码实然**（`src_ids` ∪ 展开值）：这是 adopt 项目用例引用既有元素的合法形态，改名为
    #      契约所禁；净新增的声明名必须合规 ⇒ 违规 FAIL（名字的可控权在声明者手里）；
    #   ② 存量实然（源码侧）：`src_ids` 里的非常规命名**不再 FAIL** ⇒ WARN + 清单。
    #      事故取证（本次）：`origin: adopt` 项目接入后，既有前端 `login_btn` / `loginButton`
    #      这类历史命名被本门直接打成 FAIL——存量债务不可由"接入"动作清偿，会与现代码强制
    #      改名冲突（契约明言"不强迫"）。修复后：老命名照旧活着并可见（WARN），只要新声明
    #      不夹带新造的非规范名，门就不咬人。
    src_all = set()
    for ids in src_ids.values():
        src_all |= ids
    src_all |= expanded
    bad_name = []
    for page, ids in shard_ids.items():
        for tid in ids:
            if tid in src_all:
                continue  # 引用既有实然（含 adopt 存量命名）⇒ 豁免
            if not NAME_RE.match(tid) or not (tid == page or tid.startswith(page + "-")):
                bad_name.append(f"{page or '?'}:{tid}")
    legacy_bad = []
    for page, ids in src_ids.items():
        for tid in sorted(ids):
            if not NAME_RE.match(tid):
                legacy_bad.append(f"{page or '?'}:{tid}")
    if bad_name:
        res.add("testid 命名规范", "FAIL",
                f"新声明的违规={_format_list(bad_name)} (💡 命名须满足 ^[a-z0-9]+(-[a-z0-9]+)+$ 且以所属页面 slug 为前缀；存量既有名不受此限)")
    elif legacy_bad:
        res.add("testid 命名规范", "WARN",
                f"存量非常规命名={_format_list(legacy_bad)}（存量保持现状即可，不判失败；新声明命名按规范）")
    else:
        res.add("testid 命名规范", "PASS", "")

    # 全站唯一
    cross = {t for t, n in counts.items() if n > 1}
    res.add("testid 全站唯一", "PASS" if not cross else "FAIL",
            f"重复={_format_list(cross)} (💡 提示: 同一 data-testid 在全站跨页面中必须唯一)" if cross else "")

    # 同文件重复声明（WARN 保信号，Minor-3：同文件多处声明建议关注 strict-mode 语义）
    if same_file_dups:
        dup_items = [f"{f}:{_format_list(tids)}" for f, tids in sorted(same_file_dups.items())]
        res.add("同文件 testid 重复声明", "WARN",
                f"同文件多次出现字面量={'; '.join(dup_items)} (💡 同文件多处赋值建议梳理或验证 strict-mode 唯一性)")
    else:
        res.add("同文件 testid 重复声明", "PASS", "")

    # 未归属任何用例页的前端 testid（命名违规或缺分片）
    stray = sorted(src_ids.get("", set()))
    res.add("前端 testid 归属", "PASS" if not stray else "WARN",
            f"未归属={_format_list(stray)}" if stray else "")

    # 未实现的页：前端无该页任何 testid ⇒ SKIP（契约 §4 E1；不算失败）
    unimplemented = sorted(set(shard_ids) - set(src_ids))
    if not src_ids:
        res.add("前端无 data-testid", "WARN",
                "扫描到 0 个 testid：全部页按未实现 SKIP；用 gen_testid_stub 产出应然清单供实现（§4.1）")
    elif unimplemented:
        res.add("未实现页（SKIP）", "PASS", f"{unimplemented}（前端无该页 testid；实现落地即对账）")
    else:
        res.add("未实现页（SKIP）", "PASS", "")

    # 页面表的 `实现状态`（契约 §3.2 / `3509 §B106`）：词表 fail-closed + 状态与实然一致
    # 无页面表时不另记一行：索引结构合法性归 `validate_e2e_index`（它已报「索引无页面表」WARN），
    # 本器只退化为「分片名 ∪ testid 首段」并各页按 `已实现` 严判（重复报警 = 噪声）。
    if states is not None:
        bad_state = sorted(f"{p}:{s}" for p, s in states.items() if s not in PAGE_STATES)
        res.add("页面表实现状态词表", "PASS" if not bad_state else "FAIL",
                f"非法值={_format_list(bad_state)}（合法值={list(PAGE_STATES)}）" if bad_state else "")
        stale = []
        for p, s in sorted(states.items()):
            n_front = len(src_ids.get(p, ()))
            if s == "未开始" and n_front:
                stale.append(f"{p}:声明「未开始」但前端已有 {n_front} 个 testid ⇒ 应改「实现中」/「已实现」")
            elif s == "已实现" and not n_front and p in shard_ids:
                stale.append(f"{p}:声明「已实现」但前端无该页 testid")
        res.add("实现状态与实然一致", "PASS" if not stale else "WARN",
                f"{_format_list(stale)}" if stale else "")

    # 分页等价（`已实现` 页 FAIL；`实现中`/`未开始` 页降 WARN 并附同形清单）
    unequal, unequal_soft = [], []
    origin = read_origin(root)
    for page, ids in shard_ids.items():
        if page not in src_ids:
            continue  # 未实现页已按 SKIP 记录
        pset = src_ids.get(page, set())
        # 模板展开值**不参与「多余」判罚**：外壳挂载范围静态未知（例：`${slug}-nav-*`
        # 会展开进不挂外壳的页），多余不可静态判定（盲区，见 gates.md）；字面量照判。
        # 展开值若同时是字面量（counts>0）则按字面量照判，不放过真实漂移。
        orphan = sorted(t for t in (pset - ids) if t not in expanded or counts.get(t))
        missing = sorted(ids - pset)
        if orphan or missing:
            det = {"page": page, "缺失(抽取源无)": missing, "多余(用例未引)": orphan}
            if orphan:
                # 3509 §B40：把「哪条用例的清单列过它」一并给出，避免定位到错误的用例
                where = {}
                for md2 in sorted(cases.glob("*.md")):
                    for c2, u2, l2 in case_testid_usage(md2):
                        for t2 in orphan:
                            if t2 in u2 or t2 in l2:
                                where.setdefault(t2, []).append(c2)
                det["引用过它的用例"] = where
            page_state = (states or {}).get(page, DEFAULT_PAGE_STATE)
            if origin == "adopt":
                # F20: 存量 Adopt 模式下单向子集校验（以用例为准）
                # 正向（用例引用的代码必须有）继续严格判 FAIL；
                # 反向（代码有多余未引 testid）降级为 WARN/INFO，不判 FAIL！
                if missing and page_state == "已实现":
                    unequal.append(det)
                else:
                    unequal_soft.append({**det, "实现状态": page_state})
            else:
                if page_state == "已实现":
                    unequal.append(det)
                else:
                    unequal_soft.append({**det, "实现状态": page_state})
    if unequal:
        # 诊断（D113，2026-10-19）：把触发判据从**词形启发式**改为**结构判定**。
        # 判据 = 缺失名命中源里某模板 testid 的**结构模式** ⇒ 该名由运行期值拼出、
        # **无法静态枚举**（占位符词表不可枚举的模板不产生展开值，故 expanded 里没有它）。
        # 口径提醒（与 shard_testids 一致）：用例侧应然集合 = testid: 声明 ∪ step/expected 派生
        # ⇒ **两侧都进本门**，「只写在 step/expected」不构成任何豁免。
        missing_all = [n for d in unequal for n in d.get("缺失(抽取源无)", [])]
        hint = (
            " (💡 提示: 缺失名命中某模板 testid 的结构模式 ⇒ 它由运行期值拼出、无法静态枚举；"
            "「只写在 step/expected」不构成豁免（用例侧应然集合 = `testid:` 声明 ∪ step/expected 派生，"
            "两侧都进本门）。正规形态见契约 §4：容器 + 计数（对容器断 `count`）/ 稳定样例行 / 类型级静态名)"
            if any(template_pattern_hit(n, tpl_patterns) for n in missing_all)
            else ""
        )
        res.add("分页双向集合相等", "FAIL", json.dumps(unequal, ensure_ascii=False) + hint)
    elif unequal_soft:
        hint_msg = (
            "（存量 adopt 模式未引 testid 降级为 WARN，或页实现状态非「已实现」⇒ 缺口列此）"
            if origin == "adopt" else
            "（页实现状态非「已实现」⇒ 缺口列此；实现落地并复核后改回「已实现」严判）"
        )
        res.add("分页双向集合相等", "WARN",
                json.dumps(unequal_soft, ensure_ascii=False) + hint_msg)
    else:
        res.add("分页双向集合相等", "PASS", "")

    # 应然落点（issue #20，2026-10-16）：**应然 id 的落点必须是声明式且可机检的资产**。
    # 动因：应然清单取自 AC 文字，而双向集合门只比「值集合相等」⇒ 一个**永不渲染的死字面量**
    # 就能把门凑绿，而用例仍红（现场实证：两条应然 id 所描述的控件在该产品里根本不存在）。
    # 本门把「落点」变成可校验声明：每个应然 id 至少登记一个 `落点: - <tid> <路径>`，
    # 且该文件必须存在、其内必须**可解析**到该 id（口径与全量抽取同源 = `file_testid_decls`）。
    # 分档（D88 / issue #34 联动页面实现状态）：
    #  * 已实现页：**声明了但不对**（文件不存在 / 文件内无可解析声明）= 假陈述 ⇒ FAIL；
    #  * 未实现/进行中页：正向应然先行（落点已登记但代码尚未埋点/文件未建）⇒ WARN（未实现页落点待落地）；
    #  * 未登记落点 = 纪律缺口（存量清零过渡）⇒ WARN（升 FAIL 触发见 shared/gates.md）。
    landings = shard_landings(cases, attr_pages)
    bad_land_hard, bad_land_soft, no_land = [], [], []
    for page, ids in sorted(shard_ids.items()):
        page_state = (states or {}).get(page, DEFAULT_PAGE_STATE)
        is_implemented = (page_state == "已实现")
        for tid in sorted(ids):
            paths = (landings.get(page) or {}).get(tid) or []
            if not paths:
                no_land.append(f"{page}:{tid}")
                continue
            for relp in paths:
                cand = root / relp
                if not cand.is_file():
                    err = f"{page}:{tid} → {relp}（文件不存在）"
                    if is_implemented:
                        bad_land_hard.append(err)
                    else:
                        bad_land_soft.append(f"{err}[{page_state}]")
                    continue
                try:
                    decls, _occ, tpl = file_testid_decls(
                        strip_comments(cand.read_text(encoding="utf-8", errors="ignore")), attr_pages)
                except OSError:
                    bad_land_hard.append(f"{page}:{tid} → {relp}（不可读）")
                    continue
                if tid not in decls and tid not in tpl:
                    err = f"{page}:{tid} → {relp}（该文件内无可解析声明）"
                    if is_implemented:
                        bad_land_hard.append(err)
                    else:
                        bad_land_soft.append(f"{err}[{page_state}]")
    if bad_land_hard:
        res.add("应然落点", "FAIL", f"声明与实然不符={_format_list(bad_land_hard)}")
    elif bad_land_soft:
        warn_msg = f"未实现页落点先行待落地={_format_list(bad_land_soft)}"
        if no_land:
            warn_msg += f"；另未登记落点={_format_list(no_land)}"
        res.add("应然落点", "WARN", warn_msg)
    elif no_land:
        res.add("应然落点", "WARN",
                f"未登记落点={_format_list(no_land)} (💡 分片 `落点:` 行登记 `<tid> <相对项目根的路径>`；“落点”是应然 id 承载元素的声明式证据，见契约 §5.5)")
    else:
        res.add("应然落点", "PASS", "")

    # 前端有页但无分片（页清单以页面表为准；表外的 testid 前缀归「前端 testid 归属」报）
    if states:
        no_shard = sorted(p for p in states if p in src_ids and p not in shard_ids)
    else:
        no_shard = sorted(set(src_ids) - set(shard_ids) - {""})
    res.add("前端有页但无分片", "PASS" if not no_shard else "WARN", f"待补用例={no_shard}")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    res = validate(root)
    if args.json:
        print(json.dumps({"ok": res.status != "FAIL", "status": res.status,
                          "root": str(root), "checks": res.checks}, ensure_ascii=False, indent=2))
    else:
        print(f"validate_testids @ {root}")
        for c in res.checks:
            line = f"  [{c['level']:<4}] {c['check']}"
            if c["detail"] and c["level"] not in ("PASS", "N/A"):
                line += f" —— {c['detail']}"
            print(line)
        print(res.status)
    return 1 if res.status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
