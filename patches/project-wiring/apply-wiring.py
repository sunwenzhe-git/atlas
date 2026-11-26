#!/usr/bin/env python3
"""atlas 项目接线（project wiring）——把入口指针、测试配置、宿主扩展幂等写进目标项目。

用法：
    python3 apply-wiring.py --target <项目根> [--apply] [--json]

做四件事（各自独立幂等）：

  1. `<项目根>/AGENTS.md`：把 `<!-- ATLAS:START -->…<!-- ATLAS:END -->` 段**置顶注入**
     （RFC-20261126-02：文件头 = BOM + YAML front-matter（若有）之后；宿主规则窗口
     截断尾部，EOF 注入会被整段截掉——issue #77 实证 27KB 文档截尾 3235B）；
     已存在且在头部则整段按源更新（幂等）；存量尾部块在下次接线时迁移到头部
     （内容逐字节不变，仅位置）；标记不成对或多对（≠1）⇒ 报错不修改。文件不存在时创建。

  2. `<项目根>/<测试配置>`（仅 extractor 声明的栈）：由 `adapters/ac/` 的 extractor
     提供项目级配置 hook；无 hook 的栈跳过，不写任何配置。

  3. `<项目根>/.pi/`（仅 pi 宿主）：把官方扩展落到 `.pi/extensions/atlas/index.ts`，
     并在 `.pi/settings.json` 的 `extensions[]` 里幂等登记一行（2026-10-15 补）。

  4. `<项目根>/.gitignore`（仅已存在时）：幂等追加两类默认规则（2026-10-15 补）。
     `.adapter-out/`：issue #8 后 atlas 全部中间产物统一落项目根该目录（适配器输出 /
     漂移标记 / 图谱新鲜度标记），不忽略则 `git status` 常驻未跟踪噪声——**对所有接线项目成立**，
     不只图谱用户。
     `.atlas` 白名单：装配包本身是 `atlas update` 会整包刷新的镜像，不入库；项目自产的
     `.atlas/spec/`（规范）与 `.atlas/tasks/`（任务账本）必须入库。
     判据：文件**不存在 ⇒ 不首创**（跳过并在报告里给建议行）；
     内容已含 `.adapter-out` 字样 ⇒ 幂等跳过；出现 `!.adapter-out` 负模式 ⇒ 跳过；
     atlas 块已含标记 ⇒ 幂等跳过；用户已写任意 `.atlas` 规则 ⇒ 保留用户口径。
     **本触点无退役对称**：`.gitignore` 不是本项目创建的文件，
     追加后永不回收（与 extractor 配置的「逐字节相等才清」不同——追加是单向动作，
     由报告行当刻告知用户）。

设计要点：
  * 只做**外科式插入 / 替换**，不整体覆盖任何文件；标记外内容原样保留。
  * 缺省 dry-run（安全默认）；真正写入需显式 `--apply`。
  * `.pi/settings.json` 的结构判读不了就跳过（只报要手加的那一行），不猜结构。
  * **不认识的目标形态 = 跳过 + 说明**，绝不自动创建宿主目录（非 pi 项目不建 `.pi/`）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _support.layout import LayoutError, load_layout  # noqa: E402
from adapters.ac import wire_project  # noqa: E402

PKG_ROOT = Path(__file__).resolve().parent
POINTER_SNIPPET = PKG_ROOT / "agent-pointer.md"

ATLAS_START = "<!-- ATLAS:START -->"
ATLAS_END = "<!-- ATLAS:END -->"
AGENTS_REL = "AGENTS.md"


def render_pointer() -> str:
    body = POINTER_SNIPPET.read_text(encoding="utf-8").rstrip("\n")
    return f"{ATLAS_START}\n{body}\n{ATLAS_END}\n"


# --------------------------------------------------------------------- AGENTS.md

def _head_prefix(text: str) -> str:
    """文件头保留前缀：BOM + YAML front-matter（RFC-20261126-02 评审 M2/M3）。

    置顶注入的「顶」= 这段前缀之后：front-matter 必须是文件的字节序列头部才会被
    宿主解析，atlas 块不得插到它前面；BOM 同理保持在物理文件头。无 front-matter
    （首行非 `---`，或 `---` 后无闭合行）⇒ 前缀只含 BOM（若有）。
    """
    prefix = ""
    if text.startswith("\ufeff"):
        prefix = "\ufeff"
        text = text[1:]
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        for idx in range(1, len(lines)):
            if lines[idx].strip() in ("---", "..."):
                prefix += "\n".join(lines[:idx + 1]) + "\n"
                break
    return prefix


def wire_agents(target: Path) -> dict:
    path = target / AGENTS_REL
    block = render_pointer()

    if not path.exists():
        return {
            "file": AGENTS_REL, "status": "applied", "detail": "created",
            "_write": (path, block),
        }

    text = path.read_text(encoding="utf-8")
    start_count = text.count(ATLAS_START)
    end_count = text.count(ATLAS_END)
    if (start_count, end_count) not in ((0, 0), (1, 1)):
        if start_count == 0 or end_count == 0:
            detail = (f"标记不成对（{ATLAS_START if start_count else ATLAS_END} 单侧存在），不修改")
        else:
            detail = (f"标记多对（START×{start_count} / END×{end_count}，"
                      "疑似内容粘贴复读了标记），不修改——请人工清理后重跑")
        return {"file": AGENTS_REL, "status": "error", "detail": detail}

    head = _head_prefix(text)
    body = text[len(head):]
    if start_count == 0:
        # 无块：头部前置注入（用户内容原样保留，RFC-20261126-02）
        new_text = head + block + body
        detail = "applied (injected at head)"
    else:
        i = body.index(ATLAS_START)
        j = body.index(ATLAS_END) + len(ATLAS_END)
        if body[j:j + 2] == "\r\n":
            j += 2
        elif body[j:j + 1] == "\n":
            j += 1
        if i == 0:
            # 块已在头部：原位整段替换（幂等路径）
            new_text = head + block + body[j:]
            detail = "updated (block replaced at head)"
        else:
            # 存量块不在头部（EOF 等）：原位摘除 + 头部前置，幂等收敛到置顶
            #（标记外内容原样保留；RFC-20261126-02）
            new_text = head + block + body[:i] + body[j:]
            detail = "relocated to head"

    if new_text == text:
        return {"file": AGENTS_REL, "status": "skipped", "detail": "already current"}
    return {"file": AGENTS_REL, "status": "applied", "detail": detail, "_write": (path, new_text)}


# ----------------------------------------------------------------- .gitignore 兜底（2026-10-15 补，第 4 个触点）

GITIGNORE_REL = ".gitignore"
ADAPTER_OUT_ENTRY = ".adapter-out/\n"
ADAPTER_OUT_KEY = ".adapter-out"

# atlas 装配包默认忽略口径：引擎镜像不入库，项目产出（规范 + 任务账本）入库。
ATLAS_IGNORE_MARKER = "# atlas：装配包不入库"
ATLAS_IGNORE_BLOCK = (
    ATLAS_IGNORE_MARKER + "；规范与任务账本入库（install.py 幂等维护）\n"
    ".atlas/*\n"
    "!.atlas/tasks/\n"
    "!.atlas/spec/\n"
)
ATLAS_RULE_RE = re.compile(r"^\s*!?\.atlas(?:/|\*|\s|$)", re.M)


def wire_gitignore(target: Path) -> dict:
    """`.gitignore` 幂等追加两类默认规则：`.adapter-out/` 与 `.atlas` 白名单。

    `.adapter-out/`：issue #8 后所有接线项目都需要（适配器输出 / 漂移标记），
    不忽略则 `git status` 常驻未跟踪噪声。
    `.atlas` 块：装配包是整包镜像（`atlas update` 刷新），不入库；项目自产的
    `.atlas/spec/`（规范）与 `.atlas/tasks/`（任务账本）必须入库。

    判据（缺失即跳过并显式说明，不猜）：
      * 文件**不存在 ⇒ 不首创**——根 `.gitignore` 是用户自有文件，本脚手不替用户从零创建，
        只在报告里给出建议行；
      * `.adapter-out` 已含子串 ⇒ 幂等跳过；出现 `!.adapter-out` 负模式 ⇒ 跳过，不打架；
      * atlas 块已含标记 ⇒ 幂等跳过；用户已写任意 `.atlas` 规则 ⇒ 保留用户口径，跳过该块。
    """
    path = target / GITIGNORE_REL
    if not path.is_file():
        return {"file": GITIGNORE_REL, "status": "skipped",
                "detail": (f"无 {GITIGNORE_REL} ⇒ 不首创（建议手动加 "
                           f"`.adapter-out/`、`.atlas/*`、`!.atlas/tasks/`、`!.atlas/spec/`）")}
    text = path.read_text(encoding="utf-8")
    additions: list[str] = []
    labels: list[str] = []
    notes: list[str] = []

    if "!" + ADAPTER_OUT_KEY in text:
        notes.append("存在 !.adapter-out 负模式 ⇒ 不与用户既有规则打架")
    elif ADAPTER_OUT_KEY in text:
        notes.append("已忽略 .adapter-out")
    else:
        additions.append(ADAPTER_OUT_ENTRY)
        labels.append(".adapter-out/")

    if ATLAS_IGNORE_MARKER in text:
        notes.append("已含 atlas 忽略块")
    elif ATLAS_RULE_RE.search(text):
        notes.append("已有 .atlas 规则 ⇒ 保留用户口径")
    else:
        additions.append(ATLAS_IGNORE_BLOCK)
        labels.append(".atlas 白名单")

    if not additions:
        return {"file": GITIGNORE_REL, "status": "skipped", "detail": "；".join(notes)}
    new_text = (text if text.endswith("\n") else text + "\n") + "".join(additions)
    return {"file": GITIGNORE_REL, "status": "applied",
            "detail": "；".join(notes + ["appended " + " + ".join(labels)]),
            "_write": (path, new_text)}


# ----------------------------------------------------------------- pi 宿主扩展（2026-10-15 补，第 3 个触点）

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
    try:
        load_layout(target)
    except LayoutError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2

    results = [wire_agents(target), wire_project(target), wire_gitignore(target)]
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
