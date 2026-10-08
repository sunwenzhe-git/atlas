#!/usr/bin/env python3
"""`validate_stack_profile.py` 的 `graph` 段契约判据（2026-10-05 图谱批 1）。

契约：`shared/stack-profile.md` §2 `graph` 段 —— **可选能力**：段缺失 = 不用图谱
（合法）；声明了就必须合法：键白名单 {backend, pinned}、backend 枚举 {cgc}、
pinned 语义版本形态。非法 = FAIL（响亮，不静默放行）。

词表守恒（同 origin 先例）：校验器 GRAPH_BACKENDS ⊆ 契约正文 ——
变异：给 GRAPH_BACKENDS 加第二个值而不写进契约 ⇒ 红。

变异（喂坏输入必红）：backend 换词表外值 ⇒ 红；白名单判据摘除（未知键放行）⇒ 红。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = PKG_ROOT / "validators" / "validate_stack_profile.py"
CONTRACT = PKG_ROOT / "shared" / "stack-profile.md"

_spec = importlib.util.spec_from_file_location("validate_stack_profile", VALIDATOR)
vsp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vsp)

PROFILE_HEAD = """product: 夹具
apps:
  - name: frontend
    path: frontend
    kind: frontend
    role: landing
    stack: 夹具
"""


def run_validator(root: Path) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(VALIDATOR), "--root", str(root), "--json"],
                       capture_output=True, text=True, timeout=60)
    return p.returncode, p.stdout


def mk(root: Path, graph_block: str) -> None:
    (root / "product").mkdir(parents=True, exist_ok=True)
    (root / "product" / "stack-profile.yaml").write_text(PROFILE_HEAD + graph_block,
                                                         encoding="utf-8")


def test_valid_graph_section_passes() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, 'graph:\n  backend: cgc   # 唯一合法后端\n  pinned: "0.6.13"\n')
        code, out = run_validator(root)
        assert code == 0, out
        checks = json.loads(out)["checks"]
        assert any(c["check"] == "graph.backend 枚举" and c["level"] == "PASS" for c in checks)
        assert any(c["check"] == "graph 段键白名单" and c["level"] == "PASS" for c in checks)


def test_absent_and_null_graph_is_legal() -> None:
    """可选能力：段缺失 / `graph: null` = 不用图谱（合法降级，不是缺憾）。"""
    for block in ("", "graph: null\n"):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mk(root, block)
            code, out = run_validator(root)
            assert code == 0, out
            assert any("graph 段" in c["check"] and c["level"] == "PASS"
                       for c in json.loads(out)["checks"])


def test_unknown_backend_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, "graph:\n  backend: gitnexus\n")
        code, out = run_validator(root)
        assert code == 1, out
        data = json.loads(out)
        assert data["status"] == "FAIL"
        row = next(c for c in data["checks"] if c["check"] == "graph.backend 枚举")
        assert row["level"] == "FAIL" and "cgc" in row["detail"]  # 点名允许值


def test_unknown_key_fails() -> None:
    """白名单：未知键 = FAIL（strict schema，同装配面纪律——未知形态不得静默放过）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, "graph:\n  backend: cgc\n  provider: someone\n")
        code, out = run_validator(root)
        assert code == 1, out
        row = next(c for c in json.loads(out)["checks"] if c["check"] == "graph 段键白名单")
        assert row["level"] == "FAIL" and "provider" in row["detail"]


def test_malformed_pinned_and_scalar_section_fail() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, "graph:\n  backend: cgc\n  pinned: latest\n")
        code, out = run_validator(root)
        assert code == 1, out
        row = next(c for c in json.loads(out)["checks"] if c["check"] == "graph.pinned 形态")
        assert row["level"] == "FAIL"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mk(root, "")  # 上一用例后新建；标量形态单独测
        (root / "product" / "stack-profile.yaml").write_text(
            PROFILE_HEAD + "graph: cgc\n", encoding="utf-8")
        code, out = run_validator(root)
        assert code == 1, out
        row = next(c for c in json.loads(out)["checks"] if c["check"] == "graph 段形态")
        assert row["level"] == "FAIL"


def test_graph_backend_vocabulary_in_sync() -> None:
    """词表守恒：校验器 GRAPH_BACKENDS / GRAPH_KEYS 必须出现在契约 §2 正文。"""
    contract = CONTRACT.read_text(encoding="utf-8")
    for v in vsp.GRAPH_BACKENDS:
        assert f"`{v}`" in contract, f"契约缺 graph.backend 取值：{v}"
    for k in vsp.GRAPH_KEYS:
        assert f"`{k}`" in contract, f"契约缺 graph 键：{k}"
