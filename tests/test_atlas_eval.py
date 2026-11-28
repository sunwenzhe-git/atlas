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
PYTHON_CMD = subprocess.list2cmdline([sys.executable])

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


def py_cmd(*args: str) -> str:
    return subprocess.list2cmdline([sys.executable, *args])


def registry(cases: list[dict], gate_command: str | None = None) -> dict:
    if gate_command is None:
        gate_command = py_cmd("gate.py")
    return {"schema_version": 1, "gate_command": gate_command, "cases": cases}


def write_cases(root: Path, cases: dict, name: str = "cases.json") -> Path:
    def expand(value):
        if isinstance(value, str):
            return value.replace("PYTHON_CMD ", PYTHON_CMD + " ")
        if isinstance(value, dict):
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    cases = expand(cases)
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
     "command": py_cmd("-m", "pytest", "test_sample.py", "-q")},
    {"id": "C2-p2f", "kind": "bug", "anchor": "README.md#marker",
     "command": py_cmd("-c", "import sys,pathlib; sys.exit(0 if pathlib.Path('flag.txt').exists() else 1)")},
    {"id": "C3-f2f", "kind": "mutation", "anchor": "test_sample.py::test_ok",
     "command": py_cmd("-c", "raise SystemExit(1)")},
    {"id": "C4-missing", "kind": "bug", "anchor": "docs/nope.md#X",
     "command": py_cmd("-c", "print('ok')")},
]


def ledger_dict(root: Path, base: str, cand: str, cases: list[dict],
                out: Path, extra: list[str] | None = None,
                gate_command: str | None = None) -> dict:
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
              "command": py_cmd("-c", "print('ok')")}]
    out = root / "o"
    ledger = ledger_dict(root, base, cand, cases, out)
    assert ledger["cases"][0]["anchor_ok"] is True
    assert ledger["cases"][0]["anchor_ok_base"] is True


def test_missing_node_anchor_detected(repo) -> None:
    """B1 反钉：节点真不存在 ⇒ anchor_missing（不是假 ok）。"""
    root, base, cand = repo
    cases = [{"id": "E2-nope", "kind": "mutation",
              "anchor": "test_probe.py::test_not_there",
              "command": "PYTHON_CMD -c \"print('ok')\""}]
    out = root / "o"
    ledger = ledger_dict(root, base, cand, cases, out)
    assert ledger["cases"][0]["anchor_ok"] is False
    assert ledger["summary"]["anchor_missing"] == 1


def test_new_red_fails_gate_not_f2f(repo) -> None:
    """M2：candidate 新增即红 ⇒ gate FAIL（新红），不落 f2f-WARN；base 侧跳过执行。"""
    root, base, cand = repo
    cases = [{"id": "N1-newred", "kind": "bug",
              "anchor": "test_new.py::test_bad",
              "command": py_cmd("-m", "pytest", "test_new.py", "-q")}]
    out = root / "o"
    ledger = ledger_dict(root, base, cand, cases, out, gate_command="")
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
              "command": py_cmd("-m", "pytest", "test_new_ok.py", "-q")}]
    out = root / "o"
    ledger = ledger_dict(root, base, cand, cases, out, gate_command="")
    assert ledger["summary"]["new_ok"] == 1 and ledger["summary"]["fail2pass"] == 0
    p = run_eval(root, "gate", "--ledger", str(out / "ledger.json"))
    assert p.returncode == 0


FLAKY_CMD = (py_cmd("-c", "import sys,pathlib; p=pathlib.Path('count.txt'); "
             "n=(int(p.read_text())+1) if p.exists() else 0; p.write_text(str(n)); "
             "sys.exit(0 if (n>=1 or not pathlib.Path('newflag.txt').exists()) else 1)"))


def test_retries_flaky_pass_not_regression(repo) -> None:
    """M1：candidate 首跑红、复跑绿（节拍类）⇒ --retries 2 不定罪；ledger 记 retries。"""
    root, base, cand = repo
    cases = [{"id": "R1-flaky", "kind": "bug", "anchor": "README.md#marker",
              "command": FLAKY_CMD}]
    out = root / "o"
    ledger = ledger_dict(root, base, cand, cases, out, extra=["--retries", "2"],
                         gate_command="")
    c0 = ledger["cases"][0]
    assert c0["base_status"] == "pass" and c0["candidate_status"] == "pass"
    assert c0["retries_used"] == 1
    assert ledger["summary"]["pass2pass"] == 1
    p = run_eval(root, "gate", "--ledger", str(out / "ledger.json"))
    assert p.returncode == 0


def test_retries_exhausted_still_regression(repo) -> None:
    """M1 反面：恒红（newflag 恒在）复跑耗尽 ⇒ 仍判 pass2fail 回归。"""
    root, base, cand = repo
    always_fail = py_cmd("-c", "import sys,pathlib; "
                         "sys.exit(0 if not pathlib.Path('newflag.txt').exists() else 1)")
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
         "command": "PYTHON_CMD -c \"print('ok')\""}]), "k.json")
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


def _make_harness_and_host(tmp: Path) -> tuple[Path, str, Path, str]:
    """构造最小双仓夹具：harness 源包仓 + host 采纳宿主仓。"""
    harness = tmp / "harness"
    harness.mkdir()
    git(harness, "init", "-q")
    git(harness, "config", "user.email", "t@example.com")
    git(harness, "config", "user.name", "t")
    (harness / "scripts").mkdir()
    (harness / "skills" / "demo").mkdir(parents=True)
    (harness / "patches" / "project-wiring").mkdir(parents=True)
    (harness / "skills" / "demo" / "SKILL.md").write_text("skill-v1\n", encoding="utf-8")
    (harness / "patches" / "project-wiring" / "agent-pointer.md").write_text(
        "pointer-v1\n", encoding="utf-8")
    (harness / "install.py").write_text(
        "import argparse, pathlib, shutil, sys\n"
        "ap = argparse.ArgumentParser()\n"
        "ap.add_argument('--target', required=True)\n"
        "ap.add_argument('--update', action='store_true')\n"
        "ap.add_argument('--force', action='store_true')\n"
        "ap.add_argument('--no-skill', action='store_true')\n"
        "ap.add_argument('--no-wiring', action='store_true')\n"
        "args = ap.parse_args()\n"
        "pkg = pathlib.Path(__file__).resolve().parent\n"
        "tgt = pathlib.Path(args.target)\n"
        "if (pkg / 'FAIL_INSTALL').exists():\n"
        "    sys.exit(3)\n"
        "(tgt / '.atlas').mkdir(parents=True, exist_ok=True)\n"
        "if not args.no_skill:\n"
        "    dst = tgt / '.agents' / 'skills' / 'demo'\n"
        "    dst.mkdir(parents=True, exist_ok=True)\n"
        "    shutil.copy2(pkg / 'skills' / 'demo' / 'SKILL.md', dst / 'SKILL.md')\n"
        "if not args.no_wiring:\n"
        "    shutil.copy2(pkg / 'patches' / 'project-wiring' / 'agent-pointer.md', tgt / 'AGENTS.md')\n",
        encoding="utf-8",
    )
    git(harness, "add", "-A")
    git(harness, "commit", "-qm", "harness-v1")
    h_base = subprocess.run(["git", "-C", str(harness), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()

    host = tmp / "host"
    host.mkdir()
    git(host, "init", "-q")
    git(host, "config", "user.email", "t@example.com")
    git(host, "config", "user.name", "t")
    (host / "README.md").write_text("host-anchor\n", encoding="utf-8")
    (host / "AGENTS.md").write_text("pointer-v1\n", encoding="utf-8")
    (host / ".agents" / "skills" / "demo").mkdir(parents=True)
    (host / ".agents" / "skills" / "demo" / "SKILL.md").write_text("skill-v1\n", encoding="utf-8")
    (host / ".atlas" / "runs").mkdir(parents=True)
    (host / ".atlas" / "runs" / "check-events.jsonl").write_text(
        json.dumps({"timestamp": "2026-11-26T00:00:00", "rows": [{"name": "g0", "status": "ok", "duration_ms": 1}]}) + "\n",
        encoding="utf-8",
    )
    git(host, "add", "-A")
    git(host, "commit", "-qm", "host-base")
    host_sha = subprocess.run(["git", "-C", str(host), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    return harness, h_base, host, host_sha


def test_host_assembles_skills_wiring_and_gate_passes(tmp_path: Path) -> None:
    """M258：host 模式默认装配 skills/ 与 AGENTS.md，且可通过 atlas eval gate。"""
    harness, h_base, host, _host_sha = _make_harness_and_host(tmp_path)
    (harness / "skills" / "demo" / "SKILL.md").write_text("skill-v2\n", encoding="utf-8")
    (harness / "patches" / "project-wiring" / "agent-pointer.md").write_text(
        "pointer-v2\n", encoding="utf-8")
    cases_path = write_cases(tmp_path, {
        "schema_version": 1,
        "gate_command": py_cmd("-c", "print('ok gate1')"),
        "cases": [
            {
                "id": "H1-skill",
                "kind": "fast-lane",
                "anchor": "README.md#host-anchor",
                "command": (
                    "PYTHON_CMD -c \"import pathlib, sys; "
                    "s=pathlib.Path('.agents/skills/demo/SKILL.md').read_text().strip(); "
                    "a=pathlib.Path('AGENTS.md').read_text().strip(); "
                    "sys.exit(0 if s.startswith('skill-v') and a.startswith('pointer-v') else 1)\""
                ),
            },
            {
                "id": "H2-v2-check",
                "kind": "fast-lane",
                "anchor": ".agents/skills/demo/SKILL.md#skill-v2",
                "command": (
                    "PYTHON_CMD -c \"import pathlib, sys; "
                    "sys.exit(0 if 'skill-v2' in pathlib.Path('.agents/skills/demo/SKILL.md').read_text() "
                    "and 'pointer-v2' in pathlib.Path('AGENTS.md').read_text() else 1)\""
                ),
            },
        ],
    }, "host-cases.json")
    out = tmp_path / "out-host"
    p = run_eval(host, "host", "--cases", str(cases_path),
                 "--harness-base", h_base, "--harness-cand", "WORKTREE",
                 "--harness-root", str(harness), "--host-root", str(host),
                 "--out", str(out))
    assert p.returncode == 0, p.stdout + p.stderr
    ledger = json.loads((out / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["mode"] == "host" and ledger["root"] == str(host.resolve())
    assert ledger["summary"]["pass2pass"] == 1 and ledger["summary"]["new_ok"] == 1
    assert (out / "summary.md").is_file()
    g = run_eval(host, "gate", "--ledger", str(out / "ledger.json"), "--out", "gate-res.json")
    assert g.returncode == 0, g.stdout + g.stderr
    assert (host / "gate-res.json").is_file()


def test_host_worktree_anti_noop_refused_without_allow(tmp_path: Path) -> None:
    """M257：WORKTREE 与 harness-base 装配集一致时（即使非装配文档脏）拒绝空跑；--allow-noop 放行。"""
    harness, h_base, host, _host_sha = _make_harness_and_host(tmp_path)
    (harness / "README.md").write_text("non-assembly-only\n", encoding="utf-8")
    cases_path = write_cases(tmp_path, registry([
        {"id": "H0", "kind": "smoke", "anchor": "README.md#host-anchor",
         "command": "PYTHON_CMD -c \"print('ok')\""}
    ], gate_command=None), "noop-cases.json")
    r_refuse = run_eval(host, "host", "--cases", str(cases_path),
                        "--harness-base", h_base, "--harness-cand", "WORKTREE",
                        "--harness-root", str(harness), "--host-root", str(host),
                        "--out", str(tmp_path / "out1"))
    assert r_refuse.returncode == 2 and "完全一致" in r_refuse.stderr
    r_allow = run_eval(host, "host", "--cases", str(cases_path),
                       "--harness-base", h_base, "--harness-cand", "WORKTREE",
                       "--harness-root", str(harness), "--host-root", str(host),
                       "--allow-noop", "--out", str(tmp_path / "out2"))
    assert r_allow.returncode == 0, r_allow.stdout + r_allow.stderr


def test_host_cleans_both_repos_on_install_failure(tmp_path: Path) -> None:
    harness, h_base, host, _host_sha = _make_harness_and_host(tmp_path)
    (harness / "skills" / "demo" / "SKILL.md").write_text("skill-v2\n", encoding="utf-8")
    (harness / "FAIL_INSTALL").write_text("boom\n", encoding="utf-8")
    cases_path = write_cases(tmp_path, registry([
        {"id": "H0", "kind": "smoke", "anchor": "README.md#host-anchor",
         "command": "PYTHON_CMD -c \"print('ok')\""}
    ], gate_command=None), "fail-install.json")
    wt_root = tmp_path / "wt-clean"
    r = run_eval(host, "host", "--cases", str(cases_path),
                 "--harness-base", h_base, "--harness-cand", "WORKTREE",
                 "--harness-root", str(harness), "--host-root", str(host),
                 "--worktree-root", str(wt_root), "--out", str(tmp_path / "out-fail"))
    assert r.returncode == 2 and "退出码 3" in r.stderr
    for repo_dir in (harness, host):
        wt = subprocess.run(["git", "-C", str(repo_dir), "worktree", "list"],
                            capture_output=True, text=True).stdout
        assert wt.count("\n") == 1, wt
    assert not wt_root.exists()


def test_host_check_events_delta_excludes_gate_command_and_ablation(tmp_path: Path) -> None:
    harness, h_base, host, _host_sha = _make_harness_and_host(tmp_path)
    (harness / "skills" / "demo" / "SKILL.md").write_text("skill-v2\n", encoding="utf-8")
    append_case = (
        py_cmd(
            "-c",
            "import json, pathlib; p=pathlib.Path('.atlas/runs/check-events.jsonl'); "
            "lines=[json.dumps({'timestamp':'t1','ablation_id':None,'rows':[{'name':'g1','status':'WARN','duration_ms':12}]}),"
            "json.dumps({'timestamp':'t2','ablation_id':'ab-1','rows':[{'name':'g2','status':'FAIL','duration_ms':99}]}),"
            "'{bad-json']; p.write_text(p.read_text()+chr(10).join(lines)+chr(10))",
        )
    )
    gate_cmd = (
        py_cmd(
            "-c",
            "import json, pathlib; p=pathlib.Path('.atlas/runs/check-events.jsonl'); "
            "p.write_text(p.read_text()+json.dumps({'timestamp':'tg','ablation_id':None,'rows':[{'name':'g3','status':'FAIL','duration_ms':5}]})+chr(10)); "
            "print('ok g1')",
        )
    )
    cases_path = write_cases(tmp_path, registry([
        {"id": "H-EV", "kind": "obs", "anchor": "README.md#host-anchor", "command": append_case}
    ], gate_command=gate_cmd), "ev-cases.json")
    out = tmp_path / "out-ev"
    r = run_eval(host, "host", "--cases", str(cases_path),
                 "--harness-base", h_base, "--harness-cand", "WORKTREE",
                 "--harness-root", str(harness), "--host-root", str(host),
                 "--out", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    delta = json.loads((out / "ledger.json").read_text(encoding="utf-8"))["check_events_delta"]["candidate"]
    assert delta["runs"] == 1 and delta["warn_rows"] == 1 and delta["fail_rows"] == 0
    assert delta["parse_errors"] == 1 and "g3" not in delta["by_gate"]


def test_host_rejects_missing_installer_in_historical_base(tmp_path: Path) -> None:
    harness = tmp_path / "old-harness"
    harness.mkdir()
    git(harness, "init", "-q")
    git(harness, "config", "user.email", "t@example.com")
    git(harness, "config", "user.name", "t")
    (harness / "README.md").write_text("pre-install-py\n", encoding="utf-8")
    git(harness, "add", "-A")
    git(harness, "commit", "-qm", "old")
    old_sha = subprocess.run(["git", "-C", str(harness), "rev-parse", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
    (harness / "install.py").write_text("print('ok')\n", encoding="utf-8")
    (harness / "skills" / "demo").mkdir(parents=True)
    (harness / "skills" / "demo" / "SKILL.md").write_text("v1\n", encoding="utf-8")
    host = tmp_path / "host-old"
    host.mkdir()
    git(host, "init", "-q")
    git(host, "config", "user.email", "t@example.com")
    git(host, "config", "user.name", "t")
    (host / "README.md").write_text("host\n", encoding="utf-8")
    git(host, "add", "-A")
    git(host, "commit", "-qm", "h")
    cases_path = write_cases(tmp_path, registry([
        {"id": "H0", "kind": "smoke", "anchor": "README.md#host",
         "command": "PYTHON_CMD -c \"print('ok')\""}
    ], gate_command=None), "old-cases.json")
    r = run_eval(host, "host", "--cases", str(cases_path),
                 "--harness-base", old_sha, "--harness-cand", "WORKTREE",
                 "--harness-root", str(harness), "--host-root", str(host),
                 "--out", str(tmp_path / "out-old"))
    assert r.returncode == 2 and "不支持无 install.py" in r.stderr
