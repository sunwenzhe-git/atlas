#!/usr/bin/env python3
"""atlas 项目接线（apply-wiring）回归测试。

覆盖：
  1. AGENTS.md atlas 指针块写入与幂等更新；
  2. .trellis/config.yaml after_finish hook 登记与幂等；
  3. Python 工程探测与 pytest 配置兜底（R6.2 对账定稿：pyproject.toml 优先承载、
     既有 ini 只补 marker、pythonpath 环境补丁随 F23 退役不再注入、非 Python 跳过）。
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


def test_wire_python_scaffold_created_ini_only_carries_markers() -> None:
    """R6.2：无任何 pytest 配置 ⇒ 新建 pytest.ini 只承载 marker 注册；
    `pythonpath = .` 环境补丁随 F23 退役（适配器已输出 python3 -m pytest）。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "requirements.txt").write_text("fastapi\npytest\n", encoding="utf-8")
        res = wiring.wire_python_scaffold(root)
        assert res["status"] == "applied"
        path, text = res["_write"]
        assert "markers" in text and "ac" in text
        assert "pythonpath" not in text, "pythonpath 补丁必须随 F23 退役"
        path.write_text(text, encoding="utf-8")

        # 再次运行：幂等跳过
        res2 = wiring.wire_python_scaffold(root)
        assert res2["status"] == "skipped"
        assert "已包含 marker 注册" in res2["detail"]


def test_wire_python_scaffold_pyproject_toml_takes_priority() -> None:
    """R6.2：pyproject.toml 已有 [tool.pytest...] 段 ⇒ skip，种种不另立/不复活 pytest.ini
    （防「接线复活被清掉的补丁」病理：legacy 清桩实测）。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\nmarkers = [\n    "ac: x",\n]\n', encoding="utf-8")
        res = wiring.wire_python_scaffold(root)
        assert res["status"] == "skipped" and "pyproject.toml" in res["detail"]


def test_wire_python_scaffold_existing_ini_gets_marker_only() -> None:
    """R6.2：既有 pytest.ini 只补缺失的 marker 注册；不注入 pythonpath、不动其他配置。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        (root / "pytest.ini").write_text("[pytest]\naddopts = -v\n", encoding="utf-8")
        res = wiring.wire_python_scaffold(root)
        assert res["status"] == "applied"
        path, text = res["_write"]
        assert "markers" in text and "ac" in text
        assert "pythonpath" not in text, "不得注入 pythonpath（F23 已修根因）"
        assert "addopts = -v" in text, "既有配置不得破坏"


def test_wire_python_scaffold_skips_non_python_projects() -> None:
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        res = wiring.wire_python_scaffold(root)
        assert res["status"] == "skipped"
        assert "非 Python 工程" in res["detail"]


def test_wire_config_upgrades_legacy_apply_hook_in_place() -> None:
    """C1（R7）：存量 `--apply` hook ⇒ 原位升级为 `--chain`；**不得**插入第二行
    （否则旧+新双 hook 常驻，每次 finish refresh 跑两遍——R6 现场教训变体）。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cfg = root / ".trellis" / "config.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(
            "hooks:\n"
            "  after_finish:\n"
            '    - "python3 .atlas/scripts/refresh_structure.py --root . --apply"\n',
            encoding="utf-8")
        res = wiring.wire_config(root)
        assert res["status"] == "applied" and "in-place" in res["detail"], res
        new_text = res["_write"][1]
        res["_write"][0].write_text(new_text, encoding="utf-8")  # 应用写盘，再验幂等
        assert new_text.count("refresh_structure.py") == 1, new_text
        assert "--chain" in new_text and "--apply" not in new_text

        # 幂等：已是 --chain ⇒ skipped
        res2 = wiring.wire_config(root)
        assert res2["status"] == "skipped", res2


def test_wire_config_preserves_custom_hook_without_second_line() -> None:
    """C1：前缀命令尾是自定义形态（非 --apply/--chain）⇒ 尊重自定 hook，不再插入。"""
    wiring = load_wiring()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cfg = root / ".trellis" / "config.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(
            "hooks:\n"
            "  after_finish:\n"
            '    - "python3 .atlas/scripts/refresh_structure.py --root . --custom-flag"\n',
            encoding="utf-8")
        res = wiring.wire_config(root)
        assert res["status"] == "skipped" and "自定义" in res["detail"], res
