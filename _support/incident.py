"""RFC-20261125-01 §7 Incident lifecycle, evidence and timeline authority.

The append-only ``timeline.jsonl`` is authoritative. Each event stores a
canonical JSON envelope in its frozen ``summary`` field: human-readable text
plus structured operation data. ``incident.json`` and ``report.md`` are
regenerated projections and are never accepted as independent evidence.

The first status/open event persists the module kill-switch mode. Missing mode
means shadow; off always reports UNVERIFIED/rc2. All writes use governance_io
safe paths and atomic publication, and candidates are validated before any
bytes are changed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shlex
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

from _support.filelock import lock_exclusive as _lock_exclusive, unlock as _unlock_file
from _support.governance_io import GovernancePathError, atomic_write_bytes, load_json, safe_path
from _support.governance_schema import load_schema, validate
from _support.layout import LayoutError, load_layout

MODULE = "incident"
MODES = ("shadow", "enforce", "off")
INCIDENT_RE = re.compile(r"^INC-[0-9]{8}-[0-9]{3}$")
_EVIDENCE_CAUSE = "incident_evidence_missing"
_STATE_CAUSE = "incident_not_resolved"


class IncidentError(ValueError):
    """An Incident operation is unsafe, invalid, or would violate the lifecycle."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _projection_bytes(value: dict) -> bytes:
    # canonical_bytes sorts arrays; Incident arrays are ordered replay history.
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def _mode(value: str | None) -> str:
    mode = value or "shadow"
    if mode not in MODES:
        raise IncidentError("mode 必须为 shadow/enforce/off")
    return mode


def configured_mode(root: str | Path) -> str | None:
    value = os.environ.get("ATLAS_INCIDENT_MODE")
    if not value:
        path = Path(root) / ".atlas" / "config.yaml"
        if path.is_file() and not path.is_symlink():
            match = re.search(r"^\s*incident_mode\s*:\s*(shadow|enforce|off)\b",
                              path.read_text(encoding="utf-8"), re.M)
            value = match.group(1) if match else None
    return _mode(value) if value else None


def _selected_mode(root: Path, explicit: str | None, persisted: str | None = None) -> str:
    return _mode(explicit or configured_mode(root) or persisted or "shadow")


def _error_mode(root: Path, explicit: str | None) -> str:
    try:
        return _selected_mode(root, explicit)
    except OSError:
        return explicit or "enforce"


def _finding(message: str, cause: str = _STATE_CAUSE, path: str | None = None) -> dict:
    return {"cause": cause, "message": message, **({"path": path} if path else {})}


def _result(verdict: str, rc: int, findings: list[dict], cause: str | None = None,
            mode: str = "shadow", path: str | None = None) -> dict:
    if mode == "off":
        verdict, rc, cause = "UNVERIFIED", 2, None
    elif mode == "shadow":
        rc = 0
    return {"schema_version": 1, "module": MODULE, "mode": mode, "verdict": verdict,
            "cause": cause, "rc": rc, "findings": findings, **({"path": path} if path else {})}


def incident_error_result(exc: Exception, mode: str | None = None) -> dict:
    """Fail closed for CLI/validator environmental and usage failures."""
    selected = "off" if mode == "off" else "enforce"
    return _result("UNVERIFIED", 2, [_finding(f"{type(exc).__name__}: {exc}", "incident_unverified")],
                   None if selected == "off" else "incident_unverified", selected, "incidents")


def with_repair_commands(result: dict, root: str | Path, incident_id: str | None = None) -> dict:
    """Attach copyable repair/check commands to findings without changing verdicts."""
    root = Path(root).absolute()
    cli = Path(__file__).resolve().parent.parent / "scripts" / "atlas_incident.py"
    prefix = f"python3 {shlex.quote(str(cli))} --root {shlex.quote(str(root))}"
    target = f" {incident_id}" if incident_id else ""
    for finding in result.get("findings") or []:
        if finding.get("cause") == _STATE_CAUSE and "逾期" in finding["message"]:
            repair = f"{prefix} event{target} --kind action --action-id <ACTION-ID> --update-action --waiver <批准理由> --mode enforce"
        elif finding.get("cause") == _STATE_CAUSE and incident_id:
            repair = f"{prefix}{target} close --mode enforce（resolved 后可执行；contained 先补根因/验收）"
        else:
            repair = f"{prefix} check{target} --mode enforce"
        finding["message"] += f"；修复/复核命令：{repair}"
    return result


def _failure_result(findings: list[dict], mode: str, root: Path, incident_id: str) -> dict:
    cause = _EVIDENCE_CAUSE if any(item["cause"] == _EVIDENCE_CAUSE for item in findings) else _STATE_CAUSE
    return _result("FAIL", 1, findings, cause, mode,
                   _relative(root, incident_directory(root, incident_id)))


def _incidents_rel(root: Path) -> str:
    layout = load_layout(root)
    rel = layout.assets_root.absolute().relative_to(root.absolute()).as_posix()
    safe_path(root, rel)
    return rel


def incident_directory(root: str | Path, incident_id: str) -> Path:
    """Return the safe project path for one incident ID."""
    root = Path(root).absolute()
    if not INCIDENT_RE.fullmatch(incident_id):
        raise IncidentError(f"非法 Incident ID：{incident_id}")
    return safe_path(root, f"{_incidents_rel(root)}/incidents/{incident_id}")


def _relative(root: Path, path: Path) -> str:
    return path.absolute().relative_to(root.absolute()).as_posix()


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise IncidentError(f"JSON 重复键：{key}")
        value[key] = item
    return value


def _read_timeline(path: Path) -> list[dict]:
    events: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise IncidentError(f"timeline.jsonl 第 {number} 行为空")
        try:
            event = json.loads(line, object_pairs_hook=_unique)
        except (json.JSONDecodeError, IncidentError) as exc:
            raise IncidentError(f"timeline.jsonl 第 {number} 行不可读取：{exc}") from exc
        events.append(event)
    if not events:
        raise IncidentError("timeline.jsonl 不得为空")
    return events


def _envelope(text: str, data: dict) -> str:
    if not text.strip():
        raise IncidentError("事件 summary 不得为空")
    return json.dumps({"text": text, "data": data}, ensure_ascii=False,
                      sort_keys=True, separators=(",", ":"))


def _payload(event: dict) -> tuple[str, dict]:
    try:
        value = json.loads(event["summary"], object_pairs_hook=_unique)
    except (json.JSONDecodeError, IncidentError, TypeError) as exc:
        raise IncidentError(f"事件 {event.get('id')} summary 不是本模块的 JSON envelope：{exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("text"), str) \
            or not isinstance(value.get("data"), dict):
        raise IncidentError(f"事件 {event.get('id')} summary 缺 text/data")
    return value["text"], value["data"]


def _event(incident_id: str, events: list[dict], kind: str, text: str, data: dict,
           ts: str, actor: str, evidence_refs: list[str] | None = None,
           from_status: str | None = None, to_status: str | None = None) -> dict:
    used = {event.get("id") for event in events}
    serial = len(events) + 1
    while f"{incident_id}-T{serial:04d}" in used:
        serial += 1
    value = {"schema_version": 1, "id": f"{incident_id}-T{serial:04d}", "ts": ts,
             "kind": kind, "actor": actor, "summary": _envelope(text, data),
             "evidence_refs": evidence_refs or []}
    if from_status is not None or to_status is not None or kind == "rollback":
        value["from"] = from_status
        value["to"] = to_status
    errors = validate(value, load_schema("incident-timeline-event"))
    if errors:
        raise IncidentError("timeline event schema: " + "; ".join(errors))
    return value


def _merge_links(current: dict, data: dict) -> dict:
    links = copy.deepcopy(current)
    request = data.get("request_id")
    if request is not None:
        if links.get("request_id") not in (None, request):
            raise IncidentError("一个 Incident 只能关联一个 request_id")
        links["request_id"] = request
    for key in ("task_ids", "review_refs", "spec_refs"):
        for item in data.get(key) or []:
            if not isinstance(item, str) or not item:
                raise IncidentError(f"{key} 必须是非空字符串")
            if item not in links[key]:
                links[key].append(item)
    return links


def _replay(events: list[dict]) -> tuple[dict | None, str, list[dict]]:
    """Reconstruct state from authority, returning semantic transition errors."""
    findings: list[dict] = []
    seen_events: set[str] = set()
    evidence_ids: set[str] = set()
    hypothesis_ids: set[str] = set()
    action_ids: set[str] = set()
    incident = None
    mode = "shadow"
    previous_ts = None
    for index, event in enumerate(events):
        label = f"timeline[{index}]"
        errors = validate(event, load_schema("incident-timeline-event"))
        if errors:
            findings.append(_finding(f"{label} schema: " + "; ".join(errors), _EVIDENCE_CAUSE, "timeline.jsonl"))
            continue
        event_id = event["id"]
        if event_id in seen_events:
            findings.append(_finding(f"{label} 重复事件 ID：{event_id}", _STATE_CAUSE, "timeline.jsonl"))
        seen_events.add(event_id)
        try:
            timestamp = _parse_time(event["ts"])
        except ValueError:
            findings.append(_finding(f"{label} 时间非法", _STATE_CAUSE, "timeline.jsonl"))
            timestamp = None
        if timestamp is not None:
            if previous_ts is not None and timestamp < previous_ts:
                findings.append(_finding(f"{label} 时间早于前一事件", _STATE_CAUSE, "timeline.jsonl"))
            previous_ts = timestamp
        try:
            text, data = _payload(event)
        except IncidentError as exc:
            findings.append(_finding(str(exc), _STATE_CAUSE, "timeline.jsonl"))
            continue
        operation = data.get("operation")
        if index == 0:
            if event["kind"] != "status" or operation != "open" or not isinstance(data.get("incident"), dict):
                findings.append(_finding("首个事件必须是 status/open", _STATE_CAUSE, "timeline.jsonl"))
                continue
            incident = copy.deepcopy(data["incident"])
            mode = _mode(data.get("mode"))
            if incident.get("status") != "detected" or event.get("from") is not None \
                    or event.get("to") != "detected":
                findings.append(_finding("open 事件必须创建 detected 状态", _STATE_CAUSE, "timeline.jsonl"))
            for item in incident.get("evidence") or []:
                if item.get("id") in evidence_ids:
                    findings.append(_finding(f"重复证据 ID：{item.get('id')}", _EVIDENCE_CAUSE))
                evidence_ids.add(item.get("id"))
            continue
        if incident is None:
            continue
        expected_from = None
        expected_to = None
        if event["kind"] == "evidence" and operation in ("evidence", "evidence_replace"):
            item = data.get("evidence")
            if not isinstance(item, dict):
                findings.append(_finding(f"{label} 缺 evidence 数据", _EVIDENCE_CAUSE))
                continue
            existing = next((i for i, evidence in enumerate(incident["evidence"])
                             if evidence.get("id") == item.get("id")), None)
            if existing is not None and operation == "evidence":
                findings.append(_finding(f"重复证据 ID：{item.get('id')}", _EVIDENCE_CAUSE))
            elif existing is not None:
                incident["evidence"][existing] = copy.deepcopy(item)
            else:
                if operation == "evidence_replace":
                    findings.append(_finding(f"替换不存在的证据 ID：{item.get('id')}", _EVIDENCE_CAUSE))
                incident["evidence"].append(copy.deepcopy(item))
            evidence_ids.add(item.get("id"))
        elif event["kind"] == "hypothesis" and operation == "hypothesis":
            item = data.get("hypothesis")
            if not isinstance(item, dict):
                findings.append(_finding(f"{label} 缺 hypothesis 数据", _EVIDENCE_CAUSE))
                continue
            if item.get("id") in hypothesis_ids:
                findings.append(_finding(f"重复假设 ID：{item.get('id')}", _STATE_CAUSE))
            hypothesis_ids.add(item.get("id"))
            incident["hypotheses"].append(copy.deepcopy(item))
        elif event["kind"] == "action" and operation == "action":
            item = data.get("action")
            if not isinstance(item, dict):
                findings.append(_finding(f"{label} 缺 action 数据", _STATE_CAUSE))
                continue
            if item.get("id") in action_ids:
                findings.append(_finding(f"重复行动项 ID：{item.get('id')}", _STATE_CAUSE))
            action_ids.add(item.get("id"))
            incident["actions"].append(copy.deepcopy(item))
        elif event["kind"] == "action" and operation == "action_update":
            item = data.get("action")
            if not isinstance(item, dict):
                findings.append(_finding(f"{label} 缺 action_update 数据", _STATE_CAUSE))
                continue
            index = next((i for i, action in enumerate(incident["actions"])
                          if isinstance(action, dict) and action.get("id") == item.get("id")), None)
            if index is None:
                findings.append(_finding(f"{label} 更新不存在的行动项：{item.get('id')}", _STATE_CAUSE))
            elif "task_id" in incident["actions"][index]:
                findings.append(_finding(f"{label} 任务型行动项只存 task_id，不得复制或更新任务字段", _STATE_CAUSE))
            else:
                incident["actions"][index] = copy.deepcopy(item)
        elif event["kind"] == "action" and operation == "link":
            try:
                incident["links"] = _merge_links(incident["links"], data.get("links") or {})
            except IncidentError as exc:
                findings.append(_finding(str(exc), _STATE_CAUSE))
        elif event["kind"] == "status" and operation == "contain":
            if incident["status"] != "detected":
                findings.append(_finding(f"{label} 非法 contained 迁移：{incident['status']}", _STATE_CAUSE))
            expected_from, expected_to = "detected", "contained"
            incident["previous_status"] = incident["status"]
            incident["status"] = "contained"
            incident["resolved_at"] = None
        elif event["kind"] == "resolution" and operation == "resolution":
            if incident["status"] != "contained":
                findings.append(_finding(f"{label} 非法 resolved 迁移：{incident['status']}", _STATE_CAUSE))
            expected_from, expected_to = "contained", "resolved"
            incident["previous_status"] = incident["status"]
            incident["status"] = "resolved"
            incident["resolved_at"] = event["ts"]
            incident["root_cause"] = copy.deepcopy(data.get("root_cause"))
            incident["resolution"] = copy.deepcopy(data.get("resolution"))
        elif event["kind"] == "rollback" and operation == "rollback":
            if incident["status"] != "resolved":
                findings.append(_finding(f"{label} 非法 rollback：仅 resolved→contained", _STATE_CAUSE))
            if not str(text).strip():
                findings.append(_finding(f"{label} rollback 缺理由", _STATE_CAUSE))
            expected_from, expected_to = "resolved", "contained"
            incident["previous_status"] = "resolved"
            incident["status"] = "contained"
            incident["resolved_at"] = None
            # Deliberately retain evidence, root_cause and resolution.
        elif event["kind"] == "status" and operation == "close":
            if incident["status"] != "resolved":
                findings.append(_finding(f"{label} 非法 closed 迁移：{incident['status']}", _STATE_CAUSE))
            expected_from, expected_to = "resolved", "closed"
            incident["previous_status"] = incident["status"]
            incident["status"] = "closed"
        else:
            findings.append(_finding(f"{label} 未知操作 {event['kind']}/{operation}", _STATE_CAUSE))
        if expected_from is not None:
            if event.get("from") != expected_from or event.get("to") != expected_to:
                findings.append(_finding(f"{label} from/to 与重放状态不一致", _STATE_CAUSE, "timeline.jsonl"))
    return incident, mode, findings


def _task_exists(root: Path, task_id: str) -> bool:
    if not task_id or Path(task_id).name != task_id or "\\" in task_id:
        return False
    try:
        candidates = [safe_path(root, f".atlas/tasks/{task_id}/task.json")]
        archive = safe_path(root, ".atlas/tasks/archive")
        if archive.is_dir():
            candidates.extend(safe_path(root, f".atlas/tasks/archive/{month}/{task_id}/task.json")
                              for month in archive.iterdir() if re.fullmatch(r"\d{4}-\d{2}", month.name))
        for path in candidates:
            if path.is_file() and not path.is_symlink():
                value = load_json(path)
                if isinstance(value, dict) and value.get("id") == task_id:
                    return True
        return False
    except (ValueError, GovernancePathError):
        return False


def _semantic_findings(root: Path, incident: dict, events: list[dict], *, now: str) -> list[dict]:
    findings: list[dict] = []
    errors = validate(incident, load_schema("incident"))
    for error in errors:
        cause = _EVIDENCE_CAUSE if any(token in error for token in ("evidence", "root_cause", "resolution", "resolved_at")) else _STATE_CAUSE
        findings.append(_finding("incident schema: " + error, cause, "incident.json"))
    evidence = incident.get("evidence") if isinstance(incident.get("evidence"), list) else []
    evidence_ids = [item.get("id") for item in evidence if isinstance(item, dict)]
    if len(evidence_ids) != len(set(evidence_ids)):
        findings.append(_finding("incident.evidence 存在重复 ID", _EVIDENCE_CAUSE))
    evidence_set = set(evidence_ids)
    for item in evidence:
        if not isinstance(item, dict):
            continue
        rel = item.get("path")
        try:
            path = safe_path(root, rel)
            if not path.is_file():
                findings.append(_finding(f"证据文件不存在：{rel}（证据 {item.get('id')}）", _EVIDENCE_CAUSE, rel))
            elif _sha(path) != item.get("sha256"):
                findings.append(_finding(f"证据 sha256 不一致：{rel}（证据 {item.get('id')}）", _EVIDENCE_CAUSE, rel))
        except OSError as exc:
            raise
        except (ValueError, GovernancePathError) as exc:
            findings.append(_finding(f"证据路径不安全或不可读取：{rel}: {exc}（证据 {item.get('id')}）", _EVIDENCE_CAUSE, str(rel)))

    def refs(refs: list, label: str) -> None:
        for ref in refs or []:
            if ref not in evidence_set:
                findings.append(_finding(f"{label} 引用不存在的证据：{ref}", _EVIDENCE_CAUSE))

    hypotheses = incident.get("hypotheses") or []
    hypothesis_ids = [item.get("id") for item in hypotheses if isinstance(item, dict)]
    if len(hypothesis_ids) != len(set(hypothesis_ids)):
        findings.append(_finding("incident.hypotheses 存在重复 ID", _STATE_CAUSE))
    for item in hypotheses:
        if isinstance(item, dict):
            refs(item.get("evidence_refs"), f"假设 {item.get('id')}")
    root_cause = incident.get("root_cause")
    if isinstance(root_cause, dict):
        refs(root_cause.get("evidence_refs"), "根因")
    resolution = incident.get("resolution")
    if isinstance(resolution, dict):
        refs(resolution.get("verification_refs"), "验收")
    if incident.get("status") in ("resolved", "closed"):
        if not isinstance(root_cause, dict) or not root_cause.get("evidence_refs"):
            findings.append(_finding("resolved/closed 必须有根因及证据引用", _EVIDENCE_CAUSE))
        if not isinstance(resolution, dict) or not resolution.get("verification_refs"):
            findings.append(_finding("resolved/closed 必须有验证证据", _EVIDENCE_CAUSE))
        verified_by = resolution.get("verified_by") if isinstance(resolution, dict) else None
        if not isinstance(verified_by, str) or not verified_by.strip() or not resolution.get("verified_at"):
            findings.append(_finding("resolved/closed 必须含验证签字人和时间", _EVIDENCE_CAUSE))
        if not incident.get("resolved_at"):
            findings.append(_finding("resolved/closed 必须含 resolved_at", _STATE_CAUSE))
        if not evidence:
            findings.append(_finding("resolved/closed 至少需要一份证据", _EVIDENCE_CAUSE))
    actions = incident.get("actions") or []
    action_ids = [item.get("id") for item in actions if isinstance(item, dict)]
    if len(action_ids) != len(set(action_ids)):
        findings.append(_finding("incident.actions 存在重复 ID", _STATE_CAUSE))
    today = _parse_time(now).date()
    links = incident.get("links") or {}
    for action in actions:
        if not isinstance(action, dict):
            continue
        if "task_id" in action:
            task_id = action["task_id"]
            if task_id not in (links.get("task_ids") or []):
                findings.append(_finding(f"行动项 {action.get('id')} 的 task_id 未在 links.task_ids 追踪", _STATE_CAUSE))
            if not _task_exists(root, task_id):
                findings.append(_finding(f"行动项 {action.get('id')} 引用不存在的任务：{task_id}", _STATE_CAUSE))
        elif action.get("status") == "open" and not (
                isinstance(action.get("waiver"), str) and action["waiver"].strip()):
            try:
                overdue = date.fromisoformat(action["due"]) < today
            except (KeyError, TypeError, ValueError):
                overdue = False
            if overdue:
                findings.append(_finding(f"行动项 {action.get('id')} 已逾期且无 waiver", _STATE_CAUSE))
    for task_id in links.get("task_ids") or []:
        if not _task_exists(root, task_id):
            findings.append(_finding(f"links.task_ids 引用不存在的任务：{task_id}", _STATE_CAUSE))
    for event in events:
        if isinstance(event, dict):
            refs(event.get("evidence_refs"), f"时间线事件 {event.get('id')}")
    return findings


def _render_report(incident: dict, events: list[dict]) -> str:
    def cell(value) -> str:
        return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")

    lines = [f"# Incident {incident['id']}: {incident['title']}", "",
             f"- 状态：{incident['status']}", f"- 严重级别：{incident['severity']}",
             f"- 负责人：{incident['owner']}", f"- 环境：{incident['environment']}",
             f"- 服务：{', '.join(incident['services'])}", f"- 影响：{incident['impact']}",
             f"- 开始：{incident['started_at']}", f"- 检测：{incident['detected_at']}",
             f"- 解决：{incident.get('resolved_at') or '未解决'}", "", "## 证据", "",
              "| ID | 类型 | 路径 | SHA-256 |", "|---|---|---|---|"]
    for item in incident.get("evidence") or []:
        lines.append(f"| {cell(item.get('id'))} | {cell(item.get('type'))} | {cell(item.get('path'))} | {cell(item.get('sha256'))} |")
    lines += ["", "## 假设", ""]
    for item in incident.get("hypotheses") or []:
        lines.append(f"- {item['id']} [{item['status']}] {item['statement']}（证据：{', '.join(item['evidence_refs']) or '无'}）")
    lines += ["", "## 根因与处置", ""]
    if incident.get("root_cause"):
        lines.append(f"- 根因：{incident['root_cause']['summary']}（证据：{', '.join(incident['root_cause']['evidence_refs'])}）")
    if incident.get("resolution"):
        resolution = incident["resolution"]
        lines += [f"- 处置：{resolution['summary']}",
                  f"- 验收：{resolution['before']} → {resolution['after']}",
                  f"- 验证证据：{', '.join(resolution['verification_refs'])}",
                  f"- 签字：{resolution['verified_by']} @ {resolution['verified_at']}"]
    lines += ["", "## 行动项", ""]
    for item in incident.get("actions") or []:
        if "task_id" in item:
            lines.append(f"- {item['id']}: task {item['task_id']}")
        else:
            lines.append(f"- {item['id']}: {item['owner']} / due {item['due']} / {item['status']} / waiver {item['waiver'] or '无'}")
    links = incident.get("links") or {}
    lines += ["", "## 关联", "",
              f"- request: {links.get('request_id') or '无'}",
              f"- tasks: {', '.join(links.get('task_ids') or []) or '无'}",
              f"- reviews: {', '.join(links.get('review_refs') or []) or '无'}",
              f"- specs: {', '.join(links.get('spec_refs') or []) or '无'}", "", "## 时间线", ""]
    for event in events:
        try:
            text, _ = _payload(event)
        except IncidentError:
            text = event.get("summary", "")
        lines.append(f"- {event['ts']} / {event['kind']} / {event['actor']}: {text}")
    return "\n".join(lines) + "\n"


def _load_authority(root: Path, incident_id: str) -> tuple[dict, list[dict], str]:
    directory = incident_directory(root, incident_id)
    incident_path = safe_path(root, _relative(root, directory / "incident.json"))
    timeline_path = safe_path(root, _relative(root, directory / "timeline.jsonl"))
    report_path = safe_path(root, _relative(root, directory / "report.md"))
    if not timeline_path.is_file():
        raise IncidentError(f"timeline.jsonl 不存在：{incident_id}")
    events = _read_timeline(timeline_path)
    replayed, persisted_mode, findings = _replay(events)
    if replayed is None:
        raise IncidentError("timeline 无法重放出 Incident")
    mode = _mode(persisted_mode)
    if not incident_path.is_file():
        raise IncidentError(f"incident.json 不存在：{incident_id}")
    incident = load_json(incident_path)
    if not isinstance(incident, dict):
        raise IncidentError("incident.json 必须是对象")
    return incident, events, mode


def _projection_findings(root: Path, incident_id: str, projected: dict,
                         events: list[dict], *, now: str, require_closed: bool,
                         check_disk: bool) -> list[dict]:
    findings = _semantic_findings(root, projected, events, now=now)
    if projected.get("id") != incident_id:
        findings.append(_finding(f"Incident 数据 ID {projected.get('id')} 与目录 ID {incident_id} 不一致",
                                 _STATE_CAUSE, "incident.json"))
    if require_closed and projected.get("status") != "closed":
        findings.append(_finding(f"Incident 未关闭：当前 {projected.get('status')}", _STATE_CAUSE, "incident.json"))
    if check_disk:
        directory = incident_directory(root, incident_id)
        try:
            recorded = load_json(safe_path(root, _relative(root, directory / "incident.json")))
            if recorded != projected:
                cause = _STATE_CAUSE if recorded.get("status") != projected.get("status") else _EVIDENCE_CAUSE
                findings.append(_finding("incident.json 与 timeline.jsonl 重放结果不一致", cause, "incident.json"))
            report_path = safe_path(root, _relative(root, directory / "report.md"))
            if not report_path.is_file():
                findings.append(_finding("report.md 不存在", _STATE_CAUSE, "report.md"))
            elif report_path.read_bytes() != _render_report(projected, events).encode("utf-8"):
                findings.append(_finding("report.md 不是 timeline 数据的确定性生成物", _STATE_CAUSE, "report.md"))
        except OSError as exc:
            raise
        except (ValueError, GovernancePathError) as exc:
            findings.append(_finding(f"派生产物不可读取：{exc}", _EVIDENCE_CAUSE))
    return findings


def validate_incident_closed(root: str | Path, incident_id: str, *, incident: dict | None = None,
                             events: list[dict] | None = None, mode: str | None = None,
                             now: str | None = None, force: bool = False) -> dict:
    """Pure close/finish gate: validate closed state without writing any bytes.

    ``force`` is intentionally ignored. Optional in-memory projections let the
    close command run this exact function before publishing its candidate;
    finish calls it with only root and incident_id against persisted authority.
    """
    del force
    root = Path(root).absolute()
    now = now or _utc_now()
    try:
        if incident is None or events is None:
            recorded, persisted_events, persisted_mode = _load_authority(root, incident_id)
            projected, _, replay_findings = _replay(persisted_events)
            if projected is None:
                raise IncidentError("timeline 无法重放")
            check_disk = True
        else:
            recorded, persisted_events, persisted_mode = incident, events, mode or "shadow"
            projected, _, replay_findings = _replay(events)
            if projected is None:
                raise IncidentError("候选 timeline 无法重放")
            check_disk = False
        selected_mode = _selected_mode(root, mode, persisted_mode)
        findings = replay_findings + _projection_findings(
            root, incident_id, projected, persisted_events, now=now,
            require_closed=True, check_disk=check_disk)
        if any(f["cause"] == _EVIDENCE_CAUSE for f in findings):
            verdict, cause, rc = "FAIL", _EVIDENCE_CAUSE, 1
        elif findings:
            verdict, cause, rc = "FAIL", _STATE_CAUSE, 1
        else:
            verdict, cause, rc = "PASS", None, 0
        return _result(verdict, rc, findings, cause, selected_mode,
                       _relative(root, incident_directory(root, incident_id)))
    except OSError as exc:
        selected_mode = _error_mode(root, mode)
        if selected_mode == "off":
            return _result("UNVERIFIED", 2, [_finding(str(exc), "observation")], mode="off")
        return _result("UNVERIFIED", 2, [_finding(f"Incident I/O 不可判定：{exc}", "observation")],
                       "incident_unverified", selected_mode)
    except (ValueError, RuntimeError, LayoutError, GovernancePathError) as exc:
        selected_mode = _error_mode(root, mode)
        if selected_mode == "off":
            return _result("UNVERIFIED", 2, [_finding(str(exc), "observation")], mode="off")
        return _result("FAIL", 1, [_finding(f"无法验证关闭状态：{exc}", _EVIDENCE_CAUSE)],
                       _EVIDENCE_CAUSE, selected_mode)


def check_incident(root: str | Path, incident_id: str | None = None, *, mode: str | None = None,
                   now: str | None = None, force: bool = False) -> dict:
    """Validate one Incident, or every registered Incident when ID is omitted."""
    root = Path(root).absolute()
    now = now or _utc_now()
    try:
        if incident_id is not None:
            recorded, events, persisted_mode = _load_authority(root, incident_id)
            projected, _, replay_findings = _replay(events)
            if projected is None:
                raise IncidentError("timeline 无法重放")
            selected_mode = _selected_mode(root, mode, persisted_mode)
            findings = replay_findings + _projection_findings(
                root, incident_id, projected, events, now=now,
                require_closed=False, check_disk=True)
            if any(f["cause"] == _EVIDENCE_CAUSE for f in findings):
                verdict, cause, rc = "FAIL", _EVIDENCE_CAUSE, 1
            elif findings:
                verdict, cause, rc = "FAIL", _STATE_CAUSE, 1
            else:
                verdict, cause, rc = "PASS", None, 0
            return _result(verdict, rc, findings, cause, selected_mode,
                           _relative(root, incident_directory(root, incident_id)))
        base = safe_path(root, f"{_incidents_rel(root)}/incidents")
        if not base.exists():
            return _result("WARN", 0, [_finding("尚无已登记 Incident", "observation")],
                           mode=_mode(mode), path=_relative(root, base))
        if not base.is_dir():
            raise IncidentError("incidents 不是普通目录")
        entries = sorted((path for path in base.iterdir() if INCIDENT_RE.fullmatch(path.name)), key=lambda p: p.name)
        unsafe = [path.name for path in entries if path.is_symlink() or not path.is_dir()]
        if unsafe:
            raise IncidentError(f"Incident 目录不是普通目录或为符号链接：{', '.join(unsafe)}")
        ids = [path.name for path in entries]
        if not ids:
            return _result("WARN", 0, [_finding("尚无已登记 Incident", "observation")],
                           mode=_mode(mode), path=_relative(root, base))
        selected_mode = _selected_mode(root, mode, "enforce" if any(
            _load_authority(root, item)[2] == "enforce" for item in ids) else "shadow")
        results = [check_incident(root, item, mode=selected_mode, now=now, force=force) for item in ids]
        findings = [finding for item in results for finding in item["findings"]]
        failed = [item for item in results if item["verdict"] != "PASS"]
        if any(item["verdict"] == "UNVERIFIED" for item in failed):
            return _result("UNVERIFIED", 2, findings, "incident_unverified", selected_mode,
                           _relative(root, base))
        if failed:
            cause = _EVIDENCE_CAUSE if any(f["cause"] == _EVIDENCE_CAUSE for f in findings) else _STATE_CAUSE
            return _result("FAIL", 1, findings, cause, selected_mode, _relative(root, base))
        return _result("PASS", 0, [], mode=selected_mode, path=_relative(root, base))
    except OSError as exc:
        selected_mode = _error_mode(root, mode)
        if selected_mode == "off":
            return _result("UNVERIFIED", 2, [_finding(str(exc), "observation")], mode="off")
        return _result("UNVERIFIED", 2, [_finding(f"Incident I/O 不可判定：{exc}", "observation")],
                       "incident_unverified", selected_mode)
    except (ValueError, RuntimeError, LayoutError, GovernancePathError) as exc:
        selected_mode = _error_mode(root, mode)
        if selected_mode == "off":
            return _result("UNVERIFIED", 2, [_finding(str(exc), "observation")], mode="off")
        return _result("FAIL", 1, [_finding(f"Incident 校验失败：{exc}", _EVIDENCE_CAUSE)],
                       _EVIDENCE_CAUSE, selected_mode)


def validate_task_incidents(root: str | Path, task: dict, *, force: bool = False,
                            mode: str | None = "enforce", now: str | None = None) -> list[dict]:
    """Finish adapter: only resolves_incidents is a gate; incident_ids is not."""
    resolved = task.get("resolves_incidents") or []
    if not isinstance(resolved, list) or not all(isinstance(item, str) for item in resolved):
        raise IncidentError("resolves_incidents 必须是字符串数组")
    return [validate_incident_closed(root, incident_id, mode=mode, now=now, force=force)
            for incident_id in resolved]


def _prepare(root: Path, incident_id: str, mode: str | None, *, allow_invalid: bool = False) -> tuple[list[dict], str]:
    if not allow_invalid:
        checked = check_incident(root, incident_id, mode=mode)
        if checked["verdict"] != "PASS":
            raise IncidentError("当前 Incident 未通过校验：" + "; ".join(f["message"] for f in checked["findings"]))
    _, events, persisted_mode = _load_authority(root, incident_id)
    return events, _selected_mode(root, mode, persisted_mode)


def _publish(root: Path, incident_id: str, events: list[dict], selected_mode: str,
             *, now: str, closed: bool = False) -> dict:
    directory = incident_directory(root, incident_id)
    lock_path = safe_path(root, _relative(root, directory.parent / f".{incident_id}.lock"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    locked = False
    try:
        _lock_exclusive(fd)
        locked = True
        return _publish_locked(root, incident_id, events, selected_mode, now=now, closed=closed)
    finally:
        if locked:
            try:
                _unlock_file(fd)
            except OSError:
                pass
        os.close(fd)


def _publish_locked(root: Path, incident_id: str, events: list[dict], selected_mode: str,
                    *, now: str, closed: bool = False) -> dict:
    projected, _, replay_findings = _replay(events)
    if projected is None:
        raise IncidentError("候选 timeline 无法重放")
    if closed:
        checked = validate_incident_closed(root, incident_id, incident=projected, events=events,
                                           mode=selected_mode, now=now)
    else:
        findings = replay_findings + _projection_findings(
            root, incident_id, projected, events, now=now, require_closed=False, check_disk=False)
        if findings:
            return _failure_result(findings, selected_mode, root, incident_id)
        checked = _result("PASS", 0, [], mode=selected_mode,
                          path=_relative(root, incident_directory(root, incident_id)))
    if checked["verdict"] != "PASS":
        return checked
    directory = incident_directory(root, incident_id)
    timeline_path = safe_path(root, _relative(root, directory / "timeline.jsonl"))
    if timeline_path.is_file() and _read_timeline(timeline_path) != events[:-1]:
        raise IncidentError("timeline 已被并发更新；拒绝覆盖，请重读后重试")
    incident_path = safe_path(root, _relative(root, directory / "incident.json"))
    report_path = safe_path(root, _relative(root, directory / "report.md"))
    payload = "".join(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                      for event in events).encode("utf-8")
    # Authority is published first. A crash can leave stale projections, which
    # the next check rejects; it can never make a forged projection authoritative.
    atomic_write_bytes(timeline_path, payload)
    atomic_write_bytes(incident_path, _projection_bytes(projected))
    atomic_write_bytes(report_path, _render_report(projected, events).encode("utf-8"))
    return checked


def _next_id(root: Path, day: str) -> str:
    base = safe_path(root, f"{_incidents_rel(root)}/incidents")
    maximum = 0
    if base.exists():
        for path in base.iterdir():
            match = re.fullmatch(rf"INC-{day}-([0-9]{{3}})", path.name)
            if match:
                maximum = max(maximum, int(match.group(1)))
    if maximum >= 999:
        raise IncidentError(f"{day} 的 Incident 编号已用尽")
    return f"INC-{day}-{maximum + 1:03d}"


def open_incident(root: str | Path, *, title: str, environment: str, owner: str = "oncall",
                  severity: str = "SEV3", services: list[str] | None = None,
                  impact: str = "影响评估中", started_at: str | None = None,
                  detected_at: str | None = None, incident_id: str | None = None,
                  actor: str = "oncall", mode: str | None = None, now: str | None = None) -> dict:
    """Create a new detected Incident and its authoritative opening event."""
    root = Path(root).absolute()
    selected_mode = _selected_mode(root, mode)
    if selected_mode == "off":
        raise IncidentError("Incident 模块已关闭；in-scope 操作不可判定")
    timestamp = now or _utc_now()
    incident_id = incident_id or _next_id(root, _parse_time(timestamp).strftime("%Y%m%d"))
    directory = incident_directory(root, incident_id)
    if directory.exists() or directory.is_symlink():
        raise IncidentError(f"Incident ID 已存在：{incident_id}")
    incident = {
        "schema_version": 1, "id": incident_id, "title": title, "status": "detected",
        "severity": severity, "owner": owner, "started_at": started_at or timestamp,
        "detected_at": detected_at or timestamp, "resolved_at": None,
        "environment": environment, "services": services or ["unknown"], "impact": impact,
        "evidence": [], "hypotheses": [], "root_cause": None, "contributing_factors": [],
        "resolution": None, "actions": [],
        "links": {"request_id": None, "task_ids": [], "review_refs": [], "spec_refs": []},
        "previous_status": None,
    }
    event = _event(incident_id, [], "status", f"创建 Incident：{title}",
                   {"operation": "open", "mode": selected_mode, "incident": incident},
                   timestamp, actor, from_status=None, to_status="detected")
    events = [event]
    projected, _, findings = _replay(events)
    findings += _semantic_findings(root, projected, events, now=timestamp)
    if findings:
        raise IncidentError("新 Incident 未通过校验：" + "; ".join(f["message"] for f in findings))
    for name in ("incident.json", "timeline.jsonl", "report.md"):
        safe_path(root, _relative(root, directory / name))
    directory.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.mkdir(directory)
    except FileExistsError as exc:
        raise IncidentError(f"Incident ID 已存在：{incident_id}") from exc
    try:
        atomic_write_bytes(safe_path(root, _relative(root, directory / "timeline.jsonl")),
                           (json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
        atomic_write_bytes(safe_path(root, _relative(root, directory / "incident.json")),
                           _projection_bytes(projected))
        atomic_write_bytes(safe_path(root, _relative(root, directory / "report.md")),
                           _render_report(projected, events).encode("utf-8"))
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return _result("PASS", 0, [], mode=selected_mode, path=_relative(root, directory))


def add_evidence(root: str | Path, incident_id: str, *, evidence_id: str, path: str,
                 evidence_type: str, summary: str = "登记证据", actor: str = "oncall",
                 ts: str | None = None, mode: str | None = None, replace: bool = False) -> dict:
    """Append a path-bound SHA-256 evidence event."""
    root = Path(root).absolute()
    events, selected_mode = _prepare(root, incident_id, mode, allow_invalid=replace)
    source = safe_path(root, path)
    if not source.is_file():
        raise IncidentError(f"证据文件不存在：{path}")
    item = {"id": evidence_id, "type": evidence_type, "path": path, "sha256": _sha(source)}
    event = _event(incident_id, events, "evidence", summary,
                   {"operation": "evidence_replace" if replace else "evidence", "evidence": item},
                   ts or _utc_now(), actor)
    return _publish(root, incident_id, events + [event], selected_mode, now=ts or _utc_now())


def add_hypothesis(root: str | Path, incident_id: str, *, hypothesis_id: str, statement: str,
                   status: str = "open", evidence_refs: list[str] | None = None,
                   summary: str = "登记假设", actor: str = "oncall", ts: str | None = None,
                   mode: str | None = None) -> dict:
    """Append a hypothesis whose evidence references must already exist."""
    root = Path(root).absolute()
    events, selected_mode = _prepare(root, incident_id, mode)
    item = {"id": hypothesis_id, "statement": statement, "status": status,
            "evidence_refs": evidence_refs or []}
    event = _event(incident_id, events, "hypothesis", summary,
                   {"operation": "hypothesis", "hypothesis": item}, ts or _utc_now(), actor)
    return _publish(root, incident_id, events + [event], selected_mode, now=ts or _utc_now())


def add_action(root: str | Path, incident_id: str, *, action_id: str, task_id: str | None = None,
               owner: str | None = None, due: str | None = None, status: str = "open",
               waiver: str | None = None, summary: str = "登记行动项", actor: str = "oncall",
               ts: str | None = None, mode: str | None = None) -> dict:
    """Append either a task reference or a non-task owner/due/status/waiver action."""
    root = Path(root).absolute()
    events, selected_mode = _prepare(root, incident_id, mode)
    if task_id:
        if any(value is not None for value in (owner, due, waiver)) or status != "open":
            raise IncidentError("任务型 action 只存 id/task_id，不得复制 owner/due/status/waiver")
        item = {"id": action_id, "task_id": task_id}
    else:
        if not owner or not due:
            raise IncidentError("非任务型 action 必须提供 owner 和 due")
        item = {"id": action_id, "owner": owner, "due": due, "status": status, "waiver": waiver}
    event = _event(incident_id, events, "action", summary,
                   {"operation": "action", "action": item}, ts or _utc_now(), actor)
    return _publish(root, incident_id, events + [event], selected_mode, now=ts or _utc_now())


def update_action(root: str | Path, incident_id: str, *, action_id: str,
                  status: str | None = None, waiver: str | None = None,
                  summary: str = "更新行动项状态或 waiver", actor: str = "oncall",
                  ts: str | None = None, mode: str | None = None) -> dict:
    """Append a non-task action update, allowing an overdue waiver repair.

    Existing invalid findings are not edited in place: the complete candidate
    must still pass every gate before the append-only update is published.
    """
    root = Path(root).absolute()
    events, selected_mode = _prepare(root, incident_id, mode, allow_invalid=True)
    projected, _, findings = _replay(events)
    if projected is None or findings:
        raise IncidentError("timeline 无法安全重放：" + "; ".join(f["message"] for f in findings))
    current = next((item for item in projected["actions"] if item.get("id") == action_id), None)
    if current is None:
        raise IncidentError(f"行动项不存在：{action_id}")
    if "task_id" in current:
        raise IncidentError("任务型 action 只存 task_id；任务状态回任务卡更新")
    if status is None and waiver is None:
        raise IncidentError("至少提供 status 或 waiver")
    item = copy.deepcopy(current)
    if status is not None:
        item["status"] = status
    if waiver is not None:
        item["waiver"] = waiver
    event = _event(incident_id, events, "action", summary,
                   {"operation": "action_update", "action": item}, ts or _utc_now(), actor)
    return _publish(root, incident_id, events + [event], selected_mode, now=ts or _utc_now())


def link_incident(root: str | Path, incident_id: str, *, request_id: str | None = None,
                  task_ids: list[str] | None = None, review_refs: list[str] | None = None,
                  spec_refs: list[str] | None = None, summary: str = "关联需求/任务/评审/规格",
                  actor: str = "oncall", ts: str | None = None, mode: str | None = None) -> dict:
    """Append link metadata without treating association as finish resolution."""
    root = Path(root).absolute()
    events, selected_mode = _prepare(root, incident_id, mode)
    links = {"request_id": request_id, "task_ids": task_ids or [],
             "review_refs": review_refs or [], "spec_refs": spec_refs or []}
    event = _event(incident_id, events, "action", summary,
                   {"operation": "link", "links": links}, ts or _utc_now(), actor)
    return _publish(root, incident_id, events + [event], selected_mode, now=ts or _utc_now())


def contain_incident(root: str | Path, incident_id: str, *, summary: str = "完成遏制",
                     actor: str = "oncall", ts: str | None = None, mode: str | None = None) -> dict:
    """Append the only forward transition out of detected."""
    root = Path(root).absolute()
    events, selected_mode = _prepare(root, incident_id, mode)
    event = _event(incident_id, events, "status", summary, {"operation": "contain"},
                   ts or _utc_now(), actor, from_status="detected", to_status="contained")
    return _publish(root, incident_id, events + [event], selected_mode, now=ts or _utc_now())


def resolve_incident(root: str | Path, incident_id: str, *, root_cause_summary: str,
                     root_cause_refs: list[str], resolution_summary: str,
                     verification_refs: list[str], verified_by: str, verified_at: str,
                     before: str, after: str, summary: str = "完成根因分析与修复验收",
                     actor: str = "oncall", ts: str | None = None, mode: str | None = None) -> dict:
    """Append resolution and enter resolved only with signed, measurable verification."""
    root = Path(root).absolute()
    events, selected_mode = _prepare(root, incident_id, mode)
    root_cause = {"summary": root_cause_summary, "evidence_refs": root_cause_refs}
    resolution = {"summary": resolution_summary, "verification_refs": verification_refs,
                  "verified_by": verified_by, "verified_at": verified_at,
                  "before": before, "after": after}
    event = _event(incident_id, events, "resolution", summary,
                   {"operation": "resolution", "root_cause": root_cause, "resolution": resolution},
                   ts or _utc_now(), actor, from_status="contained", to_status="resolved")
    return _publish(root, incident_id, events + [event], selected_mode, now=ts or _utc_now())


def rollback_incident(root: str | Path, incident_id: str, *, reason: str,
                      actor: str = "oncall", ts: str | None = None, mode: str | None = None) -> dict:
    """Append resolved→contained rollback while retaining all evidence and analysis."""
    root = Path(root).absolute()
    events, selected_mode = _prepare(root, incident_id, mode)
    if not reason.strip():
        raise IncidentError("rollback 必须提供理由")
    event = _event(incident_id, events, "rollback", reason, {"operation": "rollback", "reason": reason},
                   ts or _utc_now(), actor, from_status="resolved", to_status="contained")
    return _publish(root, incident_id, events + [event], selected_mode, now=ts or _utc_now())


def close_incident(root: str | Path, incident_id: str, *, summary: str = "关闭 Incident",
                   actor: str = "oncall", ts: str | None = None, mode: str | None = None,
                   force: bool = False) -> dict:
    """Validate the closed candidate with the shared pure finish gate, then publish it."""
    del force  # Explicitly cannot bypass evidence, state or signature gates.
    root = Path(root).absolute()
    events, selected_mode = _prepare(root, incident_id, mode)
    event = _event(incident_id, events, "status", summary, {"operation": "close"},
                   ts or _utc_now(), actor, from_status="resolved", to_status="closed")
    return _publish(root, incident_id, events + [event], selected_mode, now=ts or _utc_now(), closed=True)
