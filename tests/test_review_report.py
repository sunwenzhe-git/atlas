#!/usr/bin/env python3
"""`scripts/validate_review_report.py` 回归测试（`3509 §B112` 残留清偿，2026-10-06）。

夹具 = 临时报告目录（`review.json` + `README.md`）。每条判据测两侧（**正例必须绿**）：

  1. 双份留痕存在（缺 review.json / 缺 README ⇒ FAIL）；
  2. §3 必备键与类型（缺键 / round=0 ⇒ FAIL）；
  3. 分级闭集 + 回退环（未知 level / 缺 rollback ⇒ FAIL）；
  4. 状态映射写死复算（有 Critical 而 status=PASS ⇒ FAIL）；
  5. 应审/实审对账（缺 ⇒ FAIL / 缺一半 ⇒ FAIL / M<N ⇒ WARN / 预算击穿 ⇒ WARN / 齐 ⇒ PASS）。

变异证明（`gates.md` 2.1 行）：M35 摘掉状态映射复算 ⇒ `test_status_mapping_mismatch_fails` 红；
M36 把「缺对账字段」降为放行 ⇒ `test_missing_counts_fail` 红。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
VR = PKG_ROOT / "scripts" / "validate_review_report.py"

GOOD = {
    "ok": True, "status": "PASS", "root": "/tmp/demo", "scope": "夹具范围",
    "unit": "demo-unit", "round": 1, "expected": 3, "reviewed": 3,
    "checks": [{"id": "D1", "level": "Minor", "check": "style", "target": "a.py:1",
                "detail": "措辞", "rollback": "implement"}],
    "other": [],
}


def mk_report(root: Path, payload, *, readme: bool = True, name: str = "r1") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "review.json").write_text(
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False),
        encoding="utf-8")
    if readme:
        (d / "README.md").write_text("# 夹具报告\n", encoding="utf-8")
    return d


def run(d: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(VR), "--dir", str(d)],
                          capture_output=True, text=True, timeout=120)


def test_good_report_passes() -> None:
    """正例必须先绿：形态 / 映射 / 对账全齐 ⇒ PASS、退出码 0。"""
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), GOOD))
        assert p.returncode == 0, p.stdout + p.stderr
        assert p.stdout.strip().endswith("PASS"), p.stdout


def test_missing_review_json_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = root / "r1"
        d.mkdir()
        (d / "README.md").write_text("x", encoding="utf-8")
        p = run(d)
        assert p.returncode == 1 and "未审" in p.stdout, p.stdout


def test_missing_readme_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), GOOD, readme=False))
        assert p.returncode == 1 and "README" in p.stdout, p.stdout


def test_unparsable_json_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), "{not json"))
        assert p.returncode == 1 and "解析失败" in p.stdout, p.stdout


def test_missing_required_key_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        payload = {k: v for k, v in GOOD.items() if k != "round"}
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 1 and "round" in p.stdout, p.stdout


def test_zero_round_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), {**GOOD, "round": 0}))
        assert p.returncode == 1 and "round" in p.stdout, p.stdout


def test_unknown_level_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        payload = {**GOOD, "checks": [{**GOOD["checks"][0], "level": "high"}]}
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 1 and "闭集" in p.stdout, p.stdout


def test_missing_rollback_fails() -> None:
    """骨架 §2.4：每条 finding 必带回退环 ⇒ 缺 ⇒ FAIL。"""
    with tempfile.TemporaryDirectory() as td:
        payload = {**GOOD, "checks": [{k: v for k, v in GOOD["checks"][0].items() if k != "rollback"}]}
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 1 and "rollback" in p.stdout, p.stdout


def test_status_mapping_mismatch_fails() -> None:
    """有 Critical 而 status=PASS ⇒ 映射复算 FAIL。

    变异证明 M35：摘掉映射复算判据 ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        payload = {**GOOD, "checks": [{**GOOD["checks"][0], "level": "Critical"}]}
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 1 and "映射复算" in p.stdout, p.stdout


def test_missing_counts_fail() -> None:
    """缺 expected / reviewed ⇒ FAIL（缺权威输入不得给「通过」）。

    变异证明 M36：把本判据降为放行 ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = run(mk_report(root, {k: v for k, v in GOOD.items() if k not in ("expected", "reviewed")}))
        assert p.returncode == 1 and "expected" in p.stdout, p.stdout


def test_half_counts_fail() -> None:
    """expected / reviewed 只有一半 ⇒ FAIL（对账不可判，比缺失更糟的形态半截）。"""
    with tempfile.TemporaryDirectory() as td:
        payload = {**GOOD, "reviewed": None}
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 1 and "一半" in p.stdout, p.stdout


def test_fewer_reviewed_than_expected_warns() -> None:
    """M<N ⇒ WARN（少审，查静默跳过）但退出码 0——与校验器同源：WARN 不置红但可见。

    注：映射不变量 `ok == (status != \"FAIL\")` ⇒ WARN 报告的 ok 是 True（cli_review_convert 同形）。
    """
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), {**GOOD, "status": "WARN", "reviewed": 2}))
        assert p.returncode == 0, p.stdout + p.stderr
        assert "WARN" in p.stdout and "少审" in p.stdout, p.stdout


def test_budget_exceeded_warns() -> None:
    """budget_exceeded ⇒ 映射下限 WARN（cli_review_convert 同规则）+ 对账行 WARN。"""
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), {**GOOD, "status": "WARN", "budget_exceeded": True}))
        assert p.returncode == 0 and "击穿" in p.stdout, p.stdout
