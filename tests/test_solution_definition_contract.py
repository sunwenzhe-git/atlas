#!/usr/bin/env python3
"""#59：定义源命令面输出契约 + 写侧拒绝 + 硬编码读者（RFC-20261111-03 §2.6 / §7 / §8）。

反面包逐条咬红：D-03 / D-04 / D-07 / D-08 / D-13 / D-15 / D-16 / D-20 / D-28 / D-30；
每条修复都配一个「该绿的还绿」正例（默认路径、无变更、带评审的合法升级）。
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PKG_ROOT / "scripts" / "atlas_solution.py"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = _load("_atlas_solution_definition_contract", "_support/solution.py")
task = _load("_atlas_solution_definition_task", "_support/solution_task.py")
e2e = _load("_atlas_solution_definition_e2e", "_support/solution_e2e.py")


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "app.txt").write_text("app\n", encoding="utf-8")
    git(path, "add", "-A")
    git(path, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "init")
    return path


def commit_all(root: Path, message: str) -> None:
    git(root, "add", "-A")
    git(root, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", message)


def stub_reader_version(monkeypatch, tmp_path: Path, version: str = "0.4.0") -> None:
    toolroot = tmp_path / "toolroot-reader"
    toolroot.mkdir(exist_ok=True)
    (toolroot / "package.json").write_text(json.dumps({"version": version}),
                                           encoding="utf-8")
    monkeypatch.setattr(core, "_TOOL_PACKAGE_ROOT", toolroot)


def init_v2(tmp_path: Path, monkeypatch) -> Path:
    """0.4.0 读者 `init` ⇒ v2 清单 + definition + 首锁；再提交成干净基线。"""
    stub_reader_version(monkeypatch, tmp_path)
    root = make_repo(tmp_path / "root")
    make_repo(root / "web")
    core.init_solution(root, "demo", [("web", "web", "frontend")], install=False)
    commit_all(root, "init")
    # 首锁的 definition.commit 是 null（PRD 未入库）；提交后刷新一次，拿到可复算的 commit。
    core.write_lock(root, core.load_manifest(root))
    commit_all(root, "lock")
    return root


def prd_path(root: Path) -> Path:
    return root / "product" / "prd" / "solution-prd.md"


def lock_json(root: Path) -> dict:
    return json.loads((root / core.LOCK_NAME).read_text(encoding="utf-8"))


def check_row(report: dict, name: str) -> dict:
    rows = [c for c in report["checks"] if c["check"] == name]
    assert len(rows) == 1, rows
    return rows[0]


def tool_copy(tmp_path: Path, version: str = "0.3.0") -> Path:
    """子进程无法 monkeypatch `_TOOL_PACKAGE_ROOT`；用 0.3.x 副本读 v2 清单。"""
    pkg = tmp_path / "toolpkg"
    shutil.copytree(PKG_ROOT / "_support", pkg / "_support")
    (pkg / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, pkg / "scripts" / "atlas_solution.py")
    (pkg / "package.json").write_text(json.dumps({"version": version}),
                                      encoding="utf-8")
    return pkg / "scripts" / "atlas_solution.py"


def run_cli(root: Path, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), "--root", str(root), *args],
        capture_output=True, text=True)


# ---------------------------------------------------------------- ① 输出契约

def test_command_contract_check_prints_definition_identity(
        tmp_path: Path, monkeypatch) -> None:
    """`check` 每次输出 `定义源: <path> @v<prd_version> <prd_date> <sha8>`。"""
    root = init_v2(tmp_path, monkeypatch)
    row = check_row(core.check_solution(root), "定义源")
    assert row["status"] == "PASS"
    assert re.fullmatch(
        r"product/prd/solution-prd\.md @v1 \d{4}-\d{2}-\d{2} [0-9a-f]{8}",
        row["detail"]), row["detail"]


def test_command_contract_lock_update_prints_old_to_new_and_review(
        tmp_path: Path, monkeypatch) -> None:
    """`lock --update` 打印 old→new；版本变化多打 `[REVIEW] <ID>`（RFC §2.6）。"""
    root = init_v2(tmp_path, monkeypatch)
    text = prd_path(root).read_text(encoding="utf-8")
    prd_path(root).write_text(text.replace("prd_version: 1", "prd_version: 2", 1),
                              encoding="utf-8")
    commit_all(root, "bump prd")

    cli = tool_copy(tmp_path)
    res = run_cli(root, cli, "lock", "--update",
                  "--anchor-review", "REVIEW-20260101-01")
    assert res.returncode == 0, res.stderr
    assert "definition.prd_version: 1 → 2" in res.stdout
    assert "definition.path: product/prd/solution-prd.md" in res.stdout
    assert re.search(r"definition\.sha256: [0-9a-f]{8} → [0-9a-f]{8}", res.stdout)
    assert "[REVIEW] REVIEW-20260101-01" in res.stdout


def test_command_contract_lock_update_without_definition_change_has_no_review(
        tmp_path: Path, monkeypatch) -> None:
    """正例：定义源没变时不打 `[REVIEW]`，old→new 四行原样输出。"""
    root = init_v2(tmp_path, monkeypatch)
    cli = tool_copy(tmp_path)
    res = run_cli(root, cli, "lock", "--update")
    assert res.returncode == 0, res.stderr
    assert "[REVIEW]" not in res.stdout
    assert "definition.path: product/prd/solution-prd.md → " \
           "product/prd/solution-prd.md" in res.stdout


# ---------------------------------------------------------------- ② 写侧拒绝

def test_write_side_d03_rejects_same_version_content_replacement(
        tmp_path: Path, monkeypatch) -> None:
    """D-03：同 domain/code/version 副本替换 ⇒ `lock --update` 拒绝（版本未升）。"""
    root = init_v2(tmp_path, monkeypatch)
    prd_path(root).write_text(
        prd_path(root).read_text(encoding="utf-8") + "\n副本替换\n", encoding="utf-8")
    commit_all(root, "same version content change")
    with pytest.raises(core.SolutionError, match="definition_source_replaced"):
        core.write_lock(root, core.load_manifest(root),
                        anchor_review="REVIEW-20260101-01")


def test_write_side_d04_rejects_path_change_without_review(
        tmp_path: Path, monkeypatch) -> None:
    """D-04：路径变更无评审 ⇒ 拒绝；带 `--anchor-review` 则放行（正例）。"""
    root = init_v2(tmp_path, monkeypatch)
    dst = root / "product" / "prd" / "demo-prd.md"
    git(root, "mv", "product/prd/solution-prd.md", "product/prd/demo-prd.md")
    data = core.load_manifest(root)
    data["definition"] = {"domain": "solution", "path": "product/prd/demo-prd.md"}
    with pytest.raises(core.SolutionError, match="必须带评审号"):
        core.write_lock(root, data)
    core.write_lock(root, data, anchor_review="REVIEW-20260101-02")
    assert lock_json(root)["definition"]["path"] == "product/prd/demo-prd.md"
    assert dst.is_file()


def test_write_side_d30_rejects_version_bump_without_review(
        tmp_path: Path, monkeypatch) -> None:
    """D-30：blob 变、版本升、无 REVIEW ⇒ 拒绝；同形态带评审即放行（正例）。"""
    root = init_v2(tmp_path, monkeypatch)
    text = prd_path(root).read_text(encoding="utf-8")
    prd_path(root).write_text(text.replace("prd_version: 1", "prd_version: 2", 1),
                              encoding="utf-8")
    commit_all(root, "blob changed, version raised")
    data = core.load_manifest(root)
    with pytest.raises(core.SolutionError, match="必须带评审号"):
        core.write_lock(root, data)
    core.write_lock(root, data, anchor_review="REVIEW-20260101-03")
    assert lock_json(root)["definition"]["prd_version"] == 2


def test_write_side_version_rollback_and_date_backward_rejected(
        tmp_path: Path, monkeypatch) -> None:
    """D-05：版本递减 / 日期倒退 ⇒ 拒绝，评审号也不能放行。"""
    root = init_v2(tmp_path, monkeypatch)
    base = prd_path(root).read_text(encoding="utf-8")
    prd_path(root).write_text(base.replace("prd_version: 1", "prd_version: 2", 1),
                              encoding="utf-8")
    commit_all(root, "prd v2")
    core.write_lock(root, core.load_manifest(root),
                    anchor_review="REVIEW-20260101-04")

    prd_path(root).write_text(base, encoding="utf-8")
    commit_all(root, "prd v1 rollback")
    with pytest.raises(core.SolutionError, match="manifest_rollback"):
        core.write_lock(root, core.load_manifest(root),
                        anchor_review="REVIEW-20260101-05")

    prd_path(root).write_text(
        re.sub(r"^date: .*$", 'date: "1999-01-01"',
               base.replace("prd_version: 1", "prd_version: 3", 1),
               count=1, flags=re.M), encoding="utf-8")
    with pytest.raises(core.SolutionError, match="prd_date_backward"):
        core.write_lock(root, core.load_manifest(root),
                        anchor_review="REVIEW-20260101-06")


def test_write_side_d28_prd_date_missing(tmp_path: Path, monkeypatch) -> None:
    """D-28：PRD 缺 `date` ⇒ `prd_date_missing`；补回后正常签发（正例）。"""
    root = init_v2(tmp_path, monkeypatch)
    original = prd_path(root).read_text(encoding="utf-8")
    prd_path(root).write_text(
        re.sub(r"^date: .*$", "", original, count=1, flags=re.M), encoding="utf-8")
    with pytest.raises(core.SolutionError, match="prd_date_missing"):
        core.write_lock(root, core.load_manifest(root))
    prd_path(root).write_text(original, encoding="utf-8")
    core.write_lock(root, core.load_manifest(root))
    assert lock_json(root)["definition"]["prd_date"]


# ---------------------------------------------------------------- 读侧 mismatch

def test_read_side_d07_blob_sha_mismatch(tmp_path: Path, monkeypatch) -> None:
    """D-07：blob sha 不符 ⇒ `definition_source_mismatch`；未篡改则 PASS（正例）。"""
    root = init_v2(tmp_path, monkeypatch)
    assert check_row(core.check_solution(root), "定义源 commit")["status"] == "PASS"

    lock = lock_json(root)
    lock["definition"]["sha256"] = "0" * 64
    (root / core.LOCK_NAME).write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    row = check_row(core.check_solution(root), "定义源 commit")
    assert row["status"] == "FAIL"
    assert "definition_source_mismatch" in row["detail"]


def test_read_side_d08_front_matter_version_mismatch(
        tmp_path: Path, monkeypatch) -> None:
    """D-08：front matter `prd_version` 与锁不符 ⇒ `definition_source_mismatch`。"""
    root = init_v2(tmp_path, monkeypatch)
    lock = lock_json(root)
    lock["definition"]["prd_version"] = 9
    (root / core.LOCK_NAME).write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    row = check_row(core.check_solution(root), "定义源 commit")
    assert row["status"] == "FAIL"
    assert "prd_version" in row["detail"] and "definition_source_mismatch" in row["detail"]


# ---------------------------------------------------------------- ③ 硬编码读者

def _custom_definition_root(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "root"
    root.mkdir()
    make_repo(root / "web")
    prd = root / "product" / "prd" / "demo-prd.md"
    prd.parent.mkdir(parents=True)
    prd.write_text(
        "---\n"
        "domain: demo\n"
        "domain_code: DEMO\n"
        "prd_version: 1\n"
        "prd_schema: 2\n"
        'date: "2026-11-12"\n'
        "---\n\n"
        "| AC | 场景 |\n"
        "|---|---|\n"
        "| AC-DEMO-001 | 自定义定义源 |\n",
        encoding="utf-8")
    (root / "product" / "e2e").mkdir(parents=True)
    (root / "product" / "e2e" / "e2e-index.md").write_text(
        "| 页面 | 路由 | 域 | 实现状态 |\n"
        "|---|---|---|---|\n"
        "| home | / | demo | 已实现 |\n",
        encoding="utf-8")
    data = {
        "solution": "demo",
        "mode": "federated",
        "members": [{"name": "web", "path": "web"}],
        "contracts": [],
        "definition": {"domain": "demo", "path": "product/prd/demo-prd.md"},
        "requirements": [{
            "id": "REQ-001", "member": "web", "acs": ["AC-DEMO-001"],
            "task_slug": "web-task", "scope": "演示",
        }],
    }
    return root, data


def test_readers_d20_ac_prd_uses_definition_path(tmp_path: Path) -> None:
    """D-20：`_ac_prd` / `_ac_defs` 读 `definition.path`；默认名回落仍绿（正例）。"""
    root, data = _custom_definition_root(tmp_path)
    assert task._ac_prd(root, data, "product") == root / "product/prd/demo-prd.md"
    assert task._ac_defs(root, data, "product") == {"AC-DEMO-001"}
    assert task.ac_source_status(root, data, "product")["state"] == "ok"

    fallback = dict(data)
    fallback["definition"] = None
    (root / "product" / "prd" / "solution-prd.md").write_text(
        "| AC-SOLUTION-001 | 默认定义源 |\n", encoding="utf-8")
    assert task._ac_defs(root, fallback, "product") == {"AC-SOLUTION-001"}


def test_readers_d15_pointer_uses_definition_path(tmp_path: Path) -> None:
    """D-15：自定义路径下 `_pointer` 不得仍写 `solution-prd.md`。"""
    root, data = _custom_definition_root(tmp_path)
    pointer = task._pointer(root, root / "web", data, data["requirements"][0],
                            "product")
    assert "parent_prd: ../product/prd/demo-prd.md" in pointer
    assert "solution-prd.md" not in pointer


def test_readers_d16_ac_coverage_uses_definition_path(tmp_path: Path) -> None:
    """D-16：自定义路径下 `_ac_coverage` 不得按默认名聚合出 0/N。"""
    root, data = _custom_definition_root(tmp_path)
    coverage = e2e._ac_coverage(
        root, {"present": True, "ok": True, "rows": [{"关联AC": "AC-DEMO-001"}]}, data)
    assert coverage["ac_total"] == 1
    assert coverage["attached"] == 1
    assert coverage["zero_attached"] == []
    assert coverage["state"] == "ready"
