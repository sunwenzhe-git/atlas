#!/usr/bin/env python3
"""fixture 伴生 schema 生成器（契约 `rings/e2e/reference.md` §5.8，2026-11-15 诊断 S3）。

`e2e.mock.mode: on` 的项目要求每个被引用的 fixture 有同名 `<fixture>.schema.json`
（`validators/validate_e2e_mocks.py` 的「fixture schema 强制」门）。本脚本从 JSON 推断
**收紧** schema（对象层 `additionalProperties: false`、required = 该样本出现的全部键），
用于把既有桩形状锁定下来，防止后端改字段 / 改类型后桩静默假绿。

注意：**形状锁定是下限**。真实响应契约（字段名 / 类型是否与后端一致）需要从真实响应抓取
快照后人工核对；本脚本不会替你判断「fixture 是否写对了」。

用法：
    python3 scripts/gen_fixture_schemas.py <fixture.json> [...]            # 干跑，打印计划
    python3 scripts/gen_fixture_schemas.py <fixture.json> [...] --write    # 写入 .schema.json
    python3 scripts/gen_fixture_schemas.py <dir> --write                   # 递归处理目录下所有 .json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SKIP_SUFFIX = ".schema.json"


def infer(value) -> dict:
    """从单个值推断 JSON Schema 片段（无 enum / 无 format，避免把样本值写死成规则）。"""
    if value is None:
        return {}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        items = merge_all([infer(v) for v in value]) if value else {}
        return {"type": "array", "items": items} if items else {"type": "array"}
    if isinstance(value, dict):
        props = {k: infer(v) for k, v in value.items()}
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": props,
            "required": list(props),
        }
    return {}


def merge_all(schemas: list[dict]) -> dict:
    """合并同一数组内多个元素的 schema：对象取并集（required 取交集），类型冲突则放宽为 any。"""
    if not schemas:
        return {}
    out = schemas[0]
    for nxt in schemas[1:]:
        out = merge(out, nxt)
    return out


def merge(a: dict, b: dict) -> dict:
    if not a or not b:
        return {}
    if a.get("type") != b.get("type"):
        return {}
    t = a["type"]
    if t == "object":
        pa, pb = a.get("properties") or {}, b.get("properties") or {}
        props = dict(pa)
        for k, v in pb.items():
            props[k] = merge(props[k], v) if k in props else v
        req = [k for k in (a.get("required") or []) if k in (b.get("required") or [])]
        return {"type": "object", "additionalProperties": False,
                "properties": props, "required": req}
    if t == "array":
        return {"type": "array", "items": merge_all([a.get("items") or {}, b.get("items") or {}])}
    return a


def schema_for(path: Path) -> dict:
    return infer(json.loads(path.read_text(encoding="utf-8")))


def target_for(path: Path) -> Path:
    return path.with_name(path.name[: -len(".json")] + ".schema.json")


def iter_fixtures(arg: str) -> list[Path]:
    p = Path(arg)
    if p.is_dir():
        return sorted(q for q in p.rglob("*.json") if not q.name.endswith(SKIP_SUFFIX))
    return [p]


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 fixture 伴生 schema（收紧形态）")
    ap.add_argument("paths", nargs="+", help="fixture JSON 文件或目录")
    ap.add_argument("--write", action="store_true", help="写入 <fixture>.schema.json（缺省干跑）")
    args = ap.parse_args()

    for raw in args.paths:
        for fixture in iter_fixtures(raw):
            if not fixture.is_file():
                print(f"[SKIP] 不存在：{fixture}")
                continue
            schema = schema_for(fixture)
            out = target_for(fixture)
            if args.write:
                out.write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
                print(f"[WRITE] {out}")
            else:
                print(f"[DRY] {fixture} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
