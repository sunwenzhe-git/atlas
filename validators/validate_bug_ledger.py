#!/usr/bin/env python3
"""Validate canonical requirement-change/defect records and reject legacy dual landing paths."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.bug_backflow import dedupe_findings, strict_requirement_fields
from _support.bug_record import RECORD_FILE, read_record, report_ambiguities, validate_record
from _support.layout import LayoutError, load_layout
from _support.workflow_plan import PlanError, load_tasks, requirement_relation_findings

LEGACY_VALUES = {"bug", "缺陷", "defect", "change", "需求变更", "requirement-change"}


class Result:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, check: str, status: str, detail: str = "") -> None:
        self.checks.append({"check": check, "status": status, "detail": detail})

    @property
    def status(self) -> str:
        values = [item["status"] for item in self.checks]
        if "FAIL" in values:
            return "FAIL"
        if "WARN" in values:
            return "WARN"
        if values and all(value == "SKIP" for value in values):
            return "SKIP"
        return "PASS"

    @property
    def ok(self) -> bool:
        return self.status != "FAIL"


def _nonempty_dir(path: Path) -> bool:
    if path.is_symlink():
        return True
    return path.is_dir() and any(path.iterdir())


def _legacy_file(path: Path) -> bool:
    name = path.name.casefold()
    if name.startswith("bug-") or name.startswith("bug_"):
        return True
    if name == "record.json":
        return True
    if path.suffix.casefold() not in (".md", ".json", ".yaml", ".yml"):
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if re.search(r"^\*\*类型\*\*[：:]\s*(?:缺陷|需求变更)\s*$", text, re.M):
        return True
    for match in re.finditer(r"^(?:type|kind)\s*[：:]\s*([^\s#]+)", text, re.M | re.I):
        if match.group(1).strip("\"'").casefold() in LEGACY_VALUES:
            return True
    if path.suffix.casefold() == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return False
        if isinstance(payload, dict):
            for key in ("type", "kind"):
                if str(payload.get(key, "")).casefold() in LEGACY_VALUES:
                    return True
    return False


def _legacy_bugs_dir(path: Path) -> bool:
    if not _nonempty_dir(path):
        return False
    if path.is_symlink():
        return True
    return any(_legacy_file(item) for item in path.rglob("*") if item.is_file())


def _casefold_children(path: Path, name: str) -> list[Path]:
    if not path.is_dir() or path.is_symlink():
        return []
    return [item for item in path.iterdir() if item.name.casefold() == name.casefold()]


def _ledger_like(path: Path) -> bool:
    """嵌套 record.json 是否真是机器台账：看内容形态，避免同名称证据文件误伤。"""
    if path.is_symlink():
        return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    markers = {"dedupe_key", "backflow_status", "schema_version"} & set(payload)
    return len(markers) >= 2


def _nested_ledgers(req_root: Path) -> list[Path]:
    """req_root 根级以外的机器台账（大小写变体；symlink 目录只看目标顶层，防遍历逃逸）。"""
    found: list[Path] = []
    for current, dirs, files in os.walk(req_root, followlinks=False,
                                       onerror=lambda _exc: None):
        cur = Path(current)
        for name in dirs:
            link = cur / name
            if not link.is_symlink():
                continue
            try:
                entries = list(os.scandir(link))
            except OSError:
                continue
            for entry in entries:
                if entry.name.casefold() != RECORD_FILE.casefold():
                    continue
                candidate = link / entry.name
                if _ledger_like(candidate):
                    found.append(candidate)
        if cur == req_root:
            continue
        for name in files:
            if name.casefold() != RECORD_FILE.casefold():
                continue
            path = cur / name
            if _ledger_like(path):
                found.append(path)
    return sorted(found)


def validate(root: Path) -> Result:
    res = Result()
    try:
        layout = load_layout(root)
    except LayoutError as exc:
        res.add("项目布局配置", "FAIL", str(exc))
        return res
    root = root.resolve()
    requirements = layout.assets_root / "requirements"
    legacy: list[str] = []

    for path in _casefold_children(root / ".atlas", "bugs"):
        if _nonempty_dir(path):
            legacy.append(str(path.relative_to(root)))
    for path in _casefold_children(layout.assets_root, "bugs"):
        if _legacy_bugs_dir(path):
            legacy.append(str(path.relative_to(root)))
    roots: list[Path] = []
    if requirements.is_dir() and not requirements.is_symlink():
        roots = [item for item in requirements.iterdir()
                 if item.is_dir() and item.name != "archive"]
        archive = requirements / "archive"
        if archive.is_dir() and not archive.is_symlink():
            for month in archive.iterdir():
                if month.is_dir() and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month.name):
                    roots.extend(item for item in month.iterdir() if item.is_dir())
    if legacy:
        res.add("canonical_landing", "FAIL",
                "发现第二变更/缺陷落点（迁移到 requirements/<slug>/）：" + "、".join(sorted(set(legacy))))
    else:
        res.add("canonical_landing", "PASS", "未发现 legacy 双变更/缺陷落点")

    nested: list[str] = []
    for req_root in roots:
        nested.extend(str(path.relative_to(root)) for path in _nested_ledgers(req_root))
    if nested:
        res.add("canonical_ledger", "FAIL",
                "发现需求目录内的第二份机器台账（只允许 <req_root>/record.json）："
                + "、".join(sorted(set(nested))))
    else:
        res.add("canonical_ledger", "PASS", "未发现嵌套机器台账")

    record_paths = sorted(requirements.glob(f"*/{RECORD_FILE}")) if requirements.is_dir() else []
    archive = requirements / "archive"
    if archive.is_dir() and not archive.is_symlink():
        record_paths.extend(sorted(archive.glob(f"*/{RECORD_FILE}")))
        record_paths.extend(sorted(archive.glob(f"*/*/{RECORD_FILE}")))
    seen_keys: dict[str, str] = {}
    record_check_count = 0
    task_slugs: set[str] = set()
    tasks_root = root / ".atlas" / "tasks"
    if tasks_root.is_dir():
        try:
            task_slugs = {Path(str(item.get("requirement_root") or "")).name
                          for item in load_tasks(tasks_root, include_archived=True)
                          if item.get("requirement_root")}
        except (PlanError, OSError) as exc:
            res.add("task_references", "FAIL", f"任务账本不可读：{exc}")
    for path in record_paths:
        record_check_count += 1
        req_root = path.parent
        rel = str(path.relative_to(root))
        record = read_record(req_root)
        if record is None:
            res.add(f"record:{rel}", "FAIL", "record.json 不可解析或为 symlink")
            continue
        findings = validate_record(record, requirement_root=req_root, root=root)
        findings.extend(dedupe_findings(root, record, req_root))
        fields, field_findings = strict_requirement_fields(req_root)
        findings.extend(field_findings)
        if fields.get("类型") not in ("需求变更", "缺陷"):
            findings.append("record.json 存在但 requirement.md 类型不是需求变更/缺陷")
        if record.get("backflow_status") == "not_applicable" and req_root.name in task_slugs:
            findings.append("not_applicable 不得被任务卡引用")
        key = record.get("dedupe_key")
        if isinstance(key, str) and key:
            if key in seen_keys:
                findings.append(f"dedupe_key 重复：{seen_keys[key]} / {rel}")
            else:
                seen_keys[key] = rel
        if findings:
            res.add(f"record:{rel}", "FAIL", "；".join(findings))
        else:
            res.add(f"record:{rel}", "PASS", f"{record.get('backflow_status')} / {record.get('id')}")

    for req_root in roots:
        if (req_root / RECORD_FILE).is_file():
            continue
        fields, field_findings = strict_requirement_fields(req_root)
        kind = fields.get("类型")
        if kind not in ("需求变更", "缺陷"):
            continue
        ambiguity = report_ambiguities(req_root, kind)
        triage = (kind == "缺陷"
                  and fields.get("结论") in ("重复", "非缺陷", "不修")
                  and bool(fields.get("证据")))
        try:
            relation_findings = requirement_relation_findings(
                root, req_root, require_report=False)
        except (LayoutError, OSError) as exc:
            relation_findings = [f"关联需求无法校验：{exc}"]
        if relation_findings or ambiguity or not triage:
            record_check_count += 1
            rel = str(req_root.relative_to(root))
            detail = ("；".join(field_findings + relation_findings + ambiguity)
                      or "变更/缺陷既非合法分诊关闭，也无 record.json")
            res.add(f"record:{rel}", "FAIL", detail)
    if record_check_count == 0:
        if not requirements.is_dir():
            res.add("defect_records", "SKIP", "无 requirements/ 资产根（未走到变更/缺陷台账）")
        else:
            res.add("defect_records", "PASS", "无变更/缺陷台账记录")
    return res


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    res = validate(args.root.resolve())
    if args.json:
        print(json.dumps({"ok": res.ok, "status": res.status, "checks": res.checks},
                         ensure_ascii=False, indent=2))
    else:
        for item in res.checks:
            detail = f" —— {item['detail']}" if item.get("detail") else ""
            print(f"[{item['status']}] {item['check']}{detail}")
        print(f"\nFinal status: {res.status}")
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
