#!/usr/bin/env python3
"""Conservation between the frozen bug-record schema and runtime contract."""
from __future__ import annotations

import json
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
    assert tuple(props["backflow_status"]["enum"]) == records.BACKFLOW_STATUSES
    assert tuple(props["stage"]["enum"]) == records.STAGES
    assert tuple(props["impact"]["items"]["properties"]["kind"]["enum"]) == records.IMPACT_KINDS
    assert tuple(props["impact"]["items"]["properties"]["action"]["enum"]) == records.IMPACT_ACTIONS
    assert tuple(props["conflicts"]["items"]["properties"]["status"]["enum"]) == records.CONFLICT_STATUSES
    assert tuple(props["history"]["items"]["properties"]["event"]["enum"]) == records.HISTORY_EVENTS
    assert tuple(props["source"]["properties"]["mode"]["enum"]) == records.SOURCE_MODES
    assert tuple(props["source"]["properties"]["implementation_files"]["items"]["properties"]["obj_type"]["enum"]) == records.OBJECT_TYPES


def test_schema_ready_requires_implementation_and_resolved_state() -> None:
    ready = next(item for item in SCHEMA["allOf"]
                 if item.get("if", {}).get("properties", {}).get("backflow_status", {}).get("enum") == ["ready", "applied"])
    then = ready["then"]["properties"]
    assert then["source"]["properties"]["implementation_files"]["minItems"] == 1
    assert then["impact"]["minItems"] == 1
    assert then["documents"]["minItems"] == 1
    assert then["conflicts"]["items"]["properties"]["status"]["const"] == "resolved"
