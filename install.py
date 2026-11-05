#!/usr/bin/env python3
"""atlas installer —— 把 atlas 包装配到目标项目（RFC-20261103-04 第 4 步）。

用法：
  bash install.sh [--target <项目根>] [--update] [--force] [--dry-run] [--no-skill] [--no-patch] [--no-wiring]
                  [--no-trellis] [--assets-root <dir>] [--adr-dir <dir>]
（install.sh 已退化为薄 wrapper，本文件是装配单源；`python3 install.py` 等价。）

装配行为：
  1. 整包装配到 <目标>/.atlas/（shared / rings / apply / templates / adapters /
     validators / patches / tests / _support / extensions）。.atlas/ 属包产物：白名单子目录默认刷新，
     `.atlas/runs/`（运行态：E2E 汇总 / check 事件 / write-claims）保留不删。
  2. 每个 skills/atlas-*/ 以一个瘦桩 SKILL.md 装到各平台 skill 目录。
  3. 清理历史遗留的单入口 skill（<平台>/skills/atlas）。
  4. 建资产根骨架（默认 product/；已有内容永不覆盖）。
  5. 应用 .trellis/workflow.md 的 Plan 挂载补丁（atlas apply；锚点幂等，
     用 --no-patch 跳过）。
  6. 项目接线：AGENTS.md 的 atlas 指针段 + .trellis/config.yaml 的 after_archive
     hook（幂等，用 --no-wiring 跳过）。
     第 5、6 步属 global-rules §7 确认门动作，由本次显式安装触发。

模式：
  --update: 刷新已有项目的 .atlas/ 资产与平台 Skills 瘦桩（要求目标已初始化 .atlas/）。
  --assets-root / --adr-dir: 首次安装选择项目级资产根（默认 product/）与可选 ADR 根；
     写入项目根 atlas.config.yaml（git 跟踪）。--update 只读配置，不重新选择。
  --update 的触点守卫：已跟踪触点存在未提交改动 ⇒ 拒（--force 越过）；触点整目录
  未跟踪（如 .atlas/ 不入库）⇒ WARN 放行、不消费 --force（覆盖自负，先回灌更稳）。

幂等：.atlas/ 与 skill 瘦桩默认刷新（属包下发物，用 --no-skill 跳过 skill）；
      资产根下的既有内容永不覆盖；workflow.md 补丁只做锚点插入、重跑即恢复；
      AGENTS.md 指针段与 config.yaml hook 就地更新、重跑即恢复。

移植口径：编排逻辑与 install.sh 逐段 1:1，**面向用户的输出逐字节保留**
（golden 基线 = `proposals/RFC-20261103-04-installer-golden/`，验收口令
`harness.py --check --installer install.py` 必须全绿）。叶子脚本
（`_support/layout.py` / `patches/*/apply-patches.py` / `scripts/pkg_digest.py` /
`scripts/ablation.py`）继续复用，不是第二实现。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Windows 控制台缺省 GBK/cp936：装配输出是中文，非 UTF-8 locale 下 PIPE 捕获会
# UnicodeEncodeError（RFC-20261103-04 评审 P1-2）。3.7+ 可 reconfigure。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 —— 老解释器/非常规流兜底
        pass

# 子进程叶子直接写 fd1，Python 侧 print 是块缓冲 ⇒ 不关字节码缓存还会有两个错位源：
# ① 子进程输出抢在宿主 print 之前（line_buffering 解决）；② 包内 __pycache__ 被 cp 进目标
# （dont_write_bytecode 解决；快照侧也剔除 __pycache__ 双保险）。
sys.dont_write_bytecode = True

PKG = Path(__file__).resolve().parent

TARGET = ""
IS_UPDATE = False
FORCE = False
DRY_RUN = False
INSTALL_SKILL = True
INSTALL_PATCH = True
INSTALL_WIRING = True
NO_TRELLIS = False
ASSETS_ROOT_ARG = ""
ADR_DIR_ARG = ""

FAIL = 0


def say(*parts: str) -> None:
    print(" ".join(parts))


def die(code: int) -> None:
    sys.exit(code)


def run(desc: str, action=None) -> None:
    """bash run() 的对位：干跑只打印命令形态，真跑执行；失败按 set -e 语义退出 1。"""
    if DRY_RUN:
        say("  [dry-run] " + desc)
        return
    if action is not None:
        try:
            action()
        except OSError as exc:
            print(f"  [FAIL] {desc}: {exc}", file=sys.stderr)
            die(1)


def rm_rf(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def cp_r(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def cp_f(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def mkdir_p(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def py_env() -> dict:
    """叶子脚本的子进程环境：注入 PYTHONUTF8=1（评审 P1-2，非 UTF-8 locale 防 UnicodeEncodeError）。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    return env


def run_py(script_args: list[str], *, capture: bool = False, discard_out: bool = False):
    """跑一个包内 Python 叶子；capture=捕获 stdout（stderr 透传），discard_out=丢弃 stdout。"""
    return subprocess.run(
        [sys.executable, *script_args],
        env=py_env(),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else (subprocess.DEVNULL if discard_out else None),
    )


def compute_src_digest(src: Path) -> str:
    """源包装配集摘要（F55 双摘要用；算法单点 = scripts/pkg_digest.py）。

    bash 版经 python3 heredoc 调用、失败输出空；这里同语义（摘要不可核 ⇒ 调用侧说清）。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "pkg_digest_golden", src / "scripts" / "pkg_digest.py")
    if spec is None or spec.loader is None:
        return ""
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        return mod.digest(src)
    except Exception:  # noqa: BLE001 —— python 缺席同族的失败面（EmptyAssembly / 缺文件）
        return ""


# ---------------------------------------------------------------- 前置检查

LAYOUT_KEYS_UPDATE = ["stack_profile", "prd", "e2e", "e2e_cases", "e2e_scripts",
                      "e2e_index", "e2e_reviews", "console_ledger"]


def layout_print(key: str) -> str:
    r = run_py([str(PKG / "_support" / "layout.py"), "--root", TARGET, "--print", key],
               capture=True)
    if r.returncode != 0:
        die(2)
    return (r.stdout or "").strip()


def layout_validate_quiet() -> bool:
    r = run_py([str(PKG / "_support" / "layout.py"), "--root", TARGET, "--validate"],
               discard_out=True)
    return r.returncode == 0


def layout_validate_visible() -> None:
    run_py([str(PKG / "_support" / "layout.py"), "--root", TARGET, "--validate"])


def apply_patch_pkg(pkg_dir: Path) -> None:
    name = pkg_dir.name
    if DRY_RUN:
        run(f"python3 {pkg_dir / 'apply-patches.py'} --target {TARGET} "
            f"--spec {pkg_dir / 'spec.json'}")
        return
    r = subprocess.run(
        [sys.executable, str(pkg_dir / "apply-patches.py"),
         "--target", TARGET, "--spec", str(pkg_dir / "spec.json"), "--apply"],
        env=py_env(), text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    out = r.stdout or ""
    for line in out.splitlines() if out else [""]:
        say("      | " + line)
    if r.returncode == 0:
        m = re.search("合计：.*", out)
        summary = m.group(0) if m else ""
        if "applied=0 replaced=0 upgraded=0" in summary:
            say(f"      = {name}：.trellis/workflow.md 已是最新（无改动；{summary}）")
        else:
            say(f"      -> .trellis/workflow.md（{name}；{summary}）")
    else:
        say(f"      ⚠ {name} 存在 error（锚点未命中，Trellis 模板可能已变）——不阻断装配。")


def check(label: str, path: str) -> None:
    global FAIL
    if DRY_RUN:
        say(f"  [dry-run] check {label}")
        return
    if os.path.exists(path):
        say(f"  [OK]   {label}")
    else:
        say(f"  [FAIL] {label} ({path})")
        FAIL = 1


def main() -> None:
    global TARGET, IS_UPDATE, FORCE, DRY_RUN, INSTALL_SKILL, INSTALL_PATCH, INSTALL_WIRING
    global NO_TRELLIS, ASSETS_ROOT_ARG, ADR_DIR_ARG, FAIL

    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--target":
            TARGET = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2
        elif a == "--update":
            IS_UPDATE = True
            i += 1
        elif a == "--force":
            FORCE = True
            i += 1
        elif a == "--dry-run":
            DRY_RUN = True
            i += 1
        elif a == "--no-skill":
            INSTALL_SKILL = False
            i += 1
        elif a == "--no-patch":
            INSTALL_PATCH = False
            i += 1
        elif a == "--no-wiring":
            INSTALL_WIRING = False
            i += 1
        elif a == "--no-trellis":
            NO_TRELLIS = True
            i += 1
        elif a == "--assets-root":
            ASSETS_ROOT_ARG = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2
        elif a == "--adr-dir":
            ADR_DIR_ARG = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2
        elif a in ("-h", "--help"):
            print(__doc__.rstrip())
            return
        else:
            print(f"未知参数: {a}", file=sys.stderr)
            die(2)

    if not TARGET:
        TARGET = os.getcwd()
    TARGET = os.path.abspath(TARGET)

    SCRIPT_DIR = str(PKG)

    # 当前源包内容摘要（F55 守卫双摘要可见化用）。
    def src_digest() -> str:
        return compute_src_digest(PKG)

    if IS_UPDATE:
        say("atlas updater (刷新工程线束)")
    else:
        say("atlas installer")
    say(f"  包目录 : {SCRIPT_DIR}")
    say(f"  目标项目: {TARGET}")
    say("")

    if IS_UPDATE and not os.path.isdir(os.path.join(TARGET, ".atlas")):
        say(f"错误：目标项目尚未装配 atlas（{TARGET}/.atlas 不存在），无法执行 update。")
        say("      如需首次装配，请执行: atlas init")
        die(1)

    if NO_TRELLIS:
        say("提示：--no-trellis：跳过 Trellis 初始化与 .trellis 骨架。")
    else:
        if not os.path.isdir(os.path.join(TARGET, ".trellis")):
            if shutil.which("trellis"):
                if DRY_RUN:
                    # F54 补洞（2026-11-03）：干跑零落盘——trellis init 会写 .trellis/，跳过。
                    say("提示：目标项目尚未初始化 Trellis（--dry-run：跳过 trellis init，不落盘）。")
                else:
                    say("提示：目标项目尚未初始化 Trellis，尝试自动执行 trellis init...")
                    subprocess.run(["trellis", "init"], cwd=TARGET, check=False)
        if not os.path.isdir(os.path.join(TARGET, ".trellis")):
            say("警告：目标项目没有 .trellis/（未初始化 Trellis）。")
            say("      atlas 的需求级衔接依赖 Trellis，请先在目标项目执行 trellis init。")
            say("      （如果未安装，请执行: npm i -g @mindfoldhq/trellis）")
            if not FORCE:
                say("      如确认要继续，请加 --force。")
                die(1)

    # ── 临时守卫（2026-09-28 加；副本先改、源包后回灌的分歧窗口防 rm -rf 卷走）──
    if (not DRY_RUN and os.path.isdir(os.path.join(TARGET, ".atlas"))
            and os.environ.get("ATLAS_ALLOW_OVERWRITE", "0") != "1" and not IS_UPDATE):
        say(f"错误：目标已装配过 atlas（{TARGET}/.atlas 存在），本次运行会整包覆盖。")
        say("      副本侧可能有未回灌的本地改动（见目标项目 ATLAS-UPSTREAM.md）；覆盖会回退副本侧已落地改动。")
        say("      - 明知回退、仍要覆盖：ATLAS_ALLOW_OVERWRITE=1 重新运行")
        say("      - 给新项目开户：换一个没有 .atlas/ 的 --target")
        say("      - 只想预览改动：加 --dry-run")
        die(1)

    # ── 触点脏树守卫（F34 / F55 两语义）──
    if IS_UPDATE and not DRY_RUN and shutil.which("git"):
        git_dir = subprocess.run(
            ["git", "-C", TARGET, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True,
        )
        if git_dir.returncode == 0:
            dirty_touch = ""
            untracked_touch = ""
            st = subprocess.run(["git", "-C", TARGET, "status", "--porcelain"],
                                capture_output=True, text=True, errors="replace")
            for raw in (st.stdout or "").splitlines():
                if not raw:
                    continue
                raw_path = raw[3:]
                if not (raw_path == ".atlas" or raw_path.startswith(".atlas/")
                        or raw_path in (".trellis/workflow.md", ".trellis/config.yaml", "AGENTS.md")):
                    continue
                if raw[:2] == "??":
                    untracked_touch += f" {raw_path}"
                else:
                    dirty_touch += f" {raw_path}"
            if dirty_touch:
                if FORCE:
                    say(f"（--force：感知到装配触点未提交改动：{dirty_touch} —— 整包覆盖自负）")
                    if untracked_touch:
                        say(f"（另有未跟踪项：{untracked_touch} —— git 对其无改动基线，覆盖自负）")
                else:
                    say(f"错误：装配触点存在未提交改动（{dirty_touch}）；--update 的整包覆盖会冲掉")
                    say("      副本侧未回灌的线束改动（含 .atlas/ 与指针文件）。")
                    say("      - 先提交或 stash 后重跑")
                    say("      - 明知覆盖、仍要继续：加 --force")
                    die(1)
            elif untracked_touch:
                copy_stamp = ""
                version_file = os.path.join(TARGET, ".atlas", "VERSION")
                if os.path.isfile(version_file):
                    with open(version_file, encoding="utf-8", errors="replace") as fh:
                        copy_stamp = fh.readline().rstrip("\n")
                src = src_digest()
                say(f"  [WARN] 装配触点存在未跟踪项：{untracked_touch}——git 对未跟踪触点无改动基线可保护，")
                if copy_stamp and src:
                    if copy_stamp == src:
                        say(f"         本副本与当前源包一致（{copy_stamp}，无年轮差）；整包刷新照常进行。")
                    else:
                        say(f"         本副本（{copy_stamp}）与当前源包（{src}）不一致——覆盖自负。")
                else:
                    say("         摘要不可核（副本无 .atlas/VERSION 或源包摘要不可算）——覆盖自负。")
                say("         副本侧若有未回灌的本地改动，覆盖即丢失：先按 ATLAS-UPSTREAM.md 回灌")
                say("         （scripts/backflow.py 三态对账）再刷新更稳。")

    # 探测目标项目实际使用的平台目录
    platform_dirs: list[str] = []
    for probe, rel in ((".agents/skills", ".agents/skills"),
                       (".claude/skills", ".claude/skills"),
                       (".codex", ".codex/skills")):
        if os.path.isdir(os.path.join(TARGET, probe)):
            platform_dirs.append(rel)
    if not platform_dirs:
        say("警告：未探测到任何平台 skill 目录，默认创建 .agents/skills/。")
        platform_dirs = [".agents/skills"]

    # ---------------------------------------------------------------- 布局配置

    config_file = os.path.join(TARGET, "atlas.config.yaml")
    layout_py = os.path.join(SCRIPT_DIR, "_support", "layout.py")
    if not os.path.isfile(layout_py):
        say("错误：源包缺少 _support/layout.py，无法解析项目级资产根。")
        die(1)

    assets_root = ""
    adr_dir_rel = ""

    if IS_UPDATE:
        if not layout_validate_quiet():
            say(f"错误：布局配置非法（{config_file}）；先修正再 update。")
            layout_validate_visible()
            die(2)
        assets_root = layout_print("assets_root")
        adr_dir_rel = layout_print("adr")
        if ASSETS_ROOT_ARG and ASSETS_ROOT_ARG != assets_root:
            say(f"错误：--assets-root={ASSETS_ROOT_ARG} 与现有配置（{assets_root}）不一致；update 不换根。")
            die(2)
        if ADR_DIR_ARG and ADR_DIR_ARG != adr_dir_rel:
            say(f"错误：--adr-dir={ADR_DIR_ARG} 与现有配置（{adr_dir_rel}）不一致；update 不换根。")
            die(2)
    elif os.path.isfile(config_file):
        if not layout_validate_quiet():
            say(f"错误：布局配置非法（{config_file}）。")
            layout_validate_visible()
            die(2)
        assets_root = layout_print("assets_root")
        adr_dir_rel = layout_print("adr")
        if ASSETS_ROOT_ARG and ASSETS_ROOT_ARG != assets_root:
            say(f"错误：--assets-root={ASSETS_ROOT_ARG} 与现有配置（{assets_root}）不一致。")
            die(2)
        if ADR_DIR_ARG and ADR_DIR_ARG != adr_dir_rel:
            say(f"错误：--adr-dir={ADR_DIR_ARG} 与现有配置（{adr_dir_rel}）不一致。")
            die(2)
    else:
        new_assets_root = ASSETS_ROOT_ARG or "product"
        new_adr_dir = ADR_DIR_ARG
        r = run_py([layout_py, "--root", TARGET, "--validate-value",
                    "assets_root", new_assets_root])
        if r.returncode != 0:
            die(2)
        if new_adr_dir:
            r = run_py([layout_py, "--root", TARGET, "--validate-value", "adr", new_adr_dir])
            if r.returncode != 0:
                die(2)
        if new_assets_root != "product":
            for p in ("stack-profile.yaml", "prd", "e2e", "adr",
                      "design.md", "reviews", "atlas-reports"):
                if os.path.exists(os.path.join(TARGET, "product", p)):
                    say(f"错误：所选资产根 {new_assets_root} 不是默认 product，但 product/{p} 已存在（双根风险）。")
                    say(f"      先手工迁移既有资产到 {new_assets_root}/，或明确改用 --assets-root product。")
                    die(2)
        if DRY_RUN:
            say(f"      [dry-run] + atlas.config.yaml（assets_root: {new_assets_root}）")
            if new_adr_dir:
                say(f"                      adr: {new_adr_dir}")
            assets_root = new_assets_root
            adr_dir_rel = new_adr_dir or f"{assets_root}/adr"
        else:
            write_args = ["--root", TARGET, "--write", "--assets-root", new_assets_root]
            if new_adr_dir:
                write_args += ["--adr", new_adr_dir]
            r = run_py([layout_py, *write_args], discard_out=True)
            if r.returncode != 0:
                die(2)
            say(f"      + atlas.config.yaml（assets_root: {new_assets_root}）")
            if new_adr_dir:
                say(f"                      adr: {new_adr_dir}")
            assets_root = layout_print("assets_root")
            adr_dir_rel = layout_print("adr")

    rels: dict[str, str] = {}
    if (not IS_UPDATE and os.path.isfile(config_file)) or IS_UPDATE:
        for key in LAYOUT_KEYS_UPDATE:
            rels[key] = layout_print(key)

    stack_profile_rel = rels.get("stack_profile", f"{assets_root}/stack-profile.yaml")
    e2e_cases_rel = rels.get("e2e_cases", f"{assets_root}/e2e/cases")

    stack_profile = os.path.join(TARGET, stack_profile_rel)
    e2e_cases_dir = os.path.join(TARGET, e2e_cases_rel)
    say(f"  资产根   : {assets_root}")
    say(f"  ADR 根   : {adr_dir_rel}")
    say("")

    # P3-b：active 消融期间拒绝 --update 覆盖 .atlas/（--force + ATLAS_ALLOW_ABLATION_OVERWRITE=1 越过）
    if IS_UPDATE:
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "scripts", "ablation.py"),
             "status", "--root", TARGET, "--exit-active", "--quiet"],
            env=py_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if (r.returncode == 10
                and (not FORCE or os.environ.get("ATLAS_ALLOW_ABLATION_OVERWRITE", "0") != "1")):
            say("错误：目标存在未关闭的消融事务（ablation active）；先运行 ablation restore；")
            say("      确需覆盖：--force + ATLAS_ALLOW_ABLATION_OVERWRITE=1（会放弃消融现场）。")
            die(2)

    # ---------------------------------------------------------------- 1. 整包 → .atlas/

    say("[1/6] 装配 atlas 包到 .atlas/")
    atlas_dest = os.path.join(TARGET, ".atlas")
    pkg_dirs = ["shared", "rings", "apply", "scripts", "templates",
                "adapters", "validators", "patches", "tests", "_support", "extensions"]
    for d in pkg_dirs:
        run(f"rm -rf {atlas_dest}/{d}",
            action=lambda d=d: rm_rf(Path(atlas_dest) / d))
    run(f"rm -f {atlas_dest}/LICENSE",
        action=lambda: Path(atlas_dest, "LICENSE").unlink(missing_ok=True))
    run(f"mkdir -p {atlas_dest}", action=lambda: mkdir_p(Path(atlas_dest)))
    for d in pkg_dirs:
        if os.path.isdir(os.path.join(SCRIPT_DIR, d)):
            run(f"cp -R {SCRIPT_DIR}/{d} {atlas_dest}/{d}",
                action=lambda d=d: cp_r(Path(SCRIPT_DIR) / d, Path(atlas_dest) / d))
            say(f"      -> .atlas/{d}")

    if os.path.isfile(os.path.join(SCRIPT_DIR, "LICENSE")):
        run(f"cp {SCRIPT_DIR}/LICENSE {atlas_dest}/LICENSE",
            action=lambda: cp_f(Path(SCRIPT_DIR, "LICENSE"), Path(atlas_dest, "LICENSE")))

    # ---------------------------------------------------------------- 2/3. skill 瘦桩与清理

    if INSTALL_SKILL:
        say("[2/6] 装配 skill 瘦桩")
        skill_srcs = sorted((PKG / "skills").iterdir()) if (PKG / "skills").is_dir() else []
        if not skill_srcs:
            say("      未发现 skills/*，跳过。")
        else:
            for skill_src in skill_srcs:
                if not skill_src.is_dir():
                    continue
                name = skill_src.name
                for rel in platform_dirs:
                    dest = os.path.join(TARGET, rel, name)
                    run(f"rm -rf {dest}", action=lambda dest=dest: rm_rf(Path(dest)))
                    run(f"mkdir -p {TARGET}/{rel}",
                        action=lambda rel=rel: mkdir_p(Path(TARGET) / rel))
                    run(f"cp -R {skill_src} {dest}",
                        action=lambda s=skill_src, d=dest: cp_r(s, Path(d)))
                say(f"      -> {name}（{len(platform_dirs)} 个平台）")

        say("[3/6] 清理历史与退役 skill")
        for rel in platform_dirs:
            legacy = Path(TARGET) / rel / "atlas"
            if legacy.exists():
                run(f"rm -rf {legacy}", action=lambda l=legacy: rm_rf(l))
                say(f"      - 移除 {rel}/atlas（旧单入口）")
            for stale in sorted((Path(TARGET) / rel).glob("atlas-*")):
                if not stale.is_dir():
                    continue
                stale_name = stale.name
                if not os.path.isdir(os.path.join(SCRIPT_DIR, "skills", stale_name)):
                    run(f"rm -rf {stale}", action=lambda s=stale: rm_rf(s))
                    say(f"      - 移除 {rel}/{stale_name}（源包已无此 skill）")

        # agent 配置（如 atlas-reviewer）
        if os.path.isdir(os.path.join(SCRIPT_DIR, "agents")):
            for agent_src in sorted((PKG / "agents").glob("*.md")):
                if not agent_src.is_file():
                    continue
                agent_name = agent_src.name
                for agent_base in (".agents", ".claude/agents", ".codex/agents"):
                    if agent_base == ".agents" or os.path.isdir(
                            os.path.join(TARGET, os.path.dirname(agent_base))):
                        run(f"mkdir -p {TARGET}/{agent_base}",
                            action=lambda b=agent_base: mkdir_p(Path(TARGET) / b))
                        run(f"cp {agent_src} {TARGET}/{agent_base}/{agent_name}",
                            action=lambda s=agent_src, b=agent_base, n=agent_name:
                            cp_f(s, Path(TARGET) / b / n))
                say(f"      -> agent {agent_name}")
    else:
        say("[2/6] 跳过 skill（--no-skill）")
        say("[3/6] 跳过 skill 清理（--no-skill）")

    # ---------------------------------------------------------------- 4. 骨架

    say("[4/6] 建立骨架")
    skeleton = [
        e2e_cases_rel,
        ".trellis/spec/structure/domains",
        ".trellis/spec/structure/global",
    ]
    if NO_TRELLIS:
        skeleton = [d for d in skeleton if not d.startswith(".trellis/")]
    for d in skeleton:
        run(f"mkdir -p {TARGET}/{d}", action=lambda d=d: mkdir_p(Path(TARGET) / d))
        gitkeep = os.path.join(TARGET, d, ".gitkeep")
        if not os.path.isfile(gitkeep):
            run(f"touch {gitkeep}", action=lambda g=gitkeep: Path(g).touch())

    if os.path.isfile(stack_profile):
        say(f"      = {stack_profile_rel} 已存在，保留")
    elif DRY_RUN:
        say(f"      [dry-run] + {stack_profile_rel}（由模板按资产根渲染）")
    else:
        mkdir_p(Path(stack_profile).parent)
        r = subprocess.run(
            [sys.executable, "-",
             os.path.join(SCRIPT_DIR, "templates", "stack-profile.yaml"),
             stack_profile, assets_root],
            env=py_env(), text=True, encoding="utf-8", input=(
                "import sys\n"
                "src, dst, assets_root = sys.argv[1], sys.argv[2], sys.argv[3]\n"
                "text = open(src, encoding=\"utf-8\").read().replace(\"{{ASSETS_ROOT}}\", assets_root)\n"
                "open(dst, \"w\", encoding=\"utf-8\", newline=\"\").write(text)\n"
            ),
        )
        if r.returncode != 0:
            die(r.returncode or 1)
        say(f"      + {stack_profile_rel}（草稿，需人工确认）")

    # ---------------------------------------------------------------- 5. Trellis workflow 补丁

    if INSTALL_PATCH:
        say("[5/6] 应用 Trellis workflow 补丁（patches/*/）")
        found_any = False
        # bash 原样：恒迭代 `$ATLAS_DEST/patches/*/spec.json`。dry-run 首装时 dest 未拷贝
        # ⇒ glob 为空 ⇒ 「未发现…跳过」（与基线一致）；update 干跑时 dest 有上次拷贝
        # ⇒ 命中后回退源包目录，使补丁计划照样可见。
        for spec in sorted(Path(atlas_dest).glob("patches/*/spec.json")):
            pkg_dir = spec.parent
            if not (pkg_dir / "apply-patches.py").is_file():
                continue
            if DRY_RUN and (PKG / "patches" / pkg_dir.name / "apply-patches.py").is_file():
                pkg_dir = PKG / "patches" / pkg_dir.name
            found_any = True
            apply_patch_pkg(pkg_dir)
        if not found_any:
            say("      未发现含 apply-patches.py 的补丁包，跳过。")
    else:
        say("[5/6] 跳过 workflow 补丁（--no-patch）")

    # ---------------------------------------------------------------- 6. 项目接线

    wiring_dir = os.path.join(atlas_dest, "patches", "project-wiring")
    if (not os.path.isfile(os.path.join(wiring_dir, "apply-wiring.py"))
            and os.path.isfile(os.path.join(SCRIPT_DIR, "patches", "project-wiring",
                                            "apply-wiring.py"))):
        wiring_dir = os.path.join(SCRIPT_DIR, "patches", "project-wiring")
    if INSTALL_WIRING:
        say("[6/6] 项目接线（AGENTS.md 指针 + after_archive hook）")
        if os.path.isfile(os.path.join(wiring_dir, "apply-wiring.py")):
            if DRY_RUN:
                run(f"python3 {wiring_dir}/apply-wiring.py --target {TARGET}")
            else:
                r = subprocess.run(
                    [sys.executable, os.path.join(wiring_dir, "apply-wiring.py"),
                     "--target", TARGET, "--apply"],
                    env=py_env(),
                )
                if r.returncode == 0:
                    say("      -> AGENTS.md（atlas 指针段）+ .trellis/config.yaml"
                        "（after_archive hook + session_auto_commit: false）")
                else:
                    say("      ⚠ 接线存在 error——不阻断装配（见上）。")
        else:
            say("      未发现 patches/project-wiring/apply-wiring.py，跳过。")
    else:
        say("[6/6] 跳过项目接线（--no-wiring）")

    # ---------------------------------------------------------------- 图谱后端探测（可选能力）

    if os.path.isfile(stack_profile) and not DRY_RUN:
        graph_backend = ""
        section = None
        with open(stack_profile, encoding="utf-8") as fh:
            for raw in fh:
                line = re.sub(r"\s+#.*$", "", raw.rstrip())
                s = line.strip()
                if not s:
                    continue
                if not line[:1].isspace():
                    section = s[:-1].strip() if s.endswith(":") else None
                elif section == "graph":
                    m = re.match(r"^\s*backend:\s*(\S+)", line)
                    if m:
                        graph_backend = m.group(1).strip("'\"")
        if graph_backend:
            say("")
            say(f"图谱后端探测（profile 声明 backend={graph_backend}）")
            if graph_backend != "cgc":
                say(f"  [WARN] 未知后端 {graph_backend}（允许：cgc）——图谱消费者将显式报错")
            elif shutil.which("cgc"):
                v = subprocess.run(["cgc", "--version"], capture_output=True, text=True,
                                   errors="replace")
                last = (v.stdout or "").strip().splitlines() or (v.stderr or "").strip().splitlines()
                say(f"  [OK]   cgc 可用（{last[-1] if last else ''}）")
                say("      首次消费前如卡在索引，先做一次文法缓存预热（GitHub 资产直连不通时挂代理）：")
                say("      https_proxy=http://127.0.0.1:7897 python3 -c \"from tree_sitter_language_pack "
                    "import download; download(['python','typescript','javascript','tsx','bash','java'])\"")
            else:
                say("  [WARN] cgc 未安装——图谱消费者将显式 not_ready / 降级（pipx/uv tool install codegraphcontext）")

    # ---------------------------------------------------------------- 自检

    say("")
    say("自检")

    def c(label: str, path: str) -> None:
        check(label, path)

    c("共享契约", f"{atlas_dest}/shared/global-rules.md")
    c("stack-profile 契约", f"{atlas_dest}/shared/stack-profile.md")
    c("单一真相源契约", f"{atlas_dest}/shared/single-source.md")
    c("布局契约", f"{atlas_dest}/shared/layout.md")
    c("门登记表", f"{atlas_dest}/shared/gates.md")
    c("收口清单", f"{atlas_dest}/shared/closeout.md")
    c("独立审查骨架契约", f"{atlas_dest}/shared/independent-review.md")
    c("structure 环契约", f"{atlas_dest}/rings/structure/reference.md")
    c("prd 环契约", f"{atlas_dest}/rings/prd/reference.md")
    c("e2e 环契约", f"{atlas_dest}/rings/e2e/reference.md")
    c("apply 契约", f"{atlas_dest}/apply/reference.md")
    c("workflow 补丁应用器", f"{atlas_dest}/patches/workflow-plan-apply/apply-patches.py")
    c("校验器 validate_structure", f"{atlas_dest}/validators/validate_structure.py")
    c("校验器 validate_stack_profile", f"{atlas_dest}/validators/validate_stack_profile.py")
    c("校验器 validate_prd", f"{atlas_dest}/validators/validate_prd.py")
    c("校验器 validate_testids", f"{atlas_dest}/validators/validate_testids.py")
    c("校验器 validate_e2e_index", f"{atlas_dest}/validators/validate_e2e_index.py")
    c("校验器 validate_design_exemptions", f"{atlas_dest}/validators/validate_design_exemptions.py")
    c("校验器 validate_e2e_mocks", f"{atlas_dest}/validators/validate_e2e_mocks.py")
    c("校验器 validate_ac_alignment", f"{atlas_dest}/validators/validate_ac_alignment.py")
    c("校验器 validate_adr", f"{atlas_dest}/validators/validate_adr.py")
    c("校验器 validate_walkthrough", f"{atlas_dest}/validators/validate_walkthrough.py")
    c("E2E 脚本生成器", f"{atlas_dest}/scripts/gen_e2e_scripts.py")
    c("结构事实刷新器", f"{atlas_dest}/scripts/refresh_structure.py")
    c("testid 薄桩生成器", f"{atlas_dest}/scripts/gen_testid_stub.py")
    c("审查输入清单生成器", f"{atlas_dest}/scripts/make_review_inputs.py")
    c("变异证明工具", f"{atlas_dest}/scripts/mutation_proof.py")
    c("atlas 自检器", f"{atlas_dest}/scripts/atlas_check.py")
    c("消融事务工具", f"{atlas_dest}/scripts/ablation.py")
    c("E2E 评审控制台", f"{atlas_dest}/scripts/e2e_console.py")
    c("Python 启动器（钩子平台中立）", f"{atlas_dest}/scripts/run_python.js")
    c("控制台静态资源", f"{atlas_dest}/templates/e2e/console/index.html")
    c("适配器脚手架", f"{atlas_dest}/adapters/_scaffold.py")
    c("适配器指南", f"{atlas_dest}/adapters/README.md")
    c("AC 提取器注册表", f"{atlas_dest}/adapters/ac/__init__.py")
    c("AC 提取器（pytest）", f"{atlas_dest}/adapters/ac/pytest.py")
    c("AC 提取器（Vitest/Jest）", f"{atlas_dest}/adapters/ac/js.py")
    c("AC 提取器（JUnit 5）", f"{atlas_dest}/adapters/ac/junit.py")
    c("AC 外部 extractor 运行器", f"{atlas_dest}/adapters/ac/command.py")
    c("JPA 模型解析器", f"{atlas_dest}/adapters/_jpa.py")
    c("图谱后端隔离层", f"{atlas_dest}/adapters/_graph.py")
    c("影响面基准报告器", f"{atlas_dest}/scripts/impact_report.py")
    c("回灌助手", f"{atlas_dest}/scripts/backflow.py")
    c("收口派生器", f"{atlas_dest}/scripts/closeout_derive.py")
    c("写面 claim 仲裁", f"{atlas_dest}/scripts/write_claim.py")
    c("共享内核（模块加载器）", f"{atlas_dest}/_support/siblings.py")
    c("共享内核（profile 解析）", f"{atlas_dest}/_support/stack_profile.py")
    c("共享内核（用例块解析）", f"{atlas_dest}/_support/case_block.py")
    c("共享内核（手工走查块解析）", f"{atlas_dest}/_support/manual_block.py")
    c("共享内核（用例 ID 文法）", f"{atlas_dest}/_support/case_id.py")
    c("共享内核（node 运行器判据）", f"{atlas_dest}/_support/pw_runner.py")
    c("共享内核（base query 转发）", f"{atlas_dest}/_support/url_merge.py")
    c("共享内核（审查策略单源）", f"{atlas_dest}/_support/review_policy.py")
    c("共享内核（审查范围封口）", f"{atlas_dest}/_support/review_scope_core.py")
    c("共享内核（布局解析）", f"{atlas_dest}/_support/layout.py")
    c("共享内核（证据归档）", f"{atlas_dest}/_support/evidence_archive.py")
    c("共享内核（维度解析）", f"{atlas_dest}/_support/ac_coverage.py")
    c("pi 宿主扩展", f"{atlas_dest}/extensions/pi.ts")
    c("结构模板", f"{atlas_dest}/templates/structure/_meta.json")
    c("PRD 模板", f"{atlas_dest}/templates/prd/domain.md")
    c("E2E 模板", f"{atlas_dest}/templates/e2e/e2e-index.md")
    c("ADR 模板", f"{atlas_dest}/templates/adr/template.md")
    c("审查指引模板", f"{atlas_dest}/templates/reviews/README.md")
    c("stack-profile（资产根）", stack_profile)
    if not NO_TRELLIS:
        c("structure spec 根", os.path.join(TARGET, ".trellis", "spec", "structure"))
    c("e2e 用例分片目录", e2e_cases_dir)

    if INSTALL_PATCH and not DRY_RUN and os.path.isfile(
            os.path.join(TARGET, ".trellis", "workflow.md")):
        with open(os.path.join(TARGET, ".trellis", "workflow.md"),
                  encoding="utf-8", errors="replace") as fh:
            if "atlas:apply:plan-step-1-6" in fh.read():
                say("  [OK]   Plan 挂载补丁（atlas apply）")
            else:
                say("  [WARN] Plan 挂载补丁未生效（workflow.md 锚点可能已变；见 patches/workflow-plan-apply/README.md）")

    if INSTALL_WIRING and not DRY_RUN:
        agents_md = os.path.join(TARGET, "AGENTS.md")
        agents_text = ""
        if os.path.isfile(agents_md):
            agents_text = open(agents_md, encoding="utf-8", errors="replace").read()
        if "<!-- ATLAS:START -->" in agents_text:
            say("  [OK]   AGENTS.md atlas 指针段")
        else:
            say("  [WARN] AGENTS.md atlas 指针段未生效（见 patches/project-wiring/README.md）")
        config_yaml = os.path.join(TARGET, ".trellis", "config.yaml")
        config_text = ""
        if os.path.isfile(config_yaml):
            config_text = open(config_yaml, encoding="utf-8", errors="replace").read()
        if "refresh_structure.py" in config_text:
            say("  [OK]   after_archive hook（refresh_structure）")
        else:
            say("  [WARN] after_archive hook 未生效（见 patches/project-wiring/README.md）")

    if INSTALL_SKILL and not DRY_RUN:
        first_platform = platform_dirs[0]
        for skill_src in sorted((PKG / "skills").iterdir()) if (PKG / "skills").is_dir() else []:
            if not skill_src.is_dir():
                continue
            name = skill_src.name
            entry = os.path.join(TARGET, first_platform, name, "SKILL.md")
            c(f"skill {name}", entry)
            if os.path.isfile(entry):
                with open(entry, encoding="utf-8", errors="replace") as fh:
                    if not any(ln.rstrip("\n") == f"name: {name}" for ln in fh):
                        say(f"  [FAIL] {name} SKILL.md frontmatter 的 name 与目录名不符")
                        FAIL = 1

    say("")
    if FAIL:
        say("装配失败，见上面 [FAIL]。")
        die(1)

    # P3 装配版本戳（2026-10-05）：F54 干跑闸 + RFC-20261023-02 manifest 同点落。
    if DRY_RUN:
        say("  [dry-run] 装配版本戳（未落盘：干跑不产生装配态变更）")
    else:
        sys.path.insert(0, os.path.join(SCRIPT_DIR, "scripts"))
        try:
            from pkg_digest import stamp_file  # noqa: E402
            digest = stamp_file(Path(SCRIPT_DIR), Path(atlas_dest, "VERSION"))
        except Exception:  # noqa: BLE001 —— 硬错而非 WARN（F37）：装配 0 文件不是合法装配
            say("  [FAIL] 版本戳落盘失败：装配集为空或 pkg_digest 不可用 ⇒ 装配态无法对账。")
            say(f"         诊断：python3 \"{SCRIPT_DIR}/scripts/pkg_digest.py\" \"{SCRIPT_DIR}\"")
            die(1)
        say(f"  [ok] .atlas/VERSION 装配版本戳（{digest}）")
        manifest_path = os.path.join(atlas_dest, "MANIFEST.json")
        if os.path.isfile(manifest_path) and os.path.getsize(manifest_path) > 0:
            say("  [ok] .atlas/MANIFEST.json 装配基线（逐文件摘要）")
        else:
            say("  [FAIL] 装配基线 manifest 未落下（.atlas/MANIFEST.json）⇒ 装配态无法逐文件对账。")
            die(1)

    # 首建提示（终稿口径：只留「首次开户（二选一）」段，按源码痕迹排序两条入口）
    if IS_UPDATE:
        say("刷新完成。")
        say("")
        say("项目工程线束与各平台 Skills 瘦桩已对账刷新为最新版本。")
    else:
        first_run_mark = ""
        for marker in ("package.json", "requirements.txt", "pyproject.toml", "go.mod",
                       "Cargo.toml", "pom.xml", "build.gradle", "composer.json",
                       "Gemfile", "src", "app", "pages", "frontend", "backend",
                       "web", "mobile"):
            if os.path.exists(os.path.join(TARGET, marker)):
                first_run_mark = marker
                break

        say("装配完成。")
        say("")
        say("首次开户（二选一）：")
        say("存量项目 → /atlas-apply adopt —— 只登记既有结构基线 + 开户最小集：")
        say("           不重写老 PRD、不为老页面补历史用例。")
        say("全新项目 → /atlas-apply all —— structure → prd → e2e 逐环全量。")
        if first_run_mark:
            say(f"（检测到 {first_run_mark}：看起来是前者；也可以只说「帮我把这个项目接入 Atlas 工作流」）")
        else:
            say("（未检测到既有源码：看起来是后者；也可以只说「跑一下三环全量构建，建立应然基线」）")
        say(f"Agent 会先带你核对 {stack_profile_rel}（origin / apps / role / adapters）")
        say("再落盘；占位符替换前 atlas check 判 FAIL 属预期，不是装坏了。")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except OSError as exc:
        # bash `set -e` 对位：文件系统意外失败 ⇒ 静默非零退出（cp/rm 的失败面）。
        print(f"install.py: {exc}", file=sys.stderr)
        sys.exit(1)
