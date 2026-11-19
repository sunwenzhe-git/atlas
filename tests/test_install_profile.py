"""RFC-20261119-03 Phase 3：装配 Profile 旗标宏（install.py / bin/atlas.js）。"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
INSTALL = PKG_ROOT / "install.py"
CLI = PKG_ROOT / "bin" / "atlas.js"


def _run(td: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(INSTALL), "--target", td, "--dry-run", *extra],
        capture_output=True, text=True, timeout=180)


def test_audit_profile_expands_to_zero_wiring_flags() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = _run(td, "--profile=audit")
        assert p.returncode == 0, p.stdout + p.stderr
        assert "[profile] audit => --no-wiring" in p.stdout
        assert not (Path(td) / ".atlas").exists()
        assert not (Path(td) / ".atlas").exists()


def test_adopt_and_strict_profiles_expand() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = _run(td, "--profile=adopt", "--force")
        assert p.returncode == 0, p.stdout + p.stderr
        assert "[profile] adopt => --no-wiring" in p.stdout
        assert not (Path(td) / ".atlas").exists()
    with tempfile.TemporaryDirectory() as td:
        p = _run(td, "--profile=strict", "--force")
        assert p.returncode == 0, p.stdout + p.stderr
        assert "[profile] strict => （无附加旗标）" in p.stdout
        assert not (Path(td) / ".atlas").exists()


def test_separate_profile_arg_is_supported() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = _run(td, "--profile", "audit")
        assert p.returncode == 0, p.stdout + p.stderr
        assert "[profile] audit" in p.stdout


def test_unknown_profile_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = _run(td, "--profile=loose")
        assert p.returncode == 2, p.stdout + p.stderr
        assert "未知 profile" in p.stderr


def test_cli_help_mentions_profile() -> None:
    node = shutil.which("node")
    if not node:
        return
    p = subprocess.run([node, str(CLI), "--help"], capture_output=True, text=True,
                       timeout=30)
    assert p.returncode == 0, p.stderr
    assert "--profile=audit" in p.stdout
