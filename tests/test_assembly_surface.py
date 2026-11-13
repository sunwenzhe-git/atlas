#!/usr/bin/env python3
"""出厂测试 —— 装配面四表同批守恒与出厂残留清理（`RFC-20261114-01`）。

装配面有四张清单表（评审 M1）：`install.py pkg_dirs`（装配拷贝）/ `pkg_digest.ASSEMBLY_COVER_DIRS`
（VERSION+MANIFEST 摘要口径）/ `package.json.files`（npm 分发面）/ `backflow.BACKFLOW_DIRS`
（回灌清单）。`RFC-20261114-01` 起四表同批不含出厂测试目录 `tests/`；本文件钉死
「任一表单方面把 `tests` 加回 ⇒ 红」，防装配面/摘要口径/分发面/回灌清单重新劈叉。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pd = load("pkg_digest", "scripts/pkg_digest.py")
bf = load("backflow", "scripts/backflow.py")


def _install_pkg_dirs() -> set[str]:
    install_py = PKG_ROOT / "install.py"
    if not install_py.is_file():
        import pytest
        pytest.skip("包内无 install.py（副本态）——同步钉要求源包态执行")
    m = re.search(r"pkg_dirs = \[(.*?)\]", install_py.read_text(encoding="utf-8"), re.S)
    assert m, "install.py 的 pkg_dirs 清单没找到"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def test_rfc20261114_01_factory_tests_absent_from_all_four_tables() -> None:
    """四表同批守恒：`tests` 不得出现在装配拷贝 / 摘要口径 / npm 分发 / 回灌清单任一表。

    变异：任一表加回 `"tests"` ⇒ 本钉红（四表同批的 M 系列钉——单表回流即劈叉）。
    """
    tables = {
        "install.py pkg_dirs": _install_pkg_dirs(),
        "pkg_digest.ASSEMBLY_COVER_DIRS": set(pd.ASSEMBLY_COVER_DIRS),
        "package.json.files": set(json.loads(
            (PKG_ROOT / "package.json").read_text(encoding="utf-8")).get("files") or []),
        "backflow.BACKFLOW_DIRS": set(bf.BACKFLOW_DIRS),
    }
    back = {name for name, entries in tables.items() if "tests" in entries}
    assert not back, (
        f"出厂测试目录回流装配面（RFC-20261114-01）：{back} 含 'tests' —— "
        "出厂测试已回归源包验收面，装配集四表同批不含 tests/；"
        "确要恢复装配须走提案（装配面/摘要口径/分发面/回灌清单四处同改）")


def test_cleanup_factory_tests_no_residual_is_noop(tmp_path) -> None:
    """fresh 场（无 .atlas/tests）⇒ residual 空清单 + 清理 no-op 不抛。"""
    atlas = tmp_path / ".atlas"
    atlas.mkdir()
    assert pd.factory_tests_residual(atlas, atlas / "MANIFEST.json") == []
    pd.cleanup_factory_tests(atlas)  # 幂等 no-op


def test_cleanup_factory_tests_pure_factory_residual_removed(tmp_path) -> None:
    """全部命中旧 MANIFEST 基线 ⇒ residual 空（可整删）+ 清理删除目录。

    旧装配基线（含 tests 条目）由 stamp_file 生成——此处直接构造同形状
    `{digest, files: {rel: sha256}}` 验证闸逻辑。
    """
    atlas = tmp_path / ".atlas"
    tests_dir = atlas / "tests"
    tests_dir.mkdir(parents=True)
    files = {}
    for name, content in (("tests/test_a.py", "A"), ("tests/test_b.py", "B")):
        (tests_dir / name.split("/", 1)[1]).write_text(content, encoding="utf-8")
        files[name] = hashlib.sha256(content.encode()).hexdigest()
    (atlas / "MANIFEST.json").write_text(
        json.dumps({"digest": "0" * 16, "files": files}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    assert pd.factory_tests_residual(atlas, atlas / "MANIFEST.json") == []
    pd.cleanup_factory_tests(atlas)
    assert not tests_dir.exists()


def test_cleanup_factory_tests_foreign_content_blocks(tmp_path) -> None:
    """基线外 / hash 不符 ⇒ residual 指名；缓存类（__pycache__/.pyc/.DS_Store）豁免不算采纳方内容。

    防 rm 不可逆误删：对齐测试门「目录在场即跑」的语义会邀请采纳方往 .atlas/tests
    种自己的集成测试（评审 M3）。
    """
    atlas = tmp_path / ".atlas"
    tests_dir = atlas / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_ok.py").write_text("OK", encoding="utf-8")
    manifest = {"digest": "0" * 16,
                "files": {"tests/test_ok.py": hashlib.sha256(b"OK").hexdigest()}}
    (atlas / "MANIFEST.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    # 缓存类在场 ⇒ 不进 residual（豁免）
    cache_dir = tests_dir / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "test_ok.cpython-312.pyc").write_bytes(b"\x00")
    (tests_dir / ".DS_Store").write_bytes(b"\x00")
    assert pd.factory_tests_residual(atlas, atlas / "MANIFEST.json") == []
    # 采纳方自种内容 ⇒ 基线外指名
    (tests_dir / "my_integration_test.py").write_text("MINE", encoding="utf-8")
    residual = pd.factory_tests_residual(atlas, atlas / "MANIFEST.json")
    assert residual == ["tests/my_integration_test.py（基线外）"], residual
    # 改动出厂文件 ⇒ hash 不符指名
    (tests_dir / "my_integration_test.py").unlink()
    (tests_dir / "test_ok.py").write_text("TAMPERED", encoding="utf-8")
    residual = pd.factory_tests_residual(atlas, atlas / "MANIFEST.json")
    assert residual == ["tests/test_ok.py（hash 不符）"], residual
