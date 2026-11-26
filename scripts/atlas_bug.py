#!/usr/bin/env python3
"""atlas change — canonical requirement-change/defect intake, backflow, and audit queries."""
# ATLAS_CHANGE_AUTO_V1
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from _support.bug_backflow import (
    BackflowError, _apply_transaction, _run, analyze_impact, artifact_paths, bootstrap_defect,
    dedupe_findings, resolve_defect_root, run_validators, source_snapshot, staged_paths,
    strict_requirement_fields, validate_backflow,
)
from _support.bug_record import (
    RECORD_FILE, REPORT_PATHS, append_history, dedupe_key_for, new_record, read_record,
    refresh_hashes, sha256_bytes, utc_now, validate_record, write_record,
)
from _support.layout import LayoutError, load_layout
from _support.workflow_causes import exit_code_for
from _support.workflow_plan import PlanError, load_tasks, strip_fences


def _emit(payload: dict, as_json: bool) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
          if as_json else json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _error(exc: Exception, as_json: bool) -> int:
    cause = getattr(exc, "cause", "bug_backflow_invalid")
    if as_json:
        _emit({"status": "error", "cause": cause, "message": str(exc)}, True)
    else:
        print(f"ERROR: {exc}", file=sys.stderr)
    return exit_code_for(cause)


def _mode_and_base(root: Path, value: str | None) -> tuple[str, str | None]:
    if value == "staged":
        return "staged", None
    if value:
        if ".." not in value:
            return "range", f"{value}..HEAD"
        return "range", value
    if staged_paths(root):
        return "staged", None
    from _support.bug_backflow import default_base
    return "range", f"{default_base(root)}...HEAD"


def _report_field(req_root: Path, report_rel: str, keys: tuple[str, ...]) -> str:
    path = Path(req_root) / report_rel
    try:
        text = strip_fences(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise BackflowError(f"报告不可读：{exc}", cause="bug_backflow_missing")
    values = []
    for key in keys:
        values.extend(re.findall(rf"^\*\*{re.escape(key)}\*\*[：:]\s*(.*?)\s*$", text, re.M))
    unique = list(dict.fromkeys(value.strip() for value in values if value.strip()))
    if len(unique) > 1:
        raise BackflowError(f"报告字段 {keys[0]} 重复或冲突", cause="bug_backflow_pending")
    return unique[0] if unique else ""


def _stage_artifacts(root: Path, req_root: Path, record: dict) -> None:
    paths = sorted(artifact_paths(root, req_root, record))
    _run(root, ["git", "add", "--", *paths])


def _decision_replacements(root: Path, req_root: Path, record: dict,
                           source_sha256: str, path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BackflowError(f"决策文件不可读：{exc}", cause="bug_backflow_pending")
    if not isinstance(payload, dict) or payload.get("unit", payload.get("bug")) != record["id"]:
        raise BackflowError("决策文件 unit 与当前变更/缺陷不一致", cause="bug_backflow_pending")
    if payload.get("source_sha256") != source_sha256:
        raise BackflowError("决策文件 source_sha256 与当前实现 diff 不一致", cause="bug_backflow_pending")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise BackflowError("决策文件 decisions 必须为非空 array", cause="bug_backflow_pending")
    required = {"id", "conflict_id", "path", "old_sha256", "old", "new", "by", "at", "conclusion"}
    replacements: list[dict] = []
    seen: set[str] = set()
    conflict_items = {item["id"]: item for item in record.get("conflicts", [])}
    for index, item in enumerate(decisions):
        if not isinstance(item, dict) or set(item) != required:
            raise BackflowError(f"决策文件 decisions[{index}] 键集不符", cause="bug_backflow_pending")
        if item["id"] in seen:
            raise BackflowError(f"决策 id 重复：{item['id']}", cause="bug_backflow_pending")
        seen.add(item["id"])
        conflict = conflict_items.get(item["conflict_id"])
        if conflict is None:
            raise BackflowError(f"决策 conflict_id 不存在：{item['conflict_id']}",
                                cause="bug_backflow_pending")
        if item["path"] != conflict["path"]:
            raise BackflowError("决策 path 与 conflict.path 不一致", cause="bug_backflow_pending")
        if conflict.get("old") and item["old"] != conflict["old"]:
            raise BackflowError("决策 old 与 conflict.old 不一致", cause="bug_backflow_pending")
        for key in ("id", "conflict_id", "path", "old_sha256", "old", "by", "at", "conclusion"):
            if not isinstance(item[key], str) or not item[key]:
                raise BackflowError(f"决策 {key} 必须为非空 string", cause="bug_backflow_pending")
        if not isinstance(item["new"], str):
            raise BackflowError("决策 new 必须为 string", cause="bug_backflow_pending")
        replacements.append(item)
    covered = {item["conflict_id"] for item in replacements}
    open_ids = {key for key, item in conflict_items.items() if item.get("status") == "open"}
    missing = sorted(open_ids - covered)
    if missing:
        raise BackflowError("决策未覆盖全部 conflict：" + "、".join(missing),
                            cause="bug_backflow_pending")
    return replacements


def _confirmed_documents(record: dict) -> list[str]:
    paths: set[str] = set()
    for impact in record.get("impact", []):
        if impact.get("conflict_id"):
            continue
        target = str(impact.get("target") or "")
        path = target.split("#", 1)[0]
        if path and path != "diff":
            paths.add(path)
    return sorted(paths)


def _scan_records(root: Path) -> list[tuple[Path, dict, list[str]]]:
    base = load_layout(root).assets_root / "requirements"
    paths = sorted(base.glob("*/record.json")) if base.is_dir() else []
    if (base / "archive").is_dir():
        paths.extend(sorted((base / "archive").glob("*/*/record.json")))
    rows = []
    for path in paths:
        req_root = path.parent
        record = read_record(req_root)
        if record is None:
            rows.append((req_root, {}, ["record.json 不可解析"]))
            continue
        findings = validate_record(record, requirement_root=req_root, root=root)
        findings.extend(dedupe_findings(root, record, req_root))
        rows.append((req_root, record, findings))
    return rows


def run(args: argparse.Namespace, root: Path) -> int:
    root = root.resolve()
    action = args.action or "run"
    if not args.unit and args.slug:
        args.unit = args.slug
    if action == "list":
        target = args.target
        rows = []
        for req_root, record, findings in _scan_records(root):
            if not record:
                continue
            impacts = record.get("impact") or []
            if target and not any(target in str(item.get("target")) for item in impacts):
                continue
            rows.append({
                "id": record.get("id"), "status": record.get("backflow_status"),
                "stage": record.get("stage"), "requirement_root": str(req_root.relative_to(root)),
                "targets": [item.get("target") for item in impacts], "findings": findings,
            })
        _emit({"status": "ok", "changes": rows, "bugs": rows}, args.json)
        return 0

    if not args.unit:
        raise BackflowError("必须提供 --unit <slug>", cause="bug_backflow_missing")
    req_root = resolve_defect_root(root, args.unit)
    inherited_task = None
    if req_root is None:
        tasks_root = root / ".atlas" / "tasks"
        if tasks_root.is_dir():
            inherited_task = next((item for item in load_tasks(tasks_root, include_archived=True)
                                   if item.get("id") == args.unit), None)
        if inherited_task and inherited_task.get("requirement_root"):
            req_root = resolve_defect_root(root, Path(str(inherited_task["requirement_root"])).name)
    if req_root is None:
        kind = getattr(args, "kind", None) or "缺陷"
        if action != "run" or not args.requirement or not args.report or not args.stage:
            raise BackflowError(
                "落点不存在；新建需 --requirement <slug#R-NN> --report <path> --stage <prod|integration|test>",
                cause="bug_backflow_missing")
        try:
            report_text = Path(args.report).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise BackflowError(f"报告不可读：{exc}", cause="bug_backflow_missing")
        req_root = bootstrap_defect(root, args.unit, args.requirement, report_text,
                                    args.stage, kind=kind)
        record = read_record(req_root)
        assert record is not None
        if getattr(args, "auto_stage", False):
            _stage_artifacts(root, req_root, record)
        _emit({"status": "created", "unit": args.unit, "bug": args.unit,
               "requirement_root": str(req_root.relative_to(root)),
               "next": "确认 requirement.md 后运行 atlas workflow plan --requirement <root>"}, args.json)
        return 0

    fields, field_findings = strict_requirement_fields(req_root)
    declared = fields.get("类型")
    if field_findings or declared not in REPORT_PATHS:
        raise BackflowError("；".join(field_findings or ["requirement.md 类型必须为需求变更或缺陷"]),
                            cause="bug_backflow_invalid")
    if args.requirement and fields.get("关联需求") != args.requirement:
        raise BackflowError("--requirement 与 requirement.md 关联需求不一致",
                            cause="bug_backflow_invalid")
    report_rel = REPORT_PATHS[declared]
    report_path = req_root / report_rel
    if not report_path.is_file() or report_path.is_symlink():
        raise BackflowError(f"{report_rel} 缺失或为 symlink", cause="bug_backflow_missing")
    related = fields.get("关联需求")
    if not related:
        raise BackflowError(f"{declared}未关联既有需求", cause="bug_backflow_invalid")
    record_path = req_root / RECORD_FILE
    record = read_record(req_root)
    stage_source = "record"
    metadata_changed = False
    if record is None:
        if record_path.exists() or action != "run":
            raise BackflowError("record.json 缺失或不可解析", cause="bug_backflow_missing")
        report_sha = sha256_bytes(report_path.read_bytes())
        if args.stage:
            stage, stage_source = args.stage, "cli"
        else:
            stage = _report_field(req_root, report_rel, ("阶段",)) or "prod"
            stage_source = "report" if stage != "prod" else "default"
        record = new_record(req_root.name, related, stage, report_sha, report_path=report_rel)
        keys = ("根因",) if declared == "缺陷" else ("变更原因", "原因")
        record["root_cause"] = _report_field(req_root, report_rel, keys)
        refresh_hashes(record)
        write_record(req_root, record)
        metadata_changed = True
    else:
        if record.get("report", {}).get("path") != report_rel:
            raise BackflowError("record.report.path 与 requirement.md 类型不一致",
                                cause="bug_backflow_invalid")
        report_sha = sha256_bytes(report_path.read_bytes())
        if record["report"]["sha256"] != report_sha:
            record["report"]["sha256"] = report_sha
            record["dedupe_key"] = dedupe_key_for(declared, report_rel, related, report_sha)
            refresh_hashes(record)
            write_record(req_root, record)
            metadata_changed = True
        if args.stage and record["stage"] != args.stage:
            record["stage"] = args.stage
            stage_source = "cli"
            refresh_hashes(record)
            write_record(req_root, record)
            metadata_changed = True
        if args.root_cause is not None and record.get("root_cause") != args.root_cause:
            record["root_cause"] = args.root_cause
            refresh_hashes(record)
            metadata_changed = True
        elif not str(record.get("root_cause") or "").strip():
            keys = ("根因",) if declared == "缺陷" else ("变更原因", "原因")
            record["root_cause"] = _report_field(req_root, report_rel, keys)
            if record["root_cause"]:
                refresh_hashes(record)
                write_record(req_root, record)
                metadata_changed = True
    findings = validate_record(record, requirement_root=req_root, root=root)
    findings.extend(dedupe_findings(root, record, req_root))
    if findings:
        raise BackflowError("；".join(findings), cause="bug_backflow_invalid")

    if action == "show":
        _emit({"status": "ok", "record": record, "findings": findings}, args.json)
        return 0
    if action == "link":
        if not args.commit and not args.pr:
            raise BackflowError("link 至少需要 --commit 或 --pr", cause="bug_backflow_missing")
        changed = False
        if args.commit and args.commit not in record["links"]["commits"]:
            record["links"]["commits"].append(args.commit)
            changed = True
        if args.pr and args.pr not in record["links"]["pull_requests"]:
            record["links"]["pull_requests"].append(args.pr)
            changed = True
        if changed:
            append_history(record, "linked", source_sha256=record["source"]["sha256"],
                           document_sha256={item["path"]: item["after_sha256"]
                                            for item in record["documents"]})
            write_record(req_root, record)
        _emit({"status": "ok", "unchanged": not changed, "unit": args.unit, "bug": args.unit,
               "links": record["links"]}, args.json)
        return 0

    mode, base = _mode_and_base(root, args.from_)
    existing_artifacts = artifact_paths(root, req_root, record)
    source = source_snapshot(root, mode, base, existing_artifacts)
    fresh = validate_backflow(root, {"requirement_root": str(req_root.relative_to(root))})
    if (record.get("backflow_status") == "applied"
            and source["sha256"] == record["source"]["sha256"]
            and not metadata_changed and not fresh["findings"]):
        if args.commit or args.pr:
            changed = False
            if args.commit and args.commit not in record["links"]["commits"]:
                record["links"]["commits"].append(args.commit)
                changed = True
            if args.pr and args.pr not in record["links"]["pull_requests"]:
                record["links"]["pull_requests"].append(args.pr)
                changed = True
            if changed:
                append_history(record, "linked", source_sha256=record["source"]["sha256"],
                               document_sha256={item["path"]: item["after_sha256"]
                                                for item in record["documents"]})
                write_record(req_root, record)
            _emit({"status": "ok", "unchanged": not changed, "unit": args.unit, "bug": args.unit,
                   "links": record["links"]}, args.json)
            return 0
        if args.decision_file:
            try:
                replay = json.loads(Path(args.decision_file).read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise BackflowError(f"决策文件不可读：{exc}", cause="bug_backflow_pending")
            replay_decisions = replay.get("decisions") if isinstance(replay, dict) else None
            known = {item.get("id") for item in record.get("decisions", [])}
            if (isinstance(replay_decisions, list) and replay_decisions
                    and all(isinstance(item, dict) and item.get("id") in known
                            for item in replay_decisions)
                    and replay.get("source_sha256") == source["sha256"]):
                _emit({"status": "ok", "unchanged": True, "unit": args.unit, "bug": args.unit,
                       "source_sha256": source["sha256"]}, args.json)
                return 0
        elif args.root_cause is None and not args.commit and not args.pr:
            _emit({"status": "ok", "unchanged": True, "unit": args.unit, "bug": args.unit,
                   "source_sha256": source["sha256"]}, args.json)
            return 0
    previous_status = record.get("backflow_status")
    previous_source = record.get("source", {}).get("sha256")
    previous_impacts = record.get("impact")
    previous_conflicts = record.get("conflicts")
    previous_root_cause = record.get("root_cause")
    decision_paths: set[str] = set()
    if args.decision_file:
        try:
            decision_payload = json.loads(Path(args.decision_file).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BackflowError(f"决策文件不可读：{exc}", cause="bug_backflow_pending")
        decisions_value = decision_payload.get("decisions") if isinstance(decision_payload, dict) else None
        if not isinstance(decisions_value, list) or not decisions_value:
            raise BackflowError("决策文件 decisions 必须为非空 array", cause="bug_backflow_pending")
        for item in decisions_value:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item["path"]:
                raise BackflowError("决策文件 path 必须为非空 string", cause="bug_backflow_pending")
            decision_paths.add(item["path"])
    analysis_artifacts = existing_artifacts | decision_paths
    analysis_source = source_snapshot(root, mode, base, analysis_artifacts)
    impacts, conflicts = analyze_impact(root, req_root, analysis_source, analysis_artifacts)
    record["impact"] = impacts
    confirmed = _confirmed_documents(record)
    final_artifacts = analysis_artifacts | set(confirmed)
    source = source_snapshot(root, mode, base, final_artifacts)
    merged = {item.get("id"): dict(item) for item in (record.get("conflicts") or [])
              if isinstance(item, dict)}
    for item in conflicts:
        merged[item["id"]] = dict(item)
    record["conflicts"] = [merged[key] for key in sorted(merged)]
    if args.root_cause is not None:
        record["root_cause"] = args.root_cause
    record["source"] = source
    refresh_hashes(record)
    replacements = []
    if args.decision_file:
        replacements = _decision_replacements(root, req_root, record, source["sha256"],
                                              Path(args.decision_file))
    open_conflicts = [item for item in record["conflicts"] if item.get("status") == "open"]

    if args.dry_run:
        _emit({"status": "conflict" if open_conflicts and not replacements else "ok",
               "unit": args.unit, "bug": args.unit, "source": source, "impacts": impacts,
               "conflicts": open_conflicts, "would_update": sorted(final_artifacts)}, args.json)
        return 2 if open_conflicts and not replacements else 0

    if open_conflicts and not replacements:
        unchanged = (previous_status == "needs_decision"
                     and previous_source == source["sha256"]
                     and previous_impacts == impacts
                     and previous_conflicts == record["conflicts"]
                     and previous_root_cause == record.get("root_cause"))
        if unchanged:
            _emit({"status": "ok", "unchanged": True, "unit": args.unit, "bug": args.unit,
                   "source_sha256": source["sha256"]}, args.json)
            return 0
        record["backflow_status"] = "needs_decision"
        append_history(record, "analysis", source_sha256=source["sha256"],
                       document_sha256={})
        write_record(req_root, record)
        _emit({"status": "conflict", "cause": "bug_backflow_pending",
               "unit": args.unit, "bug": args.unit, "conflicts": open_conflicts,
               "record": str((req_root / RECORD_FILE).relative_to(root))}, args.json)
        return 2
    if not str(record.get("root_cause") or "").strip():
        raise BackflowError("进入 ready/applied 前必须在报告填写根因/变更原因或传 --root-cause",
                            cause="bug_backflow_pending")
    if not confirmed and not replacements:
        raise BackflowError("没有可确认的回推文档", cause="bug_backflow_pending")

    include_structure = any(item.get("kind") == "spec" for item in impacts)
    results, _after_hashes = _apply_transaction(
        root, req_root, record, replacements, confirmed, include_structure=include_structure)
    if args.commit or args.pr:
        changed = False
        if args.commit and args.commit not in record["links"]["commits"]:
            record["links"]["commits"].append(args.commit)
            changed = True
        if args.pr and args.pr not in record["links"]["pull_requests"]:
            record["links"]["pull_requests"].append(args.pr)
            changed = True
        if changed:
            append_history(record, "linked", source_sha256=record["source"]["sha256"],
                           document_sha256={item["path"]: item["after_sha256"]
                                            for item in record["documents"]})
            write_record(req_root, record)
    if getattr(args, "auto_stage", False):
        _stage_artifacts(root, req_root, record)
    _emit({"status": "ok", "unit": args.unit, "bug": args.unit,
           "backflow_status": record["backflow_status"], "stage": record["stage"],
           "stage_source": stage_source, "source_sha256": record["source"]["sha256"],
           "changed_documents": [item["path"] for item in record["documents"]],
           "validators": results}, args.json)
    return 0


def main(default_kind: str = "缺陷") -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("run", "show", "list", "link"), default="run")
    parser.add_argument("slug", nargs="?", help="show/link 的变更或缺陷 slug")
    parser.add_argument("--root", default=".")
    parser.add_argument("--unit")
    parser.add_argument("--kind", choices=("需求变更", "缺陷"))
    parser.add_argument("--requirement")
    parser.add_argument("--report")
    parser.add_argument("--stage", choices=("prod", "integration", "test"))
    parser.add_argument("--from", dest="from_")
    parser.add_argument("--root-cause")
    parser.add_argument("--decision-file")
    parser.add_argument("--commit")
    parser.add_argument("--pr")
    parser.add_argument("--target")
    parser.add_argument("--auto-stage", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.kind is None:
        args.kind = default_kind
    try:
        return run(args, Path(args.root))
    except (BackflowError, PlanError, LayoutError, OSError, ValueError) as exc:
        return _error(exc, args.json)


if __name__ == "__main__":
    sys.exit(main())
