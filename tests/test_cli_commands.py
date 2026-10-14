#!/usr/bin/env python3
"""测试 Atlas CLI 的 update 与 upgrade 命令。"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
ATLAS_BIN = PKG_ROOT / "bin" / "atlas.js"
INSTALL_SH = PKG_ROOT / "install.sh"

pytestmark = pytest.mark.skipif(
    not ATLAS_BIN.is_file() or not INSTALL_SH.is_file(),
    reason="副本态（.atlas/）不包含 bin/ 与 install.sh，仅在源包测试",
)


def run_cmd(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd or PKG_ROOT,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def test_cli_help_includes_update_and_upgrade():
    res = run_cmd(["node", str(ATLAS_BIN), "--help"])
    assert res.returncode == 0
    assert "update" in res.stdout
    assert "upgrade" in res.stdout


def test_cli_update_help():
    res = run_cmd(["node", str(ATLAS_BIN), "update", "--help"])
    assert res.returncode == 0
    assert "Atlas update" in res.stdout
    assert "--dry-run" in res.stdout
    assert "--target" in res.stdout


def test_cli_upgrade_help():
    res = run_cmd(["node", str(ATLAS_BIN), "upgrade", "--help"])
    assert res.returncode == 0
    assert "Atlas upgrade" in res.stdout
    assert "--tag" in res.stdout
    assert "--dry-run" in res.stdout


def test_cli_upgrade_dry_run_default_latest():
    res = run_cmd(["node", str(ATLAS_BIN), "upgrade", "--dry-run"])
    assert res.returncode == 0
    assert "atlas-project-harness@latest" in res.stdout
    assert "[dry-run]" in res.stdout


def test_cli_upgrade_dry_run_with_custom_tag():
    res = run_cmd(["node", str(ATLAS_BIN), "upgrade", "--tag", "beta", "--dry-run"])
    assert res.returncode == 0
    assert "atlas-project-harness@beta" in res.stdout


def test_cli_update_fails_on_uninitialized_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        res = run_cmd(["node", str(ATLAS_BIN), "update", "--target", tmpdir])
        assert res.returncode != 0
        assert "目标项目尚未装配 Atlas" in res.stderr or "目标项目尚未装配 Atlas" in res.stdout


def test_install_sh_update_fails_on_uninitialized_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        res = run_cmd(["bash", str(INSTALL_SH), "--update", "--target", tmpdir])
        assert res.returncode != 0
        assert "目标项目尚未装配 atlas" in res.stdout or "目标项目尚未装配 atlas" in res.stderr


def test_install_sh_update_preserves_runs_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        (tmppath / ".atlas").mkdir()
        (tmppath / ".atlas" / "VERSION").write_text("dummy-digest\n", encoding="utf-8")
        (tmppath / ".trellis").mkdir()
        runs_file = tmppath / ".atlas" / "runs" / "backend-ac-alignment.json"
        runs_file.parent.mkdir(parents=True)
        runs_file.write_text('{"baseline": 1}\n', encoding="utf-8")

        res = run_cmd(["bash", str(INSTALL_SH), "--update", "--target", tmpdir, "--no-skill", "--no-patch", "--no-wiring"])
        assert res.returncode == 0
        assert runs_file.is_file()
        assert runs_file.read_text(encoding="utf-8") == '{"baseline": 1}\n'


def test_cli_update_dry_run_on_initialized_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        (tmppath / ".atlas").mkdir()
        (tmppath / ".atlas" / "VERSION").write_text("dummy-digest\n", encoding="utf-8")
        (tmppath / ".trellis").mkdir()

        res = run_cmd(["node", str(ATLAS_BIN), "update", "--target", tmpdir, "--dry-run"])
        assert res.returncode == 0
        assert "Atlas Update" in res.stdout
        assert "dummy-digest" in res.stdout


def test_cli_apply_prints_guidance_and_exits_2():
    res = run_cmd(["node", str(ATLAS_BIN), "apply"])
    assert res.returncode == 2
    assert "认知编排技能" in res.stderr
    assert "/atlas-apply" in res.stderr


def test_cli_unknown_command_exits_2():
    res = run_cmd(["node", str(ATLAS_BIN), "nonexistent-cmd"])
    assert res.returncode == 2
    assert "未知命令" in res.stderr
