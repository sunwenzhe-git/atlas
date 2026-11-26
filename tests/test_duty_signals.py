#!/usr/bin/env python3
"""`scripts/duty_signals.sh` 运行态轨迹汇总回归与清洗门（RFC-20261126-03）。

变异证明：
  - M259：摘除 `ablation_id` / `SKIP` / `N/A` / 源仓遮蔽防护过滤 ⇒ 本文件对应测试必红。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
SIGNALS_SH = PKG_ROOT / "scripts" / "duty_signals.sh"


def _git(cwd: Path, *args: str) -> str:
    pr = subprocess.run(["git", "-C", str(cwd), *args], check=True,
                        capture_output=True, text=True)
    return pr.stdout.strip()


def _make_minimal_repo(root: Path, *, is_source: bool = True) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(SIGNALS_SH, root / "scripts" / "duty_signals.sh")
    (root / "duty-review").mkdir(parents=True, exist_ok=True)
    (root / "duty-review" / "families.py").write_text(
        "import sys\nprint('{}' if '--json' in sys.argv else 'ok')\n",
        encoding="utf-8",
    )
    if is_source:
        (root / "install.py").write_text("# source marker\n", encoding="utf-8")
        (root / "rings" / "prd").mkdir(parents=True, exist_ok=True)
        (root / "rings" / "prd" / "reference.md").write_text("# prd\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")


def test_duty_signals_avoids_source_self_shadowing(tmp_path: Path) -> None:
    """M259：Atlas 源仓无兄弟 atlas-playground 时跳过，不得读取源仓自身全 SKIP 噪声。"""
    src = tmp_path / "atlas"
    _make_minimal_repo(src, is_source=True)
    (src / ".atlas" / "runs").mkdir(parents=True)
    (src / ".atlas" / "runs" / "check-events.jsonl").write_text(
        json.dumps({"timestamp": "2026-11-26T01:00:00", "git_dirty": False,
                    "rows": [{"name": "source_skip_noise", "status": "SKIP", "duration_ms": 99}]}) + "\n",
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k != "ATLAS_PLAYGROUND_ROOT"}
    pr = subprocess.run(["bash", str(src / "scripts" / "duty_signals.sh"), "yesterday"],
                        cwd=str(src), env=env, capture_output=True, text=True, timeout=60)
    assert pr.returncode == 0, pr.stderr
    assert "(无 check-events.jsonl，跳过)" in pr.stdout
    assert "source_skip_noise" not in pr.stdout


def test_duty_signals_filters_ablation_skip_na_and_dirty_wip(tmp_path: Path) -> None:
    """M259：过滤 ablation_id、SKIP/N/A/null、拆分 git_dirty WIP 与 clean 摩擦热点。"""
    src = tmp_path / "atlas"
    _make_minimal_repo(src, is_source=True)
    pg = tmp_path / "atlas-playground"
    (pg / ".atlas" / "runs").mkdir(parents=True)
    events = [
        # 消融实验行：必须被过滤，不计入摩擦热点
        {"timestamp": "2026-11-26T01:00:00", "git_dirty": False, "ablation_id": "ab-01",
         "rows": [{"name": "ablation_only_fail", "status": "FAIL", "duration_ms": 50}]},
        # WIP dirty 行：计入 wip_dirty，不进 clean 摩擦热点
        {"timestamp": "2026-11-26T02:00:00", "git_dirty": True, "ablation_id": None,
         "rows": [{"name": "wip_dirty_fail", "status": "FAIL", "duration_ms": 40}]},
        # clean 运行：含 N/A 高耗时噪声、null 耗时、真实摩擦、真实 0 触发高耗时
        {"timestamp": "2026-11-26T03:00:00", "git_dirty": False, "ablation_id": None,
         "rows": [
             {"name": "na_high_ms", "status": "N/A", "duration_ms": 999},
             {"name": "skip_high_ms", "status": "SKIP", "duration_ms": 888},
             {"name": "null_dur_ok", "status": "ok", "duration_ms": None},
             {"name": "real_friction_gate", "status": "WARN", "duration_ms": 20},
             {"name": "real_ablate_hint", "status": "ok", "duration_ms": 180},
         ]},
    ]
    raw_lines = [json.dumps(e) for e in events] + ["{broken-json-line"]
    (pg / ".atlas" / "runs" / "check-events.jsonl").write_text(
        "\n".join(raw_lines) + "\n", encoding="utf-8")

    env = dict(os.environ)
    env["ATLAS_PLAYGROUND_ROOT"] = str(pg)
    pr = subprocess.run(["bash", str(src / "scripts" / "duty_signals.sh"), "yesterday"],
                        cwd=str(src), env=env, capture_output=True, text=True, timeout=60)
    assert pr.returncode == 0, pr.stderr
    out = pr.stdout
    assert "clean=1 · wip_dirty=1 · ablation_filtered=1 · parse_errors=1" in out
    assert "real_friction_gate: FAIL=0 WARN=1" in out
    assert "real_ablate_hint: ok=1 median=180ms" in out
    for noise in ("ablation_only_fail", "wip_dirty_fail", "na_high_ms", "skip_high_ms", "null_dur_ok"):
        assert noise not in out


def test_duty_signals_finds_sibling_playground_from_detached_worktree(tmp_path: Path) -> None:
    """detached worktree 下通过 git-common-dir 仍可找到主仓同级 atlas-playground。"""
    src = tmp_path / "atlas"
    _make_minimal_repo(src, is_source=True)
    pg = tmp_path / "atlas-playground"
    (pg / ".atlas" / "runs").mkdir(parents=True)
    (pg / ".atlas" / "runs" / "check-events.jsonl").write_text(
        json.dumps({"timestamp": "2026-11-26T04:00:00", "git_dirty": False, "ablation_id": None,
                    "rows": [{"name": "sibling_gate", "status": "ok", "duration_ms": 77}]}) + "\n",
        encoding="utf-8",
    )
    wt = tmp_path / "detached-wt"
    _git(src, "worktree", "add", "--detach", str(wt), "HEAD")
    try:
        env = {k: v for k, v in os.environ.items() if k != "ATLAS_PLAYGROUND_ROOT"}
        pr = subprocess.run(["bash", str(wt / "scripts" / "duty_signals.sh"), "yesterday"],
                            cwd=str(wt), env=env, capture_output=True, text=True, timeout=60)
        assert pr.returncode == 0, pr.stderr
        assert "来源=sibling:atlas-playground" in pr.stdout
        assert "sibling_gate: ok=1 median=77ms" in pr.stdout
    finally:
        subprocess.run(["git", "-C", str(src), "worktree", "remove", "--force", str(wt)],
                       capture_output=True)
