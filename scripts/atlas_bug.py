#!/usr/bin/env python3
"""atlas bug/change —— 按 diff 回推活需求文档并留校验回执。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from _support.layout import LayoutError
from _support.workflow_backflow import (
    analyze_impact, apply_backflow, backflow_findings, code_snapshot, default_base,
    parse_record, resolve_request, run_validators, write_diff_report, write_record,
)
from _support.workflow_plan import PlanError
from _support.workflow_request import (
    clause_text, living_document_findings, parse_request, request_diff_path, request_items,
    update_change_conclusion, update_request_status,
)


def _doc_hash(root: Path, path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def run(args: argparse.Namespace, root: Path) -> int:
    try:
        feature_root, request_path, task = resolve_request(root, args.unit)
        meta = parse_request(request_path)
        expected_kind = "缺陷" if args.kind == "bug" else "需求变更"
        if meta.get("kind") != expected_kind:
            print(f"ERROR: 请求类型不匹配：{meta.get('kind')} != {expected_kind}", file=sys.stderr)
            return 2
        base = args.from_ or meta.get("base_commit") or default_base(root)
        snapshot = code_snapshot(root, base)
        living_errors = living_document_findings(feature_root, request_path)
        if living_errors:
            if args.dry_run:
                print(json.dumps({"status": "fail", "request": meta.get("id"),
                                  "errors": living_errors}, ensure_ascii=False, indent=2))
                return 1
            validators = [{"validator": "validate_living_requirement", "status": "FAIL",
                           "returncode": 1, "output": "\n".join(living_errors)}]
            update_request_status(request_path, status="failed",
                                  updated=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            write_diff_report(request_path, [], [], validators)
            diff_path = request_diff_path(request_path, expected_kind)
            doc_sha256 = {diff_path.relative_to(root).as_posix(): _doc_hash(root, diff_path)}
            receipt = {
                "schema_version": 1, "request_id": meta.get("id"), "kind": expected_kind,
                "status": "fail", "base": base, "code_sha256": snapshot["sha256"],
                "code_files": snapshot["files"], "doc_sha256": doc_sha256,
                "impacts": [], "conflicts": [], "validators": validators,
                "stage": args.stage or meta.get("stage"),
                "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            write_record(request_path, receipt)
            print(json.dumps({"status": "fail", "request": meta.get("id"),
                              "errors": living_errors}, ensure_ascii=False, indent=2))
            return 1
        record = parse_record(request_path)
        if record and record.get("status") == "ok" and record.get("code_sha256") == snapshot["sha256"]:
            check_task = {**task, "intake_version": 2, "intake_type": expected_kind,
                          "requirement_root": str(feature_root.relative_to(root)),
                          "request_path": str(request_path.relative_to(root)),
                          "base_commit": base}
            if not backflow_findings(root, check_task) and not any((args.stage, args.pr, args.commit, args.decision)):
                payload = {"status": "ok", "request": meta.get("id"), "unchanged": True,
                           "code_sha256": snapshot["sha256"]}
                print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else
                      f"回推无变化：{meta.get('id')}（{snapshot['sha256'][:12]}）")
                return 0
        impacts, conflicts = analyze_impact(root, feature_root, base, expected_kind)
        if args.dry_run:
            payload = {"status": "conflict" if conflicts else "ok", "request": meta.get("id"),
                       "base": base, "code_sha256": snapshot["sha256"],
                       "impacts": impacts, "conflicts": conflicts}
            print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else
                  json.dumps(payload, ensure_ascii=False, indent=2))
            return 2 if conflicts else 0
        changed, remaining = apply_backflow(
            root, feature_root, request_path, base=base, impacts=impacts,
            conflicts=conflicts, clause_override=args.clause_text,
            decision=args.decision, decision_by=args.decision_by)
        validators = run_validators(root, feature_root, request_path,
                                    include_structure=any(i["type"] == "spec" for i in impacts))
        validator_failed = any(v["returncode"] != 0 for v in validators)
        status = "conflict" if remaining else ("fail" if validator_failed else "ok")
        update_fields = {"status": "implemented" if status == "ok" else (
            "failed" if validator_failed else "conflict"),
                         "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if args.stage:
            update_fields["stage"] = args.stage
        if args.pr:
            update_fields["pr"] = args.pr
        if args.commit:
            update_fields["commit"] = args.commit
        if args.decision:
            update_fields["decision"] = args.decision
        if args.decision_by:
            update_fields["decision_by"] = args.decision_by
        update_request_status(request_path, **update_fields)
        if status == "ok":
            update_change_conclusion(feature_root, meta.get("id", ""),
                                      "已修复并校验" if expected_kind == "缺陷" else "已实现并校验")
        write_diff_report(request_path, impacts, remaining, validators)
        diff_path = request_diff_path(request_path, expected_kind)
        doc_paths = [diff_path] + [p for p in changed if p not in (
            feature_root / "requirement.md", feature_root / "items.md")]
        doc_sha256 = {p.relative_to(root).as_posix(): _doc_hash(root, p)
                      for p in dict.fromkeys(doc_paths)}
        feature_rel = feature_root.relative_to(root).as_posix()
        items = request_items(meta)
        if len(items) == 1:
            clause = clause_text(feature_root, items[0])
            doc_sha256[f"{feature_rel}/requirement.md#clause:{items[0]}"] = (
                hashlib.sha256(clause.encode("utf-8")).hexdigest() if clause is not None else None)
            req_path = feature_root / "requirement.md"
            req_lines = req_path.read_text(encoding="utf-8", errors="replace").splitlines() if req_path.is_file() else []
            row = next((line for line in req_lines if line.startswith(f"| {meta.get('id')} |")), None)
            doc_sha256[f"{feature_rel}/requirement.md#change-row:{meta.get('id')}"] = (
                hashlib.sha256(row.encode("utf-8")).hexdigest() if row is not None else None)
            items_file = feature_root / "items.md"
            item_lines = items_file.read_text(encoding="utf-8", errors="replace").splitlines() if items_file.is_file() else []
            item_row = next((line for line in item_lines if line.startswith(f"| {items[0]} |")), None)
            item_fragment = "|".join(item_row.split("|")[1:4]) if item_row else None
            doc_sha256[f"{feature_rel}/items.md#item:{items[0]}"] = (
                hashlib.sha256(item_fragment.encode("utf-8")).hexdigest() if item_fragment else None)
        receipt = {
            "schema_version": 1, "request_id": meta.get("id"), "kind": expected_kind,
            "status": status, "base": base, "code_sha256": snapshot["sha256"],
            "code_files": snapshot["files"], "doc_sha256": doc_sha256,
            "impacts": impacts, "conflicts": remaining, "validators": validators,
            "decision": args.decision, "decision_by": args.decision_by,
            "stage": args.stage or meta.get("stage"), "pr": args.pr, "commit": args.commit,
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        write_record(request_path, receipt)
        payload = {"status": status, "request": meta.get("id"), "base": base,
                   "code_sha256": snapshot["sha256"], "changed_documents": list(doc_sha256),
                   "conflicts": remaining, "validators": validators}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else
              f"回推 {status}：{meta.get('id')}；文档 {len(doc_sha256)} 份；冲突 {len(remaining)}")
        return 2 if remaining else (1 if validator_failed else 0)
    except (PlanError, OSError, LayoutError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--unit", required=True, help="请求 ID 或任务 ID")
    parser.add_argument("--from", dest="from_", default=None, help="git commit/range；缺省用请求 base_commit")
    parser.add_argument("--kind", choices=("bug", "change"), default="bug")
    parser.add_argument("--stage", choices=("prod", "integration", "test"), default=None)
    parser.add_argument("--decision", default=None, help="语义冲突的明确结论")
    parser.add_argument("--decision-by", default=None)
    parser.add_argument("--clause-text", default=None, help="需求变更的明确条款正文")
    parser.add_argument("--pr", default=None)
    parser.add_argument("--commit", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run(args, Path(args.root).resolve())


if __name__ == "__main__":
    sys.exit(main())
