#!/usr/bin/env python3
"""backflow 回灌助手的出厂测试（`gates.md` 假绿测试义务）。

覆盖：
  * 三态差异报告正确（NEW / DIFF / SOURCE_ONLY）；
  * 有 SOURCE_ONLY 时 `--apply` 拒绝（exit 2）—— `#191/#207` 覆盖事故教训的机器化（M48）；
  * `--force` 越过拒绝；同步后内容一致（含可执行位保留）；
  * 清单守恒：`BACKFLOW_DIRS` == `install.sh` 第 1 步循环项（副本态无 install.sh ⇒ SKIP 子项）。
"""
from __future__ import annotations

import importlib.util
import os
import re
import stat
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


bf = _load("backflow", "scripts/backflow.py")
BACKFLOW_DIRS, diff_trees, apply_fn = bf.BACKFLOW_DIRS, bf.diff_trees, bf.apply


def _mk_tree(tmp_path: Path, copy_files: dict[str, str], src_files: dict[str, str],
             exec_rel: str | None = None, exec_in_copy: bool = True) -> tuple[Path, Path]:
    copy_root, src_root = tmp_path / ".atlas", tmp_path / "atlas"
    for root, files in ((copy_root, copy_files), (src_root, src_files)):
        for rel, content in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
    if exec_rel:
        p = (copy_root if exec_in_copy else src_root) / exec_rel
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return copy_root, src_root


def test_diff_three_states(tmp_path: Path) -> None:
    """三态划分：NEW / DIFF / SOURCE_ONLY 各归其位（缓存与 .pyc 不进报告）。"""
    copy_root, src_root = _mk_tree(
        tmp_path,
        {"scripts/a.py": "new\n", "validators/b.py": "same\n", "scripts/c.py": "copy\n",
         "tests/__pycache__/x.pyc": "bin"},
        {"validators/b.py": "same\n", "scripts/c.py": "src\n", "tests/d.py": "src-only\n"},
    )
    d = diff_trees(copy_root, src_root)
    assert d["new"] == ["scripts/a.py"], d
    assert d["diff"] == ["scripts/c.py"], d
    assert d["source_only"] == ["tests/d.py"], d


def test_apply_refused_on_source_only(tmp_path: Path) -> None:
    """M48：源包独有差异存在 ⇒ 拒绝（exit 2），且未复制任何文件。"""
    copy_root, src_root = _mk_tree(
        tmp_path,
        {"scripts/a.py": "new\n"},
        {"tests/d.py": "src-only\n"},
    )
    code, text = apply_fn(copy_root, src_root, force=False)
    assert code == 2, text
    assert "拒绝执行" in text
    assert not (src_root / "scripts" / "a.py").exists()   # 拒绝即不动
    assert (src_root / "tests" / "d.py").exists()          # 源包原样保留


def test_apply_copies_and_preserves_exec_bit(tmp_path: Path) -> None:
    """正常回灌：NEW/DIFF 落盘、内容一致、可执行位保留、SOURCE_ONLY 不被动。"""
    copy_root, src_root = _mk_tree(
        tmp_path,
        {"scripts/a.py": "new\n", "validators/b.py": "copy2\n", "scripts/tool.py": "tool\n"},
        {"validators/b.py": "old\n"},
        exec_rel="scripts/tool.py", exec_in_copy=True,
    )
    code, text = apply_fn(copy_root, src_root, force=False)
    assert code == 0, text
    assert (src_root / "scripts" / "a.py").read_text(encoding="utf-8") == "new\n"
    assert (src_root / "validators" / "b.py").read_text(encoding="utf-8") == "copy2\n"
    mode = (src_root / "scripts" / "tool.py").stat().st_mode
    assert mode & stat.S_IXUSR, "可执行位未保留"
    # 幂等：再跑一次为零差异
    d2 = diff_trees(copy_root, src_root)
    assert d2 == {"new": [], "diff": [], "source_only": []}


def test_force_overrides_refusal(tmp_path: Path) -> None:
    """--force 越过 SOURCE_ONLY 拒绝（先人工核对方向的显式动作）。"""
    copy_root, src_root = _mk_tree(
        tmp_path,
        {"scripts/a.py": "new\n"},
        {"tests/d.py": "src-only\n"},
    )
    code, text = apply_fn(copy_root, src_root, force=True)
    assert code == 0, text
    assert (src_root / "scripts" / "a.py").exists()
    assert (src_root / "tests" / "d.py").exists()          # 越过 ≠ 删除源包独有件


def test_drift_check_detects_write(tmp_path: Path) -> None:
    """并发写入哨兵直测：文件在快照后被改写 ⇒ 点名（首用实证 `3508 §211`）。"""
    copy_root, _ = _mk_tree(tmp_path, {"scripts/a.py": "v1\n"}, {})
    rels = ["scripts/a.py"]
    snap = {rel: bf._stat_of(copy_root / rel) for rel in rels}
    (copy_root / "scripts" / "a.py").write_text("v2\n", encoding="utf-8")
    assert bf.drift_check(copy_root, rels, snap) == rels
    # 未改写 ⇒ 空（防恒报噪声）
    snap2 = {rel: bf._stat_of(copy_root / rel) for rel in rels}
    assert bf.drift_check(copy_root, rels, snap2) == []


def test_apply_aborts_on_concurrent_write(tmp_path: Path, monkeypatch) -> None:
    """哨兵触发 ⇒ 中止 exit 3，且拒绝即不动（M49：摘哨兵 ⇒ 本钉红）。"""
    copy_root, src_root = _mk_tree(tmp_path, {"scripts/a.py": "x\n"}, {})
    monkeypatch.setattr(bf, "drift_check", lambda *a, **k: ["scripts/a.py"])
    code, text = apply_fn(copy_root, src_root, force=False)
    assert code == 3, text
    assert "并发" in text
    assert not (src_root / "scripts" / "a.py").exists()


def test_apply_verify_red_exit4(tmp_path: Path) -> None:
    """--apply 后源包回归红 ⇒ exit 4 并指路并发核对。"""
    dummy = "def test_fail():\n    assert False\n"
    copy_root, src_root = _mk_tree(
        tmp_path, {"scripts/a.py": "x\n", "tests/test_dummy.py": dummy},
        {"tests/test_dummy.py": dummy})   # 双树同置 ⇒ 不触发 SOURCE_ONLY 拒绝
    code, text = bf.apply(copy_root, src_root, force=False, verify=True)
    assert code == 4, text
    assert "源包回归" in text


def test_apply_verify_green(tmp_path: Path) -> None:
    """源包回归绿 ⇒ 成功 exit 0 且摘要可见。"""
    dummy = "def test_ok():\n    assert True\n"
    copy_root, src_root = _mk_tree(
        tmp_path, {"scripts/a.py": "x\n", "tests/test_dummy.py": dummy},
        {"tests/test_dummy.py": dummy})
    code, text = bf.apply(copy_root, src_root, force=False, verify=True)
    assert code == 0, text
    assert "ok" in text


def test_manifest_matches_install_sh() -> None:
    """清单守恒：BACKFLOW_DIRS == install.sh 第 1 步循环项（副本态无 install.sh ⇒ SKIP）。"""
    install = PKG_ROOT / "install.sh"
    if not install.is_file():
        pytest.skip("副本态无 install.sh（装配面自检只在源包跑）——不是通过")
    text = install.read_text(encoding="utf-8")
    m = re.search(r"for pkg_dir in ([^;]+); do", text)
    assert m, "install.sh 第 1 步循环行未找到（形态变了？两处须同改）"
    listed = tuple(m.group(1).split())
    assert listed == BACKFLOW_DIRS, (
        f"backflow 清单与 install.sh 不一致：backflow={BACKFLOW_DIRS} install={listed}")
