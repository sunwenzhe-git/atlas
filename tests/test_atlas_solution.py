#!/usr/bin/env python3
"""solution Phase 1：清单 / CLI / lock / check 的回归测试。"""
from __future__ import annotations

import importlib.util
import argparse
import json
import re
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


def load_e2e_kernel():
    path = PKG_ROOT / "_support" / "solution_e2e.py"
    spec = importlib.util.spec_from_file_location("_atlas_solution_e2e_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = load_core()
e2e_kernel = load_e2e_kernel()


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


def test_b_v18_init_fail_closed_when_reader_version_unknown(
        tmp_path: Path, monkeypatch) -> None:
    """RFC §5.2 第 8 条 / V-18：三级来源全缺 ⇒ init exit 2 且不写任何文件。"""
    import shutil

    toolroot = tmp_path / "toolroot"
    toolroot.mkdir()
    monkeypatch.setattr(core, "_TOOL_PACKAGE_ROOT", toolroot)
    make_repo(tmp_path / "web")
    before = sorted(p.name for p in tmp_path.iterdir())

    with pytest.raises(core.SolutionError, match="reader_version_unknown"):
        core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                           install=False)
    assert sorted(p.name for p in tmp_path.iterdir()) == before

    # CLI 面：真跑一份「工具包根没有 package.json」的副本，确认 exit 2 与固定提示
    pkg = tmp_path / "tool"
    (pkg / "scripts").mkdir(parents=True)
    shutil.copy(PKG_ROOT / "scripts" / "atlas_solution.py",
                pkg / "scripts" / "atlas_solution.py")
    shutil.copytree(PKG_ROOT / "_support", pkg / "_support")
    target = tmp_path / "proj"
    (target / "web").mkdir(parents=True)
    res = subprocess.run(
        [sys.executable, str(pkg / "scripts" / "atlas_solution.py"),
         "--root", str(target), "init", "--name", "demo", "--member", "web=web"],
        capture_output=True, text=True)
    assert res.returncode == 2, (res.returncode, res.stdout, res.stderr)
    assert "reader_version_unknown" in res.stderr
    assert not (target / core.MANIFEST_NAME).exists()
    assert not (target / "atlas.config.yaml").exists()
    assert not (target / "product").exists()


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
    # 干净样本包含已初始化的父仓 E2E 骨架（RFC-20261108-02：未初始化是 WARN）。
    e2e_kernel.init(tmp_path)
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


# ---------------------------------------------------------------- #50 悬空 AC 门禁（批次 1）

def load_task_core():
    path = PKG_ROOT / "_support" / "solution_task.py"
    spec = importlib.util.spec_from_file_location("_atlas_solution_task_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


task_core = load_task_core()

PRD_AC = (
    "# solution\n\n| AC ID | 场景 | 回指规则 |\n|---|---|---|\n"
    "| AC-DEMO-001 | Given / When / Then | DEMO-R-001 |\n"
)

AC_REQ = {"id": "REQ-001", "acs": ["AC-DEMO-001"], "member": "web",
          "task_slug": "req-001", "scope": "实现 demo", "cross_repo_e2e": "none"}


def make_ac_solution(tmp_path: Path, acs=("AC-DEMO-001",), prd: str | None = PRD_AC) -> dict:
    """最小合法夹具：单成员、清单合法、E2E 选择器已显式 none。

    坏输入只会被 #50 的 AC 判据接住，不会先被锁 / URL / 选择器拦下。
    """
    make_repo(tmp_path / "web")
    core.init_solution(
        tmp_path, "demo", [("web", "web", "frontend")], install=False,
        requirements=[dict(AC_REQ, acs=list(acs))],
    )
    prd_path = tmp_path / "product" / "prd" / "solution-prd.md"
    if prd is None:
        prd_path.unlink()
    else:
        prd_path.write_text(prd, encoding="utf-8")
    return core.load_manifest(tmp_path)


def ac_fails(report: dict) -> list[dict]:
    return [c for c in report["checks"]
            if c["check"] == "跨仓任务" and c["status"] == "FAIL"]


def test_a_dangling_ac_fails_by_default_and_exit_1(tmp_path: Path) -> None:
    make_ac_solution(tmp_path, acs=("AC-DEMO-001", "AC-DEMO-999"))
    report = core.check_solution(tmp_path)
    assert report["overall"] == "FAIL"
    fails = ac_fails(report)
    assert any("AC-DEMO-999" in c["detail"] and "AC 定义行缺失" in c["detail"]
               for c in fails)
    assert not any("AC 定义源不可用" in c["detail"] for c in fails)
    res = run_cli(tmp_path, "--root", str(tmp_path), "check")
    assert res.returncode == 1, res.stdout + res.stderr


def test_b_missing_prd_is_source_unavailable_not_dangling(tmp_path: Path) -> None:
    make_ac_solution(tmp_path, prd=None)
    report = core.check_solution(tmp_path)
    assert report["overall"] == "FAIL"
    detail = "\n".join(c["detail"] for c in ac_fails(report))
    assert "AC 定义源不可用" in detail
    assert "AC 定义行缺失" not in detail
    assert "product/prd/solution-prd.md" in detail


def test_c_assets_root_mismatch_is_source_unavailable(tmp_path: Path) -> None:
    make_ac_solution(tmp_path)
    (tmp_path / "atlas.config.yaml").write_text(
        "version: 1\nlayout:\n  assets_root: docs\n", encoding="utf-8")
    report = core.check_solution(tmp_path)
    assert report["overall"] == "FAIL"
    detail = "\n".join(c["detail"] for c in ac_fails(report))
    assert "AC 定义源不可用" in detail
    assert "AC 定义行缺失" not in detail
    assert "docs/prd/solution-prd.md" in detail


def test_d_zero_ac_definitions_is_source_unavailable(tmp_path: Path) -> None:
    make_ac_solution(
        tmp_path,
        prd="# solution\n\n| AC ID | 场景 | 回指规则 |\n|---|---|---|\n")
    report = core.check_solution(tmp_path)
    assert report["overall"] == "FAIL"
    detail = "\n".join(c["detail"] for c in ac_fails(report))
    assert "AC 定义源不可用" in detail
    assert "AC 定义行缺失" not in detail


def test_k_check_and_task_status_share_one_guard(tmp_path: Path) -> None:
    data = make_ac_solution(tmp_path, prd=None)
    report = core.check_solution(tmp_path)
    status = task_core.task_status(tmp_path, data)
    assert any("AC 定义源不可用" in c["detail"] for c in ac_fails(report))
    assert any("AC 定义源不可用" in w for w in status["warnings"])
    assert not any("AC 定义行缺失" in w for w in status["warnings"])


def test_r1_backticked_and_padded_ac_rows_pass(tmp_path: Path) -> None:
    prd = ("# solution\n\n| AC ID | 场景 | 回指规则 |\n|---|---|---|\n"
           "|  `AC-DEMO-001`  | Given | DEMO-R-001 |\n")
    make_ac_solution(tmp_path, prd=prd)
    report = core.check_solution(tmp_path)
    assert not ac_fails(report)
    assert run_cli(tmp_path, "--root", str(tmp_path), "check").returncode == 0


def seed_member_task(member: Path, requirement: str = "REQ-001") -> None:
    """造一张与清单对齐的成员任务卡，让 R2 的 PASS 不被既有 task_missing WARN 拉低。"""
    task = member / ".trellis" / "tasks" / "11-11-req-001"
    task.mkdir(parents=True)
    (task / "task.json").write_text(json.dumps({"meta": {
        "solution": "demo", "requirement": requirement, "member": member.name,
    }}), encoding="utf-8")
    (task / "solution.md").write_text("# 跨仓任务指针\n", encoding="utf-8")
    for kind in ("implement", "check"):
        (task / f"{kind}.jsonl").write_text(
            json.dumps({"file": f"{task.name}/solution.md", "reason": "指针"}) + "\n",
            encoding="utf-8")


def test_r2_defined_acs_pass_default_and_strict(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    member = make_repo(tmp_path / "web")
    (member / "atlas.config.yaml").write_text(
        "version: 1\nlayout:\n  assets_root: product\n", encoding="utf-8")
    seed_member_task(member)
    git(member, "add", "-A")
    git(member, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "cfg")
    core.init_solution(
        tmp_path, "demo",
        [("web", "web", "frontend", "https://example.com/web.git")],
        install=False, requirements=[AC_REQ],
    )
    (tmp_path / ".atlas").mkdir()
    (tmp_path / "product" / "prd" / "solution-prd.md").write_text(
        PRD_AC, encoding="utf-8")
    e2e_kernel.init(tmp_path)
    core.write_lock(tmp_path, core.load_manifest(tmp_path))
    commit_root(tmp_path, core.MANIFEST_NAME, core.LOCK_NAME)
    assert core.check_solution(tmp_path)["overall"] == "PASS"
    strict = core.check_solution(tmp_path, strict=True)
    assert strict["overall"] == "PASS", strict["checks"]
    assert run_cli(tmp_path, "--root", str(tmp_path), "check", "--strict").returncode == 0


def test_r3_missing_task_stays_warn(tmp_path: Path) -> None:
    make_ac_solution(tmp_path)
    report = core.check_solution(tmp_path)
    assert not ac_fails(report)
    assert report["overall"] != "FAIL"
    assert any(c["check"] == "跨仓任务" and c["status"] == "WARN"
               and "成员任务缺失" in c["detail"] for c in report["checks"])


def test_r4_skeleton_without_requirements_does_not_trigger(tmp_path: Path) -> None:
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")],
                       install=False)
    report = core.check_solution(tmp_path)
    assert not ac_fails(report)
    assert any(c["check"] == "solution-prd.md" and c["status"] == "WARN"
               for c in report["checks"])


def test_r5_task_status_warnings_stay_string_list(tmp_path: Path) -> None:
    data = make_ac_solution(tmp_path, acs=("AC-DEMO-001", "AC-DEMO-999"))
    status = task_core.task_status(tmp_path, data)
    assert all(isinstance(w, str) for w in status["warnings"])
    assert len([w for w in status["warnings"] if "AC-DEMO-999" in w]) == 1
    assert len([w for w in status["warnings"] if "AC-DEMO-001" in w]) == 0


def test_r6_same_finding_appears_once_per_ac(tmp_path: Path) -> None:
    data = make_ac_solution(
        tmp_path, acs=("AC-DEMO-001", "AC-DEMO-998", "AC-DEMO-999"))
    report = core.check_solution(tmp_path)
    for ac in ("AC-DEMO-998", "AC-DEMO-999"):
        rows = [c for c in report["checks"] if "AC 定义行缺失" in c["detail"]
                and ac in c["detail"]]
        assert len(rows) == 1, rows
        assert rows[0]["status"] == "FAIL"
    assert not [c for c in report["checks"]
                if c["status"] == "WARN" and "AC 定义行缺失" in c["detail"]]
    warnings = [w for w in task_core.task_status(tmp_path, data)["warnings"]
                if "AC 定义行缺失" in w]
    assert len(warnings) == 2


# ---------------------------------------------------------------- #50 --fix-acs（批次 2）

def build_raw_solution(tmp_path: Path, req_text: str, members=("web",),
                       prd: str | None = PRD_AC) -> Path:
    for name in members:
        make_repo(tmp_path / name)
    text = (
        "version: 1\nsolution: demo\nmode: federated\nmembers:\n"
        + "".join(f"  - name: {n}\n    path: {n}\n    assets: member\n" for n in members)
        + "contracts: []\nrequirements:\n" + req_text
    )
    manifest = tmp_path / core.MANIFEST_NAME
    manifest.write_text(text, encoding="utf-8")
    prd_path = tmp_path / "product" / "prd" / "solution-prd.md"
    prd_path.parent.mkdir(parents=True, exist_ok=True)
    if prd is None:
        prd_path.unlink(missing_ok=True)
    else:
        prd_path.write_text(prd, encoding="utf-8")
    return manifest


REQ_RAW = (
    "  - id: REQ-001\n"
    "    scope: 实现 demo   # 自定义键序\n"
    "    acs: AC-DEMO-001,AC-DEMO-999  # 说明\n"
    "    member: web\n"
    "    task_slug: req-001\n"
    "    cross_repo_e2e: none\n"
)


def check_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_cli(tmp_path, "--root", str(tmp_path), "check", *args)


def test_b1_same_requirement_id_across_members_keeps_both_findings(tmp_path: Path) -> None:
    """B1 + 去重真钉：去重键必须含 `member`，`task_findings` 也必须按 `(id, member)` 分组。

    同一 id 分属 web / api（无 E2E 选择器），两行引用同一个未定义 AC。正确实现下
    `check_solution` 与 `task_status` **都恰出 2 条**（web、api 各一条）：
    * 键退回 `(code, requirement, ac)` ⇒ api 那条被 check_solution 吞掉，只剩 1 条；
    * `task_findings` 退回按 requirement 聚合（每行拉该 id 全量 finding）⇒ 2 条变 4 条。
    两者都与这里的 `== 2` 不符，故本条同时是「去重消失即红」的夹具。
    """
    req = (
        "  - id: REQ-001\n"
        "    acs: AC-DEMO-001,AC-DEMO-999\n"
        "    member: web\n"
        "    task_slug: req-001\n"
        "    scope: 实现 demo\n"
        "  - id: REQ-001\n"
        "    acs: AC-DEMO-001,AC-DEMO-999\n"
        "    member: api\n"
        "    task_slug: req-001-api\n"
        "    scope: 实现 demo\n"
    )
    build_raw_solution(tmp_path, req, members=("web", "api"))
    report = core.check_solution(tmp_path)
    rows = [c for c in report["checks"] if "AC 定义行缺失" in c["detail"]
            and "AC-DEMO-999" in c["detail"]]
    assert len(rows) == 2, rows
    assert all(r["status"] == "FAIL" for r in rows)
    assert any("REQ-001/web" in r["detail"] for r in rows)
    assert any("REQ-001/api" in r["detail"] for r in rows)
    warnings = [w for w in task_core.task_status(
        tmp_path, core.load_manifest(tmp_path))["warnings"]
        if "AC 定义行缺失" in w and "AC-DEMO-999" in w]
    assert len(warnings) == 2, warnings  # 不得靠 set/前缀把重复掩盖掉
    assert any("REQ-001/web" in w for w in warnings)
    assert any("REQ-001/api" in w for w in warnings)


def test_e1a_duplicate_acs_key_refuses_without_writing(tmp_path: Path) -> None:
    req = (
        "  - id: REQ-001\n"
        "    acs: AC-DEMO-001,AC-DEMO-999\n"
        "    acs: AC-DEMO-001,AC-DEMO-999\n"
        "    member: web\n"
        "    task_slug: req-001\n"
        "    scope: 实现 demo\n"
        "    cross_repo_e2e: none\n"
    )
    manifest = build_raw_solution(tmp_path, req)
    before = manifest.read_bytes()
    res = check_cli(tmp_path, "--fix-acs", "--apply")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "无法唯一定位" in (res.stdout + res.stderr)
    assert manifest.read_bytes() == before


def test_e1b_same_id_on_two_members_refuses_without_writing(tmp_path: Path) -> None:
    req = (
        "  - id: REQ-001\n"
        "    acs: AC-DEMO-001,AC-DEMO-999\n"
        "    member: web\n"
        "    task_slug: req-001\n"
        "    scope: 实现 demo\n"
        "    cross_repo_e2e: none\n"
        "  - id: REQ-001\n"
        "    acs: AC-DEMO-001,AC-DEMO-999\n"
        "    member: api\n"
        "    task_slug: req-001-api\n"
        "    scope: 实现 demo\n"
    )
    manifest = build_raw_solution(tmp_path, req, members=("web", "api"))
    before = manifest.read_bytes()
    res = check_cli(tmp_path, "--fix-acs", "--apply")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "无法唯一定位" in (res.stdout + res.stderr)
    assert manifest.read_bytes() == before


def test_f_fix_acs_preserves_other_bytes_and_comment(tmp_path: Path) -> None:
    manifest = build_raw_solution(tmp_path, REQ_RAW)
    before = manifest.read_bytes()
    res = check_cli(tmp_path, "--fix-acs", "--apply")
    assert res.returncode == 0, res.stdout + res.stderr
    after = manifest.read_bytes()
    old_lines = before.splitlines()
    new_lines = after.splitlines()
    changed = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
    assert len(changed) == 1, changed
    assert "    acs: AC-DEMO-001  # 说明".encode() == new_lines[changed[0]]
    assert after.endswith(b"\n")
    assert "# 说明".encode() in after  # 行尾注释保留
    assert b"AC-DEMO-999" not in after
    # 自定义键序不被重排：scope 仍在 acs 前
    assert after.index(b"scope:") < after.index(b"acs:")


def test_f2_fix_acs_preserves_crlf_line_endings(tmp_path: Path) -> None:
    """F 的 CRLF 变体：行尾保字节必须连 `\\r\\n` 一起保留，不得混入裸 LF。"""
    manifest = build_raw_solution(tmp_path, REQ_RAW)
    manifest.write_bytes(manifest.read_bytes().replace(b"\n", b"\r\n"))
    before = manifest.read_bytes()
    assert before.count(b"\r\n") == 15
    res = check_cli(tmp_path, "--fix-acs", "--apply")
    assert res.returncode == 0, res.stdout + res.stderr
    after = manifest.read_bytes()
    assert after.count(b"\r\n") == 15
    assert b"\n" not in after.replace(b"\r\n", b"")  # 无裸 LF
    old_lines = before.split(b"\r\n")
    new_lines = after.split(b"\r\n")
    changed = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
    assert len(changed) == 1, changed
    assert new_lines[changed[0]] == "    acs: AC-DEMO-001  # 说明".encode()
    assert b"AC-DEMO-999" not in after


def test_h_ideographic_comma_separator(tmp_path: Path) -> None:
    req = REQ_RAW.replace("AC-DEMO-001,AC-DEMO-999", "AC-DEMO-001、AC-DEMO-999")
    manifest = build_raw_solution(tmp_path, req)
    res = check_cli(tmp_path, "--fix-acs", "--apply")
    assert res.returncode == 0, res.stdout + res.stderr
    text = manifest.read_text(encoding="utf-8")
    assert "acs: AC-DEMO-001  # 说明" in text
    assert "AC-DEMO-999" not in text


def test_h2_fullwidth_comma_separator(tmp_path: Path) -> None:
    req = REQ_RAW.replace("AC-DEMO-001,AC-DEMO-999", "AC-DEMO-001，AC-DEMO-999")
    manifest = build_raw_solution(tmp_path, req)
    res = check_cli(tmp_path, "--fix-acs", "--apply")
    assert res.returncode == 0, res.stdout + res.stderr
    text = manifest.read_text(encoding="utf-8")
    assert "acs: AC-DEMO-001  # 说明" in text
    assert "AC-DEMO-999" not in text


def test_i_last_token_refuses_and_keeps_bytes(tmp_path: Path) -> None:
    req = (
        "  - id: REQ-001\n"
        "    acs: AC-DEMO-999  # 说明\n"
        "    member: web\n"
        "    task_slug: req-001\n"
        "    scope: 实现 demo\n"
        "    cross_repo_e2e: none\n"
    )
    manifest = build_raw_solution(tmp_path, req)
    before = manifest.read_bytes()
    res = check_cli(tmp_path, "--fix-acs", "--apply")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "拒绝清空" in (res.stdout + res.stderr)
    assert "手工删除整条 requirement" in (res.stdout + res.stderr)
    assert manifest.read_bytes() == before


def test_j_write_success_but_gate_still_red_exits_1(tmp_path: Path) -> None:
    """J：写成功 ≠ 门变绿，退出码只由重跑结果决定（M7 的咬点）。

    夹具与旧版的区别：REQ-002 带一个**同样无定义**的 AC（`AC-DEMO-777`）并显式
    `cross_repo_e2e: none` —— 旧版缺该键时 exit 1 来自 E2E「二选一」报错，与 AC 无关。
    现在两条需求的悬空 AC 在同一轮被移除（stdout 留 `[REMOVED] REQ-002/AC-DEMO-777`），
    写成功成立；`--strict` 下重跑仍因基线（根非 git / 缺契约锁）FAIL ⇒ exit 1。
    注：`fix_acs` 一次性移除全部悬空 AC，结构上不存在「写成功但仍有悬空 AC 残留」，
    故 J 只能钉「写成功 + 重跑定退出码」这一层。
    """
    req = REQ_RAW + (
        "  - id: REQ-002\n"
        "    acs: AC-DEMO-001,AC-DEMO-777\n"
        "    member: web\n"
        "    task_slug: req-002\n"
        "    scope: 另一条需求\n"
        "    cross_repo_e2e: none\n"
    )
    manifest = build_raw_solution(tmp_path, req)
    res = check_cli(tmp_path, "--fix-acs", "--apply", "--strict")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "AC-DEMO-777" in res.stdout
    assert "[REMOVED] REQ-002/AC-DEMO-777" in res.stdout
    text = manifest.read_text(encoding="utf-8")
    assert "AC-DEMO-999" not in text
    assert "AC-DEMO-777" not in text
    # 退出码不是 E2E 选择器构造错误带来的：两条需求都显式 N/A 且 PASS
    assert "父仓 E2E 选择器: REQ-002: N/A" in res.stdout
    assert "二选一" not in res.stdout + res.stderr


def test_r7_flow_and_block_lists_exit_2(tmp_path: Path) -> None:
    flow = REQ_RAW.replace("AC-DEMO-001,AC-DEMO-999",
                           "[AC-DEMO-001, AC-DEMO-999]")
    build_raw_solution(tmp_path, flow)
    res = check_cli(tmp_path, "--fix-acs", "--apply")
    assert res.returncode == 2, res.stdout + res.stderr

    other = tmp_path / "block"
    build_raw_solution(other, (
        "  - id: REQ-001\n"
        "    acs:\n"
        "      - AC-DEMO-001\n"
        "      - AC-DEMO-999\n"
        "    member: web\n"
        "    task_slug: req-001\n"
        "    scope: 实现 demo\n"
    ))
    res = check_cli(other, "--fix-acs", "--apply")
    assert res.returncode == 2, res.stdout + res.stderr


def test_fix_acs_dry_run_writes_nothing(tmp_path: Path) -> None:
    manifest = build_raw_solution(tmp_path, REQ_RAW)
    before = manifest.read_bytes()
    res = check_cli(tmp_path, "--fix-acs")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "[DRY-RUN] REQ-001/AC-DEMO-999 @ line" in res.stdout
    assert manifest.read_bytes() == before


def test_fix_acs_source_unavailable_refuses(tmp_path: Path) -> None:
    manifest = build_raw_solution(tmp_path, REQ_RAW, prd=None)
    before = manifest.read_bytes()
    res = check_cli(tmp_path, "--fix-acs", "--apply")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "AC 定义源不可用" in (res.stdout + res.stderr)
    assert manifest.read_bytes() == before


# ---------------------------------------------------------------- #50 宽限与版本门（批次 3）

def load_cli_module():
    path = PKG_ROOT / "scripts" / "atlas_solution.py"
    spec = importlib.util.spec_from_file_location("_atlas_solution_cli_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cli = load_cli_module()


def check_option_strings(version: str) -> set[str]:
    parser = cli.build_parser(version)
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return {opt for a in action.choices["check"]._actions
                    for opt in a.option_strings}
    raise AssertionError("check 子命令不存在")


def test_g_grace_only_covers_class_a(tmp_path: Path) -> None:
    a = tmp_path / "a"
    make_ac_solution(a, acs=("AC-DEMO-001", "AC-DEMO-999"))
    res = run_cli(a, "--root", str(a), "check", "--allow-dangling-acs")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "0.4.0" in res.stdout and "2026-12-31" in res.stdout
    assert "宽限" in res.stdout

    b = tmp_path / "b"
    make_ac_solution(b, prd=None)
    c = tmp_path / "c"
    make_ac_solution(c)
    (c / "atlas.config.yaml").write_text(
        "version: 1\nlayout:\n  assets_root: docs\n", encoding="utf-8")
    d = tmp_path / "d"
    make_ac_solution(
        d, prd="# solution\n\n| AC ID | 场景 | 回指规则 |\n|---|---|---|\n")
    for name, root in (("B", b), ("C", c), ("D", d)):
        res = run_cli(root, "--root", str(root), "check", "--allow-dangling-acs")
        assert res.returncode == 1, f"{name}: {res.stdout}{res.stderr}"
        assert "AC 定义源不可用" in res.stdout, name


def test_m6_grace_flag_is_version_gated(tmp_path: Path) -> None:
    current = json.loads((PKG_ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    # 1) 基线：当前版本 < 0.4.0 ⇒ flag 必须在
    assert cli.semver_lt(current, "0.4.0")
    assert cli._allow_dangling_acs_enabled(current) is True
    assert "--allow-dangling-acs" in check_option_strings(current)
    # 2) 0.3.x（RFC-20261111-03 §2.6 的退役点推迟到 0.4.0）⇒ 仍注册
    assert cli._allow_dangling_acs_enabled("0.3.0") is True
    assert "--allow-dangling-acs" in check_option_strings("0.3.0")
    assert cli._allow_dangling_acs_enabled("0.3.9") is True
    # 3) 合成 0.4.0 ⇒ 必须 False，help/选项集合都不得含该 flag
    assert cli._allow_dangling_acs_enabled("0.4.0") is False
    assert "--allow-dangling-acs" not in check_option_strings("0.4.0")
    # 4) 真实版本 ≥ 0.4.0 ⇒ 同样不得注册（发版当天自动生效）
    if not cli.semver_lt(current, "0.4.0"):
        assert "--allow-dangling-acs" not in check_option_strings(current)
    # 5) 预发布：0.4.0-beta.1 在 semver 下 < 0.4.0 ⇒ 宽限仍可注册
    assert cli._allow_dangling_acs_enabled("0.4.0-beta.1") is True


# ---------------------------------------------------------------- B-0（RFC-20261111-03）

V2_MANIFEST = """\
version: 2
solution: demo
mode: federated
definition:
  domain: solution
  path: product/prd/solution-prd.md
acceptance_cutover: 2027-03-31
min_atlas: 0.4.0

members:
  - name: web
    path: web
    assets: member
    kind: frontend
"""


def test_b0_v2_manifest_roundtrip_keeps_definition_and_scalars(tmp_path: Path) -> None:
    """D-32：v2 新键进结构，不落 unknown；load_manifest 版本为 2。"""
    data = core.parse_manifest_text(V2_MANIFEST)
    assert data["unknown"] == []
    assert data["definition"] == {"domain": "solution",
                                  "path": "product/prd/solution-prd.md"}
    assert data["acceptance_cutover"] == "2027-03-31"
    assert data["min_atlas"] == "0.4.0"

    (tmp_path / "web").mkdir()
    (tmp_path / core.MANIFEST_NAME).write_text(V2_MANIFEST, encoding="utf-8")
    loaded = core.load_manifest(tmp_path)
    assert loaded["version"] == 2
    assert loaded["definition"]["path"] == "product/prd/solution-prd.md"


def test_b0_definition_null_normalizes_to_none_not_unknown() -> None:
    """D-33：`definition: null` 经 `_scalar` ⇒ None，不进 unknown。"""
    data = core.parse_manifest_text(
        "version: 2\nsolution: demo\nmode: federated\ndefinition: null\nmembers: []\n")
    assert data["definition"] is None
    assert data["unknown"] == []


def test_b0_unknown_manifest_keys_raise_instead_of_silently_dropped() -> None:
    """D-32 反面包：未知顶层键 / 未知 definition 子键都不许静默丢弃。"""
    with pytest.raises(core.SolutionError, match="manifest_field_unknown"):
        core.parse_manifest_text(
            "version: 2\nsolution: demo\nmode: federated\nbogus: 1\nmembers: []\n")
    with pytest.raises(core.SolutionError, match="definition_field_unknown"):
        core.parse_manifest_text(
            "version: 2\nsolution: demo\nmode: federated\n"
            "definition:\n  domain: demo\n  bogus: x\n")


def test_b0_version_gate_accepts_1_and_2_rejects_others(tmp_path: Path) -> None:
    """§5.3：0.3.x 同时接受 v1 / v2；其他值 `manifest_schema_unsupported`。"""
    (tmp_path / "web").mkdir()
    for version in (1, 2):
        (tmp_path / core.MANIFEST_NAME).write_text(
            f"version: {version}\nsolution: demo\nmode: federated\nmembers:\n"
            "  - name: web\n    path: web\n    assets: member\n",
            encoding="utf-8")
        assert core.load_manifest(tmp_path)["version"] == version
    (tmp_path / core.MANIFEST_NAME).write_text(
        "version: 3\nsolution: demo\nmode: federated\nmembers: []\n", encoding="utf-8")
    with pytest.raises(core.SolutionError, match="manifest_schema_unsupported"):
        core.load_manifest(tmp_path)
    # 0 与缺失同样不在 {1,2} 内：缺失 ⇒ 空值 ⇒ 报错，不算合法清单
    (tmp_path / core.MANIFEST_NAME).write_text(
        "version: 0\nsolution: demo\nmode: federated\nmembers: []\n", encoding="utf-8")
    with pytest.raises(core.SolutionError, match="manifest_schema_unsupported"):
        core.load_manifest(tmp_path)
    (tmp_path / core.MANIFEST_NAME).write_text(
        "solution: demo\nmode: federated\nmembers: []\n", encoding="utf-8")
    with pytest.raises(core.SolutionError, match="manifest_schema_unsupported"):
        core.load_manifest(tmp_path)


def test_b0_migrate_fills_missing_only_and_is_idempotent(tmp_path: Path) -> None:
    """V-15 / B-0 migrate：只补缺；二次执行零 diff。"""
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")], install=False)
    path = tmp_path / core.MANIFEST_NAME
    before = path.read_text(encoding="utf-8")
    assert "version: 1" in before
    assert "definition:" not in before

    result = core.migrate_manifest(tmp_path)
    assert result["from"] == 1 and result["to"] == 2
    assert result["added"] == ["definition", "acceptance_cutover", "min_atlas"]
    after = path.read_text(encoding="utf-8")
    assert re.search(r"^version: 2$", after, re.M)
    assert "domain: solution" in after
    assert "path: product/prd/solution-prd.md" in after
    assert "acceptance_cutover: 2027-03-31" in after
    assert "min_atlas: 0.4.0" in after
    # 已有行逐行保留：members 段与注释都不动
    assert "  - name: web" in after and "    kind: frontend" in after

    again = core.migrate_manifest(tmp_path)
    assert again["changed"] is False and again["added"] == []
    assert path.read_text(encoding="utf-8") == after


def test_b0_migrate_never_overwrites_existing_values(tmp_path: Path) -> None:
    """§5.2.7：只补缺，不改已有（含已填的 acceptance_cutover / definition）。"""
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")], install=False)
    path = tmp_path / core.MANIFEST_NAME
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "mode: federated\n",
            "mode: federated\nacceptance_cutover: 2099-01-01\n"
            "definition:\n  domain: custom\n  path: product/prd/solution-prd.md\n"),
        encoding="utf-8")
    result = core.migrate_manifest(tmp_path)
    assert result["added"] == ["min_atlas"]
    text = path.read_text(encoding="utf-8")
    assert "acceptance_cutover: 2099-01-01" in text
    assert "domain: custom" in text
    assert "min_atlas: 0.4.0" in text


def test_b0_migrate_heals_v2_without_definition(tmp_path: Path) -> None:
    """V-15：v2 清单缺 definition 时 migrate 自愈，且不动已有标量。"""
    (tmp_path / "web").mkdir()
    (tmp_path / core.MANIFEST_NAME).write_text(
        "version: 2\nsolution: demo\nmode: federated\n"
        "acceptance_cutover: 2027-03-31\nmin_atlas: 0.4.0\n"
        "members:\n  - name: web\n    path: web\n    assets: member\n",
        encoding="utf-8")
    (tmp_path / "product" / "prd").mkdir(parents=True)
    (tmp_path / "product" / "prd" / "solution-prd.md").write_text(
        "---\ndomain: solution\n---\n\n# solution\n", encoding="utf-8")
    result = core.migrate_manifest(tmp_path)
    assert result["added"] == ["definition", "prd_version", "prd_schema"]
    assert result["changed"] is True
    loaded = core.load_manifest(tmp_path)
    assert loaded["version"] == 2 and loaded["definition"]["domain"] == "solution"


def test_b0_migrate_rejects_non_default_prd_without_writing(tmp_path: Path) -> None:
    """V-12：非默认 `-prd.md` ⇒ 拒绝、提示 B 批，且不写任何文件。"""
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")], install=False)
    prd_dir = tmp_path / "product" / "prd"
    (prd_dir / "solution-prd.md").rename(prd_dir / "demo-prd.md")
    path = tmp_path / core.MANIFEST_NAME
    before = path.read_bytes()
    with pytest.raises(core.SolutionError, match="B 批后支持任意"):
        core.migrate_manifest(tmp_path)
    assert path.read_bytes() == before


def test_b0_migrate_rejects_missing_definition_path(tmp_path: Path) -> None:
    """评审重要 6：`--definition-path` 指向不存在的文件 ⇒ 拒绝，不写悬空 `definition`。"""
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")], install=False)
    (tmp_path / "product" / "prd" / "solution-prd.md").unlink()
    path = tmp_path / core.MANIFEST_NAME
    before = path.read_bytes()
    with pytest.raises(core.SolutionError, match="不存在"):
        core.migrate_manifest(tmp_path, definition_path="product/prd/solution-prd.md")
    assert path.read_bytes() == before
    assert "definition:" not in path.read_text(encoding="utf-8")


def test_b0_migrate_replaces_definition_null_in_place(tmp_path: Path) -> None:
    """评审重要 7：`definition: null` 被 `migrate --to 2` 原地替换，不追加第二块。"""
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")], install=False)
    path = tmp_path / core.MANIFEST_NAME
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "mode: federated\n", "mode: federated\ndefinition: null\n", 1),
        encoding="utf-8")
    result = core.migrate_manifest(tmp_path)
    assert result["added"][0] == "definition"
    text = path.read_text(encoding="utf-8")
    assert "definition: null" not in text
    assert text.count("definition:") == 1
    loaded = core.load_manifest(tmp_path)
    assert loaded["version"] == 2
    assert loaded["definition"] == {"domain": "solution",
                                    "path": "product/prd/solution-prd.md"}


def test_b0_migrate_keeps_version_inline_comment(tmp_path: Path) -> None:
    """评审次要 9：`version:` 的行尾注释在迁移时保留。"""
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")], install=False)
    path = tmp_path / core.MANIFEST_NAME
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "version: 1\n", "version: 1  # B-0 迁移前\n", 1),
        encoding="utf-8")
    core.migrate_manifest(tmp_path)
    assert re.search(r"^version: 2  # B-0 迁移前$",
                     path.read_text(encoding="utf-8"), re.M)


def test_b0_migrate_lists_candidates_when_multiple_prd(tmp_path: Path) -> None:
    """§5.2.7：多份 `*-prd.md` 且无 `--definition-path` ⇒ 拒绝并列出候选。"""
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")], install=False)
    prd_dir = tmp_path / "product" / "prd"
    (prd_dir / "other-prd.md").write_text("---\ndomain: other\n---\n", encoding="utf-8")
    path = tmp_path / core.MANIFEST_NAME
    before = path.read_bytes()
    with pytest.raises(core.SolutionError, match="多个域级 PRD") as exc:
        core.migrate_manifest(tmp_path)
    assert "other-prd.md" in str(exc.value) and "solution-prd.md" in str(exc.value)
    assert path.read_bytes() == before


def test_b0_v07_migrate_keeps_lock_bytes_and_dirty_prd_blocks_lock(tmp_path: Path) -> None:
    """V-07 加强：migrate 不碰锁字节；PRD 工作树脏时 `lock --update` 非零退出。

    本夹具自 B 批起证明的是「清单 v2 ⇒ 锁 schema 2」；V-10 的「0.3.x 仍写 1」
    已由 B 的首锁语义（v1 清单 ⇒ 锁 1）取代。
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")], install=False)
    lock = tmp_path / core.LOCK_NAME
    assert lock.is_file()
    before = lock.read_bytes()
    core.migrate_manifest(tmp_path)
    assert lock.read_bytes() == before

    res = run_cli(tmp_path, "--root", str(tmp_path), "lock", "--update")
    assert res.returncode == 2, res.stdout + res.stderr
    assert "定义源工作树不干净" in (res.stdout + res.stderr)

    # 只提交清单与 PRD 后再 lock：不抛 SolutionError；v2 清单的首锁升到 schema_version 2
    # 并写入 definition（B 批起；B-0 期锁仍是 1）。
    commit_root(tmp_path, core.MANIFEST_NAME, "product/prd/solution-prd.md")
    res = run_cli(tmp_path, "--root", str(tmp_path), "lock", "--update")
    assert res.returncode == 0, res.stdout + res.stderr
    written = json.loads(lock.read_text(encoding="utf-8"))
    assert written["schema_version"] == 2
    assert written["definition"]["commit"]


def test_b0_v14_init_writes_v1_then_migrate_reaches_v2(tmp_path: Path) -> None:
    """V-14：0.3.x reader（<0.4.0）的 init 写 v1，migrate 后才出现 v2。

    0.4.0 reader 的 init 写 v2 由 V-13 夹具钉（`test_b_v13_v16_...`）；本夹具只证
    0.3.x 侧的迁移前形态，不再声称「init 一律写 v1」。
    """
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")], install=False)
    text = (tmp_path / core.MANIFEST_NAME).read_text(encoding="utf-8")
    assert re.search(r"^version: 1$", text, re.M)
    assert "definition:" not in text
    lock = json.loads((tmp_path / core.LOCK_NAME).read_text(encoding="utf-8"))
    assert lock["schema_version"] == 1

    core.migrate_manifest(tmp_path)
    assert core.load_manifest(tmp_path)["version"] == 2


def test_b0_check_members_prints_active_and_archive_paths(tmp_path: Path) -> None:
    """I3：`migrate --check-members` 打印解析后的实际路径，active 与 archive 各一条。"""
    member = make_repo(tmp_path / "web")
    for rel in (".trellis/tasks/T-001/prd.md", ".trellis/tasks/T-001/solution.md",
                ".trellis/tasks/archive/2026-10/T-000/prd.md"):
        target = member / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# card\n", encoding="utf-8")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")], install=False)

    res = run_cli(tmp_path, "--root", str(tmp_path), "migrate", "--check-members")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "git -C web add -f .trellis/tasks/T-001/prd.md .trellis/tasks/T-001/solution.md" \
        in res.stdout
    assert ".trellis/tasks/archive/2026-10/T-000/prd.md" in res.stdout
    assert "git -C web add -f .trellis/tasks/archive/2026-10/T-000/prd.md" in res.stdout
    # 只读：不写清单
    manifest = (tmp_path / core.MANIFEST_NAME).read_text(encoding="utf-8")
    assert re.search(r"^version: 1$", manifest, re.M)


def test_b0_check_members_quotes_paths_with_spaces(tmp_path: Path) -> None:
    """评审次要 10：成员路径含空格时 `git add -f` 命令必须加引号（可复制即跑）。"""
    member = make_repo(tmp_path / "web app")
    card = member / ".trellis" / "tasks" / "T-001"
    card.mkdir(parents=True)
    (card / "prd.md").write_text("# card\n", encoding="utf-8")
    core.init_solution(tmp_path, "demo", [("web", "web app", "frontend")], install=False)

    cmds = core.card_tracking_commands(tmp_path, core.load_manifest(tmp_path))
    assert cmds == ["git -C 'web app' add -f .trellis/tasks/T-001/prd.md"], cmds


def test_b0_u09_lenient_allows_lock_only_clone_and_rejects_seal(tmp_path: Path) -> None:
    """U-09：只有锁、无成员工作区时 `--lenient` 可用；有封条 ⇒ exit 2。"""
    import shutil

    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")], install=False)
    shutil.rmtree(tmp_path / "web")

    res = run_cli(tmp_path, "--root", str(tmp_path), "check", "--lenient", "--json")
    assert res.returncode == 0, res.stdout + res.stderr
    rows = [c for c in json.loads(res.stdout)["checks"]
            if "member_workspace_absent" in c["detail"]]
    assert rows and rows[0]["status"] == "SKIP"

    default_run = run_cli(tmp_path, "--root", str(tmp_path), "check", "--json")
    rows = [c for c in json.loads(default_run.stdout)["checks"]
            if "member_workspace_absent" in c["detail"]]
    assert rows and rows[0]["status"] == "WARN"

    seal_dir = tmp_path / "product" / "reviews" / "apply" / "2026-11"
    seal_dir.mkdir(parents=True)
    (seal_dir / "K-001.seal.json").write_text("{}\n", encoding="utf-8")
    res = run_cli(tmp_path, "--root", str(tmp_path), "check", "--lenient")
    assert res.returncode == 2
    assert res.stderr.splitlines()[0] == "[FAIL] --lenient 仅限无封条"


def test_b0_v06_install_update_refuses_v1_with_040_package(tmp_path: Path) -> None:
    """V-06：仓内 v1 + 来包 ≥0.4.0 ⇒ `install --update` 拒绝刷新并打印迁移命令。"""
    import shutil

    from importlib.util import module_from_spec, spec_from_file_location

    def load_install(version: str):
        pkg = tmp_path / f"pkg-{version}"
        pkg.mkdir(exist_ok=True)
        shutil.copy(PKG_ROOT / "install.py", pkg / "install.py")
        # `_manifest_schema_version` 统一到 `_support/solution.py::parse_manifest_text`
        # （评审次要 8）：装配树里 `_support/` 必须就位，否则解析器加载失败。
        if not (pkg / "_support").is_dir():
            shutil.copytree(PKG_ROOT / "_support", pkg / "_support")
        (pkg / "package.json").write_text(json.dumps({"version": version}),
                                          encoding="utf-8")
        spec = spec_from_file_location(f"install_guard_{version.replace('.', '_')}",
                                       pkg / "install.py")
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    target = tmp_path / "target"
    (target / "product").mkdir(parents=True)
    (target / core.MANIFEST_NAME).write_text(
        "version: 1\nsolution: demo\nmode: federated\nmembers: []\n", encoding="utf-8")

    refuse, reason = load_install("0.4.0").solution_update_guard(str(target))
    assert refuse is True
    assert "atlas solution migrate --to 2" in reason

    refuse, _ = load_install("0.4.0-beta.1").solution_update_guard(str(target))
    assert refuse is False, "预发布 0.4.0-beta.1 在 semver 下 < 0.4.0，不拦"

    refuse, _ = load_install("0.3.0").solution_update_guard(str(target))
    assert refuse is False

    # 次要 8：引号 + 行尾注释与解析器同口径（旧正则 `^version:\s*(\S+)\s*$` 会误判）
    (target / core.MANIFEST_NAME).write_text(
        'version: "1"  # 迁移前\nsolution: demo\nmode: federated\nmembers: []\n',
        encoding="utf-8")
    refuse, _ = load_install("0.4.0").solution_update_guard(str(target))
    assert refuse is True

    (target / core.MANIFEST_NAME).write_text(
        "version: 2\nsolution: demo\nmode: federated\nmembers: []\n", encoding="utf-8")
    refuse, _ = load_install("0.4.0").solution_update_guard(str(target))
    assert refuse is False

    (target / core.MANIFEST_NAME).write_text(
        "version: 9\nsolution: demo\nmode: federated\nmembers: []\n", encoding="utf-8")
    refuse, reason = load_install("0.4.0").solution_update_guard(str(target))
    assert refuse is True and "无法识别" in reason

    (target / core.MANIFEST_NAME).unlink()
    refuse, _ = load_install("0.4.0").solution_update_guard(str(target))
    assert refuse is False


def test_b0_install_update_main_refuses_before_overwriting(tmp_path: Path,
                                                           monkeypatch, capsys) -> None:
    """评审重要 5：`main()` 的接线——`--update` 在覆盖 `.atlas` **之前**就拒绝。

    真跑一次 `install.py --update`（模块级 `main()`），断言 exit 1、迁移口令可见，
    且 `.atlas` 未被覆写（旧版本戳原样、新落点 `.atlas/package.json` 未产生）。
    """
    import shutil

    from importlib.util import module_from_spec, spec_from_file_location

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    shutil.copy(PKG_ROOT / "install.py", pkg / "install.py")
    shutil.copytree(PKG_ROOT / "_support", pkg / "_support")
    (pkg / "package.json").write_text(json.dumps({"version": "0.4.0"}),
                                      encoding="utf-8")
    spec = spec_from_file_location("install_main_wiring", pkg / "install.py")
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)

    target = tmp_path / "target"
    (target / ".atlas").mkdir(parents=True)
    (target / ".atlas" / "VERSION").write_text(
        "stamped-by-0.3.x\n2026-11-10T00:00:00+08:00\nnowhere\n", encoding="utf-8")
    (target / core.MANIFEST_NAME).write_text(
        "version: 1\nsolution: demo\nmode: federated\nmembers:\n"
        "  - name: web\n    path: web\n    assets: member\n", encoding="utf-8")

    monkeypatch.setattr(sys, "argv",
                        ["install.py", "--update", "--target", str(target)])
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "atlas solution migrate --to 2" in out
    # 写前拒绝：整包拷贝与 `.atlas/package.json` 落点都没发生
    assert (target / ".atlas" / "VERSION").read_text(encoding="utf-8").startswith(
        "stamped-by-0.3.x\n")
    assert not (target / ".atlas" / "package.json").exists()


def test_b0_install_assembles_package_json_for_reader_version(
        tmp_path: Path, monkeypatch) -> None:
    """复核 3：成功装配必须真落下 `.atlas/package.json`（`reader_version` 第 2 级来源）。

    生产里 `.atlas/VERSION` 是纯 hex 摘要 ⇒ 第 1 级恒被跳过。为排除「候选 3（工具包根
    `package.json`）恰好同版本」造成的假绿，这里把候选 3 指向仓外 toolroot（9.9.9）：
    取到来包版本才证明走的是候选 2。
    """
    target = tmp_path / "proj"
    target.mkdir()
    res = subprocess.run(
        [sys.executable, str(PKG_ROOT / "install.py"), "--target", str(target),
         "--no-skill", "--no-patch", "--no-wiring", "--no-trellis"],
        capture_output=True, text=True, timeout=300)
    assert res.returncode == 0, (res.stdout[-800:], res.stderr[-400:])

    source = json.loads((PKG_ROOT / "package.json").read_text(encoding="utf-8"))
    copied = json.loads(
        (target / ".atlas" / "package.json").read_text(encoding="utf-8"))
    assert copied["version"] == source["version"]

    stamp = (target / ".atlas" / "VERSION").read_text(encoding="utf-8")
    assert not re.match(r"^v?\d+\.\d+\.\d+", stamp.strip())

    toolroot = tmp_path / "toolroot"
    (toolroot / "validators").mkdir(parents=True)
    (toolroot / "package.json").write_text(json.dumps({"version": "9.9.9"}),
                                           encoding="utf-8")
    v_index = load_module_path(PKG_ROOT / "validators" / "validate_e2e_index.py",
                               "_atlas_validate_reader_version_probe")
    monkeypatch.setattr(v_index, "__file__",
                        str(toolroot / "validators" / "validate_e2e_index.py"))
    assert v_index._reader_version(target) == source["version"]


def load_module_path(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------- B 批：definition

def stub_reader_version(monkeypatch, tmp_path: Path, version: str = "0.4.0") -> Path:
    """把**工具包根** `package.json` 指向仓外目录，模拟 0.4.0 读者（不读被检查仓）。"""
    toolroot = tmp_path / "toolroot-reader"
    toolroot.mkdir(exist_ok=True)
    (toolroot / "package.json").write_text(json.dumps({"version": version}),
                                           encoding="utf-8")
    monkeypatch.setattr(core, "_TOOL_PACKAGE_ROOT", toolroot)
    return toolroot


def _lock_bytes(root: Path) -> dict:
    return json.loads((root / core.LOCK_NAME).read_text(encoding="utf-8"))


def _write_lock_json(root: Path, payload: dict) -> None:
    (root / core.LOCK_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _lock_commits_with_definition_commit(root: Path, *flags: str) -> list[str]:
    """列出锁历史里 `definition.commit` 非 null 的提交（供 full-history 对照）。"""
    out = subprocess.run(
        ["git", "-C", str(root), "log", *flags, "--format=%H", "HEAD",
         "--", core.LOCK_NAME], check=True, capture_output=True, text=True).stdout
    hits: list[str] = []
    for sha in out.split():
        shown = subprocess.run(
            ["git", "-C", str(root), "show", f"{sha}:{core.LOCK_NAME}"],
            capture_output=True, text=True)
        if shown.returncode != 0:
            continue
        definition = json.loads(shown.stdout).get("definition") or {}
        if definition.get("commit"):
            hits.append(sha)
    return hits


def _definition_rows(report: dict) -> list[dict]:
    return [c for c in report["checks"] if c["check"] == "定义源 commit"]


def test_b_v13_v16_init_040_writes_v2_with_commit_null_then_pending_warn(
        tmp_path: Path, monkeypatch) -> None:
    """V-13 + V-16：0.4.0 `init` 写 v2 + definition；首锁 commit=null，check 只 WARN。

    另：模板 `prd_schema: 1` 且 Assumptions 表尚无证据列 ⇒ 按 §1.5 只报
    `evidence_deadline_approaching` WARN（不是 FAIL），与 V-16 的放行口径一致。
    """
    stub_reader_version(monkeypatch, tmp_path)
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")], install=False)

    text = (tmp_path / core.MANIFEST_NAME).read_text(encoding="utf-8")
    assert re.search(r"^version: 2$", text, re.M)
    assert "definition:" in text
    assert "path: product/prd/solution-prd.md" in text

    lock = _lock_bytes(tmp_path)
    assert lock["schema_version"] == 2
    assert lock["definition"]["path"] == "product/prd/solution-prd.md"
    assert lock["definition"]["domain"] == "solution"
    assert lock["definition"]["commit"] is None
    assert lock["definition"]["sha256"]
    assert lock["acceptance_cutover"] is None

    report = core.check_solution(tmp_path)
    rows = _definition_rows(report)
    assert len(rows) == 1
    assert rows[0]["status"] == "WARN"
    assert "definition_commit_pending" in rows[0]["detail"]
    assert not any(c["status"] == "FAIL" for c in report["checks"])


def test_b_first_lock_update_fills_definition_commit_and_cutover(
        tmp_path: Path, monkeypatch) -> None:
    """首次 `lock --update`（PRD 已入库）补齐真实 commit，并开始写 acceptance_cutover。"""
    stub_reader_version(monkeypatch, tmp_path)
    root = make_repo(tmp_path / "root")
    make_repo(root / "web")
    core.init_solution(root, "demo", [("web", "web", "frontend")], install=False)
    commit_root(root, core.MANIFEST_NAME, core.CONFIG_NAME, "product")

    core.write_lock(root, core.load_manifest(root), require_clean=True)
    lock = _lock_bytes(root)
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()
    assert lock["definition"]["commit"] == head
    assert lock["definition"]["blob"]
    assert lock["acceptance_cutover"] == "2027-03-31"

    report = core.check_solution(root)
    rows = _definition_rows(report)
    assert len(rows) == 1 and rows[0]["status"] == "PASS", rows


def test_b_definition_commit_reverted_after_first_refresh_fails(
        tmp_path: Path, monkeypatch) -> None:
    """已首次刷新后把 commit 改回 null（且 cutover 也清空）⇒ FAIL，不得落 WARN。"""
    stub_reader_version(monkeypatch, tmp_path)
    root = make_repo(tmp_path / "root")
    make_repo(root / "web")
    core.init_solution(root, "demo", [("web", "web", "frontend")], install=False)
    commit_root(root, core.MANIFEST_NAME, core.CONFIG_NAME, "product")
    core.write_lock(root, core.load_manifest(root), require_clean=True)
    commit_root(root, core.LOCK_NAME)

    lock = _lock_bytes(root)
    lock["definition"]["commit"] = None
    lock["acceptance_cutover"] = None
    _write_lock_json(root, lock)
    commit_root(root, core.LOCK_NAME)

    rows = _definition_rows(core.check_solution(root))
    assert len(rows) == 1
    assert rows[0]["status"] == "FAIL"
    assert "definition_commit_unverifiable" in rows[0]["detail"]


def test_b_merge_keeps_null_lock_but_branch_wrote_nonnull_fails(
        tmp_path: Path, monkeypatch) -> None:
    """B-2 夹具：merge 保留 null 锁、被合并分支写过非 null ⇒ FAIL。

    回归点：主判据若用 `git log`（不带 `--full-history`），历史简化会看不见分支
    提交，从而误落 `definition_commit_pending` WARN。测试同时钉住两种命令的差异。
    """
    stub_reader_version(monkeypatch, tmp_path)
    root = make_repo(tmp_path / "root")
    make_repo(root / "web")
    core.init_solution(root, "demo", [("web", "web", "frontend")], install=False)
    commit_root(root, core.MANIFEST_NAME, core.CONFIG_NAME, "product", core.LOCK_NAME)
    base = subprocess.run(["git", "-C", str(root), "rev-parse", "--abbrev-ref",
                           "HEAD"], check=True, capture_output=True,
                          text=True).stdout.strip()

    git(root, "checkout", "-b", "feat")
    core.write_lock(root, core.load_manifest(root), require_clean=True)
    branch_commit = _lock_bytes(root)["definition"]["commit"]
    assert branch_commit
    commit_root(root, core.LOCK_NAME)
    branch_lock_commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
        capture_output=True, text=True).stdout.strip()

    git(root, "checkout", base)
    null_lock = _lock_bytes(root)
    null_lock["definition"]["commit"] = None
    null_lock["acceptance_cutover"] = None
    # 让 main 侧对锁产生一次真实改动（否则 merge 直接取分支侧）；仍是 init 形态的 null。
    null_lock["locked_at"] = "2026-11-11T00:00:00+00:00"
    _write_lock_json(root, null_lock)
    commit_root(root, core.LOCK_NAME)
    git(root, "merge", "-s", "ours", "--no-ff", "feat", "-m", "merge")
    assert _lock_bytes(root)["definition"]["commit"] is None

    # 差异钉：默认历史简化看不见分支的非 null 提交，完整历史扫描能看见。
    assert _lock_commits_with_definition_commit(root) == []
    assert _lock_commits_with_definition_commit(
        root, "-m", "--full-history") == [branch_lock_commit]

    rows = _definition_rows(core.check_solution(root))
    assert len(rows) == 1
    assert rows[0]["status"] == "FAIL", rows[0]
    assert "definition_commit_unverifiable" in rows[0]["detail"]
    assert "definition_commit_pending" not in rows[0]["detail"]


def _strip_definition(text: str) -> str:
    return re.sub(r"^definition:\n(?:  .*\n)+", "", text, flags=re.M)


def _definition_findings(report: dict) -> list[dict]:
    return [c for c in report["checks"] if c["check"] == "定义源"]


def test_b_definition_missing_with_lock2_fails(tmp_path: Path, monkeypatch) -> None:
    """RFC §5.2 第 5 条：v2 清单 + 锁 schema 2，definition 缺失 / null ⇒ FAIL。"""
    stub_reader_version(monkeypatch, tmp_path)
    root = make_repo(tmp_path / "root")
    make_repo(root / "web")
    core.init_solution(root, "demo", [("web", "web", "frontend")], install=False)

    manifest = root / core.MANIFEST_NAME
    stripped = _strip_definition(manifest.read_text(encoding="utf-8"))
    assert "definition:" not in stripped
    manifest.write_text(stripped, encoding="utf-8")
    nulled = stripped.replace("min_atlas: 0.4.0",
                              "definition: null\nmin_atlas: 0.4.0")
    lock = _lock_bytes(root)
    assert lock["schema_version"] == 2

    for text in (stripped, nulled):
        manifest.write_text(text, encoding="utf-8")
        rows = _definition_findings(core.check_solution(root))
        assert len(rows) == 1, rows
        assert rows[0]["status"] == "FAIL"
        assert "definition_unbound" in rows[0]["detail"]


def test_b_definition_missing_with_lock1_is_not_judged(
        tmp_path: Path, monkeypatch) -> None:
    """B-0 兼容：v2 清单 + 锁 schema 1 是合法中间态，不判 `definition_unbound`。"""
    stub_reader_version(monkeypatch, tmp_path)
    root = make_repo(tmp_path / "root")
    make_repo(root / "web")
    core.init_solution(root, "demo", [("web", "web", "frontend")], install=False)

    manifest = root / core.MANIFEST_NAME
    manifest.write_text(_strip_definition(manifest.read_text(encoding="utf-8")),
                        encoding="utf-8")
    lock = _lock_bytes(root)
    lock["schema_version"] = 1
    lock["definition"] = None
    _write_lock_json(root, lock)

    report = core.check_solution(root)
    assert not any("definition_unbound" in c["detail"] for c in report["checks"])


def _refreshed_root(tmp_path: Path, monkeypatch) -> Path:
    stub_reader_version(monkeypatch, tmp_path)
    root = make_repo(tmp_path / "root")
    make_repo(root / "web")
    core.init_solution(root, "demo", [("web", "web", "frontend")], install=False)
    commit_root(root, core.MANIFEST_NAME, core.CONFIG_NAME, "product")
    core.write_lock(root, core.load_manifest(root), require_clean=True)
    commit_root(root, core.LOCK_NAME)
    assert _lock_bytes(root)["acceptance_cutover"] == "2027-03-31"
    return root


def _cutover_rows(report: dict) -> list[dict]:
    return [c for c in report["checks"] if c["check"] == "验收切点"]


def test_b_acceptance_cutover_manifest_pushed_fails(
        tmp_path: Path, monkeypatch) -> None:
    """刷新后手改清单把 cutover 往后推、锁没跟上 ⇒ FAIL。"""
    root = _refreshed_root(tmp_path, monkeypatch)
    manifest = root / core.MANIFEST_NAME
    text = manifest.read_text(encoding="utf-8")
    manifest.write_text(text.replace("acceptance_cutover: 2027-03-31",
                                     "acceptance_cutover: 2027-12-31"),
                        encoding="utf-8")

    rows = _cutover_rows(core.check_solution(root))
    assert len(rows) == 1, rows
    assert rows[0]["status"] == "FAIL"
    assert "acceptance_cutover_mismatch" in rows[0]["detail"]
    assert "2027-12-31" in rows[0]["detail"]


def test_b_acceptance_cutover_lock_only_changed_fails(
        tmp_path: Path, monkeypatch) -> None:
    """只改锁、不勾清单 ⇒ 同样 FAIL（反向也判）。"""
    root = _refreshed_root(tmp_path, monkeypatch)
    lock = _lock_bytes(root)
    lock["acceptance_cutover"] = "2027-01-01"
    _write_lock_json(root, lock)

    rows = _cutover_rows(core.check_solution(root))
    assert len(rows) == 1, rows
    assert rows[0]["status"] == "FAIL"
    assert "acceptance_cutover_mismatch" in rows[0]["detail"]
