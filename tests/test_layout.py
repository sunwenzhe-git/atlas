#!/usr/bin/env python3
"""`_support/layout.py` 回归测试（RFC-20261026-01）。

覆盖：默认布局 / assets_root 与 adr 覆盖 / 严格键空间 / 路径逃逸 / symlink /
双根与 profile 漂移 WARN / CLI --print / --validate / --validate-value。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
LAYOUT_PY = PKG_ROOT / "_support" / "layout.py"
_spec = importlib.util.spec_from_file_location("layout_under_test", LAYOUT_PY)
layout_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = layout_mod
_spec.loader.exec_module(layout_mod)

LayoutError = layout_mod.LayoutError
load_layout = layout_mod.load_layout
validate_value = layout_mod.validate_value


def write_config(root: Path, text: str) -> None:
    (root / "atlas.config.yaml").write_text(text, encoding="utf-8")


def make_config(assets_root: str = "product", adr: str | None = None) -> str:
    lines = ["version: 1", "layout:", f"  assets_root: {assets_root}"]
    if adr is not None:
        lines.append(f"  adr: {adr}")
    return "\n".join(lines) + "\n"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LAYOUT_PY), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_default_when_config_missing(tmp_path: Path) -> None:
    lay = load_layout(tmp_path)
    root = tmp_path.resolve()
    assert lay.assets_root == root / "product"
    assert lay.adr_dir == root / "product" / "adr"
    assert lay.stack_profile == root / "product" / "stack-profile.yaml"
    assert lay.prd_dir == root / "product" / "prd"
    assert lay.e2e_scripts_dir == root / "product" / "e2e" / "scripts"
    assert lay.print_value("adr") == "product/adr"


def test_assets_root_docs(tmp_path: Path) -> None:
    write_config(tmp_path, make_config("docs"))
    lay = load_layout(tmp_path)
    root = tmp_path.resolve()
    assert lay.assets_root == root / "docs"
    assert lay.adr_dir == root / "docs" / "adr"
    assert lay.stack_profile == root / "docs" / "stack-profile.yaml"
    assert lay.prd_dir == root / "docs" / "prd"
    assert lay.print_value("stack_profile") == "docs/stack-profile.yaml"


def test_adr_override_outside_assets_root(tmp_path: Path) -> None:
    write_config(tmp_path, make_config("product", "docs/adr"))
    lay = load_layout(tmp_path)
    root = tmp_path.resolve()
    assert lay.adr_dir == root / "docs" / "adr"
    assert lay.assets_root == root / "product"
    assert lay.print_value("adr") == "docs/adr"


def test_comments_and_quotes(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        "\n".join([
            "# 项目布局",
            "version: 1  # schema",
            "layout:",
            "  assets_root: 'docs'  # 资产根",
            '  adr: "decisions/adr"',
        ]) + "\n",
    )
    lay = load_layout(tmp_path)
    assert lay.print_value("assets_root") == "docs"
    assert lay.print_value("adr") == "decisions/adr"


@pytest.mark.parametrize(
    "text, match",
    [
        ("version: 2\nlayout:\n  assets_root: product\n", "version 只支持 1"),
        ("layout:\n  assets_root: product\n", "缺少 version"),
        ("version: 1\nfoo: bar\nlayout:\n  assets_root: product\n", "未知顶层键"),
        ("version: 1\nversion: 1\nlayout:\n  assets_root: product\n", "重复顶层键"),
        ("version: 1\nlayout:\n  assets_root: product\n  assets_root: docs\n", "重复 layout 键"),
        ("version: 1\nlayout:\n  assets_root: product\n  foo: bar\n", "未知 layout 键"),
        ("version: 1\nlayout:\n  adr: docs/adr\n", "缺少 layout.assets_root"),
        ("version: 1\nlayout: {}\n", "layout 必须是块"),
        ("version: 1\nlayout:\n  assets_root:\n", "必须是非空字符串"),
        ("version: 1\nlayout:\n  assets_root: product\n  adr: null\n", "必须是非空字符串"),
        ("version: 1\nlayout:\n  assets_root: /docs\n", "不能是绝对路径"),
        ("version: 1\nlayout:\n  assets_root: C:/docs\n", "不能是绝对路径"),
        ("version: 1\nlayout:\n  assets_root: ../docs\n", "不得包含空段"),
        ("version: 1\nlayout:\n  assets_root: docs/./adr\n", "不得包含空段"),
        ("version: 1\nlayout:\n  assets_root: .atlas\n", "不得落在 .atlas"),
        ("version: 1\nlayout:\n  assets_root: .trellis/adr\n", "不得落在 .trellis"),
        ("version: 1\nlayout:\n  assets_root: docs\\adr\n", "POSIX"),
    ],
)
def test_invalid_configs(tmp_path: Path, text: str, match: str) -> None:
    write_config(tmp_path, text)
    with pytest.raises(LayoutError, match=match):
        load_layout(tmp_path)


def test_assets_root_is_file(tmp_path: Path) -> None:
    (tmp_path / "docs").write_text("not a dir", encoding="utf-8")
    write_config(tmp_path, make_config("docs"))
    with pytest.raises(LayoutError, match="不是目录"):
        load_layout(tmp_path)


def test_adr_is_file(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "adr").write_text("not a dir", encoding="utf-8")
    write_config(tmp_path, make_config("docs"))
    with pytest.raises(LayoutError, match="不是目录"):
        load_layout(tmp_path)


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    os.symlink(outside, tmp_path / "link")
    write_config(tmp_path, make_config("link/assets"))
    with pytest.raises(LayoutError, match="逃出项目根"):
        load_layout(tmp_path)


def test_validate_value(tmp_path: Path) -> None:
    assert validate_value(tmp_path, "assets_root", "docs") == tmp_path.resolve() / "docs"
    assert validate_value(tmp_path, "adr", "docs/adr") == tmp_path.resolve() / "docs" / "adr"
    with pytest.raises(LayoutError, match="未知 layout 键"):
        validate_value(tmp_path, "prd", "docs/prd")
    with pytest.raises(LayoutError, match="不得包含空段"):
        validate_value(tmp_path, "assets_root", "../docs")


def test_cli_print_and_validate(tmp_path: Path) -> None:
    write_config(tmp_path, make_config("docs", "decisions/adr"))
    out = run_cli("--root", str(tmp_path), "--print", "adr")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "decisions/adr"

    out = run_cli("--root", str(tmp_path), "--print-abs", "stack_profile")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == str(tmp_path.resolve() / "docs" / "stack-profile.yaml")

    out = run_cli("--root", str(tmp_path), "--validate")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"

    out = run_cli("--root", str(tmp_path), "--validate-value", "assets_root", "docs")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"

    out = run_cli("--root", str(tmp_path), "--validate-value", "assets_root", "../x")
    assert out.returncode == 2
    assert "ERROR:" in out.stderr

    out = run_cli("--root", str(tmp_path), "--print", "unknown")
    assert out.returncode == 2
    assert "未知输出键" in out.stderr


def test_cli_invalid_config(tmp_path: Path) -> None:
    write_config(tmp_path, "version: 1\nlayout:\n  assets_root: ../x\n")
    out = run_cli("--root", str(tmp_path), "--validate")
    assert out.returncode == 2
    assert "ERROR:" in out.stderr


def test_warning_double_root(tmp_path: Path) -> None:
    (tmp_path / "product").mkdir()
    (tmp_path / "product" / "stack-profile.yaml").write_text("product: 夹具\n", encoding="utf-8")
    write_config(tmp_path, make_config("docs"))
    codes = {w["code"] for w in load_layout(tmp_path).warnings()}
    assert "double_root" in codes


def test_warning_adr_double_root(tmp_path: Path) -> None:
    (tmp_path / "product" / "adr").mkdir(parents=True)
    write_config(tmp_path, make_config("product", "docs/adr"))
    codes = {w["code"] for w in load_layout(tmp_path).warnings()}
    assert "adr_double_root" in codes


def test_warning_configured_root_missing(tmp_path: Path) -> None:
    (tmp_path / "product" / "prd").mkdir(parents=True)
    write_config(tmp_path, make_config("docs"))
    codes = {w["code"] for w in load_layout(tmp_path).warnings()}
    assert "configured_root_missing" in codes


def test_warning_profile_path_drift(tmp_path: Path) -> None:
    (tmp_path / "docs" / "e2e").mkdir(parents=True)
    (tmp_path / "docs" / "stack-profile.yaml").write_text(
        "product: 夹具\n"
        "e2e:\n"
        "  cases_dir: product/e2e/cases\n"
        "  index: product/e2e/e2e-index.md\n"
        "  scripts_dir: product/e2e/scripts\n",
        encoding="utf-8",
    )
    write_config(tmp_path, make_config("docs"))
    codes = {w["code"] for w in load_layout(tmp_path).warnings()}
    assert "profile_path_drift" in codes


def test_write_config_and_refuse_overwrite(tmp_path: Path) -> None:
    cfg = layout_mod.write_config(tmp_path, "docs", "decisions/adr")
    assert cfg == tmp_path.absolute() / "atlas.config.yaml"
    lay = load_layout(tmp_path)
    assert lay.print_value("assets_root") == "docs"
    assert lay.print_value("adr") == "decisions/adr"
    with pytest.raises(LayoutError, match="拒绝覆盖"):
        layout_mod.write_config(tmp_path, "product")

    with pytest.raises(LayoutError, match="不得包含"):
        layout_mod.write_config(tmp_path.parent / "new-root", "docs/#x")


def test_cli_write_and_print(tmp_path: Path) -> None:
    out = run_cli("--root", str(tmp_path), "--write", "--assets-root", "docs")
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "atlas.config.yaml").is_file()

    out = run_cli("--root", str(tmp_path), "--print", "assets_root")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "docs"

    out = run_cli("--root", str(tmp_path), "--write", "--assets-root", "product")
    assert out.returncode == 2
    assert "拒绝覆盖" in out.stderr
