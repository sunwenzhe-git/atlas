#!/usr/bin/env python3
"""需求条目覆盖矩阵的 verify 期判据（#71/#72/#73，2026-11-21）。

纪律面 WARN 起步（升格 FAIL 另案）：`atlas workflow verify` 在独立审查通过后调用
`coverage_matrix_findings`，把条目覆盖缺口以 WARN 行打到 stderr，不改退出码。
契约落点：`shared/single-source.md` §4「需求原文优先序与条目覆盖」。

判据：
- 卡目录无 `requirement-items.md` ⇒ 非需求驱动卡，沉默（不制造假阳性）；
- 有条目表而 `coverage-matrix.md` 缺席 ⇒ WARN；
- 条目表零数据行且未声明「无外部需求原件」⇒ WARN（枚举本身没做，#72）；
- 矩阵格留空 / 值不在 {覆盖（…）/ 不涉及（…）/ UNRESOLVED} 词表 ⇒ 逐格 WARN；
- UNRESOLVED ⇒ 聚合 WARN（待裁决面）；
- 条目表 ⇔ 矩阵行 ID 双向差集 ⇒ WARN（漏行 / 幽灵行）。

纯标准库。
"""
from __future__ import annotations

import re
from pathlib import Path

ITEMS_FILE = "requirement-items.md"
MATRIX_FILE = "coverage-matrix.md"
MATRIX_COLUMNS = ("PRD", "设计文档", "实现", "E2E")
NO_REQUIREMENT_MARKER = "无外部需求原件"

_FENCE_RE = re.compile(r"^(```|~~~)")


def _strip_fences(text: str) -> str:
    """去围栏代码块（含条目原文中贴代码示例的情形），保留行结构。"""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def _first_table(text: str, header_needles: tuple[str, ...]) -> list[list[str]] | None:
    """第一张表头含任一 needle 的 markdown 表（header 在首行）；无 ⇒ None。"""
    lines = _strip_fences(text).splitlines()
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


def coverage_matrix_findings(task_dir: Path) -> list[str]:
    """返回条目覆盖缺口清单（空 = 干净或非需求驱动卡）；调用方以 WARN 呈现。"""
    task_dir = Path(task_dir)
    items_path = task_dir / ITEMS_FILE
    if not items_path.is_file():
        return []  # plan 未带 --requirement 的卡：不判，不制造假阳性

    findings: list[str] = []
    items_text = _strip_fences(items_path.read_text(encoding="utf-8", errors="replace"))
    items_rows = _first_table(items_text, ("原文",))
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

    matrix_rows = _first_table(
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
