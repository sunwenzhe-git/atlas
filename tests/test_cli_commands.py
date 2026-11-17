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
    assert "solution" in res.stdout


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


def _make_fake_install(tmp_path: Path) -> tuple[Path, Path]:
    """在 `<tmp>/n/lib/node_modules/` 造一份"正在运行"的安装（posix 全局布局）。"""
    prefix = tmp_path / "n"
    root = prefix / "lib" / "node_modules" / "atlas-project-harness"
    (root / "bin").mkdir(parents=True)
    shutil.copy(ATLAS_BIN, root / "bin" / "atlas.js")
    shutil.copy(PLATFORM_JS, root / "bin" / "platform.js")
    (root / "package.json").write_text(
        (PKG_ROOT / "package.json").read_text(encoding="utf-8"), encoding="utf-8")
    return root, prefix


def _fake_npm(tmp_path: Path, configured_prefix: str, log: Path) -> Path:
    """假 npm：记录调用参数；`config get prefix` 返回指定值；不联网。"""
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    npm = bindir / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'if [ "$1" = "config" ] && [ "$2" = "get" ] && [ "$3" = "prefix" ]; then\n'
        f"  echo '{configured_prefix}'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8")
    npm.chmod(0o755)
    return bindir


def _run_with_fake_npm(script: Path, bindir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{bindir}{os.pathsep}{env['PATH']}"
    return subprocess.run(["node", str(script), "upgrade", "--tag", "beta"],
                          cwd=script.parent.parent, capture_output=True, text=True, env=env)


@pytest.mark.skipif(sys.platform == "win32", reason="posix 全局布局；Windows 布局单列")
def test_cli_upgrade_installs_into_running_prefix_on_mismatch(tmp_path: Path):
    root, prefix = _make_fake_install(tmp_path)
    log = tmp_path / "npm.log"
    bindir = _fake_npm(tmp_path, "/usr/local", log)
    res = _run_with_fake_npm(root / "bin" / "atlas.js", bindir)
    assert res.returncode == 0, res.stderr
    calls = [c for c in log.read_text(encoding="utf-8").splitlines() if c.startswith("install")]
    assert len(calls) == 1
    assert f"--prefix {prefix}" in calls[0]
    assert "/usr/local" not in calls[0]
    assert str(root) in res.stdout and "/usr/local" in res.stdout
    assert "两份安装" in res.stdout
    assert "sudo npm" not in res.stdout + res.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="posix 全局布局；Windows 布局单列")
def test_cli_upgrade_single_install_when_prefix_matches(tmp_path: Path):
    root, prefix = _make_fake_install(tmp_path)
    log = tmp_path / "npm.log"
    bindir = _fake_npm(tmp_path, str(prefix), log)
    res = _run_with_fake_npm(root / "bin" / "atlas.js", bindir)
    assert res.returncode == 0, res.stderr
    calls = [c for c in log.read_text(encoding="utf-8").splitlines() if c.startswith("install")]
    assert len(calls) == 1
    assert f"--prefix {prefix}" in calls[0]
    assert "两份安装" not in res.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="posix 权限语义；Windows 另行覆盖")
def test_cli_upgrade_refuses_unwritable_prefix_without_sudo(tmp_path: Path):
    root, _ = _make_fake_install(tmp_path)
    log = tmp_path / "npm.log"
    bindir = _fake_npm(tmp_path, "/usr/local", log)
    modules = root.parent
    modules.chmod(0o555)
    try:
        res = _run_with_fake_npm(root / "bin" / "atlas.js", bindir)
    finally:
        modules.chmod(0o755)
    assert res.returncode != 0
    assert "不可写" in res.stderr
    assert "npm config set prefix" in res.stderr
    assert "sudo npm install" not in res.stdout + res.stderr
    installs = [c for c in log.read_text(encoding="utf-8").splitlines()
                if c.startswith("install")] if log.exists() else []
    assert installs == []


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


def test_cli_solution_check_dangling_ac_exits_1():
    """#50：悬空 AC 默认即 FAIL、exit 1（本仓 CI 唯一可见点，不是采纳仓的门）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        member = root / "web"
        member.mkdir()
        env = {"GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@b",
               "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@b"}
        subprocess.run(["git", "init", "-q"], cwd=member, check=True, env={**os.environ, **env})
        (member / "app.txt").write_text("app\n", encoding="utf-8")
        subprocess.run(["git", "add", "app.txt"], cwd=member, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=member, check=True,
                       env={**os.environ, **env})
        (root / "atlas.solution.yaml").write_text(
            "version: 1\nsolution: demo\nmode: federated\nmembers:\n"
            "  - name: web\n    path: web\n    assets: member\n"
            "contracts: []\nrequirements:\n"
            "  - id: REQ-001\n    acs: AC-DEMO-999\n    member: web\n"
            "    task_slug: req-001\n    scope: 实现 demo\n"
            "    cross_repo_e2e: none\n",
            encoding="utf-8",
        )
        prd = root / "product" / "prd" / "solution-prd.md"
        prd.parent.mkdir(parents=True)
        prd.write_text(
            "# solution\n\n| AC ID | 场景 | 回指规则 |\n|---|---|---|\n"
            "| AC-DEMO-001 | Given | DEMO-R-001 |\n", encoding="utf-8")
        res = run_cmd(["node", str(ATLAS_BIN), "solution", "check"], cwd=root)
        assert res.returncode == 1, res.stdout + res.stderr
        assert "AC-DEMO-999" in res.stdout
        assert "AC 定义行缺失" in res.stdout


def test_cli_solution_check_help_lists_acs_flags():
    """`--fix-acs` / `--allow-dangling-acs` 必须在本仓 help 可见（不是采纳仓的门）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        res = run_cmd(["node", str(ATLAS_BIN), "solution", "check", "--help"],
                      cwd=Path(tmpdir))
        assert res.returncode == 0, res.stdout + res.stderr
        assert "--fix-acs" in res.stdout
        assert "--allow-dangling-acs" in res.stdout
        assert "0.4.0" in res.stdout and "2026-12-31" in res.stdout


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
