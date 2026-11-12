#!/usr/bin/env python3
"""任务卡 C 批夹具：专用行 / none / AC 右集 / 跟踪前置 / Confirmed 证据状态。"""
from __future__ import annotations

import importlib.util
import subprocess
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
    "| 确认项 | 口径 | 证据状态 | 证据指针 | confirmed_review |\n"
    "|---|---|---|---|---|\n"
    "| 范围 | 本卡 | verified | PRD@1#AC-SOLUTION-001 | - |\n")


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
                  "| 确认项 | 口径 | 证据状态 | 证据指针 | confirmed_review |\n"
                  "|---|---|---|---|---|\n")


def test_k_confirmed_verified_requires_pointer(tmp_path: Path) -> None:
    root = new_repo(tmp_path, confirmed=(
        CONFIRMED_HEAD + "| 超时 | 30s | verified |  | - |\n"))
    assert "confirmed_evidence_missing" in codes(root)


def test_k_confirmed_verified_with_pointer_passes(tmp_path: Path) -> None:
    root = new_repo(tmp_path, confirmed=(
        CONFIRMED_HEAD + "| 超时 | 30s | verified | 网关@1.2#cfg.timeout | - |\n"))
    assert codes(root) == []


def test_k_confirmed_assumed_needs_only_pointer(tmp_path: Path) -> None:
    root = new_repo(tmp_path, confirmed=(
        CONFIRMED_HEAD + "| 并发 | 100 | assumed | 默认值@v1#max | - |\n"))
    assert codes(root) == []


def test_k_confirmed_unverified_requires_review(tmp_path: Path) -> None:
    root = new_repo(tmp_path, confirmed=(
        CONFIRMED_HEAD + "| 灰度 | 10% | unverified |  |  |\n"))
    assert "confirmed_downgrade_unreviewed" in codes(root)


def test_k_confirmed_unverified_with_review_is_single_report(tmp_path: Path) -> None:
    root = new_repo(tmp_path, confirmed=(
        CONFIRMED_HEAD + "| 灰度 | 10% | unverified |  | REVIEW-20261112-01 |\n"))
    errors, _ = card.validate(root, today=PASS_DATE)
    assert errors == []
    assert "confirmed_unverified" not in [e["code"] for e in errors]


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
