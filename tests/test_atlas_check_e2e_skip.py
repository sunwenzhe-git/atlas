"""E2E 就绪归因（RFC-20261103-07 D1）的判据钉。

覆盖：五态归因（gate_off / not_declared / not_generated / app_login_undeclared /
env_not_ready）+ Row.add 的 extra 机读字段。归因不改变 SKIP 判定，只让状态可分辨。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
CK = PKG / "scripts" / "atlas_check.py"


def _load_ck():
    spec = importlib.util.spec_from_file_location("atlas_check_under_test", CK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _profile(tmp: Path, text: str) -> str:
    return text


def test_gate_off_when_no_cases_and_no_scripts(tmp_path):
    ck = _load_ck()
    cases = tmp_path / "cases"
    scripts = tmp_path / "scripts"
    assert ck.e2e_readiness("", cases, scripts, None) == "gate_off"


def test_not_declared_when_base_url_empty(tmp_path):
    ck = _load_ck()
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "p.md").write_text("---\n---\n", encoding="utf-8")
    scripts = tmp_path / "scripts"
    # 已有分片 ⇒ 不是 gate_off；base_url 未声明 ⇒ 缺决策先于缺工作
    assert ck.e2e_readiness("", cases, scripts, None) == "not_declared"


def test_not_generated_when_cases_exist_but_scripts_missing(tmp_path):
    ck = _load_ck()
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "p.md").write_text("---\n---\n", encoding="utf-8")
    scripts = tmp_path / "scripts"
    text = "e2e:\n  app_base_url: http://127.0.0.1:9/\n"
    assert ck.e2e_readiness(text, cases, scripts, None) == "not_generated"


def test_app_login_undeclared_when_ready_but_no_login_block(tmp_path):
    ck = _load_ck()
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "p.md").write_text("---\n---\n", encoding="utf-8")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "p.spec.ts").write_text("// x\n", encoding="utf-8")
    text = "e2e:\n  app_base_url: http://127.0.0.1:9/\n"
    assert ck.e2e_readiness(text, cases, scripts, None) == "app_login_undeclared"


def test_env_not_ready_when_login_declared_but_unreachable(tmp_path):
    ck = _load_ck()
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "p.md").write_text("---\n---\n", encoding="utf-8")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "p.spec.ts").write_text("// x\n", encoding="utf-8")
    text = ("e2e:\n  app_base_url: http://127.0.0.1:9/\n"
            "  app_login:\n    mode: none\n")
    assert ck.e2e_readiness(text, cases, scripts, None, reachable=False) == "env_not_ready"


def test_ready_returns_none(tmp_path):
    ck = _load_ck()
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "p.md").write_text("---\n---\n", encoding="utf-8")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "p.spec.ts").write_text("// x\n", encoding="utf-8")
    text = ("e2e:\n  app_base_url: http://127.0.0.1:9/\n"
            "  app_login:\n    mode: none\n")
    assert ck.e2e_readiness(text, cases, scripts, None, reachable=True) is None


def test_reason_enum_closed():
    ck = _load_ck()
    assert set(ck.E2E_SKIP_REASONS) == {
        "gate_off", "not_declared", "not_generated",
        "app_login_undeclared", "env_not_ready",
    }


def test_row_extra_merges_but_human_fields_unchanged():
    ck = _load_ck()
    rows = ck.Row()
    rows.add("E2E 真跑", "SKIP", "无脚本目录（门控态）",
             extra={"skip_reason": "gate_off"})
    row = rows.rows[0]
    assert row["status"] == "SKIP"
    assert row["detail"] == "无脚本目录（门控态）"
    assert row["skip_reason"] == "gate_off"
    assert rows.failed is False
