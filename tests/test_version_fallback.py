#!/usr/bin/env python3
"""RFC §5.2.1 / V-05：`reader_version` 三级回落（工具自身版本，不读被检查仓）。

顺序固定：`<root>/.atlas/VERSION` → `<root>/.atlas/package.json` → 工具包根
`package.json`。中间级不可解析 ⇒ 记 `downgrades[]` 并继续回落。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = PKG_ROOT / "_support" / "solution.py"
    spec = importlib.util.spec_from_file_location("_atlas_solution_version_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = _load()


def stub_tool(monkeypatch, tmp_path: Path, version: str | None) -> Path:
    """把工具包根指到仓外目录；`version=None` 表示该级不存在。"""
    toolroot = tmp_path / "toolroot"
    toolroot.mkdir(exist_ok=True)
    if version is not None:
        (toolroot / "package.json").write_text(
            json.dumps({"version": version}), encoding="utf-8")
    monkeypatch.setattr(core, "_TOOL_PACKAGE_ROOT", toolroot)
    return toolroot


def test_version_from_atlas_version_file(tmp_path: Path, monkeypatch) -> None:
    stub_tool(monkeypatch, tmp_path, "0.2.0-beta.33")
    (tmp_path / ".atlas").mkdir()
    (tmp_path / ".atlas" / "VERSION").write_text("0.4.1\n", encoding="utf-8")
    assert core.reader_version(tmp_path) == "0.4.1"
    assert core.resolve_reader_version(tmp_path)[1] == []


def test_unparsable_version_falls_back_with_downgrade(
        tmp_path: Path, monkeypatch) -> None:
    """装配摘要形态不是 semver ⇒ 记一条降级，回落到 `.atlas/package.json`。"""
    stub_tool(monkeypatch, tmp_path, "0.2.0")
    (tmp_path / ".atlas").mkdir()
    (tmp_path / ".atlas" / "VERSION").write_text("sha256:deadbeef\n", encoding="utf-8")
    (tmp_path / ".atlas" / "package.json").write_text(
        json.dumps({"version": "0.3.5"}), encoding="utf-8")
    version, downgrades = core.resolve_reader_version(tmp_path)
    assert version == "0.3.5"
    assert [d["code"] for d in downgrades] == ["reader_version"]
    assert downgrades[0]["scope"] == "reader_version"


def test_falls_back_to_atlas_package_json(tmp_path: Path, monkeypatch) -> None:
    stub_tool(monkeypatch, tmp_path, "0.2.0")
    (tmp_path / ".atlas").mkdir()
    (tmp_path / ".atlas" / "package.json").write_text(
        json.dumps({"version": "0.4.0"}), encoding="utf-8")
    assert core.reader_version(tmp_path) == "0.4.0"


def test_falls_back_to_tool_package_json(tmp_path: Path, monkeypatch) -> None:
    stub_tool(monkeypatch, tmp_path, "0.2.0-beta.33")
    assert core.reader_version(tmp_path) == "0.2.0-beta.33"


def test_never_reads_repo_root_package_json(tmp_path: Path, monkeypatch) -> None:
    """被检查仓 `<root>/package.json` 不是版本来源（v11/重要 3）。"""
    stub_tool(monkeypatch, tmp_path, "0.3.0")
    (tmp_path / "package.json").write_text(
        json.dumps({"version": "9.9.9"}), encoding="utf-8")
    assert core.reader_version(tmp_path) == "0.3.0"


def test_all_missing_is_unknown_with_three_candidate_hint(
        tmp_path: Path, monkeypatch) -> None:
    stub_tool(monkeypatch, tmp_path, None)
    version, downgrades = core.resolve_reader_version(tmp_path)
    assert version == "" and downgrades == []
    hint = core.reader_version_unknown_hint(tmp_path)
    assert ".atlas/VERSION" in hint and ".atlas/package.json" in hint
    assert "package.json" in hint
