#!/usr/bin/env python3
"""`scripts/validate_review_report.py` 回归测试（`3509 §B112` 残留清偿，2026-10-06）。

夹具 = 临时报告目录（`review.json` + `README.md`）。每条判据测两侧（**正例必须绿**）：

  1. 双份留痕存在（缺 review.json / 缺 README ⇒ FAIL）；
  2. §3 必备键与类型（缺键 / round=0 ⇒ FAIL）；
  3. 分级闭集 + 回退环（未知 level / 缺 rollback ⇒ FAIL）；
  4. 状态映射写死复算（有 Critical 而 status=PASS ⇒ FAIL）；
  5. 应审/实审对账（缺 ⇒ FAIL / 缺一半 ⇒ FAIL / M<N ⇒ WARN / 预算击穿 ⇒ WARN / 齐 ⇒ PASS）。

变异证明（编号属本文件）：M35 摘掉状态映射复算 ⇒ `test_status_mapping_mismatch_fails` 红；
M47 应审/实审对账行退回单边 `rev < exp` ⇒ `test_reviewed_exceeds_expected_row_warns` 红
（多报时报告状态 WARN 而行显示 PASS，读报告的人会以为 N/M 齐）；
M36 把「缺对账字段」降为放行 ⇒ `test_missing_counts_fail` 红。
Batch A（RFC-20261031-01）：M40 摘掉 `cli_warn_floor` ⇒ `test_cli_partial_warns` 红；
M41 让 CLI WARN 下限降级 Critical ⇒ `test_cli_partial_does_not_downgrade_critical` 红。
签名严格化（RFC-20261101-03）：M48 `disposition_by` / `disposition_evidence` 退回 `str()` 宽松
⇒ `test_numeric_disposition_by_fails_validator` 红；M99 `verification.evidence` 同处退回宽松
⇒ `test_verification_evidence_must_be_string` 红（同对象里 `by` 已严、`evidence` 曾松的口径分裂）；
M100 `is_blocking_critical` 退回 `bool(str(...))` ⇒ `test_blocking_critical_requires_string_signer` 红
（**内核级钉子**：CLI 侧非字符串签字先被 M48 的形状判据拒掉，注入实测当时三文件 131 条仍全绿；现三文件 138 条中 M100 单红、其余 137 绿）；
M101 `escalation.approved_by` 退回宽松 ⇒ `test_escalation_approved_by_must_be_string` 红。
"""
from __future__ import annotations

import json
import hashlib
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


def run(d: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(VR), "--dir", str(d)] + (extra or []),
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


def test_executed_field_handling() -> None:
    """issue #30：executed: False 时状态下限为 WARN，executed 非 bool 时 FAIL，executed: True 时 PASS。"""
    with tempfile.TemporaryDirectory() as td:
        # executed: False ⇒ 必须为 WARN
        p1 = run(mk_report(Path(td) / "r1", {**GOOD, "status": "WARN", "executed": False}))
        assert p1.returncode == 0, p1.stdout

        # executed: False 但声明 PASS ⇒ 映射复算失败
        p2 = run(mk_report(Path(td) / "r2", {**GOOD, "status": "PASS", "executed": False}))
        assert p2.returncode == 1, p2.stdout

        # executed 不是 bool ⇒ FAIL
        p3 = run(mk_report(Path(td) / "r3", {**GOOD, "status": "WARN", "executed": "no"}))
        assert p3.returncode == 1 and "executed" in p3.stdout, p3.stdout


# ── 2026-10-21 D129：评审收敛与 finding 处置测试 ──────────────────────────────────
def test_v2_pre_existing_critical_downgrades_to_warn_not_fail() -> None:
    """D129：v2 报告中 pre_existing=True 的 Critical 不阻断收口（状态映射复算为 WARN 下限）。"""
    with tempfile.TemporaryDirectory() as td:
        crit_pre = {"id": "D1", "level": "Critical", "check": "bug", "target": "a.ts:1",
                    "detail": "存量空指针", "rollback": "implement", "pre_existing": True}
        # 声明 WARN 且 ok=True ⇒ PASS
        p1 = run(mk_report(Path(td) / "r1", {**GOOD, "schema_version": 2, "status": "WARN", "ok": True, "checks": [crit_pre]}))
        assert p1.returncode == 0, p1.stdout

        # 若错误声明为 PASS 或 FAIL ⇒ 映射复算失败
        p2 = run(mk_report(Path(td) / "r2", {**GOOD, "schema_version": 2, "status": "FAIL", "ok": False, "checks": [crit_pre]}))
        assert p2.returncode == 1 and "映射复算 WARN" in p2.stdout, p2.stdout


def test_v2_disposition_false_positive_with_signature_downgrades_to_warn() -> None:
    """D129：Critical 经签字和取证标记为 false_positive ⇒ 降级为 WARN 下限。"""
    with tempfile.TemporaryDirectory() as td:
        crit_fp = {"id": "D1", "level": "Critical", "check": "security", "target": "b.ts:10",
                   "detail": "误报鉴权缺失", "rollback": "implement", "disposition": "false_positive",
                   "disposition_by": "lead", "disposition_evidence": "外层网关已校验"}
        p1 = run(mk_report(Path(td) / "r1", {**GOOD, "schema_version": 2, "status": "WARN", "ok": True, "checks": [crit_fp]}))
        assert p1.returncode == 0, p1.stdout

        # 缺少签字人 ⇒ 校验失败
        crit_bad = dict(crit_fp, disposition_by="")
        p2 = run(mk_report(Path(td) / "r2", {**GOOD, "schema_version": 2, "status": "WARN", "ok": True, "checks": [crit_bad]}))
        assert p2.returncode == 1 and "disposition_by" in p2.stdout, p2.stdout


def test_v2_duplicate_fingerprints_fail_validator() -> None:
    """D129：v2 报告中未关闭的 finding 出现重复 fingerprint ⇒ 校验失败（防止重复刷分）。"""
    with tempfile.TemporaryDirectory() as td:
        c1 = {"id": "D1", "level": "Major", "check": "bug", "target": "c.ts:5",
              "detail": "问题1", "rollback": "implement", "fingerprint": "fp_duplicate_1"}
        c2 = {"id": "D2", "level": "Major", "check": "bug", "target": "c.ts:15",
              "detail": "问题2", "rollback": "implement", "fingerprint": "fp_duplicate_1"}
        p = run(mk_report(Path(td), {**GOOD, "schema_version": 2, "status": "WARN", "checks": [c1, c2]}))
        assert p.returncode == 1 and "重复 finding 指纹" in p.stdout, p.stdout


def test_v2_round_4_requires_escalation() -> None:
    """D129：v2 报告 round >= 4 必须登记有效 escalation，否则判定失败。"""
    with tempfile.TemporaryDirectory() as td:
        # round=4 无 escalation ⇒ FAIL
        p1 = run(mk_report(Path(td) / "r1", {**GOOD, "schema_version": 2, "round": 4}))
        assert p1.returncode == 1 and "4 轮收敛上限" in p1.stdout, p1.stdout

        # round=4 有合法 escalation ⇒ PASS
        esc = {"to": "architecture-team", "reason": "争议边界需拍板", "approved_by": "lead"}
        p2 = run(mk_report(Path(td) / "r2", {**GOOD, "schema_version": 2, "round": 4, "escalation": esc}))
        assert p2.returncode == 0, p2.stdout


# ── 2026-10-31 RFC-20261031-01 Batch A：CLI coverage 失败面 ─────────────────────
def test_cli_partial_warns() -> None:
    """M40：cli_status=partial 或 failed_files 非空 ⇒ 状态下限 WARN。"""
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), {**GOOD, "schema_version": 2, "cli_status": "partial",
                                     "failed_files": ["src/e.ts"], "status": "WARN"}))
        assert p.returncode == 0, p.stdout
        assert "WARN" in p.stdout and "CLI" in p.stdout, p.stdout


def test_cli_partial_does_not_downgrade_critical() -> None:
    """M41：CLI WARN 下限不得把阻断性 Critical 降级。

    形态门只判「报告形态是否合法」：报告自身 status=FAIL 是合法形态，故 validator
    退出码 0；防降级钉在报告 status 仍为 FAIL，且 CLI 行只报 WARN。
    """
    with tempfile.TemporaryDirectory() as td:
        crit = {**GOOD["checks"][0], "level": "Critical"}
        d = mk_report(Path(td), {**GOOD, "schema_version": 2, "checks": [crit],
                                 "cli_status": "partial", "status": "FAIL", "ok": False})
        p = run(d)
        assert p.returncode == 0 and "[WARN] CLI 审查状态" in p.stdout, p.stdout
        review = json.loads((d / "review.json").read_text())
        assert review["status"] == "FAIL" and review["ok"] is False


def test_cli_failed_files_without_status_warns() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), {**GOOD, "schema_version": 2,
                                     "failed_files": ["src/e.ts"], "status": "WARN"}))
        assert p.returncode == 0 and "WARN" in p.stdout and "CLI" in p.stdout, p.stdout


def test_cli_status_invalid_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), {**GOOD, "schema_version": 2, "cli_status": "done"}))
        assert p.returncode == 1 and "cli_status" in p.stdout, p.stdout


def test_cli_failed_files_shape_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), {**GOOD, "schema_version": 2, "failed_files": "src/a.ts"}))
        assert p.returncode == 1 and "failed_files" in p.stdout, p.stdout


def test_cli_failed_files_duplicate_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), {**GOOD, "schema_version": 2,
                                     "failed_files": ["src/a.ts", "src/a.ts"]}))
        assert p.returncode == 1 and "重复" in p.stdout, p.stdout


def test_cli_warnings_shape_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), {**GOOD, "schema_version": 2, "cli_warnings": "x"}))
        assert p.returncode == 1 and "cli_warnings" in p.stdout, p.stdout


def test_cli_skipped_does_not_warn() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), {**GOOD, "schema_version": 2, "cli_status": "skipped"}))
        assert p.returncode == 0 and p.stdout.strip().endswith("PASS"), p.stdout


def test_v2_non_delta_without_cli_fields_passes() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), {**GOOD, "schema_version": 2}))
        assert p.returncode == 0 and p.stdout.strip().endswith("PASS"), p.stdout


# ── 2026-10-31 RFC-20261031-01 Batch B：delta v3 ───────────────────────────────
def test_v3_delta_good_passes() -> None:
    payload = {**GOOD, "schema_version": 3, "delta_only": True, "head_sha": "h",
               "reviewed_files": ["a.py", "b", "c"],
               "selected_files": ["a.py", "b", "c"]}
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 0 and p.stdout.strip().endswith("PASS"), p.stdout


def test_v3_delta_missing_head_sha_fails() -> None:
    payload = {**GOOD, "schema_version": 3, "delta_only": True,
               "reviewed_files": ["a.py", "b", "c"],
               "selected_files": ["a.py", "b", "c"]}
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 1 and "head_sha" in p.stdout, p.stdout


def test_v3_delta_missing_reviewed_files_fails() -> None:
    payload = {**GOOD, "schema_version": 3, "delta_only": True, "head_sha": "h",
               "selected_files": ["a.py", "b", "c"]}
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 1 and "reviewed_files" in p.stdout, p.stdout


def test_v3_delta_duplicate_reviewed_files_fails() -> None:
    payload = {**GOOD, "schema_version": 3, "delta_only": True, "head_sha": "h",
               "reviewed_files": ["a.py", "a.py"], "selected_files": ["a.py"]}
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 1 and "重复" in p.stdout, p.stdout


def test_v3_delta_count_mismatch_warns() -> None:
    payload = {**GOOD, "schema_version": 3, "delta_only": True, "head_sha": "h",
               "reviewed_files": ["a.py"], "selected_files": ["a.py", "b", "c"],
               "status": "WARN"}
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 0 and "WARN" in p.stdout and "delta 对账（v3）" in p.stdout, p.stdout


def test_v3_delta_finding_outside_reviewed_warns() -> None:
    checks = [{**GOOD["checks"][0], "target": "src/x.ts:1"}]
    payload = {**GOOD, "schema_version": 3, "delta_only": True, "head_sha": "h",
               "checks": checks, "reviewed_files": ["a.py", "b", "c"],
               "selected_files": ["a.py", "b", "c"], "status": "WARN"}
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 0 and "delta 对账（v3）" in p.stdout, p.stdout


def test_v3_delta_finding_on_failed_warns() -> None:
    checks = [{**GOOD["checks"][0], "target": "c:1"}]
    payload = {**GOOD, "schema_version": 3, "delta_only": True, "head_sha": "h",
               "expected": 1, "reviewed": 1, "checks": checks,
               "reviewed_files": ["a.py"], "failed_files": ["c"],
               "selected_files": ["a.py", "c"], "status": "WARN"}
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 0 and "delta 对账（v3）" in p.stdout, p.stdout


def test_v3_delta_selected_mismatch_warns() -> None:
    payload = {**GOOD, "schema_version": 3, "delta_only": True, "head_sha": "h",
               "reviewed_files": ["a.py", "b", "c"],
               "selected_files": ["a.py", "b", "c", "d"], "status": "WARN"}
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 0 and "delta 对账（v3）" in p.stdout, p.stdout


def test_v3_delta_clean_reused_warns_m_le() -> None:
    payload = {**GOOD, "schema_version": 3, "delta_only": True, "head_sha": "h",
               "expected": 3, "reviewed": 2,
               "reviewed_files": ["a.py", "b"],
               "selected_files": ["a.py", "b", "c"], "reused_files": ["c"],
               "status": "WARN"}
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 0 and "[PASS] delta 对账（v3）" in p.stdout, p.stdout
        assert "[WARN] 应审/实审对账" in p.stdout, p.stdout


def test_v2_delta_missing_head_sha_warns() -> None:
    payload = {**GOOD, "schema_version": 2, "delta_only": True,
               "reviewed_files": ["a.py"], "status": "PASS"}
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 0, p.stdout
        assert "[WARN] delta 对账（v2 兼容）" in p.stdout, p.stdout
        assert "[PASS] 状态映射复算" in p.stdout, p.stdout


def test_v3_non_delta_without_head_sha_passes() -> None:
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), {**GOOD, "schema_version": 3}))
        assert p.returncode == 0 and p.stdout.strip().endswith("PASS"), p.stdout


def test_v3_delta_selected_files_shape_fails() -> None:
    payload = {**GOOD, "schema_version": 3, "delta_only": True, "head_sha": "h",
               "reviewed_files": ["a.py"], "selected_files": "a.py"}
    with tempfile.TemporaryDirectory() as td:
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 1 and "selected_files" in p.stdout, p.stdout


# ── 2026-11-01 RFC-20261101-02：D5-c scan 通道状态词表 ─────────────────────────────
def test_cli_status_success_shape_accepted() -> None:
    """`success`（`ocr scan` 完成态）在形态门的 cli_status 闭集内，不判错。"""
    with tempfile.TemporaryDirectory() as td:
        payload = {**GOOD, "schema_version": 2, "cli_status": "success", "failed_files": []}
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 0, p.stdout
        assert "不在闭集" not in p.stdout, p.stdout


def test_reviewed_exceeds_expected_row_warns() -> None:
    """M47：多报（M>N）的对账行必须 WARN 且可见，不能只靠状态映射抬下限。

    转换器侧同口径（`review_policy.count_floor`），但形态门若仍按 `rev < exp` 出文案，
    报告状态是 WARN 而对账行显示 PASS —— 读报告的人会以为「N/M 齐」。
    """
    with tempfile.TemporaryDirectory() as td:
        payload = {**GOOD, "schema_version": 2, "status": "WARN", "ok": True,
                   "expected": 3, "reviewed": 4}
        p = run(mk_report(Path(td), payload))
        assert p.returncode == 0, p.stdout + p.stderr
        assert "多报 M>N" in p.stdout, p.stdout
        assert "[WARN] 应审/实审对账" in p.stdout, p.stdout


def test_numeric_disposition_by_fails_validator() -> None:
    """M48：`disposition_by` / `disposition_evidence` 必须是非空字符串。

    取 Minor 级隔离形状判据（不让阻断性 Critical 的状态复算混进来）。
    """
    with tempfile.TemporaryDirectory() as td:
        bad = {**GOOD["checks"][0], "level": "Minor", "disposition": "fixed",
               "disposition_by": 123, "disposition_evidence": ["test green"]}
        p = run(mk_report(Path(td), {**GOOD, "schema_version": 2, "checks": [bad]}))
        assert p.returncode == 1 and "disposition_by" in p.stdout, p.stdout
        bad2 = {**GOOD["checks"][0], "level": "Minor", "disposition": "fixed",
                "disposition_by": "lead", "disposition_evidence": 0}
        p2 = run(mk_report(Path(td) / "r2", {**GOOD, "schema_version": 2, "checks": [bad2]}))
        assert p2.returncode == 1 and "disposition_evidence" in p2.stdout, p2.stdout


def test_verification_evidence_must_be_string() -> None:
    """M99：`verification.evidence` 也要非空字符串（同一对象里 `by` 已严、`evidence` 曾松）。

    该字段不喂关闭、不喂阻断判定（只作取证核验），所以这条是**口径分裂**修正，不是漏关修补；
    但「谁确认的、凭什么确认」与处置签字是同一类承重件，不该一侧严格一侧宽松。
    """
    with tempfile.TemporaryDirectory() as td:
        bad = {**GOOD["checks"][0], "level": "Minor",
               "verification": {"status": "confirmed", "by": "lead", "evidence": ["test green"]}}
        p = run(mk_report(Path(td), {**GOOD, "schema_version": 2, "checks": [bad]}))
        assert p.returncode == 1 and "verification" in p.stdout, p.stdout
        good = {**GOOD["checks"][0], "level": "Minor",
                "verification": {"status": "confirmed", "by": "lead", "evidence": "test green"}}
        p2 = run(mk_report(Path(td) / "r2", {**GOOD, "schema_version": 2, "checks": [good]}))
        assert p2.returncode == 0, p2.stdout


def test_escalation_approved_by_must_be_string() -> None:
    """M101：升级复议的拍板人 `approved_by` 同属签字类字段 ⇒ 数字不算拍板。"""
    with tempfile.TemporaryDirectory() as td:
        esc = {"to": "architecture-team", "reason": "争议边界需拍板", "approved_by": 123}
        p = run(mk_report(Path(td), {**GOOD, "schema_version": 2, "round": 4, "escalation": esc}))
        assert p.returncode == 1 and "approved_by" in p.stdout, p.stdout
        esc2 = {**esc, "approved_by": "lead"}
        p2 = run(mk_report(Path(td) / "r2", {**GOOD, "schema_version": 2, "round": 4,
                                             "escalation": esc2}))
        assert p2.returncode == 0, p2.stdout


def test_blocking_critical_requires_string_signer() -> None:
    """M100：`is_blocking_critical` 的签字判据必须走 `signed_str`（内核级钉子）。

    CLI 侧钉不住这一层：非字符串签字会先被形状判据（M48）拒掉，所以把本函数退回
    `bool(str(...))` 宽松版，当时 `test_review_report.py` + 另两个文件共 131 条仍全绿
    （只读评审第 2 轮 Major 实测；现三文件 138 条中本钉单红）。这里对内核直接断言，把两层解耦：

      - `disposition_by: 123` + 取证文本 ⇒ **仍阻断**（数字不是签名）；
      - `disposition_by: "lead"` ⇒ 不阻断（反向对照，防把正常收口刷红）。
    """
    sys.path.insert(0, str(PKG_ROOT / "_support"))
    try:
        import review_policy as rp
    finally:
        sys.path.pop(0)
    fake = {"level": "Critical", "disposition": "false_positive", "disposition_by": 123,
            "disposition_evidence": "复核记录见 EVIDENCE.md"}
    real = {**fake, "disposition_by": "lead"}
    assert rp.is_blocking_critical(fake, schema_version=2) is True
    assert rp.is_blocking_critical(real, schema_version=2) is False
    assert rp.calculate_status([fake], schema_version=2) == "FAIL"
    # 合法签字只是「不阻断」，Critical 仍把下限抬到 WARN —— 不得静默 PASS
    assert rp.calculate_status([real], schema_version=2) == "WARN"


# ---- v4 内容封口（RFC-20261103-01；M165 属本文件）-------------------------------

def _scope_manifest(root: Path, rel: str = "a.ts") -> tuple[dict, Path]:
    p = root / rel
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    files = [{"path": rel, "status": "M", "sha256": sha,
              "size": p.stat().st_size, "hash_mode": "sha256"}]
    digest = hashlib.sha256(f"{rel}\0{sha}\0sha256".encode("utf-8")).hexdigest()
    manifest = {"schema_version": 1, "generated_at": "2026-11-03T00:00:00+08:00",
                "root": str(root.resolve()), "base": "", "head": "",
                "files": files, "scope_sha256": digest}
    path = root / "scope-manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest, path


def _v4_report(root: Path, manifest: dict, **over) -> Path:
    payload = {**GOOD, "root": str(root.resolve()), "schema_version": 4,
               "expected": 1, "reviewed": 1, "checks": [],
               "review_scope": {"manifest": "scope-manifest.json",
                                "sha256": manifest["scope_sha256"],
                                "files": manifest["files"]}}
    payload.update(over)
    return mk_report(root, payload)


def test_v4_fresh_scope_passes() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.ts").write_text("one\n", encoding="utf-8")
        manifest, path = _scope_manifest(root)
        d = _v4_report(root, manifest)
        p = run(d, ["--scope-manifest", str(path)])
        assert p.returncode == 0, p.stdout
        assert "[PASS] 评审范围内容封口（v4）" in p.stdout


def test_v4_stale_scope_fails() -> None:
    """M165：摘掉校验器复算 ⇒ 本用例红（评审后改一字节必须 FAIL）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.ts").write_text("one\n", encoding="utf-8")
        manifest, path = _scope_manifest(root)
        d = _v4_report(root, manifest)
        (root / "a.ts").write_text("two\n", encoding="utf-8")
        p = run(d, ["--scope-manifest", str(path)])
        assert p.returncode == 1 and "内容已变化" in p.stdout, p.stdout


def test_v4_without_manifest_warns_not_fails() -> None:
    """只对本轮新产出报告复算：旧轮/手工复验不带 manifest ⇒ WARN，不追溯判红。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.ts").write_text("one\n", encoding="utf-8")
        manifest, _path = _scope_manifest(root)
        p = run(_v4_report(root, manifest))
        assert p.returncode == 0 and "未复算" in p.stdout, p.stdout


def test_v4_missing_review_scope_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.ts").write_text("one\n", encoding="utf-8")
        payload = {**GOOD, "root": str(root.resolve()), "schema_version": 4,
                   "expected": 1, "reviewed": 1, "checks": []}
        p = run(mk_report(root, payload))
        assert p.returncode == 1 and "review_scope" in p.stdout, p.stdout


def test_v4_scope_count_mismatch_fails() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.ts").write_text("one\n", encoding="utf-8")
        manifest, path = _scope_manifest(root)
        p = run(_v4_report(root, manifest, reviewed=2, expected=2),
                ["--scope-manifest", str(path)])
        assert p.returncode == 1 and "scope 必须覆盖实审集" in p.stdout, p.stdout


def test_v3_report_ignores_scope_manifest() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.ts").write_text("one\n", encoding="utf-8")
        manifest, path = _scope_manifest(root)
        payload = {**GOOD, "root": str(root.resolve()), "schema_version": 3}
        p = run(mk_report(root, payload), ["--scope-manifest", str(path)])
        assert p.returncode == 0 and "schema < 4" in p.stdout, p.stdout


def test_premise_optional_fields_shape() -> None:
    """S2 形状钉（RFC-20261104-01）：`premise` / `discriminating_check` 出现时校验形状。

    合法 ⇒ 通过；空串 / 非对象 / 缺 `command` / 缺 `expected_if_false` ⇒ FAIL。
    字段是**可选**的：不带这两个键的正常 finding 不受影响（正例由 `GOOD` 提供）。
    """
    with tempfile.TemporaryDirectory() as td:
        ok = {**GOOD, "schema_version": 2,
              "checks": [{**GOOD["checks"][0],
                          "premise": "共同前提：只按 completed 计实审数",
                          "discriminating_check": {"command": "pytest -q",
                                                   "expected_if_false": "reviewed 变 6/6"}}]}
        p = run(mk_report(Path(td), ok))
        assert p.returncode == 0, p.stdout
    bad_cases = [
        ({"premise": ""}, "premise"),
        ({"premise": 3}, "premise"),
        ({"discriminating_check": []}, "discriminating_check"),
        ({"discriminating_check": {"expected_if_false": "x"}}, "command"),
        ({"discriminating_check": {"command": "x"}}, "expected_if_false"),
        ({"discriminating_check": {"command": "x", "expected_if_false": "y",
                                   "observation": ""}}, "observation"),
    ]
    for extra, needle in bad_cases:
        with tempfile.TemporaryDirectory() as td:
            payload = {**GOOD, "schema_version": 2,
                       "checks": [{**GOOD["checks"][0], **extra}]}
            p = run(mk_report(Path(td), payload))
            assert p.returncode == 1 and needle in p.stdout, (extra, p.stdout)
