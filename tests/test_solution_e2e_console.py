#!/usr/bin/env python3
"""solution Phase 1：e2e_console 的成员 dirty / app_hash 感知。"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = load("_atlas_solution_e2e_core", "_support/solution.py")
console = load("_atlas_solution_e2e_console", "scripts/e2e_console.py")


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def make_repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    for rel, text in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    git(path, "add", "-A")
    git(path, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "init")
    return path


def make_solution(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    make_repo(tmp_path / "web", {"src/a.js": "export const a = 1;\n"})
    make_repo(tmp_path / "api", {"app.py": "print(1)\n"})
    core.init_solution(
        tmp_path, "demo",
        [("web", "web", "frontend"), ("api", "api", "backend")],
        install=False,
    )
    git(tmp_path, "add", "atlas.config.yaml", "atlas.solution.yaml",
        "atlas.solution.lock.json", "product")
    git(tmp_path, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "assets")
    return tmp_path


def test_solution_member_dirty_and_hash(tmp_path: Path) -> None:
    root = make_solution(tmp_path)
    assert console.repo_git_dirty(root) is False
    before = console.app_fingerprint(root)
    assert before
    (root / "web" / "src" / "a.js").write_text("export const a = 2;\n",
                                                encoding="utf-8")
    assert console.repo_git_dirty(root) is True
    after = console.app_fingerprint(root)
    assert after and after != before


def test_non_ascii_member_path(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    member = make_repo(tmp_path / "web 测试", {"src/a.js": "export const a = 1;\n"})
    core.init_solution(tmp_path, "demo", [("web 测试", "web 测试", "frontend")],
                       install=False)
    git(tmp_path, "add", "atlas.config.yaml", "atlas.solution.yaml",
        "atlas.solution.lock.json", "product")
    git(tmp_path, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "assets")
    assert console.repo_git_dirty(tmp_path) is False
    (member / "src" / "a.js").write_text("export const a = 2;\n", encoding="utf-8")
    assert console.repo_git_dirty(tmp_path) is True


def test_non_git_member_fingerprint_is_none(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "web").mkdir()
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    assert console.app_fingerprint(tmp_path) is None


def test_symlink_member_fingerprint_is_none(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    outside = make_repo(tmp_path.parent / f"{tmp_path.name}-outside", {"a.js": "1\n"})
    (tmp_path / "web").symlink_to(outside, target_is_directory=True)
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    assert console.app_fingerprint(tmp_path) is None


def test_tracked_member_is_dirty(tmp_path: Path) -> None:
    root = make_solution(tmp_path)
    git(root, "add", "web")
    assert console.repo_git_dirty(root) is True
