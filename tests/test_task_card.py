#!/usr/bin/env python3
"""任务卡 C 批夹具：专用行 / none / AC 右集 / 跟踪前置 / Confirmed 证据状态。"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "_v_card", PKG / "validators" / "validate_task_card.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


card = _load()
PASS_DATE = date(2026, 11, 12)
SCHEMA_2_PRD = "product/prd/web-prd.md"


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


CARD = ".trellis/tasks/01-x/prd.md"
POINTER = ".trellis/tasks/01-x/solution.md"


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


MINIMAL_CONFIRMED = (
    "## 六、Confirmed\n\n"
    "| 确认项 | 口径 | 证据状态 | 证据指针 |\n"
    "|---|---|---|---|\n"
    "| 范围 | 本卡 | verified | PRD@1#AC-SOLUTION-001 |\n")


def new_repo(tmp: Path, *, schema: int = 2, acceptance: str | None = None,
             confirmed: str = MINIMAL_CONFIRMED) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    git(tmp, "init", "-q")
    write(tmp, SCHEMA_2_PRD,
          "---\nprd_schema: 2\n---\n\n## 五、AC\n\n"
          "| AC | 描述 |\n|---|---|\n| AC-SOLUTION-001 | a |\n")
    write(tmp, POINTER, "# 指针\n\n- acs: AC-SOLUTION-001,AC-SOLUTION-002\n")
    body = "# 任务\n\n" + (acceptance if acceptance is not None
                           else "atlas-acceptance: AC-SOLUTION-001") + "\n"
    write(tmp, CARD, body + "\n" + confirmed)
    git(tmp, "add", "-A")
    git(tmp, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "cards")
    return tmp


def codes(root: Path, **kwargs) -> list[str]:
    errors, _ = card.validate(root, today=PASS_DATE, **kwargs)
    return [e["code"] for e in errors]


def test_k_valid_card_passes(tmp_path: Path) -> None:
    root = new_repo(tmp_path)
    assert codes(root) == []


def test_k_title_description_shell_does_not_count(tmp_path: Path) -> None:
    root = new_repo(tmp_path, acceptance=(
        "[AC-SOLUTION-001] R1\n\ndescription 跨仓任务 AC-SOLUTION-001"))
    assert "card_acceptance_missing" in codes(root)


def test_k_fenced_and_commented_lines_are_ignored(tmp_path: Path) -> None:
    acceptance = ("```text\natlas-acceptance: AC-SOLUTION-001\n```\n\n"
                  "<!--\natlas-acceptance: AC-SOLUTION-001\n-->")
    root = new_repo(tmp_path, acceptance=acceptance)
    assert "card_acceptance_missing" in codes(root)


def test_k_notes_do_not_change_projection(tmp_path: Path) -> None:
    root = new_repo(tmp_path)
    write(root, CARD, (root / CARD).read_text(encoding="utf-8")
          + "\n## Notes\n\n补充说明。\n")
    git(root, "add", "-A")
    git(root, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "notes")
    assert card.accepted_acs((root / CARD).read_text(encoding="utf-8"))[1] == \
        ["AC-SOLUTION-001"]


def test_k_ac_out_of_scope(tmp_path: Path) -> None:
    root = new_repo(tmp_path, acceptance="atlas-acceptance: AC-SOLUTION-009")
    assert "card_acceptance_out_of_scope" in codes(root)


def test_k_none_illegal_when_requirement_has_acs(tmp_path: Path) -> None:
    root = new_repo(
        tmp_path, acceptance="atlas-acceptance: none（reason=重构；owner=@a；due=2027-12-31）")
    assert "card_none_illegal" in codes(root)


def test_k_none_requires_three_fields(tmp_path: Path) -> None:
    root = new_repo(
        tmp_path, acceptance="atlas-acceptance: none（reason=重构；owner=@a）")
    write(root, POINTER, "# 指针\n\n- acs: \n")
    git(root, "add", "-A")
    git(root, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "empty acs")
    assert "card_none_fields_missing" in codes(root)


def test_k_none_due_expired(tmp_path: Path) -> None:
    root = new_repo(
        tmp_path, acceptance="atlas-acceptance: none（reason=重构；owner=@a；due=2020-01-01）")
    write(root, POINTER, "# 指针\n\n- acs: \n")
    git(root, "add", "-A")
    git(root, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "empty acs")
    assert "card_none_due_expired" in codes(root)


def test_k_untracked_card_is_fail(tmp_path: Path) -> None:
    root = new_repo(tmp_path)
    write(root, ".trellis/tasks/02-y/prd.md",
          "atlas-acceptance: AC-SOLUTION-001\n")
    write(root, ".trellis/tasks/02-y/solution.md", "- acs: AC-SOLUTION-001\n")
    assert "card_untracked" in codes(root)


def test_k_archive_card_hit(tmp_path: Path) -> None:
    root = new_repo(tmp_path)
    archived = ".trellis/tasks/archive/2026-11/01-old/prd.md"
    write(root, archived, "atlas-acceptance: AC-SOLUTION-001\n\n"
          + MINIMAL_CONFIRMED)
    write(root, ".trellis/tasks/archive/2026-11/01-old/solution.md",
          "- acs: AC-SOLUTION-001\n")
    git(root, "add", "-A")
    git(root, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "archive")
    assert codes(root) == []


CONFIRMED_HEAD = ("## 六、Confirmed\n\n"
                  "| 确认项 | 口径 | 证据状态 | 证据指针 |\n"
                  "|---|---|---|---|\n")


def test_k_confirmed_verified_requires_pointer(tmp_path: Path) -> None:
    root = new_repo(tmp_path, confirmed=(
        CONFIRMED_HEAD + "| 超时 | 30s | verified |  |\n"))
    assert "confirmed_evidence_missing" in codes(root)


def test_k_confirmed_verified_with_pointer_passes(tmp_path: Path) -> None:
    root = new_repo(tmp_path, confirmed=(
        CONFIRMED_HEAD + "| 超时 | 30s | verified | 网关@1.2#cfg.timeout |\n"))
    assert codes(root) == []


def test_k_confirmed_assumed_needs_only_pointer(tmp_path: Path) -> None:
    root = new_repo(tmp_path, confirmed=(
        CONFIRMED_HEAD + "| 并发 | 100 | assumed | 默认值@v1#max |\n"))
    assert codes(root) == []


def test_k_confirmed_unverified_requires_review(tmp_path: Path) -> None:
    root = new_repo(tmp_path, confirmed=(
        CONFIRMED_HEAD + "| 灰度 | 10% | unverified |  |\n"))
    t = codes(root)
    assert "confirmed_downgrade_unreviewed" in t
    assert "confirmed_unverified" in _warnings(root)


def test_k_confirmed_unverified_with_review_is_single_report(tmp_path: Path) -> None:
    root = new_repo(tmp_path, confirmed=(
        CONFIRMED_HEAD + "| 灰度 | 10% | unverified |  |\n\n"
        "confirmed_review: REVIEW-20261112-01\n"))
    errors, warnings = card.validate(root, today=PASS_DATE)
    assert errors == []
    assert "confirmed_unverified" not in [w["code"] for w in warnings]


def _warnings(root: Path) -> list[str]:
    _, warnings = card.validate(root, today=PASS_DATE)
    return [w["code"] for w in warnings]


def test_k_confirmed_columns_missing_schema2(tmp_path: Path) -> None:
    root = new_repo(tmp_path, confirmed="## 六、Confirmed\n\n无表。\n")
    assert "confirmed_columns_missing" in codes(root)


def test_k_confirmed_columns_missing_schema1_is_warn(tmp_path: Path) -> None:
    root = new_repo(tmp_path, confirmed="## 六、Confirmed\n\n无表。\n")
    write(root, SCHEMA_2_PRD, "---\nprd_schema: 1\n---\n")
    git(root, "add", "-A")
    git(root, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "schema1")
    errors, warnings = card.validate(root, today=PASS_DATE)
    assert "confirmed_columns_missing" not in [e["code"] for e in errors]
    assert "confirmed_columns_missing" in [w["code"] for w in warnings]


def test_k_confirmed_schema1_after_deadline_is_fail(tmp_path: Path) -> None:
    root = new_repo(tmp_path, confirmed="## 六、Confirmed\n\n无表。\n")
    write(root, SCHEMA_2_PRD, "---\nprd_schema: 1\n---\n")
    git(root, "add", "-A")
    git(root, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "schema1")
    errors, _ = card.validate(root, today=date(2027, 7, 1))
    assert "confirmed_columns_missing" in [e["code"] for e in errors]


def test_i6_card_absent_is_warn_on_member_side(tmp_path: Path) -> None:
    """成员侧不读父仓封条 ⇒ 无卡只能 WARN；FAIL 由父仓 `card_absent` 承担。"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    git(tmp_path, "init", "-q")
    (tmp_path / ".trellis").mkdir()
    (tmp_path / ".trellis" / "README.md").write_text("x\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "empty trellis")
    errors, warnings = card.validate(tmp_path, today=PASS_DATE)
    assert errors == []
    assert [w["code"] for w in warnings] == ["card_absent"]
    res = subprocess.run([sys.executable, str(PKG / "validators" / "validate_task_card.py"),
                          "--root", str(tmp_path)], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout
    assert "[WARN] card_absent" in res.stdout


def test_i6_no_seal_no_card_is_green(tmp_path: Path) -> None:
    """无封条无卡 ⇒ member 侧全绿（WARN 不改退出码）。"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    git(tmp_path, "init", "-q")
    (tmp_path / ".trellis").mkdir()
    (tmp_path / ".trellis" / "README.md").write_text("x\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "-c", "user.email=a@b", "-c", "user.name=a",
        "commit", "-qm", "empty trellis")
    res = subprocess.run([sys.executable, str(PKG / "validators" / "validate_task_card.py"),
                          "--root", str(tmp_path)], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout
    assert "[FAIL]" not in res.stdout


def test_i6_review_marker_only_counts_inside_confirmed_section(tmp_path: Path) -> None:
    """围栏里 / 注释里 / 无关章节里的 `confirmed_review:` 不得压掉降级未评审。"""
    marker = "confirmed_review: REVIEW-20261112-01\n"
    bodies = ("```text\n" + marker + "```\n",
              "<!--\n" + marker + "-->\n",
              "\n## 七、Notes\n\n" + marker)
    for index, body in enumerate(bodies):
        root = new_repo(tmp_path / f"case{index}", confirmed=(
            CONFIRMED_HEAD + "| 灰度 | 10% | unverified |  |\n\n" + body))
        assert "confirmed_downgrade_unreviewed" in codes(root), body


def test_delivery_gate_cli_exits_1_on_untracked_card(tmp_path: Path) -> None:
    root = new_repo(tmp_path)
    write(root, ".trellis/tasks/02-y/prd.md",
          "atlas-acceptance: AC-SOLUTION-001\n\n" + MINIMAL_CONFIRMED)
    write(root, ".trellis/tasks/02-y/solution.md", "- acs: AC-SOLUTION-001\n")
    res = subprocess.run(
        [sys.executable, str(PKG / "validators" / "validate_task_card.py"),
         "--root", str(root)], capture_output=True, text=True)
    assert res.returncode == 1
    assert "card_untracked" in res.stdout
