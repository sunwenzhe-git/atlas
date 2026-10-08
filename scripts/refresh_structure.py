#!/usr/bin/env python3
"""atlas 结构事实刷新 —— 从 .trellis/spec/structure/_meta.json 重生成「指针层」（tour.md + domains/*.md）。

- 只重生成 `atlas:facts` 标记内的内容；标记外的语义内容原样保留。
- 事实表（global/*.md、*/<domain>/*.md 的表）由适配器刷新，属下一步（未接适配器时由 AI 维持）。
- **未登记漂移检测**（2026-10-04）：渲染时对既有事实表做键级对比，新增/消失的行键
  打印 ⚠ 并落 `.adapter-out/_drift.json`（下一次无漂移的 `--apply` 刷新清除；
  追加 `_drift-history.jsonl` 供收口对账），由 `atlas_check` 的「结构漂移」门读出。
- 默认 dry-run；`--apply` 写盘。预算按「每域 L1+L2 ≤ max_total_chars」校验。

用法：
    python3 refresh_structure.py --root <项目根> [--max-chars N] [--apply]
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
import time
from pathlib import Path

BEGIN = "<!-- atlas:facts:begin -->"
END = "<!-- atlas:facts:end -->"
DEFAULT_MAX_TOTAL = 9500
DEFAULT_MAX_SPEC = 9400


def log(m: str) -> None:
    print(m)


def die(m: str) -> None:
    print(f"ERROR: {m}", file=sys.stderr)
    sys.exit(1)


def load_meta(root: Path) -> dict:
    p = root / ".trellis" / "spec" / "structure" / "_meta.json"
    if not p.is_file():
        die(f"缺少 {p}")
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        die(f"无法解析 {p}: {e}")
    if not isinstance(meta.get("domains"), list):
        die(f"{p} 缺 domains[]")
    for d in meta["domains"]:
        if not (isinstance(d, dict) and d.get("id") and d.get("globs")):
            die(f"域条目非法（需 id + 非空 globs）: {d!r}")
    return meta


def read_cfg_int(root: Path, key: str, default: int) -> int:
    cfg = root / ".trellis" / "config.yaml"
    if cfg.is_file():
        try:
            m = re.search(rf"^\s*{key}:\s*(\d+)", cfg.read_text(encoding="utf-8"), re.M)
            if m:
                return int(m.group(1))
        except OSError:
            pass
    return default


def body_block(body: str) -> str:
    return f"{BEGIN}\n{body.rstrip()}\n{END}"


def merge_preserve(path: Path, fm: str, body: str) -> str:
    """frontmatter 由脚本重生成；标记内是脚本区；标记后的内容（语义区）原样保留。"""
    tail = ""
    if path.is_file():
        old = path.read_text(encoding="utf-8")
        if END in old:
            tail = old.split(END, 1)[1]
    return fm + body_block(body) + "\n" + tail.lstrip("\n")


def render_tour(meta: dict) -> tuple[str, str]:
    product = meta.get("product") or "项目"
    baseline = (meta.get("baseline") or {}).get("commit") or "N/A"
    apps = meta.get("apps") or []
    domains = meta.get("domains") or []
    fm = "---\npaths:\n  - '**'\n---\n\n"
    out = [f"# {product} · 代码导航（codebase tour）", "",
           f"> atlas 结构基线蒸馏的**入口索引**——告诉 agent **去哪读**，不复制结构事实正文。基线 `{baseline}`。", "",
           "## 项目概况", "",
           f"- 应用：{'、'.join('`%s`（%s）' % (a.get('name'), a.get('role')) for a in apps) or '—'}",
           f"- 候选域：{len(domains)}", "",
           "## 全局事实（跨域）", "",
           "| 事实 | 出处 |", "|---|---|",
           "| 目录与模块地图 | `.trellis/spec/structure/global/directory-map.md` |",
           "| 全站路由总表 | `.trellis/spec/structure/global/routes.md` |", "",
           "## 域速查表", "",
           "| 域 | 中文名 | 涉及 app | 状态 |", "|---|---|---|---|"]
    for d in domains:
        out.append(f"| `{d['id']}` | {d.get('name', '')} | {'、'.join(d.get('apps') or []) or '—'} | {d.get('status', '')} |")
    out += ["", "> 碰某域代码时，对应 `.trellis/spec/structure/domains/<domain>.md` 会自动注入，含该域结构文档链接。", "",
            "## 维护约定", "",
            "- **事实区**：标记内由 `refresh_structure.py`（`after_finish` hook）刷新。",
            "- **语义区**：标记外内容由 AI / `trellis-update-spec` 维护。",
            "- 技术栈 / 启动、测试 / 运行见项目根 `README.md`。"]
    return fm, "".join(l + "\n" for l in out)


def render_domain(root: Path, d: dict) -> tuple[Path, str, str]:
    did = d["id"]
    globs = list(d.get("globs") or [])
    apps = d.get("apps") or []
    fm = "---\npaths:\n" + "".join(f"  - '{g}'\n" for g in globs) + "---\n\n"
    out = [f"# {did} 域 · 逆向导航", "", f"> {d.get('name', '')}（{d.get('status', '')}）"]
    if apps:
        out.append(f"- 涉及应用：{'、'.join(apps)}")
    out += ["", "## 改动本域前按需 Read", ""]
    linked = False
    for role in ("current", "legacy"):
        base = root / ".trellis" / "spec" / "structure" / role / did
        files = sorted(base.glob("*.md")) if base.is_dir() else []
        if not files:
            continue
        linked = True
        out += [f"**{role}**", "", "| 文件 | 路径 |", "|---|---|"]
        for f in files:
            out.append(f"| {f.stem} | `.trellis/spec/structure/{role}/{did}/{f.name}` |")
        out.append("")
    if not linked:
        out.append("（本域暂无结构文档）")
    out += ["", "## 使用口径", "",
            "- 结构事实给**现状与契约**；方法签名 / 字段名等细节以**源码为最终真值**。",
            "- 改公共契约（API / 表结构）前，先看跨域影响。",
            "- 任务级深挖：把上表相关的 1–3 份用 Trellis `add-context` 注入 `implement.jsonl`。"]
    dst = root / ".trellis" / "spec" / "structure" / "domains" / f"{did}.md"
    return dst, fm, "".join(l + "\n" for l in out)


# ---------------- 事实区自动渲染（C7 / H1 / H2 / D69） ----------------
#
# 合并语义：**按行键的单元格级合并**——适配器只更新「可枚举列」，既有行的「语义列」保留；
# 新增行语义列留空（校验器 WARN 提示补）；消失的行从事实表移除。
# 归属：条目 source_file → 所属 app（最长 path 前缀）→ role；→ 域（最长 glob 命中）；
# 无域命中 → 落 global/<cat>-shared.md。

ROUTES_HEADER = ["应用", "页面/路由", "域", "用途", "关键交互", "实现状态", "来源文件"]
API_HEADER = ["方法", "路径", "用途", "请求要点", "响应要点", "来源模块"]
MODEL_HEADER = ["表/模型", "字段", "类型", "约束/默认", "关系", "枚举"]


def _norm(s) -> str:
    return " ".join(str(s).split())


def _lit(glob: str) -> int:
    return len(glob.replace("*", "").replace("?", ""))


def app_of(source_file: str, apps: list[dict]) -> dict | None:
    best = None
    for a in apps:
        p = (a.get("path") or "").strip("/")
        if p and (source_file == p or source_file.startswith(p + "/")):
            if best is None or len(p) > len((best.get("path") or "").strip("/")):
                best = a
    return best


def domain_of(source_file: str, domains: list[dict]) -> str | None:
    best, score = None, -1
    for d in domains:
        for g in d.get("globs") or []:
            if fnmatch.fnmatch(source_file, g) and _lit(g) > score:
                score, best = _lit(g), d["id"]
    return best


def load_adapter(p: Path) -> dict | None:
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def parse_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        body = s[1:-1] if s.endswith("|") else s[1:]
        # 单元格内的 `|` 由 render_table 转义为 `\|`（2026-10-04：字段类型 `datetime | None`
        # 一类含竖线的值曾把行撑成 7 列，被本函数静默丢弃 ⇒ 语义列合并失效 + 漂移误报）
        cells = [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", body)]
        if cells and all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append(cells)
    return rows


def old_rows_by_key(path: Path, header: list[str], keys: list[str]) -> dict:
    if not path.is_file():
        return {}
    m = re.search(re.escape(BEGIN) + r"(.*?)" + re.escape(END), path.read_text(encoding="utf-8"), re.S)
    if not m:
        return {}
    rows = parse_rows(m.group(1))
    out: dict = {}
    if rows and rows[0] == header:
        for r in rows[1:]:
            if len(r) == len(header):
                k = tuple(_norm(r[header.index(n)]) for n in keys)
                out[k] = dict(zip(header, r))
    return out


def render_table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for cells in rows:
        c = (list(cells) + [""] * len(header))[: len(header)]
        # 单元格内的裸 `|` 转义，保证「写出 ⇒ parse_rows 读回」往返一致（见 parse_rows 注）
        c = [str(x).replace("|", "\\|") for x in c]
        lines.append("| " + " | ".join(c) + " |")
    return lines


def write_facts(path: Path, body_lines: list[str], apply: bool, results: list[dict]) -> None:
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    tail = old.split(END, 1)[1].lstrip("\n") if END in old else ""
    content = f"{BEGIN}\n" + "\n".join(body_lines).rstrip("\n") + f"\n{END}\n\n{tail}"
    if not content.endswith("\n"):
        content += "\n"
    changed = content != old
    results.append({"file": str(path), "changed": changed})
    if apply and changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def merge_cells(old: dict, header: list[str], keys: list[str], enum_cols: set[str], cells: dict) -> list[str]:
    k = tuple(_norm(cells.get(n, "")) for n in keys)
    prev = old.get(k, {})
    return [cells.get(h, "") if h in enum_cols else (prev.get(h) or cells.get(h, "")) for h in header]


def diff_keys(old: dict, new_keys: list[tuple]) -> dict | None:
    """键级漂移：适配器产物相对既有事实表**新增 / 消失**的行键。无增删 ⇒ None。"""
    oldk, newk = set(old), set(new_keys)
    added, removed = sorted(newk - oldk), sorted(oldk - newk)
    if not added and not removed:
        return None
    return {"added": [" ".join(k) for k in added], "removed": [" ".join(k) for k in removed]}


def record_drift(path: Path, old: dict, new_keys: list[tuple], kind: str,
                 results: list[dict], existed: bool) -> None:
    """未登记漂移检测（gates.md §2.2「结构漂移」门，2026-10-04）。

    适配器产物与既有事实表的键级增删 = 源码结构变更未经 apply 登记的信号。
    事实文件此前不存在 = 结构环首建，全量新增是常态，不算漂移。
    只记录不阻断（变更也可能合法——登记语义归收口对账人终审）；
    标记 `.adapter-out/_drift.json` 由 `atlas_check` 的「结构漂移」门行读出。
    """
    if not existed:
        return
    d = diff_keys(old, new_keys)
    if d:
        results.append({"file": str(path), "changed": True, "drift": {"kind": kind, **d}})


def render_routes(base: Path, data: dict, apps: list[dict], domains: list[dict], apply: bool, results: list[dict]) -> None:
    path = base / "global" / "routes.md"
    enum = {"应用", "页面/路由", "实现状态", "来源文件"}
    existed = path.is_file()
    old = old_rows_by_key(path, ROUTES_HEADER, ["应用", "页面/路由"])
    rows = []
    new_keys: list[tuple] = []
    for it in data.get("items") or []:
        sf = it.get("source_file") or ""
        app = app_of(sf, apps)
        cells = {"应用": (app or {}).get("name") or "—", "页面/路由": it.get("path", ""),
                 "域": domain_of(sf, domains) or "—", "用途": "", "关键交互": "",
                 "实现状态": it.get("status") or "—", "来源文件": sf}
        rows.append(merge_cells(old, ROUTES_HEADER, ["应用", "页面/路由"], enum, cells))
        new_keys.append(tuple(_norm(cells.get(n, "")) for n in ("应用", "页面/路由")))
    write_facts(path, ["# 全站路由总表", "",
                       "> 事实区由 `refresh_structure.py` 从适配器产物刷新；语义列（域/用途/关键交互）保留既有。",
                       "> `实现状态` 仅 landing（`current/`）需要，legacy 用「—」。", ""]
                + render_table(ROUTES_HEADER, rows), apply, results)
    record_drift(path, old, new_keys, "routes", results, existed)


def role_dir(role: str) -> str:
    return "legacy" if role == "legacy" else "current"


def group_by_domain_role(items: list[dict], apps: list[dict], domains: list[dict]):
    groups: dict[tuple, list[dict]] = {}
    shared: list[dict] = []
    for it in items:
        sf = it.get("source_file") or ""
        app = app_of(sf, apps)
        dom = domain_of(sf, domains)
        if dom and app and app.get("role"):
            groups.setdefault((dom, role_dir(app["role"])), []).append(it)
        else:
            shared.append(it)
    return groups, shared


def render_apis(base: Path, items: list[dict], pointers: list[dict], apps: list[dict], domains: list[dict],
                apply: bool, results: list[dict]) -> None:
    enum = {"方法", "路径", "来源模块"}

    def cells(it: dict) -> dict:
        return {"方法": it.get("method", ""), "路径": it.get("path", ""),
                "来源模块": it.get("source_module", ""), "用途": it.get("summary") or "",
                "请求要点": "", "响应要点": ""}

    groups, shared = group_by_domain_role(items, apps, domains)
    for (dom, role), its in sorted(groups.items()):
        path = base / role / dom / "apis.md"
        existed = path.is_file()
        old = old_rows_by_key(path, API_HEADER, ["方法", "路径"])
        new_keys = [tuple(_norm(cells(it).get(n, "")) for n in ("方法", "路径")) for it in its]
        rows = [merge_cells(old, API_HEADER, ["方法", "路径"], enum, cells(it)) for it in its]
        write_facts(path, [f"# {dom} · 接口清单（{role}）", "",
                           "> 事实区自动渲染；语义列（用途/请求要点/响应要点）保留既有。", ""]
                    + render_table(API_HEADER, rows), apply, results)
        record_drift(path, old, new_keys, "apis", results, existed)
    srows = [merge_cells({}, API_HEADER, ["方法", "路径"], enum,
                         {"方法": "—", "路径": p.get("spec_entry", ""), "来源模块": p.get("app", ""),
                          "用途": "真相源入口", "请求要点": "", "响应要点": ""}) for p in pointers]
    srows += [merge_cells({}, API_HEADER, ["方法", "路径"], enum, cells(it)) for it in shared]
    if srows:
        spath = base / "global" / "apis-shared.md"
        skey_cols = ("方法", "路径")
        sexisted = spath.is_file()
        sold = old_rows_by_key(spath, API_HEADER, list(skey_cols))
        skeys = ([tuple(_norm(x) for x in ("—", p.get("spec_entry", ""))) for p in pointers]
                 + [tuple(_norm(cells(it).get(n, "")) for n in skey_cols) for it in shared])
        record_drift(spath, sold, skeys, "apis", results, sexisted)
        write_facts(spath, ["# 跨域共享接口 / 真相源入口", "",
                            "> 无 domain globs 命中、或 api 为「机器可读描述」指针形态时落此；请在域内引用或补 globs。", ""]
                    + render_table(API_HEADER, srows), apply, results)


def render_models(base: Path, items: list[dict], apps: list[dict], domains: list[dict], apply: bool, results: list[dict]) -> None:
    enum = set(MODEL_HEADER)

    def cells(it: dict) -> dict:
        return {"表/模型": it.get("table", ""), "字段": it.get("field", ""), "类型": it.get("type", ""),
                "约束/默认": it.get("constraints") or it.get("default") or "",
                "关系": it.get("relation") or "", "枚举": it.get("enum") or ""}

    groups, shared = group_by_domain_role(items, apps, domains)
    for (dom, role), its in sorted(groups.items()):
        path = base / role / dom / "data-models.md"
        existed = path.is_file()
        old = old_rows_by_key(path, MODEL_HEADER, ["表/模型", "字段"])
        new_keys = [tuple(_norm(cells(it).get(n, "")) for n in ("表/模型", "字段")) for it in its]
        rows = [merge_cells(old, MODEL_HEADER, ["表/模型", "字段"], enum, cells(it)) for it in its]
        write_facts(path, [f"# {dom} · 数据模型（{role}）", "", "> 事实区自动渲染。", ""]
                    + render_table(MODEL_HEADER, rows), apply, results)
        record_drift(path, old, new_keys, "models", results, existed)
    if shared:
        spath = base / "global" / "data-models-shared.md"
        sexisted = spath.is_file()
        sold = old_rows_by_key(spath, MODEL_HEADER, ["表/模型", "字段"])
        skeys = [tuple(_norm(cells(it).get(n, "")) for n in ("表/模型", "字段")) for it in shared]
        rows = [merge_cells({}, MODEL_HEADER, ["表/模型", "字段"], enum, cells(it)) for it in shared]
        write_facts(spath, ["# 跨域共享数据模型（无域归属）", "",
                            "> 无 domain globs 命中时落此；请在域内引用或补 globs。", ""]
                    + render_table(MODEL_HEADER, rows), apply, results)
        record_drift(spath, sold, skeys, "models", results, sexisted)


def refresh_facts(root: Path, meta: dict, apply: bool) -> list[dict]:
    base = root / ".trellis" / "spec" / "structure"
    out_dir = base / ".adapter-out"
    if not out_dir.is_dir():
        return []
    apps = meta.get("apps") or []
    domains = meta.get("domains") or []
    results: list[dict] = []

    routes = load_adapter(out_dir / "routes.json")
    if routes is not None:
        render_routes(base, routes, apps, domains, apply, results)

    api_items: list[dict] = []
    api_pointers: list[dict] = []
    model_items: list[dict] = []
    for a in apps:
        name = a.get("name")
        if not name:
            continue
        d = load_adapter(out_dir / "api" / f"{name}.json")
        if d is not None:
            if d.get("items"):
                api_items.extend(d["items"])
            elif d.get("spec_entry"):
                api_pointers.append({"app": name, "spec_entry": d["spec_entry"]})
        m = load_adapter(out_dir / "models" / f"{name}.json")
        if m is not None and m.get("items"):
            model_items.extend(m["items"])
    render_apis(base, api_items, api_pointers, apps, domains, apply, results)
    render_models(base, model_items, apps, domains, apply, results)

    # 漂移标记（gates.md §2.2「结构漂移」门）：只反映**最近一次 --apply 刷新**——
    # 有键级增删 ⇒ 写标记（并追加 history 供收口对账）；无 ⇒ 清除。dry-run 只打印不写盘。
    drifts = [r["drift"] for r in results if r.get("drift")]
    marker = out_dir / "_drift.json"
    if apply:
        out_dir.mkdir(parents=True, exist_ok=True)
        if drifts:
            payload = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "drifts": drifts}
            marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            with open(out_dir / "_drift-history.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        elif marker.exists():
            marker.unlink()
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--max-chars", type=int, default=None, help="每域 L1+L2 上限（默认读 config max_total_chars，缺省 9500）")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    meta = load_meta(root)
    max_total = args.max_chars or read_cfg_int(root, "max_total_chars", DEFAULT_MAX_TOTAL)

    outputs: list[tuple[Path, str]] = []
    tour_dst = root / ".trellis" / "spec" / "structure" / "tour.md"
    tour_fm, tour_body = render_tour(meta)
    tour = merge_preserve(tour_dst, tour_fm, tour_body)
    outputs.append((tour_dst, tour))

    over = 0
    per_spec_over = 0
    for d in meta["domains"]:
        dst, fm, body = render_domain(root, d)
        merged = merge_preserve(dst, fm, body)
        outputs.append((dst, merged))
        combined = len(tour) + len(merged)
        flag = ""
        if len(merged) > DEFAULT_MAX_SPEC:
            per_spec_over += 1
            flag = "  <-- 超单文件上限"
        if combined > max_total:
            over += 1
            flag += "  <-- L1+L2 超 budget"
        log(f"  {d['id']:<22} L2={len(merged):>5}  L1+L2={combined:>5}{flag}")

    log(f"tour.md L1 = {len(tour)} 字符 ｜ 每域上限 {max_total}")
    if per_spec_over or over:
        die(f"{per_spec_over} 个域超单文件 / {over} 个域 L1+L2 超 budget")

    # 事实区自动渲染（仅有适配器产物时）
    fact_results = refresh_facts(root, meta, args.apply)
    if fact_results:
        for r in fact_results:
            if r.get("drift"):
                continue
            log(f"  facts {'~' if r['changed'] else '='} {r['file']}")
        drifts = [r for r in fact_results if r.get("drift")]
        if drifts:
            log("  ⚠ 结构漂移（未登记键级变更；变更若已走 apply 登记可忽略，否则先补登记）：")
            for r in drifts:
                d = r["drift"]
                log(f"    {d['kind']}  +{d['added'][:3]}{'…' if len(d['added']) > 3 else ''}"
                    f"  -{d['removed'][:3]}{'…' if len(d['removed']) > 3 else ''}  ← {r['file']}")
            if not args.apply:
                log("  （dry-run 未落漂移标记；--apply 后由 atlas_check「结构漂移」门读出）")
    else:
        log("  facts: 无 .adapter-out 产物，跳过事实表（由 agent / 适配器维持）")

    if args.apply:
        for path, content in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        log(f"[written] {len(outputs)} 个指针文件")
    else:
        log("(dry-run；加 --apply 写盘)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
