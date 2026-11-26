"""RFC-20261125-01 §7 / M246 Incident positive and negative contracts.

M246: dropping verification-reference existence validation must turn the
no-verification-evidence counterexample red. The timeline is authoritative;
incident.json and report.md are checked as deterministic projections.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support.incident import (  # noqa: E402
    IncidentError,
    add_action,
    add_evidence,
    add_hypothesis,
    check_incident,
    close_incident,
    contain_incident,
    incident_directory,
    link_incident,
    open_incident,
    resolve_incident,
    rollback_incident,
    update_action,
    validate_incident_closed,
    validate_task_incidents,
)
from _support.governance_schema import load_schema, validate  # noqa: E402
from scripts.atlas_incident import main as incident_main  # noqa: E402
from validators.validate_incident import main as validator_main  # noqa: E402

INCIDENT_ID = "INC-20261125-001"
NOW = "2026-11-25T01:00:00Z"


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def evidence_file(root: Path, rel: str = "evidence/before.txt", text: str = "errors=10\n") -> Path:
    return write(root, rel, text)


def case(root: Path, incident_id: str = INCIDENT_ID) -> dict:
    return json.loads((incident_directory(root, incident_id) / "incident.json").read_text(encoding="utf-8"))


def timeline(root: Path, incident_id: str = INCIDENT_ID) -> list[dict]:
    path = incident_directory(root, incident_id) / "timeline.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def event_data(event: dict) -> dict:
    return json.loads(event["summary"])["data"]


def rewrite_event_data(root: Path, index: int, data: dict, incident_id: str = INCIDENT_ID) -> None:
    path = incident_directory(root, incident_id) / "timeline.jsonl"
    events = timeline(root, incident_id)
    payload = json.loads(events[index]["summary"])
    payload["data"] = data
    events[index]["summary"] = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    path.write_text("".join(json.dumps(e, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                            for e in events), encoding="utf-8")


def regenerate_report(root: Path, incident_id: str = INCIDENT_ID) -> None:
    from _support.incident import _render_report, _replay
    events = timeline(root, incident_id)
    projected, _, findings = _replay(events)
    assert projected is not None and findings == []
    (incident_directory(root, incident_id) / "report.md").write_text(
        _render_report(projected, events), encoding="utf-8")


def opened(root: Path, *, mode: str = "shadow", incident_id: str = INCIDENT_ID) -> dict:
    result = open_incident(root, title="支付错误率突增", environment="production", owner="oncall",
                           services=["payments"], impact="支付失败率 10%", incident_id=incident_id,
                           started_at="2026-11-25T00:55:00Z", detected_at=NOW, mode=mode, now=NOW)
    assert result["verdict"] == "PASS", result
    return result


def add_base_evidence(root: Path) -> dict:
    path = evidence_file(root)
    result = add_evidence(root, INCIDENT_ID, evidence_id="E-before", path=path.relative_to(root).as_posix(),
                          evidence_type="metric", summary="故障前指标", ts="2026-11-25T01:01:00Z")
    assert result["verdict"] == "PASS", result
    return result


def contained(root: Path) -> None:
    result = contain_incident(root, INCIDENT_ID, summary="限流并摘除故障实例", ts="2026-11-25T01:06:00Z")
    assert result["verdict"] == "PASS", result


def resolved(root: Path, *, verification_refs: list[str] | None = None) -> dict:
    result = resolve_incident(
        root, INCIDENT_ID,
        root_cause_summary="连接池配置错误",
        root_cause_refs=["E-before"],
        resolution_summary="恢复连接池配置并增加校验",
        verification_refs=verification_refs or ["E-before"],
        verified_by="release-owner", verified_at="2026-11-25T01:10:00Z",
        before="errors=10", after="errors=0", summary="修复并验证", ts="2026-11-25T01:10:00Z",
    )
    assert result["verdict"] == "PASS", result
    return result


def make_resolved(root: Path, *, mode: str = "shadow") -> None:
    opened(root, mode=mode)
    add_base_evidence(root)
    contained(root)
    resolved(root)


def test_positive_lifecycle_timeline_projection_report_and_common_schema(tmp_path):
    opened(tmp_path, mode="enforce")
    add_base_evidence(tmp_path)
    hypothesis = add_hypothesis(tmp_path, INCIDENT_ID, hypothesis_id="H-pool", statement="连接池耗尽",
                                status="supported", evidence_refs=["E-before"], ts="2026-11-25T01:03:00Z")
    assert hypothesis["verdict"] == "PASS", hypothesis
    task_dir = write(tmp_path, ".atlas/tasks/TASK-77/task.json", '{"id":"TASK-77","status":"completed"}\n')
    assert task_dir.is_file()
    link = link_incident(tmp_path, INCIDENT_ID, request_id="REQ-12", task_ids=["TASK-77"],
                         review_refs=["REV-3"], spec_refs=["SPEC-4"], ts="2026-11-25T01:04:00Z")
    assert link["verdict"] == "PASS", link
    action = add_action(tmp_path, INCIDENT_ID, action_id="A-regression", task_id="TASK-77",
                        ts="2026-11-25T01:05:00Z")
    assert action["verdict"] == "PASS", action
    contained(tmp_path)
    resolved(tmp_path)
    result = close_incident(tmp_path, INCIDENT_ID, summary="关闭故障案例", ts="2026-11-25T01:11:00Z")
    assert result["verdict"] == "PASS" and result["rc"] == 0, result

    data = case(tmp_path)
    events = timeline(tmp_path)
    assert data["status"] == "closed"
    assert [e["kind"] for e in events] == ["status", "evidence", "hypothesis", "action", "action", "status", "resolution", "status"]
    assert events[-1]["from"] == "resolved" and events[-1]["to"] == "closed"
    assert validate(data, load_schema("incident")) == []
    assert all(validate(e, load_schema("incident-timeline-event")) == [] for e in events)
    assert validate(result, load_schema("governance-common")) == []
    assert validate(check_incident(tmp_path, INCIDENT_ID), load_schema("governance-common")) == []
    report = (incident_directory(tmp_path, INCIDENT_ID) / "report.md").read_text(encoding="utf-8")
    assert "支付错误率突增" in report and "errors=10" in report and "errors=0" in report
    assert "E-before" in report and "TASK-77" in report and "连接池配置错误" in report
    assert validate_incident_closed(tmp_path, INCIDENT_ID)["verdict"] == "PASS"


def test_duplicate_incident_id_is_rejected_without_overwrite(tmp_path):
    opened(tmp_path)
    before = {p.name: p.read_bytes() for p in incident_directory(tmp_path, INCIDENT_ID).iterdir()}
    with pytest.raises(IncidentError, match="已存在"):
        open_incident(tmp_path, title="重复", environment="production", incident_id=INCIDENT_ID)
    assert before == {p.name: p.read_bytes() for p in incident_directory(tmp_path, INCIDENT_ID).iterdir()}


def test_duplicate_evidence_and_event_ids_fail_closed(tmp_path):
    opened(tmp_path)
    path = evidence_file(tmp_path)
    add_evidence(tmp_path, INCIDENT_ID, evidence_id="E-before", path=path.relative_to(tmp_path).as_posix(),
                 evidence_type="metric")
    duplicate = add_evidence(tmp_path, INCIDENT_ID, evidence_id="E-before", path=path.relative_to(tmp_path).as_posix(),
                             evidence_type="metric")
    assert duplicate["verdict"] == "FAIL" and duplicate["rc"] == 0
    events = timeline(tmp_path)
    events[-1]["id"] = events[0]["id"]
    path = incident_directory(tmp_path, INCIDENT_ID) / "timeline.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    result = check_incident(tmp_path, INCIDENT_ID, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert any("重复" in f["message"] for f in result["findings"])


def test_contained_cannot_impersonate_resolved_even_with_root_cause_and_resolution(tmp_path):
    make_resolved(tmp_path)
    rollback_incident(tmp_path, INCIDENT_ID, reason="修复后指标再次恶化", ts="2026-11-25T01:20:00Z")
    data = case(tmp_path)
    assert data["status"] == "contained" and data["root_cause"] and data["resolution"]
    data["status"] = "resolved"
    data["resolved_at"] = "2026-11-25T01:10:00Z"
    data["previous_status"] = "contained"
    (incident_directory(tmp_path, INCIDENT_ID) / "incident.json").write_text(json.dumps(data), encoding="utf-8")
    result = check_incident(tmp_path, INCIDENT_ID, mode="enforce")
    assert result["verdict"] == "FAIL" and result["cause"] == "incident_not_resolved" and result["rc"] == 1
    assert validate_incident_closed(tmp_path, INCIDENT_ID)["cause"] == "incident_not_resolved"


def test_blank_verification_signature_or_waiver_cannot_close(tmp_path):
    from _support.incident import _semantic_findings
    make_resolved(tmp_path)
    incident = case(tmp_path)
    incident["resolution"]["verified_by"] = "   "
    findings = _semantic_findings(tmp_path, incident, timeline(tmp_path), now="2026-11-25T00:00:00Z")
    assert any("签字人" in item["message"] for item in findings)
    incident = case(tmp_path)
    incident["actions"] = [{"id": "A-1", "owner": "o", "due": "2020-01-01",
                            "status": "open", "waiver": "   "}]
    findings = _semantic_findings(tmp_path, incident, timeline(tmp_path), now="2026-11-25T00:00:00Z")
    assert any("waiver" in item["message"] for item in findings)


def test_incident_error_mode_does_not_reread_unreadable_config(tmp_path, monkeypatch):
    import _support.incident as incident

    def unreadable(_root):
        raise PermissionError("injected permission")

    def unavailable(*_args, **_kwargs):
        raise OSError("injected I/O")

    monkeypatch.setattr(incident, "configured_mode", unreadable)
    monkeypatch.setattr(incident, "_load_authority", unavailable)
    result = incident.check_incident(tmp_path, INCIDENT_ID, mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert result["cause"] == "incident_unverified"


def test_incident_io_error_is_unverified_rc2(tmp_path, monkeypatch):
    import _support.incident as incident

    def unavailable(*_args, **_kwargs):
        raise OSError("injected I/O")

    monkeypatch.setattr(incident, "_load_authority", unavailable)
    result = incident.check_incident(tmp_path, INCIDENT_ID, mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert result["cause"] == "incident_unverified"


def test_incident_evidence_read_io_error_is_unverified_rc2(tmp_path, monkeypatch):
    import _support.incident as incident
    make_resolved(tmp_path)

    def unavailable(_data):
        raise PermissionError("injected permission")

    monkeypatch.setattr(incident, "_sha", unavailable)
    result = incident.check_incident(tmp_path, INCIDENT_ID, mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert result["cause"] == "incident_unverified"


def test_resolved_without_verification_evidence_fails(tmp_path):
    make_resolved(tmp_path)
    index = next(i for i, e in enumerate(timeline(tmp_path)) if e["kind"] == "resolution")
    data = event_data(timeline(tmp_path)[index])
    data["resolution"]["verification_refs"] = ["E-does-not-exist"]
    rewrite_event_data(tmp_path, index, data)
    incident = case(tmp_path)
    incident["resolution"]["verification_refs"] = ["E-does-not-exist"]
    (incident_directory(tmp_path, INCIDENT_ID) / "incident.json").write_text(json.dumps(incident), encoding="utf-8")
    regenerate_report(tmp_path)
    result = check_incident(tmp_path, INCIDENT_ID, mode="enforce")
    assert result["verdict"] == "FAIL" and result["cause"] == "incident_evidence_missing" and result["rc"] == 1
    assert any("E-does-not-exist" in f["message"] for f in result["findings"])


def test_missing_root_cause_and_hypothesis_references_fail(tmp_path):
    opened(tmp_path)
    add_base_evidence(tmp_path)
    add_hypothesis(tmp_path, INCIDENT_ID, hypothesis_id="H-pool", statement="连接池耗尽", status="supported",
                   evidence_refs=["E-before"])
    index = next(i for i, e in enumerate(timeline(tmp_path)) if e["kind"] == "hypothesis")
    data = event_data(timeline(tmp_path)[index])
    data["hypothesis"]["evidence_refs"] = ["E-missing"]
    rewrite_event_data(tmp_path, index, data)
    incident = case(tmp_path)
    incident["hypotheses"][0]["evidence_refs"] = ["E-missing"]
    (incident_directory(tmp_path, INCIDENT_ID) / "incident.json").write_text(json.dumps(incident), encoding="utf-8")
    regenerate_report(tmp_path)
    result = check_incident(tmp_path, INCIDENT_ID, mode="enforce")
    assert result["verdict"] == "FAIL" and result["cause"] == "incident_evidence_missing"
    assert any("E-missing" in f["message"] for f in result["findings"])


def test_overdue_action_without_waiver_fails_and_waiver_allows(tmp_path):
    make_resolved(tmp_path)
    add_action(tmp_path, INCIDENT_ID, action_id="A-followup", owner="oncall", due="2999-01-01", status="open",
               ts="2026-11-25T01:11:00Z")
    index = next(i for i, e in enumerate(timeline(tmp_path)) if e["kind"] == "action" and "action" in event_data(e))
    data = event_data(timeline(tmp_path)[index])
    data["action"]["due"] = "2020-01-01"
    rewrite_event_data(tmp_path, index, data)
    incident = case(tmp_path)
    incident["actions"][-1]["due"] = "2020-01-01"
    (incident_directory(tmp_path, INCIDENT_ID) / "incident.json").write_text(json.dumps(incident), encoding="utf-8")
    regenerate_report(tmp_path)
    result = check_incident(tmp_path, INCIDENT_ID, mode="enforce", now="2026-11-25T00:00:00Z")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert any("逾期" in f["message"] for f in result["findings"])
    before_events = len(timeline(tmp_path))
    repaired = update_action(tmp_path, INCIDENT_ID, action_id="A-followup",
                             waiver="负责人批准延期至回归完成", ts="2026-11-25T01:12:00Z")
    assert repaired["verdict"] == "PASS", repaired
    assert len(timeline(tmp_path)) == before_events + 1
    assert case(tmp_path)["actions"][-1]["waiver"] == "负责人批准延期至回归完成"
    assert check_incident(tmp_path, INCIDENT_ID, mode="enforce", now="2026-11-25T00:00:00Z")["verdict"] == "PASS"


def test_task_action_requires_existing_traceable_task_and_does_not_copy_fields(tmp_path):
    opened(tmp_path)
    result = add_action(tmp_path, INCIDENT_ID, action_id="A-task", task_id="TASK-missing")
    assert result["verdict"] == "FAIL" and result["rc"] == 0
    write(tmp_path, ".atlas/tasks/TASK-77/task.json", '{"id":"TASK-77","owner":"task-owner","due":"2020-01-01"}\n')
    link_incident(tmp_path, INCIDENT_ID, task_ids=["TASK-77"])
    result = add_action(tmp_path, INCIDENT_ID, action_id="A-task", task_id="TASK-77")
    assert result["verdict"] == "PASS", result
    action = case(tmp_path)["actions"][0]
    assert action == {"id": "A-task", "task_id": "TASK-77"}


def test_evidence_hash_missing_file_and_unsafe_path_fail(tmp_path):
    opened(tmp_path)
    path = evidence_file(tmp_path)
    rel = path.relative_to(tmp_path).as_posix()
    add_evidence(tmp_path, INCIDENT_ID, evidence_id="E-before", path=rel, evidence_type="metric")
    assert check_incident(tmp_path, INCIDENT_ID, mode="enforce")["verdict"] == "PASS"
    path.write_text("errors=11\n", encoding="utf-8")
    result = check_incident(tmp_path, INCIDENT_ID, mode="enforce")
    assert result["verdict"] == "FAIL" and result["cause"] == "incident_evidence_missing"
    assert any("sha256" in f["message"] for f in result["findings"])
    with pytest.raises(IncidentError):
        add_evidence(tmp_path, INCIDENT_ID, evidence_id="E-escape", path="../outside", evidence_type="metric")
    path.unlink()
    assert check_incident(tmp_path, INCIDENT_ID, mode="enforce")["cause"] == "incident_evidence_missing"


def test_symlink_evidence_and_incident_directory_escape_are_rejected(tmp_path):
    opened(tmp_path)
    outside = evidence_file(tmp_path.parent, "outside-evidence.txt")
    link = tmp_path / "evidence-link.txt"
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="符号链接"):
        add_evidence(tmp_path, INCIDENT_ID, evidence_id="E-link", path=link.name, evidence_type="metric")
    real = incident_directory(tmp_path, INCIDENT_ID)
    moved = tmp_path / "moved-incident"
    real.rename(moved)
    real.symlink_to(moved, target_is_directory=True)
    result = check_incident(tmp_path, INCIDENT_ID, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert any("符号链接" in f["message"] for f in result["findings"])


def test_rollback_retains_root_cause_resolution_and_evidence_and_appends_event(tmp_path):
    make_resolved(tmp_path)
    before = case(tmp_path)
    rollback_incident(tmp_path, INCIDENT_ID, reason="验收数字反弹", ts="2026-11-25T01:20:00Z")
    after = case(tmp_path)
    assert after["status"] == "contained" and after["previous_status"] == "resolved"
    assert after["resolved_at"] is None
    assert after["root_cause"] == before["root_cause"]
    assert after["resolution"] == before["resolution"]
    assert after["evidence"] == before["evidence"]
    event = timeline(tmp_path)[-1]
    assert event["kind"] == "rollback" and event["from"] == "resolved" and event["to"] == "contained"
    assert "验收数字反弹" in event["summary"]
    result = check_incident(tmp_path, INCIDENT_ID, mode="enforce")
    assert result["verdict"] == "PASS", result
    assert validate_incident_closed(tmp_path, INCIDENT_ID)["verdict"] == "FAIL"


def test_finish_shared_function_uses_only_resolves_incidents_and_force_does_not_bypass(tmp_path, monkeypatch):
    make_resolved(tmp_path, mode="enforce")
    close_incident(tmp_path, INCIDENT_ID, summary="关闭", ts="2026-11-25T01:11:00Z")
    calls: list[tuple[str, bool]] = []
    import _support.incident as module

    original = module.validate_incident_closed

    def spy(root, incident_id, **kwargs):
        calls.append((incident_id, kwargs.get("force", False)))
        return original(root, incident_id, **kwargs)

    monkeypatch.setattr(module, "validate_incident_closed", spy)
    assert validate_task_incidents(tmp_path, {"incident_ids": [INCIDENT_ID], "resolves_incidents": []}) == []
    assert calls == []
    results = validate_task_incidents(tmp_path, {"incident_ids": [], "resolves_incidents": [INCIDENT_ID]}, force=True)
    assert calls == [(INCIDENT_ID, True)]
    assert results[0]["verdict"] == "PASS"
    second_id = "INC-20261125-002"
    open_incident(tmp_path, title="第二个未关闭故障", environment="production", incident_id=second_id,
                  started_at="2026-11-25T01:12:00Z", detected_at="2026-11-25T01:12:00Z",
                  mode="enforce", now="2026-11-25T01:12:00Z")
    add_evidence(tmp_path, second_id, evidence_id="E-second", path="evidence/before.txt",
                 evidence_type="metric", ts="2026-11-25T01:13:00Z")
    contain_incident(tmp_path, second_id, summary="遏制", ts="2026-11-25T01:14:00Z")
    blocked = validate_task_incidents(tmp_path, {"resolves_incidents": [second_id]}, force=True)
    assert blocked[0]["verdict"] == "FAIL" and blocked[0]["rc"] == 1


def test_report_is_generated_and_tampering_is_detected(tmp_path):
    opened(tmp_path)
    path = incident_directory(tmp_path, INCIDENT_ID) / "report.md"
    original = path.read_bytes()
    assert b"Incident" in original
    path.write_text("# forged\n", encoding="utf-8")
    result = check_incident(tmp_path, INCIDENT_ID, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert any("report.md" in f["message"] for f in result["findings"])


def test_invalid_open_leaves_no_incident_directory(tmp_path):
    with pytest.raises(IncidentError, match="date-time"):
        open_incident(tmp_path, title="x", environment="test", incident_id=INCIDENT_ID,
                      started_at="2026-11-25")
    assert not incident_directory(tmp_path, INCIDENT_ID).exists()


def test_config_off_blocks_open_without_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_INCIDENT_MODE", "off")
    with pytest.raises(IncidentError, match="关闭"):
        open_incident(tmp_path, title="x", environment="test", incident_id=INCIDENT_ID)
    assert not incident_directory(tmp_path, INCIDENT_ID).exists()


def test_archived_task_action_remains_valid(tmp_path):
    opened(tmp_path, mode="enforce")
    task = write(tmp_path, ".atlas/tasks/archive/2026-11/01/task.json", json.dumps({"id": "01"}))
    add_action(tmp_path, INCIDENT_ID, action_id="A1", task_id="01")
    assert check_incident(tmp_path, INCIDENT_ID)["verdict"] == "PASS"
    assert task.is_file()


def test_project_mode_promotes_existing_shadow_and_mixed_modes_use_strictest(tmp_path):
    opened(tmp_path, mode="shadow")
    (tmp_path / ".atlas").mkdir(exist_ok=True)
    (tmp_path / ".atlas/config.yaml").write_text("incident_mode: enforce\n", encoding="utf-8")
    result = check_incident(tmp_path, INCIDENT_ID)
    assert result["mode"] == "enforce" and result["verdict"] == "PASS"
    opened(tmp_path, incident_id="INC-20261125-002", mode="shadow")
    evidence_file(tmp_path, "evidence/second.txt", "before\n")
    add_evidence(tmp_path, "INC-20261125-002", evidence_id="E2", path="evidence/second.txt", evidence_type="log")
    evidence_file(tmp_path, "evidence/second.txt", "after\n")
    aggregate = check_incident(tmp_path, mode="enforce")
    assert aggregate["mode"] == "enforce" and aggregate["verdict"] == "FAIL"


def test_evidence_can_be_replaced_by_append_only_event(tmp_path):
    opened(tmp_path, mode="enforce")
    evidence = tmp_path / "evidence.log"
    evidence.write_text("one\n", encoding="utf-8")
    add_evidence(tmp_path, INCIDENT_ID, evidence_id="E1", path="evidence.log", evidence_type="log")
    evidence.write_text("two\n", encoding="utf-8")
    assert check_incident(tmp_path, INCIDENT_ID)["verdict"] == "FAIL"
    replaced = add_evidence(tmp_path, INCIDENT_ID, evidence_id="E1", path="evidence.log",
                            evidence_type="log", replace=True)
    assert replaced["verdict"] == "PASS"
    assert len(timeline(tmp_path)) == 3


def _append_outcome(append, index):
    try:
        return append(index)["verdict"], index
    except IncidentError:
        return "CONFLICT", index


def test_concurrent_appends_do_not_lose_events(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    opened(tmp_path, mode="enforce")
    def append(index):
        return add_hypothesis(tmp_path, INCIDENT_ID, hypothesis_id=f"H{index}", statement=f"hypothesis {index}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda index: _append_outcome(append, index), range(2)))
    assert sum(item[0] == "PASS" for item in outcomes) == 1
    for status, index in outcomes:
        if status != "PASS":
            assert add_hypothesis(tmp_path, INCIDENT_ID, hypothesis_id=f"H{index}", statement=f"hypothesis {index}")["verdict"] == "PASS"
    assert len(timeline(tmp_path)) == 3


def test_default_shadow_off_unverified_and_enforce_cause_exit_codes(tmp_path):
    opened(tmp_path)
    shadow = check_incident(tmp_path, INCIDENT_ID)
    assert shadow["mode"] == "shadow" and shadow["verdict"] == "PASS" and shadow["rc"] == 0
    evidence_file(tmp_path)
    data = case(tmp_path)
    data["status"] = "resolved"
    (incident_directory(tmp_path, INCIDENT_ID) / "incident.json").write_text(json.dumps(data), encoding="utf-8")
    shadow = check_incident(tmp_path, INCIDENT_ID)
    assert shadow["verdict"] == "FAIL" and shadow["rc"] == 0
    enforce = check_incident(tmp_path, INCIDENT_ID, mode="enforce")
    assert enforce["verdict"] == "FAIL" and enforce["rc"] == 1 and enforce["cause"] == "incident_not_resolved"
    off = check_incident(tmp_path, INCIDENT_ID, mode="off")
    assert off["verdict"] == "UNVERIFIED" and off["rc"] == 2 and off["cause"] is None
    assert validate(off, load_schema("governance-common")) == []


def test_projection_preserves_timeline_order_for_multiple_evidence_and_actions(tmp_path):
    opened(tmp_path, mode="enforce")
    evidence_file(tmp_path)
    add_evidence(tmp_path, INCIDENT_ID, evidence_id="E-z", path="evidence/before.txt",
                 evidence_type="metric", ts="2026-11-25T01:01:00Z")
    add_evidence(tmp_path, INCIDENT_ID, evidence_id="E-a", path="evidence/before.txt",
                 evidence_type="metric", ts="2026-11-25T01:02:00Z")
    add_action(tmp_path, INCIDENT_ID, action_id="A-z", owner="oncall", due="2999-01-01",
               ts="2026-11-25T01:03:00Z")
    add_action(tmp_path, INCIDENT_ID, action_id="A-a", owner="oncall", due="2999-01-01",
               ts="2026-11-25T01:04:00Z")
    data = case(tmp_path)
    assert [item["id"] for item in data["evidence"]] == ["E-z", "E-a"]
    assert [item["id"] for item in data["actions"]] == ["A-z", "A-a"]
    result = check_incident(tmp_path, INCIDENT_ID, mode="enforce")
    assert result["verdict"] == "PASS", result


def test_close_force_returns_enforce_failure_and_writes_nothing(tmp_path):
    opened(tmp_path, mode="enforce")
    add_base_evidence(tmp_path)
    contained(tmp_path)
    directory = incident_directory(tmp_path, INCIDENT_ID)
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    result = close_incident(tmp_path, INCIDENT_ID, summary="尝试强制关闭", force=True,
                            ts="2026-11-25T01:11:00Z")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert before == {path.name: path.read_bytes() for path in directory.iterdir()}


def test_directory_id_must_match_authority_and_duplicate_case_id_fails(tmp_path):
    opened(tmp_path)
    second_id = "INC-20261125-002"
    open_incident(tmp_path, title="第二例", environment="production", incident_id=second_id,
                  started_at="2026-11-25T01:12:00Z", detected_at="2026-11-25T01:12:00Z",
                  now="2026-11-25T01:12:00Z")
    data = event_data(timeline(tmp_path, second_id)[0])
    data["incident"]["id"] = INCIDENT_ID
    rewrite_event_data(tmp_path, 0, data, second_id)
    incident = case(tmp_path, second_id)
    incident["id"] = INCIDENT_ID
    (incident_directory(tmp_path, second_id) / "incident.json").write_text(json.dumps(incident), encoding="utf-8")
    regenerate_report(tmp_path, second_id)
    result = check_incident(tmp_path, second_id, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert any("目录 ID" in finding["message"] for finding in result["findings"])
    assert check_incident(tmp_path, mode="enforce")["verdict"] == "FAIL"


def test_scanning_all_incidents_does_not_skip_symlink_case(tmp_path):
    opened(tmp_path, mode="enforce")
    assert check_incident(tmp_path, mode="enforce")["verdict"] == "PASS"
    directory = incident_directory(tmp_path, INCIDENT_ID)
    moved = tmp_path / "moved-incident"
    directory.rename(moved)
    directory.symlink_to(moved, target_is_directory=True)
    result = check_incident(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert any("符号链接" in finding["message"] for finding in result["findings"])


def test_cli_full_lifecycle_uses_configured_assets_root(tmp_path, capsys):
    write(tmp_path, "atlas.config.yaml", "version: 1\nlayout:\n  assets_root: assets\n")
    write(tmp_path, "metrics.txt", "errors=10\n")
    write(tmp_path, ".atlas/tasks/TASK-77/task.json", '{"id":"TASK-77"}\n')
    prefix = ["--root", str(tmp_path), "--json", "--mode", "enforce"]

    def run(*args: str) -> dict:
        assert incident_main(prefix + list(args)) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["verdict"] == "PASS", result
        return result

    run("open", "--title", "API 故障", "--environment", "prod", "--id", INCIDENT_ID,
        "--started-at", "2026-11-25T00:55:00Z", "--detected-at", NOW, "--ts", NOW)
    run("event", INCIDENT_ID, "--kind", "evidence", "--evidence-id", "E-before",
        "--path", "metrics.txt", "--evidence-type", "metric", "--ts", "2026-11-25T01:01:00Z")
    run("event", INCIDENT_ID, "--kind", "hypothesis", "--hypothesis-id", "H-config",
        "--statement", "配置错误", "--evidence-ref", "E-before", "--ts", "2026-11-25T01:02:00Z")
    run("link", INCIDENT_ID, "--request", "REQ-1", "--task", "TASK-77", "--ts", "2026-11-25T01:03:00Z")
    run("event", INCIDENT_ID, "--kind", "action", "--action-id", "A-task", "--task-id", "TASK-77",
        "--ts", "2026-11-25T01:04:00Z")
    run("event", INCIDENT_ID, "--kind", "status", "--summary", "已遏制", "--ts", "2026-11-25T01:05:00Z")
    run("event", INCIDENT_ID, "--kind", "resolution", "--root-cause", "配置错误",
        "--root-cause-ref", "E-before", "--resolution", "恢复配置", "--verification", "E-before",
        "--verified-by", "owner", "--verified-at", "2026-11-25T01:06:00Z", "--before", "errors=10",
        "--after", "errors=0", "--ts", "2026-11-25T01:06:00Z")
    run("close", INCIDENT_ID, "--force", "--ts", "2026-11-25T01:07:00Z")
    run("check", INCIDENT_ID)
    directory = tmp_path / "assets" / "incidents" / INCIDENT_ID
    assert {path.name for path in directory.iterdir()} == {"incident.json", "timeline.jsonl", "report.md"}
    assert case(tmp_path)["status"] == "closed"
    assert not (tmp_path / "product" / "incidents").exists()


def test_cli_and_validator_entrypoints_return_json_and_expected_codes(tmp_path, capsys):
    assert incident_main(["--root", str(tmp_path), "--json", "--mode", "enforce", "open", "--title", "故障",
                          "--environment", "prod", "--owner", "oncall", "--id", INCIDENT_ID]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "PASS" and payload["mode"] == "enforce"
    assert incident_main(["--root", str(tmp_path), "--json", "open", "--title", "重复", "--environment", "prod",
                          "--id", INCIDENT_ID]) == 2
    assert json.loads(capsys.readouterr().out)["verdict"] == "UNVERIFIED"
    assert validator_main(["--root", str(tmp_path), "--json", "--mode", "enforce", INCIDENT_ID]) == 0
    checked = json.loads(capsys.readouterr().out)
    assert checked["module"] == "incident" and checked["verdict"] == "PASS"
