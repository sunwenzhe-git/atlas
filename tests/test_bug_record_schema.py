#!/usr/bin/env python3
"""Conservation between the frozen bug-record schema and runtime contract."""
from __future__ import annotations

import json
import re
from pathlib import Path

from _support import bug_record as records

PKG_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((PKG_ROOT / "templates/bug/record.schema.json").read_text(encoding="utf-8"))


def test_schema_and_runtime_key_sets_match() -> None:
    assert set(SCHEMA["required"]) == records.TOP_KEYS
    assert set(SCHEMA["properties"]) == records.TOP_KEYS
    mapping = {
        "report": "report", "impact": "impact", "conflicts": "conflicts",
        "documents": "documents", "decisions": "decisions", "history": "history",
        "source": "source", "links": "links",
    }
    for schema_key, runtime_key in mapping.items():
        schema_object = SCHEMA["properties"][schema_key]
        if schema_key in {"impact", "conflicts", "documents", "decisions", "history"}:
            schema_keys = set(schema_object["items"]["properties"])
        else:
            schema_keys = set(schema_object["properties"])
        assert schema_keys == records.NESTED_KEYS[runtime_key]
    assert set(SCHEMA["properties"]["documents"]["items"]["properties"]["version"]["properties"]) == records.NESTED_KEYS["version"]
    assert set(SCHEMA["properties"]["source"]["properties"]["implementation_files"]["items"]["properties"]) == records.NESTED_KEYS["implementation_files"]


def test_schema_and_runtime_enums_match() -> None:
    props = SCHEMA["properties"]
    assert set(props["report"]["properties"]["path"]["enum"]) == set(records.REPORT_PATHS.values())
    assert tuple(props["backflow_status"]["enum"]) == records.BACKFLOW_STATUSES
    assert tuple(props["stage"]["enum"]) == records.STAGES
    assert tuple(props["impact"]["items"]["properties"]["kind"]["enum"]) == records.IMPACT_KINDS
    assert tuple(props["impact"]["items"]["properties"]["action"]["enum"]) == records.IMPACT_ACTIONS
    assert tuple(props["conflicts"]["items"]["properties"]["status"]["enum"]) == records.CONFLICT_STATUSES
    assert tuple(props["history"]["items"]["properties"]["event"]["enum"]) == records.HISTORY_EVENTS
    assert tuple(props["source"]["properties"]["mode"]["enum"]) == records.SOURCE_MODES
    assert tuple(props["source"]["properties"]["implementation_files"]["items"]["properties"]["obj_type"]["enum"]) == records.OBJECT_TYPES


def test_schema_dedupe_key_shape_matches_runtime() -> None:
    pattern = re.compile(SCHEMA["properties"]["dedupe_key"]["pattern"])
    digest = "a" * 64
    assert pattern.fullmatch(f"需求变更:work/变更请求.md:base#R-01:{digest}")
    assert pattern.fullmatch(f"缺陷:work/缺陷报告.md:base#R-01:{digest}")
    assert pattern.fullmatch(f"base#R-01:{digest}")
    assert not pattern.fullmatch("x")


def test_schema_dedupe_prefix_is_bound_to_report_path() -> None:
    rules = [item for item in SCHEMA["allOf"]
             if item.get("if", {}).get("properties", {}).get("report")]
    change = next(item for item in rules
                  if item["if"]["properties"]["report"]["properties"]["path"]["const"]
                  == "work/变更请求.md")
    defect = next(item for item in rules
                  if item["if"]["properties"]["report"]["properties"]["path"]["const"]
                  == "work/缺陷报告.md")
    digest = "a" * 64
    assert re.fullmatch(change["then"]["properties"]["dedupe_key"]["pattern"],
                        f"需求变更:work/变更请求.md:base#R-01:{digest}")
    assert not re.fullmatch(change["then"]["properties"]["dedupe_key"]["pattern"],
                            f"base#R-01:{digest}")
    assert re.fullmatch(defect["then"]["properties"]["dedupe_key"]["pattern"],
                        f"base#R-01:{digest}")


def test_requirement_change_record_uses_typed_report_and_dedupe() -> None:
    digest = "a" * 64
    record = records.new_record("change-1", "base#R-01", "prod", digest,
                                report_path="work/变更请求.md")
    assert record["report"] == {"path": "work/变更请求.md", "sha256": digest}
    assert record["dedupe_key"] == f"需求变更:work/变更请求.md:base#R-01:{digest}"
    assert records.validate_record(record) == []


def test_schema_ready_requires_implementation_and_resolved_state() -> None:
    ready = next(item for item in SCHEMA["allOf"]
                 if item.get("if", {}).get("properties", {}).get("backflow_status", {}).get("enum") == ["ready", "applied"])
    then = ready["then"]["properties"]
    assert then["source"]["properties"]["implementation_files"]["minItems"] == 1
    assert then["impact"]["minItems"] == 1
    assert then["documents"]["minItems"] == 1
    assert then["conflicts"]["items"]["properties"]["status"]["const"] == "resolved"
