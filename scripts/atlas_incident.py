#!/usr/bin/env python3
"""Atlas Incident CLI (RFC-20261125-01 §7).

Commands: open, event, link, close, check. The timeline is authoritative and
all mutations are validated before publication. Default mode is shadow; use
--mode enforce for rc1 deterministic failures and --mode off for UNVERIFIED/rc2.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _support.incident import (  # noqa: E402
    IncidentError, add_action, add_evidence, add_hypothesis, check_incident,
    close_incident, contain_incident, incident_error_result, link_incident,
    open_incident, resolve_incident, rollback_incident, update_action, with_repair_commands,
)


def _actor(args: argparse.Namespace) -> str:
    return args.actor or os.environ.get("USER") or "oncall"


def _resolution_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root-cause-summary", "--root-cause", dest="root_cause_summary")
    parser.add_argument("--root-cause-ref", action="append")
    parser.add_argument("--resolution-summary", "--resolution", dest="resolution_summary")
    parser.add_argument("--verification-ref", "--verification", dest="verification_ref", action="append")
    parser.add_argument("--verified-by")
    parser.add_argument("--verified-at")
    parser.add_argument("--before")
    parser.add_argument("--after")


def _resolve(args: argparse.Namespace, root: Path) -> dict:
    required = ("root_cause_summary", "root_cause_ref", "resolution_summary", "verification_ref",
                "verified_by", "verified_at", "before", "after")
    missing = [name for name in required if not getattr(args, name)]
    if missing:
        raise IncidentError("resolution 缺少参数：" + ", ".join("--" + name.replace("_", "-") for name in missing))
    return resolve_incident(
        root, args.id, root_cause_summary=args.root_cause_summary,
        root_cause_refs=args.root_cause_ref, resolution_summary=args.resolution_summary,
        verification_refs=args.verification_ref, verified_by=args.verified_by,
        verified_at=args.verified_at, before=args.before, after=args.after,
        summary=args.summary or "完成根因分析与修复验收", actor=_actor(args),
        ts=args.ts, mode=args.mode)


def _event(args: argparse.Namespace, root: Path) -> dict:
    common = {"summary": args.summary or args.kind, "actor": _actor(args), "ts": args.ts, "mode": args.mode}
    if args.kind == "evidence":
        return add_evidence(root, args.id, evidence_id=args.evidence_id, path=args.path,
                            evidence_type=args.evidence_type, replace=args.replace_evidence, **common)
    if args.kind == "hypothesis":
        return add_hypothesis(root, args.id, hypothesis_id=args.hypothesis_id,
                              statement=args.statement, status=args.hypothesis_status,
                              evidence_refs=args.evidence_ref, **common)
    if args.kind == "action":
        if args.update_action:
            return update_action(root, args.id, action_id=args.action_id, status=args.action_status,
                                 waiver=args.waiver, summary=args.summary or "更新行动项状态或 waiver",
                                 actor=_actor(args), ts=args.ts, mode=args.mode)
        return add_action(root, args.id, action_id=args.action_id, task_id=args.task_id,
                          owner=args.owner, due=args.due, status=args.action_status or "open",
                          waiver=args.waiver, **common)
    if args.kind == "resolution":
        return _resolve(args, root)
    if args.kind == "status":
        return contain_incident(root, args.id, **common)
    if args.kind == "rollback":
        return rollback_incident(root, args.id, reason=args.summary or "修复回退", **{k: v for k, v in common.items() if k != "summary"})
    raise IncidentError(f"未知事件类型：{args.kind}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--mode", choices=("shadow", "enforce", "off"), default=None,
                        help="覆盖本次校验模式；open 未给时默认 shadow")
    parser.add_argument("--json", action="store_true", dest="as_json")
    sub = parser.add_subparsers(dest="command", required=True)

    opening = sub.add_parser("open", help="创建 detected Incident")
    opening.add_argument("--title", required=True)
    opening.add_argument("--environment", required=True)
    opening.add_argument("--owner", default=os.environ.get("USER") or "oncall")
    opening.add_argument("--severity", choices=("SEV1", "SEV2", "SEV3", "SEV4"), default="SEV3")
    opening.add_argument("--service", action="append", dest="services")
    opening.add_argument("--impact", default="影响评估中")
    opening.add_argument("--started-at")
    opening.add_argument("--detected-at")
    opening.add_argument("--ts", help="事件时间（测试/回放用；缺省当前 UTC）")
    opening.add_argument("--id", dest="incident_id")
    opening.add_argument("--actor")

    event = sub.add_parser("event", help="追加证据/假设/行动项/处置/状态/回退事件")
    event.add_argument("id")
    event.add_argument("--kind", required=True, choices=("evidence", "hypothesis", "action", "resolution", "status", "rollback"))
    event.add_argument("--summary")
    event.add_argument("--actor")
    event.add_argument("--ts")
    event.add_argument("--evidence-id")
    event.add_argument("--replace-evidence", action="store_true")
    event.add_argument("--path")
    event.add_argument("--evidence-type")
    event.add_argument("--hypothesis-id")
    event.add_argument("--statement")
    event.add_argument("--hypothesis-status", choices=("open", "supported", "rejected"), default="open")
    event.add_argument("--evidence-ref", action="append")
    event.add_argument("--action-id")
    event.add_argument("--task-id")
    event.add_argument("--owner")
    event.add_argument("--due")
    event.add_argument("--action-status", choices=("open", "done"), default=None)
    event.add_argument("--waiver")
    event.add_argument("--update-action", action="store_true", help="追加更新已有非任务 action 的 status/waiver")
    _resolution_options(event)

    link = sub.add_parser("link", help="关联 request/task/review/spec")
    link.add_argument("id")
    link.add_argument("--request", dest="request_id")
    link.add_argument("--task", action="append", dest="task_ids")
    link.add_argument("--review-ref", action="append")
    link.add_argument("--spec-ref", action="append")
    link.add_argument("--summary")
    link.add_argument("--actor")
    link.add_argument("--ts")

    closing = sub.add_parser("close", help="校验并关闭 resolved Incident；--force 不绕门")
    closing.add_argument("id")
    closing.add_argument("--summary")
    closing.add_argument("--actor")
    closing.add_argument("--ts")
    closing.add_argument("--force", action="store_true")
    _resolution_options(closing)

    checking = sub.add_parser("check", help="校验一个或全部 Incident")
    checking.add_argument("id", nargs="?")
    checking.add_argument("--force", action="store_true", help="保留兼容；不绕过校验")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).absolute()
    try:
        if args.command == "open":
            result = open_incident(root, title=args.title, environment=args.environment,
                                   owner=args.owner, severity=args.severity, services=args.services,
                                   impact=args.impact, started_at=args.started_at,
                                   detected_at=args.detected_at, incident_id=args.incident_id,
                                   actor=_actor(args), mode=args.mode, now=args.ts)
        elif args.command == "event":
            result = _event(args, root)
        elif args.command == "link":
            result = link_incident(root, args.id, request_id=args.request_id, task_ids=args.task_ids,
                                   review_refs=args.review_ref, spec_refs=args.spec_ref,
                                   summary=args.summary or "关联需求/任务/评审/规格", actor=_actor(args),
                                   ts=args.ts, mode=args.mode)
        elif args.command == "close":
            if args.root_cause_summary:
                # Also support the RFC shorthand: close --resolution ... from contained.
                resolve_incident(root, args.id, root_cause_summary=args.root_cause_summary,
                                 root_cause_refs=args.root_cause_ref,
                                 resolution_summary=args.resolution_summary,
                                 verification_refs=args.verification_ref, verified_by=args.verified_by,
                                 verified_at=args.verified_at, before=args.before, after=args.after,
                                 summary=args.summary or "完成根因分析与修复验收", actor=_actor(args),
                                 ts=args.ts, mode=args.mode)
            result = close_incident(root, args.id, summary=args.summary or "关闭 Incident",
                                    actor=_actor(args), ts=args.ts, mode=args.mode, force=args.force)
        else:
            result = check_incident(root, args.id, mode=args.mode, force=args.force)
    except (OSError, ValueError, RuntimeError, IncidentError) as exc:
        result = incident_error_result(exc, args.mode)
    with_repair_commands(result, root, getattr(args, "id", getattr(args, "incident_id", None)))
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(f"[{result['verdict']}] incident rc={result['rc']} cause={result['cause']} mode={result['mode']}")
        if result.get("path"):
            print(f"[{result['verdict']}] {result['path']}")
        for finding in result["findings"]:
            print(f"[{result['verdict']}] {finding.get('path', 'incident')}: {finding['message']}")
    return result["rc"]


if __name__ == "__main__":
    sys.exit(main())
