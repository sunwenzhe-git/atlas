#!/usr/bin/env python3
"""测试 Atlas CLI 的 update 与 upgrade 命令。"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
ATLAS_BIN = PKG_ROOT / "bin" / "atlas.js"
PLATFORM_JS = PKG_ROOT / "bin" / "platform.js"
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


@pytest.mark.skipif(sys.platform == "win32",
                    reason="直接给 bash 传 Windows 临时路径（反斜杠/盘符）；CLI 轨已有路径归一化，Windows 用 CLI 用例覆盖")
def test_install_sh_update_fails_on_uninitialized_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        res = run_cmd(["bash", str(INSTALL_SH), "--update", "--target", tmpdir])
        assert res.returncode != 0
        assert "目标项目尚未装配 atlas" in res.stdout or "目标项目尚未装配 atlas" in res.stderr


@pytest.mark.skipif(sys.platform == "win32",
                    reason="直接给 bash 传 Windows 临时路径；Windows 用 CLI 用例覆盖")
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


# ---------------------------------------------------------------- 平台探测（bin/platform.js）
# Windows 现场（2026-11-03）：原生 PowerShell 没有 which ⇒ trellis 已装却被判「未检测到」；
# 随后 `bash` 落到 C:\Windows\System32\bash.exe（WSL 中继壳）⇒ execvpe(/bin/bash) 报错，
# install.sh 一步没跑；而 spawn 失败（status=null）还会被 `|| 0` 洗成成功。
# 下面四测钉住探测口径与路径归一化。

def node_json(expr: str):
    """在 node 里求值 platform.js 的表达式，返回 JSON 结果。"""
    script = f"const p = require({json.dumps(str(PLATFORM_JS))}); console.log(JSON.stringify({expr}));"
    res = run_cmd(["node", "-e", script])
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_trellis_probe_uses_where_on_windows():
    assert node_json("p.trellisProbe('win32')") == {"cmd": "where", "args": ["trellis"]}
    assert node_json("p.trellisProbe('darwin')") == {"cmd": "which", "args": ["trellis"]}


def test_bash_candidates_are_git_bash_only():
    probe = node_json(
        "(() => {"
        "  const c = p.bashCandidates('win32', {ProgramFiles: 'C:/Program Files'});"
        "  return {count: c.length,"
        "          allGit: c.every(x => x.includes('Git') && x.endsWith('bash.exe')),"
        "          hasWslRelay: c.some(x => /system32/i.test(x))};"
        "})()"
    )
    assert probe == {"count": 2, "allGit": True, "hasWslRelay": False}


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 宿主上可能真装了 Git Bash")
def test_resolve_bash_never_falls_back_to_system_bash():
    # 拿不到 Git Bash 时必须返回 null（调用侧 fail-closed），不能回落到系统 bash。
    assert node_json("p.resolveBash('win32')") is None


def test_python_candidates_are_platform_ordered():
    assert node_json("p.pythonCandidates('win32')") == [
        {"cmd": "py", "args": ["-3"]},
        {"cmd": "python", "args": []},
    ]
    assert node_json("p.pythonCandidates('darwin')") == [
        {"cmd": "python3", "args": []},
        {"cmd": "python", "args": []},
    ]


def test_python_version_parser_requires_310():
    assert node_json("p.parsePythonVersion('Python 3.12.3')") == {
        "major": 3,
        "minor": 12,
        "patch": 3,
    }
    assert node_json("p.parsePythonVersion('garbage')") is None
    assert node_json("p.versionSupported(p.parsePythonVersion('Python 3.9.18'))") is False
    assert node_json("p.versionSupported(p.parsePythonVersion('Python 3.10.0'))") is True
    assert node_json("p.versionSupported(p.parsePythonVersion('Python 2.7.18'))") is False


def test_resolve_python_finds_local_interpreter():
    py = node_json("p.resolvePython()")
    assert py is not None, "本机必须有 Python 3.10+ 才能跑 Atlas 测试"
    assert py["version"]["major"] == 3
    assert py["version"]["minor"] >= 10


def test_normalize_bash_args_rewrites_windows_paths_only():
    out = node_json(
        "p.normalizeBashArgs(['--target', 'C:\\\\Users\\\\demo\\\\proj', '--dry-run'], 'win32')"
    )
    assert out == ["--target", "C:/Users/demo/proj", "--dry-run"]
    assert node_json("p.normalizeBashArgs(['--target', '/tmp/proj'], 'darwin')") == [
        "--target",
        "/tmp/proj",
    ]
