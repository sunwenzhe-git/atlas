#!/usr/bin/env python3
"""atlas 共享内核 —— 独立审查报告策略与状态判定（D129）。

用于 `scripts/validate_review_report.py`（对账校验门）、
`scripts/cli_review_convert.py`（CLI 转换器）以及
`scripts/gen_e2e_scripts.py::review_report_status`（生成器阻断判断）。
纯标准库，无外部依赖。
"""
from __future__ import annotations

import hashlib
import re

LEVELS = ("Critical", "Major", "Minor")
DISPOSITIONS = ("open", "fixed", "false_positive", "intentional", "ignored")
VERIFICATION_STATUSES = ("confirmed", "rejected", "inconclusive")

_LINE_STRIP_RE = re.compile(r":\d+(?:-\d+)?$")


def clean_target_file(target: str) -> str:
    """从目标定位（如 `foo/bar.ts:42` 或 `foo/bar.ts:12-15`）剥除行号/行区间，保留文件路径。"""
    s = str(target or "").strip()
    return _LINE_STRIP_RE.sub("", s)


def compute_fingerprint(target: str, check: str, detail: str) -> str:
    """计算 finding 去重指纹（16 字符 hex）。

    基于文件路径（排除易漂移的行号）+ 检查类别 + 核心摘要首行计算哈希。
    """
    clean_tgt = clean_target_file(target)
    first_line = str(detail or "").strip().splitlines()[0] if detail else ""
    key = f"{clean_tgt}|{check.strip()}|{first_line.strip()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def is_blocking_critical(check: dict, schema_version: int = 2) -> bool:
    """判定某条 check 是否构成阻断性 Critical。

    v1 报告（schema_version < 2）：**任一 Critical 即阻断**（旧「写死」语义，
    不接受 pre_existing / disposition 豁免——否则 `--schema-version 1` 会成绕过后门）。

    v2 报告：
      - 非 Critical ⇒ 不阻断
      - pre_existing=True（存量代码问题）⇒ 不阻断（状态下限抬为 WARN，仍可见）
      - disposition 为 fixed 或带签字+取证的 false_positive ⇒ 不阻断
    """
    if not isinstance(check, dict) or check.get("level") != "Critical":
        return False
    if schema_version < 2:
        return True
    if check.get("pre_existing") is True:
        return False
    disp = check.get("disposition")
    if disp in ("fixed", "false_positive"):
        has_signer = bool(str(check.get("disposition_by") or "").strip())
        has_evidence = bool(str(check.get("disposition_evidence") or "").strip())
        if has_signer and has_evidence:
            return False
    return True


def calculate_status(checks: list[dict], warn_floor: bool = False,
                     schema_version: int = 2) -> str:
    """根据 findings 列表和告警下限标志计算最终 status（FAIL / WARN / PASS）。

    状态映射规则（§3 写死 + §6 下限 + D129 处置）：
      - 存在阻断性 Critical ⇒ FAIL
      - 存在存量 Critical、Major、或 warn_floor 为 True（M<N、预算熔断、executed=False 等）⇒ WARN
      - 否则 PASS
    """
    valid_checks = [c for c in checks if isinstance(c, dict)]
    if any(is_blocking_critical(c, schema_version=schema_version) for c in valid_checks):
        return "FAIL"

    has_any_crit = any(c.get("level") == "Critical" for c in valid_checks)
    has_major = any(c.get("level") == "Major" for c in valid_checks)
    if has_any_crit or has_major or warn_floor:
        return "WARN"
    return "PASS"


def validate_v2_finding(c: dict, idx: int) -> list[str]:
    """校验 v2 单条 finding 字段形态与合法性。"""
    errs: list[str] = []
    if "fingerprint" in c:
        fp = c["fingerprint"]
        if not (isinstance(fp, str) and fp.strip()):
            errs.append(f"checks[{idx}].fingerprint 必须为非空字符串")
    if "pre_existing" in c:
        if not isinstance(c["pre_existing"], bool):
            errs.append(f"checks[{idx}].pre_existing 必须为 bool")
    if "disposition" in c:
        disp = c["disposition"]
        if disp not in DISPOSITIONS:
            errs.append(f"checks[{idx}].disposition={disp!r} 不在闭集 {DISPOSITIONS}")
        elif disp in ("fixed", "false_positive"):
            if not str(c.get("disposition_by") or "").strip():
                errs.append(f"checks[{idx}].disposition={disp} 必须带非空 disposition_by 签名")
            if not str(c.get("disposition_evidence") or "").strip():
                errs.append(f"checks[{idx}].disposition={disp} 必须带非空 disposition_evidence 取证")
    if "verification" in c:
        v = c["verification"]
        if not isinstance(v, dict):
            errs.append(f"checks[{idx}].verification 必须为对象")
        else:
            st = v.get("status")
            if st not in VERIFICATION_STATUSES:
                errs.append(f"checks[{idx}].verification.status={st!r} 不在闭集 {VERIFICATION_STATUSES}")
            if not str(v.get("by") or "").strip():
                errs.append(f"checks[{idx}].verification 必须带非空 by")
            if not str(v.get("evidence") or "").strip():
                errs.append(f"checks[{idx}].verification 必须带非空 evidence")
    return errs


def validate_v2_report_fields(data: dict) -> list[str]:
    """校验 v2 报告级扩展字段与轮次收敛规则。"""
    errs: list[str] = []
    r = data.get("round")
    if isinstance(r, int) and r >= 4:
        esc = data.get("escalation")
        if not isinstance(esc, dict) or not str(esc.get("to") or "").strip() or not str(esc.get("reason") or "").strip():
            errs.append(f"round={r} 达到或超过 4 轮收敛上限，必须登记有效 escalation（需含 to 与 reason）")
    if "delta_only" in data:
        if not isinstance(data["delta_only"], bool):
            errs.append("`delta_only` 必须为 bool")
        elif data["delta_only"] is True:
            rf = data.get("reviewed_files")
            if not isinstance(rf, list) or not rf:
                errs.append("`delta_only=true` 时必须提供非空 `reviewed_files` 列表")
    if "escalation" in data and data["escalation"] is not None:
        esc = data["escalation"]
        if not isinstance(esc, dict):
            errs.append("`escalation` 若存在必须为对象")
        elif "approved_by" in esc and not str(esc.get("approved_by") or "").strip():
            errs.append("`escalation.approved_by` 若存在必须为非空字符串")
    return errs
