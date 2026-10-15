#!/usr/bin/env python3
"""`validators/validate_adr.py` 回归测试（2026-10-13）。

夹具 = 临时项目根（按需落 `product/adr/*.md`）。
正反例全覆盖：
  1. 三态前置：无 `product/adr/` 或无文件 ⇒ SKIP；
  2. 格式完整合法 ⇒ PASS；
  3. 同号异名冲突（0001-a ⇔ 0001-b）⇒ WARN；
  4. 状态非法（如 draft）⇒ WARN；
  5. 关键章节缺失（如缺 Context/Decision）⇒ WARN；
  6. superseded 状态指向不存在后继 ⇒ WARN；
  7. accepted 状态决策内容为空 ⇒ WARN。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
V_ADR = PKG_ROOT / "validators" / "validate_adr.py"


def _load():
    spec = importlib.util.spec_from_file_location("validate_adr_under_test", V_ADR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load()


def _make_adr_file(tmp: Path, filename: str, content: str) -> Path:
    d = tmp / "product" / "adr"
    d.mkdir(parents=True, exist_ok=True)
    f = d / filename
    f.write_text(content, encoding="utf-8")
    return f


VALID_ADR_SAMPLE = """---
id: "0001"
title: "服务端 ffmpeg 多轨混音"
date: "2026-10-13"
status: "accepted"
---

# ADR-0001: 服务端 ffmpeg 多轨混音

## 一、背景与问题上下文 (Context)
前端 Web Audio API 缺乏对特定编码的跨平台硬解支持，多端兼容性差。

## 二、考虑过的备选方案 (Alternatives Considered)
1. 浏览器端合成 — 否决：长音频易 OOM。

## 三、最终架构裁决 (Decision)
统一在服务端通过 ffmpeg 异步合成，导出 mp3 与 srt 文本。

## 四、影响与后果 (Consequences)
- 正面收益：多端渲染一致性高。
- 负面代价：镜像需常驻 ffmpeg 二进制文件。
"""


def test_validate_adr_skip_when_dir_missing(tmp_path: Path):
    res = MOD.validate_adr(tmp_path)
    assert res.status == "SKIP"
    assert "无 product/adr/" in res.checks[0]["detail"]


def test_validate_adr_skip_when_dir_empty(tmp_path: Path):
    (tmp_path / "product" / "adr").mkdir(parents=True, exist_ok=True)
    res = MOD.validate_adr(tmp_path)
    assert res.status == "SKIP"
    assert "尚无 ADR 文件" in res.checks[0]["detail"]


def test_validate_adr_pass_valid(tmp_path: Path):
    _make_adr_file(tmp_path, "0001-ffmpeg-audio.md", VALID_ADR_SAMPLE)
    res = MOD.validate_adr(tmp_path)
    assert res.status == "PASS"
    assert res.ok


def test_validate_adr_warn_duplicate_id(tmp_path: Path):
    _make_adr_file(tmp_path, "0001-ffmpeg-audio.md", VALID_ADR_SAMPLE)
    _make_adr_file(tmp_path, "0001-cgc-graph.md", VALID_ADR_SAMPLE)
    res = MOD.validate_adr(tmp_path)
    assert res.status == "WARN"
    assert any("编号冲突" in c["detail"] for c in res.checks)


def test_validate_adr_warn_invalid_status(tmp_path: Path):
    bad = VALID_ADR_SAMPLE.replace('status: "accepted"', 'status: "draft"')
    _make_adr_file(tmp_path, "0001-ffmpeg-audio.md", bad)
    res = MOD.validate_adr(tmp_path)
    assert res.status == "WARN"
    assert any("状态 'draft' 非法" in c["detail"] for c in res.checks)


def test_validate_adr_warn_missing_sections(tmp_path: Path):
    bad = """---
id: "0001"
title: "测试缺少章节"
date: "2026-10-13"
status: "proposed"
---

# ADR-0001
## 一、背景与问题上下文 (Context)
仅有背景。
"""
    _make_adr_file(tmp_path, "0001-ffmpeg-audio.md", bad)
    res = MOD.validate_adr(tmp_path)
    assert res.status == "WARN"
    assert any("缺失必要章节" in c["detail"] for c in res.checks)


def test_validate_adr_warn_broken_superseded_link(tmp_path: Path):
    bad = VALID_ADR_SAMPLE.replace('status: "accepted"', 'status: "superseded"\nsuperseded_by: "9999"')
    _make_adr_file(tmp_path, "0001-ffmpeg-audio.md", bad)
    res = MOD.validate_adr(tmp_path)
    assert res.status == "WARN"
    assert any("superseded 状态未指向有效的新 ADR" in c["detail"] for c in res.checks)


def test_validate_adr_warn_accepted_empty_decision(tmp_path: Path):
    bad = VALID_ADR_SAMPLE.replace('统一在服务端通过 ffmpeg 异步合成，导出 mp3 与 srt 文本。', '[必填：方案结论]')
    _make_adr_file(tmp_path, "0001-ffmpeg-audio.md", bad)
    res = MOD.validate_adr(tmp_path)
    assert res.status == "WARN"
    assert any("决策章节内容为空" in c["detail"] for c in res.checks)


def test_validate_adr_warn_cycle_detected(tmp_path: Path):
    """ADR 演进链成环检测：0001 -> 0002 -> 0003 -> 0001 拓扑成环 ⇒ WARN adr_cycle_detected。"""
    adr1 = VALID_ADR_SAMPLE.replace('status: "accepted"', 'status: "superseded"\nsuperseded_by: "0002"')
    adr2 = VALID_ADR_SAMPLE.replace('id: "0001"', 'id: "0002"').replace(
        'ADR-0001: 服务端 ffmpeg 多轨混音', 'ADR-0002: 二代音频'
    ).replace('status: "accepted"', 'status: "superseded"\nsuperseded_by: "0003"')
    adr3 = VALID_ADR_SAMPLE.replace('id: "0001"', 'id: "0003"').replace(
        'ADR-0001: 服务端 ffmpeg 多轨混音', 'ADR-0003: 三代音频'
    ).replace('status: "accepted"', 'status: "superseded"\nsuperseded_by: "0001"')

    _make_adr_file(tmp_path, "0001-audio-v1.md", adr1)
    _make_adr_file(tmp_path, "0002-audio-v2.md", adr2)
    _make_adr_file(tmp_path, "0003-audio-v3.md", adr3)

    res = MOD.validate_adr(tmp_path)
    assert res.status == "WARN"
    cycle_checks = [c for c in res.checks if c["check"] == "adr_cycle_detected"]
    assert cycle_checks, res.checks
    assert "演进链存在循环引用环路: 0001->0002->0003->0001" in cycle_checks[0]["detail"], cycle_checks
    # F36（R8 收束）：WARN 必须随身携带**机器可读修复指令**（superseded_by 移出环外）。
    assert "superseded_by" in cycle_checks[0]["detail"] and "移出环外" in cycle_checks[0]["detail"], cycle_checks
