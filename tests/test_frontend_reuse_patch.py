#!/usr/bin/env python3
"""前端复用契约 + workflow-skill-routing 补丁的回归测试。

守护 D177：
  ① `shared/frontend-reuse.md` 的适用四档 / 四层 / 五列 / surface / 打桩边界存在；
  ② `patches/workflow-skill-routing/` 的 11 条补丁能在完整 workflow fixture 上
     干跑不写、首跑 applied、二跑 skipped、锚点缺失报错且不写；
  ③ 补丁 id 跨包唯一，片段与契约不含具体框架名；
  ④ `shared/single-source.md` 已登记复用决策记录 owner。

运行：
    python3 tests/test_frontend_reuse_patch.py
    pytest tests/test_frontend_reuse_patch.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
PATCH_PKG = PKG_ROOT / "patches" / "workflow-skill-routing"
APPLIER = PATCH_PKG / "apply-patches.py"
SPEC = PATCH_PKG / "spec.json"
CONTRACT = PKG_ROOT / "shared" / "frontend-reuse.md"
SINGLE_SOURCE = PKG_ROOT / "shared" / "single-source.md"

NEW_IDS = (
    "reuse-planning",
    "reuse-planning-inline",
    "reuse-in-progress",
    "reuse-in-progress-inline",
)
NEW_SNIPPETS = (
    "reuse-planning.insert.md",
    "reuse-planning-inline.insert.md",
    "reuse-in-progress.insert.md",
    "reuse-in-progress-inline.insert.md",
)
EXPECTED_IDS = (
    "ui-skill-breadcrumb",
    "ui-skill-breadcrumb-inline",
    "ui-skill-note",
    "skill-no-negative-echo",
    "skill-no-negative-echo-inline",
    "skill-grilling-planning",
    "skill-grilling-planning-inline",
    *NEW_IDS,
)
EXPECTED_PATCHES = 11

FRAMEWORK_WORDS = (
    "antd", "rc-select", "react", "vue", "angular", "svelte", "next", "nuxt",
    "element-plus", "naive-ui", "shadcn", "tailwind", "vite", "webpack",
    "playwright", "cypress", "selenium", "page.route", "package.json", "mcp",
    "jest", "vitest", "msw",
)

FIXTURE = """# Development Workflow

---

## Phase Index

[workflow-state:planning]
Load `trellis-brainstorm`; stay in planning.
[/workflow-state:planning]

[workflow-state:planning-inline]
Load `trellis-brainstorm`; stay in planning.
[/workflow-state:planning-inline]

[workflow-state:in_progress]
Implement only after task status is in_progress.
[/workflow-state:in_progress]

[workflow-state:in_progress-inline]
Implement only after task status is in_progress.
[/workflow-state:in_progress-inline]

---

## Phase 2: Execute

#### 2.2 Check

**Final pass (before Phase 3.4 commit)**: run full-scope checks.

#### 2.3 Next
"""


def _run(target: Path, *extra: str, spec: Path = SPEC) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(APPLIER), "--target", str(target), "--spec", str(spec), *extra],
        capture_output=True, text=True,
    )


def _run_json(target: Path, *extra: str, spec: Path = SPEC) -> tuple[dict, subprocess.CompletedProcess]:
    proc = _run(target, "--json", *extra, spec=spec)
    data = json.loads(proc.stdout)
    return data, proc


def _target(tmp: Path, fixture: str = FIXTURE) -> Path:
    root = tmp / "project"
    (root / ".trellis").mkdir(parents=True)
    (root / ".trellis" / "workflow.md").write_text(fixture, encoding="utf-8")
    return root


def _marker_count(text: str, pid: str) -> int:
    return len(re.findall(rf"<!--\s*atlas:apply:{re.escape(pid)}@[0-9a-f]{{8}}\s*-->", text))


def _state_block(text: str, name: str) -> str:
    start = text.index(f"[workflow-state:{name}]")
    end = text.index(f"[/workflow-state:{name}]")
    return text[start:end]


def _assert_no_framework_words(text: str, where: str) -> None:
    lowered = text.lower()
    hits = [w for w in FRAMEWORK_WORDS if re.search(rf"\b{re.escape(w)}\b", lowered)]
    assert not hits, f"{where} 含具体框架名/生态标识：{hits}"


def test_contract_shape() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    for heading in (
        "## 1. 适用性与执行顺序",
        "## 2. 交互清点",
        "## 3. 四层查找",
        "## 4. 复用决策表",
        "## 5. 新模块的目录确认",
        "## 6. 验证与证据",
        "## 7. 可选的项目侧索引",
        "## 8. 反模式",
    ):
        assert heading in text, f"契约缺章节：{heading}"
    for token in ("new-module", "refactor", "new-files", "not-applicable"):
        assert token in text, f"契约缺适用档：{token}"
    for column in ("Capability", "Reference", "Reuse Decision", "Gap / Deviation", "Verification"):
        assert column in text, f"契约缺决策列：{column}"
    for keyword in ("surface", "打桩", "E2E", "非门", "非真相源", "Trellis"):
        assert keyword in text, f"契约缺关键语义：{keyword}"
    _assert_no_framework_words(text, "shared/frontend-reuse.md")


def test_single_source_registration() -> None:
    text = SINGLE_SOURCE.read_text(encoding="utf-8")
    assert "前端复用决策记录" in text
    assert ".atlas/shared/frontend-reuse.md" in text


def test_patch_ids_unique_across_packages() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert [p["id"] for p in spec["patches"]] == list(EXPECTED_IDS)
    seen: dict[str, str] = {}
    for spec_path in sorted((PKG_ROOT / "patches").glob("*/spec.json")):
        other = json.loads(spec_path.read_text(encoding="utf-8"))
        for patch in other["patches"]:
            pid = patch["id"]
            assert pid not in seen, f"补丁 id 跨包重复：{pid}（{seen[pid]} / {spec_path}）"
            seen[pid] = spec_path.name
    assert len(seen) >= EXPECTED_PATCHES


def test_snippets_reference_contract() -> None:
    for name in NEW_SNIPPETS:
        text = (PATCH_PKG / name).read_text(encoding="utf-8")
        assert ".atlas/shared/frontend-reuse.md" in text, f"{name} 未指向契约"
        _assert_no_framework_words(text, f"patches/workflow-skill-routing/{name}")
    note = (PATCH_PKG / "ui-skill-note.insert.md").read_text(encoding="utf-8")
    for keyword in ("前端复用", "sibling", "surface", "打桩", "E2E"):
        assert keyword in note, f"2.2 末注缺复用语义：{keyword}"
    _assert_no_framework_words(note, "patches/workflow-skill-routing/ui-skill-note.insert.md")


def test_full_package_dry_run_does_not_write() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        target = _target(Path(tmp))
        workflow = target / ".trellis" / "workflow.md"
        before = workflow.read_bytes()
        data, proc = _run_json(target)
        assert proc.returncode == 0, proc.stderr
        assert data["dry_run"] is True
        assert data["errors"] == 0
        assert data["applied"] == EXPECTED_PATCHES
        assert workflow.read_bytes() == before, "dry-run 不得写文件"


def test_full_package_apply_and_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        target = _target(Path(tmp))
        workflow = target / ".trellis" / "workflow.md"
        first, proc = _run_json(target, "--apply")
        assert proc.returncode == 0, proc.stderr
        assert first["errors"] == 0
        assert first["applied"] == EXPECTED_PATCHES
        text = workflow.read_text(encoding="utf-8")
        for pid in NEW_IDS:
            assert _marker_count(text, pid) == 1, f"{pid} 未恰好落一块"
        assert ".atlas/shared/frontend-reuse.md" in text
        for snippet in ("按四步执行", "同面板", "surface", "打桩", "普通修复不强制"):
            assert snippet in text, f"注入内容缺：{snippet}"
        for name, first, second in (
            ("planning", "skill-grilling-planning@", "reuse-planning@"),
            ("planning-inline", "skill-grilling-planning-inline@", "reuse-planning-inline@"),
            ("in_progress", "ui-skill-breadcrumb@", "skill-no-negative-echo@"),
            ("in_progress", "skill-no-negative-echo@", "reuse-in-progress@"),
            ("in_progress-inline", "ui-skill-breadcrumb-inline@", "skill-no-negative-echo-inline@"),
            ("in_progress-inline", "skill-no-negative-echo-inline@", "reuse-in-progress-inline@"),
        ):
            block = _state_block(text, name)
            assert block.index(first) < block.index(second), (
                f"{name} 块顺序不对：{first} 应在 {second} 前"
            )

        after_first = workflow.read_bytes()
        second, proc = _run_json(target, "--apply")
        assert proc.returncode == 0, proc.stderr
        assert second["errors"] == 0
        assert second["skipped"] == EXPECTED_PATCHES
        assert second["applied"] == second["replaced"] == second["upgraded"] == 0
        assert workflow.read_bytes() == after_first, "重放不得改字节"


def _old_ui_note() -> str:
    current = (PATCH_PKG / "ui-skill-note.insert.md").read_text(encoding="utf-8").rstrip("\n")
    head = current.split("\n\n**前端复用", 1)[0]
    assert head and "前端复用" not in head
    return head + "\n"


def test_legacy_upgrade_applies_new_and_replaces_note() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = _target(root)
        old_pkg = root / "oldpkg"
        shutil.copytree(PATCH_PKG, old_pkg)
        old_note = _old_ui_note()
        (old_pkg / "ui-skill-note.insert.md").write_text(old_note, encoding="utf-8")
        full = json.loads(SPEC.read_text(encoding="utf-8"))
        old_spec = {
            "version": "1.1",
            "target_prefix": "",
            "patches": [p for p in full["patches"] if p["id"] not in NEW_IDS],
        }
        (old_pkg / "spec-old.json").write_text(
            json.dumps(old_spec, ensure_ascii=False), encoding="utf-8"
        )
        old_proc = subprocess.run(
            [sys.executable, str(old_pkg / "apply-patches.py"),
             "--target", str(target), "--spec", str(old_pkg / "spec-old.json"),
             "--apply", "--json"],
            capture_output=True, text=True,
        )
        assert old_proc.returncode == 0, old_proc.stderr
        old = json.loads(old_proc.stdout)
        assert old["applied"] == 7 and old["errors"] == 0

        data, proc = _run_json(target, "--apply")
        assert proc.returncode == 0, proc.stderr
        assert data["applied"] == 4
        assert data["replaced"] == 1
        assert data["skipped"] == 6
        assert data["errors"] == 0
        assert [r["id"] for r in data["results"] if r["status"] == "replaced"] == ["ui-skill-note"]

        text = (target / ".trellis" / "workflow.md").read_text(encoding="utf-8")
        assert old_note.strip() in text, "旧 UI 路由正文应保留"
        assert "前端复用（执行期" in text
        assert "reuse-planning@" in _state_block(text, "planning")
        assert "reuse-in-progress@" in _state_block(text, "in_progress")
        assert "reuse-planning-inline@" in _state_block(text, "planning-inline")
        assert "reuse-in-progress-inline@" in _state_block(text, "in_progress-inline")


def test_anchor_missing_errors_without_write() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        fixture = FIXTURE.replace("[/workflow-state:in_progress]\n", "")
        target = _target(Path(tmp), fixture)
        workflow = target / ".trellis" / "workflow.md"
        before = workflow.read_bytes()
        spec = json.loads(SPEC.read_text(encoding="utf-8"))
        one = {"version": spec["version"], "target_prefix": "", "patches": [
            p for p in spec["patches"] if p["id"] == "reuse-in-progress"
        ]}
        one_spec = Path(tmp) / "one.json"
        one_spec.write_text(json.dumps(one, ensure_ascii=False), encoding="utf-8")
        data, proc = _run_json(target, "--apply", spec=one_spec)
        assert proc.returncode == 1
        assert data["errors"] == 1
        assert data["results"][0]["status"] == "error"
        assert "anchor not found" in data["results"][0]["detail"]
        assert workflow.read_bytes() == before, "锚点缺失不得写文件"


def test_real_workflow_anchors_if_available() -> None:
    real = os.environ.get("ATLAS_REAL_WORKFLOW")
    if not real:
        raise unittest.SkipTest("ATLAS_REAL_WORKFLOW not set")
    source = Path(real)
    assert source.is_file(), f"ATLAS_REAL_WORKFLOW 不存在：{source}"
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "project"
        (target / ".trellis").mkdir(parents=True)
        shutil.copy2(source, target / ".trellis" / "workflow.md")
        before = (target / ".trellis" / "workflow.md").read_bytes()
        data, proc = _run_json(target)
        assert proc.returncode == 0, f"真实 workflow 锚点干跑失败：{data}"
        assert data["errors"] == 0
        assert (target / ".trellis" / "workflow.md").read_bytes() == before


def main() -> int:
    tests = [
        test_contract_shape,
        test_single_source_registration,
        test_patch_ids_unique_across_packages,
        test_snippets_reference_contract,
        test_full_package_dry_run_does_not_write,
        test_full_package_apply_and_idempotent,
        test_legacy_upgrade_applies_new_and_replaces_note,
        test_anchor_missing_errors_without_write,
        test_real_workflow_anchors_if_available,
    ]
    for test in tests:
        try:
            test()
        except unittest.SkipTest as exc:
            print(f"skip {test.__name__}: {exc}")
            continue
        print(f"ok {test.__name__}")
    print("frontend reuse patch tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
