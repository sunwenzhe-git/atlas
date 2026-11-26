"""RFC-20261125-01 frozen JSON Schema subset and canonical digest."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "shared" / "schemas"
_ALLOWED = {
    "$schema", "$id", "title", "type", "const", "enum", "required", "properties",
    "additionalProperties", "items", "minItems", "uniqueItems", "pattern", "minimum",
    "oneOf", "allOf", "if", "then", "else", "$ref", "$defs", "format", "propertyNames", "minLength", "minProperties", "maxItems",
}


def canonical_bytes(value) -> bytes:
    def normalized(item):
        if isinstance(item, dict):
            if not all(isinstance(k, str) for k in item):
                raise TypeError("canonical JSON 对象键必须为字符串")
            return {k: normalized(v) for k, v in item.items()}
        if isinstance(item, list):
            return sorted((normalized(v) for v in item), key=lambda v: json.dumps(
                v, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return item
    return json.dumps(normalized(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def canonical_digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 重复键：{key}")
        result[key] = value
    return result


def load_schema(name: str) -> dict:
    path = SCHEMA_DIR / f"{name}.json"
    schema = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    unknown = _unknown_keywords(schema)
    if unknown:
        raise ValueError(f"{path.name} 含未支持关键字：{sorted(unknown)}")
    return schema


def _unknown_keywords(schema, found=None):
    found = set() if found is None else found
    if not isinstance(schema, dict):
        return found
    for key, value in schema.items():
        if key not in _ALLOWED:
            found.add(key)
        elif key in ("properties", "$defs"):
            for child in value.values():
                _unknown_keywords(child, found)
        elif key in ("items", "additionalProperties", "propertyNames", "if", "then", "else"):
            _unknown_keywords(value, found)
        elif key in ("oneOf", "allOf"):
            for child in value:
                _unknown_keywords(child, found)
    return found


def _matches_type(value, expected: str) -> bool:
    return {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": lambda: isinstance(value, bool),
        "null": lambda: value is None,
    }[expected]()


def _resolve(schema: dict, root: dict) -> dict:
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not ref.startswith("#/"):
        raise ValueError(f"不支持外部 schema 引用：{ref}")
    target = root
    for part in ref[2:].split("/"):
        target = target[part.replace("~1", "/").replace("~0", "~")]
    return target


def validate(value, schema: dict, root: dict | None = None, path: str = "$") -> list[str]:
    root = schema if root is None else root
    errors: list[str] = []
    if "$ref" in schema:
        return validate(value, _resolve(schema, root), root, path)
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(value, item) for item in types):
            return [f"{path}: 类型应为 {types}，实际 {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: 必须等于 {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: 不在枚举 {schema['enum']!r}")
    if isinstance(value, dict):
        if len(value) < schema.get("minProperties", 0):
            errors.append(f"{path}: 属性数小于 {schema['minProperties']}")
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: 缺必填字段 {key}")
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                errors.extend(validate(item, props[key], root, f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: 未知字段 {key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(validate(item, schema["additionalProperties"], root, f"{path}.{key}"))
            if "propertyNames" in schema:
                errors.extend(validate(key, schema["propertyNames"], root, f"{path}.<key>"))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: 至少需要 {schema['minItems']} 项")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: 最多允许 {schema['maxItems']} 项")
        if schema.get("uniqueItems"):
            encoded = [canonical_bytes(item) for item in value]
            if len(set(encoded)) != len(encoded):
                errors.append(f"{path}: 存在重复项")
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(validate(item, schema["items"], root, f"{path}[{index}]"))
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: 长度小于 {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: 不匹配模式 {schema['pattern']}")
        if schema.get("format") == "date-time":
            try:
                if "T" not in value and "t" not in value:
                    raise ValueError("missing time")
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{path}: 非法 date-time")
        elif schema.get("format") == "date":
            try:
                date.fromisoformat(value)
            except ValueError:
                errors.append(f"{path}: 非法 date")
    if isinstance(value, (int, float)) and not isinstance(value, bool) \
            and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: 小于 {schema['minimum']}")
    if "oneOf" in schema:
        matches = sum(not validate(value, option, root, path) for option in schema["oneOf"])
        if matches != 1:
            errors.append(f"{path}: oneOf 命中 {matches} 个分支")
    for option in schema.get("allOf", []):
        errors.extend(validate(value, option, root, path))
    if "if" in schema:
        branch = "then" if not validate(value, schema["if"], root, path) else "else"
        if branch in schema:
            errors.extend(validate(value, schema[branch], root, path))
    return errors


def validate_receipt(value: dict) -> list[str]:
    errors = validate(value, load_schema("workflow-receipt"))
    if errors:
        return errors
    scope = set(value["in_scope_modules"])
    modes = set(value["module_modes"])
    checked = {item["module"] for item in value["validators"]}
    if scope != modes or scope != checked or len(checked) != len(value["validators"]):
        errors.append("$.validators: in_scope_modules / module_modes / validators 模块集合必须一一对应")
    required = set()
    if value["clause_ids"]:
        required.add("semantic")
    if value["doc_ids"]:
        required.add("docs")
    if value["resolves_incidents"]:
        required.add("incident")
    if value["topology_required"] or value["topology_refs"]:
        required.add("topology")
    if value["migration_required"]:
        required.add("migration")
    if value["classification_required"]:
        required.add("classification")
    if not required <= scope:
        errors.append(f"$.in_scope_modules: 任务引用要求模块 {sorted(required - scope)} 进入 scope")
    for item in value["validators"]:
        if item["verdict"] not in ("PASS", "WARN", "N/A"):
            errors.append(f"$.validators[{item['module']}]: 完成态 in-scope 结果必须为 PASS/WARN/N/A，实际 {item['verdict']}")
        if item["verdict"] == "N/A" and not all(item.get(key) for key in ("reason", "owner", "due")):
            errors.append(f"$.validators[{item['module']}]: N/A 必须带 reason/owner/due")
    return errors


def validate_topology(value: dict) -> list[str]:
    errors = validate(value, load_schema("runtime-topology"))
    if errors:
        return errors
    inputs = value["inputs"]
    ids = set()
    nodes = set()
    for item in value["items"]:
        if item.get("node") is True:
            namespace = "none" if item["namespace"] is None else item["namespace"]
            expected = ":".join((inputs["project"], inputs["environment"], inputs["cluster"],
                                 inputs["release"], namespace, item["name"]))
            if item["id"] != expected:
                errors.append(f"$.items: node id 必须由六字段重算为 {expected}")
            if item["id"] in ids:
                errors.append(f"$.items: 重复 id {item['id']}")
            ids.add(item["id"])
            nodes.add(item["id"])
    for item in value["items"]:
        if item.get("edge") is True:
            if item["id"] in ids:
                errors.append(f"$.items: 重复 id {item['id']}")
            ids.add(item["id"])
            if item["from"] not in nodes or item["to"] not in nodes:
                errors.append(f"$.items: 悬空边 {item['id']}")
    return errors
