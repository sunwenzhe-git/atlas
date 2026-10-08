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
