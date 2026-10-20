#!/usr/bin/env python3
"""atlas 共享内核 —— node 运行器：二进制解析 / **可解析性判据** / 全局兜底修复（单源）。

**为什么存在**（issue #24，2026-10-17 现场 = 百炼/v2前端；决策行见 `DESIGN.md` D101）：

「找得到 playwright」此前被实现为**判据 = 可执行文件存在**（`<e2e.node_modules>/.bin/playwright`
或系统全局命令），而真跑需要的性质是「**从 `product/e2e/scripts/` 出发 `@playwright/test`
可解析**」。`shared/gates.md` 2.2「E2E 真跑」行早已写明「解释器按**依赖可导入性**选
（不按路径存在）」——node 轨的实现漂离了该口径（**是实现漂了，不是设计选择**）。

漂离的代价在 ESM 项目上暴露为**半生效**：项目 `package.json` 声明 `"type": "module"`
⇒ 生成物（`playwright.config.ts` / `*.spec.ts`）走 ESM 解析 ⇒ Node 的 ESM 解析器
**不读 `NODE_PATH`**（该通道属 CJS）⇒ 全局兜底（F19）找得到 binary、却解析不到模块：
错误落到运行期（`Cannot find package '@playwright/test'`），且被上层计成「跑失败 / 无结果」。
`NODE_PATH` 保留（对 CJS 项目仍是真通道、对 ESM 项目无害），但它**不再冒充判据**。

本模块的两个语义**分开**，不得混用：

- **`resolve()`** —— binary 在哪（项目声明优先，全局兜底）。`source` 出口告知来自哪一侧。
- **`probe()`** —— **判据本体**：可解析性。两道消费者共用同一实现：
  `atlas_check` 真跑门用它判红绿，`e2e_console` 用它复检修复结果（不造第二份）。
- **`probe_browser()`** —— 真跑依赖的**第二件事**（issue #38，`DESIGN.md` D124，2026-10-20）：
  浏览器可执行存在（npm 装包不自动下载浏览器；`ATLAS_PLAYWRIGHT_CHANNEL` 已设 ⇒ 旁路）。
  同样两道消费者共用：真跑门不成立 ⇒ `FAIL` 指名安装命令；控制台 ⇒ 起跑前诚实拒绝。
- **`ensure_resolvable()`** —— 判据不成立时**怎么办**由调用方定：执行器要「让这轮能跑」⇒ 修复；
  门要「这个结论可信吗」⇒ 修复后照样在行里写明（依赖机器全局状态 = 不是项目自足）。

修复 = **幂等软链**（本机实测能让 ESM 解析生效、且不把全局版本混进项目依赖的唯一通道）；
只在 `source == "global"` 时发生——项目自装目录里缺模块是**项目自身缺口**，给软链会把全局版本
混进项目依赖（版本漂移源），故该情形一律**不修、只报**。

- **随包分发**：本目录随 `install.sh` 整包装配；**纯标准库**（契约 `rings/e2e/reference.md` §8.3）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

#: 生成物 import 的模块名（判据对象；`_support/` 侧一切判定以它为准）
MODULE_SPEC = "@playwright/test"

#: 可解析性探针：`node --input-type=module -e` 的 **解析基准 = cwd**（本机实测，2026-10-17：
#: cwd 内可解析 ⇒ exit 0；换 cwd ⇒ exit 1 + `ERR_MODULE_NOT_FOUND`）。故调用方必须以
#: `scripts_dir` 为 cwd 执行——那正是生成物所在目录，等价于它们自己 import 时的解析起点。
PROBE_SNIPPET = (
    "import('" + MODULE_SPEC + "').then(()=>process.exit(0),"
    "e=>{console.error('ERR '+((e&&e.code)||e));process.exit(1)})"
)

PW_BIN_NAME = "playwright.cmd" if sys.platform == "win32" else "playwright"

#: 浏览器就绪探针：让 playwright **自己算** chromium 可执行路径（走它自带的 registry——
#: 自动吃 `PLAYWRIGHT_BROWSERS_PATH` 与所装版本的 revision，Python 侧不猜路径），存在性
#: 由本侧判（2026-10-20 实证：未下载的浏览器 `executablePath()` **返回计算路径而不抛错**，
#: 本机 firefox/webkit 未下载也各得一路径 ⇒ 「算得出」≠「装了」）。
BROWSER_SNIPPET = (
    "import('" + MODULE_SPEC + "').then(m=>{"
    "if(!(m.chromium&&typeof m.chromium.executablePath==='function'))"
    "{console.error('ERR chromium 不可用：@playwright/test 未导出 chromium');process.exit(1)}"
    "try{console.log(m.chromium.executablePath())}"
    "catch(e){console.error('ERR '+((e&&e.message)||e));process.exit(1)}}"
    ",e=>{console.error('ERR '+((e&&e.code)||e));process.exit(1)})"
)

#: channel 旁路环境变量（与生成物 `launchOptions.channel` 同源：`gen_e2e_scripts.py` 读它发
#: channel）——已设 ⇒ launch 走系统通道浏览器，ms-playwright 缓存判据**不适用**。
CHANNEL_ENV = "ATLAS_PLAYWRIGHT_CHANNEL"


# ---------------------------------------------------------------- 全局侧探测

def is_node_playwright(p: Path | str) -> bool:
    """排除 Python 版 CLI（同名的 `playwright` 命令可能是 `pip install playwright` 的）。"""
    try:
        path = Path(p).resolve()
        if not path.is_file():
            return False
        if "node_modules" in str(path) or path.suffix in (".js", ".mjs", ".cjs"):
            return True
        head = path.read_text(encoding="utf-8", errors="ignore")[:300]
        if "python" in head.lower() or "playwright.__main__" in head:
            return False
        return True
    except Exception:
        return True


def global_nm_root() -> str | None:
    """npm 全局 node_modules 根：先环境变量 `NODE_PATH`，再 `npm root -g`。"""
    g = os.environ.get("NODE_PATH")
    if g:
        return g
    try:
        res = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None


def has_module(nm_root: str | None) -> bool:
    """全局根下是否存在 node 轨 playwright 模块（`@playwright/test` 或 `playwright`）。"""
    if not nm_root:
        return False
    for p in nm_root.split(os.pathsep):
        gnp = Path(p).resolve()
        if (gnp / "@playwright" / "test").exists() or (gnp / "playwright").exists():
            return True
    return False


def global_playwright(nm_root: str | None) -> Path | None:
    """全局 playwright 可执行文件（PATH 命中优先，其次按 npm prefix / 全局根推候选）。"""
    if not has_module(nm_root):
        return None
    cand = shutil.which("playwright")
    if cand and is_node_playwright(cand):
        return Path(cand)
    candidates: list[Path] = []
    if nm_root:
        for p in nm_root.split(os.pathsep):
            gnp = Path(p).resolve()
            candidates.append(gnp.parent / "bin" / PW_BIN_NAME)
            candidates.append(gnp.parent.parent / "bin" / PW_BIN_NAME)
            candidates.append(gnp / ".bin" / PW_BIN_NAME)
    try:
        res_bin = subprocess.run(["npm", "prefix", "-g"], capture_output=True, text=True, timeout=5)
        if res_bin.returncode == 0 and res_bin.stdout.strip():
            candidates.append(Path(res_bin.stdout.strip()) / "bin" / PW_BIN_NAME)
    except Exception:
        pass
    for c in candidates:
        if c.is_file() and is_node_playwright(c):
            return c
    return None


# ---------------------------------------------------------------- 二进制解析

def resolve(root: Path, nm_rel: str | None) -> tuple[Path | None, Path | None, str, str]:
    """运行器二进制解析（项目声明优先，全局兜底）。

    → `(pw_bin, nm_dir, source, why)`；`source ∈ {"local", "global", "none"}`。
    `why` 非空 ⇔ `pw_bin is None`。**本函数不判可解析性**（那是 `probe` 的事）。
    """
    nm_dir = (root / nm_rel).resolve() if nm_rel else None
    pw_bin = (nm_dir / ".bin" / PW_BIN_NAME) if nm_dir else None
    if pw_bin and pw_bin.is_file():
        return pw_bin, nm_dir, "local", ""

    g_root = global_nm_root()
    g_pw = global_playwright(g_root)
    if g_pw is not None and g_root:
        return g_pw, Path(g_root), "global", ""

    if not nm_rel:
        return None, None, "none", "stack-profile 未声明 e2e.node_modules（node-playwright 依赖目录，契约 §7）"
    return None, None, "none", f"node-playwright 可执行文件不存在：{pw_bin}（e2e.node_modules）"


# ---------------------------------------------------------------- 判据本体

def probe(scripts_dir: Path, node: str | None = None) -> tuple[bool, str]:
    """**判据本体**：从 `scripts_dir` 出发 `MODULE_SPEC` 可解析？

    → `(ok, detail)`；`detail` 非空 ⇔ 不成立（末行错误，便于行内点名）。
    """
    if not scripts_dir.is_dir():
        return False, f"脚本目录不存在：{scripts_dir}"
    exe = node or shutil.which("node")
    if not exe:
        return False, "未找到 node 可执行文件（可解析性探针无法运行；playwright CLI 亦依赖它）"
    try:
        p = subprocess.run([exe, "--input-type=module", "-e", PROBE_SNIPPET],
                           cwd=str(scripts_dir), capture_output=True, text=True, timeout=120)
    except Exception as e:  # 超时 / OSError：不可解析的判定同样成立，但如实给原因
        return False, f"探针无法运行：{e}"
    if p.returncode == 0:
        return True, ""
    # `getattr`：工程里的测试会把 `subprocess.run` 换成轻量假件（无 stderr 字段）——
    # 探针不得因此抛错（抛错 = 把「判据不成立」变成「工具坏了」）。
    tail = [ln for ln in str(getattr(p, "stderr", "") or "").strip().splitlines() if ln.strip()]
    return False, (tail[-1] if tail else f"exit {p.returncode}")


def probe_browser(scripts_dir: Path, node: str | None = None) -> tuple[bool, str]:
    """**浏览器就绪判据**（issue #38，`DESIGN.md` D124）：真跑依赖的**第二件事**。

    模块可解析（`probe`）≠ launch 可成：npm 装包**不自动下载浏览器**，缺 ⇒ launch 阶段才失败，
    而就绪门已判过「就绪」= 谎报（错误落到 Playwright 内部报错，不是门的显式输出——与 D101
    「判据必须 = 真跑真正依赖的性质」同族：真跑依赖「模块可解析 **加** 浏览器可执行」两件事）。

    判据 = playwright 自算的 chromium 可执行路径**存在**（`BROWSER_SNIPPET`）；
    `ATLAS_PLAYWRIGHT_CHANNEL` 已设 ⇒ launch 走系统通道浏览器，缓存判据不适用 ⇒ 直接通过。

    两道消费者共用：`atlas_check` 真跑门用它判红绿（不成立 ⇒ `FAIL` 指名安装命令），
    `e2e_console` 起跑前置用它诚实拒绝（不起注定 launch 失败的子进程）——不造第二份。
    → `(ok, detail)`；`detail` 非空 ⇔ 不成立（带安装出路）。
    """
    if os.environ.get(CHANNEL_ENV):
        return True, ""
    if not scripts_dir.is_dir():
        return False, f"脚本目录不存在：{scripts_dir}"
    exe = node or shutil.which("node")
    if not exe:
        return False, "未找到 node 可执行文件（浏览器探针无法运行）"
    try:
        p = subprocess.run([exe, "--input-type=module", "-e", BROWSER_SNIPPET],
                           cwd=str(scripts_dir), capture_output=True, text=True, timeout=120)
    except Exception as e:  # 超时 / OSError：与 probe() 同判——如实给原因，不把「判据不成立」变「工具坏了」
        return False, f"浏览器探针无法运行：{e}"
    if p.returncode != 0:
        tail = [ln for ln in str(getattr(p, "stderr", "") or "").strip().splitlines() if ln.strip()]
        return False, (tail[-1] if tail else f"exit {p.returncode}")
    out = str(getattr(p, "stdout", "") or "").strip()
    exe_path = out.splitlines()[-1].strip() if out else ""
    if not exe_path:
        return False, "playwright 未给出浏览器可执行路径（版本过旧或发行形态异常）"
    if not Path(exe_path).exists():
        return False, (f"chromium 浏览器未安装：{exe_path}"
                       "（npm 装包不自动下载浏览器；请执行 npx playwright install chromium，"
                       f"或设 {CHANNEL_ENV} 走系统通道浏览器）")
    return True, ""


def resolution_root(scripts_dir: Path, root: Path) -> Path:
    """Node 从 `scripts_dir` 逐级向上搜索 `node_modules` 时**最先命中**的那个（都不存在 ⇒ `<root>/node_modules`）。

    软链必须落在这里才可能被解析到：声明的 `e2e.node_modules` 是**二进制所在目录**，
    未必在 Node 的搜索路径上（两者在常规布局下重合，但不重合时判据才算得准）。
    """
    try:
        cur = scripts_dir.resolve()
        root_r = root.resolve()
    except OSError:
        return root / "node_modules"
    chain: list[Path] = []
    while True:
        chain.append(cur)
        if cur == root_r or cur.parent == cur:
            break
        cur = cur.parent
    for d in chain:
        nm = d / "node_modules"
        if nm.is_dir():
            return nm
    return root / "node_modules"


def _module_version(src: Path) -> str:
    for cand in (src / "package.json", src.parent / "playwright" / "package.json"):
        try:
            if cand.is_file():
                return str(json.loads(cand.read_text(encoding="utf-8")).get("version") or "")
        except Exception:
            continue
    return ""


def global_note(source: str, nm_dir: Path | None, nm_target: Path) -> str:
    """运行器来自全局兜底时的**标准说明**（`source != "global"` ⇒ 空串）。

    与「本次有没有动手」**无关**：用了机器全局状态是**跑的前提事实**，不是一次性事件
    （每一次都该说、每一次结论都因此降档）。两道消费者共用本函数给文案，不各写一份。
    """
    if source != "global":
        return ""
    ver = _module_version(Path(nm_dir) / "@playwright" / "test") if nm_dir else ""
    link = Path(nm_target) / "@playwright" / "test"
    return (f"运行器来自全局兜底：{MODULE_SPEC}{('@' + ver) if ver else ''}（{nm_dir}）"
            f"——结论依赖**机器全局状态**而非项目自足，解析链在 {link}；"
            f"建议项目自装（npm i -D {MODULE_SPEC}）以便可复现")


def ensure_resolvable(scripts_dir: Path, nm_target: Path, *, source: str,
                      nm_dir: Path | None = None) -> tuple[str, str, str]:
    """判据不成立时的处置：全局兜底 ⇒ 幂等软链 + 复检；其余 ⇒ 不修只报。

    → `(status, detail, note)`：
    - `status ∈ {"ok", "repaired", "fail"}`：`ok` = 探针直接通过（无需动手）；
      `repaired` = 原本不通过、已补链并**复检通过**；`fail` = 仍不成立。
    - `detail`：`fail` 时的真原因（不得回退成「跑失败 / 无结果」）；`repaired` 时 = 本次动作说明。
    - `note`：`global_note()` 的标准说明（全局兜底恒非空）——**调用方必须输出**。
    """
    note = global_note(source, nm_dir, nm_target)
    ok, detail = probe(scripts_dir)
    if ok:
        return "ok", "", note
    if source != "global":
        return "fail", (f"{MODULE_SPEC} 从 {scripts_dir} 不可解析（{detail}）"
                         "——判据 = 依赖可导入性，不按路径存在；ESM 下 NODE_PATH 无效"), ""
    if nm_dir is None:
        return "fail", f"{MODULE_SPEC} 从 {scripts_dir} 不可解析（{detail}）且全局根未知", ""
    src = Path(nm_dir) / "@playwright" / "test"
    if not src.exists():
        return "fail", f"全局 {MODULE_SPEC} 不存在：{src}", note
    link = Path(nm_target) / "@playwright" / "test"
    try:
        if os.path.lexists(link):
            same = os.path.realpath(str(link)) == os.path.realpath(str(src))
            if not same:
                return "fail", (f"{MODULE_SPEC} 从 {scripts_dir} 不可解析，且链接位已被占用"
                                 f"（非本工具所建，不覆盖）：{link}"), note
        else:
            link.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(src, link)
    except OSError as e:
        return "fail", f"{MODULE_SPEC} 从 {scripts_dir} 不可解析，软链失败：{link} → {src}（{e}）", note
    ok2, detail2 = probe(scripts_dir)
    if not ok2:
        return "fail", f"{MODULE_SPEC} 在补软链后仍不可解析（{detail2}）", note
    return "repaired", f"本次已在 {link} 补软链（幂等、可删）", note
