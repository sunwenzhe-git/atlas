#!/usr/bin/env python3
"""atlas 共享内核 —— 父仓跨仓 E2E 单源内核（RFC-20261108-02 一期）。

职责（一期）：
- 父仓模式判定（`atlas.solution.yaml` 存在且 `mode: federated`）；
- 读父仓 `<assets_root>/e2e/e2e-index.md` 主表；
- `requirements[].case_ids` 选择器（唯一选例真相，不读 `需求` / `关联AC` 列）；
- `solution check` 的 E2E 专项检查（选择器要求 / 引用存在 / 接线 / `需求` 一致性 / 孤儿审计）；
- `atlas solution e2e init`（幂等补骨架）与 `--migrate`（批量补 `成员依赖:`）；
- `atlas solution e2e status`：二期只读聚合视图（父仓用例 + 成员本地 E2E 摘要）。

**只读**：不接管成员执行、不写成员索引/账本；成员 `review_state` 按**成员根**重算，
结果只在内存/`--json` 中展示，不落盘。唯一的写动作是显式 `--snapshot` 写父仓自己的
`<assets_root>/e2e/reviews/aggregate/`（保留名，非成员状态第二份账本）。
纯标准库；索引/分片解析复用既有校验器（同一份解析，不另写）。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _support.siblings import load_module  # noqa: E402

MANIFEST_NAME = "atlas.solution.yaml"
RESERVED_PAGE = "solution-flow"
_REQ_SPLIT = re.compile(r"[、,，\s]+")


def load_manifest_module():
    """读清单（不在此模块顶层 import `solution`，避免与它的惰性加载互相成环）。"""
    return load_module("solution")


def has_manifest(root: Path) -> bool:
    return (Path(root) / MANIFEST_NAME).is_file()


def is_solution_root(root: Path) -> bool:
    """父仓模式：`atlas.solution.yaml` 存在且 `mode: federated`（RFC §3.7）。"""
    path = Path(root) / MANIFEST_NAME
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return re.search(r"^mode:\s*federated\s*$", text, re.M) is not None


def index_path(root: Path) -> Path:
    layout = load_module("layout")
    return layout.load_layout(Path(root)).e2e_index


# ---------------------------------------------------------------- 索引读取

def read_index(root: Path) -> dict:
    """读父仓索引主表 → `{present, ok, rows}`；`rows` 为 `MAIN_COLUMNS` 字典列表。"""
    path = index_path(root)
    if not path.is_file():
        return {"present": False, "ok": False, "rows": []}
    mod = load_module("validate_e2e_index")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"present": True, "ok": False, "rows": []}
    for header, body in mod.tables(text):
        if header != mod.MAIN_COLUMNS:
            continue
        rows = []
        for raw in body:
            cells = list(raw) + [""] * (len(mod.MAIN_COLUMNS) - len(raw))
            rows.append(dict(zip(mod.MAIN_COLUMNS, cells)))
        return {"present": True, "ok": True, "rows": rows}
    return {"present": True, "ok": False, "rows": []}


# ---------------------------------------------------------------- 选择器

def requirement_rows(data: dict, rid: str) -> list[dict]:
    return [r for r in data.get("requirements") or [] if r.get("id") == rid]


def case_ids_of(rows: list[dict]) -> list[str]:
    out: list[str] = []
    for r in rows:
        for cid in r.get("case_ids") or []:
            if cid not in out:
                out.append(cid)
    return out


def selector_problem(rows: list[dict]) -> str | None:
    """选择器满足性（RFC §3.3）：多成员必须 `case_ids`（禁 `none`）；单成员二选一。

    单成员显式 `cross_repo_e2e: none` 合法，返回 `None`（由调用方判 N/A）。
    """
    if not rows:
        return "requirements 里没有该需求"
    ids = case_ids_of(rows)
    cross = any(r.get("cross_repo_e2e") == "none" for r in rows)
    if len(rows) >= 2:
        if ids:
            return None
        if cross:
            return "多成员需求禁止 cross_repo_e2e: none，必须声明 case_ids"
        return "多成员需求必须声明 case_ids"
    if ids:
        return None
    if cross:
        return None
    return "单成员需求必须二选一：case_ids 或 cross_repo_e2e: none"


def select(data: dict, rid: str, index: dict) -> dict:
    """按 `case_ids` 选父仓用例（唯一选择器；不读 `需求` / `关联AC` 列）。"""
    rows = requirement_rows(data, rid)
    problem = selector_problem(rows)
    if problem:
        return {"state": "blocked", "case_ids": case_ids_of(rows), "selected": [],
                "missing": [], "reason": problem}
    ids = case_ids_of(rows)
    if not ids:
        return {"state": "na", "case_ids": [], "selected": [], "missing": [],
                "reason": "显式声明无跨仓 E2E"}
    if not index.get("present") or not index.get("ok"):
        return {"state": "blocked", "case_ids": ids, "selected": [], "missing": [],
                "reason": "父仓 e2e-index.md 缺失或主表不可解析"}
    present = {r["用例ID"] for r in index["rows"]}
    selected = [cid for cid in ids if cid in present]
    missing = [cid for cid in ids if cid not in present]
    if missing:
        return {"state": "fail", "case_ids": ids, "selected": selected,
                "missing": missing, "reason": "case_ids 引用父仓索引不存在的用例"}
    if not selected:
        return {"state": "blocked", "case_ids": ids, "selected": [], "missing": [],
                "reason": "选择器命中 0 条"}
    return {"state": "ok", "case_ids": ids, "selected": selected, "missing": [],
            "reason": None}


# ---------------------------------------------------------------- solution check 专项

def check(root: Path, data: dict) -> dict:
    """E2E 专项检查（RFC §3.7）。返回 `checks` / 两个审计集 / 索引状态。

    跨文件检查（索引存在性 / 引用存在 / 选择器接线 / `需求` 一致性）只在这里，
    不在 `validate_manifest`（那边只做清单内文法 / 去重 / 单行 / 互斥）。
    """
    checks: list[dict] = []
    add = lambda name, status, detail: checks.append(
        {"check": name, "status": status, "detail": detail})
    index = read_index(root)
    declared = any(case_ids_of(requirement_rows(data, r["id"]))
                   for r in data.get("requirements") or [])
    if not index["present"]:
        add("父仓 E2E 索引", "FAIL" if declared else "WARN",
            "已声明 case_ids 但父仓 e2e-index.md 缺失" if declared
            else "父仓 E2E 未初始化；运行 atlas solution e2e init")
    elif not index["ok"]:
        add("父仓 E2E 索引", "FAIL",
            "父仓 e2e-index.md 主表列头不可解析；期望 "
            + "/".join(load_module("validate_e2e_index").MAIN_COLUMNS))
    else:
        add("父仓 E2E 索引", "PASS", f"{len(index['rows'])} 条用例")

    req_ids = []
    for req in data.get("requirements") or []:
        if req["id"] not in req_ids:
            req_ids.append(req["id"])
    without: list[str] = []
    for rid in req_ids:
        rows = requirement_rows(data, rid)
        problem = selector_problem(rows)
        if problem:
            without.append(rid)
            add("父仓 E2E 选择器", "FAIL", f"{rid}: {problem}")
        elif not case_ids_of(rows):
            add("父仓 E2E 选择器", "PASS", f"{rid}: N/A（显式声明无跨仓 E2E）")
        else:
            add("父仓 E2E 选择器", "PASS", f"{rid}: {len(case_ids_of(rows))} 条 case_ids")

    if index["present"] and index["ok"]:
        present = {r["用例ID"] for r in index["rows"]}
        consumers: dict[str, set[str]] = {}
        for rid in req_ids:
            for cid in case_ids_of(requirement_rows(data, rid)):
                consumers.setdefault(cid, set()).add(rid)
        # 引用存在 + 选择器接线（I7：无条件调用选择器内核并核对 selected 集合）
        missing_all: list[str] = []
        wiring_bad: list[str] = []
        for rid in req_ids:
            result = select(data, rid, index)
            if result["state"] == "fail":
                missing_all += [f"{rid}:{cid}" for cid in result["missing"]]
            if result["state"] in ("ok", "fail"):
                declared_ids = set(result["case_ids"])
                got = set(result["selected"])
                if got != declared_ids & present:
                    wiring_bad.append(f"{rid}: selected={sorted(got)}")
        add("父仓 E2E case_ids 引用", "FAIL" if missing_all else "PASS",
            f"不存在={missing_all[:8]}" if missing_all else "")
        add("父仓 E2E 选择器接线", "FAIL" if wiring_bad else "PASS",
            ("选择器未接线 / selected 与 case_ids 不一致=" + "; ".join(wiring_bad[:6]))
            if wiring_bad else "")
        # `需求` 列一致性：共享用例必须列全消费方；单消费方填了就必须相等。
        mism: list[str] = []
        for row in index["rows"]:
            cid = row["用例ID"]
            expected = consumers.get(cid, set())
            actual = {x for x in _REQ_SPLIT.split(row.get("需求") or "") if x}
            if len(expected) > 1:
                if actual != expected:
                    mism.append(f"{cid}: 期望={sorted(expected)} 实际={sorted(actual)}")
            elif len(expected) == 1:
                if actual and actual != expected:
                    mism.append(f"{cid}: 期望={sorted(expected)} 实际={sorted(actual)}")
            elif actual:
                mism.append(f"{cid}: 索引声明了未消费的需求={sorted(actual)}")
        add("父仓 E2E 需求列一致", "FAIL" if mism else "PASS", f"不一致={mism[:8]}")
        orphans = sorted(present - set(consumers))
        add("父仓 E2E 孤儿用例", "WARN" if orphans else "PASS",
            f"{len(orphans)} 条未被 case_ids 引用（不自动删）：{orphans[:8]}"
            if orphans else "")
        _ = present
    else:
        add("父仓 E2E case_ids 引用", "N/A", "父仓索引缺失，无法核对引用")
        add("父仓 E2E 选择器接线", "N/A", "父仓索引缺失，无法核对选择器")
        add("父仓 E2E 需求列一致", "N/A", "父仓索引缺失，无法核对需求列")
        add("父仓 E2E 孤儿用例", "N/A", "父仓索引缺失")
    return {"checks": checks,
            "orphan_cases": sorted(
                {r["用例ID"] for r in index["rows"]}
                - {cid for rid in req_ids
                   for cid in case_ids_of(requirement_rows(data, rid))}),
            "requirements_without_case_ids": without,
            "index": {"path": str(index_path(root)),
                      "present": index["present"], "ok": index["ok"],
                      "cases": len(index["rows"])}}


# ---------------------------------------------------------------- init / migrate

_SKELETON = """# E2E 总索引（父仓跨仓 E2E）

> 父仓跨仓用例的唯一索引；`solution-flow` 是虚拟页（跨仓流入口），不是某个成员的真实页面。
> 选择器唯一真相是 `atlas.solution.yaml` 的 `requirements[].case_ids`；`需求` / `关联AC` 只做追溯。
> 契约见 `.atlas/rings/e2e/reference.md` §10.1，口径见 `.atlas/rings/e2e/reference.md` §5。

| 用例ID | 页面 | 中文标题 | 类型 | 关联AC | 需求 | 状态 | 状态原因 | 分片 |
|---|---|---|---|---|---|---|---|---|

## 页面表（页 ↔ 路由 ↔ 实现状态 / 覆盖就绪）

| 页面 | 路由 | 域 | 实现状态 | 覆盖就绪（可选） |
|---|---|---|---|---|
| solution-flow | / | solution | 未实现 | 否 |

## 页面 ↔ 用例

| 页面 | 断言落点用例 | 链路经过用例 |
|---|---|---|
| solution-flow | | |
"""


def init(root: Path, migrate: bool = False) -> dict:
    """幂等补父仓 E2E 骨架；`--migrate` 为存量用例批量补 `成员依赖:`。"""
    root = Path(root).resolve()
    layout = load_module("layout")
    lay = layout.load_layout(root)
    for d in (lay.e2e_cases_dir, lay.e2e_scripts_dir, lay.e2e_reviews_dir):
        d.mkdir(parents=True, exist_ok=True)
    created = False
    if not lay.e2e_index.is_file():
        lay.e2e_index.parent.mkdir(parents=True, exist_ok=True)
        lay.e2e_index.write_text(_SKELETON, encoding="utf-8")
        created = True
    migrated: list[dict] = []
    if migrate:
        case_block = load_module("case_block")
        mod = load_module("validate_e2e_index")
        for md in sorted(lay.e2e_cases_dir.glob("*.md")):
            text = md.read_text(encoding="utf-8")

            def repl(match, _md=md):
                body = match.group(1)
                if not body.strip():
                    return match.group(0)
                parsed = case_block.parse_block(body)
                if "成员依赖" in case_block.block_keys(body):
                    return match.group(0)
                cid = parsed.get("id") or ""
                migrated.append({"file": _md.name, "case": cid})
                new_body = body if body.endswith("\n") else body + "\n"
                new_body += "成员依赖:\n"
                return "```atlas-case\n" + new_body + "```"

            new_text = mod.BLOCK.sub(repl, text)
            if new_text != text:
                md.write_text(new_text, encoding="utf-8")
    return {"index": str(lay.e2e_index), "created": created, "migrated": migrated}


# ---------------------------------------------------------------- status（一期最小）

_AC_COVERAGE_EMPTY = {"state": "not_ready", "ac_total": 0, "attached": 0,
                      "zero_attached": []}


def _domain_ready(index_text: str, domain: str) -> bool:
    """父仓域是否 `覆盖就绪`：域内页面全部 `已实现` 或 `覆盖就绪: 是`（RFC §3.6）。"""
    mod = load_module("validate_e2e_index")
    for header, body in mod.tables(index_text):
        names = [c.strip() for c in header]
        if not any(n.startswith("页面") for n in names):
            continue
        if not any(n.startswith("路由") for n in names):
            continue
        domain_i = next((i for i, n in enumerate(names) if n.startswith("域")), None)
        status_i = next((i for i, n in enumerate(names) if n.startswith("实现状态")), None)
        cov_i = next((i for i, n in enumerate(names) if n.startswith("覆盖就绪")), None)
        if domain_i is None or status_i is None:
            continue
        rows = []
        for raw in body:
            cells = list(raw) + [""] * (len(names) - len(raw))
            if domain not in re.split(r"\s*·\s*", cells[domain_i]):
                continue
            coverage = cells[cov_i] if cov_i is not None else ""
            rows.append(coverage == "是" or (coverage != "否"
                                             and cells[status_i] == "已实现"))
        if rows:
            return all(rows)
    return False


def _ac_coverage(root: Path | None, index: dict) -> dict:
    """父仓 AC 反向覆盖（RFC §3.6）：`ac_total` / `attached` / `zero_attached[]`。

    `state=not_ready`（骨架 `未实现` / `覆盖就绪: 否`）不参与 `verdict`。
    """
    if root is None or not index.get("present") or not index.get("ok"):
        return dict(_AC_COVERAGE_EMPTY)
    prd = load_module("layout").load_layout(Path(root)).prd_dir / "solution-prd.md"
    if not prd.is_file():
        return dict(_AC_COVERAGE_EMPTY)
    try:
        prd_text = prd.read_text(encoding="utf-8")
        index_text = index_path(root).read_text(encoding="utf-8")
    except OSError:
        return dict(_AC_COVERAGE_EMPTY)
    defs = {m.group(1) for m in
            re.finditer(r"^\|\s*`?(AC-[A-Z0-9]+-\d{3})`?\s*\|", prd_text, re.M)}
    # RFC-20261111-03 §1.6：`关联AC` 一格可持多值，按 token 拆开后再与定义集求交。
    attached = {ac for r in index["rows"]
                for ac in load_module("ac_coverage").split_acs(r.get("关联AC"))} & defs
    front = prd_text.split("---")[1] if prd_text.startswith("---") else ""
    hit = re.search(r"^domain:\s*\"?([^\s\"]+)", front, re.M)
    ready = _domain_ready(index_text, hit.group(1) if hit else "solution")
    return {"state": "ready" if ready else "not_ready",
            "ac_total": len(defs), "attached": len(attached),
            "zero_attached": sorted(defs - attached)}


# ---------------------------------------------------------------- 二期：只读聚合视图

_VIEW_KIND = "solution-e2e-readonly-view"
_READONLY_NOTE = ("只读聚合视图：成员评审以成员 events.jsonl 为准；"
                  "本文件不是任何成员状态的第二份账本。")


def _console():
    """控制台内核（Ledger / 指纹 / `case_review_state`）——单一实现，不复制第二份。"""
    return load_module("e2e_console")


def _empty_counts() -> dict:
    return {"total": 0, "green": 0, "red": 0, "blocked": 0, "skipped": 0}


def _empty_review() -> dict:
    return {"fresh": 0, "stale": 0, "unreviewed": 0, "legacy": 0}


def read_member_summary(root: Path, member: dict) -> dict:
    """成员本地 E2E 摘要（RFC §5.2）。**只读**：不执行、不写成员索引/账本。

    `state`：`ok` / `no_local_e2e` / `index_invalid` / `missing`。
    `review` 由父仓按**成员根**重算（同一 `case_review_state` 内核），不落盘。
    """
    name = member.get("name") or ""
    rel = member.get("path") or ""
    path = (Path(root) / rel).resolve()
    out = {
        "name": name, "path": rel, "state": "missing",
        "index": None, "counts": _empty_counts(), "review": _empty_review(),
        "ledger": None, "latest_seq": 0, "reason": None,
    }
    cons = _console()
    if not path.is_dir() or not cons._is_repo_root(path):
        out["reason"] = "成员路径缺失或不是 git 仓"
        return out
    lay = load_module("layout").load_layout(path)
    index = lay.e2e_index
    cases_dir = lay.e2e_cases_dir
    shards = sorted(cases_dir.glob("*.md")) if cases_dir.is_dir() else []
    out["index"] = str(index)
    out["ledger"] = str(lay.console_dir / "events.jsonl")
    if not index.is_file() and not shards:
        out.update(state="no_local_e2e", reason="成员没有本地 E2E（合法，父仓不判红）")
        return out
    parsed = read_index(path)
    if not parsed["present"] or not parsed["ok"]:
        out.update(state="index_invalid", reason="成员索引缺失或主表列头不可解析")
        return out
    mod = load_module("validate_e2e_index")
    blocks, _pages = mod.gather_shards(cases_dir) if cases_dir.is_dir() else ({}, {})
    ids = [r["用例ID"] for r in parsed["rows"]]
    if len(ids) != len(set(ids)) or set(ids) != set(blocks):
        out.update(state="index_invalid", reason="成员索引与分片用例集合不一致")
        return out
    counts = _empty_counts()
    counts["total"] = len(ids)
    for row in parsed["rows"]:
        key = row.get("状态") or ""
        if key in counts and key != "total":
            counts[key] += 1
    # 成员根指纹：只读计算；不带 `solution_root`，保持单仓语义（无 prov ⇒ legacy）。
    current = dict(cons.repo_provenance(path), **cons.review_fingerprint(path))
    ledger = cons.Ledger(path, "只读视图")
    committed = ledger.committed_snapshot("app", current)
    submits = [e for e in ledger.read()
               if e.get("kind") == "submit" and e.get("source", "prototype") == "app"]
    review = _empty_review()
    for row in parsed["rows"]:
        cid = row["用例ID"]
        snap = committed["cases"].get(cid) or {}
        state = (snap.get("review_state") or cons.case_review_state(cid, {}, current))
        key = state.get("state") if isinstance(state, dict) else "unreviewed"
        review[key if key in review else "unreviewed"] += 1
    out.update(state="ok", counts=counts, review=review, latest_seq=len(submits))
    return out


def _parent_case_rows(root: Path, index: dict, selected: list[str],
                      member_states: dict[str, dict]) -> list[dict]:
    """父仓跨仓用例：索引状态 + 父仓账本 review_state + `成员依赖` ⇒ BLOCKED。"""
    cons = _console()
    lay = load_module("layout").load_layout(root)
    blocks = {}
    if lay.e2e_cases_dir.is_dir():
        blocks, _pages = load_module("validate_e2e_index").gather_shards(lay.e2e_cases_dir)
    # 父仓根指纹：`solution_root=True` 让 `case_review_state` 走 run-time prov 的 fail-closed 分支。
    current = dict(cons.run_provenance(root), solution_root=True)
    committed = cons.Ledger(root, "只读视图").committed_snapshot("app", current)
    by_id = {r["用例ID"]: r for r in index["rows"]}
    out: list[dict] = []
    for cid in selected:
        row = by_id.get(cid, {})
        deps = list((blocks.get(cid) or {}).get("成员依赖") or [])
        blocked_by = [m for m in deps
                      if (member_states.get(m) or {}).get("state") == "missing"]
        snap = committed["cases"].get(cid) or {}
        review = snap.get("review_state") or cons.case_review_state(cid, {}, current)
        status = "blocked" if blocked_by else (row.get("状态") or "")
        out.append({
            "id": cid,
            "status": status,
            "review_state": review.get("state", "unreviewed"),
            "members": deps,
            "blocked_by_members": blocked_by,
            "status_reason": ("成员不可用：" + "、".join(blocked_by)) if blocked_by
                             else (row.get("状态原因") or ""),
            "evidence": snap.get("evidence"),
        })
    return out


def _parent_provenance(root: Path, members: list[dict]) -> dict:
    """父仓 + 成员 provenance（只读；成员缺失记 null，不猜）。"""
    cons = _console()
    prov = cons.repo_provenance(root)
    out_members = []
    for m in members:
        path = (Path(root) / (m.get("path") or "")).resolve()
        if not path.is_dir() or not cons._is_repo_root(path):
            out_members.append({"name": m.get("name"), "head": None, "app_hash": None})
            continue
        out_members.append({"name": m.get("name"), "head": cons.repo_head(path),
                            "app_hash": cons.app_fingerprint(path)})
    return {"parent": {"head": prov.get("head_sha"), "app_hash": prov.get("app_hash")},
            "members": out_members}


def write_snapshot(root: Path, payload: dict) -> Path:
    """显式写父仓只读快照：`<assets_root>/e2e/reviews/aggregate/<日期>-<REQ|ALL>.json`。

    只写父仓自己的保留目录；文件头声明只读与非第二真相源。成员文件零改动。
    """
    lay = load_module("layout").load_layout(Path(root))
    out_dir = lay.e2e_reviews_dir / "aggregate"
    out_dir.mkdir(parents=True, exist_ok=True)
    req = payload.get("requirement") or "ALL"
    path = out_dir / f"{date.today().isoformat()}-{req}.json"
    body = {"kind": _VIEW_KIND, "readonly": True, "note": _READONLY_NOTE, **payload}
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def status(data: dict, index: dict, requirement: str | None = None,
           root: Path | None = None, snapshot: bool = False) -> dict:
    """只读盘点 + 二期聚合视图；不执行、不写成员盘。

    `root` 给定时附成员摘要、父仓用例的 `review_state`（按成员根重算）与
    `parent.ac_coverage`；`snapshot=True` 才写父仓 `reviews/aggregate/` 只读快照。
    """
    req_ids = []
    for req in data.get("requirements") or []:
        if req["id"] not in req_ids:
            req_ids.append(req["id"])
    if requirement:
        if requirement not in req_ids:
            return {"requirement": requirement, "verdict": "FAIL", "exit": 1,
                    "reason": "清单里没有该 requirement", "requirements": [],
                    "members": [], "parent": {"ac_coverage": dict(_AC_COVERAGE_EMPTY)}}
        req_ids = [requirement]
    rows = []
    for rid in req_ids:
        result = select(data, rid, index)
        rows.append({"requirement": rid, **result})

    coverage = _ac_coverage(root, index)
    members: list[dict] = []
    parent_cases: list[dict] = []
    provenance: dict = {"parent": {"head": None, "app_hash": None}, "members": []}
    if root is not None:
        members = [read_member_summary(root, m) for m in data.get("members") or []]
        member_states = {m["name"]: m for m in members}
        selected = sorted({cid for r in rows for cid in r["selected"]})
        if index.get("present") and index.get("ok"):
            parent_cases = _parent_case_rows(root, index, selected, member_states)
        provenance = _parent_provenance(root, data.get("members") or [])

    states = {r["state"] for r in rows}
    case_status = [c["status"] for c in parent_cases]
    case_review = [c["review_state"] for c in parent_cases
                   if c["status"] not in ("blocked", "skipped")]
    blocked_by_member = any(c["blocked_by_members"] for c in parent_cases)
    ac_incomplete = coverage["state"] == "ready" and bool(coverage["zero_attached"])
    if "fail" in states or "red" in case_status:
        verdict, code = "FAIL", 1
    elif "blocked" in states:
        verdict, code = "BLOCKED", 3
    elif states and states <= {"na"}:
        # 单成员显式 `cross_repo_e2e: none`：N/A 单列，不显示为绿（RFC §3.6）。
        verdict, code = "N/A", 0
    elif not rows:
        verdict, code = "BLOCKED", 3
    elif root is None:
        # 无根（纯选择器单元调用）只判选择器 + AC 覆盖，保持一期可复用。
        verdict, code = ("INCOMPLETE", 0) if ac_incomplete else ("PASS", 0)
    elif blocked_by_member or any(s != "green" for s in case_status):
        verdict, code = "BLOCKED", 3
    elif any(s != "fresh" for s in case_review):
        verdict, code = "INCOMPLETE", 0
    elif ac_incomplete:
        verdict, code = "INCOMPLETE", 0
    else:
        verdict, code = "PASS", 0

    payload = {
        "schema": 1,
        "requirement": requirement, "verdict": verdict, "exit": code,
        "kind": _VIEW_KIND, "readonly": True, "note": _READONLY_NOTE,
        "requirements": rows,
        "parent": {
            "index": str(index_path(root)) if root is not None else None,
            "state": "ok" if index.get("present") and index.get("ok") else "missing",
            "case_ids": sorted({cid for r in rows for cid in r["case_ids"]}),
            "ac_coverage": coverage,
            "cases": parent_cases,
            "provenance": provenance,
        },
        "members": members,
        "case_ids": sorted({cid for r in rows for cid in r["case_ids"]}),
        "selected": sorted({cid for r in rows for cid in r["selected"]}),
    }
    if snapshot and root is not None:
        payload["snapshot"] = str(write_snapshot(root, payload))
    return payload
