#!/usr/bin/env python3
"""solution Phase 1：成员目录守卫（ignore / gitlink / 非 git）。"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def load_core():
    path = PKG_ROOT / "_support" / "solution.py"
    spec = importlib.util.spec_from_file_location("_atlas_solution_guards_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = load_core()


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "app.txt").write_text("app\n", encoding="utf-8")
    git(path, "add", "app.txt")
    git(path, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "init")
    return path


def make_solution_root(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "README.md").write_text("solution\n", encoding="utf-8")
    git(path, "add", "README.md")
    git(path, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "root")


def details(result: dict) -> str:
    return "；".join(c["detail"] for c in result["checks"])


def test_gitignore_member_warns(tmp_path: Path) -> None:
    make_solution_root(tmp_path)
    (tmp_path / ".gitignore").write_text("web/\n", encoding="utf-8")
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    result = core.check_solution(tmp_path)
    assert "命中 ignore" in details(result)


def test_dotignore_member_warns(tmp_path: Path) -> None:
    make_solution_root(tmp_path)
    (tmp_path / ".ignore").write_text("web/\n", encoding="utf-8")
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    result = core.check_solution(tmp_path)
    assert "命中 ignore" in details(result)


def test_gitlink_member_warns(tmp_path: Path) -> None:
    make_solution_root(tmp_path)
    make_repo(tmp_path / "web")
    git(tmp_path, "add", "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    result = core.check_solution(tmp_path)
    assert "已被 solution 仓跟踪" in details(result)


def test_non_git_member_warns(tmp_path: Path) -> None:
    (tmp_path / "web").mkdir()
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    result = core.check_solution(tmp_path)
    assert "不是 git 仓" in details(result)


def test_rgignore_member_warns(tmp_path: Path) -> None:
    make_solution_root(tmp_path)
    (tmp_path / ".rgignore").write_text("web/\n", encoding="utf-8")
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    assert "命中 ignore" in details(core.check_solution(tmp_path))


def test_info_exclude_member_warns(tmp_path: Path) -> None:
    make_solution_root(tmp_path)
    (tmp_path / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".git" / "info" / "exclude").write_text("web/\n", encoding="utf-8")
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    assert "命中 ignore" in details(core.check_solution(tmp_path))


def test_ignore_glob_prefix_does_not_false_positive(tmp_path: Path) -> None:
    make_solution_root(tmp_path)
    (tmp_path / ".ignore").write_text("apps/**/dist\n", encoding="utf-8")
    make_repo(tmp_path / "apps")
    core.init_solution(tmp_path, "demo", [("apps", "apps", "frontend")],
                       install=False)
    assert "命中 ignore" not in details(core.check_solution(tmp_path))


def test_common_parent_ignore_warns(tmp_path: Path) -> None:
    make_solution_root(tmp_path)
    (tmp_path / ".gitignore").write_text("members/\n", encoding="utf-8")
    (tmp_path / "members").mkdir()
    make_repo(tmp_path / "members" / "web")
    core.init_solution(tmp_path, "demo", [("web", "members/web", "frontend")],
                       install=False)
    assert "命中 ignore" in details(core.check_solution(tmp_path))


def test_symlink_escape_warns(tmp_path: Path) -> None:
    make_solution_root(tmp_path)
    outside = make_repo(tmp_path.parent / f"{tmp_path.name}-outside")
    (tmp_path / "web").symlink_to(outside, target_is_directory=True)
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    assert "逃逸" in details(core.check_solution(tmp_path))


def test_show_untracked_files_disabled_warns(tmp_path: Path) -> None:
    make_solution_root(tmp_path)
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    subprocess.run(["git", "-C", str(tmp_path), "config",
                    "status.showUntrackedFiles", "no"], check=True)
    assert "showUntrackedFiles=no" in details(core.check_solution(tmp_path))


def test_root_not_git_warns(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    assert "不是 git 仓" in details(core.check_solution(tmp_path))
