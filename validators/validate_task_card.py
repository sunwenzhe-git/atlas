#!/usr/bin/env python3
"""任务卡验收断言与 Confirmed 证据状态校验（RFC-20261111-03 §1.3 / §1.5 第 8 条）。

只在成员仓跑：读 `.trellis/tasks/<ID>/prd.md`（含 `archive/<month>/<ID>/prd.md`），
解析专用行 `atlas-acceptance:`，与同目录 `solution.md` 指针的 `acs:` 集合比较；
并判卡内 `Confirmed` / `确认口径` 表的证据状态。

不读父仓 PRD / crosswalk / 封条；不判 PRD 证据列（父仓 D 批）。

退出码：0 = 全 PASS（WARN 不影响）；1 = 任一 FAIL；2 = 输入错误。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

AC_LINE_RE = re.compile(r"^[ \t]*atlas-acceptance:[ \t]*(.+?)\s*$")
ACS_POINTER_RE = re.compile(r"^[ \t]*[-*]?[ \t]*acs:[ \t]*(.+?)\s*$", re.M)
NONE_RE = re.compile(
    r"^none(?:[（(](.*?)[）)])?$", re.S)
KV_RE = re.compile(r"(\w+)\s*=\s*([^；;]+)")
AC_TOKEN_RE = re.compile(r"^AC-(?:SOLUTION|CONTRACT)-\d{3}$")
REVIEW_RE = re.compile(r"^REVIEW-\d{8}-\d{2}$")
FENCE_RE = re.compile(r"^(```|~~~)")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SCHEMA_RE = re.compile(r"^prd_schema:\s*(\d+)\s*$", re.M)
ARCHIVE_SKIP_FRESH = {"status": "archived"}


class CardError(ValueError):
    pass


def _git(root: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout


def _tracked(root: Path, rel: str) -> bool:
    rc, _ = _git(root, "ls-files", "--error-unmatch", "--", rel)
    return rc == 0


def _strip_ignored(text: str) -> str:
    """去围栏代码块与 HTML 注释块（I5）；保留行结构以便报行号。"""
    out: list[str] = []
    in_fence = False
    in_comment = False
    for line in text.splitlines():
        stripped = line.strip()
        if in_comment:
            if "-->" in line:
                in_comment = False
                line = line.split("-->", 1)[1]
                stripped = line.strip()
            else:
                out.append("")
                continue
        if not in_fence and "<!--" in line:
            head, _, tail = line.partition("<!--")
            if "-->" in tail:
                line = head + tail.split("-->", 1)[1]
                stripped = line.strip()
            else:
                in_comment = True
                line = head
                stripped = line.strip()
        if FENCE_RE.match(stripped):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def accepted_acs(text: str) -> tuple[str | None, list[str], dict, int]:
    """返回 `(raw, acs, none_fields, line_no)`；`raw is None` = 无专用行。"""
    cleaned = _strip_ignored(text)
    for index, line in enumerate(cleaned.splitlines(), 1):
        m = AC_LINE_RE.match(line)
        if not m:
            continue
        raw = m.group(1).strip()
        none = NONE_RE.match(raw)
        if none:
            fields = {k: v.strip() for k, v in KV_RE.findall(none.group(1) or "")}
            return raw, [], fields, index
        tokens = [t.strip() for t in re.split(r"[,，、]", raw) if t.strip()]
        return raw, tokens, {}, index
    return None, [], {}, 0


def pointer_acs(card_dir: Path) -> list[str]:
    pointer = card_dir / "solution.md"
    if not pointer.is_file():
        return []
    text = pointer.read_text(encoding="utf-8", errors="replace")
    m = ACS_POINTER_RE.search(text)
    if not m:
        return []
    return [t.strip() for t in re.split(r"[,，、]", m.group(1)) if t.strip()]


def prd_schema(root: Path) -> int:
    """成员 PRD 声明 `prd_schema: 2` ⇒ 2；否则按存量 1（fail-safe）。"""
    for path in sorted(root.glob("*/prd/*-prd.md")) + sorted(root.glob("prd/*-prd.md")):
        m = SCHEMA_RE.search(path.read_text(encoding="utf-8", errors="replace"))
        if m and m.group(1) == "2":
            return 2
    return 1


def _table_after_heading(text: str, needles: tuple[str, ...]) -> list[list[str]] | None:
    """定位标题（含任一 needle）后的第一张 markdown 表；无表 ⇒ None。"""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if not line.lstrip().startswith("#"):
            continue
        if any(n in line for n in needles):
            start = index + 1
            break
    if start is None:
        return None
    table: list[list[str]] = []
    begun = False
    for line in lines[start:]:
        s = line.strip()
        if s.startswith("#") and begun:
            break
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            table.append(cells)
            begun = True
        elif begun and not s:
            continue
        elif begun and not s.startswith("|"):
            break
    return table or None


def _review_markers(text: str) -> list[str]:
    """Confirmed 小节里的 `confirmed_review:` 行内标记（RFC 四列表之外的标记）。"""
    return [m.group(1) for m in re.finditer(
        r"confirmed_review:\s*(REVIEW-\d{8}-\d{2})", text)]


def confirmed_findings(text: str, schema: int, today: date) -> tuple[list[dict], list[dict]]:
    """Confirmed 表：四列（确认项 / 口径 / 证据状态 / 证据指针）+ 行内标记。"""
    errors: list[dict] = []
    warnings: list[dict] = []
    table = _table_after_heading(text, ("Confirmed", "确认口径"))
    deadline_over = today >= date(2027, 7, 1)
    if table is None:
        item = {"code": "confirmed_columns_missing",
                "message": "缺少 Confirmed / 确认口径 表"}
        (errors if schema == 2 or deadline_over else warnings).append(item)
        return errors, warnings
    header = table[0]
    if not any("确认项" in c for c in header) or not any("证据状态" in c for c in header):
        item = {"code": "confirmed_columns_missing",
                "message": f"Confirmed 表头缺 确认项 / 证据状态：{header}"}
        (errors if schema == 2 or deadline_over else warnings).append(item)
        return errors, warnings
    state_idx = next(i for i, c in enumerate(header) if "证据状态" in c)
    pointer_idx = next((i for i, c in enumerate(header) if "证据指针" in c), None)
    if pointer_idx is None:
        item = {"code": "confirmed_columns_missing",
                "message": f"Confirmed 表头缺 证据指针：{header}"}
        (errors if schema == 2 or deadline_over else warnings).append(item)
        return errors, warnings
    markers = _review_markers(text)
    marker_i = 0
    for row_no, row in enumerate(table[1:], 1):
        if len(row) <= max(state_idx, pointer_idx):
            errors.append({"code": "confirmed_columns_missing",
                           "message": f"Confirmed 第 {row_no} 行缺列"})
            continue
        state = row[state_idx].strip()
        pointer = row[pointer_idx].strip()
        # 行内标记：优先同行任意单元格，其次按顺序取小节内 `confirmed_review:` 行
        inline = next((m.group(1) for cell in row for m in
                       [re.search(r"confirmed_review:\s*(REVIEW-\d{8}-\d{2})", cell)]
                       if m), "")
        if state not in ("verified", "assumed", "unverified"):
            errors.append({"code": "confirmed_evidence_missing",
                           "message": f"Confirmed 第 {row_no} 行证据状态非法: {state!r}"})
            continue
        if state in ("verified", "assumed") and not pointer:
            errors.append({"code": "confirmed_evidence_missing",
                           "message": f"Confirmed 第 {row_no} 行 {state} 缺证据指针"})
        if state == "unverified":
            if not inline and marker_i < len(markers):
                inline = markers[marker_i]
                marker_i += 1
            if inline:
                continue  # 带 confirmed_review: ⇒ 不再报 confirmed_unverified
            errors.append({"code": "confirmed_downgrade_unreviewed",
                           "message": f"Confirmed 第 {row_no} 行 unverified 缺合法 "
                                      "confirmed_review:"})
            warnings.append({"code": "confirmed_unverified",
                             "message": f"Confirmed 第 {row_no} 行证据状态为 "
                                        "unverified"})
    return errors, warnings


def _parse_none_fields(raw: str) -> dict:
    inner = re.sub(r"^none", "", raw).strip()
    inner = inner.strip("（）() ")
    return {k: v.strip() for k, v in KV_RE.findall(inner)}


def validate(root: Path, today: date | None = None,
             allow_card_absent: bool = False) -> tuple[list[dict], list[dict]]:
    today = today or date.today()
    errors: list[dict] = []
    warnings: list[dict] = []
    schema = prd_schema(root)
    cards: list[tuple[Path, str]] = []
    for path in sorted(root.glob(".trellis/tasks/*/prd.md")):
        cards.append((path, "active"))
    for path in sorted(root.glob(".trellis/tasks/archive/*/*/prd.md")):
        cards.append((path, "archived"))
    if not cards:
        item = {"code": "card_absent",
                "message": "无任务卡（.trellis/tasks/*/prd.md 与 archive 均缺失）"}
        (warnings if allow_card_absent else errors).append(item)
        return errors, warnings
    for path, status in cards:
        rel = str(path.relative_to(root))
        text = path.read_text(encoding="utf-8", errors="replace")
        if not _tracked(root, rel):
            errors.append({"code": "card_untracked",
                           "message": f"任务卡未被 git 跟踪: {rel}"})
        pointer_rel = str((path.parent / "solution.md").relative_to(root))
        if not (path.parent / "solution.md").is_file():
            errors.append({"code": "card_pointer_missing",
                           "message": f"缺 solution.md 指针: {pointer_rel}"})
            expected: list[str] = []
        else:
            if not _tracked(root, pointer_rel):
                errors.append({"code": "card_untracked",
                               "message": f"指针未被 git 跟踪: {pointer_rel}"})
            expected = pointer_acs(path.parent)
        raw, acs, none_fields, line_no = accepted_acs(text)
        if raw is None:
            errors.append({"code": "card_acceptance_missing",
                           "message": f"{rel}: 无 atlas-acceptance: 专用行"})
        elif raw.startswith("none"):
            fields = {**none_fields, **_parse_none_fields(raw)}
            missing = [k for k in ("reason", "owner", "due") if not fields.get(k)]
            if missing:
                errors.append({"code": "card_none_fields_missing",
                               "message": f"{rel}: none 缺 {'/'.join(missing)}"})
            if expected:
                errors.append({"code": "card_none_illegal",
                               "message": f"{rel}: 需求有 AC 却写 none（应走需求级豁免）"})
            due = fields.get("due", "")
            if due and DATE_RE.match(due) and date.fromisoformat(due) < today:
                errors.append({"code": "card_none_due_expired",
                               "message": f"{rel}: none due={due} 已过期"})
        else:
            bad = [t for t in acs if not AC_TOKEN_RE.match(t)]
            if bad:
                errors.append({"code": "card_acceptance_invalid",
                               "message": f"{rel}: AC 形态非法 {bad}"})
            extra = [t for t in acs if t not in expected]
            if extra:
                errors.append({"code": "card_acceptance_out_of_scope",
                               "message": f"{rel}: AC 不在该 (req, member) 的 acs 集合内: "
                                          f"{extra}（右集={expected}）"})
        c_errors, c_warnings = confirmed_findings(text, schema, today)
        errors.extend({"code": e["code"], "message": f"{rel}: {e['message']}"}
                      for e in c_errors)
        warnings.extend({"code": w["code"], "message": f"{rel}: {w['message']}"}
                        for w in c_warnings)
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--allow-card-absent", action="store_true",
                    help="本地开发：无卡只 WARN（CI 禁用）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if not (root / ".trellis").is_dir():
        print("[N/A] 无 .trellis（成员仓未接入任务卡）")
        return 0
    errors, warnings = validate(root, allow_card_absent=args.allow_card_absent)
    for item in errors:
        print(f"[FAIL] {item['code']}: {item['message']}")
    for item in warnings:
        print(f"[WARN] {item['code']}: {item['message']}")
    if args.json:
        import json
        print(json.dumps({"ok": not errors, "errors": errors,
                          "warnings": warnings}, ensure_ascii=False, indent=2))
    print(f"{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
