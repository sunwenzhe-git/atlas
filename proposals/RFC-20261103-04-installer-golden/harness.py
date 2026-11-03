#!/usr/bin/env python3
"""装配器 golden 快照 harness（RFC-20261103-04 第 3 步）。

**必须放在装配集之外**（proposals/ 不进 `.atlas/`）：harness 自身在 `scripts/` 等
装配集目录里，加一行就会改源包摘要，把要冻结的基线自己冲掉（2026-11-03 实证）。

用途：在 `install.sh` → `install.py` 移植**之前**冻结 bash 装配器的可观察行为，
移植后用同一批场景对 `install.py` 做逐字节比对。**不是 pytest 门**，按需手动跑：

    python3 proposals/RFC-20261103-04-installer-golden/harness.py --record
                                                          # 用当前 bash 安装器录基线
    python3 proposals/RFC-20261103-04-installer-golden/harness.py --check
                                                          # 重跑 bash 并比对（确定性自检）
    python3 proposals/RFC-20261103-04-installer-golden/harness.py --check --installer install.py
                                                          # 移植后：Python 安装器对同一基线

记录内容（每个场景一个 JSON）：
  * 每次调用的参数、退出码、**归一化后**的 stdout+stderr（绝对路径/时间戳/版本号替换为占位符）；
  * 目标树快照 = 相对路径 → 内容 sha256（`.git/` 除外；`.atlas/VERSION` 的时间行与源包路径行归一化）；
  * 空目录清单（目录是否被创建本身也是可观察行为）。

goldens 放在 `proposals/RFC-20261103-04-installer-golden/`（proposals 不随包装配，
不会把快照塞进每个项目的 `.atlas/tests/`）。包内容一变（装配集文件有增删改），
基线摘要随之变化 ⇒ **常规发版后需重录**；该 harness 的窗口是移植期，不是长期 CI 门。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# harness 在 proposals/RFC-20261103-04-installer-golden/ 下，仓库根是上两级。
PKG_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLDEN = Path(__file__).resolve().parent

# 固定 PATH：git/python3 必须可解析；trellis/cgc 缺席 ⇒ 走安装器的跳过分支（确定性）。
BASE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"
ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
ISO_BYTES_RE = re.compile(rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
VER_RE = re.compile(r"v0\.2\.0-beta\.\d+")

MODIFY_PATCH = """diff --git a/a.txt b/a.txt
--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-old
+new
"""


class Ctx:
    def __init__(self, tmp: Path, installer: list[str]):
        self.tmp = tmp
        self.installer = installer
        self.pkg = PKG_ROOT
        self.root = tmp / "proj"
        self.root.mkdir(parents=True)
        self.home = tmp / "home"
        self.home.mkdir()
        self.ablation_home = tmp / "ablation"
        self.env = {
            "PATH": BASE_PATH,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
            "HOME": str(self.home),
            "TMPDIR": str(tmp),
            "ATLAS_ABLATION_HOME": str(self.ablation_home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "golden",
            "GIT_AUTHOR_EMAIL": "golden@example.invalid",
            "GIT_COMMITTER_NAME": "golden",
            "GIT_COMMITTER_EMAIL": "golden@example.invalid",
        }
        self.runs: list[dict] = []

    # ---------------------------------------------------------------- helpers
    def run(self, args: list[str], expect: int | None = None) -> subprocess.CompletedProcess:
        cmd = [*self.installer, *args]
        p = subprocess.run(
            cmd, cwd=str(self.root), env=self.env,
            capture_output=True, text=True, errors="replace",
        )
        output = normalize_text(p.stdout + p.stderr, self)
        self.runs.append({
            "args": [normalize_text(a, self) for a in args],
            "exit": p.returncode,
            "output": output.splitlines(),
        })
        if expect is not None:
            assert p.returncode == expect, (
                f"{self.root.name}: expected exit {expect}, got {p.returncode}\n{output}")
        return p

    def git(self, *args: str) -> None:
        p = subprocess.run(["git", *args], cwd=str(self.root), env=self.env,
                           capture_output=True, text=True)
        assert p.returncode == 0, p.stdout + p.stderr

    def git_init(self, add: list[str]) -> None:
        self.git("init", "-q")
        self.git("add", *add)
        self.git("commit", "-qm", "init")

    def seed_trellis(self) -> None:
        (self.root / ".trellis").mkdir(parents=True, exist_ok=True)


def normalize_text(text: str, ctx: Ctx) -> str:
    # 先长路径后短路径：root 在 tmp 内，pkg 可能是 tmp 下的副本。
    # macOS 的 TMPDIR 带 /private 前缀（bash `pwd -P` 会解析出来），两种形态都要替换。
    # 先替换最长形态（/private 前缀的 realpath），再替换短形态，避免部分替换留尾巴。
    for path, token in ((ctx.root, "<ROOT>"), (ctx.pkg, "<PKG>"), (ctx.tmp, "<TMP>")):
        for variant in dict.fromkeys([os.path.realpath(path), str(path)]):
            text = text.replace(variant, token)
    text = ISO_RE.sub("<TIMESTAMP>", text)
    text = VER_RE.sub("<VERSION>", text)
    return text


def _bytes_without_env(data: bytes, ctx: Ctx) -> bytes:
    for path, token in ((ctx.root, b"<ROOT>"), (ctx.pkg, b"<PKG>"), (ctx.tmp, b"<TMP>")):
        for variant in dict.fromkeys([os.path.realpath(path), str(path)]):
            data = data.replace(variant.encode(), token)
    return data


def snapshot(ctx: Ctx) -> dict:
    files: dict[str, str] = {}
    dirs: list[str] = []
    for p in sorted(ctx.root.rglob("*")):
        rel = p.relative_to(ctx.root).as_posix()
        if rel == ".git" or rel.startswith(".git/"):
            continue
        if "__pycache__" in rel.split("/"):
            continue  # 解释器产物，不是装配器的输出；有无取决于环境，不进快照
        if p.is_dir():
            dirs.append(rel)
            continue
        if p.is_symlink():
            files[rel] = "link:" + os.readlink(p)
            continue
        data = p.read_bytes()
        if rel == ".atlas/VERSION":
            # 行 1 = 源包摘要（应稳定）；行 2 = 时间；行 3 = 源包绝对路径。
            lines = data.decode("utf-8").splitlines()
            if len(lines) >= 3:
                lines[1] = "<TIMESTAMP>"
                lines[2] = "<PKG>"
            data = ("\n".join(lines) + "\n").encode("utf-8")
        elif rel == ".atlas/ABLATION":
            # begin 写的项目内标记含 started 时间戳。
            data = ISO_BYTES_RE.sub(b"<TIMESTAMP>", data)
        files[rel] = hashlib.sha256(_bytes_without_env(data, ctx)).hexdigest()
    return {"files": files, "dirs": dirs}


# ---------------------------------------------------------------- scenarios
# 每个场景在独立的临时项目里跑；断言退出码 = 冻结契约的一部分。

def sc_fresh(ctx: Ctx) -> None:
    """首次装配：空项目 + .trellis 骨架；默认 flags（skills/骨架/落戳/自检全走）。"""
    ctx.seed_trellis()
    ctx.run(["--target", str(ctx.root), "--assets-root", "docs"], expect=0)


def sc_update(ctx: Ctx) -> None:
    """已装配项目的 --update 刷新。"""
    sc_fresh(ctx)
    ctx.run(["--update", "--target", str(ctx.root)], expect=0)


def sc_dry_run_fresh(ctx: Ctx) -> None:
    """F54：全新 target 干跑零落盘（.atlas/ 与 atlas.config.yaml 都不出现）。"""
    ctx.seed_trellis()
    ctx.run(["--force", "--dry-run", "--target", str(ctx.root)], expect=0)


def _seed_assembled_tracked(ctx: Ctx) -> None:
    (ctx.root / ".atlas" / "scripts").mkdir(parents=True)
    (ctx.root / ".atlas" / "VERSION").write_text("fixture-stamp\nwhen\nnowhere\n", encoding="utf-8")
    ctx.seed_trellis()
    (ctx.root / ".trellis" / "workflow.md").write_text("# w\n", encoding="utf-8")
    (ctx.root / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
    ctx.git_init(["AGENTS.md", ".trellis/workflow.md", ".atlas/VERSION"])


def sc_guard_dirty(ctx: Ctx) -> None:
    """F34/F55：已跟踪触点脏 ⇒ 拒（exit 1）；--force 越过（exit 0）并整包刷新。"""
    _seed_assembled_tracked(ctx)
    (ctx.root / "AGENTS.md").write_text("# agents\n# dirty local edit\n", encoding="utf-8")
    common = ["--update", "--target", str(ctx.root), "--no-skill", "--no-patch", "--no-wiring"]
    ctx.run(common, expect=1)
    ctx.run([*common, "--force"], expect=0)


def sc_guard_untracked(ctx: Ctx) -> None:
    """F55：.atlas/ 整目录未跟踪 ⇒ WARN 放行（exit 0），双摘要可见。"""
    (ctx.root / ".atlas" / "scripts").mkdir(parents=True)
    (ctx.root / ".atlas" / "VERSION").write_text("fixture-stamp\nwhen\nnowhere\n", encoding="utf-8")
    ctx.seed_trellis()
    (ctx.root / ".trellis" / "workflow.md").write_text("# w\n", encoding="utf-8")
    (ctx.root / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
    ctx.git_init(["AGENTS.md", ".trellis/workflow.md"])  # 有意不 add .atlas/
    ctx.run(["--update", "--target", str(ctx.root), "--no-skill", "--no-patch", "--no-wiring"],
            expect=0)


def sc_ablation_active(ctx: Ctx) -> None:
    """P3-b：active 消融期间 --update 拒（exit 2）。"""
    ctx.seed_trellis()
    (ctx.root / ".atlas").mkdir()
    (ctx.root / "a.txt").write_text("old\n", encoding="utf-8")
    ctx.git_init(["a.txt"])
    patch = ctx.tmp / "p.patch"
    patch.write_text(MODIFY_PATCH, encoding="utf-8")
    p = subprocess.run(
        [sys.executable, str(PKG_ROOT / "scripts" / "ablation.py"), "begin",
         "--id", "golden", "--root", str(ctx.root), "--patch", str(patch), "--scope", "golden"],
        env=ctx.env, capture_output=True, text=True,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    ctx.run(["--update", "--target", str(ctx.root), "--no-skill", "--no-patch", "--no-wiring"],
            expect=2)


def sc_invalid_config(ctx: Ctx) -> None:
    """布局配置非法 ⇒ exit 2 且不写。"""
    ctx.seed_trellis()
    (ctx.root / "atlas.config.yaml").write_text(
        "version: 1\nlayout:\n  assets_root: product\n  bogus: x\n", encoding="utf-8")
    ctx.run(["--target", str(ctx.root)], expect=2)


def sc_missing_layout(ctx: Ctx) -> None:
    """源包缺 _support/layout.py ⇒ 前置失败（exit 1），不进入拷贝。"""
    pkg = ctx.tmp / "pkgcopy"
    shutil.copytree(
        PKG_ROOT, pkg,
        ignore=shutil.ignore_patterns(
            "node_modules", ".git", ".atlas", ".pytest_cache", "__pycache__",
            "docs", "research", "proposals", "duty-review", ".github",
        ),
    )
    (pkg / "_support" / "layout.py").unlink()
    ctx.pkg = pkg
    # 沿用当前安装器自身的解释器与文件名（bash→install.sh / python→install.py）
    ctx.installer = [ctx.installer[0], str(pkg / Path(ctx.installer[1]).name)]
    ctx.seed_trellis()
    ctx.run(["--target", str(ctx.root), "--assets-root", "docs"], expect=1)


SCENARIOS = {
    "fresh": sc_fresh,
    "update": sc_update,
    "dry-run-fresh": sc_dry_run_fresh,
    "guard-dirty": sc_guard_dirty,
    "guard-untracked": sc_guard_untracked,
    "ablation-active": sc_ablation_active,
    "invalid-config": sc_invalid_config,
    "missing-layout": sc_missing_layout,
}


def resolve_installer(raw: str | None) -> list[str]:
    if not raw:
        return ["bash", str(PKG_ROOT / "install.sh")]
    path = Path(raw)
    if not path.is_absolute():
        path = PKG_ROOT / path
    if path.suffix == ".py":
        return [sys.executable, str(path)]
    return ["bash", str(path)]


def run_scenario(name: str, fn, installer: list[str]) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"atlas-golden-{name}-") as td:
        ctx = Ctx(Path(td), list(installer))
        fn(ctx)
        return {
            "scenario": name,
            "installer": [Path(installer[0]).name, normalize_text(" ".join(installer[1:]), ctx)],
            "runs": ctx.runs,
            "tree": snapshot(ctx),
        }


def compare(expected: dict, actual: dict) -> list[str]:
    diffs: list[str] = []
    if expected.get("runs") != actual.get("runs"):
        er, ar = expected.get("runs", []), actual.get("runs", [])
        for i in range(max(len(er), len(ar))):
            e = er[i] if i < len(er) else None
            a = ar[i] if i < len(ar) else None
            if e == a:
                continue
            if e is None or a is None:
                diffs.append(f"run[{i}]: 只在{'实际' if e is None else '基线'}中存在")
                continue
            if e["exit"] != a["exit"]:
                diffs.append(f"run[{i}] exit: {e['exit']} != {a['exit']}")
            el, al = e["output"], a["output"]
            for j in range(max(len(el), len(al))):
                ev = el[j] if j < len(el) else "<无>"
                av = al[j] if j < len(al) else "<无>"
                if ev != av:
                    diffs.append(f"run[{i}] output 第 {j + 1} 行:\n  基线: {ev}\n  实际: {av}")
                    break
    et, at = expected.get("tree", {}), actual.get("tree", {})
    ef, af = et.get("files", {}), at.get("files", {})
    for rel in sorted(set(ef) | set(af)):
        if rel not in af:
            diffs.append(f"文件缺失: {rel}")
        elif rel not in ef:
            diffs.append(f"多出文件: {rel}")
        elif ef[rel] != af[rel]:
            diffs.append(f"内容不同: {rel}")
        if len(diffs) >= 30:
            diffs.append("……（差异过多，截断）")
            return diffs
    if et.get("dirs") != at.get("dirs"):
        only_e = sorted(set(et.get("dirs", [])) - set(at.get("dirs", [])))
        only_a = sorted(set(at.get("dirs", [])) - set(et.get("dirs", [])))
        if only_e:
            diffs.append(f"缺目录: {only_e[:10]}")
        if only_a:
            diffs.append(f"多目录: {only_a[:10]}")
    return diffs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--record", action="store_true", help="用当前安装器录制/覆盖基线")
    g.add_argument("--check", action="store_true", help="重跑并与基线比对")
    g.add_argument("--list", action="store_true", help="列出场景")
    ap.add_argument("--only", action="append", default=[], help="只跑指定场景（可重复）")
    ap.add_argument("--installer", default=None, help="安装器路径（.py 用当前解释器，其余用 bash）")
    ap.add_argument("--golden-dir", default=str(DEFAULT_GOLDEN))
    args = ap.parse_args()

    if args.list:
        for name in SCENARIOS:
            print(name)
        return 0

    golden = Path(args.golden_dir)
    installer = resolve_installer(args.installer)
    names = args.only or list(SCENARIOS)
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        print(f"未知场景: {unknown}", file=sys.stderr)
        return 2

    if args.record:
        golden.mkdir(parents=True, exist_ok=True)
    failed = 0
    for name in names:
        actual = run_scenario(name, SCENARIOS[name], installer)
        path = golden / f"{name}.json"
        if args.record:
            path.write_text(json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
            print(f"recorded {name} ({len(actual['tree']['files'])} files, "
                  f"{len(actual['runs'])} runs)")
            continue
        if not path.is_file():
            print(f"MISSING {name}: 基线不存在（先 --record）", file=sys.stderr)
            failed += 1
            continue
        diffs = compare(json.loads(path.read_text(encoding="utf-8")), actual)
        if diffs:
            failed += 1
            print(f"FAIL {name}:")
            for d in diffs:
                print(f"  - {d}")
        else:
            print(f"PASS {name}")
    if args.check and not failed:
        print(f"\n全部场景与基线一致（{len(names)} 个）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
