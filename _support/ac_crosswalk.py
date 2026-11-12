#!/usr/bin/env python3
"""跨仓 AC crosswalk（RFC-20261111-03 §1.2 / §2.1 / §7 C-01…C-11）。

公开面只有两个入口：

- `parse_crosswalk(text) -> CrosswalkTable`：**纯词法**函数，零 Git、零文件系统；
  坏行抛 `CrosswalkParseError(code, line)`，`code` 是五项闭集
  `header_missing | column_count | ac_format | prd_path | member_field_empty`。
- `crosswalk_findings(table, manifest, reader) -> list[Finding]`：产 C-01…C-11 所需的
  `(code, row)`，**不打印、不 exit**。`reader` 提供成员 PRD 读取面
  （`paths` / `exists` / `front_matter` / `ac_ids` / `ac_links`）与 `waivers`。

码名按 v47（§5.2 码表 / §7 C 行），**不产 `C-01` 这类反包编号**：

| 反包 | 码 |
|---|---|
| C-01 | `crosswalk_ac_unmapped` |
| C-02 | `crosswalk_member_prd_unresolved` |
| C-03 | `crosswalk_member_ac_missing` |
| C-04 | `crosswalk_requirement_missing` |
| C-05 | `crosswalk_duplicate_row` |
| C-06 | **并入 `waiver_baseline_drift`，本模块不判**（v46/项 2） |
| C-07 | `crosswalk_waiver_due_exceeded` |
| C-08 | 正例，不产码 |
| C-09 | `crosswalk_ac_link_mismatch` |
| C-10 | `crosswalk_orphan_member_ac`（默认不报） |
| C-11 | `member_domain_mismatch` |

归属边界（§2.1 v42/阻断 3）：

- crosswalk 文件缺失 / 不可读 ⇒ 调用方（`check_solution`）在 parse 前判
  `crosswalk_unresolvable`，不在这里；能读但坏行 ⇒ 调用方判 `crosswalk_parse_error`；
- 表头 / 列数 / AC 形态 / 路径形态 / 成员字段空 ⇒ `parse_crosswalk` 抛
  `CrosswalkParseError`（纯词法）；
- 唯一键重复 ⇒ findings（C-05），parse 不抛；
- 成员不存在 / 成员 PRD 缺失 / 成员 AC 不存在 / `domain` 不符 ⇒ findings；
- 孤儿成员 AC（未列进 crosswalk）**默认不判**，只有显式 `orphan_warn=True` 才 WARN（C-10）。

契约 AC（`AC-CONTRACT-*`）**不是** crosswalk 的合法值：`方案AC` 列只允许
`AC-SOLUTION-*`；成员 AC 位置出现契约 AC ⇒ findings `contract_ac_in_member_slot`
（D-46），由本模块判、不新增解析码。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

SOLUTION_AC_RE = re.compile(r"^AC-SOLUTION-\d{3}$")
MEMBER_AC_RE = re.compile(r"^AC-[A-Z0-9]+-\d{3}$")
MEMBER_AC_PARTS_RE = re.compile(r"^AC-(?P<code>.+)-(?P<num>\d{3})$")
CONTRACT_AC_RE = re.compile(r"^AC-CONTRACT-\d{3}$")
CONTRACT_AC_PREFIX = "AC-CONTRACT-"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 六列表头（顺序即契约，§1.2）
COLUMNS = ("方案AC", "成员", "成员PRD", "成员域", "成员AC", "依据")
PARSE_ERROR_CODES = ("header_missing", "column_count", "ac_format",
                     "prd_path", "member_field_empty")
# §五-b 契约 AC 表（固定六列，顺序即契约）
CONTRACT_COLUMNS = ("契约AC", "字段", "类型", "必填", "异常码", "关联AC")


class CrosswalkParseError(ValueError):
    """crosswalk 解析失败；`code` 是五项闭集之一（§2.1）。"""

    def __init__(self, code: str, line: int, message: str = "") -> None:
        if code not in PARSE_ERROR_CODES:
            raise ValueError(f"CrosswalkParseError.code 越界: {code!r}")
        self.code = code
        self.line = line
        self.message = message
        suffix = f": {message}" if message else ""
        super().__init__(f"{code}（第 {line} 行）{suffix}")


@dataclass
class CrosswalkRow:
    solution_ac: str
    member: str
    prd: str
    member_domain: str
    member_ac: str
    basis: str
    line: int


@dataclass
class CrosswalkTable:
    rows: list[CrosswalkRow] = field(default_factory=list)

    def keys(self) -> list[tuple[str, str, str, str]]:
        return [(r.solution_ac, r.member, r.prd, r.member_ac) for r in self.rows]


def _cells(line: str) -> list[str]:
    return [c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c != "")


def _is_prd_path(raw: str) -> bool:
    if not raw or raw.startswith("/") or "\\" in raw:
        return False
    parts = raw.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return False
    return raw.endswith("-prd.md")


def parse_crosswalk(text: str) -> CrosswalkTable:
    """解析 crosswalk 六列表；纯词法、零 Git / 零 FS。"""
    lines = text.splitlines()
    header_index = None
    for i, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        cells = _cells(line)
        if list(cells[:len(COLUMNS)]) != list(COLUMNS) or len(cells) != len(COLUMNS):
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if not nxt.startswith("|") or not _is_separator(_cells(nxt)):
            continue
        header_index = i
        break
    if header_index is None:
        raise CrosswalkParseError(
            "header_missing", 0,
            f"找不到含六列表头 {' | '.join(COLUMNS)} 的 crosswalk 表")

    table = CrosswalkTable()
    for offset, raw_line in enumerate(lines[header_index + 2:], header_index + 3):
        if not raw_line.strip().startswith("|"):
            break
        cells = _cells(raw_line)
        if _is_separator(cells):
            continue
        if len(cells) != len(COLUMNS):
            raise CrosswalkParseError(
                "column_count", offset,
                f"需要 {len(COLUMNS)} 列，实际 {len(cells)} 列")
        solution_ac, member, prd, member_domain, member_ac, basis = cells
        if not solution_ac:
            raise CrosswalkParseError("ac_format", offset, "方案AC 为空")
        if not SOLUTION_AC_RE.match(solution_ac):
            raise CrosswalkParseError(
                "ac_format", offset,
                f"方案AC 只允许 AC-SOLUTION-NNN（得到 {solution_ac!r}）")
        if not member:
            raise CrosswalkParseError("member_field_empty", offset, "成员为空")
        if not prd:
            raise CrosswalkParseError("member_field_empty", offset, "成员PRD 为空")
        if not member_domain:
            raise CrosswalkParseError("member_field_empty", offset, "成员域为空")
        if not member_ac:
            raise CrosswalkParseError("member_field_empty", offset, "成员AC 为空")
        if not MEMBER_AC_RE.match(member_ac):
            raise CrosswalkParseError(
                "ac_format", offset,
                f"成员AC 形态非法（得到 {member_ac!r}）")
        if not _is_prd_path(prd):
            raise CrosswalkParseError(
                "prd_path", offset,
                f"成员PRD 必须是成员仓内相对路径且以 -prd.md 结尾（得到 {prd!r}）")
        table.rows.append(CrosswalkRow(
            solution_ac=solution_ac, member=member, prd=prd,
            member_domain=member_domain, member_ac=member_ac,
            basis=basis, line=offset))
    return table


# ---------------------------------------------------------------- findings

@dataclass
class Finding:
    code: str
    severity: str
    message: str
    path: str | None = None
    detail: dict[str, Any] | None = None

    def as_dict(self) -> dict:
        item = {"code": self.code, "severity": self.severity,
                "message": self.message, "path": self.path}
        if self.detail is not None:
            item["detail"] = self.detail
        return item


def _member_paths(manifest: dict) -> dict[str, str]:
    return {str(m.get("name")): str(m.get("path") or "")
            for m in manifest.get("members") or []}


def _requirement_index(manifest: dict) -> tuple[dict[tuple[str, str], str],
                                                 set[tuple[str, str]]]:
    """`(方案AC, 成员)` → 需求 ID；并返回全部需求级 AC 引用集合。"""
    by_pair: dict[tuple[str, str], str] = {}
    pairs: set[tuple[str, str]] = set()
    for req in manifest.get("requirements") or []:
        member = str(req.get("member") or "")
        for ac in req.get("acs") or []:
            key = (str(ac), member)
            by_pair.setdefault(key, str(req.get("id") or ""))
            pairs.add(key)
    return by_pair, pairs


def _norm_waiver(item: Any) -> dict:
    if not isinstance(item, dict):
        return {}
    return {
        "requirement": str(item.get("requirement") or item.get("需求") or "").strip(),
        "owner": str(item.get("owner") or "").strip(),
        "due": str(item.get("due") or "").strip(),
        "review": str(item.get("review") or "").strip(),
    }


def _links_index(reader, path: str) -> dict[str, list[str] | None] | None:
    """`ac_links(path) -> list[{member_ac, linked_solution_ac}]` 归一成索引。

    `linked_solution_ac` 为 `None`（该行缺 `关联AC`）或方案 AC 列表；读取面没有
    `ac_links` ⇒ 返回 `None`（C-09 不可判，不得猜成通过）。
    """
    fn = getattr(reader, "ac_links", None)
    if not callable(fn):
        return None
    out: dict[str, list[str] | None] = {}
    for item in fn(path) or []:
        if not isinstance(item, dict):
            continue
        member_ac = str(item.get("member_ac") or "").strip()
        if not member_ac:
            continue
        raw = item.get("linked_solution_ac")
        if raw is None:
            value: list[str] | None = None
        elif isinstance(raw, str):
            value = [raw] if raw.strip() else None
        else:
            values = [str(x) for x in raw if str(x).strip()]
            value = values or None
        # 同一成员 AC 可能出现在多张表（AC 表 / 结构类清单）：已有非空关联不被空值覆盖。
        if out.get(member_ac) is not None:
            continue
        out[member_ac] = value
    return out


def crosswalk_findings(table: CrosswalkTable, manifest: dict, reader,
                       *, orphan_warn: bool = False) -> list[Finding]:
    """按 crosswalk + manifest + 成员 PRD 读取面判 C-01…C-11（v47 码名）。

    `reader` 需要提供 `paths(member)` / `exists(path)` / `front_matter(path)` /
    `ac_ids(path)` / `ac_links(path)`（`list[{member_ac, linked_solution_ac}]`，
    缺 `关联AC` ⇒ `linked_solution_ac = null`；不变式
    `ac_ids(path) == {x.member_ac for x in ac_links(path)}`），以及 `waivers`
    （`ac-crosswalk-waivers.md` 的行，C-07 供数）。

    C-06 已并入 `waiver_baseline_drift`（v46/项 2），本函数**不判 C-06**。

    `orphan_warn` 默认 `False`：孤儿成员 AC 默认不产生任何码（C-10 冻结口径），
    只有显式开启才 WARN `crosswalk_orphan_member_ac`。
    """
    findings: list[Finding] = []
    seen: set[tuple] = set()

    def add(code: str, severity: str, message: str, path: str | None = None,
            detail: dict | None = None, dedupe: tuple | None = None) -> None:
        marker = dedupe if dedupe is not None else (code, path, message)
        if marker in seen:
            return
        seen.add(marker)
        findings.append(Finding(code, severity, message, path, detail))

    members = _member_paths(manifest)
    by_pair, _pairs = _requirement_index(manifest)

    # C-01：需求引用的方案 AC 没有对应成员的 crosswalk 行（契约 AC 排除）
    for req in manifest.get("requirements") or []:
        req_id = str(req.get("id") or "")
        member = str(req.get("member") or "")
        for ac in req.get("acs") or []:
            ac = str(ac)
            if not SOLUTION_AC_RE.match(ac):
                continue
            if any(row.solution_ac == ac and row.member == member
                   for row in table.rows):
                continue
            add("crosswalk_ac_unmapped", "error",
                f"crosswalk_ac_unmapped: {req_id}/{member} 的方案 AC {ac} "
                "无 crosswalk 行",
                None, {"requirement": req_id, "member": member, "ac": ac},
                dedupe=("crosswalk_ac_unmapped", req_id, member, ac))

    for row in table.rows:
        member_rel = members.get(row.member, "")
        prd_rel = f"{member_rel}/{row.prd}" if member_rel else row.prd
        if row.member_ac.startswith(CONTRACT_AC_PREFIX):
            add("contract_ac_in_member_slot", "error",
                f"contract_ac_in_member_slot: 契约 AC 不得占成员 AC 位置："
                f"{row.member_ac}（{prd_rel}）",
                prd_rel, {"line": row.line},
                dedupe=("contract_ac_in_member_slot", row.member_ac, prd_rel))
            continue

        # C-11：成员 / 成员域 / AC 前缀 / PRD front matter domain 四者一致。
        parts = MEMBER_AC_PARTS_RE.match(row.member_ac)
        prefix = parts.group("code") if parts else ""
        if row.member not in members:
            add("member_domain_mismatch", "error",
                f"member_domain_mismatch: crosswalk 成员 {row.member!r} "
                "不在清单 members[] 内", prd_rel, {"line": row.line,
                                                  "kind": "member_unknown"},
                dedupe=("member_domain_mismatch", "member_unknown", row.member))
        else:
            if prefix.lower() != row.member_domain.lower():
                add("member_domain_mismatch", "error",
                    f"member_domain_mismatch: 成员域 {row.member_domain!r} 与成员AC "
                    f"前缀 {row.member_ac!r} 不一致（{prd_rel}）", prd_rel,
                    {"line": row.line, "kind": "ac_prefix"},
                    dedupe=("member_domain_mismatch", "ac_prefix", row.member_ac,
                            prd_rel))
            if reader.exists(prd_rel):
                fm = reader.front_matter(prd_rel) or {}
                domain = str(fm.get("domain") or "").strip()
                if domain and domain.lower() != row.member_domain.lower():
                    add("member_domain_mismatch", "error",
                        f"member_domain_mismatch: 成员 PRD front matter "
                        f"domain={domain!r} 与 crosswalk 成员域 "
                        f"{row.member_domain!r} 不符（{prd_rel}）", prd_rel,
                        {"line": row.line, "kind": "front_matter"},
                        dedupe=("member_domain_mismatch", "front_matter", row.member,
                                row.prd))

        # C-04：(方案AC, 成员) 无需求行（只看清单，不依赖成员 PRD）
        if (row.solution_ac, row.member) not in by_pair:
            add("crosswalk_requirement_missing", "error",
                f"crosswalk_requirement_missing: {row.member} 的方案 AC "
                f"{row.solution_ac} 无需求行",
                prd_rel, {"line": row.line},
                dedupe=("crosswalk_requirement_missing", row.solution_ac, row.member))

        if row.member not in members:
            continue

        # C-02：成员 PRD 缺失 / 多 PRD 无法定位
        if not member_rel or not reader.exists(prd_rel):
            paths = []
            try:
                paths = list(reader.paths(row.member) or [])
            except Exception:  # noqa: BLE001 - 读取面异常不得吞成 PASS
                paths = []
            reason = "成员 PRD 缺失"
            if len(paths) > 1:
                reason = f"多 PRD 无法定位（候选 {len(paths)} 份）"
            add("crosswalk_member_prd_unresolved", "error",
                f"crosswalk_member_prd_unresolved: {row.member}: {reason} — "
                f"{prd_rel}", prd_rel, {"line": row.line},
                dedupe=("crosswalk_member_prd_unresolved", row.member, row.prd))
            continue

        ac_ids = set(reader.ac_ids(prd_rel) or ())
        contract_acs = sorted(ac for ac in ac_ids
                              if ac.startswith(CONTRACT_AC_PREFIX))
        if contract_acs:
            add("contract_ac_in_member_slot", "error",
                f"contract_ac_in_member_slot: 成员 PRD AC 表出现契约 AC："
                f"{', '.join(contract_acs)}（{prd_rel}）",
                prd_rel, {"line": row.line},
                dedupe=("contract_ac_in_member_slot", "prd", prd_rel))
        c03_hit = row.member_ac not in ac_ids
        if c03_hit:
            add("crosswalk_member_ac_missing", "error",
                f"crosswalk_member_ac_missing: {row.member}: 成员 AC "
                f"{row.member_ac} 不在 {prd_rel}",
                prd_rel, {"line": row.line},
                dedupe=("crosswalk_member_ac_missing", row.member, row.prd,
                        row.member_ac))

        # C-09：显式行把成员 AC 映射到错误的方案 AC（与 PRD 的关联AC 不一致）。
        # C-03 命中行不再判 C-09（同一行只出一个码，v47 不变式）。
        if not c03_hit:
            links = _links_index(reader, prd_rel)
            if links is not None and row.member_ac in links:
                mapped = links[row.member_ac]
                if mapped is not None and row.solution_ac not in mapped:
                    add("crosswalk_ac_link_mismatch", "error",
                        f"crosswalk_ac_link_mismatch: {prd_rel} 的 "
                        f"{row.member_ac} 关联AC={sorted(mapped)}，crosswalk 却映射到 "
                        f"{row.solution_ac}",
                        prd_rel, {"line": row.line, "member_ac": row.member_ac,
                                  "linked_solution_ac": list(mapped)},
                        dedupe=("crosswalk_ac_link_mismatch", row.prd, row.member_ac,
                                row.solution_ac))

    # C-05：唯一键重复（parse 不抛，归 findings）
    groups: dict[tuple, list[CrosswalkRow]] = {}
    for row in table.rows:
        groups.setdefault((row.solution_ac, row.member, row.prd,
                           row.member_ac), []).append(row)
    for key, rows in groups.items():
        if len(rows) > 1:
            add("crosswalk_duplicate_row", "error",
                "crosswalk_duplicate_row: 重复 crosswalk 键 "
                f"({key[0]}, {key[1]}, {key[2]}, {key[3]})：第 "
                f"{', '.join(str(r.line) for r in rows)} 行",
                rows[0].prd, {"line": rows[1].line},
                dedupe=("crosswalk_duplicate_row",) + key)

    # C-07：豁免 due 必须真实且不超 acceptance_cutover（C-06 不在此判）。
    cutover = manifest.get("acceptance_cutover")
    cutover_date = None
    if isinstance(cutover, str) and DATE_RE.match(cutover):
        try:
            cutover_date = date.fromisoformat(cutover)
        except ValueError:
            cutover_date = None
    for raw in getattr(reader, "waivers", None) or []:
        waiver = _norm_waiver(raw)
        req_id = waiver["requirement"]
        due_raw = waiver["due"]
        due = None
        if DATE_RE.match(due_raw):
            try:
                due = date.fromisoformat(due_raw)
            except ValueError:
                due = None
        if due is None:
            add("crosswalk_waiver_due_exceeded", "error",
                f"crosswalk_waiver_due_exceeded: 豁免 due 必须是真实日期 "
                f"YYYY-MM-DD（{req_id} 得到 {due_raw!r}）",
                None, {"requirement": req_id, "kind": "malformed"},
                dedupe=("crosswalk_waiver_due_exceeded", req_id, "malformed"))
        elif cutover_date is not None and due > cutover_date:
            add("crosswalk_waiver_due_exceeded", "error",
                f"crosswalk_waiver_due_exceeded: 豁免 due={due_raw} 超出 "
                f"acceptance_cutover={cutover}（{req_id}）",
                None, {"requirement": req_id, "kind": "beyond_cutover"},
                dedupe=("crosswalk_waiver_due_exceeded", req_id, "beyond_cutover"))

    # C-10：孤儿成员 AC 默认不判；显式开关才 WARN
    if orphan_warn:
        listed: dict[str, set[str]] = {}
        for row in table.rows:
            member_rel = members.get(row.member, "")
            prd_rel = f"{member_rel}/{row.prd}" if member_rel else row.prd
            listed.setdefault(prd_rel, set()).add(row.member_ac)
        for prd_rel, covered in sorted(listed.items()):
            if not reader.exists(prd_rel):
                continue
            for ac in sorted(set(reader.ac_ids(prd_rel) or ()) - covered):
                if ac.startswith(CONTRACT_AC_PREFIX):
                    continue
                add("crosswalk_orphan_member_ac", "warning",
                    f"孤儿成员 AC（未列进 crosswalk）：{ac}（{prd_rel}）",
                    prd_rel, None,
                    dedupe=("crosswalk_orphan_member_ac", prd_rel, ac))

    return findings


# ---------------------------------------------------------------- §五-b 契约 AC（D 批纯判据）

def _table_with_header(text: str, required: str
                       ) -> tuple[list[str], list[tuple[int, list[str]]]] | None:
    """第一张表头含 `required` 的 Markdown 表 ⇒ `(表头, [(行号, 单元格)])`。"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        header = _cells(line)
        if required not in header:
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if not nxt.startswith("|") or not _is_separator(_cells(nxt)):
            continue
        rows: list[tuple[int, list[str]]] = []
        for j in range(i + 2, len(lines)):
            if not lines[j].strip().startswith("|"):
                break
            cells = _cells(lines[j])
            if _is_separator(cells):
                continue
            rows.append((j + 1, cells))
        return header, rows
    return None


def _front_matter_schema(text: str) -> int:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return 1
    for raw in m.group(1).splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        if key.strip() == "prd_schema":
            try:
                return int(value.strip())
            except ValueError:
                return 1
    return 1


def _contract_ac_findings(text: str, manifest: dict, rel: str) -> list[Finding]:
    """§五-b 契约 AC 的纯判据（D-46 / E-04 / E-10）。

    `text` 是定义源 PRD 的全文，`manifest` 是已解析清单；不读 Git / 文件系统。
    `prd_schema: 2` 且该域被引用而找不到 `契约AC` 表 ⇒ `contract_ac_table_missing`；
    引用未定义 ⇒ `contract_ac_undefined`；`关联AC` 悬空 ⇒ `contract_ac_orphan`；
    编号形态错 ⇒ `contract_ac_format`（`detail.kind = ac_contract_format`，v46/项 4；
    本表不经 crosswalk parser）。
    """
    out: list[Finding] = []
    schema = _front_matter_schema(text)
    requirements = manifest.get("requirements") or []
    referenced = any(req.get("acs") for req in requirements)
    found = _table_with_header(text, "契约AC")
    if found is None:
        if schema >= 2 and referenced:
            out.append(Finding(
                "contract_ac_table_missing", "error",
                f"contract_ac_table_missing: {rel} 的 prd_schema=2 且该域被引用，"
                "但找不到 §五-b 契约 AC 表", rel))
        return out
    header, rows = found
    if tuple(header) != CONTRACT_COLUMNS:
        out.append(Finding(
            "contract_ac_table_missing", "error",
            f"contract_ac_table_missing: {rel} 的 §五-b 表头必须是 "
            f"{' | '.join(CONTRACT_COLUMNS)}", rel, {"kind": "header"}))
        return out
    contract_lines = {line for line, _ in rows}
    section_ac = set()
    for idx, line in enumerate(text.splitlines(), 1):
        if idx in contract_lines or not line.strip().startswith("|"):
            continue
        for token in re.findall(r"AC-[A-Z0-9]+-\d{3}", line):
            if not token.startswith(CONTRACT_AC_PREFIX):
                section_ac.add(token)
    ids: list[str] = []
    for line, cells in rows:
        if len(cells) != len(CONTRACT_COLUMNS):
            out.append(Finding(
                "contract_ac_table_missing", "error",
                f"contract_ac_table_missing: {rel}:{line} 需要 "
                f"{len(CONTRACT_COLUMNS)} 列，实际 {len(cells)} 列",
                rel, {"kind": "column_count", "line": line}))
            continue
        ac = cells[0]
        if not CONTRACT_AC_RE.match(ac):
            out.append(Finding(
                "contract_ac_format", "error",
                f"contract_ac_format: {rel}:{line} 的契约AC {ac!r} 形态非法"
                "（应为 AC-CONTRACT-NNN）", rel,
                {"kind": "ac_contract_format", "line": line}))
            continue
        if ac in ids:
            out.append(Finding(
                "contract_ac_undefined", "error",
                f"contract_ac_undefined: {rel}:{line} 重复定义 {ac}", rel,
                {"kind": "duplicate", "line": line}))
            continue
        ids.append(ac)
        for related in re.split(r"[、,，\s]+", cells[5]):
            if not related or related == "-" or "<" in related:
                continue
            if related not in section_ac:
                out.append(Finding(
                    "contract_ac_orphan", "error",
                    f"contract_ac_orphan: {rel}:{line} 的关联AC {related!r} "
                    "不在本 PRD §五 AC 表", rel,
                    {"line": line, "related": related}))
    defined = set(ids)
    for req in requirements:
        for ac in req.get("acs") or []:
            if str(ac).startswith(CONTRACT_AC_PREFIX) and str(ac) not in defined:
                out.append(Finding(
                    "contract_ac_undefined", "error",
                    f"contract_ac_undefined: 需求 {req.get('id')} 引用了未定义的"
                    f"契约 AC {ac}", rel,
                    {"requirement": req.get("id"), "ac": str(ac)}))
    return out
