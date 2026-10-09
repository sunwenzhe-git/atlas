#!/usr/bin/env python3
"""atlas 统一检查入口 —— 把「每批收尾要串 6 条命令」收成一条（3509 §B68）。

**只聚合，不改判据**：本脚本逐项**调用**既有校验器 / 生成器 / 测试，一门一行摘要；
判据本身仍在各处实现（它们刚证明过自己会咬，不做二次实现，也不放宽）。

    一门一行：`ok|FAIL|WARN|SKIP  <名称>  <一句摘要>`

**行的语义（`3509 §B110`）**：`SKIP` = 「未走到这一步 / 前置未声明」，**不是通过、也不是失败**，
必须带原因；`生成物最新` 三态 = 未就绪(SKIP) ≠ 生成物过期(WARN) ≠ 生成失败(FAIL)。

用法：
    python3 .atlas/scripts/atlas_check.py [--root .] [--page <slug>] [--fast] [--json]

  * 默认跑：4 个校验器 → 出厂测试 → 生成物是否最新（干跑） →（有 --page 或六页全量）真跑
  * `--page voices`：只真跑该页（E1 单段：真实应用由业务侧拉起，本器不起任何服务）
  * `--fast`：跳过出厂测试与真跑（只跑校验器 + 生成物）
  * 任一 FAIL ⇒ 退出码 1；WARN 不影响退出码。
  * 真跑前按**依赖可用性**选解释器（候选须能导入运行器依赖，否则降级；全不可用 ⇒ 真跑 FAIL 并列原因）

- 框架无关：本文件不得出现任何具体框架名。纯标准库。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

VALIDATORS = (
    "validate_stack_profile",
    "validate_structure",
    "validate_e2e_index",
    "validate_testids",
    "validate_prd",
    "validate_ledger",
    "validate_design_exemptions",
)  # E1：validate_prototype 随原型环退役；§B120：stack_profile / structure 纳入（三态前置见 _GATE_PRECONDITIONS）；#182：design_exemptions 纳入（同款三态前置）

# §B120：三态前置 —— 前置未声明 ⇒ SKIP（不是通过，且必须带原因）；标记存在才真正跑。
_GATE_PRECONDITIONS = {
    # 项目未接 atlas（无 stack-profile）/ atlas 自身设计场景（工作区无 product/）⇒ 未走到这一步
    "validate_stack_profile": (
        "product/stack-profile.yaml",
        "前置未声明（未就绪，非失败）：无 product/stack-profile.yaml（项目未接 atlas）"),
    # 结构环未跑 ⇒ 结构事实区未生成
    "validate_structure": (
        ".trellis/spec/structure/_meta.json",
        "前置未声明（未就绪，非失败）：结构环未跑（无 .trellis/spec/structure/_meta.json）"),
    # 设计档案未建（frontend-design skill 首次判读时才落盘）⇒ 未走到这一步（#182）
    "validate_design_exemptions": (
        "product/design.md",
        "前置未声明（未就绪，非失败）：无 product/design.md（设计档案未建）"),
}

GEN_NOT_READY = 3

# E2E 生成物运行器所需的解释器级依赖：候选解释器必须能**导入**它们才算可用。
# 判据是「可导入性」而非「路径存在」——框架名只在这里作为探测目标出现。


class Row:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.rows.append({"name": name, "status": status, "detail": detail})

    @property
    def failed(self) -> bool:
        return any(r["status"] == "FAIL" for r in self.rows)


def run(cmd: list[str] | str, cwd: Path, timeout: int = 1800, shell: bool = False) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout, shell=shell)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"
    except FileNotFoundError as e:
        return 127, str(e)


def _url_reachable(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """靶场地址是否可连（纯标准库；只回答「栈起没起」，不回答「页面对不对」）。

    判据 = **TCP 可连**即算就绪：任何 HTTP 状态码（含 4xx/5xx）都说明服务在跑，
    页面内容是否正确由用例自己断言。地址不可解析 ⇒ 不可达（带原因）。
    """
    m = re.match(r"(https?)://([^/:\s]+)(?::(\d+))?", url.strip().strip("'\""))
    if not m:
        return False, f"地址不可解析为 http(s)://host[:port]（{url!r}）"
    host = m.group(2)
    port = int(m.group(3) or (443 if m.group(1) == "https" else 80))
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except OSError as exc:
        return False, f"{host}:{port} 连接失败（{type(exc).__name__}）"


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def check_validators(root: Path, rows: Row, py: str) -> None:
    for v in VALIDATORS:
        script = root / ".atlas" / "validators" / f"{v}.py"
        if not script.is_file():
            rows.add(v, "SKIP", "校验器不存在")
            continue
        pre = _GATE_PRECONDITIONS.get(v)
        if pre is not None and not (root / pre[0]).exists():
            rows.add(v, "SKIP", pre[1])
            continue
        code, out = run([py, str(script), "--root", "."], root)
        last = [l.strip() for l in out.strip().splitlines() if l.strip()]
        status = "ok" if code == 0 else "FAIL"
        tail = last[-1] if last else ""
        detail = ""
        if code != 0:
            bad = [l for l in last if "[FAIL]" in l or "[WARN]" in l]
            detail = (bad[0] if bad else tail)[:160]
        elif any("[WARN]" in l for l in last):
            # WARN = 提示补不置红（退出码 0），但门总览必须可见，不得静默当 ok
            status = "WARN"
            detail = next((l for l in last if "[WARN]" in l), tail)[:160]
        rows.add(v, status, detail or tail)


def check_factory(root: Path, rows: Row, py: str) -> None:
    code, out = run([py, "-m", "pytest", ".atlas/tests", "-q", "--no-header"], root, timeout=900)
    m = re.findall(r"(\d+) (passed|failed)", out)
    summary = " ".join(f"{n} {k}" for n, k in m) or out.strip().splitlines()[-1:][0] if out.strip() else ""
    rows.add("对齐测试(.atlas/tests)", "ok" if code == 0 else "FAIL", summary[:160])


def check_generated(root: Path, rows: Row, py: str) -> None:
    gen = root / ".atlas" / "scripts" / "gen_e2e_scripts.py"
    if not gen.is_file():
        rows.add("生成物最新", "SKIP", "生成器不存在")
        return
    code, out = run([py, str(gen), "--root", ".", "--json"], root)
    if code == GEN_NOT_READY:
        # 前置未声明（例：e2e.app_base_url 为空）= **未就绪**，不是失败：显式可见跳过 + 说清怎么变成可跑。
        # 三态语义（`3509 §B110`）：未就绪(SKIP) ≠ 生成物过期(WARN) ≠ 生成失败(FAIL)。
        # `run()` 把 stdout+stderr 拼在一起 ⇒ 先直解 JSON，不成再从拼接文本里抽 JSON 块（stderr 无花括号）。
        why = ""
        for blob in (out, (re.search(r"\{.*\}", out, re.S).group(0) if re.search(r"\{.*\}", out, re.S) else "")):
            if not blob:
                continue
            try:
                why = str(json.loads(blob).get("message", ""))
                break
            except Exception:
                continue
        if not why:
            why = out.strip().splitlines()[-1][:160] if out.strip() else ""
        rows.add("生成物最新", "SKIP", f"前置未声明（未就绪，非失败）：{why[:150]}")
        return
    if code != 0:
        rows.add("生成物最新", "FAIL", out.strip().splitlines()[-1][:160] if out.strip() else "")
        return
    try:
        info = json.loads(out)
    except Exception:
        rows.add("生成物最新", "WARN", "生成器输出非 JSON")
        return
    stale = [r["file"] for r in info.get("results", []) if r.get("changed")]
    if stale:
        rows.add("生成物最新", "WARN", "%d 个产物待重跑 gen_e2e_scripts.py --apply（例：%s）"
                 % (len(stale), Path(stale[0]).name))
    else:
        rows.add("生成物最新", "ok", "%d 个页面脚本与索引反向视图均已最新" % info.get("generated", 0))


def check_drift(root: Path, rows: Row) -> None:
    """「结构漂移」门（gates.md §2.2，2026-10-04 登记）：只读 refresh_structure 落的
    漂移标记，**不做二次判定**。标记 = 最近一次 --apply 刷新发现的事实表键级增删
    （源码结构变更未经 apply 登记的信号）；登记语义归收口对账人终审 ⇒ WARN 不置红。
    """
    out_dir = root / ".trellis" / "spec" / "structure" / ".adapter-out"
    marker = out_dir / "_drift.json"
    if not out_dir.is_dir():
        rows.add("结构漂移", "SKIP", "结构环未跑（无 .adapter-out 产物目录）")
        return
    if not marker.is_file():
        rows.add("结构漂移", "ok", "最近一次事实刷新无键级增删")
        return
    try:
        d = json.loads(marker.read_text(encoding="utf-8"))
        drifts = d.get("drifts") or []
    except (OSError, json.JSONDecodeError):
        rows.add("结构漂移", "WARN", "漂移标记不可解析（.adapter-out/_drift.json）")
        return
    if not drifts:
        rows.add("结构漂移", "ok", "漂移标记为空")
        return
    parts = []
    for x in drifts[:3]:
        add = (x.get("added") or ["—"])[:2]
        rem = (x.get("removed") or ["—"])[:2]
        parts.append(f"{x.get('kind', '?')} +{add} -{rem}")
    more = "" if len(drifts) <= 3 else f"（共 {len(drifts)} 处）"
    rows.add("结构漂移", "WARN",
             f"最近一次事实刷新检测到未登记键级变更（.adapter-out/_drift.json）：{'；'.join(parts)}{more}")


def check_version(root: Path, rows: Row) -> None:
    """「装配版本」对账（gates.md §2.2，P3；2026-10-05）：.atlas/VERSION 记装配时的
    源包内容摘要，与当前源包重算摘要比对——不一致 ⇒ WARN（源包已前进/落后于装配态，
    重跑 install.sh 前先回灌对账）。漂移是常态信号非门禁失败 ⇒ WARN 不置红
    （check_drift 同款语义）。算法单点 = scripts/pkg_digest.py（两侧同文件，防双端漂移）。
    """
    version_file = root / ".atlas" / "VERSION"
    if not version_file.is_file():
        rows.add("装配版本", "SKIP", "无 .atlas/VERSION（旧装配；install.sh ≥ 2026-10-05 起落戳）")
        return
    lines = [l.strip() for l in version_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(lines) < 3:
        rows.add("装配版本", "WARN", ".atlas/VERSION 形态非法（应为 摘要/时间/源包路径 三行）")
        return
    stamped, _when, source = lines[0], lines[1], lines[2]
    source_dir = Path(source)
    if not source_dir.is_dir():
        rows.add("装配版本", "SKIP", f"源包路径不可达（{source}）——搬家后未更新 VERSION")
        return
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from pkg_digest import digest  # noqa: E402  延迟导入：旧装配无此文件时走 SKIP
    except ImportError:
        rows.add("装配版本", "SKIP", "无 scripts/pkg_digest.py（旧装配）——重跑 install.sh 补齐")
        return
    try:
        current = digest(source_dir)
    except (OSError, ValueError) as e:
        rows.add("装配版本", "SKIP", f"源包摘要计算失败（{e}）")
        return
    if current == stamped:
        rows.add("装配版本", "ok", f"源包与装配态一致（{stamped}）")
        return
    rows.add("装配版本", "WARN",
             f"源包已前进/落后于装配态（装配 {stamped} → 当前 {current}）——重跑 install.sh 前先回灌对账（ATLAS-UPSTREAM）")


def check_e2e(root: Path, rows: Row, page: str | None) -> None:
    prof = root / "product" / "stack-profile.yaml"
    text = prof.read_text(encoding="utf-8") if prof.is_file() else ""
    # 值抽取正则只用 `[^\S\n]`（同行空白），不得用 `\s`——`\s` 会跨行匹配，把下一行的
    # 键名当成值（2026-10-04 门禁负向用例 #2：`app_base_url:` 空值后跟 `reset:` ⇒ 被误读成已声明）。
    m = re.search(r"^[^\S\n]*cases_dir:[^\S\n]*(\S+)", text, re.M)
    scripts = root / "product" / "e2e" / "scripts"
    if not scripts.is_dir():
        rows.add("E2E 真跑", "SKIP", "无脚本目录（门控态）")
        return
    # 页面脚本扩展名（单轨 node-playwright，3507 BO 单轨化）
    _ext = ".spec.ts"
    target = scripts if not page else scripts / f"{page}{_ext}"
    if page and not Path(target).is_file():
        rows.add("E2E 真跑", "SKIP", f"无 {page}{_ext}（{m.group(1) if m else 'cases_dir'} 未建？）")
        return
    # E1 单段：真实栈由业务侧拉起，atlas_check 不再起原型静态服务。
    mbase = re.search(r"^[^\S\n]*app_base_url:[^\S\n]*(\S+)", text, re.M)
    if not mbase or mbase.group(1) in ("null", "~", '""', "''"):
        rows.add("E2E 真跑", "SKIP",
                 "e2e.app_base_url 为空（单段执行：真实栈地址未声明；业务侧拉起后重跑）")
        return
    # 地址已声明但**靶场不可达** ⇒ 同为「未就绪」，不是失败（`gates.md` 2.2 本行的「不查什么」
    # = 真栈没起来时的任何结论，那时只报 SKIP）：少这一步就会把整批 `goto` 失败记成 FAIL
    # （2026-10-04 实测 79 failed 全因前端未起），真红与假红不可区分 ⇒ 狼来了效应（`3509 §B189-1`）。
    _ok, _why = _url_reachable(mbase.group(1))
    if not _ok:
        rows.add("E2E 真跑", "SKIP",
                 f"ENV_ISSUE：e2e.app_base_url 不可达（{mbase.group(1)}；{_why}）"
                 "——真实栈未就绪，非用例失败")
        return
    # 靶场重置（2026-09-30，台账 P4）：零步基线与用例前提假设种子初始态，真栈持久化
    # 跨 run 残留 ⇒ 声明了 `e2e.reset`（shell 命令串）就在真跑前执行；非零 ⇒ FAIL
    # （重置失败时继续跑 = 带着脏状态跑，结论不可信）。
    mreset = re.search(r"^[^\S\n]*reset:[^\S\n]*(\S.*\S)[^\S\n]*$", text, re.M)
    if mreset and mreset.group(1) not in ("null", "~"):
        reset_cmd = mreset.group(1).strip("\"'")
        code_r, out_r = run(reset_cmd, root, timeout=300, shell=True)
        if code_r != 0:
            rows.add("E2E 真跑" + (f"[{page}]" if page else "（六页）"), "FAIL",
                     f"e2e.reset 失败（exit {code_r}）：{out_r.strip()[-200:]}")
            return
    # node 单轨（3507 BO）：探测项目声明位置（e2e.node_modules）的 playwright
    # 可执行文件，经 NODE_PATH 解析生成物里的 @playwright/test；
    # 未找到 ⇒ FAIL 列原因（不静默降级）。
    nm = re.search(r"^[^\S\n]*node_modules:[^\S\n]*(\S+)", text, re.M)
    nm_dir = Path(nm.group(1)) if nm else None
    pw_bin = (nm_dir / ".bin" / "playwright") if nm_dir else None
    if not pw_bin or not pw_bin.is_file():
        rows.add("E2E 真跑", "FAIL",
                 f"node-playwright 可执行文件不存在：{pw_bin}（stack-profile e2e.node_modules）")
        return
    spec_arg = f"{page}.spec.ts" if page else ""
    cmd = (f"NODE_PATH={nm_dir} {pw_bin} test -c "
           f"{scripts.relative_to(root) / 'playwright.config.ts'} {spec_arg}".strip())
    code, out = run(cmd, root, timeout=1800, shell=True)
    m2 = re.findall(r"(\d+) (passed|failed|error)", out)
    summary = " ".join(f"{n} {k}" for n, k in m2) or "无结果"
    rows.add("E2E 真跑" + (f"[{page}]" if page else "（六页）"),
             "ok" if code == 0 else "FAIL", summary)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--page", default=None)
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    rows = Row()
    check_validators(root, rows, sys.executable)
    if not args.fast:
        check_factory(root, rows, sys.executable)
    check_generated(root, rows, sys.executable)
    check_drift(root, rows)
    check_version(root, rows)
    if not args.fast:
        check_e2e(root, rows, args.page)
    if args.json:
        print(json.dumps({"root": str(root), "ok": not rows.failed,
                          "rows": rows.rows}, ensure_ascii=False, indent=2))
    else:
        print(f"atlas check @ {root}")
        for r in rows.rows:
            line = f"  {r['status']:<4} {r['name']:<26}"
            if r["detail"]:
                line += " " + r["detail"]
            print(line)
        print("FAIL" if rows.failed else "OK")
    return 1 if rows.failed else 0


if __name__ == "__main__":
    sys.exit(main())
