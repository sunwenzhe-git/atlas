#!/usr/bin/env python3
"""solution Phase 1：清单 / CLI / lock / check 的回归测试。"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PKG_ROOT / "scripts" / "atlas_solution.py"


def load_core():
    path = PKG_ROOT / "_support" / "solution.py"
    spec = importlib.util.spec_from_file_location("_atlas_solution_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = load_core()


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def make_repo(path: Path, files: dict[str, str] | None = None) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    for rel, text in (files or {"app.txt": "app\n"}).items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    git(path, "add", "-A")
    git(path, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "init")
    return path


def test_init_federated_creates_manifest_and_skeleton(tmp_path: Path) -> None:
    make_repo(tmp_path / "web", {"src/a.js": "export const a = 1;\n"})
    make_repo(tmp_path / "api", {"app.py": "print(1)\n"})
    path = core.init_solution(
        tmp_path, "demo",
        [("web", "web", "frontend"), ("api", "api", "backend")],
        install=False,
    )
    text = path.read_text(encoding="utf-8")
    assert "mode: federated" in text
    assert "assets: member" in text
    data = core.load_manifest(tmp_path)
    assert [m["name"] for m in data["members"]] == ["web", "api"]
    assert (tmp_path / "atlas.config.yaml").is_file()
    assert (tmp_path / "product" / "stack-profile.yaml").is_file()
    assert (tmp_path / "product" / "prd" / "solution-prd.md").is_file()
    assert not (tmp_path / ".atlas").exists()


def test_init_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(core.SolutionError):
        core.init_solution(tmp_path, "demo", [("web", "../web", "frontend")],
                           install=False)


def test_manifest_rejects_unified(tmp_path: Path) -> None:
    (tmp_path / "web").mkdir()
    (tmp_path / core.MANIFEST_NAME).write_text(
        "version: 1\nsolution: demo\nmode: unified\nmembers:\n"
        "  - name: web\n    path: web\n    assets: solution\n",
        encoding="utf-8",
    )
    with pytest.raises(core.SolutionError, match="Phase 2"):
        core.load_manifest(tmp_path)


def test_check_warns_non_git_member(tmp_path: Path) -> None:
    (tmp_path / "web").mkdir()
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    data = core.check_solution(tmp_path)
    assert data["overall"] == "WARN"
    assert any("不是 git 仓" in c["detail"] for c in data["checks"])


def test_lock_roundtrip_and_head_drift(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    data = core.load_manifest(tmp_path)
    core.write_lock(tmp_path, data)
    lock = core.read_lock(tmp_path)
    assert lock and lock["members"][0]["name"] == "web"
    assert core.check_solution(tmp_path)["overall"] == "WARN"
    (tmp_path / "web" / "new.txt").write_text("new\n", encoding="utf-8")
    git(tmp_path / "web", "add", "new.txt")
    git(tmp_path / "web", "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "new")
    drift = core.check_solution(tmp_path)
    assert any("HEAD 漂移" in c["detail"] for c in drift["checks"])


def test_diff_reports_commits_since_lock(tmp_path: Path) -> None:
    member = make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    core.write_lock(tmp_path, core.load_manifest(tmp_path))
    (member / "new.txt").write_text("new\n", encoding="utf-8")
    git(member, "add", "new.txt")
    git(member, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "member change")
    entry = core.diff_solution(tmp_path)["members"][0]
    assert entry["head"] != entry["locked_head"]
    assert any("member change" in c for c in entry["commits"])
    assert "自锁以来提交" in core.render_diff({"solution": "demo",
                                               "mode": "federated",
                                               "members": [entry]})
    res = run_cli(tmp_path, "--root", str(tmp_path), "diff", "--json")
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["members"][0]["name"] == "web"


def test_contract_fingerprint_drift(tmp_path: Path) -> None:
    make_repo(tmp_path / "api", {"openapi.yaml": "openapi: 3.0.0\n"})
    make_repo(tmp_path / "web", {"client.ts": "// client\n"})
    core.init_solution(
        tmp_path, "demo",
        [("api", "api", "backend"), ("web", "web", "frontend")],
        install=False,
        contracts=[{"id": "c1", "producer": "api", "producer_path": "openapi.yaml",
                    "consumer": "web", "consumer_path": "client.ts"}],
    )
    data = core.load_manifest(tmp_path)
    core.write_lock(tmp_path, data)
    (tmp_path / "api" / "openapi.yaml").write_text("openapi: 3.1.0\n",
                                                    encoding="utf-8")
    result = core.check_solution(tmp_path)
    assert any("producer_sha256 漂移" in c["detail"] for c in result["checks"])


def test_adopt_detects_members_with_atlas_assets(tmp_path: Path) -> None:
    for name in ("web", "api"):
        path = make_repo(tmp_path / name)
        (path / "atlas.config.yaml").write_text("version: 1\nlayout:\n  assets_root: product\n",
                                                 encoding="utf-8")
    _, members = core.adopt_solution(tmp_path, "demo", install=False)
    assert [m["name"] for m in members] == ["api", "web"]
    assert core.manifest_path(tmp_path).is_file()


def test_cli_status_json(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), "status", "--json"],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert data["solution"] == "demo"
    assert data["members"][0]["name"] == "web"


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True)


def commit_root(root: Path, *paths: str) -> None:
    git(root, "add", *paths)
    git(root, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "root")


def test_init_rejects_duplicate_member_names(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    with pytest.raises(core.SolutionError, match="重复"):
        core.init_solution(tmp_path, "demo",
                           [("web", "web", "frontend"), ("web", "api", "backend")],
                           install=False)


def test_init_rejects_yaml_injection_name(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    with pytest.raises(core.SolutionError, match="非法字符"):
        core.init_solution(tmp_path, "demo\nmode: unified",
                           [("web", "web", "frontend")], install=False)


def test_existing_assets_root_is_honored(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    (tmp_path / "atlas.config.yaml").write_text(
        "version: 1\nlayout:\n  assets_root: docs\n", encoding="utf-8")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       assets_root="product", install=False)
    assert (tmp_path / "docs" / "stack-profile.yaml").is_file()
    assert (tmp_path / "docs" / "prd" / "prd.md").is_file()
    assert not (tmp_path / "product" / "stack-profile.yaml").exists()


def test_check_pass_positive(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    member = make_repo(tmp_path / "web")
    (member / "atlas.config.yaml").write_text(
        "version: 1\nlayout:\n  assets_root: product\n", encoding="utf-8")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    (tmp_path / ".atlas").mkdir()
    (tmp_path / "product" / "prd" / "solution-prd.md").write_text(
        "# solution\n\n无占位符\n", encoding="utf-8")
    core.write_lock(tmp_path, core.load_manifest(tmp_path))
    commit_root(tmp_path, core.MANIFEST_NAME, core.LOCK_NAME)
    result = core.check_solution(tmp_path)
    assert result["overall"] == "PASS", result["checks"]


def test_check_strict_fails_when_lock_untracked_or_stale(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    member = make_repo(tmp_path / "web")
    git(member, "remote", "add", "origin", "https://example.com/web.git")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    result = core.check_solution(tmp_path, strict=True)
    assert result["overall"] == "FAIL"
    assert any("未被父仓 Git 跟踪" in c["detail"] for c in result["checks"])

    commit_root(tmp_path, core.MANIFEST_NAME, core.LOCK_NAME)
    assert core.check_solution(tmp_path, strict=True)["overall"] != "FAIL"

    lock_path = tmp_path / core.LOCK_NAME
    lock_path.write_text(lock_path.read_text(encoding="utf-8") + "\n",
                         encoding="utf-8")
    stale = core.check_solution(tmp_path, strict=True)
    assert stale["overall"] == "FAIL"
    assert any("与父仓 HEAD 不一致" in c["detail"] for c in stale["checks"])


def test_check_strict_fails_on_member_dirty(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    member = make_repo(tmp_path / "web")
    git(member, "remote", "add", "origin", "https://example.com/web.git")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    commit_root(tmp_path, core.MANIFEST_NAME, core.LOCK_NAME)
    (member / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    result = core.check_solution(tmp_path, strict=True)
    assert result["overall"] == "FAIL"
    assert any("未提交改动" in c["detail"] for c in result["checks"])


def test_check_strict_fails_without_member_url(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    commit_root(tmp_path, core.MANIFEST_NAME, core.LOCK_NAME)
    result = core.check_solution(tmp_path, strict=True)
    assert result["overall"] == "FAIL"
    assert any("都没有 url" in c["detail"] for c in result["checks"])


def test_lock_rejects_detached_head(tmp_path: Path) -> None:
    member = make_repo(tmp_path / "web")
    git(member, "checkout", "--detach", "HEAD")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    with pytest.raises(core.SolutionError, match="detached HEAD"):
        core.write_lock(tmp_path, core.load_manifest(tmp_path))


def test_url_rejects_credentials_and_ext_scheme(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    with pytest.raises(core.SolutionError, match="内嵌凭据"):
        core.init_solution(
            tmp_path, "demo",
            [("web", "web", "frontend", "https://user:token@example.com/a.git")],
            install=False)
    with pytest.raises(core.SolutionError, match="白名单"):
        core.init_solution(
            tmp_path, "demo",
            [("web", "web", "frontend", "ext::sh")],
            install=False)


def test_contract_symlink_escape_is_missing(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-secret.yaml"
    outside.write_text("secret\n", encoding="utf-8")
    make_repo(tmp_path / "api", {"openapi.yaml": "openapi: 3.0.0\n"})
    web = make_repo(tmp_path / "web", {"client.ts": "// inside\n"})
    (web / "client.ts").unlink()
    (web / "client.ts").symlink_to(outside)
    core.init_solution(
        tmp_path, "demo",
        [("api", "api", "backend"), ("web", "web", "frontend")],
        install=False,
        contracts=[{"id": "c1", "producer": "api", "producer_path": "openapi.yaml",
                    "consumer": "web", "consumer_path": "client.ts"}],
    )
    states = {c["id"]: c for c in core.contract_states(
        tmp_path, core.load_manifest(tmp_path))}
    assert states["c1"]["consumer_sha256"] == "missing"


def test_cli_check_strict_exit_code(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    member = make_repo(tmp_path / "web")
    git(member, "remote", "add", "origin", "https://example.com/web.git")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    res = run_cli(tmp_path, "--root", str(tmp_path), "check", "--strict")
    assert res.returncode == 1, res.stdout
    assert "FAIL" in res.stdout

    commit_root(tmp_path, core.MANIFEST_NAME, core.LOCK_NAME)
    res = run_cli(tmp_path, "--root", str(tmp_path), "check", "--strict")
    assert res.returncode == 0, res.stdout


@pytest.mark.skipif(not (PKG_ROOT / "install.py").is_file(),
                    reason="副本态（.atlas/）无 install.py；安装器集成只在源包测试")
def test_init_with_install_skips_trellis_and_uses_solution_profile(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=True)
    assert (tmp_path / ".atlas").is_dir()
    assert not (tmp_path / ".trellis").exists()
    profile = (tmp_path / "product" / "stack-profile.yaml").read_text(encoding="utf-8")
    assert "name: web" in profile
    assert "<app 标识>" not in profile


def test_cli_input_errors_exit_2(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    bad_member = run_cli(tmp_path, "--root", str(tmp_path), "init",
                         "--name", "demo", "--member", "bad", "--no-install")
    assert bad_member.returncode == 2
    unified = run_cli(tmp_path, "--root", str(tmp_path), "init",
                      "--name", "demo", "--mode", "unified",
                      "--member", "web=web", "--no-install")
    assert unified.returncode == 2
    assert "Phase 2" in unified.stderr


def test_cli_root_equals_form(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    res = run_cli(tmp_path, f"--root={tmp_path}", "status", "--json")
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["members"][0]["name"] == "web"


def test_corrupt_lock_is_warn_not_crash(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    (tmp_path / core.LOCK_NAME).write_text("[1]\n", encoding="utf-8")
    result = core.check_solution(tmp_path)
    assert result["overall"] == "WARN"
    assert any("契约锁" in c["check"] for c in result["checks"])


def test_adopt_does_not_modify_member(tmp_path: Path) -> None:
    member = make_repo(tmp_path / "web")
    (member / "atlas.config.yaml").write_text(
        "version: 1\nlayout:\n  assets_root: product\n", encoding="utf-8")
    before = subprocess.run(["git", "-C", str(member), "status", "--porcelain",
                             "--untracked-files=all"],
                            capture_output=True, text=True, check=True).stdout
    core.adopt_solution(tmp_path, "demo", install=False)
    after = subprocess.run(["git", "-C", str(member), "status", "--porcelain",
                            "--untracked-files=all"],
                           capture_output=True, text=True, check=True).stdout
    assert before == after


def test_init_half_write_does_not_publish_manifest(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    (tmp_path / "product").mkdir()
    (tmp_path / "product" / "stack-profile.yaml").mkdir()
    with pytest.raises(OSError):
        core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                           install=False)
    assert not core.manifest_path(tmp_path).exists()
    (tmp_path / "product" / "stack-profile.yaml").rmdir()
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    assert core.manifest_path(tmp_path).is_file()


@pytest.mark.skipif(not (PKG_ROOT / "install.py").is_file(),
                    reason="副本态（.atlas/）无 install.py")
def test_init_repairs_incomplete_atlas(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    (tmp_path / ".atlas" / "shared").mkdir(parents=True)
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=True)
    assert (tmp_path / ".atlas" / "VERSION").is_file()
    assert (tmp_path / ".atlas" / "shared" / "solution.md").is_file()


def test_member_path_hash_rejected(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    with pytest.raises(core.SolutionError, match="非法字符"):
        core.init_solution(tmp_path, "demo", [("web", "#web", "frontend")],
                           install=False)


def test_corrupt_lock_structure_is_warn(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    (tmp_path / core.LOCK_NAME).write_text(
        '{"schema_version": 1, "members": "web", "contracts": []}\n',
        encoding="utf-8")
    result = core.check_solution(tmp_path)
    assert result["overall"] == "WARN"
    assert any("契约锁" in c["check"] for c in result["checks"])


def test_missing_contract_file_warns(tmp_path: Path) -> None:
    make_repo(tmp_path / "api")
    make_repo(tmp_path / "web")
    core.init_solution(
        tmp_path, "demo",
        [("api", "api", "backend"), ("web", "web", "frontend")],
        install=False,
        contracts=[{"id": "c1", "producer": "api", "producer_path": "missing.yaml",
                    "consumer": "web", "consumer_path": "missing.ts"}],
    )
    result = core.check_solution(tmp_path)
    assert any("文件缺失" in c["detail"] for c in result["checks"])


def test_user_profile_is_preserved(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    (tmp_path / "product").mkdir()
    custom = "# my profile\nproduct: custom\n"
    (tmp_path / "product" / "stack-profile.yaml").write_text(custom, encoding="utf-8")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    assert (tmp_path / "product" / "stack-profile.yaml").read_text(
        encoding="utf-8") == custom


def test_manifest_rejects_contracts_bogus(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    (tmp_path / core.MANIFEST_NAME).write_text(
        "version: 1\nsolution: demo\nmode: federated\ncontracts: bogus\nmembers:\n"
        "  - name: web\n    path: web\n    assets: member\n",
        encoding="utf-8",
    )
    with pytest.raises(core.SolutionError, match="contracts"):
        core.load_manifest(tmp_path)
