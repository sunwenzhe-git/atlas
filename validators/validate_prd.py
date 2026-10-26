#!/usr/bin/env python3
"""atlas 校验器 —— PRD 环 4 参数确定性校验（`rings/prd/reference.md` §7）。

- **框架无关**：本文件不得出现任何具体框架名。
- 纯标准库。
- 门控态（`prd.md` §零 待决策表非空）时：域级 PRD 按契约不产出，追溯类参数记 N/A、不计入分母。
- 2026-09-26：删除原「参数 5 Waste Test」——实测它是一条**恒 PASS 的空门**（`warn` 列表从未被写过）。
  可机器判的两条并入参数 4（**规则↔AC 双向**、域清单↔域级文件），语义项转 §8 人工审查；
  参数 4 另增三项：**范围形态声明合法** / **声明与 §六 表形态一致** / **最小必填集**。
- 2026-10-14：并入「**AC 号唯一**」判据（域级 PRD 内 AC 号跨文件 / 同文件不得重复）；
  原属地 `validate_ledger.py` 的项目侧判据随「知识库 / 台账子系统」退役归位本环。
- 判定：PASS / WARN / FAIL；FAIL → 退出码 1，其余 0。
- 2026-10-23（`RFC-20261023-02` ③④）：新增两条**独立机器检查**——「变更记录形态」
  （5 列 PASS / legacy 3 列 WARN / 表头不可辨或「影响」空 ⇒ FAIL；独立行，不并入参数 4
  的聚合）与「可无项显式（§六）」（§六 空表/空节且无显式 `无` ⇒ WARN 首版）。

用法：
    python3 validate_prd.py --root <项目根> [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.layout import LayoutError, load_layout  # noqa: E402

FORBIDDEN = ["TODO", "待补充", "TBD", "待定", "视情况而定", "后续补充", "[FIELD:]",
             "[必填", "[条件必填"]
EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,6}$")
BACKTICK = re.compile(r"`([^`\n]+)`")
GATE_ROW = re.compile(r"^\|\s*\d+\s*\|", re.M)
GATE_HEADING = re.compile(r"^##[^\n]*待决策登记[^\n]*$", re.M)
GATE_DECIDED = re.compile(r"已决策")
NEXT_H2 = re.compile(r"^##\s", re.M)
FN_RE = re.compile(r"FN-[A-Z0-9]+-\d+")
R_RE = re.compile(r"\b[A-Z][A-Z0-9]+-R-\d+")
AC_RE = re.compile(r"AC-[A-Z0-9]+-\d+")

# ---- 域间依赖门（参数 4 ⑧）的解析口径（F39，2026-10-15；issue #7 现场实证）----
# 节点 id = 词字符与连字符，**末位必须是词字符**（否则 `---` 这种纯横线会被当成节点）。
# 契约示例是 `id[中文名]`；裸 slug、含连字符的 slug（`ops-console`）都必须可用。
_NODE_ID = r"[\w-]*\w"
# 边：只认实线 `-->`。`-.->` 也要**识别出来**（它是虚线 = 增强链路 / 数据回流，不入边集）——
# 不识别的话就会像旧实现那样在别的箭头形态上静默丢边。其余箭头（`==>` 等）不认。
_SOLID_ARROW = "-->"
_DASHED_ARROW = "-.->"
_EDGE_RE = re.compile(
    rf"({_NODE_ID})(?:\[[^\]]*\])?\s*(?P<arr>{_SOLID_ARROW}|{re.escape(_DASHED_ARROW)})"
    rf"(?:\s*\|[^|]*\|)?\s*({_NODE_ID})")
_LABEL_RE = re.compile(rf"({_NODE_ID})\[([^\]]+)\]")


def _fm_scalar(dt: str, key: str) -> str | None:
    """取 frontmatter 标量**整行**值（`^key: <值>$`）并剥外层引号。

    为何不是 `\\S+`（F39）：那只取到**首个空白前**的一段——含空格的中文名（`网关 管理`）
    被读成 `网关`，于是 mermaid 标签写全名匹配不上、写短名又读不出来，形成**不可满足**。
    模板值本身带引号（`domain_name: "[必填：中文名]"`），故一并剥引号。
    """
    m = re.search(rf"^{re.escape(key)}:\s*(.+)$", dt, re.M)
    if not m:
        return None
    return m.group(1).strip().strip("\"'“”‘’") or None


def _solid_edges(body: str) -> list[tuple[str, str]]:
    """mermaid 流程图里的**实线**边集 `(源节点 id, 靶节点 id)`。

    支持一行的**链式**（`a --> b --> c` 出两条边）与**边标签**（`a -->|前置| b`）；
    `%%` 注释行剥除；`-.->` 不算边。

    旧实现只对整段 `findall(r"(\\w+)(?:\\[[^\\]]*\\])?\\s*-->\\s*(\\w+)")` ⇒ 链式只出第一条
    边、**带边标签的边整条静默丢失**（F39 实测）。静默丢边同样是「把缺口伪装成绿灯」。
    """
    edges: list[tuple[str, str]] = []
    for raw in body.splitlines():
        line = raw.split("%%")[0]
        pos = 0
        while True:
            m = _EDGE_RE.search(line, pos)
            if m is None:
                break
            pos = m.start(3)                 # 链式：下一段从靶节点起续扫（严格递增 ⇒ 必终止）
            if m.group("arr") == _SOLID_ARROW:
                edges.append((m.group(1), m.group(3)))
    return edges

# 契约 §4「五、验收标准」（2026-09-25 补）：域级 PRD 末附**结构类 AC 清单**（只能初始态观测的 AC）。
STRUCT_LIST_HEAD = "#### 结构类 AC 清单"
STRUCT_AC_RE = re.compile(r"AC-[A-Z0-9]+-\d{3}")
# 契约 §4「五、验收标准」（2026-10-12 补，`3509 §B201-3`）：**不可验 AC 清单**（当前 UI 无观测面的
# AC——「AC 反向覆盖」门从零挂靠清单中减去它；豁免落点定形即本条的落地）。
UNVER_LIST_HEAD = "#### 不可验 AC 清单"
# 形态（`stack-profile.yaml` 的 `origin`）。词表与 `validate_stack_profile.py` / `validate_testids.py`
# 同源，出厂测试逐项守恒（硬约束：同一口径的消费者数要数清）。
ORIGINS = ("greenfield", "adopt")
DEFAULT_ORIGIN = "greenfield"
# 范围形态声明（契约 §3，2026-09-26 补）：三行键值，各自独占一行，值闭集。
DECL_FORM = re.compile(r"^范围形态：\s*(首建|变更)\s*$", re.M)
DECL_COVER = re.compile(r"^覆盖度：\s*(全量|增量起步)\s*$", re.M)
DECL_BASE = re.compile(r"^基线：\s*\S.*$", re.M)
# 宽容抽取（只为报错时点名非法值——闭集不匹配时不能只说「缺声明」，那会误导排查）
DECL_ANY = re.compile(r"^(范围形态|覆盖度)：\s*(\S*)\s*$", re.M)
SHAPES = ("首建", "变更")
COVERS = ("全量", "增量起步")
# 全局 prd 的章节号：全量形态要求全在；增量起步只要「有下游消费者」的三节（契约 §3）。
ALL_SECTIONS = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一")
MIN_SECTIONS = ("五", "六", "七")
DOMAIN_SLUG = re.compile(r"`([a-z0-9][a-z0-9-]+)`")
RULE_ROW = re.compile(r"^\|\s*`?([A-Z][A-Z0-9]+-R-\d+)`?\s*\|", re.M)
# 规则 → 所属功能（契约 §4「所属功能」列；2026-09-28 补，`3509 §B109`）：功能 → 规则 → AC 链路的前一环。
RULE_FUNC_COL = "所属功能"
RULE_FUNC_ROW = re.compile(r"^\|\s*`?([A-Z][A-Z0-9]+-R-\d+)`?\s*\|[^|]*\|\s*([^|]*?)\s*\|", re.M)
# 追溯总表行：| 域 | `<file>-prd.md` | 模块 | 页面 | 功能数 | 规则数 | AC 数 | …
TRACE_ROW = re.compile(
    r"^\|\s*[^|]+\|\s*`?([a-z0-9-]+-prd\.md)`?\s*\|\s*[^|]*\|\s*[^|]*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|",
    re.M)
# 必须吞到行尾：`group(0)` 要包含「回指规则」列，否则规则→AC 判定永远为假（实测踩到）。
AC_ROW_LINE = re.compile(r"^\|\s*`?AC-[A-Z0-9]+-\d+`?\s*\|.*$", re.M)


class Result:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, check: str, status: str, detail: str = "") -> None:
        self.checks.append({"check": check, "status": status, "detail": detail})


def frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fm = {}
    for ln in text[3:end].splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            fm[k.strip()] = v.strip().strip("'\"")
    return fm


def path_candidates(text: str):
    for tok in BACKTICK.findall(text):
        t = re.sub(r":\d+(?:-\d+)?$", "", tok.strip())
        if t.startswith(("~", "http://", "https://", "{", "<", "/", "...")):
            continue
        if "{" in t or "/" not in t:
            continue
        if not (EXT_RE.search(t) or "*" in t):
            continue
        yield t


def resolves(root: Path, base: Path, target: str) -> bool:
    if "*" in target:
        return any(base.glob(target))
    return (base / target).exists()


def pending_gate(text: str) -> bool:
    """§零「待决策登记」表是否非空。

    只扫 §零 节（从该标题到下一个 `## ` 标题），并截断到「已决策」标记之前——
    避免误命中「已决策」子表与正文中其它「| 数字 |」表格行（如功能范围表）。
    """
    m = GATE_HEADING.search(text)
    if not m:
        return False
    rest = text[m.end():]
    nxt = NEXT_H2.search(rest)
    section = rest[: nxt.start()] if nxt else rest
    d = GATE_DECIDED.search(section)
    if d:
        section = section[: d.start()]
    return bool(GATE_ROW.search(section))


def read_origin(root: Path, lay=None) -> str:
    """读 `资产根/stack-profile.yaml` 顶层的 `origin:`（缺省 = greenfield，保持既有行为）。"""
    p = (lay or load_layout(root)).stack_profile
    if not p.is_file():
        return DEFAULT_ORIGIN
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if line.startswith("origin:"):
            v = line.split(":", 1)[1].strip().strip("'\"")
            return v if v in ORIGINS else DEFAULT_ORIGIN
    return DEFAULT_ORIGIN


def section_of(text: str, num: str):
    """取全局 `prd.md` 里 `## <num>、…` 到下一个 `## ` 之间的正文；不存在返回 None。"""
    m = re.search(rf"^##\s*{re.escape(num)}、[^\n]*$", text, re.M)
    if not m:
        return None
    rest = text[m.end():]
    nxt = re.search(r"^##\s", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def table_header_has(section: str, col: str) -> bool:
    """该节里是否存在某个表格，其表头含列 `col`（按单元格**全等**比较，不做子串匹配）。"""
    for ln in section.splitlines():
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if col in cells:
            return True
    return False


def table_with_all_cols(section: str, cols: tuple[str, ...]) -> bool:
    """该节里是否存在**同一张表**同时含全部 `cols`（按单元格全等比较）。

    与 `table_header_has` 的区别：后者只要求「某张表含某一列」；多列**同表**要求必须用本函数
    （例：§五 AC 表必须同表含 `AC ID` 与 `回指规则`，而「结构类 AC 清单」表只含前者）。
    """
    for ln in section.splitlines():
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(c in cells for c in cols):
            return True
    return False


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _table_rows(section: str) -> tuple[list[str], list[list[str]]]:
    """该节**首个**表格的 `(表头, 数据行)`；无表返回 `([], [])`。

    表头判定 = 下一行是分隔行（只含 `|` / `-` / `:` / 空白且含 `-`）——模板正文里的
    散文表格（§六 假设表的占位行）不影响：占位行是**数据行**，不是表头。
    """
    lines = section.splitlines()
    for i, ln in enumerate(lines):
        if not ln.startswith("|") or i + 1 >= len(lines):
            continue
        sep = lines[i + 1]
        if not (sep.startswith("|") and re.fullmatch(r"[\s|:\-]+", sep) and "-" in sep):
            continue
        rows: list[list[str]] = []
        for row in lines[i + 2:]:
            if not row.startswith("|"):
                break
            rows.append(_cells(row))
        return _cells(ln), rows
    return [], []


# AC 号**定义行**：表格首格 = 该 ID 且**至少 3 列**（`| ID | 场景 | 回指规则 |`）。
# 必须排除引用行（跨域回指 / 规则→AC 列）与结构类 AC 清单（只有 2 列）。**`[^|\n]` 不能写成 `[^|]`**
# （后者会跨行吃掉后续内容 ⇒ 把 2 列行也当 3 列）。
AC_DEF_ROW = re.compile(r"^\|\s*`?(AC-[A-Z0-9]+-\d+)`?\s*\|[^|\n]*\|[^|\n]*\|", re.M)


def ac_id_collisions(domains: list[Path]) -> list[str]:
    """AC 号**定义**跨文件 / 同文件重复（域级 PRD 是 AC 的应然资产落点）。

    只数**定义行**（`^| AC-… |`）：引用（跨域回指 / 结构类清单 / 规则→AC 列）不是撞号。
    原 `validators/validate_ledger.py` 的项目侧判据，2026-10-14 随知识库 / 台账子系统退役归位本环。
    """
    where: dict[str, list[str]] = {}
    bad: list[str] = []
    for f in domains:
        ids = AC_DEF_ROW.findall(f.read_text(encoding="utf-8", errors="replace"))
        for i in set(ids):
            where.setdefault(i, []).append(f.name)
        inner = sorted({i for i in ids if ids.count(i) > 1})
        if inner:
            bad.append(f"{f.name} 内定义重复：{'、'.join(inner)}")
    for i, files in sorted(where.items()):
        if len(files) > 1:
            bad.append(f"{i} 被 {len(files)} 份文件定义：{'、'.join(files)}")
    return bad


def validate(root: Path) -> Result:
    res = Result()
    try:
        lay = load_layout(root)
    except LayoutError as exc:
        res.add("项目布局配置", "FAIL", str(exc))
        return res
    prd_dir = lay.prd_dir
    prd = prd_dir / "prd.md"
    readme = prd_dir / "README.md"
    domains = sorted(p for p in prd_dir.glob("*-prd.md"))

    if not prd.is_file():
        if read_origin(root, lay) == "adopt":
            # `origin: adopt` 且**尚未开户**：不是失败，是「还没有可校验的资产」——
            # 旧项目接入的入场形态就是「资产为空、从第一条需求长起」（`apply/reference.md` §1 的 `adopt`）。
            res.add("门控态", "NA",
                    f"origin=adopt 且尚未开户（无 {lay.print_value('prd')}/）—— "
                    "跑 `apply adopt` 开户后再校验")
            res.add("总判定", "NA", "origin=adopt 尚未开户")
            return res
        res.add("参数1 文档头完整", "FAIL", f"缺 {lay.print_value('prd')}/prd.md")
        return res

    prd_text = prd.read_text(encoding="utf-8")

    # ---- 参数 0：目录规范（平铺契约，rings/prd/reference.md §2）
    illegal: list[str] = []
    for item in sorted(prd_dir.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_dir():
            illegal.append(f"子目录:{item.name}/")
        elif item.is_file():
            if item.suffix == ".md" and item.name not in ("prd.md", "README.md") and not item.name.endswith("-prd.md"):
                illegal.append(f"非标准文件:{item.name}")
    if illegal:
        res.add("参数0 目录规范", "FAIL",
                f"发现非契约目录层级或非标准文件：{illegal}（契约 rings/prd/reference.md §2 规定 PRD 必须为平铺目录 {lay.print_value('prd')}/prd.md 与 *-prd.md，严禁子目录）")
    else:
        res.add("参数0 目录规范", "PASS", "")

    # ---- 参数 1：文档头完整
    fm = frontmatter(prd_text)
    need_global = ("doc", "product", "version", "date", "status")
    bad = [k for k in need_global if not fm.get(k)]
    for d in domains:
        dfm = frontmatter(d.read_text(encoding="utf-8"))
        bad += [f"{d.name}:{k}" for k in
                ("doc", "domain", "domain_name", "domain_code", "version", "date", "status")
                if not dfm.get(k)]
    res.add("参数1 文档头完整", "PASS" if not bad else "FAIL", f"缺字段={bad}")

    # ---- 变更记录形态（`RFC-20261023-02` ③，2026-10-23；**独立行**：不并入 shape_issues，
    #      否则 WARN 会被参数 4 聚合为 FAIL）与 可无项显式（同 RFC ④，首版 WARN）。
    if not domains:
        res.add("变更记录形态", "NA", "无域级 PRD（门控态 / adopt 未开户）")
        res.add("可无项显式（§六）", "NA", "无域级 PRD（门控态 / adopt 未开户）")
    else:
        legacy, empty_rec, bad_shape, no_explicit = [], [], [], []
        for d in domains:
            dtext = d.read_text(encoding="utf-8")
            sec7 = section_of(dtext, "七")
            if sec7 is not None:
                header, rows = _table_rows(sec7)
                impact_idx = next((i for i, c in enumerate(header) if c.startswith("影响")), None)
                if not header:
                    # 节在、表无：legacy 同档 WARN（首版：存量 fixtures / 未迁移项目不首日红）
                    empty_rec.append(d.name)
                elif impact_idx is not None:
                    blanks = [str(n) for n, r in enumerate(rows, 1)
                              if impact_idx >= len(r) or not r[impact_idx].strip()]
                    if blanks:
                        bad_shape.append(f"{d.name} 第 {'/'.join(blanks)} 数据行「影响」为空")
                elif "变更说明" in header:
                    legacy.append(d.name)
                else:
                    bad_shape.append(f"{d.name} §七 表头不可辨={header}")
            sec6 = section_of(dtext, "六")
            if sec6 is not None:
                # 开户最小集：§六 整节不出现 = 合法（见 prd 契约 §4 开户最小集）；出现即须有结论。
                if "无" in sec6 or "不适用（理由" in sec6:
                    continue
                header6, rows6 = _table_rows(sec6)
                if not (header6 and rows6):
                    no_explicit.append(d.name)
        if bad_shape:
            res.add("变更记录形态", "FAIL", "；".join(bad_shape))
        elif legacy or empty_rec:
            parts = []
            if legacy:
                parts.append("legacy 3 列形态=" + ",".join(legacy)
                             + "（下次真实变更时迁 5 列：版本/日期/变更内容及原因/影响/结论与后续）")
            if empty_rec:
                parts.append("§七 变更记录节为空=" + ",".join(empty_rec))
            res.add("变更记录形态", "WARN", "；".join(parts))
        else:
            res.add("变更记录形态", "PASS", "5 列形态齐")
        if no_explicit:
            res.add("可无项显式（§六）", "WARN",
                    "§六 空表/空节且无显式结论=" + ",".join(no_explicit)
                    + "（写 `无` 或补假设行；翻转触发器见 `rings/prd/reference.md` §7）")
        else:
            res.add("可无项显式（§六）", "PASS", "")

    # ---- 范围形态声明 / 与 §六 表形态一致 / 最小必填集（契约 §3；结论并入参数 4）
    decl_form, decl_cover, decl_base = (DECL_FORM.search(prd_text), DECL_COVER.search(prd_text),
                                        DECL_BASE.search(prd_text))
    form = decl_form.group(1) if decl_form else None
    cover = decl_cover.group(1) if decl_cover else None
    shape_issues: list[str] = []
    if form is None:
        bad = [m for m in DECL_ANY.finditer(prd_text) if m.group(1) == "范围形态"]
        if bad:
            shape_issues.append(f"`范围形态` 取值非法：{bad[0].group(2)!r}"
                                f"（允许={'/'.join(SHAPES)}）")
        else:
            shape_issues.append("缺范围形态声明行（`范围形态：首建` 或 `范围形态：变更`，契约 §3）")
    elif form == "首建":
        if cover or decl_base:
            shape_issues.append("`首建` 不得声明 `覆盖度` / `基线`（没有基线就没有「沿用实然」）")
        cover = "全量"          # 首建隐含全量，供最小必填集使用
    else:                       # 变更
        if cover is None:
            bad = [m for m in DECL_ANY.finditer(prd_text) if m.group(1) == "覆盖度"]
            shape_issues.append(f"`变更` 形态的 `覆盖度` 取值非法：{bad[0].group(2)!r}"
                                f"（允许={'/'.join(COVERS)}）" if bad
                                else "`变更` 形态必须声明 `覆盖度：全量 | 增量起步`")
        if decl_base is None:
            shape_issues.append("`变更` 形态必须声明 `基线：<路径或版本>`")

    has_dispose = table_header_has(section_of(prd_text, "六") or "", "处置")
    if form is not None and has_dispose != (form == "变更"):
        shape_issues.append(f"§六 表形态与声明不一致：声明={form} 期望处置列={form == '变更'} "
                            f"实际={has_dispose}")

    need = MIN_SECTIONS if cover == "增量起步" else ALL_SECTIONS
    absent = [n for n in need if section_of(prd_text, n) is None]
    if absent:
        shape_issues.append(f"缺必填章节：{'/'.join(absent)}（形态={form} 覆盖度={cover}）")
    elif cover != "增量起步" and not (section_of(prd_text, "十一") or "").strip():
        shape_issues.append("`十一 修订记录` 正文为空（不设则写 `不适用（理由：…）`）")

    sec5 = section_of(prd_text, "五") or ""
    listed = sorted(set(DOMAIN_SLUG.findall(sec5)))
    disk = sorted(p.name[: -len("-prd.md")] for p in domains)
    extra = [s for s in listed if s not in disk]
    orphan = [s for s in disk if s not in listed]
    # `增量起步` 下允许「已列但无域级文件」—— 那正是「本轮未覆盖」的域，由参数 4 ⑥ 判
    # （每个未覆盖域必须在追溯总表有登记行；2026-09-28 补，`3509 §B75`）。
    if orphan or (extra and cover != "增量起步"):
        shape_issues.append(f"域清单↔域级文件不一致：清单多={extra if cover != '增量起步' else []} "
                            f"磁盘多={orphan}"
                            + ("（`增量起步` 下「已列无文件」= 未覆盖域，改由参数 4 ⑥ 判）"
                               if cover == "增量起步" else ""))

    # 门控态：§零「待决策登记」表非空（仅扫该节，排除「已决策」子表）
    gate = pending_gate(prd.read_text(encoding="utf-8"))
    if gate and domains:
        res.add("门控一致性", "FAIL", "待决策非空却产出了域级 PRD")

    # ---- 参数 2：零占位符
    hits = []
    for f in [prd, readme] + domains:
        if not f.is_file():
            continue
        for n, ln in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if ln.strip().startswith(("domain_code:", "domain:", "product:")):
                continue
            stripped = BACKTICK.sub("`x`", ln)
            for w in FORBIDDEN:
                if w in stripped:
                    hits.append(f"{f.name}:{n} 含「{w}」")
    res.add("参数2 零占位符", "PASS" if not hits else "FAIL", "；".join(hits))

    # ---- 参数 3：链接可解析
    unresolved = []
    for f in [prd, readme] + domains:
        if not f.is_file():
            continue
        for tok in path_candidates(f.read_text(encoding="utf-8")):
            base = f.parent if tok.startswith(("./", "../")) else root
            if not resolves(root, base, tok):
                unresolved.append(f"{f.name} -> {tok}")
    res.add("参数3 链接可解析", "PASS" if not unresolved else "FAIL", "；".join(sorted(set(unresolved))))

    # ---- 参数 4：追溯完整（门控态 N/A）
    if gate:
        res.add("参数4 追溯完整", "NA", "门控态：待决策非空，域级 PRD 按契约未产出")
    else:
        issues = list(shape_issues)
        for d in domains:
            t = d.read_text(encoding="utf-8")
            missing_core = [sec for sec in ("二", "四", "五") if section_of(t, sec) is None]
            if missing_core:
                issues.append(f"{d.name} 缺必填核心章节：{'/'.join(missing_core)}")
            if STRUCT_LIST_HEAD not in t:
                issues.append(f"{d.name} 缺「{STRUCT_LIST_HEAD}」小节（契约 §4 五，必填可为空表）")
            fns, rs, acs = set(FN_RE.findall(t)), set(R_RE.findall(t)), set(AC_RE.findall(t))
            if not fns or not rs or not acs:
                issues.append(f"{d.name} 缺 FN/R/AC 编号")
            ref_rules = set(R_RE.findall(t))
            if rs and not ref_rules:
                issues.append(f"{d.name} AC 未回指规则")
            # 结构类 AC 清单自洽（契约 §4「五」）：清单里的每个 ID 必须在本文档的 AC 表里存在。
            # 清单是 E2E 环「零证据用例须挂结构类 AC」那道门的**唯一输入** ⇒ 它漂了，门就静默失效。
            if STRUCT_LIST_HEAD in t:
                head, tail = t.split(STRUCT_LIST_HEAD, 1)
                cut = re.search(r"^#{1,4} ", tail, re.M)
                listed = set(STRUCT_AC_RE.findall(tail[:cut.start()] if cut else tail))
                # 基准只取**清单之前**的正文（AC 表所在处）—— 拿全文找会把自己也算进来，
                # 这样「清单 ⊆ 全文」永远成立 = 一道永远不咬的门（实测踩到）。
                declared = set(AC_RE.findall(head))
                ghost = sorted(a for a in listed if a not in declared)
                if ghost:
                    issues.append(f"{d.name} 结构类清单引用了不存在的 AC：{ghost}")
            # 不可验 AC 清单自洽（契约 §4「五」，2026-10-12 补，`3509 §B201-3`）：与结构类同款——
            # 清单是 E2E「AC 反向覆盖」门的豁免输入 ⇒ 幽灵豁免（引用了本域不存在的 AC）会让
            # 一道不该豁免的 AC 静默逃过覆盖门 ⇒ FAIL。**只扫表格行**（清单 = 表格；
            # 说明散文里的 AC 提及——如「先例 `AC-MIXING-001`」——不构成清单条目）。
            if UNVER_LIST_HEAD in t:
                head, tail = t.split(UNVER_LIST_HEAD, 1)
                cut = re.search(r"^#{1,4} ", tail, re.M)
                zone = tail[:cut.start()] if cut else tail
                listed = set(m.group(1) for m in
                             re.finditer(r"^\|\s*`?(AC-[A-Z0-9]+-\d{3})`?\s*\|", zone, re.M))
                declared = set(AC_RE.findall(head))
                ghost = sorted(a for a in listed if a not in declared)
                if ghost:
                    issues.append(f"{d.name} 不可验清单引用了不存在的 AC：{ghost}")
            # §五 AC 表列头（契约 §5 三列形态；2026-09-28 补，`3509 §B74`）：表列是契约承诺，
            # 无判据时文本与产物会长期不一致（实测：契约曾要求 6 列、7 份产物全 3 列，无人发现）。
            sec5d = section_of(t, "五") or ""
            if not table_with_all_cols(sec5d, ("AC ID", "回指规则")):
                issues.append(f"{d.name} §五 缺三列 AC 表（需同表含 `AC ID` 与 `回指规则`）")
            elif table_with_all_cols(sec5d, ("样例类型",)):
                issues.append(f"{d.name} §五 AC 表含 `样例类型` 列（已移交 E2E 环，`3509 §B74`）")
            # 规则→AC 覆盖（契约 §5「双向追溯」，2026-09-26 补）：每条规则至少被一条 AC 回指。
            # 原「参数 5 Waste Test」的第一条判据即此项 —— 它此前从未被实现（恒 PASS 的空门）。
            rules = {m.group(1) for m in RULE_ROW.finditer(t)}
            acrows = "\n".join(m.group(0) for m in AC_ROW_LINE.finditer(t))
            uncited = sorted(r for r in rules
                             if not re.search(r"\b" + re.escape(r) + r"\b", acrows))
            if uncited:
                issues.append(f"{d.name} 规则无 AC 回指：{uncited}")
            # 功能 → 规则 链路（契约 §6 双向追溯 + §4 `所属功能` 列；2026-09-28 补，`3509 §B109`）：
            # ① 每条规则在 §四 声明它服务哪些功能；② 每个功能被 ≥1 条规则服务。两条合起来，
            # 才让「每个功能至少有一条 AC」可机器判（功能 → 规则 → AC 由上面的「规则被 AC 回指」接上）。
            code_m = re.search(r"^domain_code:\s*([A-Z0-9]+)", t, re.M)
            code = code_m.group(1) if code_m else ""
            # 功能号只能取自 **§二 功能清单小节** —— 从全文取就是自证：幽灵号写在规则行里，
            # 它也出现在全文里，幽灵检查于是永远不咬（实测踩到，属「恒 PASS 空门」一族）。
            fn_sec = ""
            msec = re.search(r"^#{1,4}[^\n]*功能清单[^\n]*$", t, re.M)
            if msec:
                tail = t[msec.end():]
                cut = re.search(r"^#{1,4} ", tail, re.M)
                fn_sec = tail[:cut.start()] if cut else tail
            decl_fn = set(re.findall(rf"FN-{code}-\d+", fn_sec)) if code else set(FN_RE.findall(fn_sec))
            if not msec and (code and re.search(rf"FN-{code}-\d+", t)):
                issues.append(f"{d.name} 缺 §二 功能清单小节：功能号无权威落点")
            frow: dict[str, set[str]] = {}
            no_func: list[str] = []
            ghost: list[str] = []
            own_rules = {m.group(1) for m in RULE_ROW.finditer(t)
                         if not code or m.group(1).startswith(code + "-")}
            col_missing = bool(own_rules) and RULE_FUNC_COL not in t
            if col_missing:
                issues.append(f"{d.name} 规则表缺「{RULE_FUNC_COL}」列")
            else:
                # 契约 rings/prd/reference.md §四：所属功能必须在第 3 列（规则 ID ｜ 规则内容 ｜ 所属功能 ｜ …）
                sec4 = section_of(t, "四") or t
                header_match = re.search(r"^\|\s*([^|\n]+\|)+", sec4, re.M)
                wrong_col_order = False
                if header_match:
                    cols = [c.strip().strip("`") for c in header_match.group(0).split("|")[1:-1]]
                    if RULE_FUNC_COL in cols:
                        col_idx = cols.index(RULE_FUNC_COL) + 1  # 1-based
                        if col_idx != 3:
                            wrong_col_order = True
                            issues.append(
                                f"{d.name} 规则表列序不符契约 §四：「{RULE_FUNC_COL}」应在第 3 列（规则 ID ｜ 规则内容 ｜ 所属功能 ｜ …），当前在第 {col_idx} 列"
                            )
                if not wrong_col_order:
                    for m in RULE_FUNC_ROW.finditer(t):
                        rid, cells = m.group(1), set(FN_RE.findall(m.group(2)))
                        if not cells:
                            no_func.append(rid)
                            continue
                        ghost += [f"{rid}→{x}" for x in cells if x not in decl_fn]
                        frow[rid] = cells
                    if no_func:
                        issues.append(f"{d.name} 规则未声明所属功能：{sorted(no_func)[:8]}")
                    if ghost:
                        issues.append(f"{d.name} 所属功能引用了不存在的功能：{ghost[:8]}")
            if decl_fn and not own_rules:
                issues.append(f"{d.name} 缺 §四 规则表：功能无法与规则/AC 建链")
            elif not col_missing and not wrong_col_order:
                served = set().union(*frow.values()) if frow else set()
                orphan_fn = sorted(f for f in decl_fn if f not in served)
                if orphan_fn:
                    issues.append(f"{d.name} 功能无规则服务：{orphan_fn[:8]}")

        # AC 跨域唯一性检查（Phase 0：B209-1 / 3507 BT，只检查各域主定义的本域 AC，跨域引用不计入）
        seen_acs: dict[str, str] = {}
        dup_acs: list[str] = []
        for d in domains:
            t = d.read_text(encoding="utf-8")
            cm = re.search(r"^domain_code:\s*([A-Z0-9]+)", t, re.M)
            c = cm.group(1) if cm else ""
            if not c:
                continue
            # 本域声明的 AC（AC-{domain_code}-\d+）
            own_acs = set(re.findall(rf"AC-{c}-\d+", t))
            for ac in own_acs:
                if ac in seen_acs:
                    dup_acs.append(f"{ac} 在 {seen_acs[ac]} 与 {d.name} 重复")
                else:
                    seen_acs[ac] = d.name
        if dup_acs:
            issues.append(f"本域 AC 编号跨域重复（必须全局唯一）：{dup_acs[:5]}")

        # 追溯总表行形态 + 未覆盖登记（契约 §7 参数 4 ⑥；2026-09-28 补，`3509 §B75`）：
        # `增量起步` 下没有域级文件的域，必须在总表里有一行合法的「未覆盖（沿用实然）」——
        # 否则「本轮没覆盖哪些域」没有唯一登记点（下一条需求接手时看不出上一轮的边界）。
        # 结论并入本项（不另开一行）：「域没登记」就是「追溯不完整」，两个报告面重叠会变噪声（`§106`）。
        # **触发条件 = 真的有未覆盖域**（`extra` 非空）：没有未覆盖域时就不需要登记点，
        # 否则会把「未建 README 但也没未覆盖域」判成缺陷（噪声，不是守备）。
        if cover == "增量起步" and extra:
            tr2 = readme.read_text(encoding="utf-8") if readme.is_file() else ""
            sec2 = section_of(tr2, "二") or ""
            rows2 = [ln for ln in sec2.splitlines() if ln.startswith("|")]
            data2 = [ln for ln in rows2
                     if "域级文件" not in ln and not re.fullmatch(r"\|[\s\-:|]+\|", ln.strip())]
            bad_rows: list[str] = []
            uncovered = 0
            for ln in data2:
                if TRACE_ROW.match(ln):
                    continue
                if "—（未覆盖）" in ln and "未覆盖（沿用实然）" in ln:
                    uncovered += 1
                    continue
                bad_rows.append(ln.strip()[:60])
            if not data2:
                issues.append("有未覆盖域但追溯总表无数据行（未覆盖域没有登记点）")
            if bad_rows:
                issues.append(f"追溯总表行形态非法（需「已覆盖」或「未覆盖（沿用实然）」）：{bad_rows[:3]}")
            if uncovered < len(extra):
                issues.append(f"未覆盖行数 {uncovered} < 缺域级文件的域数 {len(extra)}"
                              "（每个未覆盖域都要有登记行）")

        res.add("参数4 追溯完整", "PASS" if not issues else "FAIL", "；".join(issues))

        # 追溯总表计数对账（契约 §7 参数 4 ⑤；2026-09-28 补，`3509 §B109`）：表里的数字是人
        # 维护的，没有判据就会静默过期（实测七域全过期）。口径 = 按该域 `domain_code` 去重。
        trace = lay.prd_dir / "README.md"
        if trace.is_file():
            tr_text = trace.read_text(encoding="utf-8")
            mism = []
            for m in TRACE_ROW.finditer(tr_text):
                fname = m.group(1)
                nf, nr, na = int(m.group(2)), int(m.group(3)), int(m.group(4))
                p = lay.prd_dir / fname
                if not p.is_file():
                    continue
                dt = p.read_text(encoding="utf-8")
                cm = re.search(r"^domain_code:\s*([A-Z0-9]+)", dt, re.M)
                if not cm:
                    continue
                c = cm.group(1)
                real = (len(set(re.findall(rf"FN-{c}-\d+", dt))),
                        len(set(re.findall(rf"{c}-R-\d+", dt))),
                        len(set(re.findall(rf"AC-{c}-\d+", dt))))
                if real != (nf, nr, na):
                    mism.append(f"{fname} 表记 {nf}/{nr}/{na} ≠ 实际 {real[0]}/{real[1]}/{real[2]}")
            if TRACE_ROW.search(tr_text):
                res.add("参数4 追溯总表计数", "PASS" if not mism else "FAIL", "；".join(mism))


    # ---- 域间依赖（`depends_on` ⇔ 全局 §五 mermaid 实线边集；2026-10-04 补，`3509 §B186-1`）
    # 真相源 = 域级 frontmatter `depends_on`（`shared/single-source.md`）；语义 = **实现前置依赖**，
    # 只含全局 `prd.md` §五 mermaid 的**实线**（`-->`）；虚线（`-.->` = 增强链路 / 数据回流）不入判据。
    # 三判据：悬空引用 / 实线子图成环 / 与实线边集不一致——均 FAIL（收敛后应零红；
    # 2026-10-04 实测收敛前 5/7 域三处互相矛盾）。
    d_slug: dict[Path, str] = {}
    name2slug: dict[str, str] = {}
    dep: dict[str, set[str]] = {}
    for p in domains:
        dt = p.read_text(encoding="utf-8")
        slug = _fm_scalar(dt, "domain")
        if not slug:
            continue
        d_slug[p] = slug
        nm = _fm_scalar(dt, "domain_name")
        if nm:
            name2slug[nm] = slug
        # 裸 slug 节点（`ops-console --> platform`，无 `id[中文名]`）也认：域 slug 本身就是
        # 推导键。旧实现只认 `id[标签]` ⇒ 裸 slug 退化成 `?slug` ⇒ 边集比对永远失败。
        name2slug.setdefault(slug, slug)
        md = re.search(r"^depends_on:\s*\[([^\]]*)\]", dt, re.M)
        dep[slug] = {x.strip().strip("\"'“”") for x in (md.group(1).split(",") if md else [])
                     if x.strip()}
    gfile = lay.prd_dir / "prd.md"
    gtext = gfile.read_text(encoding="utf-8") if gfile.is_file() else ""
    gsec = re.search(r"^##\s*五、功能架构\s*$(.*?)(?=^##\s|\Z)", gtext, re.S | re.M)
    gmer = re.search(r"```mermaid(.*?)```", gsec.group(1), re.S) if gsec else None
    if not dep or not gmer:
        res.add("参数4 域间依赖", "N/A",
                "无域级 `depends_on` 声明，或全局 §五 无 mermaid 域间关系图")
    else:
        body = gmer.group(1)
        labels = dict(_LABEL_RE.findall(body))
        unresolved: set[str] = set()

        def _slug(node: str) -> str:
            nm = labels.get(node, node)
            s = name2slug.get(nm)
            if s is None:
                unresolved.add(nm)
                return "?" + nm
            return s

        solid = {(_slug(a), _slug(b)) for a, b in _solid_edges(body)}
        issues: list[str] = []
        dangling = sorted({(d, x) for d, s in dep.items() for x in s if x not in dep})
        if dangling:
            issues.append("悬空引用=" + ",".join(f"{d}→{x}" for d, x in dangling[:6]))
        adj: dict[str, list[str]] = {}
        for a, b in solid:
            adj.setdefault(a, []).append(b)
        color: dict[str, int] = {}
        cycles: list[str] = []

        def _dfs(u: str, stack: list[str]) -> None:
            color[u] = 1
            for v in adj.get(u, []):
                if color.get(v) == 1:
                    cycles.append("→".join(stack[stack.index(v):] + [v]))
                elif color.get(v) is None:
                    _dfs(v, stack + [v])
            color[u] = 2

        for n in list(adj):
            if color.get(n) is None:
                _dfs(n, [n])
        if cycles:
            issues.append("实线成环=" + " | ".join(cycles[:3]))
        mer_dep: dict[str, set[str]] = {}
        for a, b in solid:
            mer_dep.setdefault(b, set()).add(a)
        mism = [d for d in sorted(set(dep) | set(mer_dep))
                if dep.get(d, set()) != mer_dep.get(d, set())]
        if mism:
            # F39：两类根因分开报——「标签未解析」是写法/取名问题（改 mermaid 标签或
            # `domain_name` 即可），「边集不一致」是真·依赖声明与图不符。混在一起报会让人
            # 以为依赖写错了，而实际只是域名对不上（旧文案只给 `?中文名` 对比，读者无从判断）。
            if unresolved:
                issues.append(
                    "标签未解析=" + ",".join(sorted(unresolved)[:6])
                    + "（mermaid 节点标签与任何域级 `domain_name` 都不逐字相同——"
                      "要么该域级 PRD 缺失，要么标签写的是简称/别名）")

            def _resolved_clean(d: str) -> bool:
                """该域两侧有没有「标签未解析」的痕迹（`?` 前缀是内部标记）。

                `?` 本身也是键——不能把 `?<名>` 这条算成「真·边集不一致」，那正是旧文案
                让读者困惑的形态（两个都不存在的域名的对比）。
                """
                return (not d.startswith("?")
                        and not any(x.startswith("?") for x in mer_dep.get(d, set())))

            real = [d for d in mism if _resolved_clean(d)]
            if real or not unresolved:
                issues.append("与实线边集不一致=" + "; ".join(
                    f"{d}(frontmatter={sorted(dep.get(d, set()))} ≠ 实线={sorted(mer_dep.get(d, set()))})"
                    for d in (real or mism)[:4]))
        res.add("参数4 域间依赖", "PASS" if not issues else "FAIL", "；".join(issues))

    # ---- AC 号唯一（域级 PRD 内 AC 号跨文件 / 同文件不得重复；2026-10-14 归位自 validate_ledger）
    ac_bad = ac_id_collisions(domains)
    res.add("AC 号唯一", "FAIL" if ac_bad else "PASS",
            "；".join(ac_bad) if ac_bad else "域级 PRD 内 AC 号无跨文件 / 同文件重复")

    # ---- 判定
    statuses = [c["status"] for c in res.checks]
    if "FAIL" in statuses:
        status = "FAIL"
    else:
        applicable = [s for s in statuses if s in ("PASS", "WARN")]
        if applicable and all(s == "PASS" for s in applicable):
            status = "PASS"
        elif applicable:
            status = "WARN"
        else:
            status = "PASS"
    res.checks.append({"check": "总判定", "status": status, "detail": f"gate={gate} 域级文件={len(domains)}"})
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    res = validate(root)
    status = next((c["status"] for c in reversed(res.checks) if c["check"] == "总判定"), "FAIL")
    if args.json:
        print(json.dumps({"ok": status != "FAIL", "status": status,
                          "root": str(root), "checks": res.checks}, ensure_ascii=False, indent=2))
    else:
        print(f"validate_prd @ {root}")
        for c in res.checks:
            line = f"  [{c['status']:<4}] {c['check']}"
            if c["detail"]:
                line += f" —— {c['detail']}"
            print(line)
        print(status)
    return 1 if status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
