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
**连续 carried 的前提复核（`RFC-20261104-01` S2）**：最新轮仍 open、且**上一轮（轮差 = 1）**
同指纹也 open ⇒ 视为连续未关闭，最新轮 `checks[]` 必须带 `premise`（一句话共同前提）与
`discriminating_check{command, expected_if_false}`；缺失/形状错只记 `premise_required[]` + `warnings`、
抬 WARN，**退出码仍为 0，永不阻断**。上一轮用 `events` 里 `< latest` 且 `kind=="check"` 的**最大轮号**
判相邻（不用跨轮去重后的 `prior_round`，否则 `{1,2,3}` 会被算成 `3-1=2` 而漏掉空窗）；
同轮重复只在本轮内去重、等级取最严档；上一轮已 resolves 关闭则重新开启不算连续。

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
from _support import review_scope_core as scope_core  # noqa: E402

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
    """签字 + 取证（单源判据；非字符串的「签名」不算）。"""
    return review_policy.has_signed_disposition(check)


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
        suffix = name[len(unit) + 2:] if name.startswith(unit + ".r") else ""
        if name == unit:
            rnd = 1
        elif suffix.isdigit() and suffix.isascii():   # 全角 / 上标数字不认（见上注）
            rnd = int(suffix)
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

    **逐条取舍，不整批没收**：一条写歪只作废它自己（不同 fingerprint）；同轮其余合法声明照常
    承重。否则历史里一个 `by: 123` 会把该轮所有合法关闭声明一起清零 —— 那是「假失忆」，比响亮更糟。

    **重复指纹整组作废**：同一 fingerprint 出现多次是同一义务的冲突声明，不能按书写顺序挑第一条
    承重（`fixed` 在前就关、`intentional` 在前就不关）。该指纹的**全部**条目都不作关闭证据，
    其余指纹照常承重。重复检测对坏条目同样计数，与最新轮 `resolves_shape_errors` 同口径。
    """
    raw = data.get("resolves")
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], review_policy.resolves_shape_errors(raw, f"{path.name} 的 resolves")
    valid: list[dict] = []
    errs: list[str] = []
    fp_order: list[str] = []
    fp_counts: dict[str, int] = {}
    for i, item in enumerate(raw):
        label = f"{path.name} 的 resolves[{i}]"
        entry_errs = review_policy.resolves_entry_errors(item, label)
        if entry_errs:
            errs.extend(entry_errs)
        else:
            valid.append(item)
        fp = item.get("fingerprint") if isinstance(item, dict) else None
        if isinstance(fp, str) and fp.strip() and fp == fp.strip():
            if fp not in fp_counts:
                fp_order.append(fp)
            fp_counts[fp] = fp_counts.get(fp, 0) + 1
    dups = {fp for fp in fp_order if fp_counts[fp] > 1}
    errs.extend(f"{path.name} 的 resolves 出现重复 fingerprint：{fp}"
                for fp in fp_order if fp in dups)
    return [item for item in valid if item["fingerprint"] not in dups], errs


def declares_close(entry: dict, obligation_level: str | None) -> bool:
    """一条 `resolves` 声明是否构成关闭：取证要求 + Critical 不接受 intentional/ignored。

    `obligation_level` 是义务在**所有出现里最严的一档**（见 `worst_level`），两个方向都挡住。
    """
    status = entry.get("status")
    if status not in CLOSED:
        return False
    if status in EVIDENCE_REQUIRED:
        return review_policy.has_signed_disposition(entry, "by", "evidence")
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


def round_worst_level(entries: list[dict]) -> str | None:
    """同轮同指纹重复时取**最严档**，不让升降级语义被去重吞掉。"""
    level: str | None = None
    for entry in entries:
        level = review_policy.worst_level(level, entry.get("level"))
    return level


def premise_missing(check: dict) -> list[str]:
    """最新轮连续 carried 必须带的前提字段；缺失项按稳定顺序返回（空列表 = 合格）。

    形状面（类型/非空）由 `validate_review_report` 判；这里是语义面的「写了没」。
    """
    missing: list[str] = []
    if not review_policy.signed_str(check, "premise"):
        missing.append("premise")
    dc = check.get("discriminating_check")
    if not isinstance(dc, dict):
        missing.append("discriminating_check")
        return missing
    for key in ("command", "expected_if_false"):
        if not review_policy.signed_str(dc, key):
            missing.append(f"discriminating_check.{key}")
    return missing


def streak_prev_round(events: list[tuple[int, str, dict]], item: dict,
                      latest_round: int) -> int | None:
    """连续 carried 的「上一轮」：`events` 中 `< latest` 且 `kind=="check"` 的最大轮号。

    必须读 `events`，不能用 `prior` 里的 `prior_round`——后者是跨轮去重后的首现轮，
    `{1,2,3}` 会被算成 `3-1=2`，第 2–3 轮的空窗被漏掉。同轮重复只在本轮内去重
    （同一轮多个 check 事件只贡献一个轮号，跨轮命中不把 streak 归 N/A）。
    """
    rounds = sorted({rnd for rnd, kind, _ in events
                     if kind == "check" and rnd < latest_round})
    if not rounds:
        return None
    prev = rounds[-1]
    if latest_round - prev != 1:
        return None
    prev_checks = [entry for rnd, kind, entry in events
                   if kind == "check" and rnd == prev]
    if not any(relevant(entry) for entry in prev_checks):
        return None   # 上一轮是 `pre_existing` / Minor / 已关闭 ⇒ 不参与 streak
    if any(declares_close(entry, item.get("level")) for rnd, kind, entry in events
           if kind == "resolves" and rnd == prev):
        return None   # 上一轮已 resolves 关闭、最新又 open ⇒ 重新开启，不是同前提连续失败
    return prev


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
        if status in EVIDENCE_REQUIRED and not review_policy.has_signed_disposition(item,
                                                                                    "by", "evidence"):
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
            "carried": [], "resolved": [], "unaccounted": [], "premise_required": [],
            "level_downgraded": [], "unknown_resolves": [], "invalid_resolves": [],
            "scope_drift": [], "scope_drift_accepted": [],
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

    # 级别加宽读**全部出现**（含被标 pre_existing、已关闭、非本池级别的条目）：
    # 加宽若挂在 relevant() 之后，「升级那一轮顺手标 pre_existing」就跳过加宽，
    # 义务仍按陈旧 Major 判 ⇒ 声明侧与重报侧都能免签关掉（评审打出的 B1 残留方向）
    for item in prior:
        for _rnd, kind, entry in events.get(item["fingerprint"], []):
            if kind == "check":
                item["level"] = review_policy.worst_level(item.get("level"), entry.get("level"))

    # ---- 跨轮内容封口（RFC-20261103-01，观察面非门）--------------------------------
    # 只看「prior 轮审过的文件，现在变了，且最新轮没审当前内容」——这才是未复审变化。
    # 最新轮自己的 manifest 过期归 validate_review_report --scope-manifest，不在此重复判。
    scope_drift: list[dict] = []
    scope_drift_accepted: list[dict] = []
    scope_unavailable = False
    root_path = Path(str(root.get("root") or "."))
    latest_scope = root.get("review_scope") if isinstance(root.get("review_scope"), dict) else None
    latest_files = {f.get("path"): f.get("sha256")
                    for f in (latest_scope or {}).get("files", []) if isinstance(f, dict)}
    drift = root.get("review_scope_drift") if isinstance(root.get("review_scope_drift"), dict) else None
    accepted_drift = bool(
        drift and review_policy.signed_str(drift, "accepted_by")
        and review_policy.signed_str(drift, "reason")
        and latest_scope and latest_scope.get("sha256") == drift.get("current_sha256"))
    if latest_scope is not None and root_path.is_dir():
        for rnd, _path, data in prior_rounds:
            pscope = data.get("review_scope")
            if not isinstance(pscope, dict) or not isinstance(pscope.get("files"), list):
                continue
            round_drift: list[dict] = []
            for item in pscope["files"]:
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    continue
                rel, old = item["path"], item.get("sha256")
                try:
                    cur = scope_core.entry_for(root_path, rel)
                except scope_core.ScopeError:
                    cur = {"sha256": scope_core.HASH_ABSENT}
                if cur.get("sha256") == old:
                    continue
                # `review_scope_drift` 明确 reviewed=false：即便最新轮 manifest 覆盖了当前内容，
                # 也不能当成「已复审」——它是用户确认放行，不是审过。
                if latest_files.get(rel) == cur.get("sha256") and not accepted_drift:
                    continue  # 最新轮审了当前内容 ⇒ 已复审
                round_drift.append({"round": rnd, "path": rel,
                                    "prior_sha256": old, "current_sha256": cur.get("sha256")})
            if not round_drift:
                continue
            if accepted_drift and pscope.get("sha256") == drift.get("previous_sha256"):
                scope_drift_accepted.extend(round_drift)
            else:
                scope_drift.extend(round_drift)
                for item in round_drift:
                    warnings.append(
                        f"r{item['round']} 的 `{item['path']}` 内容已变化且未纳入最新实审集"
                        "（未复审变化；重审或走 --accept-scope-drift）")
    elif latest_scope is None and any(isinstance(d.get("review_scope"), dict)
                                      for _, _, d in prior_rounds):
        warnings.append("最新轮无 review_scope，无法做跨轮内容封口比对（旧报告兼容）")
        scope_unavailable = True

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
    contradictions: list[str] = []
    for item in prior:
        fp = item["fingerprint"]
        latest = latest_by_fp.get(fp)
        if latest:
            still_open = [c for c in latest if state_of(c, item.get("level")) == "open"]
            if still_open and len(still_open) < len(latest):
                contradictions.append(fp)
                warnings.append(f"同指纹在最新轮同时出现 open 与已关闭条目：{fp}"
                                "（形态矛盾，需 triage 归一）⇒ 按未关闭跟踪")
            if not still_open:
                resolved.append({**item, "via": "re-reported", "status": "closed"})
            else:
                carried.append(item)
                if item.get("level") == "Critical" and all(
                        c.get("level") != "Critical" for c in latest):
                    latest_level = round_worst_level(latest)
                    downgraded.append({**item, "latest_level": latest_level})
                    warnings.append(
                        f"prior Critical（round {item['prior_round']} `{item.get('target')}`）"
                        f"新一轮降级为 {latest_level!r} —— 仍按未关闭跟踪")
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

    # ---- 连续 carried 的前提复核（S2；只 WARN，退出码仍为 0，不进 atlas_check）----------
    premise_required: list[dict] = []
    for item in carried:
        fp = item["fingerprint"]
        prev = streak_prev_round(events.get(fp, []), item, latest_round)
        if prev is None:
            continue
        open_entries = [c for c in latest_by_fp.get(fp, [])
                        if state_of(c, item.get("level")) == "open"]
        if not open_entries:
            continue
        # 同轮同指纹重复只在本轮内去重：字段按「本轮写过」判一次，等级取最严档
        missing_by_entry = [premise_missing(c) for c in open_entries]
        if any(not missing for missing in missing_by_entry):
            continue
        level = round_worst_level(open_entries)
        strict = next((c for c in open_entries if c.get("level") == level), open_entries[0])
        missing = premise_missing(strict)
        premise_required.append({"fingerprint": fp, "target": item.get("target"),
                                 "level": level, "prev_round": prev,
                                 "latest_round": latest_round, "missing": missing})
        warnings.append(
            f"连续 carried r{prev}→r{latest_round} 的 `{fp}` 缺 {'/'.join(missing)}"
            "（共同前提与判别检查是复核承重件；只 WARN，不阻断）")

    for entry in (root.get("resolves") or []):
        if not isinstance(entry, dict):
            continue
        declared_round = entry.get("round")
        fp = str(entry.get("fingerprint") or "")
        obligation = next((x for x in prior if x["fingerprint"] == fp), None)
        if isinstance(declared_round, int) and obligation and declared_round != obligation["prior_round"]:
            warnings.append(
                f"resolves 声明的 round={declared_round} 与义务所在轮 "
                f"r{obligation['prior_round']} 不一致（{fp}）"
                "⇒ 判定按文件轮次，声明里的 round 只作人读标注")

    stale = sorted(declared_earlier - prior_fps)
    if stale:
        warnings.append(f"中间轮有 {len(stale)} 个指纹匹配不到任何义务"
                        f"（历史冗余声明或指纹写错）：{stale[:5]}")

    if prior_shape_errors:
        warnings.extend(f"中间轮 resolves 形状错（该条不作关闭证据）：{e}" for e in prior_shape_errors)
    status = "WARN" if (unaccounted or unknown_resolves or invalid_resolves or orphans
                        or downgraded or prior_shape_errors or contradictions
                        or premise_required
                        or scope_drift or scope_unavailable) else "PASS"
    result = {"schema_version": 1, "unit": unit, "latest_round": latest_round,
              "rounds": [r for r, _, _ in prior_rounds] + [latest_round],
              "prior_relevant": len(prior), "carried": carried, "resolved": resolved,
              "unaccounted": unaccounted, "premise_required": premise_required,
              "level_downgraded": downgraded,
              "unknown_resolves": unknown_resolves,
              "invalid_resolves": invalid_resolves,
              "scope_drift": scope_drift, "scope_drift_accepted": scope_drift_accepted,
              "warnings": warnings, "status": status}
    return status, result


def skeleton(result: dict) -> dict:
    """待填骨架：`--resolves` 可直接吃这个形状（顶层 `by` 为整批缺省签字人）。"""
    return {"by": "",
            "resolves": [{"fingerprint": u["fingerprint"], "status": "", "by": "", "evidence": "",
                          "prior_round": u["prior_round"], "target": u.get("target")}
                         for u in result["unaccounted"]],
            "scope_drift": result.get("scope_drift", [])}


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
    try:
        (report_dir / "closure.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    except OSError as exc:
        return die(f"写 {report_dir / 'closure.json'} 失败：{exc}")
    print(f"review_closure @ {report_dir}   {status}   rounds {len(result['rounds'])} "
          f"prior {result['prior_relevant']} carried {len(result['carried'])} "
          f"resolved {len(result['resolved'])} unaccounted {len(result['unaccounted'])} "
          f"premise {len(result['premise_required'])} "
          f"unknown {len(result['unknown_resolves'])} invalid {len(result['invalid_resolves'])} "
          f"scope_drift {len(result['scope_drift'])} accepted {len(result['scope_drift_accepted'])} "
          f"warnings {len(result['warnings'])}")
    for w in result["warnings"]:
        print(f"  · {w}")
    if args.emit_skeleton:
        out = Path(args.emit_skeleton)
        sk = skeleton(result)
        entries = sk["resolves"]
        out.write_text(json.dumps(sk, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"  骨架 → {out}（{len(entries)} 条待填 status/by/evidence）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
