"""`scripts/gen_fixture_schemas.py` 的形态断言（2026-11-15 诊断 S3）。

只验「推断结果是否收紧、可被 validate_e2e_mocks 接受」，不验业务字段对错。
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("gen_fx", ROOT / "scripts" / "gen_fixture_schemas.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load()


def test_infer_object_is_strict_and_merges_arrays() -> None:
    schema = gen.infer({
        "code": 0,
        "data": {"records": [{"a": 1, "b": "x"}, {"a": 2}], "total": 2},
        "msg": None,
    })
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    data = schema["properties"]["data"]
    assert data["additionalProperties"] is False
    # 数组元素取并集：a 必填（两个元素都有），b 可选（只有一个元素有）
    items = data["properties"]["records"]["items"]
    assert items["type"] == "object"
    assert items["additionalProperties"] is False
    assert items["required"] == ["a"]
    assert set(items["properties"]) == {"a", "b"}
    # null 不锁类型（避免把「后端可空」误锁成 any 之外的东西）
    assert schema["properties"]["msg"] == {}


def test_write_emits_companion_schema(tmp_path: Path) -> None:
    fx = tmp_path / "records.json"
    fx.write_text(json.dumps({"code": 0, "data": {"records": [], "total": 0}}), encoding="utf-8")
    out = gen.target_for(fx)
    out.write_text(json.dumps(gen.schema_for(fx), ensure_ascii=False), encoding="utf-8")
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert out.name == "records.schema.json"
    assert loaded["properties"]["data"]["properties"]["total"]["type"] == "integer"
