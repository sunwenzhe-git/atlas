#!/usr/bin/env python3
"""atlas 结构事实刷新 —— 从 .trellis/spec/structure/_meta.json 重生成「指针层」（tour.md + domains/*.md）。

- 只重生成 `atlas:facts` 标记内的内容；标记外的语义内容原样保留。
- 事实表（global/*.md、*/<domain>/*.md 的表）由适配器刷新，属下一步（未接适配器时由 AI 维持）。
- **未登记漂移检测**（2026-10-04）：渲染时对既有事实表做键级对比，新增/消失的行键
  打印 ⚠ 并落 `.adapter-out/_drift.json`（下一次无漂移的 `--apply` 刷新清除；
  追加 `_drift-history.jsonl` 供收口对账），由 `atlas_check` 的「结构漂移」门读出。
- 默认 dry-run；`--apply` 写盘。预算按「每域 L1+L2 ≤ max_total_chars」校验。
- **单遍化（F27，2026-10-15）**：事实区先行渲染落盘，指针层（L2 链接表）后拼装
  —— 首建一遍 `--apply` 即得完整 L2 链接表（旧口径首遍空表须跑两遍）。
  已知语义：预算检查后置 ⇒ 预算 die 时事实区已落盘（部分写盘态，测试显式钉住）。
- **链式收口 `--chain`（F25，隐含 --apply）**：先按 `stack-profile.adapters` 自动执行
  非空适配器（全局类别 `routes` 跑一次；域级 `api/models/tests` 按 apps 各跑一次，
  产物落 `.adapter-out/` 既有约定路径），后执行事实/指针刷新。
  **失败语义（拍板）**：任一适配器非零退出 / 声明了适配器名但按契约解析不到脚本
  ⇒ 中止链条、不进 refresh、exit 2；中止前已落盘的产物 = 上一轮一致态，无害残留。
- **基线自进（F26，只跟随 `--chain` 路径）**：`--chain` 完成 refresh 后，四前置
  全满足才把 `_meta.json` 的 `baseline.commit` 推进到当前 HEAD——
  ① 推进判定读**本轮刚算出的漂移结果**（drift 标记写盘之后），不读上轮遗留标记；
  ② 无键级漂移；③ 至少一份适配器产物且事实结果非空（空转态不背书）；
  ④ 产品侧工作树干净（`.atlas/` `.trellis/` `product/` 之外无脏路径——给未审定
  代码背书违背诚实 ratchet）。任一不满足 ⇒ SKIP 并说明理由；冻结时可用
  `--advance-baseline` 显式越过（人工终审后通道；默认显式 `--apply` **永不**推进，
  零变化承诺保持）。SHA 比较归一化（存量存 7 位短 SHA，前缀匹配即同值）。

用法：
    python3 refresh_structure.py --root <项目根> [--max-chars N] [--apply] [--chain] [--advance-baseline]
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
import time
from pathlib import Path

BEGIN = "<!-- atlas:facts:begin -->"
END = "<!-- atlas:facts:end -->"
DEFAULT_MAX_TOTAL = 9500
DEFAULT_MAX_SPEC = 9400
# 基线自进的本地写盘豁免前缀（写盘面与装配/元数据自身不算"产品侧脏"）
# 「产品侧干净」判据的豁免前缀（F26 基线自进前置④）：这些是 atlas 自己的产物 / 中间产物，
# 不算「未审定的产品侧改动」。
# `.adapter-out/` 必须在内（2026-10-15，issue #8 移动落点后暴露）：它此前位于 `.trellis/`
# 之下、被 `.trellis/` 顺带豁免；移到项目根后若仍不豁免，atlas 自己写的中间目录就会被读成
# 「产品侧有未提交改动」⇒ **基线自进永久冻结**（比原缺陷更难察觉：门不报错，只是再也不前进）。
CLEAN_EXEMPT_PREFIXES = (".atlas/", ".trellis/", "product/", ".adapter-out/")
# 适配器四类目（shared/stack-profile.md §3.3）：routes 全局跑一次，域级按 app 各跑一次
ADAPTER_CATEGORIES = ("routes", "api", "models", "tests")
# `.adapter-out/` 的**单一位点 = 项目根**（2026-10-15 统一，issue #8）。
# 适配器产物 / 漂移标记 / 图谱新鲜度标记同址——设计档案 `docs/design/structure-ring.md`
# 的目录树从一开始写的就是项目根，实现却漂到了 `.trellis/spec/structure/` 下 ⇒ 同名两处，
# 而图谱层（`adapters/_graph.py`）写在项目根：现场于是出现「`git status` 里有
# `.adapter-out/`，漂移门却说『无 .adapter-out 产物目录』」的自相矛盾（排查者会先怀疑门坏）。
# 统一后该矛盾**构造性消失**；`atlas_check`（漂移门）与 `_graph.py`（标记）都读这一处。
# 三消费者同址由 `tests/test_refresh_facts.py::test_f41_adapter_out_single_location` 钉住。
ADAPTER_OUT_DIRNAME = ".adapter-out"


def adapter_out_dir(root: Path) -> Path:
    """适配器产物 / 漂移标记 / 图谱标记的**共同**落点（项目根，非 spec 目录）。"""
    return root / ADAPTER_OUT_DIRNAME


def log(m: str) -> None:
    print(m)


def die(m: str) -> None:
    print(f"ERROR: {m}", file=sys.stderr)
    sys.exit(1)


def load_meta(root: Path) -> dict | None:
    p = root / ".trellis" / "spec" / "structure" / "_meta.json"
    if not p.is_file():
        return None
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


def render_tour(root: Path, meta: dict) -> tuple[str, str]:
    product = meta.get("product") or "项目"
    baseline = (meta.get("baseline") or {}).get("commit") or "N/A"
    apps = meta.get("apps") or []
    domains = meta.get("domains") or []
    fm = "---\npaths:\n  - '**'\n---\n\n"
    # F29（2026-10-15）：tests 适配器产物的消费落点 = tour.md「项目概况」行
    # （tour 全量重渲不进漂移机制，"告诉 agent 去哪读"的门面文件即天然读者）。
    test_cmds: list[str] = []
    out_dir = adapter_out_dir(root)
    for a in apps:
        name = a.get("name")
        if not name:
            continue
        d = load_adapter(out_dir / "tests" / f"{name}.json")
        if d is None:
            continue
        for it in d.get("items") or []:
            rc = (it.get("run_command") or "").strip()
            if rc and rc not in test_cmds:
                test_cmds.append(rc)
    test_line = (f"\n- 测试运行方式：{'；'.join(f'`{c}`' for c in test_cmds)}"
                 f"（来源：结构适配器 tests.json）\n" if test_cmds else "")
    out = [f"# {product} · 代码导航（codebase tour）", "",
           f"> atlas 结构基线蒸馏的**入口索引**——告诉 agent **去哪读**，不复制结构事实正文。基线 `{baseline}`。", "",
           "## 项目概况", "",
           f"- 应用：{'、'.join('`%s`（%s）' % (a.get('name'), a.get('role')) for a in apps) or '—'}",
           f"- 候选域：{len(domains)}",
           test_line.rstrip("\n"), "",
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
            "- 技术栈 / 启动、测试 / 运行见 `_meta.json` 的 `truth_carriers`（缺省为项目根 `README.md`）。"]
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


# ---- 单元格「写出 ⇒ 读回」不变式（2026-10-16，issue #16；RFC-20261016-01 D84）----
#
# 病根：render_table 只转义裸 `|`，假定单元格单行；适配器给多行取值（类型字面量等）时该
# 行在盘面断成多行 ⇒ parse_rows 丢掉首行（列数不符）、跳过续行（不以竖线开头）⇒① 事实
# 丢行；② old_rows_by_key 读不回该键 ⇒ 每轮刷新都判「新增」⇒ 漂移标记常驻、baseline
# 棘轮永不释放（一个永不收敛的假告警）。
# 定案：写侧单行化（换行 → `<br>`，保留行结构而不是用空格把成员粘起来）+ 渲染即自校。
CELL_NEWLINE_RE = re.compile(r"\r\n|\r|\n")
CELL_BREAK = "<br>"


def cell_text(v) -> str:
    """单元格取值 → 单行文本（换行 → `<br>`）。「写出 ⇒ 读回」不变式的定义式一侧。"""
    return CELL_NEWLINE_RE.sub(CELL_BREAK, str(v if v is not None else ""))


def _norm(s) -> str:
    """行键归一化：`<br>` 与换行**等价**（D84；2026-10-16，issue #16）。

    缺了这条时：适配器原值（真换行）与盘面读回值（`<br>`）归一化后不等 ⇒ 键列含换行时
    `old_rows_by_key` 读不回 ⇒ 与写侧单行化要治的是同一族幻影漂移。
    """
    return " ".join(str(s).replace(CELL_BREAK, " ").split())


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


def render_table(header: list[str], rows: list[list[str]], *, where: str = "") -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    want: list[list[str]] = []
    for cells in rows:
        # 单行化（D84）：多行取值不得把一行撑成多行——盘面断行就是丢行 + 幻影漂移
        c = [cell_text(x) for x in (list(cells) + [""] * len(header))[: len(header)]]
        want.append([x.strip() for x in c])
        # 单元格内的裸 `|` 转义，保证「写出 ⇒ parse_rows 读回」往返一致（见 parse_rows 注）
        lines.append("| " + " | ".join(x.replace("|", "\\|") for x in c) + " |")
    _selfcheck_round_trip(header, want, lines, where)
    return lines


def _selfcheck_round_trip(header: list[str], want: list[list[str]], lines: list[str], where: str) -> None:
    """渲染即自校（D84 条 3）：对**渲染出的字符串**逐单元格比对，与是否写盘解耦

    （dry-run 同样出品）。取 WARN 不取硬错：本脚本是 `after_finish` hook，契约规定
    hook 失败只告警、不阻塞任务（`rings/structure/reference.md` §8）。真正会咬的门是
    同名单测——`tests/test_refresh_facts.py` 的往返用例。
    """
    got = parse_rows("\n".join(lines))[1:]          # 去掉表头行
    bad = ""
    if len(got) != len(want):
        bad = f"行数 读回={len(got)} ≠ 渲染前={len(want)}"
    else:
        for i, (g, w) in enumerate(zip(got, want), 1):
            if len(g) != len(header):
                bad = f"第 {i} 行列数 读回={len(g)} ≠ {len(header)}"
                break
            for j, (gc, wc) in enumerate(zip(g, w), 1):
                if gc != wc:
                    bad = f"第 {i} 行第 {j} 列 读回={gc!r} ≠ 期望={wc!r}"
                    break
            if bad:
                break
    if bad:
        print(f"WARN[render_table] 「写出 ⇒ 读回」不变式不成立（{where or '未命名表'}）：{bad}"
              " —— 事实区可能已损坏（丢行 / 幻影漂移）；见 RFC-20261016-01 D84", file=sys.stderr)


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


def dedup_by_row_key(cell_rows: list[dict], key_cols: list[str]) -> tuple[list[dict], list[tuple]]:
    """**按渲染行键折叠重复行**（2026-10-15 补；D69 的行键级合并以「行键唯一」为前提）。

    为何在渲染层而不是适配器里（同日复核改判，有实测依据）：适配器 `items` 的粒度 =
    **代码里的事实**——同一端点被两个域各调一次是**两条合法事实**，渲染期按 `source_file`
    分域后各自进自己的 `apis.md`（真项目实测：25 个重复（方法,路径）键**全部跨域**，
    零个落进同一张表）。在适配器里按行键全局去重，会把另一个域**唯一**的那条抹掉。
    同一个目标文件内才会出现同键（同域两个模块调同一端点；两个文件声明了同名同字段的
    模型），那里才是折叠点。保留**首个**出现（输入序 = 适配器的确定性排序）。
    """
    out: list[dict] = []
    keys: list[tuple] = []
    seen: set[tuple] = set()
    for cells in cell_rows:
        k = tuple(_norm(cells.get(n, "")) for n in key_cols)
        if k in seen:
            continue
        seen.add(k)
        out.append(cells)
        keys.append(k)
    return out, keys


def render_routes(base: Path, data: dict, apps: list[dict], domains: list[dict], apply: bool, results: list[dict]) -> None:
    path = base / "global" / "routes.md"
    enum = {"应用", "页面/路由", "实现状态", "来源文件"}
    existed = path.is_file()
    old = old_rows_by_key(path, ROUTES_HEADER, ["应用", "页面/路由"])
    items = data.get("items") or []
    if not items and existed:
        raw_rows = parse_rows(path.read_text(encoding="utf-8", errors="replace"))
        if bool(old) or len(raw_rows) >= 2:
            print("WARN: 适配器产物为空，保留既有手工事实")
            return
    cell_rows: list[dict] = []
    for it in items:
        sf = it.get("source_file") or ""
        app = app_of(sf, apps)
        cell_rows.append({"应用": (app or {}).get("name") or "—", "页面/路由": it.get("path", ""),
                          "域": domain_of(sf, domains) or "—", "用途": "", "关键交互": "",
                          "实现状态": it.get("status") or "—", "来源文件": sf})
    cds, new_keys = dedup_by_row_key(cell_rows, ["应用", "页面/路由"])
    rows = [merge_cells(old, ROUTES_HEADER, ["应用", "页面/路由"], enum, c) for c in cds]
    write_facts(path, ["# 全站路由总表", "",
                       "> 事实区由 `refresh_structure.py` 从适配器产物刷新；语义列（域/用途/关键交互）保留既有。",
                       "> `实现状态` 仅 landing（`current/`）需要，legacy 用「—」。", ""]
                + render_table(ROUTES_HEADER, rows, where="global/routes.md"), apply, results)
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
        cds, new_keys = dedup_by_row_key([cells(it) for it in its], ["方法", "路径"])
        rows = [merge_cells(old, API_HEADER, ["方法", "路径"], enum, c) for c in cds]
        write_facts(path, [f"# {dom} · 接口清单（{role}）", "",
                           "> 事实区自动渲染；语义列（用途/请求要点/响应要点）保留既有。", ""]
                    + render_table(API_HEADER, rows, where=f"{role}/{dom}/apis.md"), apply, results)
        record_drift(path, old, new_keys, "apis", results, existed)
    scell_rows = [{"方法": "—", "路径": p.get("spec_entry", ""), "来源模块": p.get("app", ""),
                   "用途": "真相源入口", "请求要点": "", "响应要点": ""} for p in pointers]
    scell_rows += [cells(it) for it in shared]
    scds, skeys = dedup_by_row_key(scell_rows, ["方法", "路径"])
    srows = [merge_cells({}, API_HEADER, ["方法", "路径"], enum, c) for c in scds]
    if srows:
        spath = base / "global" / "apis-shared.md"
        sexisted = spath.is_file()
        sold = old_rows_by_key(spath, API_HEADER, ["方法", "路径"])
        record_drift(spath, sold, skeys, "apis", results, sexisted)
        write_facts(spath, ["# 跨域共享接口 / 真相源入口", "",
                            "> 无 domain globs 命中、或 api 为「机器可读描述」指针形态时落此；请在域内引用或补 globs。", ""]
                    + render_table(API_HEADER, srows, where="global/apis-shared.md"), apply, results)


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
        cds, new_keys = dedup_by_row_key([cells(it) for it in its], ["表/模型", "字段"])
        rows = [merge_cells(old, MODEL_HEADER, ["表/模型", "字段"], enum, c) for c in cds]
        write_facts(path, [f"# {dom} · 数据模型（{role}）", "", "> 事实区自动渲染。", ""]
                    + render_table(MODEL_HEADER, rows, where=f"{role}/{dom}/data-models.md"), apply, results)
        record_drift(path, old, new_keys, "models", results, existed)
    if shared:
        spath = base / "global" / "data-models-shared.md"
        sexisted = spath.is_file()
        sold = old_rows_by_key(spath, MODEL_HEADER, ["表/模型", "字段"])
        scds, skeys = dedup_by_row_key([cells(it) for it in shared], ["表/模型", "字段"])
        rows = [merge_cells({}, MODEL_HEADER, ["表/模型", "字段"], enum, c) for c in scds]
        write_facts(spath, ["# 跨域共享数据模型（无域归属）", "",
                            "> 无 domain globs 命中时落此；请在域内引用或补 globs。", ""]
                    + render_table(MODEL_HEADER, rows, where="global/data-models-shared.md"), apply, results)
        record_drift(spath, sold, skeys, "models", results, sexisted)


def load_adapters_profile(root: Path) -> dict[str, str | None]:
    """读 stack-profile 顶层 `adapters:` 段（`key: value|null`；契约 shared/stack-profile.md §3）。

    与 `_lib.load_apps` 同一手写行级解析口径（不引第三方 YAML）；键闭集 = ADAPTER_CATEGORIES。
    """
    p = root / "product" / "stack-profile.yaml"
    out: dict[str, str | None] = {}
    if not p.is_file():
        return out
    in_section = False
    for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = re.sub(r"\s+#.*$", "", raw.rstrip())
        s = line.strip()
        if not s:
            continue
        if not line[:1].isspace():
            in_section = s.rstrip(":") == "adapters" and s.endswith(":") or s == "adapters:"
            if in_section and not s.endswith(":"):
                in_section = False  # `adapters: {…}` 行内形态不在本解析范围内
            continue
        if not in_section:
            continue
        m = re.match(rf"^({'|'.join(ADAPTER_CATEGORIES)})\s*:\s*(.+?)\s*$", s)
        if m:
            v = m.group(2).strip().strip("'\"")
            out[m.group(1)] = None if v in ("null", "~", "") else v
    return out


def run_chain(root: Path, meta: dict) -> int:
    """F25 链式收口：按 `stack-profile.adapters` 执行非空适配器（routes 全局一次，
    api/models/tests 按 app 各跑一次；产物路径按 `.adapter-out/` 既有约定）。

    失败语义（拍板，C3）：适配器非零退出 / 声明了适配器名但按契约 §3.3 三级解析失
    败 ⇒ 中止链条、不进 refresh、exit 2；中止前已落盘产物 = 上一轮一致态，残留无害。
    """
    adapters = load_adapters_profile(root)
    if not any(v is not None for v in adapters.values()):
        log("  chain: profile 未声明非空 adapters ⇒ 跳过适配器执行（事实区由 agent 维持）")
        return 0
    out_dir = adapter_out_dir(root)
    apps = [a["name"] for a in (meta.get("apps") or []) if a.get("name")]
    for cat, name in ((c, adapters.get(c)) for c in ADAPTER_CATEGORIES):
        if not name:
            continue
        # 解析顺序（契约 §3.3）：.atlas/adapters/<名> → .atlas/adapters/<名>.py → 目标项目根同名可执行
        script = root / ".atlas" / "adapters" / name
        script_py = Path(f"{script}.py")
        project_root = root / name
        if script_py.is_file():
            cmd = [sys.executable, str(script_py)]
        elif script.is_file():
            cmd = [str(script)]
        elif project_root.is_file():
            cmd = [str(project_root)]
        else:
            print(f"ERROR: chain: 适配器 {cat}={name!r} 解析失败（.atlas/adapters/<名>(.py) 与项目根皆缺）——"
                  "中止链条不进 refresh（先装配 .atlas/adapters）", file=sys.stderr)
            return 2
        if cat == "routes":
            targets: list[tuple[str | None, Path]] = [(None, out_dir / "routes.json")]
        elif not apps:
            log(f"  chain: {cat} 有适配器但 apps 为空 ⇒ 无执行对象，跳过")
            continue
        else:
            targets = [(a, out_dir / cat / f"{a}.json") for a in apps]
        for app, out_path in targets:
            full = list(cmd) + ["--root", str(root)]
            if app is not None:
                full += ["--app", app]
            full += ["--out", str(out_path)]
            r = subprocess.run(full, capture_output=True, text=True)
            if r.returncode != 0:
                tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["(无输出)"]
                print(f"ERROR: chain: 适配器 {cat}{'@' + app if app else ''} exit {r.returncode}：{tail[0]}——"
                      "中止链条不进 refresh", file=sys.stderr)
                return 2
            log(f"  chain {cat}{'@' + app if app else ''} → {out_path.relative_to(root)}")
    return 0


def _git(root: Path, *argv: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(["git", "-C", str(root), *argv], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    if r.returncode != 0:
        return False, ""
    return True, r.stdout.strip()


def maybe_advance_baseline(root: Path, meta: dict, fact_results: list[dict],
                           drifts: list[dict], override: bool) -> None:
    """F26 基线自进（只由 --chain / 显式 --advance-baseline 通道调用）。

    四前置（docstring 与方案 §1.2）：本轮 drift 已写盘（调用时序由 main 保证）/ 零漂移
    （override 显式越过）/ 事实结果非空 / 产品侧干净。SHA 前缀归一比较。
    """
    if drifts and not override:
        log("  baseline: 存在未终审键级漂移 ⇒ 冻结待终审（诚实 ratchet；--advance-baseline 可显式越过）")
        return
    if not fact_results:
        log("  baseline: 无适配器产物参与渲染（空转态）⇒ 不推进（不给半装配态背书）")
        return
    ok, cur = _git(root, "rev-parse", "HEAD")
    if not ok:
        log("  baseline: git HEAD 不可得 ⇒ SKIP 推进")
        return
    ok2, porcelain = _git(root, "status", "--porcelain")
    if ok2:
        dirty = []
        for line in porcelain.splitlines():
            # v1 格式 `XY path`：_git 的 .strip() 会吃掉首行前导空格 ⇒ 不能盲切 [3:]，
            # 按状态字符扫描到 path 起点（行首空格跳2位即可见 path）。
            i = 0
            while i < len(line) and line[i] == " ":
                i += 1
            i += 2  # 跳过两位状态字符
            while i < len(line) and line[i] == " ":
                i += 1
            rest = line[i:]
            if rest and not rest.startswith(CLEAN_EXEMPT_PREFIXES):
                dirty.append(rest)
        if dirty:
            log(f"  baseline: 产品侧工作树有未提交改动（{dirty[:3]}…）⇒ 不推进（不给未审定代码背书）")
            return
    cur = cur.splitlines()[0] if cur else ""
    old = (meta.get("baseline") or {}).get("commit") or ""
    if old and (cur == old or cur.startswith(old) or old.startswith(cur)):
        log(f"  baseline: 已与当前 HEAD 对齐（{old}）⇒ 不重复推进")
        return
    branch = (meta.get("baseline") or {}).get("branch") or ""
    ok3, abbrev = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    branch = abbrev or branch
    meta["baseline"] = {"branch": branch, "commit": cur}
    meta_path = root / ".trellis" / "spec" / "structure" / "_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"  advanced baseline → {cur[:12]}（ {_meta_note()}）")


def _meta_note() -> str:
    return "语义：baseline = facts 所描述代码态所在 commit；_meta.json 落其后"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--max-chars", type=int, default=None, help="每域 L1+L2 上限（默认读 config max_total_chars，缺省 9500）")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--chain", action="store_true",
                    help="链式收口（F25，隐含 --apply）：先执行非空适配器后刷新；任一失败 ⇒ 中止 exit 2")
    ap.add_argument("--advance-baseline", action="store_true",
                    help="显式越过漂移冻结推进 baseline（F26 人工通道；默认仅 --chain 自动推进）")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    meta = load_meta(root)
    if meta is None:
        log("SKIP: 缺少 .trellis/spec/structure/_meta.json（结构环尚未首建，跳过结构事实刷新）")
        return 0
    max_total = args.max_chars or read_cfg_int(root, "max_total_chars", DEFAULT_MAX_TOTAL)
    apply = args.apply or args.chain

    # F25 链式先行：适配器产物齐了，本轮事实才拿得到最新代码结构
    if args.chain:
        rc = run_chain(root, meta)
        if rc != 0:
            return rc

    # F27 单遍化：事实区先渲染落盘（apply 时），指针层（L2 链接表）后拼装
    # ⇒ 首建一遍即得完整 L2 链接表。已知语义：预算 die 时事实区已落盘（部分写盘态）。
    fact_results = refresh_facts(root, meta, apply)
    if fact_results:
        drifts = [r["drift"] for r in fact_results if r.get("drift")]
        for r in fact_results:
            if r.get("drift"):
                continue
            log(f"  facts {'~' if r['changed'] else '='} {r['file']}")
        if drifts:
            log("  ⚠ 结构漂移（未登记键级变更；变更若已走 apply 登记可忽略，否则先补登记）：")
            for d in drifts:
                log(f"    {d['kind']}  +{d['added'][:3]}{'…' if len(d['added']) > 3 else ''}"
                    f"  -{d['removed'][:3]}{'…' if len(d['removed']) > 3 else ''}  ←（键级变更）")
        else:
            log("  facts: 无键级漂移（本轮巧取无漂移态；--chain 会在此后推进 baseline）")
    else:
        drifts = []
        log("  facts: 无 .adapter-out 产物，跳过事实表（由 agent / 适配器维持）")

    outputs: list[tuple[Path, str]] = []
    tour_dst = root / ".trellis" / "spec" / "structure" / "tour.md"
    tour_fm, tour_body = render_tour(root, meta)
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

    if apply:
        for path, content in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        log(f"[written] {len(outputs)} 个指精准文件")
    else:
        log("(dry-run；加 --apply 写盘)")

    # F26：基线自进只在 --chain（或显式 --advance-baseline）通道且本轮 apply 时发生；
    # 显式 `--apply` 默认永不推进（零变化承诺）。dry-run 不推进。
    if apply and (args.chain or args.advance_baseline):
        maybe_advance_baseline(root, meta, fact_results, drifts, args.advance_baseline)
    elif not apply and args.advance_baseline:
        log("baseline: dry-run 不推进（--apply 后重跑生效）")
    return 0


def refresh_facts(root: Path, meta: dict, apply: bool) -> list[dict]:
    """事实区自动渲染（适配器产物 → atlas:facts 区；产物路径见 render_* 家族）。

    返回 results；调用方由结果派生 drifts（本轮最新判定，绝不读上轮遗留标记——F26 前置①）。
    """
    base = root / ".trellis" / "spec" / "structure"
    out_dir = adapter_out_dir(root)
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


if __name__ == "__main__":
    sys.exit(main())
