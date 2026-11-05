#!/usr/bin/env python3
"""`scripts/run_python.js` 启动器回归（RFC-20261103-04 §6 决策 3）。

钩子写在 git 跟踪的 `.trellis/config.yaml` 里，跨 OS 必须同一串命令可用：
启动器在运行时解析 Python 3.10+，转发 argv 与退出码。这里钉住四件事：
argv 透传 / 退出码透传 / 缺参数 fail-closed / 叶子进程强制 UTF-8。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = PKG_ROOT / "scripts" / "run_python.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="需要 node 才能跑启动器（Atlas CLI 的硬依赖；缺席环境不是通过）",
)


def _run_at(launcher: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(launcher), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return _run_at(LAUNCHER, args)


def test_launcher_is_module_type_agnostic() -> None:
    """内容钉：发射物不得依赖 CJS 的 `require`，且仍可按 CJS 语法解析。

    宿主的 `package.json` 决定 `.js` 的解析模式：装配进 `"type": "module"` 的仓时，
    `require` 不存在。启动器必须用两种模式都合法的动态 `import()`。
    """
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "require(" not in text, "启动器回退了 CJS 的 require（ESM 宿主会 ReferenceError）"
    assert "await import('node:child_process')" in text, "启动器未走动态 import 入口"
    r = subprocess.run(
        ["node", "--check", str(LAUNCHER)], capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 0, r.stderr


def test_runs_from_esm_host(tmp_path: Path) -> None:
    """行为钉：把发射物放进 `"type": "module"` 的宿主上下文，argv 与退出码仍正确。

    复现 2026-11-05 的真实缺陷：CJS `require` 在 ESM 宿主里直接崩，4 条钉全红；
    修复后本钉必须绿（变异 M192 = 回退裸 require ⇒ 本钉红）。
    """
    host = tmp_path / "esm-host"
    host.mkdir()
    (host / "package.json").write_text('{"type": "module"}\n', encoding="utf-8")
    launcher = host / "run_python.js"
    shutil.copyfile(LAUNCHER, launcher)
    script = host / "echo.py"
    script.write_text(
        "import sys\nprint('|'.join(sys.argv[1:]))\nraise SystemExit(7)\n",
        encoding="utf-8",
    )
    r = _run_at(launcher, [str(script), "a", "b"])
    assert r.returncode == 7, (r.stdout, r.stderr)
    assert r.stdout.strip() == "a|b", r.stdout
    missing = _run_at(launcher, [])
    assert missing.returncode == 2, missing.stderr


def test_forwards_argv_and_exit_code(tmp_path: Path) -> None:
    script = tmp_path / "echo.py"
    script.write_text(
        "import sys\nprint('|'.join(sys.argv[1:]))\nraise SystemExit(7)\n",
        encoding="utf-8",
    )
    r = _run([str(script), "a", "b"])
    assert r.returncode == 7, (r.stdout, r.stderr)
    assert r.stdout.strip() == "a|b", r.stdout


def test_requires_script_argument() -> None:
    r = _run([])
    assert r.returncode == 2
    assert "用法" in r.stderr, r.stderr


def test_finds_python_310_and_reports_version(tmp_path: Path) -> None:
    script = tmp_path / "ver.py"
    script.write_text("import sys\nprint('%d.%d' % sys.version_info[:2])\n", encoding="utf-8")
    r = _run([str(script)])
    assert r.returncode == 0, r.stderr
    major, minor = r.stdout.strip().split(".")
    assert int(major) == 3 and int(minor) >= 10, r.stdout


def test_leaf_gets_utf8_mode(tmp_path: Path) -> None:
    script = tmp_path / "cn.py"
    script.write_text("import sys\nprint('中文输出', sys.flags.utf8_mode)\n", encoding="utf-8")
    r = _run([str(script)])
    assert r.returncode == 0, r.stderr
    assert "中文输出" in r.stdout, r.stdout
    assert "1" in r.stdout.split()[-1], r.stdout  # PYTHONUTF8=1 生效
