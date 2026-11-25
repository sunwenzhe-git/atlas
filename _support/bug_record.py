#!/usr/bin/env python3
"""Canonical defect backflow record schema, history, and atomic storage."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from _support.layout import LayoutError, load_layout

RECORD_FILE = "record.json"
SCHEMA_VERSION = 1
BACKFLOW_STATUSES = ("pending", "needs_decision", "ready", "applied", "not_applicable")
STAGES = ("prod", "integration", "test")
IMPACT_KINDS = ("prd", "ac", "e2e", "spec")
IMPACT_ACTIONS = ("update", "confirmed", "pending")
CONFLICT_STATUSES = ("open", "resolved")
HISTORY_EVENTS = ("bootstrap", "analysis", "decision_applied", "validated", "linked")
SOURCE_MODES = ("staged", "range")
OBJECT_TYPES = ("blob", "symlink", "commit", "unknown")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
MODE_RE = re.compile(r"^[0-7]{6}$")
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

TOP_KEYS = {
    "schema_version", "id", "dedupe_key", "backflow_status", "stage", "report",
    "root_cause", "impact", "conflicts", "documents", "decisions", "history",
    "source", "links", "content_sha256",
}
NESTED_KEYS = {
    "report": {"path", "sha256"},
    "impact": {"id", "conflict_id", "kind", "target", "evidence", "action"},
    "conflicts": {"id", "path", "old", "new", "reason", "status"},
    "documents": {"path", "action", "version", "change_ref", "before_sha256", "after_sha256"},
    "version": {"supported", "before", "after"},
    "decisions": {"id", "conflict_id", "path", "old_sha256", "old", "new", "by", "at", "conclusion"},
    "history": {"seq", "prev_content_sha256", "event", "source_sha256", "document_sha256", "at", "event_sha256"},
    "source": {"mode", "base", "head", "implementation_files", "sha256"},
    "implementation_files": {"path", "old_oid", "new_oid", "old_mode", "new_mode", "obj_type"},
    "links": {"commits", "pull_requests"},
}


class BugRecordError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def record_content_hash(record: dict) -> str:
    payload = {k: v for k, v in record.items() if k != "content_sha256"}
    return sha256_bytes(canonical_bytes(payload))


def event_content_hash(event: dict) -> str:
    payload = {k: v for k, v in event.items() if k != "event_sha256"}
    return sha256_bytes(canonical_bytes(payload))


def refresh_hashes(record: dict) -> None:
    for event in record.get("history", []):
        event["event_sha256"] = event_content_hash(event)
    record["content_sha256"] = record_content_hash(record)


def _keys(value: object, expected: set[str], label: str, findings: list[str]) -> bool:
    if not isinstance(value, dict):
        findings.append(f"{label} 不是 object")
        return False
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        findings.append(f"{label} 键集不符：缺={missing} 多={extra}")
    return True


def _string(value: object, label: str, findings: list[str], *, nonempty: bool = False) -> bool:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        findings.append(f"{label} 必须为{'非空 ' if nonempty else ''}string")
        return False
    return True


def _sha(value: object, label: str, findings: list[str], *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        findings.append(f"{label} 必须为 64-hex sha256")


def _oid(value: object, label: str, findings: list[str]) -> None:
    if not isinstance(value, str) or not OID_RE.fullmatch(value):
        findings.append(f"{label} 必须为 40/64-hex OID")


def _datetime(value: object, label: str, findings: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        findings.append(f"{label} 必须为非空 date-time string")
        return
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        findings.append(f"{label} 不是合法 ISO date-time")


def _requirement_metadata(req_root: Path) -> dict[str, str]:
    path = req_root / "requirement.md"
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}
    fields: dict[str, str] = {}
    for key in ("类型", "关联需求", "状态", "结论", "证据"):
        match = re.search(rf"^\*\*{re.escape(key)}\*\*[：:]\s*(.*?)\s*$", text, re.M)
        if match:
            fields[key] = match.group(1).strip()
    return fields


def _document_path_findings(root: Path | None, req_root: Path | None,
                            rel: object, label: str) -> list[str]:
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        return [f"{label} 不是合法项目根相对路径"]
    if root is None or req_root is None:
        return []
    root = root.resolve()
    raw = root / rel
    if raw.is_symlink():
        return [f"{label} 不得为 symlink"]
    try:
        candidate = raw.parent.resolve() / raw.name
        layout = load_layout(root)
    except (OSError, RuntimeError, LayoutError):
        return [f"{label} 无法解析"]
    if root not in candidate.parents:
        return [f"{label} 逃逸项目根"]
    allowed = [layout.assets_root.resolve(), layout.adr_dir.resolve(),
               layout.prd_dir.resolve(), layout.e2e_dir.resolve(),
               req_root.resolve(), (root / ".atlas/spec").resolve()]
    if not any(candidate == base or base in candidate.parents for base in allowed):
        return [f"{label} 不在合法资产/spec 面"]
    req_rel = candidate.relative_to(req_root.resolve()).as_posix() if req_root.resolve() in candidate.parents else ""
    if req_rel in (RECORD_FILE, "work/缺陷报告.md"):
        return [f"{label} 不得指向台账或缺陷报告自身"]
    return []


def _unique_ids(items: list[object], label: str, findings: list[str]) -> set[str]:
    ids: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            findings.append(f"{label}[{index}] 必须为 object")
            continue
        value = item.get("id")
        if not isinstance(value, str) or not value:
            findings.append(f"{label}[{index}].id 必须为非空 string")
            continue
        if value in ids:
            findings.append(f"{label}.id 重复：{value}")
        ids.add(value)
    return ids


def validate_record(record: object, *, requirement_root: Path | None = None,
                    root: Path | None = None) -> list[str]:
    findings: list[str] = []
    if not _keys(record, TOP_KEYS, "record", findings):
        return findings
    assert isinstance(record, dict)
    if record.get("schema_version") != SCHEMA_VERSION:
        findings.append("schema_version 必须为 1")
    slug = record.get("id")
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
        findings.append("id 不是合法 slug")
    if requirement_root is not None and slug != requirement_root.name:
        findings.append(f"record.id={slug!r} 与目录 slug={requirement_root.name!r} 不一致")
    _string(record.get("dedupe_key"), "dedupe_key", findings, nonempty=True)
    if record.get("backflow_status") not in BACKFLOW_STATUSES:
        findings.append(f"backflow_status 非法：{record.get('backflow_status')!r}")
    if record.get("stage") not in STAGES:
        findings.append(f"stage 非法：{record.get('stage')!r}")
    _string(record.get("root_cause"), "root_cause", findings)
    _sha(record.get("content_sha256"), "content_sha256", findings)
    if isinstance(record.get("content_sha256"), str) and SHA256_RE.fullmatch(record["content_sha256"]):
        if record["content_sha256"] != record_content_hash(record):
            findings.append("content_sha256 与当前 record 内容不一致")

    report = record.get("report")
    if _keys(report, NESTED_KEYS["report"], "report", findings):
        assert isinstance(report, dict)
        if report.get("path") != "work/缺陷报告.md":
            findings.append("report.path 必须固定为 work/缺陷报告.md")
        _sha(report.get("sha256"), "report.sha256", findings)

    metadata = _requirement_metadata(requirement_root) if requirement_root is not None else {}
    if requirement_root is not None and isinstance(report, dict):
        report_path = requirement_root / "work" / "缺陷报告.md"
        if not report_path.is_file() or report_path.is_symlink():
            findings.append("work/缺陷报告.md 缺失或为 symlink")
        else:
            try:
                actual = sha256_bytes(report_path.read_bytes())
            except OSError:
                actual = ""
            if actual != report.get("sha256"):
                findings.append("report.sha256 与 work/缺陷报告.md 当前内容不一致")
        related = metadata.get("关联需求")
        expected_dedupe = f"{related}:{report.get('sha256')}"
        if related and record.get("dedupe_key") != expected_dedupe:
            findings.append("dedupe_key 必须为 <关联需求>:<report.sha256>")

    impact = record.get("impact")
    conflicts = record.get("conflicts")
    decisions = record.get("decisions")
    documents = record.get("documents")
    for value, label in ((impact, "impact"), (conflicts, "conflicts"),
                         (decisions, "decisions"), (documents, "documents")):
        if not isinstance(value, list):
            findings.append(f"{label} 必须为 array")
    impact_items = [item for item in impact if isinstance(item, dict)] if isinstance(impact, list) else []
    conflict_items = [item for item in conflicts if isinstance(item, dict)] if isinstance(conflicts, list) else []
    decision_items = [item for item in decisions if isinstance(item, dict)] if isinstance(decisions, list) else []
    document_items = [item for item in documents if isinstance(item, dict)] if isinstance(documents, list) else []
    for value, label in ((impact, "impact"), (conflicts, "conflicts"),
                         (decisions, "decisions"), (documents, "documents")):
        if isinstance(value, list):
            for index, item in enumerate(value):
                if not isinstance(item, dict):
                    findings.append(f"{label}[{index}] 必须为 object")
    conflict_ids = _unique_ids(conflict_items, "conflicts", findings)
    decision_ids = _unique_ids(decision_items, "decisions", findings)
    _unique_ids(impact_items, "impact", findings)

    for index, item in enumerate(impact_items):
        label = f"impact[{index}]"
        if not _keys(item, NESTED_KEYS["impact"], label, findings):
            continue
        if item.get("kind") not in IMPACT_KINDS:
            findings.append(f"{label}.kind 非法")
        if item.get("action") not in IMPACT_ACTIONS:
            findings.append(f"{label}.action 非法")
        _string(item.get("target"), f"{label}.target", findings, nonempty=True)
        _string(item.get("evidence"), f"{label}.evidence", findings, nonempty=True)
        conflict_id = item.get("conflict_id")
        if conflict_id is not None and conflict_id not in conflict_ids:
            findings.append(f"{label}.conflict_id 指向不存在的 conflict：{conflict_id!r}")
        if item.get("action") == "pending" and not conflict_id:
            findings.append(f"{label} action=pending 必须有 conflict_id")

    for index, item in enumerate(conflict_items):
        label = f"conflicts[{index}]"
        if not _keys(item, NESTED_KEYS["conflicts"], label, findings):
            continue
        _string(item.get("path"), f"{label}.path", findings, nonempty=True)
        findings.extend(_document_path_findings(root, requirement_root, item.get("path"), f"{label}.path"))
        _string(item.get("old"), f"{label}.old", findings)
        _string(item.get("new"), f"{label}.new", findings)
        _string(item.get("reason"), f"{label}.reason", findings, nonempty=True)
        if item.get("status") not in CONFLICT_STATUSES:
            findings.append(f"{label}.status 非法")

    document_paths: set[str] = set()
    for index, item in enumerate(document_items):
        label = f"documents[{index}]"
        if not _keys(item, NESTED_KEYS["documents"], label, findings):
            continue
        path = item.get("path")
        _string(path, f"{label}.path", findings, nonempty=True)
        findings.extend(_document_path_findings(root, requirement_root, path, f"{label}.path"))
        if isinstance(path, str):
            if path in document_paths:
                findings.append(f"documents.path 重复：{path}")
            document_paths.add(path)
        if item.get("action") not in ("update", "confirmed"):
            findings.append(f"{label}.action 非法")
        version = item.get("version")
        if _keys(version, NESTED_KEYS["version"], f"{label}.version", findings):
            assert isinstance(version, dict)
            if not isinstance(version.get("supported"), bool):
                findings.append(f"{label}.version.supported 必须为 bool")
            for key in ("before", "after"):
                if version.get(key) is not None:
                    _string(version[key], f"{label}.version.{key}", findings, nonempty=True)
            if version.get("supported") is False and (version.get("before") is not None or version.get("after") is not None):
                findings.append(f"{label} supported=false 时 before/after 必须为 null")
            if version.get("supported") is True and (not version.get("before") or not version.get("after")):
                findings.append(f"{label} supported=true 时 before/after 必须非空")
        if item.get("change_ref") is not None:
            _string(item["change_ref"], f"{label}.change_ref", findings, nonempty=True)
        _sha(item.get("before_sha256"), f"{label}.before_sha256", findings)
        _sha(item.get("after_sha256"), f"{label}.after_sha256", findings)

    for index, item in enumerate(decision_items):
        label = f"decisions[{index}]"
        if not _keys(item, NESTED_KEYS["decisions"], label, findings):
            continue
        conflict = next((c for c in conflict_items if c.get("id") == item.get("conflict_id")), None)
        if conflict is not None:
            if item.get("path") != conflict.get("path"):
                findings.append(f"{label}.path 与 conflict.path 不一致")
            if conflict.get("old") and item.get("old") != conflict.get("old"):
                findings.append(f"{label}.old 与 conflict.old 不一致")
        else:
            findings.append(f"{label}.conflict_id 指向不存在的 conflict")
        _string(item.get("path"), f"{label}.path", findings, nonempty=True)
        findings.extend(_document_path_findings(root, requirement_root, item.get("path"), f"{label}.path"))
        _sha(item.get("old_sha256"), f"{label}.old_sha256", findings)
        _string(item.get("old"), f"{label}.old", findings, nonempty=True)
        _string(item.get("new"), f"{label}.new", findings)
        _string(item.get("by"), f"{label}.by", findings, nonempty=True)
        _datetime(item.get("at"), f"{label}.at", findings)
        _string(item.get("conclusion"), f"{label}.conclusion", findings, nonempty=True)

    history = record.get("history")
    if not isinstance(history, list) or not history:
        findings.append("history 必须为非空 array")
        history_items = []
    else:
        history_items = history
    for index, event in enumerate(history_items):
        label = f"history[{index}]"
        if not _keys(event, NESTED_KEYS["history"], label, findings):
            continue
        if event.get("seq") != index + 1:
            findings.append(f"{label}.seq 必须为 {index + 1}")
        if index == 0 and event.get("prev_content_sha256") is not None:
            findings.append("history[0].prev_content_sha256 必须为 null")
        if index > 0:
            _sha(event.get("prev_content_sha256"), f"{label}.prev_content_sha256", findings)
        if event.get("event") not in HISTORY_EVENTS:
            findings.append(f"{label}.event 非法")
        if event.get("source_sha256") is not None:
            _sha(event.get("source_sha256"), f"{label}.source_sha256", findings)
        doc_hashes = event.get("document_sha256")
        if not isinstance(doc_hashes, dict):
            findings.append(f"{label}.document_sha256 必须为 object")
        else:
            for path, digest in doc_hashes.items():
                _string(path, f"{label}.document_sha256 key", findings, nonempty=True)
                _sha(digest, f"{label}.document_sha256[{path!r}]", findings)
        _datetime(event.get("at"), f"{label}.at", findings)
        _sha(event.get("event_sha256"), f"{label}.event_sha256", findings)
        if isinstance(event.get("event_sha256"), str) and SHA256_RE.fullmatch(event["event_sha256"]):
            if event["event_sha256"] != event_content_hash(event):
                findings.append(f"{label}.event_sha256 与事件内容不一致")

    source = record.get("source")
    if _keys(source, NESTED_KEYS["source"], "source", findings):
        assert isinstance(source, dict)
        if source.get("mode") not in SOURCE_MODES:
            findings.append("source.mode 非法")
        _string(source.get("base"), "source.base", findings, nonempty=True)
        _string(source.get("head"), "source.head", findings, nonempty=True)
        _sha(source.get("sha256"), "source.sha256", findings)
        files = source.get("implementation_files")
        if not isinstance(files, list):
            findings.append("source.implementation_files 必须为 array")
            files = []
        seen_paths: set[str] = set()
        for index, item in enumerate(files):
            label = f"source.implementation_files[{index}]"
            if not _keys(item, NESTED_KEYS["implementation_files"], label, findings):
                continue
            path = item.get("path")
            _string(path, f"{label}.path", findings, nonempty=True)
            if isinstance(path, str):
                if path in seen_paths:
                    findings.append(f"source.implementation_files.path 重复：{path}")
                seen_paths.add(path)
            _oid(item.get("old_oid"), f"{label}.old_oid", findings)
            _oid(item.get("new_oid"), f"{label}.new_oid", findings)
            for key in ("old_mode", "new_mode"):
                if not isinstance(item.get(key), str) or not MODE_RE.fullmatch(item[key]):
                    findings.append(f"{label}.{key} 必须为六位 octal mode")
            if item.get("obj_type") not in OBJECT_TYPES:
                findings.append(f"{label}.obj_type 非法")

    links = record.get("links")
    if _keys(links, NESTED_KEYS["links"], "links", findings):
        assert isinstance(links, dict)
        for key in ("commits", "pull_requests"):
            value = links.get(key)
            if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
                findings.append(f"links.{key} 必须为非空 string array")
            elif len(set(value)) != len(value):
                findings.append(f"links.{key} 不得重复")

    status = record.get("backflow_status")
    if status in ("ready", "applied"):
        if not str(record.get("root_cause") or "").strip():
            findings.append("ready/applied 必须非空 root_cause")
        if not impact_items or not document_items:
            findings.append("ready/applied 必须同时有 impact 与 documents")
        if not isinstance(source, dict) or not source.get("implementation_files"):
            findings.append("ready/applied 必须至少有一个实现文件")
        if any(item.get("action") == "pending" for item in impact_items):
            findings.append("ready/applied 不得保留 pending impact")
        if any(item.get("status") == "open" for item in conflict_items):
            findings.append("ready/applied 不得保留 open conflict")
        resolved_by_decisions = {d.get("conflict_id") for d in decision_items}
        for conflict in conflict_items:
            if conflict.get("status") == "resolved" and conflict.get("id") not in resolved_by_decisions:
                findings.append(f"resolved conflict {conflict.get('id')!r} 缺 decision")
        for item in impact_items:
            if item.get("action") == "pending":
                continue
            target = item.get("target")
            has_document = any(d.get("path") == target or str(target).startswith(str(d.get("path")) + "#")
                               for d in document_items)
            if not has_document and item.get("conflict_id") not in resolved_by_decisions:
                findings.append(f"impact {item.get('id')!r} 无 document 或已应用 decision 支撑")
    if status == "needs_decision":
        if not any(item.get("status") == "open" for item in conflict_items):
            findings.append("needs_decision 必须至少有一个 open conflict")
        if not any(item.get("action") == "pending" for item in impact_items):
            findings.append("needs_decision 必须至少有一个 pending impact")
    if status == "not_applicable":
        if isinstance(source, dict) and source.get("implementation_files"):
            findings.append("not_applicable 不得有实现 diff")
        if isinstance(links, dict) and (links.get("commits") or links.get("pull_requests")):
            findings.append("not_applicable 不得有 commit/PR 链接")
        if requirement_root is not None:
            if metadata.get("结论") not in ("重复", "非缺陷", "不修"):
                findings.append("not_applicable 必须写合法分诊结论")
            if not metadata.get("证据"):
                findings.append("not_applicable 必须写非空证据")
    return findings


def new_record(slug: str, related: str, stage: str, report_sha256: str) -> dict:
    if stage not in STAGES:
        raise BugRecordError(f"非法 stage：{stage!r}")
    now = utc_now()
    record = {
        "schema_version": SCHEMA_VERSION,
        "id": slug,
        "dedupe_key": f"{related}:{report_sha256}",
        "backflow_status": "pending",
        "stage": stage,
        "report": {"path": "work/缺陷报告.md", "sha256": report_sha256},
        "root_cause": "",
        "impact": [],
        "conflicts": [],
        "documents": [],
        "decisions": [],
        "history": [{
            "seq": 1, "prev_content_sha256": None, "event": "bootstrap",
            "source_sha256": None, "document_sha256": {}, "at": now,
            "event_sha256": "",
        }],
        "source": {
            "mode": "staged", "base": "HEAD", "head": "WORKTREE",
            "implementation_files": [], "sha256": "",
        },
        "links": {"commits": [], "pull_requests": []},
        "content_sha256": "",
    }
    source_payload = {k: v for k, v in record["source"].items() if k != "sha256"}
    record["source"]["sha256"] = sha256_bytes(canonical_bytes(source_payload))
    refresh_hashes(record)
    return record


def append_history(record: dict, event: str, *, source_sha256: str | None,
                   document_sha256: dict[str, str]) -> None:
    if event not in HISTORY_EVENTS:
        raise BugRecordError(f"非法 history event：{event!r}")
    previous = record.get("content_sha256")
    record.setdefault("history", []).append({
        "seq": len(record["history"]) + 1,
        "prev_content_sha256": previous,
        "event": event,
        "source_sha256": source_sha256,
        "document_sha256": dict(sorted(document_sha256.items())),
        "at": utc_now(),
        "event_sha256": "",
    })
    refresh_hashes(record)


def read_record(requirement_root: Path) -> dict | None:
    path = Path(requirement_root) / RECORD_FILE
    if not path.is_file() or path.is_symlink():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_record(requirement_root: Path, record: dict) -> None:
    findings = validate_record(record, requirement_root=Path(requirement_root))
    if findings:
        raise BugRecordError("；".join(findings))
    atomic_write_bytes(Path(requirement_root) / RECORD_FILE,
                       json.dumps(record, ensure_ascii=False, indent=2,
                                  sort_keys=True).encode("utf-8") + b"\n")
