#!/usr/bin/env python3
"""atlas 验收执行器(执行层最小立项面 ①)——`RFC-20261025-02` v2 / `DESIGN.md` D150;
backfill 步 = 附录 B v2 / `DESIGN.md` D151(2026-10-26 评审修后通过)。

步序(**执行器 = 编排者 + 统一报告者 + 留档者,不重造真跑**):

  pre       项目数据准备钩子 `product/e2e/scripts/atlas-prepare.mjs`(缺 ⇒ SKIP+原因,不算失败);
            cwd = 项目根、180s 上限(控制台 D110 同款);env 带 `ATLAS_CASE_ID=verify-batch`
            (显式批标识——RFC-20261025-02 批级语义:非用例 ID,D121 的逐用例分段仍归控制台);
            `<root>/node_modules` 存在 ⇒ 同步注入 `NODE_PATH`(与真跑子进程依赖解析环境一致)。
  run       = `python3 .atlas/scripts/atlas_check.py --root <root>`(默认模式含全量真跑与装配门)
            ——**全批只跑一次真跑**(双跑 = 首跑 D108 留证被 Playwright 二次起跑清空)。
  backfill  附录 B v2(D151):**仅全链绿批、排在留档前**——写前硬断言(B4)→ claim(`scripts/
            write_claim.py`,task=`verify-backfill`,粒度 = 整文件 e2e-index.md)→ 账本基线
            (events.jsonl 字节/行数 + 尾 submit (ts, prov))→ **复用 `e2e_console.writeback`
            同函数**回填状态列(签名/行为零改动;机器批与人批在索引内同形,分辨面 = 留档)→
            复检(尾 submit 变 ⇒ 撞窗:FAIL + 覆盖差量 + 出路 = 人工经 console 重提交;字节变
            而尾 submit 不变 ⇒ 区间漂移注记)→ release。**永不写 events.jsonl**(B2:评审账本
            是人签字载体);索引缺失 / results.json 缺失 ⇒ SKIP(合法态);红批不回填(停环)。
  report    汇总行集 → stdout(+`--json`)并落档 `product/e2e/reviews/<日期>-verify/`
            (README + report.json;含回填章);**仅全链绿时落档**——失败批只出结构化报告不落档,
            重跑因此不被短路。

续跑语义(无独立状态文件;失败停环沿 `apply/reference.md` §7;**落刀现场修正 2026-10-25**:
  原「run 按 results.json 产物跳过」有假绿通道——Playwright 在**失败批**结束同样写出
  results.json ⇒ 失败后重跑会跳过 run、把空行集落档成 ok。修正:run 步**恒重跑**
  (atlas_check 本就是验收本体),**留档是唯一短路门户**——只有全链绿落过档的批才不再重跑;
  - 留档在 ⇒ 整批短路(已成功的批不重跑,**backfill 也不再跑**——索引状态由上批已回填
    或人批维护;附录 B v2 步序相互作用);
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

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.layout import LayoutError, load_layout  # noqa: E402

PRE_TIMEOUT_S = 180
BATCH_CASE_ID = "verify-batch"  # RFC-20261025-02 批级语义:显式批标识,非用例 ID(D121)
# 附录 B v2(D151):backfill 的 claim task 名(写面残留行/冲突报告里的「在办任务」)。
# 固定值 = 机器批可指认;`verify-batch` 一物两用是批标识/留档标记,**不是**索引词表值。
BACKFILL_TASK = "verify-backfill"


def _prep_env(root: Path) -> dict:
    env = dict(__import__("os").environ)
    env["ATLAS_CASE_ID"] = BATCH_CASE_ID
    nm = root / "node_modules"
    if nm.is_dir():
        env["NODE_PATH"] = str(nm)
    return env


def step_pre(root: Path) -> dict:
    """项目数据准备钩子;缺 ⇒ SKIP,失败/超时 ⇒ 失败(停环)。"""
    prep = load_layout(root).e2e_scripts_dir / "atlas-prepare.mjs"
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
    d = load_layout(root).e2e_run_dir
    if not d.is_dir():
        return []
    hits = [str(p.relative_to(root)) for p in sorted(d.rglob("*"))
            if p.is_file() and (p.name == "trace.zip" or p.name.startswith("test-failed"))]
    return hits[:20]


def archive_dir(root: Path) -> Path:
    return load_layout(root).e2e_reviews_dir / f"{datetime.now().date().isoformat()}-verify"


# -------------------------------------------------------------- backfill(附录 B v2 / D151)

def _import_console():
    """按**装配态同目录**导入 `e2e_console` / `write_claim` —— 与控制台同副本同版本,单一来源。

    解析规则 = `sys.path[0]` 即本脚本所在目录(源包态 `scripts/`、采纳态 `.atlas/scripts/`,
    install.sh:440/448 同批拷入);测试以 importlib 加载此处会补 entry 保证同目录可达。
    e2e_console 导入不启服(服务进程在 `__main__` 守卫内),其 `_support` 自举幂等无害。
    """
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import e2e_console
    import write_claim
    return e2e_console, write_claim


def _draft_from_results(run_dir: Path) -> dict | None:
    """Playwright JSON 报告(`results.json`)→ 逐用例 draft `{用例ID: {"ok": bool}}`。

    `suites[].specs[].title` 首词 = 用例 ID(如「E2E-HOME-001 点击后标题就绪」);
    `expected`/`flaky` ⇒ ok(都以通过收尾);`unexpected` ⇒ 红;`skipped` 不入 draft
    (未执行,不回填——索引原样保留,状态语义 = 上一批)。
    """
    rf = run_dir / "results.json"
    if not rf.is_file():
        return None
    try:
        data = json.loads(rf.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    statuses: dict[str, list[str]] = {}

    def walk(suite: dict) -> None:
        for spec in suite.get("specs", []):
            title = (spec.get("title") or "").strip()
            cid = title.split(None, 1)[0] if title else ""
            if not cid.startswith("E2E-"):
                continue
            for t in spec.get("tests", []):
                st = t.get("status")
                if st in {"expected", "flaky", "unexpected", "skipped"}:
                    statuses.setdefault(cid, []).append(st)
        for s2 in suite.get("suites", []):
            walk(s2)

    for s in data.get("suites", []) or []:
        walk(s)
    draft = {}
    for cid, sts in statuses.items():
        ran = [x for x in sts if x != "skipped"]
        if ran:
            draft[cid] = {"ok": all(x in {"expected", "flaky"} for x in ran)}
    return draft


def _ledger_signature(root: Path) -> dict:
    """撞窗基线(附录 B v2 B3):events.jsonl 的 (字节数, 行数) + 最后一条 submit 的 (ts, prov)。

    submit 是唯一写索引的账本事件 ⇒ 尾 submit 变 = 撞窗;字节/行数变而尾 submit 不变 =
    区间漂移(非 submit 事件写入,索引未被竞写)。
    """
    f = load_layout(root).console_ledger
    if not f.is_file():
        return {"bytes": -1, "lines": -1, "last_submit": None}
    raw = f.read_bytes()
    last: dict | None = None
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and ev.get("kind") == "submit":
            last = {"ts": ev.get("ts"), "prov": ev.get("prov")}
    return {"bytes": len(raw), "lines": len(raw.splitlines()), "last_submit": last}


def _index_case_ids(root: Path, index: Path | None = None) -> set[str]:
    """e2e-index.md 主表的用例 ID 集(B4 断言①的比对源;形态与 `e2e_console.writeback` 同源)。"""
    index = index or load_layout(root).e2e_index
    ids: set[str] = set()
    for line in index.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("| E2E-"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and cells[0].startswith("E2E-"):
                ids.add(cells[0])
    return ids


def _index_state_of(root: Path, cid: str, index: Path | None = None) -> str | None:
    index = index or load_layout(root).e2e_index
    for line in index.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith(f"| {cid} ") or line.lstrip().startswith(f"| {cid}|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            return cells[6] if len(cells) > 6 else None
    return None


def _submit_changed(before: dict, after: dict) -> bool:
    """尾 submit 身份比较:ts + prov 都没动才算「不是人批」。"""
    b, a = before.get("last_submit"), after.get("last_submit")
    if b is None and a is None:
        return False
    return (a is None) != (b is None) or a != b


def step_backfill(root: Path) -> dict:
    """backfill(附录 B v2):断言(B4)→ claim(B3)→ 基线 → 复用 console writeback 同函数
    回填(B1)→ 复检 → release。红批不进本步(停环);索引/results 缺 ⇒ SKIP(合法态)。"""
    started = time.perf_counter()
    lay = load_layout(root)
    index = lay.e2e_index
    index_rel = lay.print_value("e2e_index")
    if not index.is_file():
        return {"name": "backfill", "status": "SKIP",
                "detail": "无 e2e-index.md(合法态:无索引即无回填面)", "duration_ms": 0}
    try:
        console, claim_mod = _import_console()
    except Exception as e:  # 装配残缺 = 装配态自检门的族病;此处如实点名为硬失败
        return {"name": "backfill", "status": "FAIL",
                "detail": f"e2e_console/write_claim 不可导入(装配残缺?):{type(e).__name__}: {e}",
                "duration_ms": int((time.perf_counter() - started) * 1000)}
    draft = _draft_from_results(lay.e2e_run_dir)
    if draft is None:
        return {"name": "backfill", "status": "SKIP",
                "detail": "无 results.json(合法态:无可解析执行结果,不回填)",
                "duration_ms": int((time.perf_counter() - started) * 1000)}

    def _fail_step(detail: str) -> dict:
        return {"name": "backfill", "status": "FAIL", "detail": detail,
                "duration_ms": int((time.perf_counter() - started) * 1000)}

    # ---- B4 断言①(写前):draft 键集 ⊆ 索引行 ID 集。writeback 对未知键静默丢弃,
    #      必须执行器自己数;未知 ID ⇒ 整批拒绝(exit 非 0,不部分写)。
    ids = _index_case_ids(root, index)
    unknown = sorted(set(draft) - ids)
    if unknown:
        return _fail_step(f"B4 断言①失败:draft 含索引不存在用例 {unknown[:5]}"
                          "(writeback 对未知键静默丢弃 ⇒ 整批拒绝;出路 = 人工经 console 核对)")

    # ---- B3:claim take → 基线 → 回填 → 复检 → release(失败路径也 release,不产残留)。
    try:
        claim_mod.take(root, index_rel, BACKFILL_TASK)
    except Exception as e:
        return _fail_step(f"claim take 失败:{e}——§5.1 停下报告,不得抢占")
    release_note = ""
    try:
        base = _ledger_signature(root)
        try:
            res = console.writeback(root, draft, apply=True, source="app")
            after = _ledger_signature(root)
        except Exception as we:
            raise RuntimeError(f"回填执行异常:{type(we).__name__}: {we}") from we
    except Exception as e:
        return _fail_step(f"{e};claim 已释放(.atlas/runs/write-claims/ 应无残留)")
    finally:
        try:
            claim_mod.release(root, index_rel, BACKFILL_TASK)
        except Exception as rel_err:
            release_note = f"(release 异常:{rel_err}——人工核对 .atlas/runs/write-claims/)"

    # ---- B4 断言②:留档逐用例表键集 == 索引改动集键集(按构造成立,断言兜底)。
    chapter = {"verify_batch": True, "file": index_rel, "task": BACKFILL_TASK,
               "cases": {c["id"]: {"ok": draft[c["id"]]["ok"], "from": c["from"],
                                   "to": c["to"]} for c in res.get("changes", [])},
               "changed": res.get("changed", 0),
               "unchanged": len(draft) - len(res.get("changes", [])),
               "ledger_before": base, "ledger_after": after}
    changed_ids = {c["id"] for c in res.get("changes", [])}
    if set(chapter["cases"]) != changed_ids:
        return _fail_step("B4 断言②失败:留档映射键集 ≠ 索引改动集键集(不可全溯 ⇒ 整批拒绝;"
                          "出路 = 人工经 console 核对索引)")

    # ---- B3 复检:尾 submit 变 ⇒ 撞窗(结构化差量;出路 = 人工经 console 重提交——
    #      重跑执行器代价 = 全量真跑且撞窗批已可能留档短路,故出自路不是「请重跑」)。
    if _submit_changed(base, after):
        collided = after.get("last_submit") or {}
        current_rows = []
        for cid in sorted(changed_ids):
            current_rows.append({"id": cid, "intended": chapter["cases"].get(cid, {}).get("to"),
                                 "current": _index_state_of(root, cid, index)})
        detail = (f"与人批撞窗:回填窗口内 events.jsonl 尾 submit 被顶掉(ts={collided.get('ts')})——"
                  f"本次回填作废性报告:意图改动 {sorted(changed_ids)};"
                  f"写后索引现值 vs 意图值 = {current_rows};"
                  "出路 = 人工经 console 重提交(不是重跑执行器:全绿批可能已留档短路;"
                  "重跑 = 全量真跑,D108 留证被清)")
        return {"name": "backfill", "status": "FAIL", "detail": detail,
                "backfill": {**chapter, "collision": True, "rows_after": current_rows},
                "duration_ms": int((time.perf_counter() - started) * 1000)}

    drift = ""
    if (base["bytes"], base["lines"]) != (after["bytes"], after["lines"]):
        drift = (";区间漂移:回填窗口内账本有非 submit 事件写入(字节 "
                 f"{base['bytes']}→{after['bytes']}),索引未被竞写,回填有效")
    status = "ok"
    detail = f"回填 {res.get('changed', 0)} 行(无改动 {chapter['unchanged']};不进评审账本){drift}{release_note}"
    return {"name": "backfill", "status": status, "detail": detail, "backfill": chapter,
            "duration_ms": int((time.perf_counter() - started) * 1000)}


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
    if any(s.get("name") == "backfill" and s.get("status") == "ok" for s in report["steps"]):
        lines += ["", "> 本批索引状态列由**执行器回填**(机器批 `verify-backfill`;标记面 = 本留档,"
                    "索引行不带机器标记,评审账本零写入——附录 B v2/D151)。"]
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
    try:
        load_layout(root)
    except LayoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
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
    rows = run.get("rows", [])
    if run["status"] == "FAIL":
        return _fail(root, steps, rows, real_run, args.json)

    # backfill = 附录 B v2(D151):全链绿批 run 后、留档前;FAIL ⇒ 停环(不落档)。
    bf = step_backfill(root)
    steps.append(bf)
    if bf["status"] == "FAIL":
        return _fail(root, steps, rows, real_run, args.json)

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
