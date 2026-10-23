#!/usr/bin/env python3
"""`validators/validate_walkthrough.py` 回归测试（M1，`RFC-20261022-01` 批 1）。

对账平面 = **声明 ⇔ 凭据**：apply 的三问第 2 问答「是」⇒ 受影响域级 PRD 的走查节
必须有 `> 已确认：<日期>` 行。四态出口逐条钉死（评审 P1-1 / P1-2）：

  正控：确认行齐 ⇒ PASS；
  坏输入：是 + 无确认行 ⇒ FAIL / 确认行形态非法 ⇒ FAIL / 缺走查节 ⇒ FAIL /
          域级 PRD 不存在 ⇒ FAIL / 重派生只留说明行 ⇒ FAIL；
  解析面：第 2 问不可解析 ⇒ WARN（不是 SKIP——防写歪措辞静默旁路）/ 无第 2 问行 ⇒ WARN /
          是但受影响域解析不到 ⇒ WARN；
  时空域：已归档任务不扫 / 无 apply 记录 ⇒ SKIP / 第 2 问否 ⇒ SKIP / task 记录损坏 ⇒ SKIP。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
V_WALK = PKG_ROOT / "validators" / "validate_walkthrough.py"


def _load():
    spec = importlib.util.spec_from_file_location("validate_walkthrough_under_test", V_WALK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load()


def _task(root: Path, tid: str = "T1", status: str = "planning") -> Path:
    d = root / ".trellis" / "tasks" / tid
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.json").write_text(
        json.dumps({"id": tid, "title": "夹具", "status": status}, ensure_ascii=False),
        encoding="utf-8")
    return d


def _apply(d: Path, text: str) -> Path:
    p = d / "atlas-apply.md"
    p.write_text(text, encoding="utf-8")
    return p


APPLY_YES = """# T1 · 交付报告

## 2. 三问门判定

1. **这次是否改动既有能力**？是 → 有 PRD 基线
2. **这次是否需要人来确认应然 UI / 流程**？**是** ⇒ 派生走查并取得确认
3. **这次是否需要可重复的验收**？是

## 3. 影响面清单

- `product/prd/demo-prd.md`：新增旅程 1 条
"""

APPLY_UNCLEAR = APPLY_YES.replace(
    "2. **这次是否需要人来确认应然 UI / 流程**？**是** ⇒ 派生走查并取得确认",
    "2. **这次是否需要人来确认应然 UI / 流程**？看情况而定")
APPLY_NO = APPLY_YES.replace(
    "2. **这次是否需要人来确认应然 UI / 流程**？**是** ⇒ 派生走查并取得确认",
    "2. **这次是否需要人来确认应然 UI / 流程**？否（纯后端）")
APPLY_NO_Q2 = """## 2. 三问门判定

1. 是否改动既有能力？是

## 3. 影响面清单
- `product/prd/demo-prd.md`
"""
APPLY_NO_SECTION = """# 报告

## 1. 模式与需求 ID

apply T1
"""


def _prd(root: Path, domain: str = "demo", confirm: str | None = "2026-10-23",
         with_section: bool = True, template_note: bool = False) -> Path:
    d = root / "product" / "prd"
    d.mkdir(parents=True, exist_ok=True)
    lines = [f"# {domain} 域 PRD", "", "## 七、变更记录", "", "- 2026-10-23 初稿", ""]
    if with_section:
        lines += ["## 八、用户旅程走查", ""]
        if confirm is not None:
            lines += [f"> 已确认：{confirm}", ""]
        if template_note:
            lines += ["> [初稿无「已确认」行 = 未确认；重派生本节时必须删除旧的「已确认」行待重确认]", ""]
        lines += ["### 旅程 1：查看列表（FN-01）", "", "1. 入口：`/demo` ⇒ 列表可见"]
    p = d / f"{domain}-prd.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _checks(res) -> list[dict]:
    return res.checks


# ---------------------------------------------------------------- 正控


def test_confirmed_walkthrough_passes(tmp_path) -> None:
    d = _task(tmp_path)
    _apply(d, APPLY_YES)
    _prd(tmp_path)
    res = MOD.run(tmp_path)
    assert res.status == "PASS", _checks(res)
    assert any(c["status"] == "PASS" and "demo" in c["check"] for c in res.checks)


def test_main_exit_zero_and_json(tmp_path, capsys) -> None:
    d = _task(tmp_path)
    _apply(d, APPLY_YES)
    _prd(tmp_path)
    rc = MOD.main(["--root", str(tmp_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True and payload["status"] == "PASS"


# ---------------------------------------------------------------- 坏输入（必红）


def test_yes_without_confirmation_line_fails(tmp_path) -> None:
    d = _task(tmp_path)
    _apply(d, APPLY_YES)
    _prd(tmp_path, confirm=None)
    res = MOD.run(tmp_path)
    assert res.status == "FAIL", _checks(res)
    bad = [c for c in res.checks if c["status"] == "FAIL"]
    assert bad and "demo" in bad[0]["check"] and "demo-prd.md" in bad[0]["detail"]
    assert MOD.main(["--root", str(tmp_path)]) == 1


def test_rederived_section_with_only_template_note_fails(tmp_path) -> None:
    """重派生删确认行后只剩模板说明行 —— 说明行不得被当成确认凭据。"""
    d = _task(tmp_path)
    _apply(d, APPLY_YES)
    _prd(tmp_path, confirm=None, template_note=True)
    res = MOD.run(tmp_path)
    assert res.status == "FAIL", _checks(res)
    assert any("未确认" in c["detail"] or "已确认" in c["detail"]
               for c in res.checks if c["status"] == "FAIL")


def test_malformed_confirmation_line_fails(tmp_path) -> None:
    d = _task(tmp_path)
    _apply(d, APPLY_YES)
    _prd(tmp_path, confirm="待用户拍板")
    res = MOD.run(tmp_path)
    assert res.status == "FAIL", _checks(res)
    assert any("形态非法" in c["detail"] for c in res.checks if c["status"] == "FAIL")


def test_missing_walkthrough_section_fails(tmp_path) -> None:
    d = _task(tmp_path)
    _apply(d, APPLY_YES)
    _prd(tmp_path, with_section=False)
    res = MOD.run(tmp_path)
    assert res.status == "FAIL", _checks(res)
    assert any("缺「用户旅程走查」节" in c["detail"]
               for c in res.checks if c["status"] == "FAIL")


def test_missing_domain_prd_fails(tmp_path) -> None:
    d = _task(tmp_path)
    _apply(d, APPLY_YES)
    # 不建 demo-prd.md
    res = MOD.run(tmp_path)
    assert res.status == "FAIL", _checks(res)
    assert any("不存在" in c["detail"] for c in res.checks if c["status"] == "FAIL")


# ---------------------------------------------------------------- 解析面（WARN 不静默）


def test_unparseable_second_question_warns_not_skips(tmp_path) -> None:
    d = _task(tmp_path)
    _apply(d, APPLY_UNCLEAR)
    _prd(tmp_path, confirm=None)
    res = MOD.run(tmp_path)
    assert res.status == "WARN", _checks(res)
    assert any("不可解析" in c["detail"] for c in res.checks if c["status"] == "WARN")
    assert MOD.main(["--root", str(tmp_path)]) == 0  # WARN 不置红


def test_missing_second_question_line_warns(tmp_path) -> None:
    d = _task(tmp_path)
    _apply(d, APPLY_NO_Q2)
    _prd(tmp_path, confirm=None)
    res = MOD.run(tmp_path)
    assert res.status == "WARN", _checks(res)
    assert any("无第 2 问行" in c["detail"] for c in res.checks if c["status"] == "WARN")


def test_yes_without_domain_reference_warns(tmp_path) -> None:
    d = _task(tmp_path)
    _apply(d, APPLY_YES.replace("`product/prd/demo-prd.md`：新增旅程 1 条", "（影响面见会话）"))
    _prd(tmp_path, confirm=None)
    res = MOD.run(tmp_path)
    assert res.status == "WARN", _checks(res)
    assert any("受影响域不可解析" in c["detail"] for c in res.checks if c["status"] == "WARN")


# ---------------------------------------------------------------- 时空域 / SKIP


def test_archived_task_is_not_scanned(tmp_path) -> None:
    d = _task(tmp_path, status="completed")
    _apply(d, APPLY_YES)
    _prd(tmp_path, confirm=None)  # 确认行缺失，但在归档域外 ⇒ 不得红
    res = MOD.run(tmp_path)
    assert res.status == "SKIP", _checks(res)


def test_no_apply_record_skips(tmp_path) -> None:
    _task(tmp_path)
    res = MOD.run(tmp_path)
    assert res.status == "SKIP", _checks(res)
    assert any("无 atlas-apply.md" in c["detail"] for c in res.checks)


def test_second_question_no_skips(tmp_path) -> None:
    d = _task(tmp_path)
    _apply(d, APPLY_NO)
    _prd(tmp_path, confirm=None)
    res = MOD.run(tmp_path)
    assert res.status == "SKIP", _checks(res)
    assert any("第 2 问＝否" in c["detail"] for c in res.checks)


def test_no_question_section_skips(tmp_path) -> None:
    d = _task(tmp_path)
    _apply(d, APPLY_NO_SECTION)
    res = MOD.run(tmp_path)
    assert res.status == "SKIP", _checks(res)


def test_broken_task_record_skips_loudly_and_other_task_still_checked(tmp_path) -> None:
    broken = tmp_path / ".trellis" / "tasks" / "BAD"
    broken.mkdir(parents=True)
    (broken / "task.json").write_text("{not json", encoding="utf-8")
    (broken / "atlas-apply.md").write_text(APPLY_YES, encoding="utf-8")
    _prd(tmp_path, confirm=None)

    d = _task(tmp_path, tid="GOOD")
    _apply(d, APPLY_YES)
    res = MOD.run(tmp_path)
    skips = [c for c in res.checks if c["status"] == "SKIP" and "BAD" in c["check"]]
    fails = [c for c in res.checks if c["status"] == "FAIL" and "GOOD" in c["check"]]
    assert skips and "不可解析" in skips[0]["detail"], _checks(res)
    assert fails, _checks(res)  # 坏记录不吞掉健康任务的红色


def test_no_tasks_dir_skips(tmp_path) -> None:
    res = MOD.run(tmp_path)
    assert res.status == "SKIP", _checks(res)
    assert "未就绪" in res.checks[0]["detail"]


def test_unknown_status_is_visible_skip(tmp_path) -> None:
    """评审 P1-1：未知 / 变体 status 不得静默出域（手滑 `in-progress` 会整体绕过锁）。"""
    d = _task(tmp_path, status="in-progress")
    _apply(d, APPLY_YES)
    _prd(tmp_path, confirm=None)
    res = MOD.run(tmp_path)
    assert res.status == "SKIP", _checks(res)
    named = [c for c in res.checks if "in-progress" in c["detail"]]
    assert named and named[0]["status"] == "SKIP", _checks(res)


def test_conflicting_second_question_lines_warn_not_bypass(tmp_path) -> None:
    """评审 P1-2：小节里模板行「否」在前、真实判定「是」在后 ⇒ WARN，不得按首行 SKIP。"""
    text = APPLY_YES.replace(
        "## 2. 三问门判定\n\n",
        "## 2. 三问门判定\n\n"
        "2. **这次是否需要人来确认应然 UI / 流程**？否（引用的模板行）\n")
    d = _task(tmp_path)
    _apply(d, text)
    _prd(tmp_path, confirm=None)
    res = MOD.run(tmp_path)
    assert res.status == "WARN", _checks(res)
    assert any("不一致" in c["detail"] for c in res.checks if c["status"] == "WARN")
    assert not any(c["status"] == "SKIP" and "第 2 问＝否" in c["detail"] for c in res.checks)


def test_consistent_duplicate_second_question_lines_resolve(tmp_path) -> None:
    """多行一致（都答「是」）⇒ 正常取值并进入对账，不误判 WARN。"""
    text = APPLY_YES.replace(
        "## 2. 三问门判定\n\n",
        "## 2. 三问门判定\n\n"
        "2. **这次是否需要人来确认应然 UI / 流程**？是（引用模板）\n")
    d = _task(tmp_path)
    _apply(d, text)
    _prd(tmp_path, confirm=None)
    res = MOD.run(tmp_path)
    assert res.status == "FAIL", _checks(res)
