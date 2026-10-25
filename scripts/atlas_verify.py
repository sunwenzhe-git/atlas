#!/usr/bin/env python3
"""atlas 验收执行器(执行层最小立项面 ①)——`RFC-20261025-02` v2 / `DESIGN.md` D150。

四步(**执行器 = 编排者 + 统一报告者 + 留档者,不重造真跑**):

  pre     项目数据准备钩子 `product/e2e/scripts/atlas-prepare.mjs`(缺 ⇒ SKIP+原因,不算失败);
          cwd = 项目根、180s 上限(控制台 D110 同款);env 带 `ATLAS_CASE_ID=verify-batch`
          (显式批标识——RFC-20261025-02 批级语义:非用例 ID,D121 的逐用例分段仍归控制台);
          `<root>/node_modules` 存在 ⇒ 同步注入 `NODE_PATH`(与真跑子进程依赖解析环境一致)。
  run     = `python3 .atlas/scripts/atlas_check.py --root <root>`(默认模式含全量真跑与装配门)
          ——**全批只跑一次真跑**(双跑 = 首跑 D108 留证被 Playwright 二次起跑清空)。
  report  汇总行集 → stdout(+`--json`)并落档 `product/e2e/reviews/<日期>-verify/`
          (README + report.json);**仅全链绿时落档**——失败批只出结构化报告不落档,
          重跑因此不被短路。
  backfill **缓行**(首批写面零触碰:不写 e2e-index 状态列、不进评审账本、不取写面 claim)。

续跑语义(无独立状态文件;失败停环沿 `apply/reference.md` §7;**落刀现场修正 2026-10-25**:
  原「run 按 results.json 产物跳过」有假绿通道——Playwright 在**失败批**结束同样写出
  results.json ⇒ 失败后重跑会跳过 run、把空行集落档成 ok。修正:run 步**恒重跑**
  (atlas_check 本就是验收本体),**留档是唯一短路门户**——只有全链绿落过档的批才不再重跑;
  - 留档目录在 ⇒ 整批短路(已成功的批不重跑);
  - pre / run 均**恒重跑**(pre 幂等廉价;run = 验收本体,重跑它就是验收)——
    副作用 = 重跑会清空上一失败批的 `.atlas-run` 留证(已知观察,bugs.md 留存窗口行,
    跨轮取证先手动归档);
  - 任一步失败 ⇒ 停该步、结构化报告(哪步/为何/已完步产物清单),下游不静默跳过。

退出码:**0** 全链绿或短路;**1** 失败(结构化报告);**2** 参数错(不写盘)。纯标准库。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PRE_TIMEOUT_S = 180
BATCH_CASE_ID = "verify-batch"  # RFC-20261025-02 批级语义:显式批标识,非用例 ID(D121)


def _prep_env(root: Path) -> dict:
    env = dict(__import__("os").environ)
    env["ATLAS_CASE_ID"] = BATCH_CASE_ID
    nm = root / "node_modules"
    if nm.is_dir():
        env["NODE_PATH"] = str(nm)
    return env


def step_pre(root: Path) -> dict:
    """项目数据准备钩子;缺 ⇒ SKIP,失败/超时 ⇒ 失败(停环)。"""
    prep = root / "product" / "e2e" / "scripts" / "atlas-prepare.mjs"
    started = time.perf_counter()
    if not prep.is_file():
        return {"name": "pre", "status": "SKIP",
                "detail": "无项目数据准备钩子 atlas-prepare.mjs(合法态,不算失败)",
                "duration_ms": int((time.perf_counter() - started) * 1000)}
    try:
        pr = subprocess.run(["node", str(prep)], cwd=str(root), capture_output=True,
                            text=True, timeout=PRE_TIMEOUT_S, env=_prep_env(root))
    except FileNotFoundError:
        return {"name": "pre", "status": "FAIL", "detail": "node 可执行不存在", "duration_ms": 0}
    except subprocess.TimeoutExpired:
        return {"name": "pre", "status": "FAIL",
                "detail": f"atlas-prepare 超时(>{PRE_TIMEOUT_S}s,不占真跑超时窗)",
                "duration_ms": PRE_TIMEOUT_S * 1000}
    dur = int((time.perf_counter() - started) * 1000)
    if pr.returncode != 0:
        return {"name": "pre", "status": "FAIL",
                "detail": f"atlas-prepare 失败(exit={pr.returncode}):{(pr.stderr or pr.stdout or '')[-800:]}",
                "duration_ms": dur}
    return {"name": "pre", "status": "ok",
            "detail": ((pr.stdout or "").strip()[-400:] or "(无输出)"), "duration_ms": dur}


def _parse_rows(output: str) -> list[dict]:
    """解析 atlas_check 行形态(`ok|WARN|FAIL|SKIP <名称> <摘要>`,与门行原样)。

    已知局限:名称含空格的门行(如「E2E 真跑(六页)」)name 只取到首词——
    消费方按 startswith 匹配;摘要列完整保留。"""
    
    rows = []
    for line in output.splitlines():
        toks = line.split(None, 2)
        if toks and toks[0] in {"ok", "WARN", "FAIL", "SKIP"} and len(toks) >= 2:
            rows.append({"status": toks[0], "name": toks[1],
                         "summary": (toks[2] if len(toks) > 2 else "").strip()})
    return rows


def step_run(root: Path, py: str) -> dict:
    """run = atlas_check 默认模式(含全量真跑);**恒重跑**(留档是唯一短路门户——
    results.json 在失败批同样存在,按它跳过 = 假绿通道,落刀现场修正 2026-10-25)。"""
    started = time.perf_counter()
    check = root / ".atlas" / "scripts" / "atlas_check.py"
    if not check.is_file():
        return {"name": "run", "status": "FAIL", "detail": "atlas_check.py 不存在(未装配?)",
                "duration_ms": 0, "rows": [], "real_run_count": 0}
    pr = subprocess.run([py, str(check), "--root", str(root)], capture_output=True, text=True)
    dur = int((time.perf_counter() - started) * 1000)
    out = (pr.stdout or "") + (pr.stderr or "")
    return {"name": "run", "status": "ok" if pr.returncode == 0 else "FAIL",
            "detail": f"atlas_check exit={pr.returncode}" + ("" if pr.returncode == 0 else f":{out.strip()[-400:]}"),
            "duration_ms": dur, "rows": _parse_rows(out), "real_run_count": 1}


def _evidence_paths(root: Path) -> list[str]:
    d = root / "product" / "e2e" / "scripts" / ".atlas-run"
    if not d.is_dir():
        return []
    hits = [str(p.relative_to(root)) for p in sorted(d.rglob("*"))
            if p.is_file() and (p.name == "trace.zip" or p.name.startswith("test-failed"))]
    return hits[:20]


def archive_dir(root: Path) -> Path:
    return root / "product" / "e2e" / "reviews" / f"{datetime.now().date().isoformat()}-verify"


def write_archive(root: Path, report: dict) -> str:
    d = archive_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# 验收执行器留档({datetime.now().isoformat(timespec='seconds')};RFC-20261025-02/D150)",
             "", "| 步 | 态 | 用时(ms) | 说明 |", "|---|---|---|---|"]
    for st in report["steps"]:
        lines.append(f"| {st['name']} | {st['status']} | {st['duration_ms']} | {st['detail'][:120]} |")
    lines += ["", "| 门行 | 态 | 摘要 |", "|---|---|---|"]
    for r in report["rows"]:
        lines.append(f"| {r['name']} | {r['status']} | {r['summary'][:120]} |")
    (d / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(d.relative_to(root))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="atlas 验收执行器(编排+统一报告+留档;不重造真跑)")
    ap.add_argument("--root", required=True, help="项目根")
    ap.add_argument("--json", action="store_true", help="机读报告(stdout)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print("ERROR: --root 不是目录", file=sys.stderr)
        return 2

    # 留档在 ⇒ 整批短路(已成功的批不重跑)
    if archive_dir(root).is_dir():
        report = {"ok": True, "short_circuit": True,
                  "detail": f"留档 {archive_dir(root).relative_to(root)} 已存在——已成功的批不重跑",
                  "steps": [], "rows": [], "real_run_count": 0, "archive": str(archive_dir(root).relative_to(root))}
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
              else f"[短路] {report['detail']}")
        return 0

    steps: list[dict] = []
    real_run = 0

    pre = step_pre(root)
    steps.append(pre)
    if pre["status"] == "FAIL":
        return _fail(root, steps, [], 0, args.json)

    run = step_run(root, py=sys.executable)
    steps.append(run)
    real_run += run.get("real_run_count", 0)
    if run["status"] == "FAIL":
        return _fail(root, steps, run.get("rows", []), real_run, args.json)

    rows = run.get("rows", [])
    report = {"ok": True, "short_circuit": False, "steps": steps, "rows": rows,
              "real_run_count": real_run, "archive": None}
    report["archive"] = write_archive(root, report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for st in steps:
            print(f"[{st['status']}] {st['name']} ({st['duration_ms']}ms) {st['detail'][:160]}")
        for r in rows:
            print(f"  {r['status']:<4} {r['name']:<24} {r['summary'][:100]}")
        print(f"[留档] {report['archive']}")
    return 0


def _fail(root: Path, steps: list[dict], rows: list[dict], real_run: int, as_json: bool) -> int:
    """失败停环:停在该步、结构化报告、下游不静默跳过;失败不落档(重跑不被短路)。"""
    report = {"ok": False, "short_circuit": False, "steps": steps, "rows": rows,
              "real_run_count": real_run, "archive": None,
              "failed_step": next((s["name"] for s in reversed(steps) if s["status"] == "FAIL"), None),
              "completed_steps": [s["name"] for s in steps if s["status"] in {"ok", "SKIP"}],
              "evidence": _evidence_paths(root)}
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"[FAIL] 停在 {report['failed_step']} 步(下游不执行);已完步:{report['completed_steps']}",
              file=sys.stderr)
        if report["evidence"]:
            print(f"[留证] 失败构件:{report['evidence']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
