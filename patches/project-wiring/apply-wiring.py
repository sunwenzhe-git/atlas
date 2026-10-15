#!/usr/bin/env python3
"""atlas 项目接线（project wiring）——把入口指针、收口 hook、宿主扩展幂等写进目标项目。

用法：
    python3 apply-wiring.py --target <项目根> [--apply] [--json]

做五件事（各自独立幂等）：

  1. `<项目根>/AGENTS.md`：在 Trellis 区块 `<!-- TRELLIS:END -->` **之后**追加
     `<!-- ATLAS:START -->…<!-- ATLAS:END -->` 段。该段位于 Trellis 区块**之外**，
     因此不被 `trellis update` 覆盖。已存在则整段按源更新（不新建重复段）。
     文件不存在时创建。

  2. `<项目根>/.trellis/config.yaml`：登记 `after_finish` hook 跑
     `refresh_structure.py`（结构事实刷新，决策 D38）；已有 `hooks:` 块则并入，
     否则在文件末尾新增。

  3. `<项目根>/pytest.ini`（仅 Python 工程）：补 `ac` marker 注册；非 Python 工程里
     若躺着本脚本误建的那一份，按退役对称清掉。

  4. `<项目根>/.pi/`（仅 pi 宿主）：把官方扩展落到 `.pi/extensions/atlas/index.ts`，
     并在 `.pi/settings.json` 的 `extensions[]` 里幂等登记一行（2026-10-15 补）。

  5. `<项目根>/.gitignore`（仅已存在时）：幂等追加一行 `.adapter-out/`（2026-10-15 补）。
     issue #8 后 atlas 全部中间产物统一落项目根该目录（适配器输出 / 漂移标记 /
     图谱新鲜度标记），不忽略则 `git status` 常驻未跟踪噪声——**对所有接线项目成立**，
     不只图谱用户。判据：文件**不存在 ⇒ 不首创**（跳过并在报告里给一行建议）；
     内容已含 `.adapter-out` 字样 ⇒ 幂等跳过；出现 `!.adapter-out` 负模式 ⇒ 跳过，
     不与用户既有规则打架。**本触点无退役对称**：`.gitignore` 不是本项目创建的文件，
     追加后永不回收（与 `pytest.ini` 的「逐字节相等才清」不同——追加是单向动作，
     由报告行当刻告知用户）。

设计要点：
  * 只做**外科式插入 / 替换**，不整体覆盖任何文件；标记外内容原样保留。
  * 缺省 dry-run（安全默认）；真正写入需显式 `--apply`。
  * `.yaml` 目标写入前做轻量结构护栏（不依赖第三方库）：`hooks:` 顶层键唯一、
    hook 命令行存在；不满足则报 error 且不写该文件。`.pi/settings.json` 同律：
    结构判读不了就跳过（只报要手加的那一行），不猜结构。
  * **不认识的目标形态 = 跳过 + 说明**，绝不自动创建宿主目录（非 pi 项目不建 `.pi/`）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent
POINTER_SNIPPET = PKG_ROOT / "agent-pointer.md"

ATLAS_START = "<!-- ATLAS:START -->"
ATLAS_END = "<!-- ATLAS:END -->"
TRELLIS_END = "<!-- TRELLIS:END -->"
AGENTS_REL = "AGENTS.md"

HOOK_CMD = "python3 .atlas/scripts/refresh_structure.py --root . --chain"
# C1（R7，2026-10-15）：存量钩子的**前缀**（幂等判据必须冗余于一字符）——
# 子串等于旧命令会漏识别 `--apply` 旧形态 ⇒ 双 hook 常驻、refresh 跑两遍。
HOOK_PREFIX = "python3 .atlas/scripts/refresh_structure.py --root ."
CONFIG_REL = ".trellis/config.yaml"

RE_HOOKS = re.compile(r"^hooks:\s*(#.*)?$")
RE_AFTER_FINISH = re.compile(r"^  after_finish:\s*(#.*)?$")
RE_TOP_LEVEL = re.compile(r"^\S")


def render_pointer() -> str:
    body = POINTER_SNIPPET.read_text(encoding="utf-8").rstrip("\n")
    return f"{ATLAS_START}\n{body}\n{ATLAS_END}\n"


# --------------------------------------------------------------------- AGENTS.md

def wire_agents(target: Path) -> dict:
    path = target / AGENTS_REL
    block = render_pointer()

    if not path.exists():
        return {
            "file": AGENTS_REL, "status": "applied", "detail": "created",
            "_write": (path, block),
        }

    text = path.read_text(encoding="utf-8")
    has_start = ATLAS_START in text
    has_end = ATLAS_END in text

    if has_start != has_end:
        return {"file": AGENTS_REL, "status": "error",
                "detail": f"标记不成对（{ATLAS_START if has_start else ATLAS_END} 单侧存在），不修改"}

    if has_start:
        i = text.index(ATLAS_START)
        j = text.index(ATLAS_END) + len(ATLAS_END)
        if text[j:j + 1] == "\n":
            j += 1
        new_text = text[:i] + block + text[j:]
        detail = "updated (block replaced)"
    elif TRELLIS_END in text:
        idx = text.index(TRELLIS_END) + len(TRELLIS_END)
        if text[idx:idx + 1] == "\n":
            idx += 1
        new_text = text[:idx] + block + text[idx:]
        detail = "applied (after TRELLIS:END)"
    else:
        new_text = text
        if not new_text.endswith("\n"):
            new_text += "\n"
        new_text += "\n" + block
        detail = "applied (appended at EOF)"

    if new_text == text:
        return {"file": AGENTS_REL, "status": "skipped", "detail": "already current"}
    return {"file": AGENTS_REL, "status": "applied", "detail": detail, "_write": (path, new_text)}


# ----------------------------------------------------------------- .trellis/config.yaml

def wire_config(target: Path) -> dict:
    path = target / CONFIG_REL
    if not path.exists():
        return {"file": CONFIG_REL, "status": "skipped",
                "detail": "config.yaml 不存在（Trellis 未初始化？）"}

    text = path.read_text(encoding="utf-8")
    if HOOK_CMD in text:
        return {"file": CONFIG_REL, "status": "skipped", "detail": "after_finish hook 已登记"}

    # C1 迁移分支（R7）：识别旧形态 `HOOK_PREFIX … --apply`（引号/裸命令皆），**原位替换**
    # 为 --chain，而不是插入新行——否则旧+新双 hook 常驻，每次 finish 刷新跑两遍。
    if HOOK_PREFIX in text and HOOK_CMD not in text:
        tails = [m.group(1) for m in re.finditer(re.escape(HOOK_PREFIX) + r"([^\n\"\']*)", text)]
        if any(t.strip() == "--apply" for t in tails):
            new_text = re.sub(re.escape(HOOK_PREFIX) + r"\s+--apply", HOOK_CMD, text)
            # 护栏：替换后同一文件内仍有 `HOOK_PREFIX --apply`（多 hook 场景不期）则拒绝
            if "--apply" in new_text and HOOK_PREFIX in new_text:
                return {"file": CONFIG_REL, "status": "error",
                        "detail": "迁移护栏：替换后仍存在旧形态 --apply hook，不修改"}
            return {"file": CONFIG_REL, "status": "applied",
                    "detail": "hook upgraded in-place (--apply → --chain)", "_write": (path, new_text)}
        if all(t.strip() not in ("--apply", "--chain") for t in tails):
            # 前缀在但命令尾是自定义形态 ⇒ 尊重用户自定 hook，不插第二行（防双 hook 常驻）
            return {"file": CONFIG_REL, "status": "skipped",
                    "detail": "存在自定义 refresh hook（yellow 尾非 --apply/--chain），未改"}

    lines = text.splitlines(keepends=True)

    hooks_i = next((i for i, ln in enumerate(lines) if RE_HOOKS.match(ln)), None)

    if hooks_i is not None:
        after_finish_i = None
        for j in range(hooks_i + 1, len(lines)):
            if RE_TOP_LEVEL.match(lines[j]):
                break  # 离开 hooks 子块
            if RE_AFTER_FINISH.match(lines[j]):
                after_finish_i = j
                break
        if after_finish_i is not None:
            lines.insert(after_finish_i + 1, f'    - "{HOOK_CMD}"\n')
            detail = "applied (hook added to existing after_finish)"
        else:
            lines.insert(hooks_i + 1, f'  after_finish:\n    - "{HOOK_CMD}"\n')
            detail = "applied (after_finish added to existing hooks)"
    else:
        if text and not text.endswith("\n"):
            lines.append("\n")
        lines.append("\n# atlas structure refresh（D38）：每个任务 Finish 后刷新结构事实指针层\n")
        lines.append("hooks:\n")
        lines.append("  after_finish:\n")
        lines.append(f'    - "{HOOK_CMD}"\n')
        detail = "applied (new hooks block at EOF)"

    new_text = "".join(lines)

    # 轻量 YAML 结构护栏（不依赖 PyYAML）
    top_hooks = [ln for ln in new_text.splitlines() if RE_HOOKS.match(ln)]
    if len(top_hooks) != 1:
        return {"file": CONFIG_REL, "status": "error",
                "detail": f"YAML 护栏：顶层 hooks: 出现 {len(top_hooks)} 次（期望 1），不修改"}
    if HOOK_CMD not in new_text:
        return {"file": CONFIG_REL, "status": "error",
                "detail": "YAML 护栏：hook 命令未写入，不修改"}

    if new_text == text:
        return {"file": CONFIG_REL, "status": "skipped", "detail": "already current"}
    return {"file": CONFIG_REL, "status": "applied", "detail": detail, "_write": (path, new_text)}


# ------------------------------------------------------------------- pytest 配置兜底（R6.2 对账定稿，2026-10-15）

# 注释剥离（2026-10-15 事故）：出厂模板的 `backend_test:` 段是**注释示例**，逐字匹配 raw
# 文本会把**每个**按模板开户的项目判成 Python 工程 ⇒ 纯前端仓库里凭空多出一个 pytest.ini
# （存量实测：pnpm + React 仓库，`atlas init` 当刻即中招）。⇒ 只认**声明项**。
RE_COMMENT = re.compile(r"(?:^|\s+)#.*$")


def is_python_project(target: Path) -> bool:
    """探测是否为 Python 工程（stack-profile **声明**或根目录 Python 特征文件）。

    只看**声明**：注释里出现的关键字不算（见上面 RE_COMMENT 的事故注）——出厂模板的
    `#   framework: pytest` 是注释，不能当证据。声明面三种任一生效：
    `python` 字样 / `framework: pytest` / `backend_test:` 段（最后一个是本兜底所服务的
    AC 标记特性的**契约 opt-in 段**，`shared/stack-profile.md` §2）。
    """
    prof_path = target / "product" / "stack-profile.yaml"
    if prof_path.is_file():
        text = prof_path.read_text(encoding="utf-8", errors="ignore")
        declared = "\n".join(RE_COMMENT.sub("", ln) for ln in text.splitlines()).lower()
        if "python" in declared or "framework: pytest" in declared or "backend_test:" in declared:
            return True
    for marker in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile", ".venv"):
        if (target / marker).exists():
            return True
    return False


MARKERS_INI = (
    "[pytest]\n"
    "markers =\n"
    "    ac: mark test with AC ID for traceability\n"
)

MARKERS_PYPROJECT = (
    "[tool.pytest.ini_options]\n"
    "markers = [\n"
    "    \"ac: mark test with AC ID for traceability\",\n"
    "]\n"
)


def _has_pytest_section(pyproject: Path) -> bool:
    try:
        return "[tool.pytest" in pyproject.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def wire_python_scaffold(target: Path) -> dict:
    """AC 标记注册兜底——**载体优先级：已有 pytest 配置文件 > 既有 pytest.ini > 新建 pytest.ini**。

    R6.2 对账定稿（2026-10-15）：本兜底只承担 **`ac` marker 注册**这一项正当元数据；
    `pythonpath = .` 环境补丁已随 F23（适配器输出 `python3 -m pytest`，cwd 自动入
    `sys.path`）退役——线束不再替业务打环境补丁（假桩③病理）。

    优先级（防「复活被清掉的补丁」）：
      1. pyproject.toml / setup.cfg 已承载 pytest 配置 ⇒ skip；
      2. 既有 pytest.ini ⇒ 只补缺失的 marker 注册（pythonpath 不再注入）；
      3. 什么都没有 ⇒ 新建 pytest.ini（仅 marker 注册）。

    **退役对称（2026-10-15 补）**：非 Python 工程里若躺着一份**逐字节等于我们兜底内容**
    的 pytest.ini，那是本脚本早先误建的（判据事故见 `RE_COMMENT`）⇒ 清掉。用户改过 ⇒
    一字不动（只跳过）——「只删自己写的、且没被动过的东西」。
    """
    ini_path = target / "pytest.ini"
    if not is_python_project(target):
        if ini_path.is_file() and ini_path.read_text(encoding="utf-8") == MARKERS_INI:
            return {"file": "pytest.ini", "status": "removed",
                    "detail": "非 Python 工程：清掉本兜底误建的 pytest.ini"
                              "（仅当内容逐字节等于兜底内容；用户改过则保留）",
                    "_remove": ini_path}
        return {"file": "pytest.ini", "status": "skipped", "detail": "非 Python 工程，跳过"}

    pyproject = target / "pyproject.toml"
    setup_cfg = target / "setup.cfg"

    # 1. pyproject.toml / setup.cfg 已承载 pytest 配置 ⇒ 尊重，不另立 pytest.ini
    if pyproject.is_file() and _has_pytest_section(pyproject):
        return {"file": "pytest.ini", "status": "skipped", "detail": "已由 pyproject.toml 承载 pytest 配置"}
    if setup_cfg.is_file():
        text_cfg = setup_cfg.read_text(encoding="utf-8", errors="ignore")
        if "[tool:pytest]" in text_cfg:
            return {"file": "pytest.ini", "status": "skipped", "detail": "已由 setup.cfg 承载 pytest 配置"}

    if not ini_path.is_file():
        # 3. 全无 ⇒ 新建 pytest.ini（只承载 marker 注册；pythonpath 补丁已随 F23 退役）
        return {"file": "pytest.ini", "status": "applied",
                "detail": "created pytest.ini with ac marker registration (pythonpath retired with F23)",
                "_write": (ini_path, MARKERS_INI)}

    # 2. 既有 pytest.ini ⇒ 只补 marker 注册（幂等）
    content = ini_path.read_text(encoding="utf-8")
    if "markers" in content:
        return {"file": "pytest.ini", "status": "skipped", "detail": "pytest.ini 已包含 marker 注册"}

    new_content = content.rstrip("\n") + "\nmarkers =\n    ac: mark test with AC ID for traceability\n"
    return {"file": "pytest.ini", "status": "applied",
            "detail": "updated (appended ac marker registration)",
            "_write": (ini_path, new_content)}


# ----------------------------------------------------------------- .gitignore 兜底（2026-10-15 补，第 5 个触点）

GITIGNORE_REL = ".gitignore"
ADAPTER_OUT_LINE = ".adapter-out/"


def wire_gitignore(target: Path) -> dict:
    """`.gitignore` 追加 `.adapter-out/`（issue #8 后所有接线项目都需要，不只图谱用户）。

    三条判据（缺失即跳过并显式说明，不猜）：
      * 文件**不存在 ⇒ 不首创**——根 `.gitignore` 是用户自有文件，本脚手不替用户从零创建，
        只在报告里给出建议行；
      * 内容已含 `.adapter-out` **子串** ⇒ 已忽略，幂等跳过（子串判据兼容
        `.adapter-out`、`.adapter-out/*` 等一切等价写法）；
      * 出现 `!.adapter-out` 负模式 ⇒ 意见相反，跳过不与用户打架。
    """
    path = target / GITIGNORE_REL
    if not path.is_file():
        return {"file": GITIGNORE_REL, "status": "skipped",
                "detail": f"无 {GITIGNORE_REL} ⇒ 不首创（建议手动加一行 {ADAPTER_OUT_LINE}）"}
    text = path.read_text(encoding="utf-8")
    if "!" + ADAPTER_OUT_LINE.rstrip("/") in text:
        return {"file": GITIGNORE_REL, "status": "skipped",
                "detail": "存在 !.adapter-out 负模式 ⇒ 不与用户既有规则打架"}
    if ADAPTER_OUT_LINE.rstrip("/") in text:
        return {"file": GITIGNORE_REL, "status": "skipped", "detail": "已忽略 .adapter-out"}
    new_text = (text if text.endswith("\n") else text + "\n") + ADAPTER_OUT_LINE + "\n"
    return {"file": GITIGNORE_REL, "status": "applied",
            "detail": "appended .adapter-out/ (atlas 中间产物单一位点，issue #8)",
            "_write": (path, new_text)}


# ----------------------------------------------------------------- pi 宿主扩展（2026-10-15 补，第 4 个触点）

PI_REL = ".pi"
PI_SETTINGS_REL = ".pi/settings.json"
PI_EXT_ENTRY = "./extensions/atlas/index.ts"
PI_EXT_DEST_REL = ".pi/extensions/atlas/index.ts"
# 扩展源：`__file__` 的爷爷目录就是包根（源包态 = 仓库根；副本态 = `.atlas/`）
PI_EXT_SRC_REL = "extensions/pi.ts"

RE_EXT_ARRAY = re.compile(r'"extensions"\s*:\s*\[')


def _pi_ext_source() -> Path:
    return Path(__file__).resolve().parents[2] / PI_EXT_SRC_REL


def wire_pi_extension(target: Path) -> list[dict]:
    """pi 宿主：把官方扩展落到 `.pi/extensions/atlas/index.ts`，并在 `.pi/settings.json`
    的 `extensions` 数组里**幂等登记**一行（2026-10-15 补 —— 此前该扩展只在 npm 包里有，
    装配从不落地它，于是 `/atlas` 命令与「未开户」提示在真实项目里全都不存在）。

    三条纪律：
      * **非 pi 宿主不动**：没有 `.pi/` ⇒ 跳过（不替用户创建宿主目录）。
      * **外科式插入**：`settings.json` 只往数组里插一行，不整体重写（本脚本的既有设计要点）；
        数组形态无法可靠判读（缺 `extensions` 键 / 空数组）⇒ **跳过并给出要手加的那一行**，
        不猜结构、不覆盖。
      * **可逆**：注销 = 删掉那一行 + 删 `.pi/extensions/atlas/`。
    """
    pi_dir = target / PI_REL
    if not pi_dir.is_dir():
        return [{"file": PI_EXT_DEST_REL, "status": "skipped", "detail": "非 pi 宿主（无 .pi/），跳过"}]

    out: list[dict] = []

    # ① 扩展本体
    src = _pi_ext_source()
    dest = target / PI_EXT_DEST_REL
    if not src.is_file():
        out.append({"file": PI_EXT_DEST_REL, "status": "error",
                    "detail": f"找不到扩展源 {src}（包面缺 extensions/pi.ts）"})
    else:
        new_text = src.read_text(encoding="utf-8")
        if dest.is_file() and dest.read_text(encoding="utf-8") == new_text:
            out.append({"file": PI_EXT_DEST_REL, "status": "skipped", "detail": "already current"})
        else:
            existed = dest.is_file()
            out.append({"file": PI_EXT_DEST_REL, "status": "applied",
                        "detail": "refreshed from package" if existed else "installed from package",
                        "_write": (dest, new_text)})

    # ② settings.json 登记
    cfg = target / PI_SETTINGS_REL
    if not cfg.is_file():
        out.append({"file": PI_SETTINGS_REL, "status": "skipped",
                    "detail": f"settings.json 不存在 ⇒ 未登记（扩展已就位，手加一行 {PI_EXT_ENTRY}）"})
        return out
    text = cfg.read_text(encoding="utf-8")
    if PI_EXT_ENTRY in text:
        out.append({"file": PI_SETTINGS_REL, "status": "skipped",
                    "detail": "extensions 已含 atlas 扩展"})
        return out
    m = RE_EXT_ARRAY.search(text)
    if not m:
        out.append({"file": PI_SETTINGS_REL, "status": "skipped",
                    "detail": f"无 extensions 数组 ⇒ 不猜结构（手加 \"extensions\": [\"{PI_EXT_ENTRY}\"]）"})
        return out
    # 数组非空 ⇒ 抄第一个元素的行首缩进插一行；空数组 ⇒ 用 2 空格兜底
    tail = text[m.end():]
    nM = re.match(r"(\r?\n[ \t]*)", tail)
    if nM and tail[nM.end():nM.end() + 1] not in ("]", ""):
        indent, sep = nM.group(1), nM.group(1)
        insert = f"{sep}\"{PI_EXT_ENTRY}\","
        new_text = text[:m.end()] + insert + tail
    elif tail.lstrip().startswith("]"):
        line_start = text.rfind("\n", 0, m.start())
        base = text[line_start + 1: m.start()] if line_start >= 0 else ""
        new_text = (text[:m.end()] + "\n" + base + "  " + f"\"{PI_EXT_ENTRY}\"" + "\n" + base + "]"
                    + tail.lstrip()[1:])
    else:
        out.append({"file": PI_SETTINGS_REL, "status": "skipped",
                    "detail": f"extensions 数组形态无法判读 ⇒ 未登记（手加一行 {PI_EXT_ENTRY}）"})
        return out
    try:
        json.loads(new_text)
    except json.JSONDecodeError as exc:
        out.append({"file": PI_SETTINGS_REL, "status": "error",
                    "detail": f"插入后 JSON 非法，放弃写入：{exc}"})
        return out
    out.append({"file": PI_SETTINGS_REL, "status": "applied",
                "detail": "registered atlas extension in extensions[]", "_write": (cfg, new_text)})
    return out


# ----------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=str(Path.cwd()), help="项目根目录（缺省 = 当前目录）")
    ap.add_argument("--apply", action="store_true", help="真正写入；缺省为 dry-run（安全默认）")
    ap.add_argument("--dry-run", action="store_true", help="显式 dry-run（与缺省等价）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    write = bool(args.apply) and not bool(args.dry_run)
    target = Path(args.target).resolve()

    results = [wire_agents(target), wire_config(target), wire_python_scaffold(target),
               wire_gitignore(target)]
    results += wire_pi_extension(target)
    errors = sum(1 for r in results if r["status"] == "error")

    if write:
        for r in results:
            if r["status"] == "applied" and "_write" in r:
                p, t = r["_write"]
                p.parent.mkdir(parents=True, exist_ok=True)  # `.pi/extensions/atlas/` 这类新目录
                p.write_text(t, encoding="utf-8")
            elif r["status"] == "removed" and "_remove" in r:
                r["_remove"].unlink(missing_ok=True)

    for r in results:
        r.pop("_write", None)
        r.pop("_remove", None)

    applied = sum(1 for r in results if r["status"] == "applied")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    removed = sum(1 for r in results if r["status"] == "removed")

    if args.json:
        print(json.dumps({"target": str(target), "dry_run": not write,
                          "applied": applied, "skipped": skipped, "removed": removed,
                          "errors": errors,
                          "results": results}, ensure_ascii=False, indent=2))
    else:
        print(f"▶ 目标项目 : {target}")
        print(f"▶ 模式     : {'apply' if write else 'dry-run'}")
        for r in results:
            icon = {"applied": "✓", "skipped": "=", "error": "✗", "removed": "−"}.get(r["status"], "?")
            print(f"  {icon} {r['file']} — {r['detail']}")
        print(f"合计：applied={applied} skipped={skipped} removed={removed} errors={errors}")
        if not write:
            print("（dry-run：未写入任何文件；如需写入请加 --apply）")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
