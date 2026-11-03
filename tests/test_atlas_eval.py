#!/usr/bin/env python3
"""`scripts/atlas_eval.py` 跑分器回归（RFC-20261103-06）。

夹具 = 临时 git 仓：base（flag.txt 存在 / gate.py 打 3 行 ok）/ candidate（flag.txt 删除 /
gate.py 打 2 行 ok）；case 注册表指针化（pytest 节点 / 文件片段锚）。

覆盖：run 分类（pass2pass / pass2fail / fail2fail）/ 锚缺失抓取 / gate_green 计数与下降 /
gate 三类失败与 f2f 只 WARN / 同 sha 拒绝 / 注册表形状拒（kind 闭集、重复 id）/
worktree 默认清理与 `--keep-worktrees` / gate --out 判定 JSON。

变异证明（编号属本文件）：M171 摘 pass→fail 检测 ⇒ gate 用例红；
M172 摘锚缺失 FAIL ⇒ 锚用例红。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "atlas_eval.py"


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, text=True)


def make_repo(tmp: Path) -> tuple[Path, str, str]:
    root = tmp / "proj"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    (root / "README.md").write_text("marker\n", encoding="utf-8")
    (root / "flag.txt").write_text("exists\n", encoding="utf-8")
    (root / "gate.py").write_text(
        "#!/usr/bin/env python3\nfor _ in range(3):\n    print(\"ok\")\n", encoding="utf-8")
    (root / "test_sample.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    base = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    (root / "flag.txt").unlink()
    (root / "gate.py").write_text(
        "#!/usr/bin/env python3\nfor _ in range(2):\n    print(\"ok\")\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "cand")
    cand = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    return root, base, cand


CASES = {
    "schema_version": 1,
    "gate_command": "python3 gate.py",
    "cases": [
        {"id": "C1-p2p", "kind": "mutation", "anchor": "test_sample.py::test_ok",
         "command": "python3 -m pytest test_sample.py -q"},
        {"id": "C2-p2f", "kind": "bug", "anchor": "README.md#marker",
         "command": "python3 -c \"import sys,pathlib; sys.exit(0 if pathlib.Path('flag.txt').exists() else 1)\""},
        {"id": "C3-f2f", "kind": "mutation", "anchor": "test_sample.py::test_ok",
         "command": "python3 -c \"raise SystemExit(1)\""},
        {"id": "C4-missing", "kind": "bug", "anchor": "docs/nope.md#X",
         "command": "python3 -c \"print('ok')\""},
    ],
}


def write_cases(root: Path, cases: dict, name: str = "cases.json") -> Path:
    p = root / name
    p.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    return p


def run_eval(root: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), *args],
                          capture_output=True, text=True, timeout=300, env=e)


@pytest.fixture()
def repo(tmp_path: Path):
    root, base, cand = make_repo(tmp_path)
    return root, base, cand


def test_run_classifies_and_cleans_worktrees(repo) -> None:
    root, base, cand = repo
    cases = write_cases(root, CASES)
    out = root / "ledger-out"
    p = run_eval(root, "run", "--cases", str(cases), "--base", base,
                 "--candidate", cand, "--out", str(out), "--timeout", "120")
    assert p.returncode == 0, p.stdout + p.stderr
    ledger = json.loads((out / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["summary"] == {"pass2pass": 1, "pass2fail": 1,
                                 "fail2pass": 0, "fail2fail": 1, "anchor_missing": 1}
    by_id = {c["id"]: c for c in ledger["cases"]}
    assert by_id["C1-p2p"]["base_status"] == "pass"
    assert by_id["C2-p2f"]["base_status"] == "pass" and by_id["C2-p2f"]["candidate_status"] == "fail"
    assert by_id["C3-f2f"]["base_status"] == "fail" and by_id["C3-f2f"]["candidate_status"] == "fail"
    assert by_id["C4-missing"]["anchor_ok"] is False
    assert ledger["gate_green"]["base"] == 3 and ledger["gate_green"]["candidate"] == 2
    assert LEG_NOTE in ledger["note"]
    # worktree 默认清理：只剩主工作树
    wt = subprocess.run(["git", "-C", str(root), "worktree", "list"],
                        capture_output=True, text=True).stdout
    assert wt.count("\n") == 1, wt


def test_gate_fails_on_regression_missing_green(repo) -> None:
    root, base, cand = repo
    cases = write_cases(root, CASES)
    out = root / "ledger-out"
    run_eval(root, "run", "--cases", str(cases), "--base", base,
             "--candidate", cand, "--out", str(out), "--timeout", "120")
    gate_out = root / "gate.json"
    p = run_eval(root, "gate", "--ledger", str(out / "ledger.json"), "--out", str(gate_out))
    assert p.returncode == 1
    assert "pass→fail：C2-p2f" in p.stdout
    assert "锚缺失：C4-missing" in p.stdout
    assert "gate_green 下降：3 → 2" in p.stdout
    result = json.loads(gate_out.read_text(encoding="utf-8"))
    assert result["status"] == "FAIL"
    assert result["regressions"] == ["C2-p2f"] and result["anchor_missing"] == ["C4-missing"]


def test_gate_passes_clean_ledger(tmp_path: Path) -> None:
    ledger = {"schema_version": 1, "cases": [
        {"id": "A", "anchor_ok": True, "base_status": "pass", "candidate_status": "pass"}],
        "gate_green": {"base": 3, "candidate": 3}}
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(ledger), encoding="utf-8")
    r = run_eval(tmp_path, "gate", "--ledger", str(p))
    assert r.returncode == 0 and "PASS" in r.stdout


def test_gate_fail2fail_warns_not_fails(tmp_path: Path) -> None:
    ledger = {"schema_version": 1, "cases": [
        {"id": "A", "anchor_ok": True, "base_status": "fail", "candidate_status": "fail"}],
        "gate_green": {"base": 1, "candidate": 1}}
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(ledger), encoding="utf-8")
    r = run_eval(tmp_path, "gate", "--ledger", str(p))
    assert r.returncode == 0 and "fail2fail" in r.stdout


def test_gate_green_null_skips(tmp_path: Path) -> None:
    ledger = {"schema_version": 1, "cases": [
        {"id": "A", "anchor_ok": True, "base_status": "pass", "candidate_status": "pass"}],
        "gate_green": {"base": None, "candidate": None}}
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(ledger), encoding="utf-8")
    r = run_eval(tmp_path, "gate", "--ledger", str(p))
    assert r.returncode == 0 and "gate_green 不完整" in r.stdout


def test_same_sha_refused(repo) -> None:
    root, base, _cand = repo
    cases = write_cases(root, CASES)
    r = run_eval(root, "run", "--cases", str(cases), "--base", base,
                 "--candidate", base, "--out", str(root / "o"))
    assert r.returncode == 2 and "同一 commit" in r.stderr


def test_registry_bad_kind_and_duplicate_refused(repo) -> None:
    root, base, cand = repo
    bad_kind = write_cases(root, {**CASES, "cases": [
        {"id": "X", "kind": "foo", "anchor": "README.md#marker", "command": "true"}]}, "k.json")
    r = run_eval(root, "run", "--cases", str(bad_kind), "--base", base,
                 "--candidate", cand, "--out", str(root / "o"))
    assert r.returncode == 2 and "kind" in r.stderr
    dup = write_cases(root, {**CASES, "cases": [CASES["cases"][0], CASES["cases"][0]]}, "d.json")
    r2 = run_eval(root, "run", "--cases", str(dup), "--base", base,
                  "--candidate", cand, "--out", str(root / "o"))
    assert r2.returncode == 2 and "重复 case id" in r2.stderr


def test_keep_worktrees_flag(repo) -> None:
    root, base, cand = repo
    cases = write_cases(root, CASES)
    p = run_eval(root, "run", "--cases", str(cases), "--base", base,
                 "--candidate", cand, "--out", str(root / "o"), "--timeout", "120",
                 "--keep-worktrees")
    assert p.returncode == 0, p.stdout + p.stderr
    wt = subprocess.run(["git", "-C", str(root), "worktree", "list"],
                        capture_output=True, text=True).stdout
    assert wt.count("\n") == 3, wt
    # 清理现场：KEEP 的 worktree 在系统临时目录，测试尾部手动回收（防泄漏）
    import shutil
    extras = [ln.split()[0] for ln in wt.strip().splitlines()[1:] if ln.strip()]
    parents = set()
    for d in extras:
        subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", d],
                       capture_output=True)
        parents.add(Path(d).parent)
    for pd in parents:
        shutil.rmtree(pd, ignore_errors=True)


LEG_NOTE = ("单项目单环境有限 case 集；不宣称净收益 / 反事实；结果不可外推"
            "（口径承自 research/2026-10-25-net-contribution-ledger.md）。")


def test_gate_regression_alone_fails(tmp_path: Path) -> None:
    """M171：摘掉 pass→fail 检测 ⇒ 本用例红（无锚缺失/无 green 下降，唯一失败类）。"""
    ledger = {"schema_version": 1, "cases": [
        {"id": "A", "anchor_ok": True, "base_status": "pass", "candidate_status": "fail"}],
        "gate_green": {"base": 3, "candidate": 3}}
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(ledger), encoding="utf-8")
    r = run_eval(tmp_path, "gate", "--ledger", str(p))
    assert r.returncode == 1 and "pass→fail：A" in r.stdout


def test_gate_anchor_missing_alone_fails(tmp_path: Path) -> None:
    """M172：摘掉锚缺失 FAIL ⇒ 本用例红（不静默 SKIP）。"""
    ledger = {"schema_version": 1, "cases": [
        {"id": "A", "anchor_ok": False, "anchor_detail": "锚文件不存在：x.md",
         "base_status": "pass", "candidate_status": "pass"}],
        "gate_green": {"base": 3, "candidate": 3}}
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(ledger), encoding="utf-8")
    r = run_eval(tmp_path, "gate", "--ledger", str(p))
    assert r.returncode == 1 and "锚缺失：A" in r.stdout
