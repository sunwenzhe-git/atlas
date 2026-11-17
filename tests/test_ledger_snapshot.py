#!/usr/bin/env python3
"""派生数字生成器的出厂测试（2026-11-17 账本设计案 方案乙 · 步 1）。

钉住三件事：
  1. 唯一源口径：给定合成仓，派生键值必须等于手算的 golden 向量；
  2. 缺源/未知键必炸：不许静默 0、不许原样放过（fail-closed）；
  3. 逐文件量具与 canonical 同口径：字符串里的幽灵 `def test_` 不计入。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
PKG_ROOT = TESTS_DIR.parent
for extra in (TESTS_DIR, PKG_ROOT / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from ledger_snapshot import SnapshotError, count_tests, derive, rewrite  # noqa: E402


def _mk_repo(tmp: Path) -> Path:
    (tmp / "scripts").mkdir()
    (tmp / "validators").mkdir()
    (tmp / "tests").mkdir()
    (tmp / "skills" / "s1").mkdir(parents=True)
    (tmp / "skills" / "s2").mkdir(parents=True)
    (tmp / "rings" / "r1").mkdir(parents=True)
    (tmp / "shared").mkdir()
    (tmp / "_support").mkdir()

    (tmp / "scripts" / "atlas_check.py").write_text(
        'VALIDATORS = (\n    "validate_a",\n    "validate_b",\n)\n', encoding="utf-8")
    (tmp / "scripts" / "big.py").write_text("x = 1\n" * 10, encoding="utf-8")
    (tmp / "scripts" / "small.py").write_text("y = 1\n", encoding="utf-8")
    (tmp / "validators" / "validate_a.py").write_text("", encoding="utf-8")
    (tmp / "validators" / "validate_b.py").write_text("", encoding="utf-8")
    (tmp / "tests" / "test_a.py").write_text(
        "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n", encoding="utf-8")
    (tmp / "tests" / "test_b.py").write_text(
        'def test_real():\n    pass\n\n\n_SAMPLE = """\ndef test_phantom():\n    pass\n"""\n',
        encoding="utf-8")
    (tmp / "install.py").write_text(
        'c("a", "b")\nc("c", "d")\nc("e", "f")\n', encoding="utf-8")
    (tmp / "rings" / "r1" / "reference.md").write_text("", encoding="utf-8")
    for name in ("a.md", "b.md", "c.md"):
        (tmp / "shared" / name).write_text("", encoding="utf-8")
    (tmp / "_support" / "k.py").write_text("", encoding="utf-8")
    return tmp


def test_derive_matches_golden_vector(tmp_path: Path) -> None:
    facts = derive(_mk_repo(tmp_path))
    assert facts == {
        "校验器": "2",
        "校验器文件": "2",
        "出厂测试文件": "2",
        "自检声明": "3",
        "skills": "2",
        "环": "1",
        "共享契约": "3",
        "共享内核": "1",
        "最大单件文件": "scripts/big.py",
        "最大单件行数": "10",
        "用例数.test_a.py": "2",
        "用例数.test_b.py": "1",
    }, f"派生键不等于 golden 向量：{facts}"


@pytest.mark.parametrize("missing", ["rings", "shared", "_support", "skills", "tests"])
def test_missing_source_fails_loud(tmp_path: Path, missing: str) -> None:
    repo = _mk_repo(tmp_path)
    for child in sorted((repo / missing).rglob("*"), reverse=True):
        child.unlink() if child.is_file() else child.rmdir()
    (repo / missing).rmdir()
    with pytest.raises(SnapshotError) as ei:
        derive(repo)
    assert missing in str(ei.value), f"缺源 {missing} 必须点名并炸，不得静默 0"


def test_missing_install_py_fails_loud(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path)
    (repo / "install.py").unlink()
    with pytest.raises(SnapshotError) as ei:
        derive(repo)
    assert "install.py" in str(ei.value)


def test_unknown_token_key_fails_loud() -> None:
    with pytest.raises(SnapshotError) as ei:
        rewrite("值 〔数:没登记的键=1〕", {"校验器": "12"})
    assert "没登记的键" in str(ei.value), "未知键必须炸：否则该占位永远不会被门看到"


def test_rewrite_fixes_stale_value_and_is_idempotent() -> None:
    facts = {"出厂测试文件": "81", "校验器": "12"}
    text = "共 〔数:出厂测试文件=80〕 个；校验器 〔数:校验器:12〕"
    new, drifts = rewrite(text, facts)
    assert drifts == [("出厂测试文件", "80", "81")]
    assert "〔数:出厂测试文件=81〕" in new
    assert rewrite(new, facts) == (new, []), "重渲染必须幂等（否则门恒红）"


def test_per_file_gauge_ignores_phantom_tests_in_strings(tmp_path: Path) -> None:
    p = tmp_path / "test_x.py"
    p.write_text('def test_real():\n    pass\n\n\n_S = """\ndef test_phantom():\n    pass\n"""\n',
                 encoding="utf-8")
    assert count_tests(p) == 1, "字符串内嵌的幽灵 def test_ 不得计入（M10 教训）"


def test_per_file_gauge_parity_with_canonical() -> None:
    from test_canonical_consistency import _collected_test_count
    diffs = []
    for p in sorted((PKG_ROOT / "tests").glob("test_*.py")):
        a, b = count_tests(p), _collected_test_count(p)
        if a != b:
            diffs.append((p.name, a, b))
    assert not diffs, f"逐文件量具与 canonical 分叉：{diffs}"
