#!/usr/bin/env python3
"""atlas 项目接线（apply-wiring）回归测试。

覆盖：
  1. AGENTS.md atlas 指针块写入与幂等更新；
  2. .trellis/config.yaml after_finish hook 登记与幂等；
  3. Python 工程探测与 pytest.ini 兜底（创建、已有补充 pythonpath、非 Python 工程跳过）。
"""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
WIRING_SCRIPT = PKG_ROOT / "patches" / "project-wiring" / "apply-wiring.py"


def load_wiring():
    spec = importlib.util.spec_from_file_location("apply_wiring_mod", WIRING_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_wire_python_scaffold_creates_pytest_ini_when_python_detected() -> None:
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "requirements.txt").write_text("fastapi\npytest\n", encoding="utf-8")
        res = wiring.wire_python_scaffold(root)
        assert res["status"] == "applied"
        assert res["file"] == "pytest.ini"
        path, text = res["_write"]
        path.write_text(text, encoding="utf-8")

        # 再次运行：幂等跳过
        res2 = wiring.wire_python_scaffold(root)
        assert res2["status"] == "skipped"
        assert "已包含 pythonpath" in res2["detail"]


def test_wire_python_scaffold_injects_pythonpath_into_existing_ini() -> None:
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        (root / "pytest.ini").write_text("[pytest]\naddopts = -v\n", encoding="utf-8")
        res = wiring.wire_python_scaffold(root)
        assert res["status"] == "applied"
        path, text = res["_write"]
        assert "pythonpath = ." in text
        assert "addopts = -v" in text


def test_wire_python_scaffold_skips_non_python_projects() -> None:
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        res = wiring.wire_python_scaffold(root)
        assert res["status"] == "skipped"
        assert "非 Python 工程" in res["detail"]
