#!/usr/bin/env python3
"""`atlas report` 上报体的形态判据（`shared/global-rules.md` §15）。

守两条契约要求（**弱判据，语义归人**）：
  1. **零业务上下文**：上报只描述设计问题 —— 上报体没有「业务背景」段，且带范围声明；
  2. **来源如实**：`--trigger user`（用户要求上报 = §15 类别 4 = 模型本轮漏认）
     不得被写成「Agent 自动感知归因」——池子的来源分布是这条契约的体检表。

判据只跑纯函数与 `--help`（不入网、不碰 GitHub：`main()` 的网络路径不在判据内）。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PKG_ROOT / "scripts" / "atlas_report.py"


def load_mod():
    spec = importlib.util.spec_from_file_location("atlas_report_mod", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_body_carries_no_business_context_section() -> None:
    """上报体只写设计问题：无「业务背景」段，且正文自述范围（不含产品名 / 业务名词 / 真实数据）。"""
    mod = load_mod()
    body = mod.format_markdown("t", "design-conflict", "提取器 X 在形态 Y 下机械冲突", "形态 Y",
                               "解耦建议", "校验器报错行")
    assert "业务背景" not in body, "上报体不得有业务背景段（§15 零业务上下文）"
    assert "零业务上下文" in body and "业务名词" in body, "上报体必须自述范围"
    for section in ("设计缺陷本体", "触发形态", "建议解法", "证据"):
        assert section in body, f"上报体缺段：{section}"


def test_trigger_user_is_not_labelled_as_auto_detected() -> None:
    """`--trigger user` ⇒ 来源写「漏认」，不得冒充自动感知（缺省 auto 仍写自动归因）。"""
    mod = load_mod()
    auto = mod.format_markdown("t", "bug", "c", "", "", "")
    user = mod.format_markdown("t", "bug", "c", "", "", "", trigger="user")
    assert "自动感知归因" in auto
    assert "自动感知归因" not in user and "漏认" in user, "用户触发的报告不得标成自动感知"


def test_cli_exposes_shape_and_no_business_context_field() -> None:
    """CLI 面：要的是**抽象触发形态**（`--shape`），不再有邀人填业务背景的 `--context`。"""
    res = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "--shape" in res.stdout, "缺少 --shape（抽象触发形态）"
    assert "--context" not in res.stdout, "不得再有 --context（会邀人上传业务背景）"
