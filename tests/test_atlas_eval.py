#!/usr/bin/env python3
"""`scripts/atlas_eval.py` 跑分器回归（RFC-20261103-06；评审修后批）。

夹具 = 临时 git 仓：base（flag.txt 存在 / gate.py 打 3 行 ok / test_probe.py）/
candidate（flag.txt 删除 / gate.py 打 2 行 ok / 新增 test_new.py(红) + test_new_ok.py(绿) +
newflag.txt）；case 注册表指针化（测试节点 / 文件片段锚）。

覆盖：run 分类（pass2pass / pass2fail / fail2fail / anchor_missing，锚缺失不参与分类）/
gate_green 计数与下降 / gate 四类失败（回归 / 锚缺失 / **新增即红** / green 下降）与
f2f 只 WARN / **error 命名锚不被子串误杀（B1 正反钉）** / **--retries 节拍类防抖** /
同 sha 拒绝 / 注册表形状拒（重复 id；kind 已降级为自由文本不校验）/
worktree 默认清理、`--keep-worktrees`、**--worktree-root**、**坏 candidate sha 零残留**。

变异证明（编号属本文件）：M171 摘 pass→fail 检测 ⇒ gate 用例红；M172 摘锚缺失 FAIL ⇒
锚用例红；M173 摘收集器 returncode 判据（退回子串判据）⇒ error 命名锚正钉红。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "atlas_eval.py"

FAKE_FILES = {
    "README.md": "marker\n",
    "flag.txt": "exists\n",
    "gate.py": "#!/usr/bin/env python3\nfor _ in range(3):\n    print(\"ok\")\n",
    "test_sample.py": "def test_ok():\n    assert True\n",
    "test_probe.py": "def test_error_probe():\n    assert True\n",
}

CAND_CHANGES = {
    "gate.py": "#!/usr/bin/env python3\nfor _ in range(2):\n    print(\"ok\")\n",
    "test_new.py": "def test_bad():\n    assert False\n",
    "test_new_ok.py": "def test_good():\n    assert True\n",
    "newflag.txt": "candidate-only\n",
}


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, text=True)


def make_repo(tmp: Path) -> tuple[Path, str, str]:
    root = tmp / "proj"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    for name, text in FAKE_FILES.items():
        (root / name).write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    base = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    (root / "flag.txt").unlink()
    for name, text in CAND_CHANGES.items():
        (root / name).write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "cand")
    cand = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    return root, base, cand


def registry(cases: list[dict], gate_command: str | None = "python3 gate.py") -> dict:
    return {"schema_version": 1, "gate_command": gate_command, "cases": cases}


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


CASES_MAIN = [
    {"id": "C1-p2p", "kind": "mutation", "anchor": "test_sample.py::test_ok",
     "command": "python3 -m pytest test_sample.py -q"},
    {"id": "C2-p2f", "kind": "bug", "anchor": "README.md#marker",
     "command": "python3 -c \"import sys,pathlib; sys.exit(0 if pathlib.Path('flag.txt').exists() else 1)\""},
    {"id": "C3-f2f", "kind": "mutation", "anchor": "test_sample.py::test_ok",
     "command": "python3 -c \"raise SystemExit(1)\""},
    {"id": "C4-missing", "kind": "bug", "anchor": "docs/nope.md#X",
     "command": "python3 -c \"print('ok')\""},
]


def ledger_dict(root: Path, base: str, cand: str, cases: list[dict],
                out: Path, extra: list[str] | None = None,
                gate_command: str | None = "python3 gate.py") -> dict:
    cp = write_cases(root, registry(cases, gate_command), "cases-run.json")
    p = run_eval(root, "run", "--cases", str(cp), "--base", base, "--candidate", cand,
                 "--out", str(out), "--timeout", "120", *(extra or []))
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads((out / "ledger.json").read_text(encoding="utf-8"))


def test_run_classifies_and_cleans_worktrees(repo) -> None:
    root, base, cand = repo
    out = root / "ledger-out"
    ledger = ledger_dict(root, base, cand, CASES_MAIN, out)
    assert ledger["summary"] == {"pass2pass": 1, "pass2fail": 1, "fail2pass": 0,
                                 "fail2fail": 1, "anchor_missing": 1,
                                 "new_red": 0, "new_ok": 0}
    by_id = {c["id"]: c for c in ledger["cases"]}
    assert by_id["C2-p2f"]["base_status"] == "pass"
    assert by_id["C2-p2f"]["candidate_status"] == "fail"
    assert by_id["C4-missing"]["anchor_ok"] is False
    assert ledger["gate_green"]["base"] == 3 and ledger["gate_green"]["candidate"] == 2
    assert ledger["registry_sha256"] and len(ledger["case_ids"]) == 4
    wt = subprocess.run(["git", "-C", str(root), "worktree", "list"],
                        capture_output=True, text=True).stdout
    assert wt.count("\n") == 1, wt


def test_gate_fails_on_regression_missing_green(repo) -> None:
    root, base, cand = repo
    out = root / "ledger-out"
    ledger_dict(root, base, cand, CASES_MAIN, out)
    gate_out = root / "gate.json"
    p = run_eval(root, "gate", "--ledger", str(out / "ledger.json"), "--out", str(gate_out))
    assert p.returncode == 1
    assert "pass→fail：C2-p2f" in p.stdout
    assert "锚缺失：C4-missing" in p.stdout
    assert "gate_green 下降：3 → 2" in p.stdout
    result = json.loads(gate_out.read_text(encoding="utf-8"))
    assert result["regressions"] == ["C2-p2f"] and result["anchor_missing"] == ["C4-missing"]


def test_error_named_anchor_not_killed(repo) -> None:
    """B1 正钉：节点名含 error 不得被子串判据误杀（收集器只按退出码判）。"""
    root, base, cand = repo
    cases = [{"id": "E1-err", "kind": "mutation",
              "anchor": "test_probe.py::test_error_probe",
              "command": "python3 -c \"print('ok')\""}]
    out = root / "o"
    ledger = ledger_dict(root, base, cand, cases, out)
    assert ledger["cases"][0]["anchor_ok"] is True
    assert ledger["cases"][0]["anchor_ok_base"] is True


def test_missing_node_anchor_detected(repo) -> None:
    """B1 反钉：节点真不存在 ⇒ anchor_missing（不是假 ok）。"""
    root, base, cand = repo
    cases = [{"id": "E2-nope", "kind": "mutation",
              "anchor": "test_probe.py::test_not_there",
              "command": "python3 -c \"print('ok')\""}]
    out = root / "o"
    ledger = ledger_dict(root, base, cand, cases, out)
    assert ledger["cases"][0]["anchor_ok"] is False
    assert ledger["summary"]["anchor_missing"] == 1


def test_new_red_fails_gate_not_f2f(repo) -> None:
    """M2：candidate 新增即红 ⇒ gate FAIL（新红），不落 f2f-WARN；base 侧跳过执行。"""
    root, base, cand = repo
    cases = [{"id": "N1-newred", "kind": "bug",
              "anchor": "test_new.py::test_bad",
              "command": "python3 -m pytest test_new.py -q"}]
    out = root / "o"
    ledger = ledger_dict(root, base, cand, cases, out, gate_command=None)
    c0 = ledger["cases"][0]
    assert c0["anchor_ok"] is True and c0["anchor_ok_base"] is False
    assert c0["base_status"] == "skipped" and c0["candidate_status"] == "fail"
    assert ledger["summary"]["new_red"] == 1
    p = run_eval(root, "gate", "--ledger", str(out / "ledger.json"))
    assert p.returncode == 1 and "新增即红：N1-newred" in p.stdout


def test_new_ok_recorded_not_f2p(repo) -> None:
    root, base, cand = repo
    cases = [{"id": "N2-newok", "kind": "bug",
              "anchor": "test_new_ok.py::test_good",
              "command": "python3 -m pytest test_new_ok.py -q"}]
    out = root / "o"
    ledger = ledger_dict(root, base, cand, cases, out, gate_command=None)
    assert ledger["summary"]["new_ok"] == 1 and ledger["summary"]["fail2pass"] == 0
    p = run_eval(root, "gate", "--ledger", str(out / "ledger.json"))
    assert p.returncode == 0


FLAKY_CMD = ("python3 -c \"import sys,pathlib; p=pathlib.Path('count.txt'); "
             "n=(int(p.read_text())+1) if p.exists() else 0; p.write_text(str(n)); "
             "sys.exit(0 if (n>=1 or not pathlib.Path('newflag.txt').exists()) else 1)\"")


def test_retries_flaky_pass_not_regression(repo) -> None:
    """M1：candidate 首跑红、复跑绿（节拍类）⇒ --retries 2 不定罪；ledger 记 retries。"""
    root, base, cand = repo
    cases = [{"id": "R1-flaky", "kind": "bug", "anchor": "README.md#marker",
              "command": FLAKY_CMD}]
    out = root / "o"
    ledger = ledger_dict(root, base, cand, cases, out, extra=["--retries", "2"],
                         gate_command=None)
    c0 = ledger["cases"][0]
    assert c0["base_status"] == "pass" and c0["candidate_status"] == "pass"
    assert c0["retries_used"] == 1
    assert ledger["summary"]["pass2pass"] == 1
    p = run_eval(root, "gate", "--ledger", str(out / "ledger.json"))
    assert p.returncode == 0


def test_retries_exhausted_still_regression(repo) -> None:
    """M1 反面：恒红（newflag 恒在）复跑耗尽 ⇒ 仍判 pass2fail 回归。"""
    root, base, cand = repo
    always_fail = ("python3 -c \"import sys,pathlib; "
                   "sys.exit(0 if not pathlib.Path('newflag.txt').exists() else 1)\"")
    cases = [{"id": "R2-real", "kind": "bug", "anchor": "README.md#marker",
              "command": always_fail}]
    out = root / "o"
    ledger = ledger_dict(root, base, cand, cases, out, extra=["--retries", "3"])
    c0 = ledger["cases"][0]
    assert c0["candidate_status"] == "fail" and c0["retries_used"] == 2
    assert ledger["summary"]["pass2fail"] == 1
    p = run_eval(root, "gate", "--ledger", str(out / "ledger.json"))
    assert p.returncode == 1 and "pass→fail：R2-real" in p.stdout


def test_gate_passes_clean_ledger(tmp_path: Path) -> None:
    ledger = {"schema_version": 1, "cases": [
        {"id": "A", "anchor_ok": True, "anchor_ok_base": True,
         "base_status": "pass", "candidate_status": "pass"}],
        "gate_green": {"base": 3, "candidate": 3}}
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(ledger), encoding="utf-8")
    r = run_eval(tmp_path, "gate", "--ledger", str(p))
    assert r.returncode == 0 and "PASS" in r.stdout


def test_gate_fail2fail_warns_not_fails(tmp_path: Path) -> None:
    ledger = {"schema_version": 1, "cases": [
        {"id": "A", "anchor_ok": True, "anchor_ok_base": True,
         "base_status": "fail", "candidate_status": "fail"}],
        "gate_green": {"base": 1, "candidate": 1}}
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(ledger), encoding="utf-8")
    r = run_eval(tmp_path, "gate", "--ledger", str(p))
    assert r.returncode == 0 and "fail2fail" in r.stdout


def test_gate_green_null_skips(tmp_path: Path) -> None:
    ledger = {"schema_version": 1, "cases": [
        {"id": "A", "anchor_ok": True, "anchor_ok_base": True,
         "base_status": "pass", "candidate_status": "pass"}],
        "gate_green": {"base": None, "candidate": None}}
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(ledger), encoding="utf-8")
    r = run_eval(tmp_path, "gate", "--ledger", str(p))
    assert r.returncode == 0 and "gate_green 不完整" in r.stdout


def test_gate_regression_alone_fails(tmp_path: Path) -> None:
    """M171：摘掉 pass→fail 检测 ⇒ 本用例红（无锚缺失/无 green 下降，唯一失败类）。"""
    ledger = {"schema_version": 1, "cases": [
        {"id": "A", "anchor_ok": True, "anchor_ok_base": True,
         "base_status": "pass", "candidate_status": "fail"}],
        "gate_green": {"base": 3, "candidate": 3}}
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(ledger), encoding="utf-8")
    r = run_eval(tmp_path, "gate", "--ledger", str(p))
    assert r.returncode == 1 and "pass→fail：A" in r.stdout


def test_gate_anchor_missing_alone_fails(tmp_path: Path) -> None:
    """M172：摘掉锚缺失 FAIL ⇒ 本用例红（不静默 SKIP）。"""
    ledger = {"schema_version": 1, "cases": [
        {"id": "A", "anchor_ok": False, "anchor_detail": "锚文件不存在：x.md",
         "anchor_ok_base": True, "base_status": "pass", "candidate_status": "pass"}],
        "gate_green": {"base": 3, "candidate": 3}}
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(ledger), encoding="utf-8")
    r = run_eval(tmp_path, "gate", "--ledger", str(p))
    assert r.returncode == 1 and "锚缺失：A" in r.stdout


def test_same_sha_refused(repo) -> None:
    root, base, _cand = repo
    cases = write_cases(root, registry(CASES_MAIN))
    r = run_eval(root, "run", "--cases", str(cases), "--base", base,
                 "--candidate", base, "--out", str(root / "o"))
    assert r.returncode == 2 and "同一 commit" in r.stderr


def test_bad_candidate_sha_cleans_worktrees(repo) -> None:
    """M3：candidate sha 非法（收集失败）⇒ 已建的 base worktree 必须回滚，零残留。"""
    root, base, _cand = repo
    cases = write_cases(root, registry(CASES_MAIN))
    r = run_eval(root, "run", "--cases", str(cases), "--base", base,
                 "--candidate", "deadbeef" * 5, "--out", str(root / "o"))
    assert r.returncode == 2
    wt = subprocess.run(["git", "-C", str(root), "worktree", "list"],
                        capture_output=True, text=True).stdout
    assert wt.count("\n") == 1, wt


def test_registry_duplicate_id_refused(repo) -> None:
    root, base, cand = repo
    dup = write_cases(root, registry([CASES_MAIN[0], CASES_MAIN[0]]), "d.json")
    r = run_eval(root, "run", "--cases", str(dup), "--base", base,
                 "--candidate", cand, "--out", str(root / "o"))
    assert r.returncode == 2 and "重复 case id" in r.stderr


def test_kind_is_free_text_not_validated(repo) -> None:
    """评审 m1：kind 降级为自由文本（不参与判据即不设闭集门）。"""
    root, base, cand = repo
    cases = write_cases(root, registry([
        {"id": "K1", "kind": "未来的某类", "anchor": "README.md#marker",
         "command": "python3 -c \"print('ok')\""}]), "k.json")
    r = run_eval(root, "run", "--cases", str(cases), "--base", base,
                 "--candidate", cand, "--out", str(root / "o"), "--timeout", "120")
    assert r.returncode == 0, r.stdout + r.stderr


def test_worktree_root_explicit(repo) -> None:
    """M3：--worktree-root 显式根目录；跑完即清（worktree list 回 1，目录被删）。"""
    root, base, cand = repo
    cases = write_cases(root, registry(CASES_MAIN))
    wt_root = root / "wt"
    p = run_eval(root, "run", "--cases", str(cases), "--base", base,
                 "--candidate", cand, "--out", str(root / "o"), "--timeout", "120",
                 "--worktree-root", str(wt_root))
    assert p.returncode == 0, p.stdout + p.stderr
    wt = subprocess.run(["git", "-C", str(root), "worktree", "list"],
                        capture_output=True, text=True).stdout
    assert wt.count("\n") == 1, wt
    assert not wt_root.exists() or not any(wt_root.iterdir())
