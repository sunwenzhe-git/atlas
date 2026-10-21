#!/usr/bin/env python3
"""`cli_review_convert.py` 的假绿测试（`gates.md` 假绿测试义务）。

每条用例 = 一个「喂坏输入必红 / 喂好输入必绿」的证明：
未知严重度 / 缺实审数 / 缺应审口径 / 覆盖旧轮 ⇒ 各自 exit 2（响亮，不静默）；
Critical ⇒ exit 1 + FAIL；M<N ⇒ WARN；other 不计门禁；产物三件形态。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cli_review_convert.py"


def run(tmp_path: Path, payload: dict | None, *, unit: str = "B1", extra: list[str] | None = None,
        infile: str = "ocr.json") -> subprocess.CompletedProcess:
    d = tmp_path / "report"
    inp = tmp_path / infile
    if payload is not None:
        inp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    cmd = [sys.executable, str(SCRIPT), "--root", str(tmp_path), "--input", str(inp),
           "--out", "report", "--unit", unit, "--round", "1"]
    return subprocess.run(cmd + (extra or []), capture_output=True, text=True)


def ok_payload(comments: list[dict] | None = None, files_reviewed: int = 2) -> dict:
    return {"status": "completed", "summary": {"files_reviewed": files_reviewed, "comments":
            len(comments or [])}, "comments": comments or [], "warnings": []}


C = {"path": "src/a.ts", "content": "覆盖了原文件", "start_line": 88, "end_line": 88,
     "category": "bug", "severity": "critical", "suggestion_code": "先查重再写"}


def test_unknown_severity_refused(tmp_path: Path) -> None:
    bad = ok_payload([dict(C, severity="catastrophic")])
    r = run(tmp_path, bad, extra=["--expected-files", "2"])
    assert r.returncode == 2 and "严重度" in r.stderr


def test_missing_summary_refused(tmp_path: Path) -> None:
    r = run(tmp_path, {"status": "completed", "comments": []}, extra=["--expected-files", "2"])
    assert r.returncode == 2 and "files_reviewed" in r.stderr


def test_missing_expected_scope_refused(tmp_path: Path) -> None:
    r = run(tmp_path, ok_payload())  # 无 --from/--to 也无 --expected-files
    assert r.returncode == 2 and "应审" in r.stderr


def test_critical_fails(tmp_path: Path) -> None:
    r = run(tmp_path, ok_payload([C]), extra=["--expected-files", "1"])
    assert r.returncode == 1
    review = json.loads((tmp_path / "report" / "review.json").read_text())
    assert review["status"] == "FAIL" and review["ok"] is False
    assert review["checks"][0]["level"] == "Critical" and review["checks"][0]["rollback"] == "implement"


def test_partial_coverage_warns(tmp_path: Path) -> None:
    r = run(tmp_path, ok_payload([], files_reviewed=1), extra=["--expected-files", "3"])
    assert r.returncode == 0
    review = json.loads((tmp_path / "report" / "review.json").read_text())
    assert review["status"] == "WARN"


def test_same_unit_round_refuses_overwrite(tmp_path: Path) -> None:
    run(tmp_path, ok_payload(), extra=["--expected-files", "2"])
    r = run(tmp_path, ok_payload(), extra=["--expected-files", "2"])
    assert r.returncode == 2 and "不得覆盖" in r.stderr


def test_other_category_not_gated(tmp_path: Path) -> None:
    r = run(tmp_path, ok_payload([dict(C, severity="low", category="other")]),
            extra=["--expected-files", "1"])
    assert r.returncode == 0
    review = json.loads((tmp_path / "report" / "review.json").read_text())
    assert review["checks"] == [] and len(review["other"]) == 1 and review["status"] == "PASS"


def test_outputs_three_artifacts(tmp_path: Path) -> None:
    r = run(tmp_path, ok_payload([dict(C, severity="medium")], files_reviewed=1),
            extra=["--expected-files", "1"])
    assert r.returncode == 0
    rep = tmp_path / "report"
    f1 = rep / "findings" / "B1.r1.json"
    assert json.loads(f1.read_text())["status"] == "WARN"  # medium → Major ⇒ WARN
    readme = (rep / "README.md").read_text()
    assert "## 1. 审查总结" in readme and "应审 1 / 实审 1" in readme and "优化建议" in readme


def test_high_maps_to_major(tmp_path: Path) -> None:
    r = run(tmp_path, ok_payload([dict(C, severity="high")]), extra=["--expected-files", "1"])
    assert r.returncode == 0
    review = json.loads((tmp_path / "report" / "review.json").read_text())
    assert review["checks"][0]["level"] == "Major" and review["status"] == "WARN"


# ── 2026-10-21 D129：fingerprint 生成与 round 4 升级复议约束 ──────────────────────
def test_converts_checks_with_fingerprint_and_v2_schema(tmp_path: Path) -> None:
    """D129：转换器产出的 checks 带有去重 fingerprint，默认 schema_version 为 2。"""
    r = run(tmp_path, ok_payload([dict(C, severity="high")]), extra=["--expected-files", "1"])
    assert r.returncode == 0
    review = json.loads((tmp_path / "report" / "review.json").read_text())
    assert review["schema_version"] == 2
    c = review["checks"][0]
    assert "fingerprint" in c and len(c["fingerprint"]) == 16
    assert c["pre_existing"] is False
    assert c["disposition"] == "open"


def test_round_4_refuses_without_escalation(tmp_path: Path) -> None:
    """D129：round >= 4 必须显式声明 --escalate-to 与 --escalate-reason。"""
    # 无 escalation ⇒ 拒绝
    r = run(tmp_path, ok_payload(), extra=["--expected-files", "1", "--round", "4"])
    assert r.returncode == 2 and "4 轮收敛上限" in r.stderr

    # 降版不得开后门（评审 Minor：轮次上限属过程收敛纪律，与报告形态版本无关）
    r1 = run(tmp_path, ok_payload(), extra=["--expected-files", "1", "--round", "5",
                                            "--schema-version", "1"])
    assert r1.returncode == 2 and "4 轮收敛上限" in r1.stderr, r1.stderr

    # 有 escalation ⇒ 放行并记入报告
    r2 = run(tmp_path, ok_payload(), extra=[
        "--expected-files", "1", "--round", "4",
        "--escalate-to", "arch-lead", "--escalate-reason", "收敛争议复议"
    ])
    assert r2.returncode == 0
    review = json.loads((tmp_path / "report" / "review.json").read_text())
    assert review["escalation"] == {"to": "arch-lead", "reason": "收敛争议复议"}


def test_fingerprint_stable_across_line_numbers(tmp_path: Path) -> None:
    """D129 评审 Major 修正：target 的行号区间（`src/a.ts:12-15`）不得进入指纹。

    CLI 恒产 `path:start-end` 形态；若指纹含行号，同一问题在下一轮因行号漂移得到新指纹
    ⇒ 去重门永不命中，「不重复已贴出的发现」落空。本钉两侧：行号不同 ⇒ 指纹同；
    内容不同 ⇒ 指纹不同（防「一律常量化」把去重做成恒同）。
    """
    r_a = run(tmp_path, ok_payload([dict(C, severity="high", start_line=12, end_line=15)]),
              unit="FP-A", extra=["--expected-files", "3"])
    assert r_a.returncode == 0
    r_b = run(tmp_path, ok_payload([dict(C, severity="high", start_line=34, end_line=34)]),
              unit="FP-B", extra=["--expected-files", "3"])
    assert r_b.returncode == 0
    fp_a = json.loads((tmp_path / "report" / "findings" / "FP-A.r1.json").read_text())
    fp_b = json.loads((tmp_path / "report" / "findings" / "FP-B.r1.json").read_text())
    assert fp_a["checks"][0]["fingerprint"] == fp_b["checks"][0]["fingerprint"], (
        "行号漂移后指纹变化 ⇒ 去重门永不命中")

    r_c = run(tmp_path, ok_payload([dict(C, severity="high", content="另一类空引用")]),
              unit="FP-C", extra=["--expected-files", "3"])
    assert r_c.returncode == 0
    fp_c = json.loads((tmp_path / "report" / "findings" / "FP-C.r1.json").read_text())
    assert fp_c["checks"][0]["fingerprint"] != fp_a["checks"][0]["fingerprint"], (
        "不同内容指纹相同 ⇒ 去重门误杀真问题")

