#!/usr/bin/env python3
"""`scripts/impact_reconcile.py` 对账门回归测试（B191-1，2026-10-07）。

夹具 = tmp git 仓库（base 提交 + 工作树改动）+ 手写 `impact.json`。四条线：

  1. **全等 ⇒ ok**：actual ⊆ predicted 且无漂移 ⇒ status=ok；
  2. **双向差集 ⇒ WARN 指名**：漏报（实际改动在预测集外）与多报（预测未改）双侧逐文件；
  3. **基准漂移 ⇒ WARN 指名**：报告 head ≠ 当前 HEAD、diff-base 不一致——不得静默对账；
  4. **响亮跳过**：impact.json 缺失 / 非 git ⇒ exit 3（SKIP 不是通过）。

变异证明（`gates.md` 2.1 行）：**M39** 摘掉差集检测 ⇒ 用例 2 红；**M40** 摘掉 head 漂移检查
⇒ 用例 3 红；还原逐字节一致。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
IR = PKG_ROOT / "scripts" / "impact_reconcile.py"


def _git(root: Path, *args: str) -> str:
    p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       cwd=str(root), capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, (args, p.stderr)
    return p.stdout


def mk_repo(root: Path) -> str:
    """base 提交（a.py + b.py），随后工作树改 b.py ⇒ actual = {b.py}。返回 base ref。"""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    (root / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (root / "b.py").write_text("def b():\n    return 2\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    base = _git(root, "rev-parse", "HEAD").strip()
    (root / "b.py").write_text("def b():\n    return 20\n", encoding="utf-8")
    return base


def mk_impact(root: Path, *, head: str, touched: list[str], paths: list[str] | None = None,
              layers: list[dict] | None = None, diff_base: str | None = None) -> Path:
    d = root / ".trellis" / "tasks" / "T1"
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "category": "impact",
        "head": head,
        "inputs": {"symbols": ["b"], "paths": paths or [], "diff_base": diff_base},
        "touched_files": touched,
        "layers": layers or [],
    }
    (d / "impact.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return d / "impact.json"


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(IR), "--root", str(root), *args],
                          capture_output=True, text=True, timeout=120)


def test_reconcile_equal_is_ok() -> None:
    """actual = {b.py} ⊆ predicted（touched=b.py）且 head/diff-base 一致 ⇒ ok。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        base = mk_repo(root)
        mk_impact(root, head=base, touched=["b.py"], diff_base=base)
        p = run(root, "--task", "T1", "--diff-base", base)
        assert p.returncode == 0, p.stdout + p.stderr
        out = json.loads((root / ".trellis" / "tasks" / "T1" / "impact-reconcile.json").read_text())
        assert out["status"] == "ok", out
        assert out["miss"] == [] and out["over"] == [], out


def test_reconcile_diff_sets_warn_and_name_files() -> None:
    """漏报（b.py 在预测外）+ 多报（c.py 未改）⇒ WARN 双侧逐文件指名。

    变异证明 M39：摘掉差集检测 ⇒ 本用例红（status 退回 ok、差集消失）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        base = mk_repo(root)
        mk_impact(root, head=base, touched=["c.py"], layers=[{"symbols": [], "files": ["d.py"]}],
                  diff_base=base)
        p = run(root, "--task", "T1", "--diff-base", base)
        assert p.returncode == 0, p.stdout + p.stderr
        out = json.loads((root / ".trellis" / "tasks" / "T1" / "impact-reconcile.json").read_text())
        assert out["status"] == "warn", out
        assert out["miss"] == ["b.py"], out          # 实际改动 b.py 不在预测集（c.py+d.py）
        assert out["over"] == ["c.py", "d.py"], out  # 预测的 c/d 均未改动
        assert any("漏报" in w for w in out["warns"]) and any("多报" in w for w in out["warns"])


def test_reconcile_head_drift_warns() -> None:
    """报告 head ≠ 当前 HEAD（base 之后有过提交）⇒ WARN 指名两个 head，不得静默对账。

    变异证明 M40：摘掉 head 漂移检查 ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        base = mk_repo(root)
        mk_impact(root, head="0" * 40, touched=["b.py"], diff_base=base)
        p = run(root, "--task", "T1", "--diff-base", base)
        out = json.loads((root / ".trellis" / "tasks" / "T1" / "impact-reconcile.json").read_text())
        assert out["status"] == "warn", out
        assert out["head_report"] == "0" * 40 and out["head_now"] == base, out
        assert any("基准 head 漂移" in w for w in out["warns"]), out


def test_reconcile_diff_base_mismatch_warns() -> None:
    """`--diff-base` ≠ `inputs.diff_base` ⇒ WARN 指名（两个基线不同 = 差集不可比）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        base = mk_repo(root)
        mk_impact(root, head=base, touched=["b.py"], diff_base="HEAD~1")
        p = run(root, "--task", "T1", "--diff-base", base)
        out = json.loads((root / ".trellis" / "tasks" / "T1" / "impact-reconcile.json").read_text())
        assert out["status"] == "warn", out
        assert any("diff-base 不一致" in w for w in out["warns"]), out


def test_reconcile_skips_loudly_without_report() -> None:
    """impact.json 缺失 ⇒ exit 3 + 指名路径（SKIP 不是通过）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        base = mk_repo(root)
        p = run(root, "--task", "NOPE", "--diff-base", base)
        assert p.returncode == 3, (p.returncode, p.stdout + p.stderr)
        assert "impact.json 不存在" in p.stdout, p.stdout


def _load_ir():
    spec = importlib.util.spec_from_file_location("atlas_ir_under_test", IR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    sys.exit(0)
