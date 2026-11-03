"""E2E 触发段（RFC-20261103-07 D2）的判据钉。

覆盖：归因提示词完备、委托命令构造（`--page` 走 atlas_check；否则优先 atlas_verify），
以及**绝不**调用生成器 `--apply` 的纪律。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
TRIGGER = PKG / "scripts" / "e2e_trigger.py"


def _load_trigger():
    # e2e_trigger 在模块内把自身目录插入 sys.path 后 import atlas_check；
    # 这里保证从源包 scripts/ 解析，而不是装入点的旧副本。
    sys.path.insert(0, str(PKG / "scripts"))
    spec = importlib.util.spec_from_file_location("e2e_trigger_under_test", TRIGGER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_hints_cover_every_reason():
    mod = _load_trigger()
    assert set(mod.HINTS) == set(mod.ac.E2E_SKIP_REASONS)


def test_delegate_prefers_verify_without_page(tmp_path, monkeypatch):
    mod = _load_trigger()
    scripts = tmp_path / ".atlas" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "atlas_verify.py").write_text("", encoding="utf-8")
    seen = {}

    def fake_call(cmd, cwd=None):
        seen["cmd"] = cmd
        seen["cwd"] = cwd
        return 0

    monkeypatch.setattr(mod.subprocess, "call", fake_call)
    assert mod._delegate(tmp_path, None) == 0
    assert seen["cmd"][1].endswith("atlas_verify.py")
    assert "--page" not in seen["cmd"]
    assert seen["cwd"] == str(tmp_path)


def test_delegate_page_uses_atlas_check(tmp_path, monkeypatch):
    mod = _load_trigger()
    scripts = tmp_path / ".atlas" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "atlas_verify.py").write_text("", encoding="utf-8")
    seen = {}

    def fake_call(cmd, cwd=None):
        seen["cmd"] = cmd
        return 0

    monkeypatch.setattr(mod.subprocess, "call", fake_call)
    assert mod._delegate(tmp_path, "project-list") == 0
    assert seen["cmd"][1].endswith("atlas_check.py")
    assert "--page" in seen["cmd"]
    assert "project-list" in seen["cmd"]


def test_delegate_never_invokes_generator():
    """纪律钉：委托段不得拼生成器命令（生成前必须有 E2E 环独立审查报告）。"""
    src = TRIGGER.read_text(encoding="utf-8")
    body = src[src.index("def _delegate"):src.index("def main")]
    assert "gen_e2e_scripts" not in body
