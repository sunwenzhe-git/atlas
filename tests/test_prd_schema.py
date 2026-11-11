#!/usr/bin/env python3
"""B 批：PRD `prd_version` / `prd_schema` 与 Assumptions 证据列谓词（RFC §1.5）。"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from datetime import date
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def load_core():
    path = PKG_ROOT / "_support" / "solution.py"
    spec = importlib.util.spec_from_file_location("_atlas_solution_prd_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


core = load_core()


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "app.txt").write_text("app\n", encoding="utf-8")
    git(path, "add", "-A")
    git(path, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "init")
    return path


def stub_reader_version(monkeypatch, tmp_path: Path, version: str = "0.4.0") -> None:
    toolroot = tmp_path / "toolroot-prd-reader"
    toolroot.mkdir(exist_ok=True)
    (toolroot / "package.json").write_text(json.dumps({"version": version}),
                                           encoding="utf-8")
    monkeypatch.setattr(core, "_TOOL_PACKAGE_ROOT", toolroot)


PRD_TEMPLATE = """---
doc: prd-domain
domain: demo
domain_code: DEMO
version: 0.1.0
prd_version: 1
prd_schema: {schema}
date: "2026-11-11"
status: draft
---

# demo — 域级 PRD

## 六、Assumptions & Defaults

| {columns} |
|---|---|
| a | b | c | d |
"""

FOUR_COLUMNS = "假设内容 | 采用的默认值 | 影响面 | 何时需要澄清"
SIX_COLUMNS = FOUR_COLUMNS + " | 证据状态 | 证据指针"


def test_template_declares_prd_version_and_schema() -> None:
    """R1：真模板带 `prd_version: 1` / `prd_schema: 1`，B 批夹具直接用真模板。"""
    fm = core._front_matter_of(
        (PKG_ROOT / "templates" / "prd" / "domain.md").read_text(encoding="utf-8"))
    assert fm["prd_version"] == "1"
    assert fm["prd_schema"] == "1"


def test_prd_schema_2_requires_evidence_columns_immediately() -> None:
    """E-08：`prd_schema: 2` 缺两列 ⇒ 立即 FAIL，不享受 2027-06-30 缓冲。"""
    text = PRD_TEMPLATE.format(schema=2, columns=FOUR_COLUMNS)
    rows = core.prd_schema_findings(text, "product/prd/demo-prd.md", date(2026, 11, 11))
    assert rows[0][0] == "FAIL", rows
    assert "evidence_columns_missing" in rows[0][1]
    assert "证据状态" in rows[0][1] and "证据指针" in rows[0][1]

    ok = PRD_TEMPLATE.format(schema=2, columns=SIX_COLUMNS)
    assert core.prd_schema_findings(ok, "demo-prd.md", date(2026, 11, 11))[0][0] == "PASS"


def test_prd_schema_1_buffers_until_deadline() -> None:
    """E-03：`prd_schema: 1` 缺列，2027-06-30（含）前 WARN，2027-07-01 起 FAIL。"""
    text = PRD_TEMPLATE.format(schema=1, columns=FOUR_COLUMNS)
    last_day = core.prd_schema_findings(text, "demo-prd.md", date(2027, 6, 30))
    assert last_day[0][0] == "WARN"
    assert "evidence_deadline_approaching" in last_day[0][1]

    after = core.prd_schema_findings(text, "demo-prd.md", date(2027, 7, 1))
    assert after[0][0] == "FAIL"
    assert "evidence_columns_missing" in after[0][1]
    assert "到期" in after[0][1]


def test_prd_schema_missing_defaults_to_1() -> None:
    """未写 `prd_schema` 的存量 PRD 按 1 走缓冲，不直接 FAIL。"""
    text = PRD_TEMPLATE.format(schema=1, columns=FOUR_COLUMNS).replace("prd_schema: 1\n", "")
    rows = core.prd_schema_findings(text, "demo-prd.md", date(2026, 11, 11))
    assert rows[0][0] == "WARN" and "evidence_deadline_approaching" in rows[0][1]


def test_prd_schema_higher_than_supported_fails() -> None:
    """D-29 的 B 批子集：高于工具支持档位 ⇒ `prd_schema_unsupported`。"""
    text = PRD_TEMPLATE.format(schema=3, columns=FOUR_COLUMNS)
    rows = core.prd_schema_findings(text, "demo-prd.md", date(2026, 11, 11))
    assert rows[0][0] == "FAIL" and "prd_schema_unsupported" in rows[0][1]


def test_prd_without_assumptions_table_is_not_gated() -> None:
    """开户最小集 / 写「无」：没有证据行可挂，不判缺列（不制造假红）。"""
    text = "---\nprd_schema: 2\n---\n\n## 一、域概述\n\n无\n"
    rows = core.prd_schema_findings(text, "demo-prd.md", date(2027, 7, 1))
    assert rows[0][0] == "PASS", rows
    assert "未声明 Assumptions 表" in rows[0][1]


def test_migrate_backfills_prd_front_matter_without_overwriting(tmp_path: Path) -> None:
    """§5.2 第 6 条：migrate 给 PRD 补 prd_version / prd_schema；已有值不动、幂等。"""
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")], install=False)
    prd = tmp_path / "product" / "prd" / "solution-prd.md"
    text = prd.read_text(encoding="utf-8")
    prd.write_text(re.sub(r"^prd_(version|schema):.*\n", "", text, flags=re.M),
                   encoding="utf-8")

    result = core.migrate_manifest(tmp_path)
    assert result["added"][-2:] == ["prd_version", "prd_schema"]
    fm = core._prd_front_matter(prd)
    assert fm["prd_version"] == "1" and fm["prd_schema"] == "1"

    again = core.migrate_manifest(tmp_path)
    assert again["added"] == [] and again["changed"] is False

    # 已有值不覆盖：人手写的 7 / 2 原样保留
    prd.write_text(prd.read_text(encoding="utf-8").replace(
        "prd_version: 1", "prd_version: 7").replace(
        "prd_schema: 1", "prd_schema: 2"), encoding="utf-8")
    before = prd.read_text(encoding="utf-8")
    core.migrate_manifest(tmp_path)
    assert prd.read_text(encoding="utf-8") == before


def test_init_040_writes_prd_fields_into_prd_and_lock(
        tmp_path: Path, monkeypatch) -> None:
    """V-13 延伸：0.4.0 init 的 PRD front matter 与锁 definition 都带两个字段。"""
    stub_reader_version(monkeypatch, tmp_path)
    make_repo(tmp_path / "web")
    core.init_solution(tmp_path, "demo", [("web", "web", "frontend")], install=False)

    prd = tmp_path / "product" / "prd" / "solution-prd.md"
    fm = core._prd_front_matter(prd)
    assert fm["prd_version"] == "1" and fm["prd_schema"] == "1"

    lock = json.loads((tmp_path / core.LOCK_NAME).read_text(encoding="utf-8"))
    assert lock["definition"]["prd_version"] == 1
    assert lock["definition"]["prd_schema"] == 1

    rows = [c for c in core.check_solution(tmp_path)["checks"]
            if c["check"] == "PRD 证据列"]
    assert len(rows) == 1 and rows[0]["status"] == "WARN", rows
    assert "evidence_deadline_approaching" in rows[0]["detail"]
