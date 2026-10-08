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
import json
import re
import sys
from pathlib import Path

TESTID_ATTR = re.compile(r"""data-testid\s*=\s*["']([^"']+)["']""")
# 模板字面量 testid（2026-10-04）：`data-testid={`…${ident}…`}`——共享外壳按页派生前缀的
# 合法形态（页 slug 与索引页面表逐字一致，可静态枚举），此前被字面量正则漏扫 ⇒
# 「页面表状态如实升『已实现』必然 FAIL」与「状态停在旧值 ⇒ 最严门自动降 WARN」互锁。
TEMPLATE_TESTID_ATTR = re.compile(r"""data-testid\s*=\s*\{\s*`([^`]+)`\s*\}""")
PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")
MAX_EXPANSION = 64  # 展开组合数上限——超出 = 词表不可枚举，按不猜整体跳过
SLUG_IDENTS = ("slug", "pageSlug", "page")  # `${slug}` 族 = 页面表词表（collect_testids 的 pages）
# 形态（`stack-profile.yaml` 的 `origin`）。词表与 `validate_stack_profile.py` 同源，出厂测试守恒。
ORIGINS = ("greenfield", "adopt")
DEFAULT_ORIGIN = "greenfield"
FRONTEND_KINDS = ("frontend", "fullstack")
SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", "coverage", "__pycache__",
             ".venv", "venv", "vendor", ".cache", "out", "target"}
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


def collect_testids(root: Path,
                    globs: list | None = None) -> tuple[dict[str, set[str]], dict[str, int], list[str]]:
    """兼容入口（3 元组）：模板展开值集合见 `collect_testids_expanded`。"""
    per_page, counts, files, _expanded = collect_testids_expanded(root, globs)
    return per_page, counts, files


def collect_testids_expanded(
    root: Path, globs: list | None = None,
) -> tuple[dict[str, set[str]], dict[str, int], list[str], set[str]]:
    """扫**前端源码**取 testid 实然集合（E1 统一，不再按 origin 分流）：
    `(按页归集, 全站字面量计数, 扫到的源文件, 模板展开值全集)`。

    前端源文件的**文件名不是页 slug**（如页面组件 / 路由文件），按 **testid 自身的页前缀**归属；
    **页清单 = 索引页面表（契约 §3.2，唯一真相源）∪ 分片名**——无页面表时才退化为
    「分片名 ∪ testid 首段」（旧口径会把 `error-component` 这类非页 testid 当成页，`3509 §B106`）。
    归不到页的归入 `""`（仍参与全站唯一性，不参与分页等价）。
    **模板字面量**（2026-10-04）：`data-testid={`…${slug}…`}` 按可枚举词表展开入按页归集
    （`${slug}` = 页面表；其余 = 同文件静态属性）；`counts` 只计**字面量**——全站唯一是
    「字面量重复」判据，展开值不是重复字面量。**展开值的挂载范围静态未知**（外壳可能只挂载
    部分页），故展开值**只参与「缺失」判罚、不参与「多余」判罚**（多余 = 调用方排除纯展开值）。
    """
    cases = root / "product" / "e2e" / "cases"
    shard_pages = sorted(p.stem for p in cases.glob("*.md")) if cases.is_dir() else []
    files = _scan_files([root / g for g in (globs or [])])
    texts = [(f, f.read_text(encoding="utf-8", errors="ignore")) for f in files]
    all_tids: set[str] = set()
    for _f, text in texts:
        all_tids.update(TESTID_ATTR.findall(text))
    states = index_page_states(root)
    if states:
        pages = sorted(set(states) | set(shard_pages))
    else:
        pages = sorted(set(shard_pages) | {t.split("-", 1)[0] for t in all_tids})
    per_page: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    expanded: set[str] = set()
    for f, text in texts:
        for tid in TESTID_ATTR.findall(text):
            counts[tid] = counts.get(tid, 0) + 1
            per_page.setdefault(tid_owner(tid, pages) or "", set()).add(tid)
        for body in TEMPLATE_TESTID_ATTR.findall(text):
            for tid in expand_template_testid(body, text, pages) or []:
                expanded.add(tid)
                per_page.setdefault(tid_owner(tid, pages) or "", set()).add(tid)
    return per_page, counts, [f.relative_to(root).as_posix() for f, _t in texts], expanded


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
        cid, section = "", None
        used: set[str] = set()
        listed: set[str] = set()
        for line in block.splitlines():
            t = line.strip()
            if t.startswith("id:"):
                cid = t.split(":", 1)[1].strip()
                continue
            if t in ("step:", "expected:", "testid:"):
                section = t[:-1]
                continue
            if section is None or not t.startswith("- "):
                continue
            item = t[2:].strip()
            if section == "testid":
                listed.add(item)
                continue
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
                used.add(parts[1])
        if cid:
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

    # 实现期薄桩（契约 §4.1）：契约要求它由生成器产出 ⇒ 不存在即 FAIL，不静默（`3509 §B73`）
    stub = root / ".trellis" / "spec" / "conventions" / "testid.md"
    if stub.is_file():
        res.add("实现期薄桩存在", "PASS", "")
    else:
        res.add("实现期薄桩存在", "FAIL",
                "缺 .trellis/spec/conventions/testid.md —— 跑 "
                "`python3 .atlas/scripts/gen_testid_stub.py --root .` 生成"
                "（rings/e2e/reference.md §4.1）")

    src_ids, counts, sources, expanded = collect_testids_expanded(root, globs)
    states = index_page_states(root)
    # 归属页词表：有页面表则以它为准（唯一真相源）；否则沿用「前端前缀 ∪ 分片名」（`3509 §B106`）
    attr_pages = (sorted(set(states) | {p.stem for p in cases.glob("*.md")}) if states
                  else sorted((set(src_ids) - {""}) | {p.stem for p in cases.glob("*.md")}))
    shard_ids = shard_testids(cases, attr_pages)
    if not src_ids and not shard_ids:
        res.add("门控态", "N/A", "前端无 testid 且无分片引用")
        return res

    # 命名规范（"" 桶 = 归不到任何用例页，只查 NAME_RE）
    bad_name = []
    for page, ids in src_ids.items():
        for tid in ids:
            if not NAME_RE.match(tid) or (page and not (tid == page or tid.startswith(page + "-"))):
                bad_name.append(f"{page or '?'}:{tid}")
    res.add("testid 命名规范", "PASS" if not bad_name else "FAIL", f"违规={bad_name[:8]}")

    # 全站唯一
    cross = {t for t, n in counts.items() if n > 1}
    res.add("testid 全站唯一", "PASS" if not cross else "FAIL", f"重复={sorted(cross)[:8]}")

    # 未归属任何用例页的前端 testid（命名违规或缺分片）
    stray = sorted(src_ids.get("", set()))
    res.add("前端 testid 归属", "PASS" if not stray else "WARN",
            f"未归属={stray[:8]}" if stray else "")

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
                f"非法值={bad_state[:8]}（合法值={list(PAGE_STATES)}）" if bad_state else "")
        stale = []
        for p, s in sorted(states.items()):
            n_front = len(src_ids.get(p, ()))
            if s == "未开始" and n_front:
                stale.append(f"{p}:声明「未开始」但前端已有 {n_front} 个 testid ⇒ 应改「实现中」/「已实现」")
            elif s == "已实现" and not n_front and p in shard_ids:
                stale.append(f"{p}:声明「已实现」但前端无该页 testid")
        res.add("实现状态与实然一致", "PASS" if not stale else "WARN",
                f"{stale[:8]}" if stale else "")

    # 分页等价（`已实现` 页 FAIL；`实现中`/`未开始` 页降 WARN 并附同形清单）
    unequal, unequal_soft = [], []
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
            if (states or {}).get(page, DEFAULT_PAGE_STATE) == "已实现":
                unequal.append(det)
            else:
                unequal_soft.append({**det, "实现状态": states[page]})
    if unequal:
        res.add("分页双向集合相等", "FAIL", json.dumps(unequal, ensure_ascii=False))
    elif unequal_soft:
        res.add("分页双向集合相等", "WARN",
                json.dumps(unequal_soft, ensure_ascii=False)
                + "（页实现状态非「已实现」⇒ 缺口列此；实现落地并复核后改回「已实现」严判）")
    else:
        res.add("分页双向集合相等", "PASS", "")

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
