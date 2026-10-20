#!/usr/bin/env python3
"""atlas 统一检查入口 —— 把「每批收尾要串 6 条命令」收成一条（3509 §B68）。

**只聚合，不改判据**：本脚本逐项**调用**既有校验器 / 生成器 / 测试，一门一行摘要；
判据本身仍在各处实现（它们刚证明过自己会咬，不做二次实现，也不放宽）。

    一门一行：`ok|FAIL|WARN|SKIP  <名称>  <一句摘要>`

**行的语义（`3509 §B110`）**：`SKIP` = 「未走到这一步 / 前置未声明」，**不是通过、也不是失败**，
必须带原因；`生成物最新` 三态 = 未就绪(SKIP) ≠ 生成物过期(WARN) ≠ 生成失败(FAIL)。

用法：
    python3 .atlas/scripts/atlas_check.py [--root .] [--page <slug>] [--fast] [--json]

  * 默认跑：全部校验器（`VALIDATORS` 全量；数量钉在 `gates.md`，见 `test_canonical_consistency` 判据⑥） → 出厂测试 → 生成物是否最新（干跑） →（有 --page 或六页全量）真跑
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

# 随包内核引导（`_support/`，2026-10-12 单源批）：共享实现一律经本引导取用，不就地复制。
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _support.siblings import load_module  # noqa: E402

# node 运行器单源内核（二进制解析 / **可解析性判据** / 全局兜底修复；issue #24，`DESIGN.md` D101）。
# 本文件此前与 `scripts/e2e_console.py` 各存一份解析实现（含 `_is_node_playwright` 两份拷贝）。
pw_runner = load_module("pw_runner")

# 行内 `#` 注释剥除单源（`_support/stack_profile.strip_inline_comment`；D94 口径）。本门四处
# 标量取值曾不过剥注释 ⇒ `reset: null   # 真跑前…` 整段被当成命令执行（2026-10-17 现场
# 百炼/v2前端：`e2e.reset 失败（exit 127）：/bin/sh: null: command not found`——**假红，且在
# 跑到用例之前**）。D94 ③ 把这批「其余文本期门」登记为残余，本处是其中一处的现场实证。
strip_inline_comment = load_module("stack_profile").strip_inline_comment

VALIDATORS = (
    "validate_stack_profile",
    "validate_structure",
    "validate_e2e_index",
    "validate_testids",
    "validate_e2e_mocks",
    "validate_ac_alignment",
    "validate_prd",
    "validate_design_exemptions",
    "validate_adr",
)  # E1：validate_prototype 随原型环退役；§B120：stack_profile / structure 纳入；#182：design_exemptions 纳入；§5.8：e2e_mocks 纳入；B209-1（3507 BT）：validate_ac_alignment 纳入；2026-10-13：validate_adr 纳入（架构决策资产门）；2026-10-14：validate_ledger 随知识库/台账子系统退役（AC 号唯一判据归位 validate_prd）

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
    # E2E 用例资产未建 ⇒ 打桩门无输入面（§5.8，2026-10-12）
    "validate_e2e_mocks": (
        "product/e2e/e2e-index.md",
        "前置未声明（未就绪，非失败）：E2E 用例资产未建（无 product/e2e/e2e-index.md）"),
    # PRD 资产未建 ⇒ AC 对账门无输入面（B209-1，2026-10-12）
    "validate_ac_alignment": (
        "product/prd/prd.md",
        "前置未声明（未就绪，非失败）：PRD 资产未建（无 product/prd/prd.md）"),
    # 架构决策资产未建 ⇒ 未走到这一步（2026-10-13）
    "validate_adr": (
        "product/adr",
        "前置未声明（未就绪，非失败）：无 product/adr/（尚未创建任何 ADR）"),
}

GEN_NOT_READY = 3

# 空装配摘要（= sha256('')[:16]）。旧安装器在 npm 全局安装路径下每个文件都被过滤掉，
# 落的就是这个值；两侧同错 ⇒ 本门曾恒等恒 ok。识别它是为了给**根因级**指引（重装），
# 而不是混进「源包已前进/落后」那条对账文案（F37，2026-10-15）。
EMPTY_DIGEST = "e3b0c44298fc1c14"

# E2E 生成物运行器所需的解释器级依赖：候选解释器必须能**导入**它们才算可用。
# 判据是「可导入性」而非「路径存在」——框架名只在这里作为探测目标出现。


class Row:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.failures: list[dict] = []

    def add(self, name: str, status: str, detail: str = "",
            command: str = "", full_output: str = "", code: int | None = None) -> None:
        self.rows.append({"name": name, "status": status, "detail": detail})
        if status == "FAIL":
            self.failures.append({
                "name": name,
                "detail": detail,
                "command": command,
                "code": code,
                "output": full_output,
            })

    @property
    def failed(self) -> bool:
        return any(r["status"] == "FAIL" for r in self.rows)


def _reset_command(raw: str) -> str:
    """`e2e.reset` 的取值清洗：先剥行内注释，再只剥**成对**引号（D94 ③ 残余清偿 / MB9）。

    **调用点与钉必须走同一函数**：否则把调用点改回 `.strip("\"\'")` 时钉照样绿（本轮实测踩到）。
    """
    return _strip_matching_quotes(strip_inline_comment(raw))


def _strip_matching_quotes(v: str) -> str:
    """去掉**成对**的包裹引号（YAML 标量的引号是语法，不是值的一部分）。

    此前用 `.strip("\"\'")` —— 它从**两端**剥掉集合内任意字符：`sh -c 'echo x'` 这类
    **结尾本身带引号**的合法发令会被吃掉最后一个字符（未报错、静默改义）。
    """
    s = v.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


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
            detail = "; ".join(bad) if bad else tail
            rows.add(v, status, detail or tail,
                     command=f"{py} {script} --root .", full_output=out, code=code)
        elif any("[WARN]" in l for l in last):
            # WARN = 提示补不置红（退出码 0），但门总览必须可见，不得静默当 ok
            status = "WARN"
            bad = [l for l in last if "[WARN]" in l]
            detail = "; ".join(bad) if bad else tail
            rows.add(v, status, detail or tail)
        else:
            rows.add(v, status, tail)


def check_factory(root: Path, rows: Row, py: str) -> None:
    tests = root / ".atlas" / "tests"
    if not tests.is_dir():
        # F53（2026-10-16，issue #17 残余；RFC-20261016-02 D91）：目录不在场 = 包装配没有可跑对象
        # = 「未走到这一步」，不是测试失败 —— 三态先例：`_GATE_PRECONDITIONS` / `GEN_NOT_READY`。
        # 触发面：存量装配（npm 旧发行版不发布 tests/ ⇒ install.sh 拷贝空操作）、源包开发态
        #（仓根本无 .atlas/）、装配损坏（路径被文件占用，is_dir 同样不成立）。否则 pytest 收集
        # 失败 exit 4 ⇒ 恒红，而 --fast 一跑就 OK —— 两相反结论并存，红被训练成噪声。
        # 文案两层（评审 M-1/m-2/m-3）：判据面（连实测路径；「或不是目录」覆盖文件形态，
        # 不对在场者谎称「未找到」）+ 出路（可执行的动作词）。
        rows.add("对齐测试(.atlas/tests)", "SKIP",
                 f"前置未声明（未就绪，非失败）：{tests} 不存在或不是目录 —— "
                 "装配集不含包出厂测试目录（旧发行版装配态 / 源包开发态 / 装配损坏）。"
                 "包自检在源包跑（pytest tests）；项目侧跑齐 = 重装取新发行版装配"
                 "（install.sh / atlas upgrade，需解释器可跑 pytest）")
        return
    code, out = run([py, "-m", "pytest", ".atlas/tests", "-q", "--no-header"], root, timeout=900)
    m = re.findall(r"(\d+) (passed|failed)", out)
    summary = " ".join(f"{n} {k}" for n, k in m) or out.strip().splitlines()[-1:][0] if out.strip() else ""
    rows.add("对齐测试(.atlas/tests)", "ok" if code == 0 else "FAIL", summary[:160],
             command=f"{py} -m pytest .atlas/tests -q --no-header", full_output=out, code=code)


def check_serial_execution(root: Path, rows: Row) -> None:
    """「执行串行」门（契约 §7.1，`DESIGN.md` D115，2026-10-19）。

    生成的运行器配置**必须** `workers: 1` + `fullyParallel: false`：靶场是共享有状态环境，
    同域用例必须按序串行（零步基线先于改态用例）；并行调度会打乱定义序 ⇒ 恒真误报 / 前提被前序污染。
    手改配置或封装运行方式注入并行 ⇒ **FAIL**（正确性纪律，不是「过期」的新鲜度问题 ⇒ 不降 WARN）。
    """
    cfg = root / "product" / "e2e" / "scripts" / "playwright.config.ts"
    if not cfg.is_file():
        rows.add("执行串行", "SKIP", "无 product/e2e/scripts/playwright.config.ts（E2E 资产未建）")
        return
    text = cfg.read_text(encoding="utf-8", errors="ignore")
    missing = []
    if not re.search(r"\bworkers\s*:\s*1\b", text):
        missing.append("workers: 1")
    if not re.search(r"\bfullyParallel\s*:\s*false\b", text):
        missing.append("fullyParallel: false")
    if missing:
        rows.add("执行串行", "FAIL",
                 "运行器配置未串行：缺 " + " / ".join(missing) +
                 "（契约 §7.1：同域用例必须按序串行；共享有状态靶场并行会污染前提）")
    else:
        rows.add("执行串行", "ok", "workers: 1 + fullyParallel: false")


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
        rows.add("生成物最新", "FAIL", out.strip().splitlines()[-1][:160] if out.strip() else "",
                 command=f"{py} {gen} --root . --json", full_output=out, code=code)
        return
    info = None
    for blob in (out, (re.search(r"\{.*\}", out, re.S).group(0) if re.search(r"\{.*\}", out, re.S) else "")):
        if not blob:
            continue
        try:
            info = json.loads(blob)
            if isinstance(info, dict):
                break
        except Exception:
            continue
    if info is None or not isinstance(info, dict):
        rows.add("生成物最新", "WARN", "生成器输出非 JSON")
        return
    stale = [r["file"] for r in info.get("results", []) if r.get("changed")]
    if stale:
        rows.add("生成物最新", "WARN", "%d 个产物待重跑 gen_e2e_scripts.py --apply（例：%s）"
                 % (len(stale), Path(stale[0]).name))
    elif "基线报告兜底中" in out:
        rows.add("生成物最新", "WARN", "独立审查未执行（基线报告兜底中；跑 gen_e2e_scripts.py --bootstrap-review）")
    else:
        rows.add("生成物最新", "ok", "%d 个页面脚本与索引反向视图均已最新" % info.get("generated", 0))


def check_review_report(root: Path, rows: Row) -> None:
    """「审查报告形态」常驻巡检门（gates.md §2.2；F21，2026-10-15）。
    调 `validate_review_report.validate_report()` 对最新 E2E 审查报告进行形态与状态复算：
    - 缺报告 / 未开户：SKIP
    - 基线兜底报告（N/0）：WARN 随行披露（诚实降级，揭发未审状态）
    - 形态门通过：ok
    - 形态门失败（如手写假桩缺字段、映射自相矛盾）：FAIL 揭发伪造证据
    """
    reviews_dir = root / "product" / "e2e" / "reviews"
    if not reviews_dir.is_dir():
        rows.add("审查报告形态", "SKIP", "无 product/e2e/reviews 目录")
        return
    review_re = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)$")
    candidates = [p for p in reviews_dir.iterdir() if p.is_dir() and review_re.match(p.name)]
    if not candidates:
        rows.add("审查报告形态", "SKIP", "无符合命名规范的审查报告目录")
        return
    candidates.sort(key=lambda p: p.name)
    latest = candidates[-1]

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from validate_review_report import validate_report  # noqa: E402
    except ImportError:
        rows.add("审查报告形态", "SKIP", "无 scripts/validate_review_report.py")
        return

    res = validate_report(latest)
    if res.status == "FAIL":
        fails = [c["check"] for c in res.checks if c.get("level") == "FAIL"]
        rows.add("审查报告形态", "FAIL", f"{latest.name} 形态不合规（例：{fails[:2]}）")
    elif res.status == "WARN":
        rows.add("审查报告形态", "WARN", f"{latest.name} 处于未审基线或含警告（状态={res.status}）")
    else:
        rows.add("审查报告形态", "ok", f"{latest.name} 形态合规且状态一致")


def check_drift(root: Path, rows: Row) -> None:
    """「结构漂移」门（gates.md §2.2，2026-10-04 登记）：只读 refresh_structure 落的
    漂移标记，**不做二次判定**。标记 = 最近一次 --apply 刷新发现的事实表键级增删
    （源码结构变更未经 apply 登记的信号）；登记语义归收口对账人终审 ⇒ WARN 不置红。

    基准 = **项目根** `.adapter-out/`（2026-10-15 统一，issue #8）。此前本门读
    `.trellis/spec/structure/.adapter-out/`，而图谱层写项目根 ⇒ 同名两处，现场出现
    「`git status` 里有 `.adapter-out/`，本门却说『无 .adapter-out 产物目录』」的矛盾
    （排查者会先怀疑门坏）。统一后 SKIP 文案**带上实际路径**，这类「SKIP 与现场不一致」
    一眼能看出问的是哪条路径。
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from refresh_structure import adapter_out_dir  # noqa: E402  单源：落点只此一处
    except ImportError:
        adapter_out_dir = lambda r: r / ".adapter-out"  # noqa: E731  旧装配缺该模块时的退路
    out_dir = adapter_out_dir(root)
    marker = out_dir / "_drift.json"
    if not out_dir.is_dir():
        rows.add("结构漂移", "SKIP", f"结构环未跑（未找到 {out_dir}）")
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

    F37（2026-10-15）：历史坏戳 `e3b0c44298fc1c14`（= `sha256('')[:16]`）单列一条
    **根因级** WARN，不走「源包已前进/落后」——那条会把人引向对账，而真正该做的是
    重装。坏戳由旧安装器产出：旧 `digest()` 拿**绝对** parts 判 `SKIP_DIRS`，npm 全局
    安装的源包位于 `<prefix>/lib/node_modules/<pkg>` ⇒ 每个文件都被滤掉 ⇒ 空摘要落戳，
    而副本侧同错重算 ⇒ 两侧恒等 ⇒ 本门恒 ok。修后 `digest()` 对空装配直接抛
    `EmptyAssembly`，故该哨兵只可能对应「修复前落的戳」。
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
    if stamped == EMPTY_DIGEST:
        rows.add("装配版本", "WARN",
                 "历史坏戳（旧安装器把空装配当成合法摘要：摘要 == sha256('')[:16]）"
                 "——重跑 install.sh 重新落戳；此戳不承载任何内容信息，本门此前恒 ok")
        return
    source_dir = Path(source)
    if not source_dir.is_dir():
        rows.add("装配版本", "SKIP", f"源包路径不可达（{source}）——搬家后未更新 VERSION")
        return
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from pkg_digest import EmptyAssembly, digest  # noqa: E402  延迟导入：旧装配无此文件时走 SKIP
    except ImportError:
        rows.add("装配版本", "SKIP",
                 "无 scripts/pkg_digest.py 或版本过旧（无 EmptyAssembly）——重跑 install.sh 补齐")
        return
    try:
        current = digest(source_dir)
    except EmptyAssembly as e:
        # 独立子句且**排在 (OSError, ValueError) 之前**：EmptyAssembly 是 ValueError 子类，
        # 并进同一个 tuple 会被当成 SKIP，而「装配集为空」绝不是合法降级。
        rows.add("装配版本", "WARN", f"装配集为空，摘要不可信（{e}）——源包疑似不完整，重跑 install.sh")
        return
    except (OSError, ValueError) as e:
        rows.add("装配版本", "SKIP", f"源包摘要计算失败（{e}）")
        return
    if current == stamped:
        rows.add("装配版本", "ok", f"源包与装配态一致（{stamped}）")
        return
    rows.add("装配版本", "WARN",
             f"源包已前进/落后于装配态（装配 {stamped} → 当前 {current}）——"
             "生效：npm 全局源包态 `atlas upgrade` 后在项目里跑 `atlas update`；"
             "本地源仓态重跑 `install.sh`；差异明细跑 `backflow.py` 三态对账"
             "（SOURCE_ONLY 拒绝护栏；D79 ⑤）")


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
        rows.add("E2E 真跑", "SKIP", f"无 {page}{_ext}（{strip_inline_comment(m.group(1)) if m else 'cases_dir'} 未建？）")
        return
    # E1 单段：真实栈由业务侧拉起，atlas_check 不再起原型静态服务。
    mbase = re.search(r"^[^\S\n]*app_base_url:[^\S\n]*(\S+)", text, re.M)
    if not mbase or strip_inline_comment(mbase.group(1)) in ("null", "~", '""', "''"):
        rows.add("E2E 真跑", "SKIP",
                 "e2e.app_base_url 为空（单段执行：真实栈地址未声明；业务侧拉起后重跑）")
        return
    # 地址已声明但**靶场不可达** ⇒ 同为「未就绪」，不是失败（`gates.md` 2.2 本行的「不查什么」
    # = 真栈没起来时的任何结论，那时只报 SKIP）：少这一步就会把整批 `goto` 失败记成 FAIL
    # （2026-10-04 实测 79 failed 全因前端未起），真红与假红不可区分 ⇒ 狼来了效应（`3509 §B189-1`）。
    _ok, _why = _url_reachable(strip_inline_comment(mbase.group(1)))
    if not _ok:
        rows.add("E2E 真跑", "SKIP",
                 f"ENV_ISSUE：e2e.app_base_url 不可达（{strip_inline_comment(mbase.group(1))}；{_why}）"
                 "——真实栈未就绪，非用例失败")
        return
    # 靶场重置（2026-09-30，台账 P4）：零步基线与用例前提假设种子初始态，真栈持久化
    # 跨 run 残留 ⇒ 声明了 `e2e.reset`（shell 命令串）就在真跑前执行；非零 ⇒ FAIL
    # （重置失败时继续跑 = 带着脏状态跑，结论不可信）。
    mreset = re.search(r"^[^\S\n]*reset:[^\S\n]*(\S.*\S)[^\S\n]*$", text, re.M)
    if mreset and strip_inline_comment(mreset.group(1)) not in ("null", "~"):
        reset_cmd = _reset_command(mreset.group(1))
        code_r, out_r = run(reset_cmd, root, timeout=300, shell=True)
        if code_r != 0:
            rows.add("E2E 真跑" + (f"[{page}]" if page else "（六页）"), "FAIL",
                     f"e2e.reset 失败（exit {code_r}）：{out_r.strip()[-200:]}",
                     command=reset_cmd, full_output=out_r, code=code_r)
            return
    # node 单轨（3507 BO）：运行器解析 + **可解析性判据**（issue #24，`DESIGN.md` D101）。
    # 判据本体 = 「从 `product/e2e/scripts/` 出发 `@playwright/test` 可解析」——
    # 即 `gates.md` 2.2 本行早写明的「按**依赖可导入性**，不按路径存在」；
    # 二进制存在只是必要条件（此前把它当充要条件 ⇒ ESM 项目上「找得到 bin、解析不到模块」半生效，
    # 错误落到运行期并被计成「跑失败 / 无结果」）。解析/探针/修复全走单源内核 `_support/pw_runner.py`。
    nm = re.search(r"^[^\S\n]*node_modules:[^\S\n]*(\S+)", text, re.M)
    nm_rel = Path(strip_inline_comment(nm.group(1))) if nm else None
    pw_bin, node_path, runner_source, why = pw_runner.resolve(root, str(nm_rel) if nm_rel else None)
    if pw_bin is None:
        disp_bin = (nm_rel / ".bin" / pw_runner.PW_BIN_NAME) if nm_rel else "未配置"
        hint = f"（提示：请在 {nm_rel.parent if nm_rel else '.'} 执行 npm i -D {pw_runner.MODULE_SPEC}）"
        rows.add("E2E 真跑", "FAIL",
                 f"node-playwright 可执行文件不存在：{disp_bin}（stack-profile e2e.node_modules）{hint}",
                 command="", full_output=f"pw_bin not found: {pw_bin}\n提示：请先在对应目录安装 {pw_runner.MODULE_SPEC}")
        return
    # 判据本体（与执行器同一实现、同一修复）：不成立 ⇒ 先试全局兜底修复，复检仍不过 ⇒ FAIL。
    # 修复成功 ⇒ 真跑能跑，但结论依赖**机器全局状态**（非项目自足）⇒ 降为 WARN 并在行内写明。
    runner_status, runner_detail, runner_note = pw_runner.ensure_resolvable(
        scripts, pw_runner.resolution_root(scripts, root), source=runner_source, nm_dir=node_path)
    if runner_status == "fail":
        rows.add("E2E 真跑", "FAIL",
                 f"node 运行器判据不成立：{runner_detail}（判据 = 依赖可导入性，不按路径存在；gates.md 2.2）",
                 command="", full_output=f"probe failed at {scripts}\n{runner_detail}")
        return
    # 浏览器就绪判据（issue #38，`DESIGN.md` D124）：模块可解析 ≠ launch 可成——npm 装包不自动
    # 下载浏览器，缺 ⇒ launch 阶段才炸，门此前已判「就绪」= 谎报（错误落到 Playwright 内部报错、
    # 非门的显式输出）。判据 = playwright 自算的 chromium 可执行路径存在（吃 `PLAYWRIGHT_BROWSERS_PATH`），
    # 或 `ATLAS_PLAYWRIGHT_CHANNEL` 已设（launch 走系统通道浏览器，缓存判据不适用）。
    # 不成立 ⇒ FAIL 指名安装命令——与上分支「运行器可执行不存在 ⇒ FAIL + npm i 提示」同族：
    # E2E 意图已声明、依赖装了一半，不是「前置未声明」的 SKIP。
    br_ok, br_detail = pw_runner.probe_browser(scripts)
    if not br_ok:
        rows.add("E2E 真跑", "FAIL",
                 f"node 浏览器判据不成立：{br_detail}",
                 command="", full_output=f"browser probe at {scripts}\n{br_detail}")
        return
    spec_arg = f"{page}.spec.ts" if page else ""
    node_path_env = f"NODE_PATH={node_path} " if node_path else ""
    # **执行 cwd = 生成物所在目录**（issue #29 / `DESIGN.md` D106）：生成物里的相对路径全是
    # cwd 相对的（`storageState: ".atlas-auth/state.json"`、`outputDir: ".atlas-run"`、mock fixture）。
    # 此前本门用 cwd=项目根 + `-c <相对路径>` 跑，Playwright 把 storageState 解析到 `<root>/.atlas-auth/`
    # ⇒ **读不到人的会话**（并在那儿写一个空 state）⇒ 未登录态跑用例 ⇒ 20s 超时假红。
    # 控制台（`e2e_console`）本来就是 `cd scripts` 再跑 —— 本门与它对齐，两个入口一个口径。
    cmd = f"{node_path_env}{pw_bin} test -c playwright.config.ts {spec_arg}".strip()
    code, out = run(cmd, scripts, timeout=1800, shell=True)
    m2 = re.findall(r"(\d+) (passed|failed|error)", out)
    summary = " ".join(f"{n} {k}" for n, k in m2) or "无结果"

    results_json = scripts / ".atlas-run" / "results.json"
    parsed_stats = {}
    if results_json.is_file():
        try:
            rdata = json.loads(results_json.read_text(encoding="utf-8"))
            stats = rdata.get("stats", {})
            parsed_stats = {
                "expected": stats.get("expected", 0),
                "unexpected": stats.get("unexpected", 0),
                "flaky": stats.get("flaky", 0),
                "skipped": stats.get("skipped", 0),
                "duration_ms": stats.get("duration", 0),
            }
        except Exception:
            pass

    full_err_output = out
    if code != 0 and results_json.is_file():
        try:
            rdata = json.loads(results_json.read_text(encoding="utf-8"))
            err_details = []
            for suite in rdata.get("suites", []):
                for spec in suite.get("specs", []):
                    for t in spec.get("tests", []):
                        if t.get("status") == "unexpected":
                            title = " > ".join(t.get("titlePath", [spec.get("title", "")]))
                            res_list = t.get("results", [])
                            err_msg = ""
                            if res_list and "error" in res_list[0]:
                                err_msg = res_list[0]["error"].get("message", "")
                            err_details.append(f"FAILED: {title}\n{err_msg}")
            if err_details:
                full_err_output = "\n".join(err_details) + "\n\n--- Playwright Raw Output ---\n" + out
        except Exception:
            pass

    if code == 0:
        summary_path = root / ".atlas" / "runs" / "e2e-summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        git_head, git_dirty = "unknown", False
        try:
            p_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root),
                                    capture_output=True, text=True, timeout=5)
            if p_head.returncode == 0:
                git_head = p_head.stdout.strip()
            p_st = subprocess.run(["git", "status", "--porcelain"], cwd=str(root),
                                  capture_output=True, text=True, timeout=5)
            if p_st.returncode == 0:
                git_dirty = bool(p_st.stdout.strip())
        except Exception:
            pass

        summary_payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "git_head": git_head,
            "git_dirty": git_dirty,
            "page": page,
            "status": "ok",
            "summary": summary,
            "stats": parsed_stats,
            "results_path": str(results_json.relative_to(root)) if results_json.is_file() and results_json.is_relative_to(root) else None,
        }
        try:
            summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    level = "ok" if code == 0 else "FAIL"
    if level == "ok" and runner_note:
        # 运行器来自全局兜底：真跑跑得起来，但结论依赖**机器全局状态**而非项目自足 ⇒ 降档
        # 可见（WARN 不是失败，也不假装「项目自足」）；本次有没有补链写在词尾。
        level = "WARN"
        summary = f"{summary} ｜ {runner_note}" + (f"（{runner_detail}）" if runner_detail else "")
    rows.add("E2E 真跑" + (f"[{page}]" if page else "（六页）"),
             level, summary,
             command=cmd, full_output=full_err_output, code=code)


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
    check_review_report(root, rows)
    check_serial_execution(root, rows)
    check_drift(root, rows)
    check_version(root, rows)
    if not args.fast:
        check_e2e(root, rows, args.page)

    error_log = root / ".atlas" / "runs" / "last-check-error.log"
    if rows.failed:
        error_log.parent.mkdir(parents=True, exist_ok=True)
        with error_log.open("w", encoding="utf-8") as f:
            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            f.write("=" * 80 + "\n")
            f.write(f"ATLAS CHECK FAILURE LOG - {now_str}\n")
            f.write(f"Target root: {root}\n")
            f.write(f"Failed count: {len(rows.failures)}\n")
            f.write("=" * 80 + "\n\n")
            for i, fail in enumerate(rows.failures, 1):
                f.write(f"[{i}/{len(rows.failures)}] Gate: {fail['name']}\n")
                if fail.get("command"):
                    f.write(f"Command: {fail['command']}\n")
                if fail.get("code") is not None:
                    f.write(f"Exit Code: {fail['code']}\n")
                if fail.get("detail"):
                    f.write(f"Summary: {fail['detail']}\n")
                f.write("--- Full Output ---\n")
                f.write(fail.get("output", "").strip() + "\n\n")
    else:
        if error_log.is_file():
            try:
                error_log.unlink()
            except OSError:
                pass

    if args.json:
        payload = {
            "root": str(root),
            "ok": not rows.failed,
            "rows": rows.rows,
            "failures": rows.failures,
            "error_log": str(error_log.relative_to(root)) if rows.failed and error_log.is_file() else None,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"atlas check @ {root}")
        for r in rows.rows:
            line = f"  {r['status']:<4} {r['name']:<26}"
            if r["detail"]:
                line += " " + r["detail"]
            print(line)
        if rows.failed:
            print("\n" + "=" * 60)
            print("❌ 门禁失败详情 (Failures Breakdown):")
            for fail in rows.failures:
                print(f"▶ [{fail['name']}] (Exit Code: {fail.get('code')})")
                if fail.get("command"):
                    print(f" • 命令: {fail['command']}")
                out_lines = [l for l in fail.get("output", "").splitlines() if l.strip()]
                key_lines = [l for l in out_lines if "[FAIL]" in l or "Error" in l or "error:" in l.lower()]
                lines_to_show = key_lines[:20] if key_lines else out_lines[-10:]
                for l in lines_to_show:
                    print(f" • {l}")
            print("=" * 60)
            rel = error_log.relative_to(root) if error_log.is_file() else error_log
            print(f"\nFAIL (详细错误堆栈已落盘至: {rel})")
        else:
            print("OK")
    return 1 if rows.failed else 0


if __name__ == "__main__":
    sys.exit(main())
