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


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", str(LAUNCHER), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


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
