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


def ok_payload(comments: list[dict] | None = None, files_reviewed: int = 2, *,
               status: str = "completed", coverage: dict | None = None) -> dict:
    payload = {"status": status, "summary": {"files_reviewed": files_reviewed, "comments":
               len(comments or [])}, "comments": comments or [], "warnings": []}
    if coverage is not None:
        payload["manifest"] = {"coverage": coverage}
    return payload


def coverage(completed=(), failed=(), waived=(), reused=(), selected=None) -> dict:
    def paths(items):
        return [{"path": p} for p in items]

    if selected is None:
        selected = list(dict.fromkeys([*completed, *reused, *failed, *waived]))
    return {"completed": paths(completed), "failed": paths(failed),
            "waived": paths(waived), "reused": paths(reused),
            "selected": paths(selected)}


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


# ── 2026-10-31 RFC-20261031-01 Batch A：coverage 权威 + CLI 失败面 ──────────────
def _review(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report" / "review.json").read_text())


def test_coverage_completed_is_reviewed_not_summary(tmp_path: Path) -> None:
    """M37：coverage.completed 是实审权威，summary 只作自报。

    变异证明 M37：摘掉 coverage 读取（退回 summary）⇒ 本用例红。
    """
    payload = ok_payload(
        [], files_reviewed=6, status="partial",
        coverage=coverage(
            completed=("src/a.ts", "src/b.ts", "src/c.ts"),
            failed=("src/e.ts",), waived=("src/f.ts",),
            selected=("src/a.ts", "src/b.ts", "src/c.ts", "src/e.ts", "src/f.ts"),
        ),
    )
    r = run(tmp_path, payload, extra=["--expected-files", "5"])
    assert r.returncode == 0, r.stderr
    review = _review(tmp_path)
    assert review["reviewed"] == 3
    assert review["expected"] == 5
    assert review["cli_status"] == "partial"
    assert review["failed_files"] == ["src/e.ts"]
    assert review["waived_files"] == ["src/f.ts"]
    assert review["status"] == "WARN"
    assert any("summary.files_reviewed=6" in w for w in review["cli_warnings"])


def test_coverage_partial_with_critical_still_fails(tmp_path: Path) -> None:
    """CLI partial 只抬 WARN，不得把 Critical 降级。"""
    payload = ok_payload(
        [dict(C, severity="critical")], files_reviewed=3, status="partial",
        coverage=coverage(completed=("src/a.ts", "src/b.ts"), failed=("src/c.ts",)),
    )
    r = run(tmp_path, payload, extra=["--expected-files", "3"])
    assert r.returncode == 1
    assert _review(tmp_path)["status"] == "FAIL"


def test_coverage_empty_completed_refused(tmp_path: Path) -> None:
    """有 coverage 但 completed 为空且无 findings ⇒ 没有发生审查，拒绝产出。"""
    payload = ok_payload(
        [], files_reviewed=3, status="failed",
        coverage=coverage(completed=(), failed=("src/a.ts", "src/b.ts", "src/c.ts")),
    )
    r = run(tmp_path, payload, extra=["--expected-files", "3"])
    assert r.returncode == 2 and "没有发生审查" in r.stderr


def test_coverage_missing_completed_refused(tmp_path: Path) -> None:
    payload = ok_payload([], files_reviewed=3, status="partial")
    payload["manifest"] = {"coverage": {"selected": [{"path": "src/a.ts"}]}}
    r = run(tmp_path, payload, extra=["--expected-files", "3"])
    assert r.returncode == 2 and "completed" in r.stderr


def test_summary_coverage_mismatch_uses_coverage(tmp_path: Path) -> None:
    payload = ok_payload(
        [], files_reviewed=6, status="complete",
        coverage=coverage(completed=("src/a.ts", "src/b.ts", "src/c.ts", "src/d.ts")),
    )
    r = run(tmp_path, payload, extra=["--expected-files", "4"])
    assert r.returncode == 0
    review = _review(tmp_path)
    assert review["reviewed"] == 4 and review["status"] == "PASS"
    assert any("summary.files_reviewed=6" in w for w in review["cli_warnings"])


def test_reused_not_counted_as_reviewed(tmp_path: Path) -> None:
    payload = ok_payload(
        [], files_reviewed=3, status="complete",
        coverage=coverage(completed=("src/a.ts", "src/b.ts"), reused=("src/c.ts",)),
    )
    r = run(tmp_path, payload, extra=["--expected-files", "3"])
    assert r.returncode == 0
    review = _review(tmp_path)
    assert review["reviewed"] == 2 and review["status"] == "WARN"
    assert review["reused_files"] == ["src/c.ts"]


def test_failed_files_with_complete_status_warns(tmp_path: Path) -> None:
    payload = ok_payload(
        [], files_reviewed=3, status="complete",
        coverage=coverage(completed=("src/a.ts", "src/b.ts"), failed=("src/c.ts",)),
    )
    r = run(tmp_path, payload, extra=["--expected-files", "3"])
    assert r.returncode == 0
    review = _review(tmp_path)
    assert review["reviewed"] == 2 and review["status"] == "WARN"
    assert review["failed_files"] == ["src/c.ts"]


def test_unknown_cli_status_recorded_not_floor(tmp_path: Path) -> None:
    payload = ok_payload(
        [], files_reviewed=2, status="weird",
        coverage=coverage(completed=("src/a.ts", "src/b.ts")),
    )
    r = run(tmp_path, payload, extra=["--expected-files", "2"])
    assert r.returncode == 0
    review = _review(tmp_path)
    assert review["cli_status"] == "unknown" and review["status"] == "PASS"
    assert any("未知 CLI status" in w for w in review["cli_warnings"])


def test_skipped_cli_status_recorded_not_floor(tmp_path: Path) -> None:
    payload = ok_payload(
        [], files_reviewed=2, status="skipped",
        coverage=coverage(completed=("src/a.ts", "src/b.ts")),
    )
    r = run(tmp_path, payload, extra=["--expected-files", "2"])
    assert r.returncode == 0
    review = _review(tmp_path)
    assert review["cli_status"] == "skipped" and review["status"] == "PASS"


def test_no_completed_with_findings_warns(tmp_path: Path) -> None:
    payload = ok_payload(
        [dict(C, severity="high")], files_reviewed=1, status="failed",
        coverage=coverage(completed=(), failed=("src/a.ts",)),
    )
    r = run(tmp_path, payload, extra=["--expected-files", "1"])
    assert r.returncode == 0
    review = _review(tmp_path)
    assert review["reviewed"] == 0 and review["status"] == "WARN"
    assert review["failed_files"] == ["src/a.ts"]


def test_coverage_path_normalization_dedup(tmp_path: Path) -> None:
    payload = ok_payload(
        [], files_reviewed=2, status="complete",
        coverage=coverage(completed=("src\\a.ts", "src/a.ts"),
                          selected=("src\\a.ts", "src/a.ts")),
    )
    r = run(tmp_path, payload, extra=["--expected-files", "1"])
    assert r.returncode == 0
    review = _review(tmp_path)
    assert review["reviewed"] == 1 and review["status"] == "PASS"


def test_comments_null_refused(tmp_path: Path) -> None:
    payload = ok_payload([], files_reviewed=2)
    payload["comments"] = None
    r = run(tmp_path, payload, extra=["--expected-files", "2"])
    assert r.returncode == 2 and "comments" in r.stderr


def test_no_coverage_falls_back_to_summary(tmp_path: Path) -> None:
    r = run(tmp_path, ok_payload([], files_reviewed=2, status="complete"),
            extra=["--expected-files", "2"])
    assert r.returncode == 0
    review = _review(tmp_path)
    assert review["reviewed"] == 2 and review["status"] == "PASS"
    assert "failed_files" not in review


# ── 2026-10-31 RFC-20261031-01 Batch B：delta v3 ───────────────────────────────
def test_delta_v3_clean_uses_completed_and_head_sha(tmp_path: Path) -> None:
    payload = ok_payload([], files_reviewed=3, status="complete",
                         coverage=coverage(completed=("src/a.ts", "src/b.ts", "src/c.ts")))
    r = run(tmp_path, payload, extra=["--round", "2", "--expected-files", "3",
                                       "--delta-only", "--base-sha", "111", "--head-sha", "222"])
    assert r.returncode == 0, r.stderr
    review = _review(tmp_path)
    assert review["schema_version"] == 3
    assert review["head_sha"] == "222"
    assert review["reviewed_files"] == ["src/a.ts", "src/b.ts", "src/c.ts"]
    assert review["status"] == "PASS" and "delta_warnings" not in review


def test_delta_v3_missing_head_sha_refused(tmp_path: Path) -> None:
    payload = ok_payload([], files_reviewed=3, status="complete",
                         coverage=coverage(completed=("src/a.ts", "src/b.ts", "src/c.ts")))
    r = run(tmp_path, payload, extra=["--round", "2", "--expected-files", "3",
                                       "--delta-only", "--base-sha", "111"])
    assert r.returncode == 2 and "head_sha" in r.stderr


def test_delta_v3_without_coverage_or_reviewed_files_refused(tmp_path: Path) -> None:
    payload = ok_payload([], files_reviewed=3, status="complete")
    r = run(tmp_path, payload, extra=["--round", "2", "--expected-files", "3",
                                       "--delta-only", "--head-sha", "222"])
    assert r.returncode == 2 and "reviewed_files" in r.stderr


def test_delta_v3_explicit_reviewed_files_without_coverage(tmp_path: Path) -> None:
    payload = ok_payload([], files_reviewed=3, status="complete")
    r = run(tmp_path, payload, extra=["--round", "2", "--expected-files", "3",
                                       "--delta-only", "--head-sha", "222",
                                       "--reviewed-files", "src/a.ts,src/b.ts,src/c.ts"])
    assert r.returncode == 0, r.stderr
    review = _review(tmp_path)
    assert review["schema_version"] == 3
    assert review["reviewed_files"] == ["src/a.ts", "src/b.ts", "src/c.ts"]
    assert review["status"] == "PASS"


def test_delta_v3_reviewed_files_from_completed_not_findings(tmp_path: Path) -> None:
    payload = ok_payload([dict(C, severity="high")], files_reviewed=3, status="complete",
                         coverage=coverage(completed=("src/a.ts", "src/b.ts", "src/c.ts")))
    r = run(tmp_path, payload, extra=["--round", "2", "--expected-files", "3",
                                       "--delta-only", "--head-sha", "222"])
    assert r.returncode == 0, r.stderr
    review = _review(tmp_path)
    assert review["reviewed_files"] == ["src/a.ts", "src/b.ts", "src/c.ts"]
    assert review["status"] == "WARN"  # high → Major；不是 reviewed_files 1/3
    assert "delta_warnings" not in review


def test_delta_v3_clean_reused_warns_m_le(tmp_path: Path) -> None:
    payload = ok_payload(
        [], files_reviewed=3, status="complete",
        coverage=coverage(completed=("src/a.ts", "src/b.ts"), reused=("src/c.ts",)),
    )
    r = run(tmp_path, payload, extra=["--round", "2", "--expected-files", "3",
                                       "--delta-only", "--head-sha", "222",
                                       "--reviewed-files", "src/a.ts,src/b.ts"])
    assert r.returncode == 0, r.stderr
    review = _review(tmp_path)
    assert review["reviewed"] == 2 and review["reviewed_files"] == ["src/a.ts", "src/b.ts"]
    assert review["reused_files"] == ["src/c.ts"]
    assert review["status"] == "WARN" and "delta_warnings" not in review


def test_delta_v3_count_mismatch_warns(tmp_path: Path) -> None:
    payload = ok_payload(
        [], files_reviewed=3, status="complete",
        coverage=coverage(completed=("src/a.ts", "src/b.ts")),
    )
    r = run(tmp_path, payload, extra=["--round", "2", "--expected-files", "3",
                                       "--delta-only", "--head-sha", "222",
                                       "--reviewed-files", "src/a.ts,src/b.ts,src/c.ts"])
    assert r.returncode == 0, r.stderr
    review = _review(tmp_path)
    assert review["reviewed"] == 2 and len(review["reviewed_files"]) == 3
    assert any("reviewed_files" in w and "reviewed" in w for w in review["delta_warnings"])
    assert review["status"] == "WARN"


def test_delta_v3_selected_mismatch_warns(tmp_path: Path) -> None:
    payload = ok_payload(
        [], files_reviewed=3, status="complete",
        coverage=coverage(completed=("src/a.ts", "src/b.ts", "src/c.ts"),
                          selected=("src/a.ts", "src/b.ts", "src/c.ts", "src/d.ts")),
    )
    r = run(tmp_path, payload, extra=["--round", "2", "--expected-files", "3",
                                       "--delta-only", "--head-sha", "222"])
    assert r.returncode == 0, r.stderr
    review = _review(tmp_path)
    assert any("selected_files" in w for w in review["delta_warnings"])
    assert review["status"] == "WARN"


def test_delta_v3_target_outside_reviewed_warns(tmp_path: Path) -> None:
    payload = ok_payload(
        [dict(C, severity="low", path="src/c.ts")], files_reviewed=2, status="complete",
        coverage=coverage(completed=("src/a.ts", "src/b.ts")),
    )
    r = run(tmp_path, payload, extra=["--round", "2", "--expected-files", "2",
                                       "--delta-only", "--head-sha", "222"])
    assert r.returncode == 0, r.stderr
    review = _review(tmp_path)
    assert any("src/c.ts" in w and "reviewed_files" in w for w in review["delta_warnings"])
    assert review["status"] == "WARN"


def test_delta_v3_target_on_failed_warns(tmp_path: Path) -> None:
    payload = ok_payload(
        [dict(C, severity="low", path="src/c.ts")], files_reviewed=3, status="complete",
        coverage=coverage(completed=("src/a.ts", "src/b.ts"), failed=("src/c.ts",)),
    )
    r = run(tmp_path, payload, extra=["--round", "2", "--expected-files", "3",
                                       "--delta-only", "--head-sha", "222"])
    assert r.returncode == 0, r.stderr
    review = _review(tmp_path)
    assert any("failed_files" in w for w in review["delta_warnings"])
    assert review["status"] == "WARN"


def test_delta_v2_missing_head_sha_warns(tmp_path: Path) -> None:
    payload = ok_payload([dict(C, severity="low")], files_reviewed=2, status="complete",
                         coverage=coverage(completed=("src/a.ts", "src/b.ts")))
    r = run(tmp_path, payload, extra=["--round", "2", "--expected-files", "2",
                                       "--delta-only", "--schema-version", "2", "--base-sha", "111"])
    assert r.returncode == 0, r.stderr
    review = _review(tmp_path)
    assert review["schema_version"] == 2
    assert review["reviewed_files"] == ["src/a.ts"]  # v2 legacy：findings 反推
    assert any("v2 delta 缺 head_sha" in w for w in review["delta_warnings"])
    assert review["status"] == "WARN"


def test_delta_v3_empty_reviewed_files_refused(tmp_path: Path) -> None:
    payload = ok_payload([dict(C, severity="low")], files_reviewed=1, status="complete",
                         coverage=coverage(completed=(), failed=("src/a.ts",)))
    r = run(tmp_path, payload, extra=["--round", "2", "--expected-files", "1",
                                       "--delta-only", "--head-sha", "222"])
    assert r.returncode == 2 and "reviewed_files" in r.stderr


def test_delta_v3_missing_target_skips_membership(tmp_path: Path) -> None:
    payload = ok_payload(
        [{"content": "定位失败", "category": "bug", "severity": "low"}],
        files_reviewed=2, status="complete",
        coverage=coverage(completed=("src/a.ts", "src/b.ts")),
    )
    r = run(tmp_path, payload, extra=["--round", "2", "--expected-files", "2",
                                       "--delta-only", "--head-sha", "222"])
    assert r.returncode == 0, r.stderr
    review = _review(tmp_path)
    assert "delta_warnings" not in review and review["status"] == "PASS"


def test_delta_v3_reviewed_failed_overlap_warns(tmp_path: Path) -> None:
    payload = ok_payload(
        [], files_reviewed=1, status="complete",
        coverage=coverage(completed=("src/a.ts",), failed=("src/a.ts",),
                          selected=("src/a.ts",)),
    )
    r = run(tmp_path, payload, extra=["--round", "2", "--expected-files", "1",
                                       "--delta-only", "--head-sha", "222"])
    assert r.returncode == 0, r.stderr
    review = _review(tmp_path)
    assert any("交集" in w for w in review["delta_warnings"])
    assert review["status"] == "WARN"

