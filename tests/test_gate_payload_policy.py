"""RFC-20261119-03 Phase 2：门禁载荷防自动改写。

判据本体在 `scripts/atlas_check.py` 的 `payload_violations()` / `command_is_readonly()`；
本文件钉四件事：
  1. 干净载荷必须零违规；
  2. `fix` / `autofix` 键、`detail` / `output` / hint 中的 `--write` / `--record` /
     `--apply` / `release --file` / `git apply` / `rm -rf` 必须判红；
  3. `command` 只允许只读命令头，不再整类豁免；
  4. 源码级扫描：`rows.add(...)` 的字符串与 `self.failures.append({...})` 的键集合
     不得回潮（挡住未来新增门又塞 `fix`）。
"""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
CK = PKG_ROOT / "scripts" / "atlas_check.py"


def _load_check_module():
    spec = importlib.util.spec_from_file_location("atlas_check_policy", CK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_clean_payload_has_no_violations() -> None:
    ac = _load_check_module()
    payload = {
        "schema_version": 1,
        "rows": [{"name": "装配版本", "status": "ok", "detail": "一致"}],
        "failures": [],
    }
    assert ac.payload_violations(payload) == []


def test_forbidden_key_and_text_are_caught() -> None:
    ac = _load_check_module()
    payload = {
        "rows": [
            {"name": "x", "status": "FAIL", "detail": "请执行 gen.py --write"},
            {"name": "y", "status": "WARN", "detail": "ok"},
        ],
        "failures": [{
            "name": "z",
            "detail": "ok",
            "output": "run --record to fix",
            "command": "python3 ok.py",
            "fix": "rm -rf /",
            "remediation_hint": {"text": "git apply patch.diff"},
        }],
    }
    got = ac.payload_violations(payload)
    codes = {v["code"] for v in got}
    assert "forbidden_key" in codes, got
    assert "forbidden_text" in codes, got
    paths = {v["path"] for v in got}
    assert "$.rows[0].detail" in paths, paths
    assert "$.failures[0].output" in paths, paths
    assert any("remediation_hint" in p for p in paths), paths


def test_command_allowlist() -> None:
    ac = _load_check_module()
    assert ac.command_is_readonly("")
    assert ac.command_is_readonly("python3 -m pytest .atlas/tests -q")
    assert ac.command_is_readonly("/opt/homebrew/bin/python3.12 validate_prd.py --root .")
    assert ac.command_is_readonly("npx playwright test")
    assert not ac.command_is_readonly("git apply x.diff")
    assert not ac.command_is_readonly("python3 gen.py --apply")
    assert not ac.command_is_readonly("bash -c 'rm -rf /tmp/x'")
    assert not ac.command_is_readonly("unknown-bin --force")


def test_row_add_puts_hint_on_failure_and_row() -> None:
    ac = _load_check_module()
    rows = ac.Row()
    rows.add("对齐测试(.atlas/tests)", "FAIL", "1 failed", command="python3 -m pytest",
             code=1, full_output="boom")
    row = rows.rows[0]
    fail = rows.failures[0]
    assert row["remediation_hint"]["category"] == "regression", row
    assert fail["remediation_hint"] == row["remediation_hint"], fail
    assert ac.payload_violations({"rows": rows.rows, "failures": rows.failures}) == []


def test_atlas_check_json_payload_is_clean() -> None:
    ac = _load_check_module()
    with tempfile.TemporaryDirectory() as td:
        p = subprocess.run([sys.executable, str(CK), "--root", ".", "--fast", "--json"],
                           cwd=td, capture_output=True, text=True, timeout=600)
        payload = json.loads(p.stdout)
        assert payload["schema_version"] == 1, payload
        violations = ac.payload_violations(payload)
        assert violations == [], violations
        for fail in payload["failures"]:
            assert fail.get("remediation_hint"), fail


def test_source_gate_messages_are_clean() -> None:
    """源码级：`rows.add(...)` 的字符串不得含改写旗标（注释不在 AST 内）。"""
    ac = _load_check_module()
    tree = ast.parse(CK.read_text(encoding="utf-8"))
    bad: list[str] = []

    def scan_constants(node: ast.AST, where: str) -> None:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                for pat in ac.FORBIDDEN_PAYLOAD_PATTERNS:
                    if pat.search(sub.value):
                        bad.append(f"{where}:{getattr(sub, 'lineno', '?')} {sub.value!r}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "add" and isinstance(node.func.value, ast.Name) \
                and node.func.value.id in {"rows", "row"}:
            scan_constants(node, "rows.add")
    assert not bad, bad


def test_failure_dict_keys_are_closed_set() -> None:
    """源码级：`self.failures.append({...})` 的键集合不得新增 `fix` 一类字段。"""
    ac = _load_check_module()
    allowed = {"name", "detail", "command", "code", "output", "remediation_hint"}
    tree = ast.parse(CK.read_text(encoding="utf-8"))
    seen: list[set[str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = {k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            # failure 载荷的固定键集合；命中即视为「失败载荷字典」。
            if {"name", "detail", "command", "code", "output"} <= keys:
                seen.append(keys)
    assert seen, "未找到失败载荷字典"
    for keys in seen:
        assert keys <= allowed, keys - allowed
        assert not (keys & ac.FORBIDDEN_PAYLOAD_KEYS), keys
