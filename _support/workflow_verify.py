#!/usr/bin/env python3
"""需求条目覆盖矩阵的 verify 期判据（#71/#72/#73，2026-11-21；落点模式 RFC-20261122-03）。

纪律面 WARN 起步（升格 FAIL 另案）：`atlas workflow verify` 在独立审查通过后调用
`coverage_matrix_findings`（逐卡）与 `requirement_root_findings`（跨卡落点对账），
把条目覆盖缺口以 WARN 行打到 stderr，不改退出码。
契约落点：`shared/single-source.md` §4「需求原文优先序与条目覆盖」。

机制文档机器面（RFC-20261122-04 + RFC-20261123-01 升格）：触及面已升格为
**申报判决门**（`mechanism_declaration_verdict`，verify 前置判定带 FAIL rc1+扣预算，
触及未跟改未申报 / 词表非法 glob；申报面 = 卡目录 `mech-declares.md`）；
`mechanism_doc_findings` 只剩审查后 WARN 提示族残部（疑似死 paths / 词表点名 /
死测试锚——与缺口族 #71–#74 分族；契约落点 `shared/single-source.md` §1
「机制叙事文档」行与 §4 提示族条款）。

判据：
- 卡目录无 `requirement-items.md` ⇒ 非需求驱动卡，沉默（不制造假阳性）；
- 直填模式（表头含「原文」）：既有判据不变——矩阵缺席 / 零数据行未声明豁免 /
  格留空 / 词表外 / UNRESOLVED / 条目⇔矩阵双向差集 ⇒ WARN；
- 落点模式（表头含「来源」，RFC-20261122-03）：卡条目表 = 领取引用表，ID = 落点条目
  ID、来源 = `<落点路径>#<落点ID>`；零领取未声明豁免 / 来源语法非法 / 引用 ID 与
  本行 ID 不一致 ⇒ WARN；矩阵判据复用（行 = 领取 ID）；
- `requirement_root_findings`（跨卡）：落点 `items.md` 缺席 / 零条目 / 漏领（落点条目
  无任何卡领取）/ 幽灵引用（引用 ID 不在落点条目表）/ 状态机不一致（有卡领取但
  状态候选或缺失；关联卡全部收口但状态未推进已收口；已拆但无关联卡）⇒ WARN。

条目↔卡语义 = at-least-once 共担合法（同一条目跨卡实现是常态），按覆盖性不按计数。
纯标准库。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from _support.layout import LayoutError
from _support.workflow_plan import (
    REQUIREMENT_TYPES, is_archived_task_dir, normalize_requirement_ref,
    read_requirement_fields, requirement_relation_findings, requirement_type,
    resolve_requirement_root, strip_fences,
)

ITEMS_FILE = "requirement-items.md"
MATRIX_FILE = "coverage-matrix.md"
MATRIX_COLUMNS = ("PRD", "设计文档", "实现", "E2E")
NO_REQUIREMENT_MARKER = "无外部需求原件"
# 落点模式（RFC-20261122-03）
CLAIM_NONE_MARKER = "不承接需求条目"
REQUIREMENT_DOC_FILE = "requirement.md"
REQUIREMENT_ROOT_ITEMS_FILE = "items.md"
SOURCE_REF_RE = re.compile(r"^(?P<path>\S+)#(?P<id>\S+)$")


def first_table(text: str, header_needles: tuple[str, ...]) -> list[list[str]] | None:
    """第一张表头含任一 needle 的 markdown 表（header 在首行）；无 ⇒ None。"""
    lines = strip_fences(text).splitlines()
    for start, line in enumerate(lines):
        if not line.lstrip().startswith("|") or not any(n in line for n in header_needles):
            continue
        rows: list[list[str]] = []
        for raw in lines[start:]:
            s = raw.strip()
            if not s.startswith("|"):
                if rows:
                    break
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue  # 分隔行
            rows.append(cells)
        return rows if rows else None
    return None


def read_requirement_status(req_root: Path) -> str | None:
    """读需求落点首部状态字段；围栏示例不参与。"""
    return read_requirement_fields(req_root).get("状态")


def _parse_claim_rows(
    rows: list[list[str]], items_text: str
) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """落点模式卡条目表（领取引用表）解析：返回 (领取 ID, (路径, ID) 引用, findings)。"""
    findings: list[str] = []
    src_idx = next(i for i, c in enumerate(rows[0]) if "来源" in c)
    ids: list[str] = []
    refs: list[tuple[str, str]] = []
    for row_no, row in enumerate(rows[1:], 1):
        row_id = row[0].strip() if row else ""
        src = row[src_idx].strip() if len(row) > src_idx else ""
        if not row_id:
            findings.append(f"{ITEMS_FILE} 第 {row_no} 行缺条目 ID（落点模式：ID = 落点条目 ID）")
            continue
        m = SOURCE_REF_RE.match(src)
        if not m:
            findings.append(
                f"{ITEMS_FILE} 第 {row_no} 行（{row_id}）「来源」列非法：{src!r}"
                "（须为 <落点路径>#<落点ID> 引用，不复制正文——RFC-20261122-03）")
            continue
        if m.group("id") != row_id:
            findings.append(
                f"{ITEMS_FILE} 第 {row_no} 行（{row_id}）「来源」引用 ID 不一致：{m.group('id')!r}")
            continue
        ids.append(row_id)
        refs.append((m.group("path"), m.group("id")))
    if not ids and CLAIM_NONE_MARKER not in items_text:
        findings.append(
            f"{ITEMS_FILE} 零领取行且未声明「{CLAIM_NONE_MARKER}」："
            "落点模式卡须从落点 items.md 写引用行领取（RFC-20261122-03）")
    return ids, refs, findings


def coverage_matrix_findings(task_dir: Path) -> list[str]:
    """返回条目覆盖缺口清单（空 = 干净或非需求驱动卡）；调用方以 WARN 呈现。"""
    task_dir = Path(task_dir)
    items_path = task_dir / ITEMS_FILE
    if not items_path.is_file():
        return []  # plan 未带 --requirement 的卡：不判，不制造假阳性

    findings: list[str] = []
    items_text = strip_fences(items_path.read_text(encoding="utf-8", errors="replace"))
    items_rows = first_table(items_text, ("原文", "来源"))
    claim_mode = bool(items_rows) and any("来源" in c for c in items_rows[0])
    if claim_mode:
        item_ids, _refs, claim_findings = _parse_claim_rows(items_rows, items_text)
        findings.extend(claim_findings)
    else:
        item_ids = [r[0].strip() for r in items_rows[1:] if r and r[0].strip()] \
            if items_rows else []
        if not item_ids and NO_REQUIREMENT_MARKER not in items_text:
            findings.append(
                f"{ITEMS_FILE} 零数据行且未声明「{NO_REQUIREMENT_MARKER}」："
                "条目枚举没做（#72 开工前置）")

    matrix_path = task_dir / MATRIX_FILE
    if not matrix_path.is_file():
        findings.append(
            f"{MATRIX_FILE} 不存在：需求条目覆盖矩阵未建"
            "（每格 覆盖（位置）/ 不涉及（理由）/ UNRESOLVED 三选一）")
        return findings

    matrix_rows = first_table(
        matrix_path.read_text(encoding="utf-8", errors="replace"), MATRIX_COLUMNS)
    if matrix_rows is None:
        findings.append(
            f"{MATRIX_FILE} 无合法表（表头须含 {' / '.join(MATRIX_COLUMNS)}）")
        return findings
    header = matrix_rows[0]
    col_idx: dict[str, int] = {}
    for name in MATRIX_COLUMNS:
        idx = next((i for i, c in enumerate(header) if name in c), None)
        if idx is None:
            findings.append(f"{MATRIX_FILE} 表头缺「{name}」列：{header}")
            return findings
        col_idx[name] = idx

    matrix_ids: list[str] = []
    unresolved: list[str] = []
    for row_no, row in enumerate(matrix_rows[1:], 1):
        row_id = row[0].strip() if row else ""
        if not row_id:
            findings.append(f"{MATRIX_FILE} 第 {row_no} 行缺条目 ID")
            continue
        matrix_ids.append(row_id)
        for name in MATRIX_COLUMNS:
            idx = col_idx[name]
            value = row[idx].strip() if len(row) > idx else ""
            if not value:
                findings.append(
                    f"{MATRIX_FILE} 第 {row_no} 行（{row_id}）「{name}」列留空："
                    "覆盖（位置）/ 不涉及（理由）/ UNRESOLVED 三选一")
            elif "UNRESOLVED" in value:
                unresolved.append(f"第 {row_no} 行（{row_id}）「{name}」")
            elif not (value.startswith("覆盖") or value.startswith("不涉及")):
                findings.append(
                    f"{MATRIX_FILE} 第 {row_no} 行（{row_id}）「{name}」列值非法：{value!r}"
                    "（只认 覆盖（位置）/ 不涉及（理由）/ UNRESOLVED）")
    if unresolved:
        findings.append(
            f"{MATRIX_FILE} 存在 UNRESOLVED（待裁决面）：{'；'.join(unresolved)}")
    matrix_id_set = set(matrix_ids)
    missing = [i for i in item_ids if i not in matrix_id_set]
    if missing:
        findings.append(f"{MATRIX_FILE} 缺条目行（漏覆盖）：{'、'.join(missing)}")
    item_id_set = set(item_ids)
    ghost = [i for i in matrix_ids if i not in item_id_set]
    if ghost:
        findings.append(f"{MATRIX_FILE} 行 ID 不在条目表（幽灵行）：{'、'.join(ghost)}")
    return findings


def requirement_root_findings(root: Path) -> list[str]:
    """需求落点 ⇄ Σ卡领取 覆盖性对账 + 状态机一致性（RFC-20261122-03，WARN 纪律面）。

    扫描 `.atlas/tasks/`（含 archive）全部 task.json 中带 `requirement_root` 的卡，
    按落点聚合领取 ID 集合（只认语法合法的引用行；非法单元格由逐卡
    `coverage_matrix_findings` 负责），再对每个落点判：items.md 缺席 / 零条目 /
    漏领 / 幽灵引用 / 状态机不一致。损坏卡在此沉默（损坏本身由 load_tasks 面负责）。
    """
    root = Path(root)
    tasks_root = root / ".atlas" / "tasks"
    if not tasks_root.is_dir():
        return []

    per_root: dict[str, dict] = {}
    ledger_findings: list[str] = []
    seen_ids: dict[str, str | None] = {}
    duplicate_roots: set[str] = set()
    ledger_invalid = False
    for p in sorted(tasks_root.rglob("task.json")):
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            ledger_findings.append(f"任务账本不可读：{p}（{exc}）")
            ledger_invalid = True
            continue
        if not isinstance(meta, dict) or not meta.get("id"):
            ledger_findings.append(f"任务卡缺少 id：{p}")
            ledger_invalid = True
            continue
        task_id = str(meta["id"])
        raw_root = meta.get("requirement_root")
        req_root = (normalize_requirement_ref(root, raw_root)
                    if isinstance(raw_root, str) and raw_root.strip() else None)
        if task_id in seen_ids:
            prior_root = seen_ids[task_id]
            duplicate_roots.update(r for r in (prior_root, req_root) if r)
            ledger_findings.append(
                f"任务 ID 重复：{task_id}（{prior_root or '无落点'} / {req_root or '无落点'}），"
                "拒绝判定全部收口")
            ledger_invalid = True
        else:
            seen_ids[task_id] = req_root
        if req_root is None:
            continue
        entry = per_root.setdefault(
            req_root, {"claimed": set(), "cards": [], "any_claim": False,
                       "findings": []})
        t_dir = p.parent
        items_path = t_dir / ITEMS_FILE
        if items_path.is_file():
            rows = first_table(
                strip_fences(items_path.read_text(encoding="utf-8", errors="replace")),
                ("来源",))
            if rows and any("来源" in c for c in rows[0]):
                src_idx = next(i for i, c in enumerate(rows[0]) if "来源" in c)
                for r in rows[1:]:
                    if not (r and r[0].strip()):
                        continue
                    entry["any_claim"] = True
                    m = SOURCE_REF_RE.match(r[src_idx].strip() if len(r) > src_idx else "")
                    if m:
                        source_root = normalize_requirement_ref(root, m.group("path"))
                        if source_root == req_root:
                            entry["claimed"].add(m.group("id"))
                        else:
                            entry["findings"].append(
                                f"任务 {meta.get('id', '?')} 领取来源路径 {source_root!r} "
                                f"与 requirement_root {req_root!r} 不一致：拒绝跨落点冒领")
        archived = (is_archived_task_dir(tasks_root, p.parent)
                    and p.parent.name == meta.get("id"))
        entry["cards"].append(
            {"id": meta.get("id", "?"), "archived": archived,
             "status": meta.get("status", "")})

    findings: list[str] = ledger_findings
    for req_root_rel, entry in per_root.items():
        try:
            candidate = (root / req_root_rel).resolve()
        except (OSError, RuntimeError) as exc:
            findings.append(f"需求落点 {req_root_rel} 路径不可解析：{exc}")
            continue
        if root.resolve() not in candidate.parents and candidate != root.resolve():
            findings.append(
                f"需求落点 {req_root_rel} 路径越界（项目根外）：领取引用须指向项目根内落点")
            continue
        try:
            req_dir = resolve_requirement_root(root, req_root_rel)
        except (LayoutError, OSError) as exc:
            findings.append(f"需求落点 {req_root_rel} 无法解析：{exc}")
            continue
        if req_dir is None:
            findings.append(
                f"需求落点 {req_root_rel} 非法或不存在（须为配置资产根内唯一 requirements/<slug>）："
                "检查 slug 是否复用、归档是否完整或路径是否越界")
            continue
        findings.extend(entry["findings"])
        try:
            relation_findings = requirement_relation_findings(root, req_dir)
            findings.extend(relation_findings)
        except OSError as exc:
            findings.append(f"需求落点 {req_root_rel} 元数据不可读：{exc}")
            continue
        items_file = req_dir / REQUIREMENT_ROOT_ITEMS_FILE
        if not items_file.is_file():
            findings.append(
                f"需求落点 {req_root_rel} 缺 {REQUIREMENT_ROOT_ITEMS_FILE}："
                "条目正文唯一住址未建（RFC-20261122-03）")
            continue
        try:
            rows = first_table(
                strip_fences(items_file.read_text(encoding="utf-8", errors="replace")),
                ("原文",))
        except OSError as exc:
            findings.append(f"需求落点 {req_root_rel} 条目表不可读：{exc}")
            continue
        root_ids = [r[0].strip() for r in rows[1:] if r and r[0].strip()] if rows else []
        if not root_ids:
            findings.append(
                f"需求落点 {req_root_rel} 的 {REQUIREMENT_ROOT_ITEMS_FILE} 零条目："
                "先在落点逐条枚举（items.md 是条目正文唯一住址）")
            continue
        claimed = entry["claimed"]
        if not claimed:
            findings.append(
                f"需求落点 {req_root_rel} 无任何卡领取条目（共 {len(root_ids)} 条）："
                "先拆卡并写领取引用行")
        else:
            missing = [i for i in root_ids if i not in claimed]
            if missing:
                findings.append(
                    f"需求落点 {req_root_rel} 漏领条目（无任何卡领取）：{'、'.join(missing)}")
            ghost = sorted(claimed - set(root_ids))
            if ghost:
                findings.append(
                    f"需求落点 {req_root_rel} 幽灵引用（ID 不在 items.md）：{'、'.join(ghost)}")
        try:
            status = read_requirement_status(req_dir)
            kind = requirement_type(req_dir)
        except OSError as exc:
            findings.append(f"需求落点 {req_root_rel} 元数据不可读：{exc}")
            continue
        valid_type = kind in REQUIREMENT_TYPES
        if not valid_type:
            findings.append(f"需求落点 {req_root_rel} 类型非法：{kind!r}，不推进收口")
        if status not in ("已确认", "已拆", "已收口"):
            findings.append(
                f"需求落点 {req_root_rel} 状态 = {status or '缺失'} 但已有卡领取："
                "先过确认门（候选 → 已确认）")
        cards = entry["cards"]
        all_done = (valid_type and not ledger_invalid and not entry["findings"]
                    and not relation_findings and req_root_rel not in duplicate_roots
                    and bool(cards) and all(
                        c["archived"] and c["status"] == "completed" for c in cards))
        if all_done and status != "已收口":
            if kind == "缺陷":
                findings.append(
                    f"需求落点 {req_root_rel} 关联卡已全部归档且 completed，状态 = {status or '缺失'}："
                    "推进为「已收口」；仅当产品事实缺失或错误时回写")
            else:
                findings.append(
                    f"需求落点 {req_root_rel} 关联卡已全部归档且 completed，状态 = {status or '缺失'}："
                    "推进为「已收口」并按域沉淀回产品事实（RFC-20261122-03 B5）")
    return findings


# ------------------------------------------------- 机制文档机器面（RFC-20261122-04）

MECHANISM_PATHS_KEY = "mechanism-paths"
MECHANISM_PENDING = "pending"  # 冷启动豁免标记（评审 s1）：新篇首跑不判
MECHANISM_WARN_CAP = 5  # 提示族点名上限（评审 M3）：触及提示退役后由死 paths/死锚族沿用语义

_MECH_FM_RE = re.compile(r"\A\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)
_MECH_KEY_RE = re.compile(r"^mechanism-paths[：:]\s*(.*)$")
_MECH_ITEM_RE = re.compile(r"^-\s+(.+)$")
_MECH_DECLARE_RE = re.compile(r"^-\s+(\S+):\s*not-involved:\s*(.*)$")


def _mech_glob_wellformed(glob: str) -> bool:
    """两档词表（RFC-20261123-01 §2.3）：字面路径（无 `*`/`?`）或 `dir/**`
    （`**` 恰在末尾且前缀字面）。裸 `**`、`**/x`、中段 `**`、单星、`?` 均非法。"""
    if "*" not in glob and "?" not in glob:
        return True
    return (glob.endswith("/**") and len(glob) > 3
            and "*" not in glob[:-3] and "?" not in glob[:-3])
_MECH_PRUNE_DIRS = {".git", "node_modules", "__pycache__", ".atlas", ".atlas-run",
                    ".adapter-out", "dist", "build"}


def _mech_glob_regex(glob: str) -> re.Pattern[str]:
    """机制篇 glob → 正则；语义对齐 `_support/workflow_context._glob_regex`
    （`**` 跨目录、`a/**` 允许零段；单星由词表判据先行拒绝，此处仅为引擎一致性测试保留解析）。"""
    g = str(glob).strip().replace("\\", "/")
    while g.startswith("./"):
        g = g[2:]
    if g.endswith("/"):
        g += "**"
    out: list[str] = []
    i, n = 0, len(g)
    while i < n:
        ch = g[i]
        if ch == "*":
            if i + 1 < n and g[i + 1] == "*":
                if i + 2 < n and g[i + 2] == "/":
                    out.append("(?:.*/)?")
                    i += 3
                elif out and out[-1] == "/":
                    out.pop()
                    out.append("(?:/.*)?")
                    i += 2
                else:
                    out.append(".*")
                    i += 2
            else:
                out.append("[^/]*")
                i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("".join(out))


def _mech_hit(path: str, glob: str) -> bool:
    """改动文件是否命中机制篇 glob；无通配符的字面目录按前缀命中（同 hit_path 语义）。"""
    if not path:
        return False
    if _mech_glob_regex(glob).fullmatch(path):
        return True
    if "*" not in glob and "?" not in glob:
        g = glob.rstrip("/")
        return path == g or path.startswith(g + "/")
    return False


def _split_mechanism_frontmatter(text: str) -> tuple[list[str], list[str]]:
    """解析文件头 frontmatter 的 `mechanism-paths:` 值，返回 (合法 globs, 非法 globs)。

    只认文件首部 `---` 围栏块（块列表 `- item` / 行内标量 / 行内 `[a, b]`）；
    词表两档（RFC-20261123-01 §2.3，逆紧：中段 `**` 自此拒收）——字面路径或
    `dir/**`，其余（单星/裸 `**`/中段 `**`/`?`）判非法。"""
    m = _MECH_FM_RE.match(text)
    if not m:
        return [], []
    raw: list[str] = []
    in_block = False
    for line in m.group(1).splitlines():
        km = _MECH_KEY_RE.match(line.strip())
        if km:
            rest = km.group(1).strip()
            if rest.startswith("["):
                inner = rest[1:rest.index("]")] if "]" in rest else rest[1:]
                for item in inner.split(","):
                    item = item.strip().strip("'\"")
                    if item:
                        raw.append(item)
                in_block = False
            elif rest:
                raw.append(rest.strip("'\""))
                in_block = False
            else:
                in_block = True
            continue
        if in_block:
            im = _MECH_ITEM_RE.match(line.strip())
            if im:
                raw.append(im.group(1).strip().strip("'\""))
            elif line.strip():
                in_block = False
    good: list[str] = []
    bad: list[str] = []
    for g in raw:
        (bad if not _mech_glob_wellformed(g) else good).append(g)
    return good, bad


def _iter_repo_files(root: Path):
    """全仓文件相对路径（剪枝点目录 / node_modules / 构建产物；机制文档永不入 .atlas）。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in _MECH_PRUNE_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            yield (Path(dirpath) / fn).relative_to(root).as_posix()


def _tracked_files(root: Path) -> list[str]:
    """死 paths 判据的仓内文件全集：`git ls-files`；git 不可用 / 非仓 ⇒ 回落遍历。"""
    try:
        pr = subprocess.run(["git", "ls-files"], cwd=str(root),
                            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pr = None
    if pr is not None and pr.returncode == 0:
        return [ln.strip() for ln in pr.stdout.splitlines() if ln.strip()]
    return list(_iter_repo_files(root))


def discover_mechanism_docs(
        root: Path) -> list[tuple[str, list[str], list[str], bool]]:
    """全仓按 frontmatter `mechanism-paths:` key 发现机制文档（RFC-20261122-04）。

    返回 `(相对路径, 合法 globs, 非法 globs, pending)`；`pending` 篇的合法 globs
    置空（冷启动豁免不判，非法条目仍点名）。"""
    root = Path(root)
    docs: list[tuple[str, list[str], list[str], bool]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in _MECH_PRUNE_DIRS and not d.startswith("."))
        for fn in sorted(filenames):
            if not fn.endswith(".md"):
                continue
            p = Path(dirpath) / fn
            try:
                if p.stat().st_size > 1_000_000:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            good, bad = _split_mechanism_frontmatter(text)
            if not good and not bad:
                continue
            pending = good == [MECHANISM_PENDING]
            docs.append((p.relative_to(root).as_posix(),
                         [] if pending else good, bad, pending))
    return docs


def _globs_alive(universe: list[str], globs: list[str]) -> bool:
    """任一 glob 对文件全集命中即活（早退；死篇才付全量扫描成本）。"""
    rxs = [(_mech_glob_regex(g), g) for g in globs]
    for f in universe:
        for rx, g in rxs:
            if rx.fullmatch(f):
                return True
            if "*" not in g and "?" not in g:
                gg = g.rstrip("/")
                if f == gg or f.startswith(gg + "/"):
                    return True
    return False


def mechanism_doc_findings(
        root: Path,
        docs: list[tuple[str, list[str], list[str], bool]] | None = None,
) -> list[str]:
    """机制文档提示族残部（RFC-20261122-04，WARN 纪律面；调用方以 WARN 呈现）。

    触及提示已退役升格为申报判决门（RFC-20261123-01，前置判定带 FAIL）；
    本函数只剩审查后 WARN 残部（红轮不可见 = 既有语义不变）：

    - 死 paths：某篇全部 globs 对仓内文件全集零命中 ⇒ WARN「疑似死 paths」
      （治 paths 自身裸奔——代码整目录搬空后永不命中的静默死，评审 M2）；
    - 词表非法 glob 逐条点名（两档拒收，RFC-20261123-01 §2.3）；
    - 死测试锚（RFC-20261122-07 §3.2.2 提示族扩展）：判据行 `〔测:…〕` 锚指向的
      测试文件不存在 ⇒ WARN（可选但存活，只在已写锚的行上出声）；
    - `pending` 冷启动豁免（paths 覆盖不判；测试锚仍判——锚存活与 paths 无关；
      词表非法照点名）；
    - 仓内无机制文档 ⇒ 沉默。"""
    root = Path(root)
    docs = docs if docs is not None else discover_mechanism_docs(root)
    if not docs:
        return []
    universe = _tracked_files(root)
    findings: list[str] = []
    for rel, globs, bad, pending in docs:
        for g in bad:
            findings.append(
                f"{rel} 的 {MECHANISM_PATHS_KEY} 含非法 glob {g!r}："
                "词表只认字面路径与 dir/**（两档，RFC-20261123-01）")
        if pending:
            continue
        if globs and universe and not _globs_alive(universe, globs):
            findings.append(
                f"{rel} 的 {MECHANISM_PATHS_KEY} 指向零个仓内文件（疑似死 paths）："
                "核对代码是否已搬迁或删除（RFC-20261122-04）")
    findings.extend(_dead_anchor_findings(root, docs))
    return findings


def parse_mech_declares(
        root: Path, tasks_root: Path, unit: str,
) -> tuple[dict[str, str], str | None]:
    """解析卡目录 `mech-declares.md` 申报面（RFC-20261123-01 §2.2 文法）。

    合法行恰三类：空行 / `#` 注释 / `- <篇相对路径>: not-involved: <非空白理由>`；
    存在任何其余非空行 ⇒ fail-closed（返回不可解析描述，含行号与原文）。
    路径归一化 = strip 前导 `./`、`\\`→`/`（与暂存集同款）。缺文件 ⇒ ({}, None)。"""
    path = Path(tasks_root) / unit / "mech-declares.md"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}, None
    declares: dict[str, str] = {}
    for no, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = _MECH_DECLARE_RE.match(s)
        if not m:
            return {}, f"第 {no} 行不合法：{s}"
        reason = m.group(2).strip()
        if not reason:
            return {}, f"第 {no} 行申报缺理由：{s}"
        doc = m.group(1).replace("\\", "/")
        if doc.startswith("./"):
            doc = doc[2:]
        declares[doc] = reason
    return declares, None


def mechanism_declaration_verdict(
        root: Path,
        staged_files: list[str],
        tasks_root: Path,
        unit: str,
        docs: list[tuple[str, list[str], list[str], bool]] | None = None,
) -> list[dict]:
    """机制文档触及申报判决（RFC-20261123-01，FAIL 面；前置判定带调用）。

    - 词表非法 glob ⇒ kind=invalid_paths（`pending` 篇不豁免——词形缺陷非覆盖判定）；
    - 申报文件不可解析 ⇒ kind=unparsable_declares（fail-closed，其余判全部短路）；
    - 触及未跟改未申报 ⇒ kind=undeclared（`D` 判据 = 篇 ∈ 暂存；`A` = 申报映射）。

    判决面剔除 `.atlas/` 前缀暂存路径（卡产物自身入暂存不得触发触及）。
    返回 violation dict 列表（kind/doc/hits/declare_path/template），空 = PASS。"""
    root = Path(root)
    docs = docs if docs is not None else discover_mechanism_docs(root)
    if not docs:
        return []
    declare_path = Path(tasks_root) / unit / "mech-declares.md"
    declares, unparsable = parse_mech_declares(root, tasks_root, unit)
    violations: list[dict] = []
    if unparsable:
        violations.append({
            "kind": "unparsable_declares", "doc": "", "hits": [unparsable],
            "declare_path": str(declare_path), "template": ""})
        return violations
    norm_changed = [
        (c[2:] if c.startswith("./") else c).strip().replace("\\", "/")
        for c in staged_files if str(c).strip()]
    norm_changed = [c for c in norm_changed if not c.startswith(".atlas/")]
    for rel, _globs, bad, _pending in docs:
        if bad:
            violations.append({
                "kind": "invalid_paths", "doc": rel, "hits": list(bad),
                "declare_path": str(declare_path), "template": ""})
    for rel, globs, _bad, pending in docs:
        if pending or not globs:
            continue
        hits = [c for c in norm_changed if any(_mech_hit(c, g) for g in globs)]
        if hits and rel not in norm_changed and rel not in declares:
            violations.append({
                "kind": "undeclared", "doc": rel, "hits": hits,
                "declare_path": str(declare_path),
                "template": f"- {rel}: not-involved: <理由>"})
    return violations


def mechanism_dead_declare_findings(
        root: Path,
        tasks_root: Path,
        unit: str,
        docs: list[tuple[str, list[str], list[str], bool]] | None = None,
) -> list[str]:
    """申报死行提示（RFC-20261123-01 §2.2，WARN 提示族；审查通过后出声）。

    申报行指向零发现篇（不存在/已改名）⇒ WARN；缺文件/不可解析 ⇒ 沉默
    （不可解析已由判决位 fail-closed 出红，此处不重复）。"""
    root = Path(root)
    docs = docs if docs is not None else discover_mechanism_docs(root)
    known = {rel for rel, _g, _b, _p in docs}
    declares, unparsable = parse_mech_declares(root, tasks_root, unit)
    if unparsable:
        return []
    return [
        f"{path} 的申报行无对应机制篇（疑似申报死行）：核对篇是否已改名或删除"
        "（RFC-20261123-01）"
        for path in declares if path not in known]


# ───────────── 判据行测试锚（RFC-20261122-07 §3.2.2，可选但存活）─────────────

_TEST_ANCHOR_RE = re.compile(r"〔测[:：]\s*([^〕]+?)\s*〕")


def _dead_anchor_findings(
        root: Path,
        docs: list[tuple[str, list[str], list[str], bool]]) -> list[str]:
    """机制文档判据行测试锚存活检测（WARN 提示族扩展，随装配分发——采纳仓可达）。

    只消费已写锚的行（棘轮起点 = 可选；「新增行必带」的升格条件见 single-source
    §58 第五条）：锚目标须为 `tests/` 前缀的仓内文件（可带 `::node`）；文件不存在
    ⇒ 死锚 WARN；形态非法（非 `tests/` 前缀 / 越界）⇒ 形态 WARN。
    **节点级存在性不机器判**（防 verify 挂 pytest 收集，盲区在
    `shared/single-source.md` §57 登记行声明）；`pending` 篇同样判。"""
    findings: list[str] = []
    for rel, _globs, _bad, _pending in docs:
        p = root / rel
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        body = _MECH_FM_RE.sub("", text, count=1)  # 只扫正文，不扫 frontmatter
        for m in _TEST_ANCHOR_RE.finditer(body):
            target = m.group(1).strip()
            file_part = target.split("::", 1)[0].strip()
            if not file_part.startswith("tests/") or ".." in file_part:
                findings.append(
                    f"{rel} 判据行测试锚 {target!r} 形态非法（须 tests/ 前缀的仓内文件，"
                    "可带 ::node；RFC-20261122-07 §3.2.2）")
                continue
            if not (root / file_part).is_file():
                findings.append(
                    f"{rel} 判据行测试锚指向不存在的测试文件：{file_part}（死锚）"
                    "——核对测试是否已改名/删除，或修正锚（RFC-20261122-07 §3.2.2）")
    return findings
