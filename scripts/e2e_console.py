#!/usr/bin/env python3
"""E2E 用例评审控制台 —— 随 atlas 包分发的本地小服务（纯标准库）。

本文件在 `.atlas/scripts/e2e_console.py`；静态资源在 `.atlas/templates/e2e/console/`；
项目侧只保留账本 `product/e2e/reviews/console/`（运行时产物，不进包）。

一张 4 列的表，逐条执行、逐条人工评审：

| 用例分类 | 用例描述 | 执行用例 | 人工 review 用例 |

读写边界（**单写者 + 提交才落盘**）：

* 只**读**用例真相源 `product/e2e/e2e-index.md` + `product/e2e/cases/*.md`；
  分片解析沿用 `.atlas/validators/validate_e2e_index.py`（不另写第二份格式解析）。
* **执行与勾选先只改页面本地状态**（存浏览器 `localStorage`，刷新不丢；用户 2026-09-23 定「乙」），
  **不**写任何服务端文件。
* 点「提交」才**一次性**落两处：① 账本 `product/e2e/reviews/console/events.jsonl` 追加**一条快照**
  （append-only，唯一真相源；含每条的执行结果与评审态及时间）并派生人读的 `ledger.md`；
  ② 回写索引 `e2e-index.md` 的 `状态` 一列（先给预览、确认后写）。
* 不提交 ⇒ 服务端什么都不知道（这是「乙」的取舍：账本简洁，但过程只在页面里）。
* **来源（单一靶场，E1）**：`app`（真实应用，`e2e.app_base_url`）。索引回写：通过 → `green`、失败 → `red`（`prototype-pass` 为 E0 历史终态，不再产生；旧账本里 `source=prototype` 的事件仍可读）。
  `e2e.app_base_url` 为 `null` 时「真实应用」不可执行——契约要求向用户索取，不猜默认。

执行语义：

* 「执行用例」= 起一次**有头**子进程跑这一条（node 单轨：`<e2e.node_modules>/.bin/playwright test
  -c playwright.config.ts <file>:<line> --headed`；慢动作经 `ATLAS_SLOWMO` 注入生成配置的
  `launchOptions.slowMo`（Playwright `test` CLI 无 `--slowmo` 旗标，2026-10-14 F11）；
  「跑完留窗 + 结果哨兵」由生成物 `atlas-hold.ts` 承载——契约 `rings/e2e/reference.md` §10.1）；
* **并发 = 1**（同时只跑一条，其余按钮禁用）；单条 wall-clock 超时到点 kill 并如实报「超时」；
* **留窗不被运行器超时掐断**（2026-10-21，D126）：持窗模式给 playwright 传 `--timeout=0`——
  其默认 30s test timeout **计入 fixture teardown**，会把「等人工关窗」判超时并在约 30s 处
  强制关窗（现场：执行完毕后浏览器仍自动关闭）；控制台的 `--timeout` 是唯一超时真相源；
* **数据准备钩子**（2026-10-18，D110；2026-10-20，D121 补用例上下文）：项目自带
  `product/e2e/scripts/atlas-prepare.mjs` ⇒ 每条用例执行前先跑它（失败/超时 ⇒ 拒绝执行并
  如实上报，见契约 §10「执行」）；运行时经 `ATLAS_CASE_ID` 传入当前用例 ID，项目脚本可据此
  只准备该用例依赖的数据（不读该变量的存量脚本行为不变）；
* 「人工 review 通过」= 人工复核**执行结果**符合业务预期；只在**执行通过**后解锁按钮
  （不通过就是没通过，回对话改用例）。
* **起跑前置判据**（2026-10-20，D124）：运行器可解析之外还须**浏览器就绪**——playwright 自算的
  chromium 可执行路径存在，或 `ATLAS_PLAYWRIGHT_CHANNEL` 已设（走系统通道浏览器）；npm 装包不自动
  下载浏览器，缺 ⇒ 起跑前诚实拒绝（与 `atlas_check`「E2E 真跑」门同一内核 `_support/pw_runner.py`）。

用法：

    python3 .atlas/scripts/e2e_console.py [--root .] [--port 4190] [--slowmo 500] [--timeout 120] [--no-head]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
import urllib.parse
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 随包运行时：HERE = <项目>/.atlas/scripts ⇒ 静态资源在 <项目>/.atlas/templates/e2e/console/
ASSETS = Path(os.environ.get("ATLAS_CONSOLE_ASSETS") or (HERE.parent / "templates" / "e2e" / "console"))
DEFAULT_ROOT = Path.cwd()
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}

# 随包内核引导（`_support/`，2026-10-12 单源批）：模块加载收敛为单源实现；
# `prefer_root` 保控制台既有「项目 .atlas 优先、随包同级回落」语义。
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))
from _support.siblings import load_module  # noqa: E402
from _support.manual_block import parse_manual  # noqa: E402
from _support.layout import LayoutError, load_layout  # noqa: E402

# 用例 ID 文法体单源（正文归 rings/e2e/reference.md §5.3）；锚点在使用处自留。
case_id = load_module("case_id")

# node 运行器单源内核（二进制解析 / **可解析性判据** / 全局兜底修复；issue #24）：
# `atlas_check` 真跑门与本月控制台共用同一实现 —— 此前两处各存一份拷贝。
pw_runner = load_module("pw_runner")
# 宿主注入型 base query（issue #27 / D104）：单源 `_support/url_merge.py`。
url_merge = load_module("url_merge")


# ---------------------------------------------------------------- 代码提交与生成脚本指纹（D128）

def _git_output(root: Path, *args: str) -> str | None:
    try:
        res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return None


def repo_head(root: Path) -> str | None:
    return _git_output(root, "rev-parse", "HEAD")


def repo_git_dirty(root: Path) -> bool | None:
    out = _git_output(root, "status", "--porcelain")
    return None if out is None else bool(out.strip())


def scripts_hash(root: Path) -> str | None:
    """计算当前 E2E 生成脚本与前置准备钩子的内容散列（16 字符前缀）。

    白名单：`product/e2e/scripts/` 下源码脚本（ts/js/mjs/json/yaml/yml），
    以及可选的项目级数据准备钩子 `atlas-prepare.mjs`。
    严格排除运行时产物（test-results/、playwright-report/、.atlas-auth/、node_modules/、trace、png 等），
    确保执行产物不导致指纹假漂移。
    """
    s_dir = load_layout(root).e2e_scripts_dir
    if not s_dir.is_dir():
        return None
    h = hashlib.sha256()
    files: list[tuple[str, Path]] = []
    for p in sorted(s_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(s_dir).as_posix()
        if any(part in rel for part in ("test-results", "playwright-report", ".atlas-auth", "node_modules")):
            continue
        if rel.endswith((".trace", ".png", ".webm", ".last-run.json")):
            continue
        if rel.endswith((".ts", ".js", ".mjs", ".json", ".yaml", ".yml")):
            files.append((f"scripts/{rel}", p))
    for prep in (s_dir / "atlas-prepare.mjs", root / "atlas-prepare.mjs"):
        if prep.is_file():
            files.append(("atlas-prepare.mjs", prep))
            break
    if not files:
        return None
    for rel, p in files:
        h.update(rel.encode("utf-8"))
        try:
            h.update(p.read_bytes())
        except Exception:
            pass
    return h.hexdigest()[:16]


def repo_provenance(root: Path) -> dict:
    """提取当前工作区的代码提交与测试脚本指纹，供评审账本留痕与陈旧度（stale）判定。"""
    head = repo_head(root)
    dirty = repo_git_dirty(root)
    shash = scripts_hash(root)
    actor_type = os.environ.get("ATLAS_ACTOR_TYPE", "human")
    if actor_type not in ("human", "agent"):
        actor_type = "unknown"
    return {
        "head_sha": head,
        "head_short": head[:7] if head else None,
        "git_dirty": dirty,
        "scripts_hash": shash,
        "actor_type": actor_type,
    }


def case_review_state(snap: dict, current: dict | None) -> dict:
    """计算单个用例在当前代码/脚本下的评审新鲜度。

    状态闭集：
      - unreviewed: 尚未标记评审通过
      - fresh: 评审指纹与当前 HEAD 及生成脚本一致（有效评审）
      - stale: 评审后 HEAD 或生成脚本已变化（需重跑/重审）
      - legacy: 历史账本条目无提交指纹（来源无法验证）
    """
    reviewed = snap.get("reviewed") or {}
    if not reviewed.get("pass"):
        return {"state": "unreviewed", "reason": "未评审"}
    prov = snap.get("prov")
    if not prov or not isinstance(prov, dict) or (not prov.get("head_sha") and not prov.get("scripts_hash")):
        return {"state": "legacy", "reason": "历史快照无提交指纹，需重审"}
    if current is None:
        return {"state": "legacy", "reason": "未提供当前工作区指纹，新鲜度无法核验"}
    mismatches = []
    cur_head = current.get("head_sha")
    old_head = prov.get("head_sha")
    if cur_head and old_head and cur_head != old_head:
        mismatches.append(f"HEAD变动({old_head[:7]}→{cur_head[:7]})")
    cur_shash = current.get("scripts_hash")
    old_shash = prov.get("scripts_hash")
    if cur_shash and old_shash and cur_shash != old_shash:
        mismatches.append(f"脚本变动({old_shash[:6]}→{cur_shash[:6]})")
    if mismatches:
        return {"state": "stale", "reason": "；".join(mismatches), "prov": prov}
    warning = "提交时工作区有未提交改动（dirty），提交后请先落库" if prov.get("git_dirty") else None
    res = {"state": "fresh", "prov": prov}
    if warning:
        res["warning"] = warning
    return res


# ---------------------------------------------------------------- 用例真相源（只读）

def load_validator(root: Path):
    """复用 E2E 环校验器的分片/索引解析器（同一份格式解析，不另写）。"""
    return load_module("validate_e2e_index", prefer_root=root)


PROTO_DEFAULT = "http://127.0.0.1:4173"


class SnapshotError(RuntimeError):
    """用例真相源读不出来（列头与契约不一致等）——必须上报，不得静默降级为空列表。"""


def load_profile_parser(root: Path):
    """复用随包内核的 profile 解析器（同一份格式解析，不另写）。

    优先读项目根下的 `.atlas/_support/stack_profile.py`（部署副本 = 随包时同物）；
    若为临时/独立运行目录，回落至本控制台所在包（随包同级分发）。
    """
    return load_module("stack_profile", prefer_root=root)


def read_manual(root: Path) -> list[dict]:
    """手工走查项（product/e2e/manual.md，用户 2026-10-01 设计）：控制台「手工」类型承载。

    兼容旧单行格式与 D143 `atlas-manual` 结构化块（解析单源 `_support/manual_block.py`）；
    执行 = 开浏览器到对应页面，其余人工。文件缺失 = 空清单（手工面是可选增强）。
    """
    path = load_layout(root).e2e_manual
    if not path.is_file():
        return []
    return parse_manual(path.read_text(encoding="utf-8"))


def manual_open_url(root: Path, route: str) -> str:
    """手工项「打开」用的**绝对地址**（issue #27 / D104）。

    旧实现是 `base.rstrip("/") + route` 字符串拼接 —— base 一旦带 query（宿主注入型前提，
    如 `?switchAgent=7202`）必产畸形 URL（`…?switchAgent=7202/console/#/…`）；路径形态路由
    （`/console/#/…`）也会被拼成 `<base>/console/#/…` 的双前缀。改为 origin + 合并后的路径。
    """
    base = (read_sources(root).get("app", {}) or {}).get("base_url") or ""
    return url_merge.origin_of(base) + url_merge.merge_base_query(route, base)


def page_routes(root: Path) -> dict:
    """页面表（页 ↔ 路由唯一真相源）解析：供手工项「打开」跳转。"""
    path = load_layout(root).e2e_index
    routes: dict[str, str] = {}
    if not path.is_file():
        return routes
    in_table = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## 页面表"):
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if in_table and line.startswith("|") and not line.startswith("| 页面") and "---" not in line:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0] and cells[1].startswith("/"):
                routes[cells[0]] = cells[1]
    return routes


def _e2e_section(prof: dict) -> dict:
    """取 `e2e` 段；非映射形态（如行内流式写法）按**未声明**处理。

    契约口径 = 段缺失 / `e2e: null` = 合法降级（`shared/stack-profile.md` §2）；
    内核解析器对顶层 `key: value` 标量行按校验器口径落成字符串，这里如实归一到降级面。
    """
    e2e = prof.get("e2e")
    return e2e if isinstance(e2e, dict) else {}


def read_sources(root: Path) -> dict:
    """唯一来源（靶场，E1 单段）与它的 baseURL。地址的唯一来源是 stack-profile.yaml。"""
    profile = load_layout(root).stack_profile
    prof = load_profile_parser(root).parse_profile(profile.read_text(encoding="utf-8"))
    app = _e2e_section(prof).get("app_base_url")
    return {
        "app": {"label": "真实应用", "base_url": app, "configured": bool(app),
                "why": "真实应用（e2e.app_base_url）为 null ⇒ 契约要求向用户索取，不猜默认" if not app
                       else "真实应用（e2e.app_base_url）"},
    }


def snapshot(root: Path) -> dict:
    """读出 44 条用例及其描述（描述来自分片，不另抄一份）。

    列头对不上契约时**大声报错**，不静默给空列表：
    2026-09-23 实测过这个坑 —— 契约去列后，旧进程把「看不到列头」当成「索引里没有这条用例」，
    前端只看到「未启动：索引里没有 E2E-LOGIN-002」，真因（列头与契约不一致）完全不可见。
    """
    mod = load_validator(root)
    try:
        lay = load_layout(root)
    except LayoutError as exc:
        raise SnapshotError(str(exc)) from exc
    e2e = lay.e2e_dir
    index = lay.e2e_index
    if not index.is_file():
        raise SnapshotError(
            f"索引文件缺失: {index} 不存在。请先准备 {lay.print_value('e2e')}/e2e-index.md 再启动控制台。")
    blocks, _pages = mod.gather_shards(e2e / "cases")

    rows: list[dict] = []
    header: list[str] = []
    heads: list[list[str]] = []
    for head, body in mod.tables(index.read_text(encoding="utf-8")):
        heads.append(head)
        if head == mod.MAIN_COLUMNS:
            header, rows = head, body
            break
    if not header:
        raise SnapshotError(
            "索引主表列头与契约不一致，无法读取用例："
            f"实际={heads[0] if heads else '(无表格)'}；期望={mod.MAIN_COLUMNS}。"
            "先对齐 " + lay.print_value("e2e_index") + "；改过契约 / 校验器后必须重启本控制台。")
    idx = {name: i for i, name in enumerate(header)}

    cases = []
    for r in rows:
        cid = r[idx["用例ID"]]
        blk = blocks.get(cid, {})
        cases.append({
            "id": cid,
            "page": r[idx["页面"]],
            "title": r[idx["中文标题"]],
            "type": r[idx["类型"]],
            "ac": r[idx["关联AC"]],
            "need": r[idx["需求"]],
            "status": r[idx["状态"]],
            "reason": r[idx["状态原因"]],
            "shard": r[idx["分片"]],
            "intent": blk.get("intent", ""),
            "pages": blk.get("pages", []),
            "precondition": blk.get("precondition", []),
            "step": blk.get("step", []),
            "expected": blk.get("expected", []),
            "testid": blk.get("testid", []),
            # 契约 §5.8（2026-10-12）：mock 行随分片带给前端渲染 MOCKED 徽标（桩披露，静态事实）
            "mock": blk.get("mock", []),
            # 契约 §5.5（2026-10-21，D130）：前端覆盖维度（C01-C14）
            "dimensions": blk.get("覆盖维度", []),
        })
    return {"cases": cases, "nodeids": node_ids(e2e / "scripts")}


def node_ids(scripts_dir: Path) -> dict:
    """用例 ID → playwright 测试引用 `<file>.spec.ts:<line>`（从生成脚本里读，不猜）。

    node 单轨（3507 BO，2026-10-12 控制台迁移批）：解析 `.spec.ts` 里 `test('<ID> …')`
    的**行号**——`file:line` 是 playwright 的原生过滤形态（`--list` 输出同款）。
    blocked / skipped 用例生成物为 `test.skip(` ⇒ 天然不匹配（本就无可执行测试）；
    零步基线 `test('test_<page>__…')` 不带用例 ID 前缀 ⇒ 同样不匹配。
    """
    out: dict[str, str] = {}
    if not scripts_dir.is_dir():
        return out
    for ts in sorted(scripts_dir.glob("*.spec.ts")):
        for lineno, line in enumerate(ts.read_text(encoding="utf-8").splitlines(), start=1):
            m = re.match(rf"\s*test\(['\"]({case_id.GRAMMAR})[ '\"].*async", line)
            if m:
                out[m.group(1)] = f"{ts.name}:{lineno}"
    return out


def resolve_pw(root: Path, *, repair: bool = False) -> tuple[Path | None, Path | None, str, str]:
    """node 单轨运行器解析 —— **单源内核** `_support/pw_runner.py`（与 `atlas_check`「E2E 真跑」门
    同一个 `resolve` / `probe` / `ensure_resolvable`，不造第二份）。

    → `(pw_bin, nm_dir, why, note)`；`why` 非空 ⇔ 不可用（控制台如实拒绝，不静默降级）。

    `repair=True`（**执行器侧**，issue #24）：判据本体 = 「从 `product/e2e/scripts/` 出发
    `@playwright/test` 可解析」，不成立时按内核走**幂等修复 + 复检**（仅当运行器来自全局兜底）。
    `note` = 运行器来自全局兜底时的标准说明（**每次都给**——「用了机器全局状态」是跑的前提事实），
    **调用方必须输出**。
    """
    lay = load_layout(root)
    profile = lay.stack_profile
    if not profile.is_file():
        return None, None, f"无 {lay.print_value('stack_profile')}", ""
    prof = load_profile_parser(root).parse_profile(profile.read_text(encoding="utf-8"))
    nm = _e2e_section(prof).get("node_modules")
    pw_bin, nm_dir, source, why = pw_runner.resolve(root, str(nm) if nm else None)
    if pw_bin is None:
        return None, None, why, ""
    if not repair:
        return pw_bin, nm_dir, "", ""
    scripts = lay.e2e_scripts_dir
    status, detail, note = pw_runner.ensure_resolvable(
        scripts, pw_runner.resolution_root(scripts, root), source=source, nm_dir=nm_dir)
    if status == "fail":
        return None, None, f"node-playwright 运行器不可用：{detail}", ""
    # note（全局兜底的标准说明）每次都给；detail 只在本次动了手时非空。
    return pw_bin, nm_dir, "", (f"{note}；{detail}" if detail else note)


# ---------------------------------------------------------------- 账本（append-only 唯一真相源）

class Ledger:
    def __init__(self, root: Path, actor: str):
        self.layout = load_layout(root)
        self.dir = self.layout.console_dir
        self.events = self.dir / "events.jsonl"
        self.ledger = self.dir / "ledger.md"
        self.actor = actor
        self.lock = threading.Lock()

    def read(self) -> list[dict]:
        if not self.events.is_file():
            return []
        out = []
        for line in self.events.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out

    def append(self, ev: dict) -> None:
        with self.lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            ev = dict(ev)
            ev.setdefault("ts", datetime.now().astimezone().isoformat(timespec="seconds"))
            ev["actor"] = self.actor
            with self.events.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
            self._render()

    # ---- 派生视图：人读用（正文唯一在 events.jsonl）
    def _render(self) -> None:
        evs = self.read()
        runs: dict[str, dict] = {}
        reviews: dict[str, dict] = {}
        for e in evs:
            if e.get("kind") == "run":
                runs[e["case"]] = e
            elif e.get("kind") == "review":
                reviews[e["case"]] = e
        submits = [e for e in evs if e.get("kind") == "submit"]
        lines = [
            "# E2E 用例评审账本（派生视图）",
            "",
            "> 唯一真相源 = `events.jsonl`（append-only）；本文件由 `console.py` 从事件流重算，勿手改。",
            "> 口径：**一次提交 = 一条快照事件**（执行结果与评审态只在点「提交」时落账本）。",
            "",
            f"- 事件数：**{len(evs)}**（提交 {len(submits)} · 历史执行 {sum(1 for e in evs if e.get('kind') == 'run')}"
            f" · 历史评审 {sum(1 for e in evs if e.get('kind') == 'review')}）",
        ]
        if submits:
            last = submits[-1]
            snap = _snap_cases(last)
            scope = last.get("reviewed_scope")
            lines += [
                f"- 最近提交：**{last.get('ts', '')}** · {last.get('actor', '')}"
                f"（快照 {len(snap)} 条 · 执行通过 {sum(1 for v in snap.values() if v.get('ok'))}"
                f" · 已评审 {sum(1 for v in snap.values() if (v.get('reviewed') or {}).get('pass'))}）",
            ]
            if isinstance(scope, list) and scope:
                shown = "、".join(str(x) for x in scope[:8]) + ("…" if len(scope) > 8 else "")
                lines.append(f"- 本次评审范围：**{len(scope)} 条** · {shown}")
        lines += [
            "",
            "## 逐条留痕（最新一条在前）",
            "",
            "| 时间 | 动作 | 用例 | 结果 | 触发者 | 备注 |",
            "|---|---|---|---|---|---|",
        ]
        for e in reversed(evs):
            kind = {"run": "执行", "review": "人工 review", "submit": "提交索引"}.get(e.get("kind"), e.get("kind", ""))
            if e.get("kind") == "submit":
                snap = _snap_cases(e)
                res = f"快照 {len(snap)} 条"
                note = (f"执行通过 {sum(1 for v in snap.values() if v.get('ok'))}/{len(snap)}"
                        f" · 已评审 {sum(1 for v in snap.values() if (v.get('reviewed') or {}).get('pass'))}/{len(snap)}"
                        f" · 索引改动 {e.get('changed')} 行")
            elif e.get("kind") == "run":
                res = "通过" if e.get("ok") else "失败"
                note = f"exit={e.get('exit')} · {int(e.get('duration_ms', 0) / 1000)}s"
                if e.get("timeout"):
                    res = "超时"
            else:
                res = {"pass": "勾选通过", "unchecked": "取消勾选"}.get(e.get("verdict"), str(e.get("verdict")))
                note = e.get("note", "")
            lines.append(f"| {e.get('ts','')} | {kind} | {e.get('case','—')} | {res} | {e.get('actor','')} | {note} |")
        lines.append("")
        self.ledger.write_text("\n".join(lines), encoding="utf-8")

    def last_submit(self, source: str) -> dict | None:
        """某个来源最近一次提交的快照（旧事件没有 source 字段 ⇒ 视为 prototype）。"""
        for e in reversed(self.read()):
            if e.get("kind") == "submit" and e.get("source", "prototype") == source:
                return e
        return None

    def committed_snapshot(self, source: str, current: dict | None = None) -> dict:
        """某个来源的**累计**已提交快照：按事件流顺序合并，后提交覆盖同名用例。

        单次提交只携带页面草稿（通常是本次执行/勾选的那几条），不是全量快照；
        若「已提交」只取最后一条事件，之前提交过的用例会在下一次部分提交后消失
        （表现为控制台里已执行/已评审的用例变回「未跑」）。这里按 append-only 的
        事件顺序逐条合并，保持「提交即留痕、后写覆盖先写」的语义。
        D128：若传入当前工作区指纹，自动为每条用例计算 review_state（新鲜/陈旧/旧版）。
        """
        merged: dict = {}
        ts = actor = None
        scope: list = []
        for e in self.read():
            if e.get("kind") != "submit" or e.get("source", "prototype") != source:
                continue
            merged.update(_snap_cases(e))
            ts = e.get("ts") or ts
            actor = e.get("actor") or actor
            s = e.get("reviewed_scope")
            if isinstance(s, list):
                scope = [str(x) for x in s]
        for snap in merged.values():
            if isinstance(snap, dict):
                snap["review_state"] = case_review_state(snap, current)
        return {"ts": ts, "actor": actor, "cases": merged,
                "reviewed_scope": scope, "reviewed_count": len(scope)}


# ---------------------------------------------------------------- 执行器（并发=1）

class Runner:
    def __init__(self, root: Path, ledger: Ledger, timeout: int, head: bool, keep_open: bool = True):
        self.root = root
        self.layout = load_layout(root)
        self.ledger = ledger
        self.timeout = timeout
        self.head = head
        # 人工 review（用户 2026-09-23 要求）：跑完**不自动关浏览器**，留给人手动关。
        # 无头/自动关模式的取舍在 `main()` 算好再传进来（Runner 只认参数，不耦合 head）。
        self.keep_open = bool(keep_open)
        self.cond = threading.Condition()
        self.lines: list[str] = []
        self.running = False
        self.case: str | None = None
        self.done: dict | None = None
        self.held_case: str | None = None   # 窗口被保留中的那条用例（可手动关窗）
        self._proc: subprocess.Popen | None = None

    def start(self, case: dict, nodeid: str, slowmo: int, source: str, base_url: str) -> tuple[bool, str]:
        # node 单轨（2026-10-12 迁移批）：运行器先行解析 + **可解析性判据**（issue #24）。
        # 判据本体 = 「生成物能不能 import 到 @playwright/test」（单源内核 `_support/pw_runner.py`）；
        # 不成立时执行器走幂等修复（仅全局兜底），且把「用了全局什么」如实播出来；修不好 ⇒ 诚实拒绝。
        pw_bin, nm_dir, why, note = resolve_pw(self.root, repair=True)
        if note:
            self._emit("ℹ " + note)
        if pw_bin is None:
            return False, f"node-playwright 不可用：{why}——解析规则与 atlas_check「E2E 真跑」门一致"
        # 浏览器就绪判据（issue #38，`DESIGN.md` D124）：与「E2E 真跑」门同一内核（`probe_browser`），
        # 不造第二份——模块可解析 ≠ launch 可成（npm 装包不自动下载浏览器）；缺 ⇒ 起跑前诚实拒绝，
        # 不起注定 launch 失败的子进程；`ATLAS_PLAYWRIGHT_CHANNEL` 已设 ⇒ 旁路（系统通道浏览器）。
        br_ok, br_detail = pw_runner.probe_browser(self.layout.e2e_scripts_dir)
        if not br_ok:
            return False, f"浏览器未就绪：{br_detail}——判据与 atlas_check「E2E 真跑」门一致"
        with self.cond:
            if self.running:
                return False, f"已有用例在跑（{self.case}）——本控制台并发=1"
            self._proc_alive_kill()   # 跑下一条前，先关掉上一条保留的窗口
            self.running = True
            self.case = case["id"]
            self.lines = []
            self.done = None
        threading.Thread(target=self._run, args=(case, nodeid, slowmo, source, base_url, pw_bin, nm_dir), daemon=True).start()
        return True, ""

    def _proc_alive_kill(self) -> None:
        """持窗进程还活着就结束它（并清 held_case）。调用方须已持 cond 锁。"""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            self._emit("⏹ 已关闭上一条保留的浏览器窗口")
            try:
                proc.kill()
            except Exception:
                pass
        self._proc = None
        self.held_case = None

    def close_window(self) -> dict:
        """手动关掉被保留的浏览器窗口。"""
        with self.cond:
            had = self.held_case
            self._proc_alive_kill()
        return {"ok": True, "closed": had}

    def _emit(self, text: str) -> None:
        with self.cond:
            self.lines.append(text)
            self.cond.notify_all()

    def _pump(self, proc: subprocess.Popen) -> None:
        """持续把子进程 stdout 搬进日志（持窗期间仍在读，避免管道写满） 。"""
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                self._emit(line.rstrip("\n"))
        except Exception:
            pass

    def _run(self, case: dict, nodeid: str, slowmo: int, source: str, base_url: str,
             pw_bin: Path, nm_dir: Path) -> None:
        scripts = self.layout.e2e_scripts_dir
        # 用例执行前的项目数据准备钩子（v3 现场实证移植，duty-review/bugs.md 005/006 链 companion）：
        # 共享型靶场是有状态环境（SPA + 服务端态），用例 precondition 属文档性声明、运行器不自动
        # 归零 ⇒ 残留实体会让 count 类断言系统性偏移。项目自带 product/e2e/scripts/atlas-prepare.mjs
        # ⇒ 每条用例先跑它（cwd = 项目根，180s 上限，**不计入**用例超时窗——本块在计时起点之前）；
        # 失败/超时 ⇒ 拒绝执行该用例并按 done 事件完整形状（带 prep_failed 标记）如实上报——
        # 不静默跑一条注定偏移的用例。
        # D121（2026-10-20）：用例 ID 经 ATLAS_CASE_ID 传入，项目脚本可按用例分段准备。此前钩子
        # 无任何用例上下文 ⇒ 一组用例的前置缺失会把无关用例一并挡在 prepare 阶段（全局前置）。
        # D125（2026-10-20）：NODE_PATH 同步注入（若 nm_dir 存在），与真跑子进程依赖解析环境一致
        # ⇒ 避免 scripts/ 目录下未独立建 node_modules 时脚本顶层 import 报 ERR_MODULE_NOT_FOUND。
        prep = scripts / "atlas-prepare.mjs"
        if prep.is_file():
            self._emit("$ 前置数据准备 atlas-prepare.mjs …")
            prep_exit = None
            prep_env = {**os.environ, "ATLAS_CASE_ID": case["id"]}
            if nm_dir:
                prep_env["NODE_PATH"] = str(nm_dir)
            try:
                pr = subprocess.run(["node", str(prep)], cwd=str(self.root),
                                    capture_output=True, text=True, timeout=180,
                                    env=prep_env)
                self._emit((pr.stdout or "")[-1500:])
                if pr.returncode != 0:
                    self._emit(f"\n[前置] atlas-prepare 失败（exit={pr.returncode}）：未执行用例\n"
                               + (pr.stderr or "")[-800:])
                    prep_exit = pr.returncode
            except Exception as exc:
                self._emit(f"\n[前置] atlas-prepare 无法执行：{exc!r} —— 未执行用例")
                prep_exit = -2
            if prep_exit is not None:
                with self.cond:
                    raw = list(self.lines)
                ev = {"kind": "done", "case": case["id"], "nodeid": nodeid, "ok": False,
                      "exit": prep_exit, "duration_ms": 0, "timeout": False, "held": False,
                      "slowmo": slowmo, "head": self.head, "source": source,
                      "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                      "tail": "\n".join(_clean(ln) for ln in raw[-80:]),
                      "prep_failed": True}
                with self.cond:
                    self.running = False
                    self.done = ev
                    self.cond.notify_all()
                return
        # node 单轨（3507 BO）：`file:line` 过滤 + 运行器原生 flag（--headed）；NODE_PATH 让生成物里的
        # @playwright/test 解析到项目声明的依赖目录（与 atlas_check 真跑门同一姿势）。
        cmd = [str(pw_bin), "test", "-c", "playwright.config.ts", nodeid]
        if self.head:
            cmd.append("--headed")
        if self.keep_open:
            # D126（2026-10-21）：Playwright 默认 test timeout（30s）**计入 fixture teardown**
            # ⇒ `atlas-hold.ts` 的留窗等待会被判超时并把浏览器关掉（实测报错：
            # Tearing down "atlasHold" exceeded the test timeout of 30000ms）。
            # 持窗模式关掉运行器自身超时，控制台的 wall-clock `--timeout` 是唯一超时真相源
            # （到点 kill 并如实报「超时」）；自动关窗模式保留 30s 原生兜底，防孤儿进程。
            cmd.append("--timeout=0")
        self._emit(f"# 来源 {source} → ATLAS_BASE_URL={base_url}（slowmo={slowmo}ms via ATLAS_SLOWMO）\n$ cd {scripts}\n$ {' '.join(cmd)}\n")
        t0 = time.time()
        timed_out = False
        held = False
        exit_code = -1
        # 结果哨兵：持窗模式下进程会活过用例结束，所以不能靠「进程退出」判结果。
        # node 轨的哨兵写入方 = 生成物 atlas-hold.ts（ATLAS_RESULT_FILE；契约 §10.1）。
        # 注意：mkstemp 会**先建一个空文件**，必须删掉它—— 否则 is_file() 一开始就为真。
        _fd, _spath = tempfile.mkstemp(prefix="atlas-e2e-result-", suffix=".json")
        os.close(_fd)
        sentinel = Path(_spath)
        sentinel.unlink()
        # F11（2026-10-14）：Playwright `test` CLI 无 `--slowmo` 旗标（1.64 实测 unknown
        # option）⇒ 慢动作经 `ATLAS_SLOWMO` 注入生成配置的 launchOptions.slowMo；未设 ⇒ 0。
        env = {**os.environ, "ATLAS_BASE_URL": base_url, "ATLAS_SLOWMO": str(slowmo)}
        if nm_dir:
            env["NODE_PATH"] = str(nm_dir)
        if self.keep_open:
            env["ATLAS_KEEP_OPEN"] = "1"
            env["ATLAS_RESULT_FILE"] = str(sentinel)
        try:
            proc = subprocess.Popen(cmd, cwd=str(scripts), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
            self._proc = proc
            threading.Thread(target=self._pump, args=(proc,), daemon=True).start()
            while True:
                if sentinel.is_file():
                    try:
                        exit_code = int(json.loads(sentinel.read_text(encoding="utf-8"))["exitstatus"])
                    except Exception:
                        rc = proc.poll()
                        exit_code = rc if rc is not None else -1
                    held = proc.poll() is None
                    if held:
                        self._emit("⏸ 用例已结束；浏览器窗口保留，请手动关闭（控制台也可点「关闭浏览器窗口」）")
                    break
                if proc.poll() is not None:
                    exit_code = proc.returncode
                    break
                if time.time() - t0 > self.timeout:
                    self._kill()
                    timed_out = True
                    break
                time.sleep(0.1)
        except Exception as exc:  # pragma: no cover
            self._emit(f"控制台起子进程失败：{exc}")
        try:
            sentinel.unlink()
        except Exception:
            pass
        dur = int((time.time() - t0) * 1000)
        ok = (exit_code == 0 and not timed_out)
        with self.cond:
            raw = list(self.lines)
        # 「乙」：执行结果只回给页面（浏览器存本地草稿），提交时才落账本
        ev = {"kind": "done", "case": case["id"], "nodeid": nodeid, "ok": ok, "exit": exit_code,
              "duration_ms": dur, "timeout": timed_out, "held": held,
              "slowmo": slowmo, "head": self.head, "source": source,
              "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
              # 失败原文是人工评审的输入 ⇒ 交给页面留在本地草稿里（提交时随快照一起落账本）
              "tail": "\n".join(_clean(ln) for ln in raw[-80:])}
        with self.cond:
            self.running = False
            self.done = ev
            if held:
                self.held_case = case["id"]
            self.cond.notify_all()
        if held:
            threading.Thread(target=self._watch_held, args=(proc,), daemon=True).start()

    def _watch_held(self, proc: subprocess.Popen) -> None:
        """人手动关了窗口 ⇒ 持窗进程自然退出 ⇒ 顺手把 held_case 清掉（不让 UI 一直挂一个已失效的按钮）。"""
        try:
            proc.wait()
        except Exception:
            pass
        with self.cond:
            if self._proc is proc:
                self._proc = None
                self.held_case = None
            self.cond.notify_all()

    def _kill(self) -> None:
        proc = self._proc
        if proc and proc.poll() is None:
            setattr(proc, "_atlas_killed", True)
            try:
                proc.kill()
            except Exception:
                pass
            self._emit(f"⏱ 超时 {self.timeout}s，已终止该条用例")

    def wait_lines(self, since: int, block_s: float = 20.0) -> tuple[list[str], int, bool, dict | None]:
        with self.cond:
            self.cond.wait(timeout=block_s if self.running else 0.05)
            return self.lines[since:], len(self.lines), self.running, self.done


# ---------------------------------------------------------------- 回写索引（显式动作 + 预览）

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _clean(s: str) -> str:
    """去掉 ANSI 颜色码，账本里存纯文本。"""
    return _ANSI.sub("", s).rstrip()


def _snap_cases(entry: dict) -> dict:
    """取提交事件快照的「逐用例」部分。

    `events.jsonl` 是 append-only 的，里面存着**历史版本的写入形状**：旧版提交事件把
    `cases` 写成变更清单（list，键含 `to`），新版写成 `{用例ID: 条目}`（dict）。
    派生视图（`ledger.md`）是从事件流**重算**出来的，必须能重算任何历史形状——
    不能假设「最后一条提交 = 最新形状」（2026-09-23 实测：正是这一点让渲染崩在
    `snap.values()`，下一次「提交」会在 `append()` 里报 500）。
    """
    cases = entry.get("cases")
    return cases if isinstance(cases, dict) else {}


def _compact(entry: dict, prov: dict | None = None) -> dict:
    """落账本的快照条目：失败才带输出尾部（80 行，与运行期同长），避免账本被 traceback 撑爆。"""
    out = {"ok": bool(entry.get("ok")), "exit": entry.get("exit"),
           "duration_ms": entry.get("duration_ms"), "timeout": bool(entry.get("timeout")),
           "ts": entry.get("ts")}
    reviewed = entry.get("reviewed") or {}
    if reviewed:
        out["reviewed"] = {"pass": bool(reviewed.get("pass")),
                           "checked_at": reviewed.get("checked_at"),
                           "unchecked_at": reviewed.get("unchecked_at")}
    p = entry.get("prov") or prov
    if p and isinstance(p, dict):
        out["prov"] = {
            "head_sha": p.get("head_sha"),
            "scripts_hash": p.get("scripts_hash"),
            "git_dirty": p.get("git_dirty"),
            "actor_type": p.get("actor_type", "human"),
        }
    if not out["ok"] and entry.get("tail"):
        out["tail"] = "\n".join(str(entry["tail"]).splitlines()[-80:])
    return out


def writeback(root: Path, draft: dict, apply: bool, source: str = "app") -> dict:
    """按页面草稿（执行结果 + 评审态）算索引改动；apply=True 才落盘。

    只改一列：`状态`（契约 §5.4 E1 单段：通过 → `green`，失败 → `red`）。
    """
    index = load_layout(root).e2e_index
    lines = index.read_text(encoding="utf-8").splitlines()
    changes: list[dict] = []
    out: list[str] = []
    for line in lines:
        if not line.startswith("| E2E-"):
            out.append(line)
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        cid = cells[0]
        before = list(cells)
        note = ""
        snap = draft.get(cid)
        if snap:
            # 契约 §5.4 状态机（E1 单段）：通过 → green
            ok_state = "green"
            cells[6] = ok_state if snap.get("ok") else "red"
            if cells[6] not in ("blocked", "skipped"):
                cells[7] = ""  # §8.2：状态原因仅 blocked/skipped 时非空
            note = f"执行：{'通过' if snap.get('ok') else '失败'}"
            if (snap.get("reviewed") or {}).get("pass"):
                note += " · 人工评审通过"
        if cells != before:
            changes.append({"id": cid, "from": {"状态": before[6]},
                            "to": {"状态": cells[6]}, "note": note})
        out.append("| " + " | ".join(cells) + " |")
    if apply and changes:
        index.write_text("\n".join(out) + "\n", encoding="utf-8")
    return {"apply": apply, "changed": len(changes), "changes": changes}


# ---------------------------------------------------------------- HTTP

class App:
    def __init__(self, root: Path, port: int, slowmo: int, timeout: int, head: bool, keep_open: bool = True):
        self.root = root
        self.layout = load_layout(root)
        self.port = port
        self.slowmo = slowmo
        self.actor = f"{os.environ.get('USER', 'local')}·控制台"
        self.ledger = Ledger(root, self.actor)
        self.runner = Runner(root, self.ledger, timeout, head, keep_open)

    def cases_payload(self, source: str) -> dict:
        current_prov = repo_provenance(self.root)
        try:
            snap = snapshot(self.root)
        except SnapshotError as exc:
            return {"source": source, "sources": read_sources(self.root), "problem": str(exc),
                    "slowmo": self.slowmo, "timeout": self.runner.timeout, "head": self.runner.head,
                    "ledger": self.layout.print_value("console_ledger"), "cases": [], "nodeids": {},
                    "committed": {"ts": None, "actor": None, "cases": {}},
                    "provenance": current_prov}
        committed = self.ledger.committed_snapshot(source, current_prov)
        return {
            "source": source,
            "sources": read_sources(self.root),
            "root": str(self.root),
            "slowmo": self.slowmo,
            "timeout": self.runner.timeout,
            "head": self.runner.head,
            "keep_open": self.runner.keep_open,
            "held_case": self.runner.held_case,
            "ledger": self.layout.print_value("console_ledger"),
            "cases": snap["cases"],
            "manual": read_manual(self.root),
            "manual_state": ("created"
                             if self.layout.e2e_manual.is_file()
                             else "missing"),
            # manual_state（RFC-20261015-01，issue #10）：「没有」与「忘了」不得同形——
            # missing ⇒ 前端显式披露「未创建」，不静默空栏；评估留痕另落域收口走查 README
            # （rings/e2e/reference.md §5.4 末 / §10 执行纪律 5）。
            "nodeids": snap["nodeids"],
            # 已提交的快照（页面草稿覆盖它；草稿在浏览器本地，见 docstring 的「乙」）
            "committed": committed,
            "provenance": current_prov,
        }


class Handler(BaseHTTPRequestHandler):
    app: App

    def log_message(self, fmt, *args):  # 安静点
        pass

    # ---- helpers
    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, rel: str) -> None:
        path = (ASSETS / rel).resolve()
        if not path.is_file() or ASSETS not in path.parents:
            self.send_error(404)
            return
        if path.suffix in (".js", ".html"):
            text = path.read_text(encoding="utf-8")
            text = (text
                    .replace("{{ATLAS_E2E_MANUAL}}", self.app.layout.print_value("e2e_manual"))
                    .replace("{{ATLAS_E2E_INDEX}}", self.app.layout.print_value("e2e_index"))
                    .replace("{{ATLAS_CONSOLE_LEDGER}}",
                             self.app.layout.print_value("console_ledger")))
            body = text.encode("utf-8")
        else:
            body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    # ---- routes
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._static("index.html")
        elif path == "/api/cases":
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            self._json(self.app.cases_payload("app"))
        elif path == "/api/stream":
            self._stream()
        elif path.startswith("/api/"):
            self.send_error(404)
        else:
            self._static(path.lstrip("/"))

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        body = self._body()
        if path == "/api/run":
            self._run(body)
        elif path == "/api/close-window":
            self._json(self.app.runner.close_window())
        elif path == "/api/open":
            self._open_manual(body)
        elif path == "/api/submit":
            self._submit(body)
        else:
            self.send_error(404)

    def _open_manual(self, body: dict) -> None:
        """手工项执行：开浏览器到该项声明的页面，其余人工（用户 2026-10-01 设计）。"""
        mid = body.get("id", "")
        item = next((m for m in read_manual(self.app.root) if m["id"] == mid), None)
        if not item:
            self._json({"ok": False, "error": f"manual.md 里没有 {mid}"}, 404)
            return
        route = page_routes(self.app.root).get(item["page"])
        if not route:
            self._json({"ok": False, "error": f"{item['page']} 不在索引页面表里，无法跳转"}, 409)
            return
        url = manual_open_url(self.app.root, route)
        opener_cmd = ["open"] if sys.platform == "darwin" else (["xdg-open"] if shutil.which("xdg-open") else None)
        if opener_cmd is None:
            self._json({"ok": True, "url": url, "opened": False,
                        "note": "系统无 open/xdg-open，请手动访问下方地址"}, 200)
            return
        subprocess.Popen(opener_cmd + [url])
        self._json({"ok": True, "url": url, "opened": True}, 200)

    def _run(self, body: dict) -> None:
        cid = body.get("id", "")
        source = "app"
        src = read_sources(self.app.root).get(source)
        if not src or not src.get("configured"):
            why = (src or {}).get("why", "未知来源")
            self._json({"ok": False, "error": f"{source} 不可执行：{why}"}, 409)
            return
        try:
            snap = snapshot(self.app.root)
        except SnapshotError as exc:
            self._json({"ok": False, "error": str(exc)}, 409)
            return
        case = next((c for c in snap["cases"] if c["id"] == cid), None)
        nodeid = snap["nodeids"].get(cid)
        if not case:
            self._json({"ok": False, "error": f"索引里没有 {cid}"}, 404)
            return
        if case.get("status") in ("blocked", "skipped"):
            # 契约 §7：合法不可跑（生成物为 test.skip，本就无 node id）——如实拒绝，不指向重跑生成。
            reason = case.get("reason") or ""
            self._json({"ok": False, "error": f"{cid} 在索引里是 {case['status']}（合法不可跑）{('：' + reason) if reason else ''}"}, 409)
            return
        if not nodeid:
            self._json({"ok": False, "error": f"{cid} 在生成脚本里找不到 node id，先重跑 gen_e2e_scripts.py --apply"}, 409)
            return
        slowmo = int(body.get("slowmo") or self.app.slowmo)
        ok, err = self.app.runner.start(case, nodeid, slowmo, source, src["base_url"])
        self._json({"ok": ok, "error": err, "nodeid": nodeid, "source": source,
                    "base_url": src["base_url"]}, 200 if ok else 409)

    def _submit(self, body: dict) -> None:
        """提交 = 一次性落两处：账本追加一条快照 + 回写索引（预览/确认）。"""
        draft = body.get("draft") or {}
        source = "app"
        apply = bool(body.get("apply"))
        # 指纹在 writeback 前获取，避免 writeback 自身修改索引使 git_dirty 假阳性（D128）
        prov = repo_provenance(self.app.root)
        res = writeback(self.app.root, draft, apply, source)
        if apply:
            snap = {cid: _compact(v, prov) for cid, v in draft.items()}
            reviewed_scope = [cid for cid, v in draft.items() if (v.get("reviewed") or {}).get("pass")]
            self.app.ledger.append({"kind": "submit", "source": source,
                                    "changed": res["changed"], "cases": snap,
                                    "prov": prov, "actor_type": prov.get("actor_type", "human"),
                                    "reviewed_scope": reviewed_scope})
            res["committed_ts"] = self.app.ledger.committed_snapshot(source, prov).get("ts")
            res["provenance"] = prov
        self._json(res)

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        # 无 Content-Length 的流式响应：必须由服务端关闭连接，
        # 否则客户端只能读到自己设的超时才结束（httplib/curl 均如此）。
        self.close_connection = True
        since = 0
        try:
            while True:
                lines, since, running, done = self.app.runner.wait_lines(since)
                for ln in lines:
                    self.wfile.write(f"data: {json.dumps({'kind': 'line', 'text': ln}, ensure_ascii=False)}\n\n".encode("utf-8"))
                if done is not None:
                    self.wfile.write(f"data: {json.dumps({**done, 'kind': 'done'}, ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    return
                if not running and not lines:
                    self.wfile.flush()
                    return
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> int:
    ap = argparse.ArgumentParser(description="E2E 用例评审控制台")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--port", type=int, default=4190)
    ap.add_argument("--slowmo", type=int, default=500, help="有头执行的慢动作毫秒数（可在页面上改）")
    ap.add_argument("--timeout", type=int, default=120, help="单条用例 wall-clock 超时（秒）")
    ap.add_argument("--no-head", action="store_true", help="不带有头窗口（默认有头）")
    ap.add_argument("--auto-close", action="store_true",
                    help="跑完自动关浏览器（默认**不关**：留窗给人手动 review；无头时恒自动关）")
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    try:
        load_layout(root)
    except LayoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    app = App(root, args.port, args.slowmo, args.timeout, not args.no_head,
              (not args.auto_close) and (not args.no_head))
    Handler.app = app
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"E2E 用例评审控制台 → http://{args.host}:{args.port}/")
    print(f"  根目录   : {root}")
    print(f"  执行     : {'有头' if app.runner.head else '无头'} · slowmo={args.slowmo}ms · 并发=1 · 超时={args.timeout}s")
    print(f"  跑完关窗 : {'自动关' if not app.runner.keep_open else '**不关**（人工 review 用：手动关窗，或控制台点「关闭浏览器窗口」）'}")
    print("  落盘时机 : 点「提交」才写账本 + 回写索引（执行/勾选只存页面本地草稿）")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
