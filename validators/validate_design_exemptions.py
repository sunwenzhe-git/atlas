#!/usr/bin/env python3
"""atlas 校验器 —— 设计档案 detect 豁免 ⇔ impeccable 检测器配置对账（`ATLAS-UPSTREAM #182`，2026-10-08）。

守一件事（机器对账取代 prose 约定）：

  `product/design.md`（视觉设计档案，frontend-design skill 写、atlas 只读）里
  「已有豁免」中的 detect 类豁免写作 `detect:<rule-id>`；同一组 rule id 必须
  出现在项目根 `.impeccable/config.json` 的 `detector.ignoreRules` —— **双向
  集合相等**。

  为什么两侧都必须有：豁免 = 关掉一条确定性检测的报警。开关只能有一处
  （机器配置才真的关掉报警），档案是人读台账（为什么关、谁批准的）。
  单侧缺失 = 报警关了没人知道为什么（缺台账），或台账说关了其实没关（缺配置）。

判定（三态，`§B120`）：
  - 无 `product/design.md` ⇒ **SKIP**（档案未建 = 未就绪，不是失败）。
  - 档案 `detect:<id>` 集合 ⇔ 配置 `detector.ignoreRules` 集合相等 ⇒ PASS
    （两侧皆空是合法退化态）。
  - 任一侧多出 ⇒ FAIL，双向差集指名。
  - 档案已声明 detect 豁免而无 `.impeccable/config.json` ⇒ FAIL。
  - config JSON 损坏 ⇒ FAIL（impeccable detect 自身也读不了它，响亮暴露）。

显式盲区（不查）：
  - 豁免**理由是否成立**（语义，人侧终审：走查 / 验收门）。
  - rule id 是否真实存在于 impeccable 规则表（不内嵌第三方规则表——impeccable
    升级会误伤；写错的 id 会在双向对账中以漂移形态自然暴露）。
  - 档案其余事实行（判读 / 旋钮 / 设计系统 / 强调色）的内容正确性——那是
    frontend-design skill 的辖区，atlas 只管豁免这一处两侧一致。

框架无关；纯标准库。CLI：`python3 validate_design_exemptions.py --root <项目根> [--json]`
输出 `{ok, status, checks[]}`；判定 PASS / SKIP → 退出码 0，FAIL → 1。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DESIGN_RELPATH = Path("product") / "design.md"
CONFIG_RELPATH = Path(".impeccable") / "config.json"
DETECT_TOKEN = re.compile(r"detect:([A-Za-z0-9][A-Za-z0-9_-]*)")


class Result:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, check: str, status: str, detail: str = "") -> None:
        self.checks.append({"check": check, "status": status, "detail": detail})

    @property
    def status(self) -> str:
        statuses = [c["status"] for c in self.checks]
        if "FAIL" in statuses:
            return "FAIL"
        if "WARN" in statuses:
            return "WARN"
        if statuses and all(s == "SKIP" for s in statuses):
            return "SKIP"
        return "PASS"

    @property
    def ok(self) -> bool:
        return self.status != "FAIL"


def design_detect_ids(text: str) -> set[str]:
    """档案全文的 `detect:<rule-id>` token 集合（契约：token 即豁免声明）。"""
    return set(DETECT_TOKEN.findall(text))


def config_ignore_rules(cfg_path: Path) -> set[str]:
    """`.impeccable/config.json` 的 `detector.ignoreRules` 集合。损坏 ⇒ ValueError。"""
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("顶层不是 JSON object")
    det = data.get("detector") or {}
    if not isinstance(det, dict):
        raise ValueError("detector 段不是 object")
    rules = det.get("ignoreRules") or []
    if not isinstance(rules, list):
        raise ValueError("detector.ignoreRules 不是列表")
    return {str(r) for r in rules}


def run(root: Path) -> Result:
    res = Result()
    design = root / DESIGN_RELPATH
    if not design.is_file():
        res.add("设计档案存在", "SKIP",
                "无 product/design.md（档案未建，未就绪非失败）")
        return res
    res.add("设计档案存在", "PASS", DESIGN_RELPATH.as_posix())

    ids = design_detect_ids(design.read_text(encoding="utf-8", errors="replace"))
    cfg = root / CONFIG_RELPATH

    if not cfg.is_file():
        if ids:
            res.add("豁免 ⇔ ignoreRules", "FAIL",
                    f"档案声明 detect 豁免 {sorted(ids)}，但无 .impeccable/config.json（报警没真关）")
        else:
            res.add("豁免 ⇔ ignoreRules", "PASS", "档案无 detect 豁免，无需配置")
        return res

    try:
        rules = config_ignore_rules(cfg)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
        res.add("豁免 ⇔ ignoreRules", "FAIL", f".impeccable/config.json 不可读：{e}")
        return res

    only_design = ids - rules
    only_config = rules - ids
    if only_design or only_config:
        parts = []
        if only_design:
            parts.append(f"档案有而配置缺={sorted(only_design)}（台账说关了，报警还开着）")
        if only_config:
            parts.append(f"配置有而档案缺={sorted(only_config)}（报警关了，没人知道为什么）")
        res.add("豁免 ⇔ ignoreRules", "FAIL", "；".join(parts))
    else:
        res.add("豁免 ⇔ ignoreRules", "PASS",
                f"{len(ids)} 条双向一致" if ids else "两侧皆空（合法退化态）")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="设计档案 detect 豁免 ⇔ .impeccable 配置对账")
    ap.add_argument("--root", required=True, help="项目根")
    ap.add_argument("--json", action="store_true", help="JSON 输出（stdout）")
    args = ap.parse_args(argv)

    res = run(Path(args.root))
    payload = {"ok": res.ok, "status": res.status, "checks": res.checks}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{res.status}  validate_design_exemptions")
        for c in res.checks:
            line = f"  [{c['status']}] {c['check']}"
            if c["detail"]:
                line += f" — {c['detail']}"
            print(line)
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
