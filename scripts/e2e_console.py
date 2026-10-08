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

* 「执行用例」= 起一次**有头**子进程跑这一条（`--headed --slowmo <N>`，看得见浏览器在动）；
* **并发 = 1**（同时只跑一条，其余按钮禁用）；单条 wall-clock 超时到点 kill 并如实报「超时」；
* 「人工 review 通过」= 人工复核**执行结果**符合业务预期；只在**执行通过**后解锁按钮
  （不通过就是没通过，回对话改用例）。

用法：

    python3 .atlas/scripts/e2e_console.py [--root .] [--port 4190] [--slowmo 500] [--timeout 120] [--no-head]
"""
from __future__ import annotations

import argparse
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


# ---------------------------------------------------------------- 用例真相源（只读）

def load_validator(root: Path):
    """复用 E2E 环校验器的分片/索引解析器（同一份格式解析，不另写）。"""
    path = root / ".atlas" / "validators" / "validate_e2e_index.py"
    spec = importlib.util.spec_from_file_location("atlas_validate_e2e_index", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


PROTO_DEFAULT = "http://127.0.0.1:4173"


class SnapshotError(RuntimeError):
    """用例真相源读不出来（列头与契约不一致等）——必须上报，不得静默降级为空列表。"""


def load_generator(root: Path):
    """复用生成器的 profile 解析器（同一份格式解析，不另写）。"""
    spec = importlib.util.spec_from_file_location(
        "atlas_gen_e2e_scripts", root / ".atlas" / "scripts" / "gen_e2e_scripts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def read_manual(root: Path) -> list[dict]:
    """手工走查项（product/e2e/manual.md，用户 2026-10-01 设计）：控制台「手工」类型承载。

    每行 `- <ID> | <页面> | <标题> | <操作说明>`；执行 = 开浏览器到对应页面，其余人工。
    文件缺失 = 空清单（手工面是可选增强，不阻塞任何项目）。
    """
    path = root / "product" / "e2e" / "manual.md"
    if not path.is_file():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s.startswith("- "):
            continue
        parts = [x.strip() for x in s[2:].split("|")]
        if len(parts) >= 4:
            items.append({"id": parts[0], "page": parts[1], "title": parts[2],
                          "note": " | ".join(parts[3:])})
    return items


def page_routes(root: Path) -> dict:
    """页面表（页 ↔ 路由唯一真相源）解析：供手工项「打开」跳转。"""
    path = root / "product" / "e2e" / "e2e-index.md"
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


def read_sources(root: Path) -> dict:
    """唯一来源（靶场，E1 单段）与它的 baseURL。地址的唯一来源是 stack-profile.yaml。"""
    profile = root / "product" / "stack-profile.yaml"
    prof = load_generator(root).parse_profile(profile.read_text(encoding="utf-8"))
    app = (prof.get("e2e") or {}).get("app_base_url")
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
    e2e = root / "product" / "e2e"
    index = e2e / "e2e-index.md"
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
            "先对齐 product/e2e/e2e-index.md；改过契约 / 校验器后必须重启本控制台。")
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
        })
    return {"cases": cases, "nodeids": node_ids(e2e / "scripts")}


def node_ids(scripts_dir: Path) -> dict:
    """用例 ID → pytest node id（从生成脚本里读，不猜函数名）。"""
    out: dict[str, str] = {}
    if not scripts_dir.is_dir():
        return out
    for py in sorted(scripts_dir.glob("*.py")):
        if py.name == "conftest.py":
            continue
        text = py.read_text(encoding="utf-8")
        for m in re.finditer(r"def (\w+)\(page\):", text):
            hit = re.search(r"(E2E-[A-Z0-9]+-\d{3})", text[m.end():m.end() + 400])
            if hit:
                out[hit.group(1)] = f"{py.name}::{m.group(1)}"
    return out


# ---------------------------------------------------------------- 账本（append-only 唯一真相源）

class Ledger:
    def __init__(self, root: Path, actor: str):
        self.dir = root / "product" / "e2e" / "reviews" / "console"
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
            lines += [
                f"- 最近提交：**{last.get('ts', '')}** · {last.get('actor', '')}"
                f"（快照 {len(snap)} 条 · 执行通过 {sum(1 for v in snap.values() if v.get('ok'))}"
                f" · 已评审 {sum(1 for v in snap.values() if (v.get('reviewed') or {}).get('pass'))}）",
            ]
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


# ---------------------------------------------------------------- 执行器（并发=1）

class Runner:
    def __init__(self, root: Path, ledger: Ledger, timeout: int, head: bool, keep_open: bool = True):
        self.root = root
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

    def python(self) -> str:
        venv = self.root / ".venv" / "bin" / "python"
        return str(venv) if venv.is_file() else sys.executable

    def start(self, case: dict, nodeid: str, slowmo: int, source: str, base_url: str) -> tuple[bool, str]:
        with self.cond:
            if self.running:
                return False, f"已有用例在跑（{self.case}）——本控制台并发=1"
            self._proc_alive_kill()   # 跑下一条前，先关掉上一条保留的窗口
            self.running = True
            self.case = case["id"]
            self.lines = []
            self.done = None
        threading.Thread(target=self._run, args=(case, nodeid, slowmo, source, base_url), daemon=True).start()
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

    def _run(self, case: dict, nodeid: str, slowmo: int, source: str, base_url: str) -> None:
        scripts = self.root / "product" / "e2e" / "scripts"
        cmd = [self.python(), "-m", "pytest", "-q", "--slowmo", str(slowmo),
               "--browser-channel", "chrome", nodeid]
        if self.head:
            cmd.insert(3, "--headed")
        self._emit(f"# 来源 {source} → ATLAS_BASE_URL={base_url}\n$ cd {scripts}\n$ {' '.join(cmd)}\n")
        t0 = time.time()
        timed_out = False
        held = False
        exit_code = -1
        # 结果哨兵：持窗模式下进程会活过用例结束，所以不能靠「进程退出」判结果。
        # 注意：mkstemp 会**先建一个空文件**，必须删掉它—— 否则 is_file() 一开始就为真。
        _fd, _spath = tempfile.mkstemp(prefix="atlas-e2e-result-", suffix=".json")
        os.close(_fd)
        sentinel = Path(_spath)
        sentinel.unlink()
        env = {**os.environ, "ATLAS_BASE_URL": base_url}
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


def _compact(entry: dict) -> dict:
    """落账本的快照条目：失败才带输出尾部（80 行，与运行期同长），避免账本被 traceback 撑爆。"""
    out = {"ok": bool(entry.get("ok")), "exit": entry.get("exit"),
           "duration_ms": entry.get("duration_ms"), "timeout": bool(entry.get("timeout")),
           "ts": entry.get("ts")}
    reviewed = entry.get("reviewed") or {}
    if reviewed:
        out["reviewed"] = {"pass": bool(reviewed.get("pass")),
                           "checked_at": reviewed.get("checked_at"),
                           "unchecked_at": reviewed.get("unchecked_at")}
    if not out["ok"] and entry.get("tail"):
        out["tail"] = "\n".join(str(entry["tail"]).splitlines()[-80:])
    return out


def writeback(root: Path, draft: dict, apply: bool, source: str = "app") -> dict:
    """按页面草稿（执行结果 + 评审态）算索引改动；apply=True 才落盘。

    只改一列：`状态`（契约 §5.4 E1 单段：通过 → `green`，失败 → `red`）。
    """
    index = root / "product" / "e2e" / "e2e-index.md"
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
        self.port = port
        self.slowmo = slowmo
        self.actor = f"{os.environ.get('USER', 'local')}·控制台"
        self.ledger = Ledger(root, self.actor)
        self.runner = Runner(root, self.ledger, timeout, head, keep_open)

    def cases_payload(self, source: str) -> dict:
        try:
            snap = snapshot(self.root)
        except SnapshotError as exc:
            return {"source": source, "sources": read_sources(self.root), "problem": str(exc),
                    "slowmo": self.slowmo, "timeout": self.runner.timeout, "head": self.runner.head,
                    "ledger": "product/e2e/reviews/console/events.jsonl", "cases": [], "nodeids": {},
                    "committed": {"ts": None, "actor": None, "cases": {}}}
        last = self.ledger.last_submit(source) or {}
        return {
            "source": source,
            "sources": read_sources(self.root),
            "root": str(self.root),
            "slowmo": self.slowmo,
            "timeout": self.runner.timeout,
            "head": self.runner.head,
            "keep_open": self.runner.keep_open,
            "held_case": self.runner.held_case,
            "ledger": "product/e2e/reviews/console/events.jsonl",
            "cases": snap["cases"],
            "manual": read_manual(self.root),
            "nodeids": snap["nodeids"],
            # 已提交的快照（页面草稿覆盖它；草稿在浏览器本地，见 docstring 的「乙」）
            "committed": {"ts": last.get("ts"), "actor": last.get("actor"), "cases": last.get("cases", {})},
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
        url = (read_sources(self.app.root).get("app", {}).get("base_url") or "").rstrip("/") + route
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
        res = writeback(self.app.root, draft, apply, source)
        if apply:
            snap = {cid: _compact(v) for cid, v in draft.items()}
            self.app.ledger.append({"kind": "submit", "source": source,
                                    "changed": res["changed"], "cases": snap})
            res["committed_ts"] = self.app.ledger.last_submit(source).get("ts")
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
