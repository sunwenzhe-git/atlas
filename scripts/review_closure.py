#!/usr/bin/env python3
"""跨轮 finding 闭环台账（WARN 观察面，非门）。

**问题**：`findings/<unit>.r<round>.json` 保存了每轮的原始结论，但报告形态门只看最新
`review.json`；上一轮未关闭的 Critical/Major 如果在新一轮既没有被同指纹重报、也没有显式
处置，就会被静默丢掉。契约又明确「同一问题跨轮不得重复贴」，所以不能用「强制重报」来补。

**解决方式**：本器读取报告目录的多轮单元文件，对比最新轮的 `checks` 与 `review.json` 的
`resolves`：
  - 最新轮同指纹仍在（open）⇒ `carried`（仍可见，不告警）；
  - 最新轮同指纹已带签字+取证关闭，或 `resolves` 声明关闭 ⇒ `resolved`；
  - 二者都没有 ⇒ `unaccounted`，WARN。
关闭是否成立按**上一轮的级别**从严判：prior Critical 被新一轮降级成 Major 再挂
`intentional`（无签字取证）不算关闭；即便仍按 open 重报，「Critical 变低级」也单独记 WARN。
`findings/` 里出现非本 unit 的孤儿文件也判 WARN——跨轮换 unit 名会让闭环义务凭空清零。
不进入 `atlas_check`，不建 FAIL 门；输入形状错误才 exit 2。

用法：
    python3 .atlas/scripts/review_closure.py --dir product/reviews/<日期>-<范围>

输出：报告目录下 `closure.json` + 一行摘要；退出码 0（PASS/WARN/SKIP），2（输入错误）。
纯标准库。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))
from _support.siblings import load_module  # noqa: E402

review_policy = load_module("review_policy")

CLOSED = ("fixed", "false_positive", "intentional", "ignored")
EVIDENCE_REQUIRED = ("fixed", "false_positive")


def die(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 2


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(die(f"读 {path} 失败：{exc}"))
    if not isinstance(data, dict):
        raise SystemExit(die(f"{path} 顶层不是 JSON 对象"))
    return data


def fingerprint(check: dict) -> str:
    fp = check.get("fingerprint")
    if isinstance(fp, str) and fp.strip():
        return fp.strip()
    return review_policy.compute_fingerprint(
        str(check.get("target") or ""), str(check.get("check") or ""),
        str(check.get("detail") or ""))


def has_evidence(check: dict) -> bool:
    return bool(str(check.get("disposition_by") or "").strip()) and bool(
        str(check.get("disposition_evidence") or "").strip())


def state_of(check: dict, obligation_level: str | None = None) -> str:
    """open / closed；Critical 的 intentional/ignored 不视为关闭（仍阻断）。

    `obligation_level` 传入**上一轮**该指纹的级别：闭环义务按最严的级别判，否则
    「新一轮把 Critical 降级成 Major + intentional（无签字）」即可绕开签字取证要求。
    """
    disp = str(check.get("disposition") or "").strip()
    if disp in EVIDENCE_REQUIRED:
        return "closed" if has_evidence(check) else "open"
    if disp in ("intentional", "ignored"):
        level = obligation_level or check.get("level")
        return "closed" if level != "Critical" else "open"
    return "open"


def relevant(check: dict) -> bool:
    if not isinstance(check, dict) or check.get("level") not in ("Critical", "Major"):
        return False
    if check.get("pre_existing") is True:
        return False
    return state_of(check) != "closed"


def load_prior_rounds(report_dir: Path, unit: str,
                      latest_round: int) -> tuple[list[tuple[int, Path, dict]], list[str]]:
    """上一轮单元文件 + **孤儿文件**（`findings/` 里不属于本 unit 的 json）。

    孤儿不得静默跳过：跨轮 `--unit` 改名（或一个目录塞了多个 unit）会让闭环义务凭空清零，
    正是本器要治的「悄悄变绿」。孤儿 ⇒ 调用侧抬 WARN。
    """
    findings = report_dir / "findings"
    if not findings.is_dir():
        return [], []
    rounds: list[tuple[int, Path, dict]] = []
    orphans: list[str] = []
    seen: dict[int, Path] = {}
    for path in sorted(findings.glob("*.json")):
        name = path.stem
        if name == unit:
            rnd = 1
        elif name.startswith(unit + ".r") and name[len(unit) + 2:].isdigit():
            rnd = int(name[len(unit) + 2:])
        else:
            orphans.append(path.name)
            continue
        data = load_json(path)
        if str(data.get("unit") or "") not in ("", unit):
            raise SystemExit(die(f"{path} 的 unit 与报告 unit={unit} 不一致"))
        if isinstance(data.get("round"), int) and data["round"] != rnd:
            raise SystemExit(die(f"{path} 的 round 与文件名 {rnd} 不一致"))
        if rnd in seen:
            raise SystemExit(die(f"unit={unit} round={rnd} 存在重复单元文件：{seen[rnd]} / {path}"))
        seen[rnd] = path
        if rnd < latest_round:
            rounds.append((rnd, path, data))
    return sorted(rounds, key=lambda item: item[0]), orphans


def parse_resolves(data: dict, prior_fps: set[str]) -> tuple[list[dict], list[str], list[str]]:
    raw = data.get("resolves")
    if raw is None:
        return [], [], []
    if not isinstance(raw, list):
        raise SystemExit(die("`resolves` 必须为数组"))
    resolved: list[dict] = []
    unknown: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SystemExit(die(f"resolves[{i}] 必须为对象"))
        fp = item.get("fingerprint")
        status = item.get("status")
        if not (isinstance(fp, str) and fp.strip()):
            raise SystemExit(die(f"resolves[{i}].fingerprint 必须为非空字符串"))
        if status not in CLOSED:
            raise SystemExit(die(f"resolves[{i}].status={status!r} 不在闭集 {CLOSED}"))
        if fp in seen:
            raise SystemExit(die(f"resolves 出现重复 fingerprint：{fp}"))
        seen.add(fp)
        if "round" in item and (not isinstance(item["round"], int) or item["round"] < 1):
            raise SystemExit(die(f"resolves[{i}].round 必须为 ≥1 的整数"))
        if status in EVIDENCE_REQUIRED and not (
                str(item.get("by") or "").strip() and str(item.get("evidence") or "").strip()):
            invalid.append(fp)
            continue
        if fp not in prior_fps:
            unknown.append(fp)
            continue
        resolved.append({"fingerprint": fp, "status": status,
                         "by": str(item.get("by") or ""), "evidence": str(item.get("evidence") or "")})
    return resolved, unknown, invalid


def base_result(unit: str, latest_round: int, rounds: list[int],
                warnings: list[str], status: str) -> dict:
    return {"schema_version": 1, "unit": unit, "latest_round": latest_round,
            "rounds": rounds, "prior_relevant": 0,
            "carried": [], "resolved": [], "unaccounted": [],
            "level_downgraded": [], "unknown_resolves": [], "invalid_resolves": [],
            "warnings": warnings, "status": status}


def orphan_warning(orphans: list[str]) -> str:
    return (f"findings/ 有 {len(orphans)} 个非本 unit 的单元文件未纳入闭环"
            f"（跨轮 unit 改名或一目录多 unit）：{orphans[:5]}")


def run(report_dir: Path) -> tuple[str, dict]:
    root = load_json(report_dir / "review.json")
    unit = root.get("unit")
    latest_round = root.get("round")
    if not (isinstance(unit, str) and unit.strip()):
        raise SystemExit(die("review.json 缺 unit"))
    if not isinstance(latest_round, int) or latest_round < 1:
        raise SystemExit(die("review.json 缺有效 round"))
    if latest_round < 2:
        return "SKIP", base_result(unit, latest_round, [latest_round],
                                   ["少于 2 轮，无法做跨轮闭环"], "SKIP")

    prior_rounds, orphans = load_prior_rounds(report_dir, unit, latest_round)
    if not prior_rounds:
        if orphans:
            return "WARN", base_result(unit, latest_round, [latest_round],
                                       [orphan_warning(orphans)], "WARN")
        return "SKIP", base_result(unit, latest_round, [latest_round],
                                   ["没有上一轮 unit 文件"], "SKIP")

    prior: list[dict] = []
    prior_fps: set[str] = set()
    warnings: list[str] = [orphan_warning(orphans)] if orphans else []
    for rnd, path, data in prior_rounds:
        checks = data.get("checks")
        if not isinstance(checks, list):
            raise SystemExit(die(f"{path} 缺 checks[]"))
        for c in checks:
            if not isinstance(c, dict) or not relevant(c):
                continue
            fp = fingerprint(c)
            if fp in prior_fps:
                warnings.append(f"prior fingerprint 重复：{fp}（round {rnd}）")
                continue
            prior_fps.add(fp)
            prior.append({"prior_round": rnd, "fingerprint": fp,
                          "level": c.get("level"), "target": c.get("target")})

    latest_checks = root.get("checks") if isinstance(root.get("checks"), list) else []
    latest_by_fp: dict[str, list[dict]] = {}
    for c in latest_checks:
        if isinstance(c, dict):
            latest_by_fp.setdefault(fingerprint(c), []).append(c)

    resolves, unknown_resolves, invalid_resolves = parse_resolves(root, prior_fps)
    resolved_by_fp = {r["fingerprint"]: r for r in resolves}
    carried: list[dict] = []
    resolved: list[dict] = []
    unaccounted: list[dict] = []
    downgraded: list[dict] = []
    for item in prior:
        fp = item["fingerprint"]
        latest = latest_by_fp.get(fp)
        if latest:
            if any(state_of(c, item.get("level")) == "closed" for c in latest):
                resolved.append({**item, "via": "re-reported", "status": "closed"})
            else:
                carried.append(item)
                if item.get("level") == "Critical" and all(
                        c.get("level") != "Critical" for c in latest):
                    downgraded.append({**item, "latest_level": latest[0].get("level")})
                    warnings.append(
                        f"prior Critical（round {item['prior_round']} `{item.get('target')}`）"
                        f"新一轮降级为 {latest[0].get('level')!r} —— 仍按未关闭跟踪")
            continue
        if fp in resolved_by_fp:
            resolve = resolved_by_fp[fp]
            if item.get("level") == "Critical" and resolve["status"] in ("intentional", "ignored"):
                if fp not in invalid_resolves:
                    invalid_resolves.append(fp)
                unaccounted.append(item)
            else:
                resolved.append({**item, "via": "resolves", "status": resolve["status"]})
        else:
            unaccounted.append(item)

    status = "WARN" if (unaccounted or unknown_resolves or invalid_resolves
                        or orphans or downgraded) else "PASS"
    result = {"schema_version": 1, "unit": unit, "latest_round": latest_round,
              "rounds": [r for r, _, _ in prior_rounds] + [latest_round],
              "prior_relevant": len(prior), "carried": carried, "resolved": resolved,
              "unaccounted": unaccounted, "level_downgraded": downgraded,
              "unknown_resolves": unknown_resolves,
              "invalid_resolves": invalid_resolves, "warnings": warnings, "status": status}
    return status, result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="审查报告目录（含 review.json / findings/）")
    args = ap.parse_args()
    report_dir = Path(args.dir)
    if not report_dir.is_dir():
        print(f"ERROR: 报告目录不存在：{report_dir}", file=sys.stderr)
        return 2
    status, result = run(report_dir)
    (report_dir / "closure.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"review_closure @ {report_dir}   {status}   rounds {len(result['rounds'])} "
          f"prior {result['prior_relevant']} carried {len(result['carried'])} "
          f"resolved {len(result['resolved'])} unaccounted {len(result['unaccounted'])} "
          f"unknown {len(result['unknown_resolves'])} invalid {len(result['invalid_resolves'])} "
          f"warnings {len(result['warnings'])}")
    for w in result["warnings"]:
        print(f"  · {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
