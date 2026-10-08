#!/usr/bin/env python3
"""独立审查报告对账器 —— `review.json` ⇔ `shared/independent-review.md` §3/§4/§6 形态与「应审 N / 实审 M」。

**病根**（`3509 §B112` 残留清偿 / `§B100` 静默少审同族，2026-10-06）：契约写死了报告形态
（§3 双份留痕 + §4 状态映射写死 + §6 第 8 条应审/实审对账）但**零机器判据**——实测存量 4 份
报告 4 种形态（缺 ok / 缺 unit / 缺 round / 缺对账字段各有一），形态漂移无门。本器 = **单份
报告的落盘门**：实例 ⑤ 经 `scripts/cli_review_convert.py` 产出后再验一道；①②④ 聚合器产物
落盘后同验（报告落盘当轮必跑，`shared/closeout.md` 触发表）。

判据（全部可机器判）：

  1. `review.json` 存在且可解析（**报告不存在 = 未审，不是通过**）；`README.md` 存在（双份留痕，骨架 §2.5）。
  2. §3 必备键齐且类型对：`ok`(bool) / `status` / `root` / `scope` / `unit`(非空) / `round`(int ≥1) / `checks`[] / `other`[]。
  3. 分级闭集：`checks[].level ∈ {Critical, Major, Minor}`；每条 finding 必带非空 `rollback`（骨架 §2.4）。
  4. 状态映射复算（§3 写死 + §6 第 8 条 WARN 下限，cli_review_convert 同规则）：有 Critical ⇒
     FAIL；否则有 Major 或 M<N 或 budget_exceeded ⇒ WARN；否则 PASS；且 `ok == (status != "FAIL")`。
  5. 应审/实审对账（§6 第 8 条）：`expected` / `reviewed` **必填**（单审查者实例记 1/1）——
     缺一或缺二 ⇒ FAIL（缺权威输入不得给「通过」）；`reviewed < expected` 或 `budget_exceeded` ⇒ WARN。

用法：

    python3 .atlas/scripts/validate_review_report.py --dir product/reviews/<日期>-<范围>

退出码：FAIL ⇒ 1；WARN ⇒ 0（与校验器同源：WARN 不置红但报告行可见）。纯标准库。

**盲区（显式）**：**不回扫存量历史报告**（形态契约 2026-10-06 起对新落盘报告生效——存量 4 份
形态各异，回扫 = 永久红 ⇒ 静音门）；`findings/<unit>.r<round>.json` 逐单元文件不在此判
（聚合器职责，§4）；审查结论的**语义对错**（归审查者与校准环）；「该审的对象是否真的审了」
的 N 口径（归各实例的 fan-out 契约）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LEVELS = ("Critical", "Major", "Minor")
# §3 必备键 → 期望类型（bool 必须先于 int 判——Python 里 bool 是 int 子类）
REQUIRED_KEYS: list[tuple[str, type]] = [
    ("ok", bool), ("status", str), ("root", str), ("scope", str),
    ("unit", str), ("round", int), ("checks", list), ("other", list),
]


class Result:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, check: str, level: str, detail: str = "") -> None:
        self.checks.append({"check": check, "level": level, "detail": detail})

    @property
    def status(self) -> str:
        levels = {c["level"] for c in self.checks}
        if "FAIL" in levels:
            return "FAIL"
        return "WARN" if "WARN" in levels else "PASS"


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate_report(d: Path) -> Result:
    res = Result()
    rj = d / "review.json"
    if not rj.is_file():
        res.add("review.json 可读", "FAIL", f"{rj} 不存在 —— 报告不存在 = 未审（不是通过）")
        return res
    try:
        data = json.loads(rj.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        res.add("review.json 可读", "FAIL", f"解析失败：{e}")
        return res
    if not isinstance(data, dict):
        res.add("review.json 可读", "FAIL", "顶层不是 JSON 对象")
        return res
    res.add("review.json 可读", "PASS", str(rj))

    has_readme = (d / "README.md").is_file()
    res.add("双份留痕（骨架 §2.5）", "PASS" if has_readme else "FAIL",
            "README.md 与 review.json 双份" if has_readme else "缺 README.md（人读侧）")

    bad: list[str] = []
    for k, t in REQUIRED_KEYS:
        v = data.get(k)
        if v is None or not isinstance(v, t) or (t is int and isinstance(v, bool)):
            bad.append(f"`{k}` 缺失或类型非 {t.__name__}")
        elif t is str and not str(v).strip():
            bad.append(f"`{k}` 为空")
    r = data.get("round")
    if _is_int(r) and r < 1:
        bad.append("`round` 必须 ≥ 1")
    res.add("契约形态（§3 必备键）", "FAIL" if bad else "PASS",
            "；".join(bad) if bad else f"{len(REQUIRED_KEYS)} 键齐且类型对")

    checks = data.get("checks") if isinstance(data.get("checks"), list) else []
    bad_lv: list[str] = []
    for i, c in enumerate(checks):
        if not isinstance(c, dict):
            bad_lv.append(f"checks[{i}] 不是对象")
            continue
        if c.get("level") not in LEVELS:
            bad_lv.append(f"checks[{i}].level={c.get('level')!r} 不在闭集")
        rb = c.get("rollback")
        if not (isinstance(rb, str) and rb.strip()):
            bad_lv.append(f"checks[{i}] 缺非空 rollback（骨架 §2.4）")
    res.add("分级闭集 + 回退环", "FAIL" if bad_lv else "PASS",
            ("；".join(bad_lv))[:200] if bad_lv else f"{len(checks)} 条 finding 闭集与回退环齐")

    lv_set = {c.get("level") for c in checks if isinstance(c, dict)}
    # 应审/实审先解析（映射复算要把 §6 第 8 条的 WARN 下限算进去 —— cli_review_convert 同规则：
    # Critical ⇒ FAIL；否则 Major 或 M<N 或预算击穿 ⇒ WARN；否则 PASS）
    exp, rev = data.get("expected"), data.get("reviewed")
    warn_floor = (data.get("budget_exceeded") is True) or (
        _is_int(exp) and _is_int(rev) and rev < exp)
    expect = "FAIL" if "Critical" in lv_set else ("WARN" if ("Major" in lv_set or warn_floor) else "PASS")
    st, ok = data.get("status"), data.get("ok")
    map_bad: list[str] = []
    if st != expect:
        map_bad.append(f"status={st!r} ≠ 映射复算 {expect}（§3 写死 + §6 第 8 条下限）")
    if ok is not (expect != "FAIL"):
        map_bad.append(f"ok={ok!r} ≠ (status != FAIL)")
    res.add("状态映射复算（§3 写死 + §6 下限）", "FAIL" if map_bad else "PASS",
            "；".join(map_bad) if map_bad else f"status={expect} 与分级 / 对账下限一致")

    if exp is None and rev is None:
        res.add("应审/实审对账（§6 第 8 条）", "FAIL",
                "缺 `expected` / `reviewed` —— 缺权威输入不得给「通过」（单审查者实例记 1/1）")
    elif (exp is None) != (rev is None):
        res.add("应审/实审对账（§6 第 8 条）", "FAIL",
                f"expected={exp!r} / reviewed={rev!r} 只有一半 —— 对账不可判")
    elif not (_is_int(exp) and _is_int(rev)):
        res.add("应审/实审对账（§6 第 8 条）", "FAIL",
                f"expected={exp!r} / reviewed={rev!r} 必须是整数")
    elif rev < exp:
        res.add("应审/实审对账（§6 第 8 条）", "WARN",
                f"应审 {exp} / 实审 {rev} —— 少审 M<N，查静默跳过（§6 第 8 条）")
    elif data.get("budget_exceeded"):
        res.add("应审/实审对账（§6 第 8 条）", "WARN",
                "budget_exceeded —— 预算击穿（§6 第 6 条熔断），结论覆盖面受限")
    else:
        res.add("应审/实审对账（§6 第 8 条）", "PASS", f"应审 {exp} / 实审 {rev}")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="审查报告目录（含 review.json / README.md）")
    args = ap.parse_args()
    d = Path(args.dir)
    if not d.is_dir():
        print(f"ERROR: 报告目录不存在：{d}", file=sys.stderr)
        return 2
    res = validate_report(d)
    print(f"validate_review_report @ {d}")
    for c in res.checks:
        line = f"  [{c['level']:<4}] {c['check']}"
        if c["detail"] and c["level"] != "PASS":
            line += f" —— {c['detail']}"
        print(line)
    print(res.status)
    return 1 if res.status == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
