#!/usr/bin/env python3
"""atlas apply 挂载补丁的回归测试。

守护 A3/D66：`patches/workflow-plan-apply/` 必须能对 `.trellis/workflow.md`
做**锚点式幂等插入**——插入 1.6 步骤 + 3 处 enforcement/索引行；再次运行幂等；
dry-run 不写；锚点缺失报错且不改文件。

两种运行方式：
    python3 atlas/tests/test_apply_patches.py      # 脚本式
    pytest atlas/tests/test_apply_patches.py       # pytest 式
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
PKG = PKG_ROOT / "patches" / "workflow-plan-apply"
REPO = PKG_ROOT.parent
APPLIER = PKG / "apply-patches.py"
SPEC = PKG / "spec.json"
REAL_WORKFLOW = Path(os.environ["ATLAS_REAL_WORKFLOW"]) if os.environ.get("ATLAS_REAL_WORKFLOW") else None

MARKERS = (
    "atlas:apply:plan-step-1-6",
    "atlas:apply:phase-index-1-6",
    "atlas:apply:breadcrumb-planning",
    "atlas:apply:breadcrumb-planning-inline",
)

FIXTURE = """# Development Workflow

---

## Phase Index

### Phase 1: Plan
- 1.0 Create task
- 1.5 Completion criteria

[workflow-state:planning]
Load `trellis-brainstorm`; stay in planning.
[/workflow-state:planning]

[workflow-state:planning-inline]
Load `trellis-brainstorm`; stay in planning.
[/workflow-state:planning-inline]

---

## Phase 1: Plan

#### 1.5 Completion criteria

| Condition | Required |
|------|:---:|
| `prd.md` exists | ✅ |

---

## Phase 2: Execute

Goal: implement the reviewed artifacts.
"""


def run(target: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(APPLIER), "--target", str(target), "--spec", str(SPEC), *extra],
        capture_output=True, text=True,
    )


def write_fixture(tmp: Path, content: str = FIXTURE) -> Path:
    d = tmp / ".trellis"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "workflow.md"
    f.write_text(content, encoding="utf-8")
    return f


def marker_re(pid: str) -> re.Pattern[str]:
    """块标记（带可选正文指纹）——版本化后不能再用字面量匹配。"""
    return re.compile(rf"<!--\s*atlas:apply:{re.escape(pid)}(?:@(?P<fp>[0-9a-f]{{8}}))?\s*-->")


def end_marker(pid: str) -> str:
    return f"<!-- /atlas:apply:{pid} -->"


def spec_patches() -> list[dict]:
    return pkg_patches(PKG)


def pkg_patches(pkg: Path) -> list[dict]:
    return json.loads((pkg / "spec.json").read_text(encoding="utf-8"))["patches"]


def all_patch_pkgs() -> list[Path]:
    """patches/ 下全部补丁包，glob 排序 = install.sh 泛化后的应用顺序。"""
    return sorted(p.parent for p in (PKG_ROOT / "patches").glob("*/spec.json"))


def snippet_of(patch: dict) -> str:
    return pkg_snippet(PKG, patch)


def pkg_snippet(pkg: Path, patch: dict) -> str:
    return (pkg / patch["snippet"]).read_text(encoding="utf-8").rstrip("\n")


def pid_of(marker: str) -> str:
    """`MARKERS` 存的是完整标记名（`atlas:apply:<id>`）；spec 里只存 `<id>`。"""
    return marker.split("atlas:apply:", 1)[1]


def to_legacy(text: str, pid: str, old_body: str | None = None) -> str:
    """把版本化块降级成旧式块（去掉指纹与结束标记），可选换成一段旧正文。"""
    m = marker_re(pid).search(text)
    assert m, f"找不到块标记 {pid}"
    e = text.find(end_marker(pid), m.end())
    assert e >= 0, f"找不到结束标记 {pid}"
    body = old_body if old_body is not None else text[m.end() + 1 : e].rstrip("\n") + "\n"
    j = e + len(end_marker(pid))
    if text[j : j + 1] == "\n":
        j += 1
    return text[: m.start()] + f"<!-- atlas:apply:{pid} -->\n" + body + text[j:]


def strip_patched(text: str) -> str:
    return strip_pkg(text, PKG)


def strip_pkg(text: str, pkg: Path) -> str:
    """把指定补丁包的已落块剥掉，还原成未打补丁的模板（兼容版本化块与旧式块）。

    旧式 + 正文不符 + `insert_after*` ⇒ 无法可靠定界，**不猜**，保持原样。
    """
    for p in pkg_patches(pkg):
        pid = p["id"]
        m = marker_re(pid).search(text)
        if not m:
            continue
        e = text.find(end_marker(pid), m.end())
        if e >= 0:
            j = e + len(end_marker(pid))
            if text[j : j + 1] == "\n":
                j += 1
            text = text[: m.start()] + text[j:]
            continue
        body = pkg_snippet(pkg, p)
        off = m.end() + (1 if text[m.end() : m.end() + 1] == "\n" else 0)
        if text.startswith(body, off):
            j = off + len(body)
            if text[j : j + 1] == "\n":
                j += 1
            text = text[: m.start()] + text[j:]
            continue
        if p["mode"].startswith("insert_after"):
            continue
        if p["mode"].endswith("_regex"):
            mm = re.compile(p["pattern"], re.MULTILINE).search(text, m.start())
            idx = mm.start() if mm else -1
        else:
            idx = text.find(p["anchor"], m.start())
        if idx > 0:
            text = text[: m.start()] + text[idx:]
    return text


def test_spec_is_valid_and_snippets_exist() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert spec["patches"], "spec 无补丁"
    for p in spec["patches"]:
        assert (PKG / p["snippet"]).is_file(), f"snippet 缺失: {p['snippet']}"


def test_apply_inserts_and_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as td:
        f = write_fixture(Path(td))

        r1 = run(Path(td), "--apply")
        assert r1.returncode == 0, r1.stderr + r1.stdout
        text = f.read_text(encoding="utf-8")

        for m in MARKERS:
            assert m in text, f"缺标记 {m}"
        assert "#### 1.6 项目级资产更新（atlas apply）" in text
        assert "- 1.6 项目级资产更新（atlas apply）" in text
        assert text.count("实现前对当前 task id 触发 `atlas-apply`") == 2
        # 1.6 必须在 Phase 2 标题之前
        assert text.index("#### 1.6") < text.index("## Phase 2: Execute")
        # 原始内容未被破坏
        assert "#### 1.5 Completion criteria" in text
        assert "[/workflow-state:planning]" in text

        # 第二次运行：全部 skipped，文件字节不变
        before = f.read_text(encoding="utf-8")
        r2 = run(Path(td), "--apply")
        assert r2.returncode == 0, r2.stderr + r2.stdout
        assert "skipped=4" in r2.stdout, r2.stdout
        assert f.read_text(encoding="utf-8") == before


def test_dry_run_does_not_write() -> None:
    with tempfile.TemporaryDirectory() as td:
        f = write_fixture(Path(td))
        before = f.read_text(encoding="utf-8")
        r = run(Path(td))  # 缺省 dry-run
        assert r.returncode == 0, r.stderr + r.stdout
        assert "applied=4" in r.stdout, r.stdout
        assert f.read_text(encoding="utf-8") == before


def test_missing_anchor_errors_without_writing() -> None:
    with tempfile.TemporaryDirectory() as td:
        f = write_fixture(Path(td), "# Dev\n\nno anchors here\n")
        before = f.read_text(encoding="utf-8")
        r = run(Path(td), "--apply")
        assert r.returncode == 1, r.stdout
        assert "errors=4" in r.stdout, r.stdout
        assert f.read_text(encoding="utf-8") == before


def test_real_workflow_anchors_present() -> None:
    """对真实 Trellis 模板跑一遍：剥掉已落补丁后重放，必须回到原样。

    守护两件事：① 真实 `workflow.md` 的 4 个锚点仍可定位（Trellis 升级或本地改写
    导致锚点漂移即红）；② 片段与真实文件一致（任一方被单独改动 ⇒ 重放结果与真实
    文件不逐字节相等 ⇒ 红）。**已打过补丁的真实文件也是合法输入**——剥掉再重放。
    """
    if REAL_WORKFLOW is None:
        msg = (
            "未指定 ATLAS_REAL_WORKFLOW —— 包内不写死任何具体项目的 workflow.md（属具体项目，"
            "不属包件）；要跑本用例请传 ATLAS_REAL_WORKFLOW=<项目>/.trellis/workflow.md"
        )
        try:
            import pytest
        except ImportError:
            print("skip: " + msg)
        else:
            pytest.skip(msg)
        return
    if not REAL_WORKFLOW.is_file():
        print(f"skip: ATLAS_REAL_WORKFLOW 指向的文件不存在：{REAL_WORKFLOW}")
        return
    real = REAL_WORKFLOW.read_text(encoding="utf-8")
    pkgs = all_patch_pkgs()
    already_patched = all(
        marker_re(p["id"]).search(real)
        for pkg in pkgs for p in pkg_patches(pkg)
    )
    with tempfile.TemporaryDirectory() as td:
        f = write_fixture(Path(td), real)
        # 剥 + 重放**全部补丁包**，顺序与 install.sh 泛化后的 glob 排序一致
        # （只重放单包会让后落包的块在重放产物中丢失，字节比对必假红）
        for pkg in pkgs:
            f.write_text(strip_pkg(f.read_text(encoding="utf-8"), pkg), encoding="utf-8")
            r1 = subprocess.run(
                [sys.executable, str(pkg / "apply-patches.py"),
                 "--target", str(td), "--spec", str(pkg / "spec.json"), "--apply"],
                capture_output=True, text=True, timeout=120,
            )
            assert r1.returncode == 0, f"{pkg.name} 锚点未命中：\n" + r1.stdout + r1.stderr
            assert "errors=0" in r1.stdout, (pkg.name, r1.stdout)
        text = f.read_text(encoding="utf-8")
        for pkg in pkgs:
            for p in pkg_patches(pkg):
                assert end_marker(p["id"]) in text, f"{pkg.name}:{p['id']} 缺结束标记"
        if already_patched:
            assert text == real, "重放结果与真实 workflow.md 不逐字节相等（片段或真实文件被单独改动）"
        for pkg in pkgs:   # 二次重放幂等（全部 skip，不再动文件）
            r2 = subprocess.run(
                [sys.executable, str(pkg / "apply-patches.py"),
                 "--target", str(td), "--spec", str(pkg / "spec.json"), "--apply"],
                capture_output=True, text=True, timeout=120,
            )
            assert r2.returncode == 0 and "applied=0" in r2.stdout, (pkg.name, r2.stdout)
        assert f.read_text(encoding="utf-8") == text


def test_real_workflow_replays_all_packages() -> None:
    """指定 `ATLAS_REAL_WORKFLOW` 时：`patches/` 下**每个补丁包**都对真实 workflow.md
    干跑重放一遍，必须 `errors=0`（任一包的锚点漂移或片段失配 ⇒ 红）。

    背景（2026-10-04 回灌 #161/#162）：install.sh 第 5 步已泛化为遍历 `patches/*/`，
    本用例保证「每个随装配自动生效的包」在真实 Trellis 模板上都能定位锚点。
    """
    if REAL_WORKFLOW is None:
        msg = (
            "未指定 ATLAS_REAL_WORKFLOW —— 包内不写死任何具体项目的 workflow.md（属具体项目，"
            "不属包件）；要跑本用例请传 ATLAS_REAL_WORKFLOW=<项目>/.trellis/workflow.md"
        )
        try:
            import pytest
        except ImportError:
            print("skip: " + msg)
        else:
            pytest.skip(msg)
        return
    if not REAL_WORKFLOW.is_file():
        print(f"skip: ATLAS_REAL_WORKFLOW 指向的文件不存在：{REAL_WORKFLOW}")
        return
    target = REAL_WORKFLOW.parent.parent
    specs = sorted((PKG_ROOT / "patches").glob("*/spec.json"))
    assert specs, "patches/ 下没有任何补丁包"
    for spec in specs:
        r = subprocess.run(
            [sys.executable, str(spec.parent / "apply-patches.py"),
             "--target", str(target), "--spec", str(spec)],
            capture_output=True, text=True, timeout=120,
        )
        assert r.returncode == 0, (spec, r.stdout + r.stderr)
        assert "errors=0" in r.stdout, (spec, r.stdout)


def test_blocks_are_versioned() -> None:
    """块必须是「带正文指纹的开始标记 + 结束标记」，否则「片段改了项目拿不到新正文」。"""
    with tempfile.TemporaryDirectory() as td:
        f = write_fixture(Path(td))
        r = run(Path(td), "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        text = f.read_text(encoding="utf-8")
        for p in spec_patches():
            m = marker_re(p["id"]).search(text)
            assert m, f"缺标记 {p['id']}"
            assert m.group("fp"), f"{p['id']} 标记缺正文指纹"
            assert end_marker(p["id"]) in text, f"{p['id']} 缺结束标记"


def test_snippet_change_replaces_stale_block() -> None:
    """B93 核心：片段更新后，已落的旧块必须被**整块替换**，而不是被 skip。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        f = write_fixture(td)
        assert run(td, "--apply").returncode == 0

        pkg2 = td / "pkg2"
        shutil.copytree(PKG, pkg2)
        snip = pkg2 / "1.6-plan-apply.insert.md"
        snip.write_text(snip.read_text(encoding="utf-8") + "\n- NEW-LINE-FROM-SNIPPET-CHANGE\n", encoding="utf-8")

        r = subprocess.run(
            [sys.executable, str(pkg2 / "apply-patches.py"), "--target", str(td),
             "--spec", str(pkg2 / "spec.json"), "--apply"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "replaced=1" in r.stdout and "skipped=3" in r.stdout, r.stdout

        new = f.read_text(encoding="utf-8")
        assert new.count("NEW-LINE-FROM-SNIPPET-CHANGE") == 1
        assert new.count("#### 1.6 项目级资产更新") == 1, "旧块没被换掉，出现重复块"
        assert len(re.findall(r"<!--\s*atlas:apply:plan-step-1-6@[0-9a-f]{8}\s*-->", new)) == 1
        assert new.count(end_marker("plan-step-1-6")) == 1

        # 换过之后仍然幂等（用同一份改过的包再跑）
        r2 = subprocess.run(
            [sys.executable, str(pkg2 / "apply-patches.py"), "--target", str(td),
             "--spec", str(pkg2 / "spec.json"), "--apply"],
            capture_output=True, text=True,
        )
        assert "skipped=4" in r2.stdout, r2.stdout
        assert f.read_text(encoding="utf-8") == new


def test_legacy_block_is_migrated() -> None:
    """旧式块（无指纹 / 无结束标记）：正文一致 ⇒ upgraded；正文不符 ⇒ replaced。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        f = write_fixture(td)
        assert run(td, "--apply").returncode == 0
        text = f.read_text(encoding="utf-8")

        text = to_legacy(text, "plan-step-1-6", "#### 1.6 旧正文（旧版片段）\n\n- 旧内容\n")
        for pid in ("phase-index-1-6", "breadcrumb-planning", "breadcrumb-planning-inline"):
            text = to_legacy(text, pid)
        f.write_text(text, encoding="utf-8")
        outside_before = strip_patched(text)

        r = run(td, "--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "replaced=1" in r.stdout and "upgraded=3" in r.stdout, r.stdout

        after = f.read_text(encoding="utf-8")
        assert "#### 1.6 旧正文" not in after
        assert strip_patched(after) == outside_before, "块外的正文被改动了"
        for p in spec_patches():
            assert end_marker(p["id"]) in after, f"{p['id']} 未被升级"
        assert "skipped=4" in run(td, "--apply").stdout


def test_legacy_insert_after_without_end_marker_is_refused() -> None:
    """`insert_after` 的旧式块无法可靠定界 ⇒ 必须报 error 且不改文件（不猜边界）。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        f = write_fixture(td)
        assert run(td, "--apply").returncode == 0
        text = to_legacy(f.read_text(encoding="utf-8"), "phase-index-1-6",
                         "- 1.6 旧式插入（与当前片段不符）\n")
        f.write_text(text, encoding="utf-8")

        r = run(td, "--apply")
        assert r.returncode == 1, r.stdout
        assert "errors=1" in r.stdout, r.stdout
        assert f.read_text(encoding="utf-8") == text, "报 error 时不得写文件"


def test_every_patch_package_is_complete() -> None:
    """包面守卫（2026-10-04 回灌 #161/#162）：`patches/` 下每个补丁包必须四件齐——
    spec.json 可解析、包内补丁 id 唯一（指纹追踪前提）、每条补丁引用的片段文件存在、
    锚点正则可编译、自包含 `apply-patches.py` 在位。新增包漏件即红（防「装配时才炸」）。
    变异：删任一包的 apply-patches.py / 片段 ⇒ 本用例红。
    """
    specs = sorted((PKG_ROOT / "patches").glob("*/spec.json"))
    assert len(specs) >= 2, specs          # workflow-plan-apply + workflow-skill-routing 两包在位
    for spec_path in specs:
        pkg = spec_path.parent
        assert (pkg / "apply-patches.py").is_file(), f"{pkg} 缺 apply-patches.py"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        patches = spec.get("patches")
        assert isinstance(patches, list) and patches, (pkg, "patches[] 缺失")
        ids = [p.get("id") for p in patches]
        assert len(ids) == len(set(ids)), (pkg, ids)
        for p in patches:
            snippet = p.get("snippet")
            assert snippet and (pkg / snippet).is_file(), (pkg, p.get("id"), snippet)
            if p.get("pattern"):
                re.compile(p["pattern"])   # 锚点正则必须可编译


def main() -> int:
    tests = [
        test_spec_is_valid_and_snippets_exist,
        test_apply_inserts_and_is_idempotent,
        test_blocks_are_versioned,
        test_snippet_change_replaces_stale_block,
        test_legacy_block_is_migrated,
        test_legacy_insert_after_without_end_marker_is_refused,
        test_dry_run_does_not_write,
        test_missing_anchor_errors_without_writing,
        test_real_workflow_anchors_present,
        test_every_patch_package_is_complete,
        test_real_workflow_replays_all_packages,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"{'FAIL' if failed else 'PASS'} ({len(tests) - failed}/{len(tests)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
