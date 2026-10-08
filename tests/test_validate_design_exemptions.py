#!/usr/bin/env python3
"""`validators/validate_design_exemptions.py` 回归测试（`ATLAS-UPSTREAM #182`，2026-10-08）。

夹具 = 临时项目根（按需落 `product/design.md` 与 `.impeccable/config.json`）。
每件事各测两侧（**正例必须绿**，否则后面的红说明不了任何事）：

  1. **三态**：无档案 ⇒ SKIP（未就绪非失败，`§B120`）；有档案 ⇒ 真正跑对账；
  2. **双向集合相等 ⇒ PASS**（含「两侧皆空」的退化侧与「多条一致」侧）；
  3. **单侧漂移 ⇒ FAIL**：档案→配置缺（报警没真关）/ 配置→档案缺（关报警没台账），两侧各钉；
  4. **配置缺失 / 损坏**：档案已声明豁免而无 config ⇒ FAIL；JSON 坏 ⇒ FAIL（响亮）。

变异证明：
  * M43 摘掉双向差集判据（恒 PASS）⇒ `test_design_only_drift_fails` 与
    `test_config_only_drift_fails` 双红。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
VDE = PKG_ROOT / "validators" / "validate_design_exemptions.py"


def _load():
    spec = importlib.util.spec_from_file_location("validate_design_exemptions_under_test", VDE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load()

DESIGN_TMPL = """# 设计档案
- 判读：面向技术买家的 B2B SaaS 落地页，Linear 式极简语言
- 旋钮：DESIGN_VARIANCE 6 / MOTION_INTENSITY 4 / VISUAL_DENSITY 3（基线）
- 设计系统 / 审美家族：Tailwind utilities + Geist
- 强调色与主题：#5e6ad2；双模式
- 已有豁免：{exemptions}
"""


def _mkroot(tmp: Path, exemptions: str | None = None, ignore_rules: list | None = None,
            raw_config: str | None = None) -> Path:
    """搭夹具项目根。exemptions=None ⇒ 不落 design.md；ignore_rules=None ⇒ 不落 config。"""
    if exemptions is not None:
        d = tmp / "product"
        d.mkdir(parents=True, exist_ok=True)
        (d / "design.md").write_text(DESIGN_TMPL.format(exemptions=exemptions), encoding="utf-8")
    if raw_config is not None:
        c = tmp / ".impeccable"
        c.mkdir(parents=True, exist_ok=True)
        (c / "config.json").write_text(raw_config, encoding="utf-8")
    elif ignore_rules is not None:
        c = tmp / ".impeccable"
        c.mkdir(parents=True, exist_ok=True)
        (c / "config.json").write_text(
            json.dumps({"detector": {"ignoreRules": ignore_rules}}, ensure_ascii=False),
            encoding="utf-8")
    return tmp


def test_no_design_md_skips() -> None:
    """无档案 ⇒ SKIP + 退出码 0（未就绪不是失败，也不是通过）。"""
    with tempfile.TemporaryDirectory() as td:
        res = MOD.run(Path(td))
        assert res.status == "SKIP", res.checks
        assert res.ok is True
        assert "未就绪" in res.checks[0]["detail"]


def test_no_exemptions_no_config_passes() -> None:
    """档案存在、无 detect 豁免、无 config ⇒ PASS（合法退化态）。"""
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(Path(td), exemptions="无")
        res = MOD.run(root)
        assert res.status == "PASS", res.checks


def test_matching_sets_pass() -> None:
    """多条豁免双向一致 ⇒ PASS。"""
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(
            Path(td),
            exemptions="detect:gradient-text — 品牌渐变标题是本设计身份；detect:bounce-easing —  playful 基调需要",
            ignore_rules=["gradient-text", "bounce-easing"])
        res = MOD.run(root)
        assert res.status == "PASS", res.checks
        assert "2 条双向一致" in res.checks[-1]["detail"]


def test_design_only_drift_fails() -> None:
    """档案声明了豁免、配置没落 ⇒ FAIL 且指名缺失 id（M43 咬合面 ①）。"""
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(
            Path(td),
            exemptions="detect:gradient-text — 理由；detect:bounce-easing — 理由",
            ignore_rules=["gradient-text"])
        res = MOD.run(root)
        assert res.status == "FAIL", res.checks
        detail = res.checks[-1]["detail"]
        assert "档案有而配置缺" in detail
        assert "bounce-easing" in detail


def test_config_only_drift_fails() -> None:
    """配置关了报警、档案没记 ⇒ FAIL 且指名多余 id（M43 咬合面 ②）。"""
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(
            Path(td),
            exemptions="detect:gradient-text — 理由",
            ignore_rules=["gradient-text", "dark-glow"])
        res = MOD.run(root)
        assert res.status == "FAIL", res.checks
        assert "dark-glow" in res.checks[-1]["detail"]


def test_config_absent_with_exemptions_fails() -> None:
    """档案有 detect 豁免但 .impeccable/config.json 整个缺失 ⇒ FAIL。"""
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(Path(td), exemptions="detect:gradient-text — 理由", ignore_rules=None)
        res = MOD.run(root)
        assert res.status == "FAIL", res.checks
        assert "无 .impeccable/config.json" in res.checks[-1]["detail"]


def test_malformed_config_fails() -> None:
    """config JSON 损坏 ⇒ FAIL（响亮，不静默当无豁免）。"""
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(Path(td), exemptions="detect:gradient-text — 理由",
                       raw_config="{detector: ignoreRules=oops")
        res = MOD.run(root)
        assert res.status == "FAIL", res.checks
        assert "不可读" in res.checks[-1]["detail"]


def test_cli_json_shape_and_exit_codes() -> None:
    """CLI 契约：{ok,status,checks[]}；PASS/SKIP → 0，FAIL → 1（学 validate_prd 口径）。"""
    with tempfile.TemporaryDirectory() as td:
        root = _mkroot(Path(td), exemptions="detect:gradient-text — 理由", ignore_rules=[])
        p = subprocess.run(
            [sys.executable, str(VDE), "--root", str(root), "--json"],
            capture_output=True, text=True)
        assert p.returncode == 1
        payload = json.loads(p.stdout)
        assert payload["ok"] is False
        assert payload["status"] == "FAIL"
        assert isinstance(payload["checks"], list) and payload["checks"]
        assert {"check", "status", "detail"} <= set(payload["checks"][0])
        # SKIP 侧退出码 0
        with tempfile.TemporaryDirectory() as td2:
            p2 = subprocess.run(
                [sys.executable, str(VDE), "--root", td2, "--json"],
                capture_output=True, text=True)
            assert p2.returncode == 0
            assert json.loads(p2.stdout)["status"] == "SKIP"
