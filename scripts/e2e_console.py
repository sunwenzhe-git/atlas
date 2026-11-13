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
  `e2e.app_base_url` 为 `null` 时「真实应用」不可执行——成员仓契约要求向用户索取，不猜默认。
  **solution 根 / 父仓无实体页面**：不展示该索取提示、不参与真实应用执行判定（`read_sources().app.applicable=false`）。

执行语义：

* 「执行用例」= 起一次**有头**子进程跑这一条（node 单轨：`<e2e.node_modules>/.bin/playwright test
  -c playwright.config.ts <file>:<line> --headed`；慢动作经 `ATLAS_SLOWMO` 注入生成配置的
  `launchOptions.slowMo`（Playwright `test` CLI 无 `--slowmo` 旗标，2026-10-14 F11）；
  「跑完留窗 + 结果哨兵」由生成物 `atlas-hold.ts` 承载——契约 `rings/e2e/reference.md` §10.1）；
* **并发 = 1**（同时只跑一条，其余按钮禁用）；自动关窗模式（无头）单条 wall-clock 超时到点
  kill 并如实报「超时」；**持窗模式只提示、绝不 kill**（见下条硬性要求）；
* **持窗到下一条起跑（硬性要求，2026-11-12，取代 2026-11-11「只手动关」）**：持窗模式下用例
  跑完浏览器窗口**必须保持打开**，wall-clock `--timeout` 到点也**不得主动 kill**（只提示一次，
  继续等待）；**起跑下一条用例时必须先收掉之前保留的窗口**——这是唯一允许的自动结束时点
  （`Runner._collect_held_windows()`）；其余结束途径 = 用户手动关窗，或显式点控制台
  「关闭浏览器窗口」（`/api/close-window`）。不提供「跑完自动关」开关（`--auto-close` 已移除，
  跑完即关仍禁止）。无头（`--no-head`）本就没有窗口，不在此约束内。
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
import atexit
import hashlib
import importlib.util
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
import urllib.parse
import urllib.request
import shlex
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
from _support.solution import load_manifest  # noqa: E402

# 用例 ID 文法体单源（正文归 rings/e2e/reference.md §5.3）；锚点在使用处自留。
case_id = load_module("case_id")
# `关联AC` 多值拆分单源（RFC-20261111-03 §1.6）：页面只展示拆开后的 token，不回显原始分隔串。
ac_coverage = load_module("ac_coverage")

# node 运行器单源内核（二进制解析 / **可解析性判据** / 全局兜底修复；issue #24）：
# `atlas_check` 真跑门与本月控制台共用同一实现 —— 此前两处各存一份拷贝。
pw_runner = load_module("pw_runner")
# 证据归档（RFC-20261104-01 S1）：与 atlas_verify / globalTeardown 共用同一内核。
evidence_archive = load_module("evidence_archive")
# 宿主注入型 base query（issue #27 / D104）：单源 `_support/url_merge.py`。
url_merge = load_module("url_merge")
# 登录态预检（RFC-20261112-01 v1 / D）：形态识别、过期分治、probe、指纹与哈希校验的单源内核。
auth_state = load_module("auth_state")
# 运行期输出目录（仓库外、每次 run 独立；D194）：结构上消除仓内受限写与并发互清。
run_workspace = load_module("run_workspace")


# ---------------------------------------------------------------- 代码提交与生成脚本指纹（D128）

def _git_output(root: Path, *args: str) -> str | None:
    try:
        res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return None


def _git_paths(root: Path, *args: str) -> list[str] | None:
    """`git -C root <args>` 的 NUL 分隔路径输出（配 `-z` 用，绕开 core.quotePath 转义）。"""
    try:
        res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)
    except Exception:
        return None
    return [p for p in res.stdout.decode("utf-8", "replace").split("\0") if p]


def _sha16(data: str | bytes) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()[:16]


def _git_status_entries(root: Path) -> list[tuple[str, str]] | None:
    """`git status --porcelain -z` 的 (XY, path) 列表（NUL 分隔；不解析 C-quote）。"""
    try:
        res = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "-z",
             "--untracked-files=all"],
            capture_output=True, check=True,
        )
    except Exception:
        return None
    parts = res.stdout.decode("utf-8", "replace").split("\0")
    entries: list[tuple[str, str]] = []
    for part in parts:
        if not part:
            continue
        if len(part) >= 4 and part[2] == " ":
            entries.append((part[:2], part[3:]))
        else:
            entries.append((part[:2], part))
    return entries


def _git_status_paths(root: Path) -> list[str] | None:
    entries = _git_status_entries(root)
    return None if entries is None else [path for _xy, path in entries]


def repo_head(root: Path) -> str | None:
    return _git_output(root, "rev-parse", "HEAD")


def _is_repo_root(path: Path) -> bool:
    top = _git_output(path, "rev-parse", "--show-toplevel")
    if not top:
        return False
    try:
        return Path(top).resolve() == Path(path).resolve()
    except OSError:
        return False


def _solution_member_rels(root: Path) -> list[str]:
    try:
        data = load_manifest(root)
    except Exception:
        return []
    return [m["path"] for m in data["members"]]


def _solution_members(root: Path) -> list[Path]:
    """solution 根 ⇒ 成员仓路径；非 solution / 清单非法时返回空表（保持旧行为）。"""
    try:
        data = load_manifest(root)
    except Exception:
        return []
    return [(Path(root) / m["path"]).resolve() for m in data["members"]]


def _is_solution_root(root: Path) -> bool:
    """父仓模式（RFC-20261108-02）：`atlas.solution.yaml` 存在且 `mode: federated`。"""
    try:
        return load_manifest(root).get("mode") == "federated"
    except Exception:
        return False


def _is_member_status_path(path: str, member_rels: list[str]) -> bool:
    p = path.rstrip("/")
    return any(p == rel or rel.startswith(p + "/") or p.startswith(rel + "/")
               for rel in member_rels)


def repo_git_dirty(root: Path) -> bool | None:
    root = Path(root)
    member_rels = _solution_member_rels(root)
    entries = _git_status_entries(root)
    if entries is None:
        return None
    if entries:
        if not member_rels:
            return True
        # 只豁免 untracked（`??`）的成员折叠行 `?? members/` / `?? web/`；
        # 成员被 solution 根误跟踪成 `A web` / `M web` 时必须算脏（守卫违规）。
        if any(not (xy.strip() == "??" and _is_member_status_path(path, member_rels))
               for xy, path in entries):
            return True
    for member in _solution_members(root):
        if not member.is_dir() or not _is_repo_root(member):
            continue
        st = _git_status_paths(member)
        if st is None:
            continue
        if st:
            return True
    return False


# D128 #31：运行期产物目录 / 后缀闭集单源——`scripts_hash` 与 `script_file_map` 共用，
# 避免两处清单再次漂移。`.atlas-run/`（直跑运行目录：`results.json`、`.last-run.json`、trace 等；
# 控制台 run 自 D194 起落在仓库外）整体是运行产物，不参与指纹。
_RUNTIME_PATH_PARTS = ("test-results", "playwright-report", ".atlas-auth", "node_modules",
                       ".atlas-run", ".atlas-evidence")
_RUNTIME_SUFFIXES = (".trace", ".png", ".webm", ".last-run.json")
_SCRIPT_SUFFIXES = (".ts", ".js", ".mjs", ".json", ".yaml", ".yml")


def _script_inventory(root: Path) -> list[tuple[str, Path]]:
    """白名单脚本清单（单源）：`scripts_hash` 与 `script_file_map` 的**唯一**枚举。

    `product/e2e/scripts/` 下源码脚本 + 可选 `atlas-prepare.mjs`（scripts 内优先，其次项目根）；
    排除 `_RUNTIME_PATH_PARTS` / `_RUNTIME_SUFFIXES`。顺序稳定（目录序 + 钩子末位）。
    """
    s_dir = load_layout(root).e2e_scripts_dir
    if not s_dir.is_dir():
        return []
    inv: list[tuple[str, Path]] = []
    for p in sorted(s_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(s_dir).as_posix()
        if any(part in rel for part in _RUNTIME_PATH_PARTS):
            continue
        if rel.endswith(_RUNTIME_SUFFIXES) or not rel.endswith(_SCRIPT_SUFFIXES):
            continue
        inv.append((f"scripts/{rel}", p))
    for prep in (s_dir / "atlas-prepare.mjs", root / "atlas-prepare.mjs"):
        if not prep.is_file():
            continue
        key = "scripts/atlas-prepare.mjs" if prep.parent == s_dir else "atlas-prepare.mjs"
        if all(k != key for k, _ in inv):
            inv.append((key, prep))
        break
    return inv


def scripts_hash(root: Path) -> str | None:
    """计算当前 E2E 生成脚本与前置准备钩子的内容散列（16 字符前缀）。

    白名单与排除规则的单源是 `_script_inventory`；`script_file_map` 消费同一清单。
    """
    files = _script_inventory(root)
    if not files:
        return None
    h = hashlib.sha256()
    for rel, p in files:
        h.update(rel.encode("utf-8"))
        try:
            h.update(p.read_bytes())
        except Exception:
            pass
    return h.hexdigest()[:16]


def script_file_map(root: Path) -> dict[str, Path]:
    """白名单脚本的逐文件清单 `{相对路径: 路径}`（与 `scripts_hash` 同源）。"""
    return dict(sorted(_script_inventory(root)))


def script_file_hashes(root: Path) -> dict[str, str]:
    """白名单脚本的逐文件内容散列（16 字符前缀）。"""
    out: dict[str, str] = {}
    for rel, p in script_file_map(root).items():
        try:
            out[rel] = _sha16(p.read_bytes())
        except OSError:
            out[rel] = "missing"
    return out


_CASE_TEST_LINE = re.compile(rf"\s*test\(['\"]({case_id.GRAMMAR})[ '\"].*async")
_LOCAL_IMPORT = re.compile(r"""(?:\bfrom\s+|\bimport\s+|\bimport\s*\(\s*|\brequire\s*\(\s*)['"](\.[^'"]*)['"]""")
_JS_EXTS = (".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs", ".json")


def case_fingerprints(scripts_dir: Path) -> dict[str, dict]:
    """逐用例脚本指纹 `{用例ID: {script, block, rest}}`。

    `block` = 该 `test(...)` 行到下一个 `test(` 行之间的原文；`rest` = 同一文件里
    所有用例块之外的原文（imports / 文件内 helper）。判据：
      * 只改一条用例的块 ⇒ 只有该条 `block` 变；
      * 改块外共享代码 ⇒ 该文件全部用例 `rest` 变（保守：块外代码可能被任一用例调用）。
    用例之间的夹层文本归属前一条用例（生成物里用例块连续，夹层只有空行/注释）。
    """
    out: dict[str, dict] = {}
    if not scripts_dir.is_dir():
        return out
    for ts in sorted(scripts_dir.glob("*.spec.ts")):
        try:
            lines = ts.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError:
            continue
        marks: list[tuple[int, str]] = []
        for i, line in enumerate(lines):
            m = _CASE_TEST_LINE.match(line)
            if m:
                marks.append((i, m.group(1)))
        if not marks:
            continue
        spans = [(start, marks[i + 1][0] if i + 1 < len(marks) else len(lines))
                 for i, (start, _cid) in enumerate(marks)]
        inside: set[int] = set()
        for start, end in spans:
            inside.update(range(start, end))
        rest = _sha16("".join(line for i, line in enumerate(lines) if i not in inside))
        script = f"scripts/{ts.name}"
        for (start, end), (_i, cid) in zip(spans, marks):
            out[cid] = {"script": script, "block": _sha16("".join(lines[start:end])), "rest": rest}
    return out


def _resolve_local_import(src: Path, spec: str, known: dict[Path, str]) -> str | None:
    base = src.parent / spec
    cands = [base] + [Path(str(base) + ext) for ext in _JS_EXTS]
    cands += [base / f"index{ext}" for ext in _JS_EXTS]
    for cand in cands:
        try:
            rel = known.get(cand.resolve())
        except OSError:
            rel = None
        if rel:
            return rel
    return None


def shared_script_hashes(root: Path) -> tuple[dict[str, str], str | None, bool]:
    """静态可达的非 spec 脚本（config / setup / prepare / helper）逐文件散列与聚合散列。

    可达性 = 从 `.spec.ts`、`playwright.config.ts`、`*.setup.ts`、`atlas-prepare.mjs`
    出发解析相对 import（传递）。没被任何执行入口引用的脚本（如一次性探针）不进指纹
    ——它们不是验收证据，改它们不该作废评审。
    任一相对 import 解析不出 ⇒ **保守回退**：全部非 spec 脚本都算共享（宁可多判 stale）。
    返回 `(逐文件散列, 聚合散列, 是否保守回退)`；无共享脚本 ⇒ 聚合为 `None`。
    """
    files = script_file_map(root)
    if not files:
        return {}, None, False
    known: dict[Path, str] = {}
    for rel, p in files.items():
        try:
            known[p.resolve()] = rel
        except OSError:
            pass
    roots = [(rel, p) for rel, p in files.items()
             if p.name.endswith(".spec.ts") or p.name == "playwright.config.ts"
             or p.name.endswith(".setup.ts") or p.name == "atlas-prepare.mjs"]
    if not roots:
        return {}, None, False
    spec_rels = {rel for rel, p in roots if p.name.endswith(".spec.ts")}
    seen: set[str] = set()
    queue = [p for _rel, p in roots]
    unresolved = False
    while queue:
        cur = queue.pop()
        try:
            text = cur.read_text(encoding="utf-8")
        except OSError:
            continue
        for spec in _LOCAL_IMPORT.findall(text):
            if "${" in spec:
                unresolved = True
                continue
            rel = _resolve_local_import(cur, spec, known)
            if rel is None:
                unresolved = True
                continue
            if rel not in seen:
                seen.add(rel)
                queue.append(files[rel])
    if unresolved:
        shared = {rel for rel, p in files.items() if not p.name.endswith(".spec.ts")}
    else:
        shared = ({rel for rel, p in roots if not p.name.endswith(".spec.ts")} | seen) - spec_rels
    hashes: dict[str, str] = {}
    for rel in sorted(shared):
        try:
            hashes[rel] = _sha16(files[rel].read_bytes())
        except OSError:
            hashes[rel] = "missing"
    agg = _sha16("\n".join(f"{rel}\0{h}" for rel, h in hashes.items())) if hashes else None
    return hashes, agg, unresolved


_APP_FILE_CACHE: dict[str, tuple[int, int, str]] = {}


def _is_app_path(rel: str, e2e_rel: str) -> bool:
    if rel == e2e_rel or rel.startswith(e2e_rel + "/"):
        return False
    if rel == ".atlas" or rel.startswith(".atlas/"):
        return False
    if rel == "node_modules" or rel.startswith("node_modules/") or "/node_modules/" in rel:
        return False
    if rel.endswith(".md"):
        return False
    return True


def _content_digest(path: Path) -> str:
    try:
        st = path.stat()
    except OSError:
        return "missing"
    key = str(path)
    hit = _APP_FILE_CACHE.get(key)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    try:
        digest = _sha16(path.read_bytes())
    except OSError:
        return "missing"
    _APP_FILE_CACHE[key] = (st.st_mtime_ns, st.st_size, digest)
    return digest


def _member_app_entries(root: Path, member: Path) -> list[str] | None:
    try:
        rel_member = member.resolve().relative_to(Path(root).resolve()).as_posix()
    except (OSError, ValueError):
        return None
    if not _is_repo_root(member):
        return None
    tracked = _git_paths(member, "ls-files", "-z")
    if tracked is None:
        return None
    untracked = _git_paths(member, "ls-files", "-o", "--exclude-standard", "-z") or []
    try:
        e2e_rel = load_layout(member).e2e_dir.resolve().relative_to(member).as_posix()
    except (LayoutError, ValueError):
        e2e_rel = "product/e2e"
    entries = []
    for rel in sorted(set(tracked) | set(untracked)):
        if not _is_app_path(rel, e2e_rel):
            continue
        entries.append(f"{rel_member}/{rel}\0{_content_digest(member / rel)}")
    return entries


def app_fingerprint(root: Path) -> str | None:
    """应用代码的**内容**指纹（与提交指针无关；D174）。

    评审绑定的应是「当时被测应用的内容」，不是 `HEAD`：commit 本身、提交账本
    都不该让全部用例失效。范围 = 工作区里 git 已跟踪 + 未忽略的新文件，
    排除 E2E 环（脚本/索引/账本）、`.atlas/`、`node_modules/` 与 `*.md`
    （文档不是运行时证据）；未提交改动天然计入（读的是工作区内容）。

    solution 根（`atlas.solution.yaml`）下，成员代码在各自仓库内：按成员仓
    `ls-files` 枚举并加成员前缀，避免 solution 根只看到 `?? members/` 目录。
    """
    root = Path(root).resolve()
    members = _solution_members(root)
    if members:
        entries: list[str] = []
        for member in members:
            part = _member_app_entries(root, member)
            if part is None:
                return None
            entries += part
        return _sha16("\n".join(entries))
    if _git_output(root, "rev-parse", "--is-inside-work-tree") != "true":
        return None
    tracked = _git_paths(root, "ls-files", "-z")
    if tracked is None:
        return None
    untracked = _git_paths(root, "ls-files", "-o", "--exclude-standard", "-z") or []
    lay = load_layout(root)
    try:
        e2e_rel = lay.e2e_dir.resolve().relative_to(root).as_posix()
    except ValueError:
        e2e_rel = "product/e2e"
    entries = []
    for rel in sorted(set(tracked) | set(untracked)):
        if not _is_app_path(rel, e2e_rel):
            continue
        entries.append(f"{rel}\0{_content_digest(root / rel)}")
    return _sha16("\n".join(entries))


def case_content_hashes(root: Path) -> dict[str, str]:
    """逐用例**内容指纹**（D198，2026-11-12）：`{用例ID: sha16(归一化 atlas-case 块)}`。

    绑定对象 = 用例真相源 `product/e2e/cases/*.md` 的 `atlas-case` 块（`step` / `expected` /
    `testid` / `precondition` / `mock` / 覆盖维度…），**不是**生成出的 `.spec.ts`：
    `.atlas` 重放、生成器升级、spec 重新生成都不改变它 ⇒ 已审用例不得被判待审。
    归一化：逐行剥 `#` 后行内注释、折叠空白、丢空行；`_file` / `_body`（含注释原文）不参与。
    """
    try:
        mod = load_validator(root)
        blocks, _pages = mod.gather_shards(load_layout(root).e2e_dir / "cases")
    except (LayoutError, OSError):
        return {}
    strip = load_module("stack_profile").strip_inline_comment
    out: dict[str, str] = {}
    for cid, block in blocks.items():
        norm: dict = {}
        for key, val in block.items():
            if key.startswith("_"):
                continue
            if isinstance(val, list):
                items = [re.sub(r"\s+", " ", strip(str(x)).strip()) for x in val]
                norm[key] = [x for x in items if x]
            else:
                norm[key] = re.sub(r"\s+", " ", strip(str(val)).strip())
        out[cid] = _sha16(json.dumps(norm, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")))
    return out


def review_fingerprint(root: Path) -> dict:
    """`case_review_state` 复算用的当前指纹面（不进 `provenance` 的前端负载）。

    D198：新增 `case`（用例内容指纹，评审新鲜度的**唯一权威**）；`cases`（生成物脚本块）
    仅保留给旧账本迁移期做保守兜底。
    """
    _shared, shared_hash, _fallback = shared_script_hashes(root)
    return {
        "scripts": script_file_hashes(root),
        "shared_hash": shared_hash,
        "cases": case_fingerprints(load_layout(root).e2e_scripts_dir),
        "case": case_content_hashes(root),
    }


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
        "app_hash": app_fingerprint(root),
        "actor_type": actor_type,
    }


def run_provenance(root: Path) -> dict:
    """运行期 provenance（RFC-20261108-02 §3.5）：随 `done` 事件回传，`_compact` 只认它。"""
    return dict(repo_provenance(root), **review_fingerprint(root))


def case_review_state(cid: str, snap: dict, current: dict | None) -> dict:
    """计算单个用例在当前内容下的评审新鲜度。

    状态闭集（D128 四态语义不变）：
      - unreviewed: 尚未标记评审通过
      - fresh: 评审指纹与当前**内容**一致（有效评审）
      - stale: 评审后该用例的脚本块 / 文件内共享代码 / 共享脚本 / 应用代码已变化
      - legacy: 历史账本条目无可用指纹（来源无法验证）

    D174：新账本条目按「内容」判——
      ① 用例自己的 test 块（`fp.block`）变了 ⇒ 只作废这一条；
      ② 同文件块外代码（`fp.rest`）变了 ⇒ 该文件全部用例作废；
      ③ 共享脚本（`fp.shared`）变了 ⇒ 全部作废；
      ④ 应用代码（`fp.app`）变了 ⇒ 全部作废；
      ⑤ 用例换了脚本文件 / 当前脚本里找不到 ⇒ 作废。
    D198（2026-11-12）：新条目以**用例内容指纹** `fp.case`（真相源 `cases/*.md` 的
    `atlas-case` 块归一化哈希）为唯一权威 —— `.atlas` 重放 / 生成器升级 / spec 重生成
    都不再使已审用例失效；只有 `step`/`expected`/`testid` 等内容的真实变化才 stale。
    旧条目（无 `fp.case`）走迁移：当前能解析出内容指纹 ⇒ 直接沿用已审（旧账本无法还原评审
    时的 md 内容，块差异可能只是生成器升级；重跑/提交后自动写入 `fp.case`）；解析不到该用例
    时退回比生成物块 `block`/`rest`（忽略 `shared`/`app`）。
    更旧条目（无 `fp`）沿用 D128 的 HEAD + 全局脚本散列比较（fail-closed，重提交后升级）。
    """
    reviewed = snap.get("reviewed") or {}
    if not reviewed.get("pass"):
        return {"state": "unreviewed", "reason": "未评审"}
    prov = snap.get("prov")
    # 父仓模式（RFC-20261108-02 §3.5 / §3.6）：`reviewed.pass` 必须绑定**最近一次 run**
    # 的 run-time provenance。提交时用当前值补的 prov 没有 `fp` ⇒ fail-closed 为 stale。
    # 单仓分支不走这里，保持 D128 / D174 既有语义逐字节不变。
    if current is not None and current.get("solution_root"):
        if not isinstance(prov, dict) or not isinstance(prov.get("fp"), dict):
            return {"state": "stale",
                    "reason": "父仓模式无 run-time provenance，需重跑后重审", "prov": prov}
    if not prov or not isinstance(prov, dict) or (not prov.get("head_sha") and not prov.get("scripts_hash")):
        return {"state": "legacy", "reason": "历史快照无提交指纹，需重审"}
    if current is None:
        return {"state": "legacy", "reason": "未提供当前工作区指纹，新鲜度无法核验"}
    fp = prov.get("fp")
    if isinstance(fp, dict):
        mismatches = []
        # D198：内容指纹优先 —— 只要 `atlas-case` 块（step/expected/testid…）没变，
        # 生成物重生成 / 共享脚本变化 / 应用代码变化都不作废已审状态。
        if fp.get("case"):
            cur_case = (current.get("case") or {}).get(cid)
            if not cur_case:
                return {"state": "stale",
                        "reason": "用例分片里找不到该用例（内容指纹缺失）", "prov": prov}
            if cur_case != fp["case"]:
                return {"state": "stale",
                        "reason": "用例内容变动（step/expected/testid 等）", "prov": prov}
            res = {"state": "fresh", "prov": prov}
            if prov.get("git_dirty"):
                res["warning"] = "提交时工作区有未提交改动（dirty），提交后请先落库"
            return res
        # 旧账本迁移：无内容指纹时，若当前能解析出该用例的内容指纹 ⇒ 直接沿用已审
        # （旧账本无法还原评审时的 md 内容；块差异可能只是生成器升级造成的，不能据此
        #  要求重审）。本次起的新评审都会写入 `fp.case`，之后只认内容。
        if (current.get("case") or {}).get(cid):
            res = {"state": "fresh", "prov": prov}
            if prov.get("git_dirty"):
                res["warning"] = "提交时工作区有未提交改动（dirty），提交后请先落库"
            return res
        cur = (current.get("cases") or {}).get(cid)
        script = fp.get("script")
        if script:
            if not isinstance(cur, dict):
                mismatches.append(f"脚本中找不到该用例({script})")
            else:
                if cur.get("script") != script:
                    mismatches.append(f"脚本位置变动({script}→{cur.get('script')})")
                elif cur.get("block") != fp.get("block"):
                    mismatches.append(f"用例脚本变动({script})")
                if cur.get("rest") != fp.get("rest"):
                    mismatches.append(f"同文件共享代码变动({script})")
        if mismatches:
            return {"state": "stale", "reason": "；".join(mismatches), "prov": prov}
        res = {"state": "fresh", "prov": prov}
        if prov.get("git_dirty"):
            res["warning"] = "提交时工作区有未提交改动（dirty），提交后请先落库"
        return res
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
    """唯一来源（靶场，E1 单段）与它的 baseURL。地址的唯一来源是 stack-profile.yaml。

    `applicable=False` = 本源**无实体页面**（solution 根 / 父仓）：不展示「缺 app_base_url
    索取」提示，也不参与真实应用执行判定。成员仓缺 `app_base_url` 时仍如实提示、不猜默认。
    """
    profile = load_layout(root).stack_profile
    prof = load_profile_parser(root).parse_profile(profile.read_text(encoding="utf-8"))
    app = _e2e_section(prof).get("app_base_url")
    if _is_solution_root(root):
        return {
            "app": {"label": "真实应用", "base_url": app, "configured": True,
                    "applicable": False,
                    "why": "本源无实体页面（solution 根 / 父仓），不参与真实应用执行"},
        }
    return {
        "app": {"label": "真实应用", "base_url": app, "configured": bool(app),
                "applicable": True,
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
        acs = ac_coverage.split_acs(r[idx["关联AC"]])
        cases.append({
            "id": cid,
            "page": r[idx["页面"]],
            "title": r[idx["中文标题"]],
            "type": r[idx["类型"]],
            # 主 AC + 全量 token 列表（多值时前端逐个渲染，不显示原始逗号串）
            "ac": acs[0] if acs else "",
            "acs": acs,
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


# solution 根：成员用例在本控制台**只读**（RFC-20261108-02 二期·逐条聚合）。
# 执行需要成员自己的 spec 目录 / 账本 / base_url，父仓没有可安全路由的执行器；
# 因此不渲染执行/评审控件，`/api/run` 与 `/api/submit` 对成员复合键显式拒绝。
MEMBER_READONLY_REASON = (
    "成员用例在父仓只读：执行需成员自己的 spec 目录 / 账本 / base_url，父仓控制台不代跑；"
    "评审请回成员仓 atlas console --root <member>")


def _status_counts(cases: list[dict]) -> dict:
    out = {"total": len(cases), "green": 0, "red": 0, "blocked": 0, "skipped": 0}
    for c in cases:
        st = c.get("status")
        if st in out and st != "total":
            out[st] += 1
    return out


def _review_counts(cases: list[dict]) -> dict:
    out = {"fresh": 0, "stale": 0, "unreviewed": 0, "legacy": 0}
    for c in cases:
        st = (c.get("review_state") or {}).get("state")
        if st in out:
            out[st] += 1
    return out


def member_console_cmd(mroot: Path, port: int) -> str:
    """成员控制台启动命令：可直接复制执行（路径含空格/中文时按 shell 规则转义）。

    契约 `rings/e2e/reference.md §10.1.2` 第 6 条：父仓只提供入口与命令，
    执行/评审/账本仍归成员进程。
    """
    argv = [sys.executable or "python3", str(Path(__file__).resolve()),
            "--root", str(mroot), "--port", str(port), "--host", "127.0.0.1"]
    return " ".join(shlex.quote(x) for x in argv)


def member_targets(root: Path, parent_port: int = 4190) -> list[dict]:
    """清单顺序 ⇒ 成员控制台目标（名称 / 相对路径 / 绝对根 / 确定性端口）。

    端口 = 父仓端口 + 1 + 成员序号（序号 = `atlas.solution.yaml` 成员顺序）；
    不探测、不扫描，重启后稳定。只读聚合与自动拉起共用这一处推导，避免两份端口规则漂移。
    """
    root = Path(root)
    if not _is_solution_root(root):
        return []
    out: list[dict] = []
    for idx, ent in enumerate(load_manifest(root).get("members") or []):
        rel = str(ent.get("path") or "")
        out.append({
            "name": str(ent.get("name") or Path(rel).name),
            "path": rel,
            "root": str((root / rel).resolve()),
            "port": parent_port + 1 + idx,
        })
    return out


def member_snapshots(root: Path, parent_port: int = 4190) -> dict:
    """solution 根 ⇒ 逐成员只读快照（逐条用例按成员分组）。

    只读边界（契约 `rings/e2e/reference.md §10.1.2` 第 6 条 / `shared/solution.md §6.1`）：
    只调 `snapshot()` / `Ledger.read()` / provenance 复算，不复制成员用例正文进父仓，
    不写成员索引/账本，不代跑。非 solution 根返回空成员表 ⇒ 单根行为逐字节不变。

    成员状态闭集：`ok` / `no_local_e2e` / `missing` / `layout_error` / `index_invalid`。
    用例 ID 跨成员冲突不改本地 ID，用 `uid = <成员名>:<用例ID>` 复合键区分，
    并在 `conflicts` 里显式列出，不静默覆盖。
    """
    root = Path(root)
    if not _is_solution_root(root):
        return {"scope": "single", "members": [], "conflicts": []}
    members: list[dict] = []
    owners: dict[str, list[str]] = {}
    for tgt in member_targets(root, parent_port):
        name = tgt["name"]
        rel = tgt["path"]
        mroot = Path(tgt["root"])
        port = int(tgt["port"])
        item = {
            "id": name, "name": name, "path": rel, "root": str(mroot),
            "readonly": True, "run_blocked_reason": MEMBER_READONLY_REASON,
            "console_url": f"http://127.0.0.1:{port}/",
            "console_cmd": member_console_cmd(mroot, port),
            "state": "ok", "reason": None, "index": None, "cases": [],
            "counts": {"total": 0, "green": 0, "red": 0, "blocked": 0, "skipped": 0},
            "review": {"fresh": 0, "stale": 0, "unreviewed": 0, "legacy": 0},
        }
        members.append(item)
        if not mroot.is_dir():
            item.update(state="missing", reason=f"成员路径不存在：{rel}")
            continue
        try:
            lay = load_layout(mroot)
        except LayoutError as exc:
            item.update(state="layout_error", reason=str(exc))
            continue
        item["index"] = lay.print_value("e2e_index")
        if not lay.e2e_index.is_file():
            item.update(state="no_local_e2e",
                        reason="成员没有本地 E2E 索引（合法；父仓不代建、不补空骨架）")
            continue
        try:
            snap = snapshot(mroot)
        except SnapshotError as exc:
            item.update(state="index_invalid", reason=str(exc))
            continue
        except Exception as exc:  # 成员侧异常不得拖垮父仓视图
            item.update(state="index_invalid", reason=f"{type(exc).__name__}: {exc}")
            continue
        try:
            current = dict(repo_provenance(mroot), **review_fingerprint(mroot))
            committed = Ledger(mroot, "只读视图").committed_snapshot("app", current)
        except Exception as exc:
            committed = {"cases": {}}
            item["review_problem"] = f"评审态未计算：{type(exc).__name__}: {exc}"
        reviewed = committed.get("cases") or {}
        cases = []
        for c in snap["cases"]:
            cid = c["id"]
            owners.setdefault(cid, []).append(name)
            rs = (reviewed.get(cid) or {}).get("review_state") or {}
            row = dict(c)
            row.update({
                "uid": f"{name}:{cid}",
                "member": name,
                "scope": "member",
                "readonly": True,
                "run_blocked_reason": MEMBER_READONLY_REASON,
                "review_state": {"state": rs.get("state") or "unreviewed",
                                 "reason": rs.get("reason")},
            })
            cases.append(row)
        item["cases"] = cases
        item["counts"] = _status_counts(cases)
        item["review"] = _review_counts(cases)
    conflicts = [{"case_id": cid, "members": names}
                 for cid, names in sorted(owners.items()) if len(names) > 1]
    return {"scope": "solution", "members": members, "conflicts": conflicts}


MEMBER_CONSOLE_TIMEOUT = 10.0
# 失败冷却：页面每次刷新都会走一次「无监听则拉起」的兜底检查，冷却避免刷屏式重复拉起。
MEMBER_CONSOLE_RETRY_COOLDOWN = 30.0
NO_SPAWN_NOTE = "--no-spawn：自动拉起已关闭，按页面命令手动启动成员控制台"
TERMINAL_APP = "Terminal"


class SpawnError(RuntimeError):
    """自动拉起失败（带可读原因，不静默）。"""


def member_console_argv(mroot: Path, port: int) -> list[str]:
    """成员控制台 argv（与页面「手动启动命令」同一份参数口径）。"""
    return [sys.executable or "python3", str(Path(__file__).resolve()),
            "--root", str(mroot), "--port", str(port), "--host", "127.0.0.1",
            "--no-spawn"]  # 子进程不再递归拉起；防御 solution 嵌套


def member_console_shell_command(mroot: Path, port: int, log: Path, pidfile: Path) -> str:
    """Terminal 里执行的一行命令：先记 PID，再 exec 成控制台进程。

    脱离口径（2026-11-12）：命令交给 Terminal.app 的 shell 执行 ⇒ 进程父级是 Terminal，
    父控制台所在会话被回收时不会连带被杀（本机实测 nohup / setsid / PPID=1 都会在
    5–10 秒内被 SIGKILL，只有 Terminal 托管能真正活下来）。
    """
    argv = member_console_argv(mroot, port)
    return (f"cd {shlex.quote(str(mroot))} && "
            f"echo $$ > {shlex.quote(str(pidfile))}; "
            f"exec {' '.join(shlex.quote(x) for x in argv)} "
            f">> {shlex.quote(str(log))} 2>&1")


def _applescript_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def terminal_spawn_command(shell_cmd: str, app: str = TERMINAL_APP) -> str:
    """把 shell 命令包成 AppleScript：`Terminal → do script`（不 activate，不抢焦点）。"""
    return f'tell application "{app}" to do script "{_applescript_escape(shell_cmd)}"'


class MemberConsoles:
    """solution 根下自动拉起成员控制台（2026-11-10，方案 B：自动拉起、不代理执行）。

    边界：只起进程、只探端口、不转发执行与提交、不写成员任何文件——成员账本仍由成员
    进程写。**脱离口径（2026-11-12）**：拉起一律经 Terminal.app 托管，父控制台所在
    会话被回收时成员进程继续存活；因此父控制台退出时**不再回收**自己拉起的成员
    （复用的外部实例本来就不碰）。

    端口占用（不杀、不抢）：能响应的成员控制台 ⇒ 复用；端口被其它进程占着 ⇒ 跳过该
    成员并在页面披露原因；端口空闲 ⇒ 经 Terminal 拉起，`MEMBER_CONSOLE_TIMEOUT` 内
    未就绪如实报失败并附日志尾部。

    拉起时机：父控制台启动时逐个拉起；页面访问（`/api/cases`）与成员行入口点击
    （`/api/member-open`）时再做一次「无监听则拉起、已有监听则复用」的兜底。

    状态闭集：`ready` / `reused` / `starting` / `failed` / `skipped` / `disabled` / `no_index`。
    """

    def __init__(self, root: Path, port: int, enabled: bool = True,
                 spawner=None, ready_timeout: float = MEMBER_CONSOLE_TIMEOUT):
        self.root = Path(root)
        self.port = port
        self.enabled = enabled
        # 可注入替换（单测）：签名 (name, mroot, port) -> handle dict；默认走 Terminal。
        self.spawner = spawner
        self.ready_timeout = float(ready_timeout)
        self._lock = threading.Lock()
        self._targets: dict[str, dict] = {}
        self._handles: dict[str, dict] = {}
        self._info: dict[str, dict] = {}
        self._threads: list[threading.Thread] = []
        self._inflight: set[str] = set()
        self._last_attempt: dict[str, float] = {}
        self._stopping = False

    # ---- 对外
    def start_all(self, targets: list[dict], states: dict[str, str] | None = None) -> None:
        if not targets:
            return
        states = states or {}
        for tgt in targets:
            self._targets[tgt["name"]] = tgt
            member_state = states.get(tgt["name"], "ok")
            if member_state != "ok":
                # 没有可用本地 E2E 索引的成员不占进程（起来也是空列表 + 报错页）。
                self._set(tgt["name"], "no_index",
                          f"无本地 E2E 索引（{member_state}），未启动控制台")
                continue
            if not self.enabled:
                self._set(tgt["name"], "disabled", NO_SPAWN_NOTE)
                continue
            self._kick(tgt)

    def ensure(self, name: str, wait: bool = False) -> dict:
        """「无监听则拉起、已有监听则复用」的兜底入口（页面访问 / 成员行点击共用）。

        `wait=True` 时最多等 `ready_timeout + 5s`，供 `/api/member-open` 跳转使用；
        `wait=False` 只投递异步拉起，页面轮询即可看到 `starting → ready`。
        """
        tgt = self._targets.get(name)
        if tgt is None:
            tgt = next((t for t in member_targets(self.root, self.port)
                        if t["name"] == name), None)
            if tgt is not None:
                self._targets[name] = tgt
        if tgt is None:
            return {"console_state": "skipped", "console_note": f"未知成员：{name}",
                    "console_log": None}
        if not self.enabled:
            self._set(name, "disabled", NO_SPAWN_NOTE)
            return self.snapshot(name)
        snap = self.snapshot(name)
        if snap.get("console_state") in ("ready", "reused"):
            return snap
        with self._lock:
            inflight = name in self._inflight
            last = self._last_attempt.get(name)
        th = None
        if not inflight:
            if (last is not None
                    and time.monotonic() - last < MEMBER_CONSOLE_RETRY_COOLDOWN
                    and snap.get("console_state") == "failed"):
                return snap  # 冷却期内不反复拉起；把上次的可读原因原样留给页面
            th = self._kick(tgt)
        if wait:
            if th is not None:
                th.join(self.ready_timeout + 5.0)
            else:
                deadline = time.monotonic() + self.ready_timeout + 5.0
                while time.monotonic() < deadline:
                    if self.snapshot(name).get("console_state") != "starting":
                        break
                    time.sleep(0.2)
        return self.snapshot(name)

    def snapshot(self, name: str) -> dict:
        with self._lock:
            info = dict(self._info.get(name) or {})
        if not info:
            if self.enabled:
                info = {"console_state": "starting",
                        "console_note": "尚未拉起：页面访问或点击成员入口时会自动启动",
                        "console_log": None}
            else:
                info = {"console_state": "disabled", "console_note": NO_SPAWN_NOTE,
                        "console_log": None}
        info.setdefault("console_log", None)
        return info

    def stop(self) -> None:
        """父控制台退出：**不回收** Terminal 托管的成员控制台。

        「拉起后真正脱离、不随父会话回收而死」是硬要求；父退出时顺手杀子进程会把
        原来的问题换条路径重现。复用的外部实例本来就不碰。需要停止请到对应
        Terminal 窗口 Ctrl-C（或换端口重开）。
        """
        with self._lock:
            self._stopping = True

    # ---- 内部
    def _set(self, name: str, state: str, note: str, log: Path | None = None) -> None:
        with self._lock:
            self._info[name] = {"console_state": state, "console_note": note,
                                "console_log": str(log) if log else None}

    def _kick(self, tgt: dict) -> threading.Thread | None:
        """投递一次异步拉起；同名已在拉起中 ⇒ 返回 None（不重复拉）。"""
        name = tgt["name"]
        with self._lock:
            if name in self._inflight:
                return None
            self._inflight.add(name)
            self._last_attempt[name] = time.monotonic()
        th = threading.Thread(target=self._start_one, args=(tgt,),
                              name=f"member-console-{name}", daemon=True)
        th.start()
        self._threads.append(th)
        return th

    def _start_one(self, tgt: dict) -> None:
        name, mroot, port = tgt["name"], Path(tgt["root"]), int(tgt["port"])
        try:
            if not mroot.is_dir():
                self._set(name, "skipped", f"成员路径不存在，不拉起：{tgt['path']}")
                return
            probe = self._probe(port)
            if probe == "member":
                self._set(name, "reused",
                          f"端口 {port} 上已有成员控制台在响应，直接复用"
                          f"（非本进程拉起，不重启、不杀、退出不回收）")
                return
            if probe == "other":
                self._set(name, "skipped",
                          f"端口 {port} 已被占用（有响应，但不是可用的成员控制台——可能是旧版本或"
                          f"别的进程），不抢占、不杀；换父仓端口可避开")
                return
            self._set(name, "starting",
                      f"正在拉起成员控制台（端口 {port}，Terminal.app 托管）…")
            try:
                handle = self._spawn(name, mroot, port)
            except SpawnError as exc:
                self._set(name, "failed", f"拉起失败：{exc}")
                return
            except OSError as exc:
                self._set(name, "failed", f"拉起失败：{type(exc).__name__}: {exc}")
                return
            with self._lock:
                self._handles[name] = handle
            log = Path(handle["log"])
            deadline = time.monotonic() + self.ready_timeout
            while time.monotonic() < deadline:
                if self._probe(port) == "member":
                    pid = self._read_pid(handle) or handle.get("pid")
                    via = ("Terminal.app 托管，父会话退出不影响"
                           if handle.get("via") == "terminal" else "子进程托管")
                    self._set(name, "ready",
                              f"已就绪（PID {pid}，端口 {port}，{via}）", log)
                    return
                pid = self._read_pid(handle) or handle.get("pid")
                if pid and not self._pid_alive(pid):
                    self._set(name, "failed",
                              f"成员控制台启动即退出（PID {pid}）。日志尾部：{self._tail(log)}",
                              log)
                    return
                time.sleep(0.2)
            self._set(name, "failed",
                      f"{self.ready_timeout:.0f}s 内未就绪（端口 {port}）。"
                      f"日志尾部：{self._tail(log)}", log)
        finally:
            with self._lock:
                self._inflight.discard(name)

    def _spawn(self, name: str, mroot: Path, port: int) -> dict:
        """拉起成员控制台；默认经 Terminal.app 托管（真正脱离父会话）。

        返回 handle：`{via, pid, log, pidfile, shell_cmd}`。失败一律抛 `SpawnError`，
        带上 osascript 的原始错误行——页面直接展示，不静默。
        """
        if self.spawner is not None:
            return self.spawner(name, mroot, port)
        return self._spawn_terminal(name, mroot, port)

    def _spawn_terminal(self, name: str, mroot: Path, port: int) -> dict:
        safe = re.sub(r"[^0-9A-Za-z_.-]", "_", name)
        log = Path(tempfile.gettempdir()) / f"atlas-console-{port}-{safe}.log"
        pidfile = Path(tempfile.gettempdir()) / f"atlas-console-{port}-{safe}.pid"
        try:
            pidfile.unlink()
        except OSError:
            pass
        shell_cmd = member_console_shell_command(mroot, port, log, pidfile)
        try:
            res = subprocess.run(["osascript", "-e", terminal_spawn_command(shell_cmd)],
                                 capture_output=True, text=True, timeout=20)
        except FileNotFoundError as exc:
            raise SpawnError("找不到 osascript（非 macOS 或 PATH 不完整），"
                             "请用页面「手动启动命令」拉起") from exc
        except subprocess.TimeoutExpired as exc:
            raise SpawnError("osascript 调用超时（Terminal 无响应，或自动化权限被拒）") from exc
        if res.returncode != 0:
            detail = [ln.strip() for ln in (res.stderr or res.stdout or "").splitlines()
                      if ln.strip()]
            raise SpawnError(f"osascript 调用失败（exit={res.returncode}）："
                             f"{detail[-1] if detail else '无输出'}")
        return {"via": "terminal", "pid": self._read_pid({"pidfile": str(pidfile)}),
                "log": str(log), "pidfile": str(pidfile), "shell_cmd": shell_cmd}

    @staticmethod
    def _read_pid(handle: dict) -> int | None:
        try:
            return int(Path(handle["pidfile"]).read_text(encoding="utf-8").strip())
        except (OSError, ValueError, KeyError):
            return None

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _probe(port: int, host: str = "127.0.0.1") -> str:
        """端口判别：`free` 空闲 / `member` 成员控制台 / `other` 有响应但不是。"""
        try:
            with socket.create_connection((host, port), timeout=0.3):
                pass
        except OSError:
            return "free"
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/api/cases", timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return "other"
        return "member" if data.get("scope") == "single" else "other"

    @staticmethod
    def _tail(log: Path, lines: int = 5) -> str:
        try:
            text = Path(log).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "（无日志）"
        rows = [ln.strip() for ln in text.splitlines() if ln.strip()][-lines:]
        return " / ".join(rows) if rows else "（日志为空）"


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
            m = _CASE_TEST_LINE.match(line)
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
        for cid, snap in merged.items():
            if isinstance(snap, dict):
                snap["review_state"] = case_review_state(cid, snap, current)
        return {"ts": ts, "actor": actor, "cases": merged,
                "reviewed_scope": scope, "reviewed_count": len(scope)}


# ---------------------------------------------------------------- 执行器（并发=1）

class Runner:
    def __init__(self, root: Path, ledger: Ledger, timeout: int, head: bool, keep_open: bool = True,
                 kill_grace_secs: float = 5.0):
        self.root = root
        self.layout = load_layout(root)
        self.ledger = ledger
        self.timeout = timeout
        self.head = head
        # P13=A（RFC-20261104-01）：超时先 SIGTERM，等 grace（默认 5s、钳 0–15s）再 SIGKILL。
        # 只改「进程怎么退出」，不改「超时判 FAIL」；grace 只对 node 进程，worker/browser 不在控制内。
        self.kill_grace_secs = max(0.0, min(15.0, float(kill_grace_secs)))
        self._pre_archived = False  # 每批只做一次 pre-run 归档（批首、第一个用例起跑前）
        # D194（2026-11-12）：每次 run 的仓库外独立输出目录；起跑时创建，结果/证据/归档全部落这里。
        self.run_dir: Path | None = None
        self.evidence_dir: Path | None = None
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
        # 硬性要求（2026-11-12 取代 2026-11-11「只手动关」）：持窗到下一条起跑。已结束但仍持窗的
        # 进程集中在这里——跑完**不**kill、超时**不**kill；**起跑下一条**时由
        # `_collect_held_windows()` 统一收掉（唯一自动结束时点）；用户也可手动关窗
        # 或点「关闭浏览器窗口」（close_window()）提前结束它们。
        self._held_procs: list[subprocess.Popen] = []
        # RFC-20261108-02 §3.5：运行期 provenance（起跑时快照），随 done 回传；
        # 直接调 `_run` 的测试/工具不设置 ⇒ done 不带 prov，父仓模式据此 fail-closed。
        self.run_prov: dict | None = None

    def start(self, case: dict, nodeid: str, slowmo: int, source: str, base_url: str) -> tuple[bool, str]:
        # 执行前预检（RFC-20261112-01 v1 / D）：登录态按形态分治判定 + 必填 probe + 来源 / 指纹 /
        # 哈希一致性。不可用即拒绝执行并给出可读原因（含 `atlas e2e login`），不起注定 401 的子进程。
        verdict = auth_state.preflight(self.root)
        if not verdict.get("ok"):
            return False, verdict.get("reason") or "登录态预检未通过"
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
            self._reap_finished()   # 先清掉已自行退出（人手动关窗）的持窗进程
            self.running = True
            self.case = case["id"]
            self.lines = []
            self.done = None
            # 硬性要求（2026-11-12）：起跑下一条前收掉仍开着的旧窗口；日志须落在
            # `lines = []` 之后才能进本条的新输出缓冲
            self._collect_held_windows()
        # 运行期 provenance 在起跑前快照（`_run` 只回传，不重新计算）。
        self.run_prov = run_provenance(self.root)
        threading.Thread(target=self._run, args=(case, nodeid, slowmo, source, base_url, pw_bin, nm_dir), daemon=True).start()
        return True, ""

    def _reap_finished(self) -> None:
        """移除已自行退出（人手动关窗）的持窗进程；**绝不主动 kill**。调用方须已持 cond 锁。"""
        self._held_procs = [p for p in self._held_procs if p.poll() is None]
        if not self._held_procs:
            self.held_case = None

    def _collect_held_windows(self) -> int:
        """硬性要求（2026-11-12）：起跑下一条用例前，收掉之前保留的全部浏览器窗口。

        「持窗到下一条起跑」——这是持窗模式下**唯一**允许自动结束持窗进程的时点；
        跑完、超时都**不得**走到这里。自行持 cond 锁（RLock 可重入：`start()` 持锁中
        调用安全，测试直接调用也安全）；kill 后 `_watch_held` 线程会自行完成残余
        清理（此处同步清空，双写幂等）。返回实际收掉的窗口数（0 = 无旧窗，静默不打日志）。
        """
        with self.cond:
            killed = 0
            for proc in self._held_procs:
                if proc.poll() is None:
                    try:
                        proc.kill()
                        killed += 1
                    except Exception:
                        pass
            if killed:
                had = self.held_case
                self._held_procs = []
                self.held_case = None
                self.lines.append(f"↻ 起跑新用例：已收掉之前保留的浏览器窗口（{had or '上一条'}）")
                self.cond.notify_all()
            return killed

    def close_window(self) -> dict:
        """手动关掉被保留的浏览器窗口 —— 用户主动收窗的途径（跑完即关仍不存在；
        自动收窗只有「起跑下一条」这一个时点，见 `_collect_held_windows()`）。"""
        with self.cond:
            held = self._held_procs
            self._held_procs = []
            had = self.held_case
            self.held_case = None
        closed = 0
        for proc in held:
            if proc.poll() is None:
                try:
                    proc.kill()
                    closed += 1
                except Exception:
                    pass
        if closed:
            self._emit(f"⏹ 已关闭 {closed} 个保留的浏览器窗口（用户手动操作）")
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
                if self.run_prov:
                    ev["prov"] = self.run_prov
                with self.cond:
                    self.running = False
                    self.done = ev
                    self.cond.notify_all()
                return
        # 起跑前证据归档：批首、第一个用例起跑前做一次（归档**上一次** run 的仓库外产物）。
        self._archive_pre_once()
        # D194（2026-11-12）：每次 run 使用仓库外独立输出目录（结构修复 EACCES + 并发互清）。
        try:
            keep = int(os.environ.get("ATLAS_RUN_KEEP", "10") or 10)
        except ValueError:
            keep = 10
        self.run_dir = run_workspace.new_run_dir(self.root)
        self.evidence_dir = run_workspace.evidence_root(self.root)
        run_workspace.prune(self.root, keep=keep)  # 含本次 ⇒ 磁盘上恒定保留最近 keep 次
        legacy = run_workspace.legacy_run_dir(self.root)
        if legacy.is_dir():
            self._emit(f"# 提示：旧仓内运行目录仍存在（不删除，可手动清理）：{legacy}\n")
        # node 单轨（3507 BO）：`file:line` 过滤 + 运行器原生 flag（--headed）；NODE_PATH 让生成物里的
        # @playwright/test 解析到项目声明的依赖目录（与 atlas_check 真跑门同一姿势）。
        cmd = [str(pw_bin), "test", "-c", "playwright.config.ts", nodeid]
        # `--output` 覆盖配置里的 outputDir（旧生成物也能吃到结构修复）；JSON reporter 的落点由
        # Playwright 官方环境变量 PLAYWRIGHT_JSON_OUTPUT_NAME 覆盖。
        cmd += ["--output", str(self.run_dir)]
        if self.head:
            cmd.append("--headed")
        if self.keep_open:
            # D126（2026-10-21）：Playwright 默认 test timeout（30s）**计入 fixture teardown**
            # ⇒ `atlas-hold.ts` 的留窗等待会被判超时并把浏览器关掉（实测报错：
            # Tearing down "atlasHold" exceeded the test timeout of 30000ms）。
            # 持窗模式关掉运行器自身超时，控制台的 wall-clock `--timeout` 是唯一超时真相源
            # （持窗模式到点只提示、不 kill；自动关窗模式保留 30s 原生兜底，防孤儿进程）。
            cmd.append("--timeout=0")
        self._emit(f"# 来源 {source} → ATLAS_BASE_URL={base_url}（slowmo={slowmo}ms via ATLAS_SLOWMO）\n$ cd {scripts}\n$ {' '.join(cmd)}\n")
        t0 = time.time()
        timed_out = False
        warned_timeout = False
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
        env = {**os.environ, "ATLAS_BASE_URL": base_url, "ATLAS_SLOWMO": str(slowmo),
               "ATLAS_RUN_DIR": str(self.run_dir),
               "ATLAS_EVIDENCE_DIR": str(self.evidence_dir),
               "PLAYWRIGHT_JSON_OUTPUT_NAME": str(self.run_dir / "results.json")}
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
                    if self.keep_open:
                        # 硬性要求（2026-11-12）：持窗模式跑完后绝不自动关浏览器 ⇒ 超时只提示一次，
                        # 不 kill、不退出循环；用例/窗口等到用户手动关窗或点「关闭浏览器窗口」为止。
                        if not warned_timeout:
                            warned_timeout = True
                            self._emit(
                                f"⏱ 已超过 --timeout={self.timeout}s：持窗模式不主动结束进程，"
                                "浏览器窗口保持打开（需要结束请手动关窗或点「关闭浏览器窗口」）")
                        time.sleep(0.1)
                        continue
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
        # 失败后证据归档：只复制、只观 WARN，绝不改判定（ok / timeout 照旧）。
        ev_archive = None
        if not ok:
            ev_archive = evidence_archive.archive_run_artifacts(
                self.root, source=f"e2e_console-{case['id']}", phase="fail",
                failed_cases=[case["id"]],
                run_dir=self.run_dir, evidence_dir=self.evidence_dir)
            if ev_archive["status"] == "WARN":
                self._emit(f"[证据归档] WARN {'; '.join(ev_archive['warnings'])[:300]}")
        with self.cond:
            raw = list(self.lines)
        # 「乙」：执行结果只回给页面（浏览器存本地草稿），提交时才落账本
        ev = {"kind": "done", "case": case["id"], "nodeid": nodeid, "ok": ok, "exit": exit_code,
              "duration_ms": dur, "timeout": timed_out, "held": held,
              "evidence_archive": ev_archive,
              "slowmo": slowmo, "head": self.head, "source": source,
              "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
              # 失败原文是人工评审的输入 ⇒ 交给页面留在本地草稿里（提交时随快照一起落账本）
              "tail": "\n".join(_clean(ln) for ln in raw[-80:])}
        # RFC-20261108-02 §3.5：运行期 provenance 随 done 回传；提交时不得用当前值替代。
        if self.run_prov:
            ev["prov"] = self.run_prov
        with self.cond:
            self.running = False
            self.done = ev
            if held:
                # 硬性要求（2026-11-12「持窗到下一条起跑」）：进程留在持窗清单里——跑完与
                # 超时都**不**杀；下一条起跑时由 `_collect_held_windows()` 收掉，或用户
                # 手动关窗 / 点「关闭浏览器窗口」提前结束。
                self._held_procs.append(proc)
                self.held_case = case["id"]
            self.cond.notify_all()
        if held:
            threading.Thread(target=self._watch_held, args=(proc,), daemon=True).start()

    def _watch_held(self, proc: subprocess.Popen) -> None:
        """人手动关了窗口 ⇒ 持窗进程自然退出 ⇒ 从持窗清单移除（**不** kill）。"""
        try:
            proc.wait()
        except Exception:
            pass
        with self.cond:
            self._held_procs = [p for p in self._held_procs if p is not proc]
            if self._proc is proc:
                self._proc = None
            if not self._held_procs:
                self.held_case = None
            self.cond.notify_all()

    def _archive_pre_once(self) -> None:
        """批首、第一个用例起跑前归档**上一次** run 的仓库外产物（每 Runner 批一次）。"""
        if self._pre_archived:
            return
        self._pre_archived = True
        prev = run_workspace.latest_run_dir(self.root, exclude=self.run_dir)
        if prev is None:
            return
        ev = evidence_archive.archive_run_artifacts(
            self.root, source="e2e_console", phase="pre-run",
            run_dir=prev, evidence_dir=run_workspace.evidence_root(self.root))
        if ev["status"] == "WARN":
            self._emit(f"[证据归档] WARN {'; '.join(ev['warnings'])[:300]}")

    def _kill(self) -> None:
        """P13=A：SIGTERM → grace（默认 5s、钳 0–15s）→ 仍不退出才 SIGKILL。

        **不改超时判定**：调用方随后照旧置 `timed_out=True` ⇒ FAIL。软杀只是让
        Playwright 有机会 flush trace；grace 只对 node 进程，worker / browser 不在控制内。
        """
        proc = self._proc
        if not (proc and proc.poll() is None):
            return
        setattr(proc, "_atlas_killed", True)
        grace = self.kill_grace_secs
        try:
            proc.terminate()
        except Exception:
            pass
        deadline = time.time() + grace
        while grace > 0 and proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
            self._emit(f"⏱ 超时 {self.timeout}s，grace {grace:g}s 内未退出 ⇒ 已硬杀（SIGKILL）")
        else:
            self._emit(f"⏱ 超时 {self.timeout}s，已软杀（SIGTERM，grace {grace:g}s）")

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


def _compact(entry: dict, prov: dict | None = None, cid: str | None = None) -> dict:
    """落账本的快照条目：失败才带输出尾部（80 行，与运行期同长），避免账本被 traceback 撑爆。

    D174：`prov` 带当前指纹面（`cases` / `shared_hash` / `app_hash`）时，逐用例落
    `prov.fp = {script, block, rest, shared, app}` —— 评审新鲜度按内容复算，不再绑 HEAD。
    RFC-20261108-02 §3.5：`fp` **只能**来自运行期 provenance（`entry["prov"]`，由 `done`
    事件回传）；提交时传入的 `prov` 是当前值，不得拿来补 `fp.app`，否则「跑完再改应用、
    只重签」会被误判 fresh。无运行期 provenance ⇒ 不写 `fp`，父仓模式据此 fail-closed。
    """
    out = {"ok": bool(entry.get("ok")), "exit": entry.get("exit"),
           "duration_ms": entry.get("duration_ms"), "timeout": bool(entry.get("timeout")),
           "ts": entry.get("ts")}
    reviewed = entry.get("reviewed") or {}
    if reviewed:
        out["reviewed"] = {"pass": bool(reviewed.get("pass")),
                           "checked_at": reviewed.get("checked_at"),
                           "unchecked_at": reviewed.get("unchecked_at")}
    run_prov = entry.get("prov") if isinstance(entry.get("prov"), dict) else None
    p = run_prov or prov
    if p and isinstance(p, dict):
        out["prov"] = {
            "head_sha": p.get("head_sha"),
            "scripts_hash": p.get("scripts_hash"),
            "git_dirty": p.get("git_dirty"),
            "actor_type": p.get("actor_type", "human"),
        }
        if cid and isinstance(run_prov, dict):
            if isinstance(run_prov.get("fp"), dict):
                out["prov"]["fp"] = dict(run_prov["fp"])
            elif "cases" in run_prov or "shared_hash" in run_prov:
                cf = (run_prov.get("cases") or {}).get(cid) or {}
                out["prov"]["fp"] = {
                    "script": cf.get("script"),
                    "block": cf.get("block"),
                    "rest": cf.get("rest"),
                    "shared": run_prov.get("shared_hash"),
                    "app": run_prov.get("app_hash"),
                    # D198：用例内容指纹（真相源 md），评审新鲜度以它为准
                    "case": (run_prov.get("case") or {}).get(cid),
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
    def __init__(self, root: Path, port: int, slowmo: int, timeout: int, head: bool, keep_open: bool = True,
                 kill_grace_secs: float = 5.0, members: MemberConsoles | None = None,
                 host: str = "127.0.0.1"):
        self.root = root
        self.layout = load_layout(root)
        self.port = port
        self.host = host
        self.targets = member_targets(root, port)
        self.members = members
        self.slowmo = slowmo
        self.actor = f"{os.environ.get('USER', 'local')}·控制台"
        self.ledger = Ledger(root, self.actor)
        self.runner = Runner(root, self.ledger, timeout, head, keep_open,
                             kill_grace_secs=kill_grace_secs)

    def cases_payload(self, source: str) -> dict:
        current_prov = repo_provenance(self.root)
        # 成员聚合是 pure-read（只读成员索引/账本），单根下返回空成员表。
        scope_payload = member_snapshots(self.root, self.port)
        # 「访问父控制台 ⇒ 无监听则拉起、已有监听则复用」：只投递异步拉起，不阻塞本请求。
        if self.members:
            for item in scope_payload.get("members") or []:
                if item.get("state") == "ok":
                    self.members.ensure(item["name"])
        # 运行期状态（自动拉起的结果）只在内存里；`--no-spawn` 时为 disabled。
        for item in scope_payload.get("members") or []:
            item.update(self.members.snapshot(item["name"]) if self.members else {
                "console_state": "disabled", "console_log": None,
                "console_note": "未启用自动拉起（未传入 MemberConsoles），按页面命令手动启动",
            })
        try:
            snap = snapshot(self.root)
        except SnapshotError as exc:
            return {"source": source, "sources": read_sources(self.root), "problem": str(exc),
                    "slowmo": self.slowmo, "timeout": self.runner.timeout, "head": self.runner.head,
                    "ledger": self.layout.print_value("console_ledger"), "cases": [], "nodeids": {},
                    "committed": {"ts": None, "actor": None, "cases": {}},
                    "provenance": current_prov, **scope_payload}
        current = dict(current_prov, **review_fingerprint(self.root))
        current["solution_root"] = _is_solution_root(self.root)
        committed = self.ledger.committed_snapshot(source, current)
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
            **scope_payload,
        }

    def open_member_console(self, name: str) -> tuple[int, dict]:
        """父 → 子跳转：确保成员控制台在跑，再给出它的 host/port。

        返回 `(status, payload)`；`payload.ok=True` 时 `payload.url` 是 302 目标。
        失败带 `console_state` 与可读原因（含 osascript / 日志尾部），不静默。
        """
        tgt = next((t for t in self.targets if t["name"] == name), None)
        if tgt is None:
            return 404, {"ok": False, "error": f"未知成员：{name}",
                         "members": [t["name"] for t in self.targets]}
        url = f"http://{self.host}:{int(tgt['port'])}/"
        if self.members is None:
            return 200, {"ok": True, "url": url, "console_state": "unknown",
                         "console_note": "未启用自动拉起（未传入 MemberConsoles）"}
        snap = self.members.ensure(name, wait=True)
        state = snap.get("console_state")
        if state in ("ready", "reused"):
            return 200, {"ok": True, "url": url, "console_state": state,
                         "console_note": snap.get("console_note")}
        return 503, {"ok": False, "url": url, "console_state": state,
                     "error": snap.get("console_note") or "成员控制台不可用"}


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

    def _redirect(self, url: str) -> None:
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

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
        elif path == "/api/member-open":
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            name = (qs.get("name") or [""])[0]
            code, payload = self.app.open_member_console(name)
            if payload.get("ok"):
                self._redirect(str(payload["url"]))
            else:
                self._json(payload, code)
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
        if body.get("member"):
            # 成员用例在父仓只读：执行需成员自己的 scripts 目录 / 账本 / base_url，绝不代跑。
            self._json({"ok": False, "readonly": True,
                        "error": MEMBER_READONLY_REASON}, 409)
            return
        source = "app"
        src = read_sources(self.app.root).get(source)
        if not src or src.get("applicable") is False or not src.get("configured"):
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
        member_keys = [k for k in draft if ":" in str(k)]
        if member_keys:
            # 复合键只在只读视图里存在；绝不把成员用例写进父仓索引/账本。
            self._json({"ok": False, "readonly": True,
                        "error": "成员用例在父仓只读：拒绝把复合键写进父仓索引/账本（"
                                 + "、".join(str(k) for k in member_keys[:5]) + "）"}, 409)
            return
        source = "app"
        apply = bool(body.get("apply"))
        # 指纹在 writeback 前获取，避免 writeback 自身修改索引使 git_dirty 假阳性（D128）
        prov = repo_provenance(self.app.root)
        current = dict(prov, **review_fingerprint(self.app.root))
        current["solution_root"] = _is_solution_root(self.app.root)
        res = writeback(self.app.root, draft, apply, source)
        if apply:
            snap = {cid: _compact(v, current, cid) for cid, v in draft.items()}
            reviewed_scope = [cid for cid, v in draft.items() if (v.get("reviewed") or {}).get("pass")]
            self.app.ledger.append({"kind": "submit", "source": source,
                                    "changed": res["changed"], "cases": snap,
                                    "prov": prov, "actor_type": prov.get("actor_type", "human"),
                                    "reviewed_scope": reviewed_scope})
            res["committed_ts"] = self.app.ledger.committed_snapshot(source, current).get("ts")
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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="E2E 用例评审控制台")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--port", type=int, default=4190)
    ap.add_argument("--slowmo", type=int, default=500, help="有头执行的慢动作毫秒数（可在页面上改）")
    ap.add_argument("--timeout", type=int, default=120, help="单条用例 wall-clock 超时（秒）")
    ap.add_argument("--no-head", action="store_true", help="不带有头窗口（默认有头）")
    # 硬性要求（2026-11-12）：不提供「跑完自动关」开关；窗口跑完保留，起跑下一条时才自动收掉
    # （`_collect_held_windows()`），用户也可手动关窗或点「关闭浏览器窗口」（close_window()）。
    # 旧 `--auto-close`（跑完即关）已移除，不得以任何形式加回。
    ap.add_argument("--kill-grace", type=float, default=5.0,
                    help="超时软杀 grace 秒数（SIGTERM 后等待；0–15，默认 5；0=立即 SIGKILL）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-spawn", action="store_true",
                    help="不自动拉起成员控制台（solution 根默认按「父仓端口+1+清单序号」"
                         "逐个拉起，退出/信号时只回收自己拉起的那些；端口被占则复用或跳过）")
    return ap


def main() -> int:
    args = build_parser().parse_args()

    root = Path(args.root).resolve()
    try:
        load_layout(root)
    except LayoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    targets = member_targets(root, args.port)
    states = {m["name"]: m["state"]
              for m in (member_snapshots(root, args.port).get("members") or [])}
    consoles = MemberConsoles(root, args.port, enabled=not args.no_spawn)
    consoles.start_all(targets, states)
    atexit.register(consoles.stop)

    def _stop_on_signal(_signum, _frame):
        consoles.stop()
        raise KeyboardInterrupt

    for _sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None),
                 getattr(signal, "SIGHUP", None)):
        if _sig is None:
            continue
        try:
            signal.signal(_sig, _stop_on_signal)
        except (ValueError, OSError):
            pass

    app = App(root, args.port, args.slowmo, args.timeout, not args.no_head,
              not args.no_head, kill_grace_secs=args.kill_grace,
              members=consoles, host=args.host)
    Handler.app = app
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"E2E 用例评审控制台 → http://{args.host}:{args.port}/")
    print(f"  根目录   : {root}")
    print(f"  执行     : {'有头' if app.runner.head else '无头'} · slowmo={args.slowmo}ms · 并发=1 · 超时={args.timeout}s")
    print(f"  跑完关窗 : {'无窗口（--no-head，无自动关窗语义）' if not app.runner.keep_open else '**不关**；起跑下一条时自动收掉旧窗（持窗到下一条起跑，2026-11-12）；也可手动关或点「关闭浏览器窗口」'}")
    print("  落盘时机 : 点「提交」才写账本 + 回写索引（执行/勾选只存页面本地草稿）")
    if targets:
        mode = "关闭（--no-spawn）" if args.no_spawn else "自动拉起（Terminal.app 托管，父会话退出不影响）"
        print(f"  成员控制台: {mode} · {len(targets)} 个"
              f"（端口 {args.port + 1}–{args.port + len(targets)}）· 已有监听则复用，不重启、不杀")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n停止。")
    finally:
        consoles.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
