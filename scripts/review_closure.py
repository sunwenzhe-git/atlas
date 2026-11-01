#!/usr/bin/env python3
"""跨轮 finding 闭环台账（WARN 观察面，非门）。

**问题**：`findings/<unit>.r<round>.json` 保存了每轮的原始结论，但报告形态门只看最新
`review.json`；上一轮未关闭的 Critical/Major 如果在新一轮既没有被同指纹重报、也没有显式
处置，就会被静默丢掉。契约又明确「同一问题跨轮不得重复贴」，所以不能用「强制重报」来补。

**解决方式**：本器读取报告目录的多轮单元文件，把每轮的 `checks` 与 `resolves` 都当作证据，
按「该指纹最后一次证据」判定：
  - 最新轮同指纹仍在（open）⇒ `carried`（仍可见，不告警）；
  - 最新轮同指纹已带签字+取证关闭，或 `resolves` 声明关闭 ⇒ `resolved`；
  - 最新轮没再提，但**任一中间轮**在最后一次 open 之后正式关闭过 ⇒ `resolved`
    （`via` 记 `resolves@rN` / `re-reported-closed@rN`）——关闭是历史事实，不要求每轮重贴；
  - 都没有 ⇒ `unaccounted`，WARN。
中间轮的声明同样从严：`fixed`/`false_positive` 要 `by`+`evidence`，Critical 不接受
`intentional`/`ignored`，且声明轮次必须**晚于**最后一次 open 的轮次（历史不能倒着关）。
关闭是否成立按**上一轮的级别**判：prior Critical 被新一轮降级成 Major 再挂
`intentional`（无签字取证）不算关闭；即便仍按 open 重报，「Critical 变低级」也单独记 WARN。
`findings/` 里出现非本 unit 的孤儿文件也判 WARN——跨轮换 unit 名会让闭环义务凭空清零。
不进入 `atlas_check`，不建 FAIL 门；输入形状错误才 exit 2。

用法：
    python3 .atlas/scripts/review_closure.py --dir product/reviews/<日期>-<范围>
        [--emit-skeleton resolves-skeleton.json]   # 把 unaccounted 义务打成待填骨架（纯输出）

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

# 闭集与取证面单源在 _support/review_policy.py（与转换器的 --resolves 共用同一判据）
CLOSED = review_policy.RESOLVES_STATUSES
EVIDENCE_REQUIRED = review_policy.RESOLVES_EVIDENCE_REQUIRED


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

    级别取 `obligation_level`（该问题在**所有出现里最严的一档**）与本条 `level` 的
    较严者：只按义务首现级别判 ⇒ `Major 升级为 Critical` 一侧可免签关掉；只按本轮级别判
    ⇒ `Critical 降级为 Major` 一侧可免签关掉（`43dca7f` 修的是后者，本批补上前者）。
    """
    disp = str(check.get("disposition") or "").strip()
    if disp in EVIDENCE_REQUIRED:
        return "closed" if has_evidence(check) else "open"
    if disp in ("intentional", "ignored"):
        level = review_policy.worst_level(obligation_level, check.get("level"))
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


def round_declares(path: Path, data: dict) -> tuple[list[dict], list[str]]:
    """某一轮文件里的 `resolves` 声明 + 形状错误列表。

    中间轮**不因坏形状而 exit 2**：`(unit, round)` 文件按契约不得覆盖，历史里一个写歪的
    `status` 会把闭环永久钉死。形状错 ⇒ 该条不作关闭证据 + 记入 warnings 并抬 WARN
    （响亮但不阻断）。最新轮仍走 exit 2（那是操作者本轮自己要落的声明）。
    """
    raw = data.get("resolves")
    errs = review_policy.resolves_shape_errors(raw, f"{path.name} 的 resolves")
    if errs:
        return [], errs
    return list(raw or []), []


def declares_close(entry: dict, obligation_level: str | None) -> bool:
    """一条 `resolves` 声明是否构成关闭：取证要求 + Critical 不接受 intentional/ignored。

    `obligation_level` 是义务在**所有出现里最严的一档**（见 `worst_level`），两个方向都挡住。
    """
    status = entry.get("status")
    if status not in CLOSED:
        return False
    if status in EVIDENCE_REQUIRED:
        return bool(str(entry.get("by") or "").strip()
                    and str(entry.get("evidence") or "").strip())
    return obligation_level != "Critical"


def last_close(events: list[tuple[int, str, dict]], obligation: dict) -> dict | None:
    """闭合按「该指纹最后一次证据」判：中间轮关过、更晚一轮又 open ⇒ 早先关闭不作数。

    返回 `{via, status, declared_in_round}`，其中轮次必须晚于最后一次 open 的轮次。
    """
    level = obligation.get("level")
    last_open = obligation["prior_round"]
    best: tuple[int, str, dict] | None = None
    for rnd, kind, entry in events:
        closed = (state_of(entry, level) == "closed") if kind == "check" \
            else declares_close(entry, level)
        if closed:
            if best is None or rnd >= best[0]:
                best = (rnd, kind, entry)
        elif kind == "check":
            last_open = max(last_open, rnd)
    if best is None or best[0] <= last_open:
        return None
    via = "re-reported-closed" if best[1] == "check" else "resolves"
    entry = best[2]
    return {"via": f"{via}@r{best[0]}", "declared_in_round": best[0],
            "status": str(entry.get("status") or entry.get("disposition") or "closed")}


def parse_resolves(data: dict, prior_fps: set[str]) -> tuple[list[dict], list[str], list[str]]:
    raw = data.get("resolves")
    errs = review_policy.resolves_shape_errors(raw, "resolves")
    if errs:
        raise SystemExit(die(errs[0]))
    resolved: list[dict] = []
    unknown: list[str] = []
    invalid: list[str] = []
    for item in (raw or []):
        fp = str(item.get("fingerprint") or "").strip()
        status = item.get("status")
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
    # fp → [(轮次, 证据类型, 原始条目)]：中间轮的关闭/重开都是证据，闭合按最后一次判
    events: dict[str, list[tuple[int, str, dict]]] = {}
    declared_earlier: set[str] = set()
    prior_shape_errors: list[str] = []
    for rnd, path, data in prior_rounds:
        checks = data.get("checks")
        if not isinstance(checks, list):
            raise SystemExit(die(f"{path} 缺 checks[]"))
        for c in checks:
            if not isinstance(c, dict):
                continue
            fp = fingerprint(c)
            events.setdefault(fp, []).append((rnd, "check", c))
            if not relevant(c):
                continue
            if fp in prior_fps:
                # 同一问题跨轮重复出现是常态（carried 形态）：义务级别取最严的一档，
                # 否则 Major 升级为 Critical 后可被无签字的 intentional 关掉
                for known in prior:
                    if known["fingerprint"] == fp:
                        known["level"] = review_policy.worst_level(known.get("level"), c.get("level"))
                warnings.append(f"prior fingerprint 重复：{fp}（round {rnd}）")
                continue
            prior_fps.add(fp)
            prior.append({"prior_round": rnd, "fingerprint": fp,
                          "level": c.get("level"), "target": c.get("target")})
        entries, errs = round_declares(path, data)
        prior_shape_errors.extend(errs)
        for entry in entries:
            fp = str(entry.get("fingerprint") or "").strip()
            events.setdefault(fp, []).append((rnd, "resolves", entry))
            declared_earlier.add(fp)

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
            closer = last_close(events.get(fp, []), item)
            if closer:
                resolved.append({**item, "via": closer["via"], "status": closer["status"],
                                 "declared_in_round": closer["declared_in_round"]})
            else:
                unaccounted.append(item)

    stale = sorted(declared_earlier - prior_fps)
    if stale:
        warnings.append(f"中间轮有 {len(stale)} 个指纹匹配不到任何义务"
                        f"（历史冗余声明或指纹写错）：{stale[:5]}")

    if prior_shape_errors:
        warnings.extend(f"中间轮 resolves 形状错（该条不作关闭证据）：{e}" for e in prior_shape_errors)
    status = "WARN" if (unaccounted or unknown_resolves or invalid_resolves or orphans
                        or downgraded or prior_shape_errors) else "PASS"
    result = {"schema_version": 1, "unit": unit, "latest_round": latest_round,
              "rounds": [r for r, _, _ in prior_rounds] + [latest_round],
              "prior_relevant": len(prior), "carried": carried, "resolved": resolved,
              "unaccounted": unaccounted, "level_downgraded": downgraded,
              "unknown_resolves": unknown_resolves,
              "invalid_resolves": invalid_resolves, "warnings": warnings, "status": status}
    return status, result


def skeleton(result: dict) -> dict:
    """待填骨架：`--resolves` 可直接吃这个形状（顶层 `by` 为整批缺省签字人）。"""
    return {"by": "",
            "resolves": [{"fingerprint": u["fingerprint"], "status": "", "by": "", "evidence": "",
                          "prior_round": u["prior_round"], "target": u.get("target")}
                         for u in result["unaccounted"]]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="审查报告目录（含 review.json / findings/）")
    ap.add_argument("--emit-skeleton", metavar="FILE",
                    help="把本轮 unaccounted 义务打成待填 resolves 骨架（纯输出，不参与判定）")
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
    if args.emit_skeleton:
        out = Path(args.emit_skeleton)
        entries = skeleton(result)["resolves"]
        out.write_text(json.dumps(skeleton(result), ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        print(f"  骨架 → {out}（{len(entries)} 条待填 status/by/evidence）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
