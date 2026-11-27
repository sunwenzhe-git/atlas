#!/usr/bin/env python3
"""Standard-library tests for the canonical bug-ledger validator."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support.bug_record import new_record, refresh_hashes, write_record
from validators import validate_bug_ledger as ledger

VALIDATOR = PKG_ROOT / "validators" / "validate_bug_ledger.py"


def git(root: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", "-c", "user.name=Atlas Test", "-c", "user.email=atlas-test@example.invalid", *args],
        cwd=root, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (args, result.stdout, result.stderr)


class BugLedgerValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="atlas-bug-ledger-")
        self.addCleanup(self.temp.cleanup)
        self.root = (Path(self.temp.name) / "repo").resolve()
        self.root.mkdir()
        git(self.root, "init", "-q")
        self._write("product/stack-profile.yaml", "origin: adopt\n")
        self._write("product/requirements/baseline/requirement.md",
                    "# baseline\n\n**类型**：初始需求\n**状态**：已确认\n")
        self._write("product/requirements/baseline/items.md",
                    "| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n"
                    "| R-01 | p1 | behavior | baseline behavior |\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "baseline")

    def _write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _requirement(self, slug: str, *, conclusion: str = "", evidence: str = "") -> Path:
        return self._write(
            f"product/requirements/{slug}/requirement.md",
            f"# {slug}\n\n**类型**：缺陷\n**关联需求**：baseline#R-01\n"
            f"**状态**：已收口\n**结论**：{conclusion}\n**证据**：{evidence}\n",
        )

    def _record(self, slug: str, dedupe_key: str) -> None:
        self._requirement(slug)
        req_root = self.root / "product" / "requirements" / slug
        report = b"shared report evidence\n"
        (req_root / "work").mkdir()
        (req_root / "work" / "缺陷报告.md").write_bytes(report)
        record = new_record(
            slug, "baseline#R-01", "test", hashlib.sha256(report).hexdigest())
        record["dedupe_key"] = dedupe_key
        refresh_hashes(record)
        write_record(req_root, record)

    def _assert_landing_failure(self, expected_path: str) -> None:
        result = ledger.validate(self.root)
        self.assertEqual(result.status, "FAIL", result.checks)
        failures = [item for item in result.checks if item["status"] == "FAIL"]
        self.assertTrue(any(item["check"] == "canonical_landing" for item in failures), failures)
        self.assertTrue(any(expected_path in item["detail"] for item in failures), failures)

    def test_rejects_atlas_bugs_landing(self) -> None:
        """M252：摘除 legacy 双落点扫描后，本用例必须红。"""
        self._write(".atlas/bugs/report.md", "# Legacy bug\n")
        self._assert_landing_failure(".atlas/bugs")

    def test_rejects_assets_bugs_with_legacy_type_or_kind(self) -> None:
        bugs = self.root / "product" / "bugs"
        for suffix in ("md", "json"):
            for key in ("type", "kind"):
                for value in ("bug", "缺陷", "defect"):
                    with self.subTest(suffix=suffix, key=key, value=value):
                        shutil.rmtree(bugs, ignore_errors=True)
                        text = (f"{key}: {value}\n" if suffix == "md"
                                else json.dumps({key: value}, ensure_ascii=False) + "\n")
                        self._write(f"product/bugs/report.{suffix}", text)
                        self._assert_landing_failure("product/bugs")

    def test_allows_requirement_local_material_dirs(self) -> None:
        """#79：bugs/、changes/ 只是来源材料目录，不再按目录名判第二落点。"""
        self._write("product/requirements/bug-login/requirement.md",
                    "# bug-login\n\n**类型**：初始需求\n")
        self._write("product/requirements/bug-login/bugs/report.md", "# 现场材料\n")
        self._write("product/requirements/bug-login/Bugs/BUG-001.md",
                    "**类型**：缺陷\n\n历史报告正文\n")
        self._write("product/requirements/bug-login/changes/CHG-01/request.md",
                    "# 变更记录\n")
        result = ledger.validate(self.root)
        self.assertNotEqual(result.status, "FAIL", result.checks)
        self.assertTrue(any(item["check"] == "canonical_ledger" and item["status"] == "PASS"
                            for item in result.checks), result.checks)

    def test_rejects_nested_record_json(self) -> None:
        """机器台账只允许 req_root/record.json；任意嵌套、大小写、symlink 均拒。"""
        self._write("product/requirements/bug-login/requirement.md",
                    "# bug-login\n\n**类型**：初始需求\n")
        for rel in ("Bugs/Record.json", "work/bugs/record.json",
                    "changes/CHG-01/record.json"):
            self._write(f"product/requirements/bug-login/{rel}",
                        '{"schema_version": 1, "dedupe_key": "x"}\n')
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "record.json").write_text(
            '{"schema_version": 1, "backflow_status": "pending"}\n', encoding="utf-8")
        (self.root / "product" / "requirements" / "bug-login" / "linked").symlink_to(
            outside, target_is_directory=True)
        result = ledger.validate(self.root)
        self.assertEqual(result.status, "FAIL", result.checks)
        failures = [item for item in result.checks
                    if item["status"] == "FAIL" and item["check"] == "canonical_ledger"]
        self.assertTrue(failures, result.checks)
        for rel in ("Bugs/Record.json", "work/bugs/record.json",
                    "changes/CHG-01/record.json", "linked/record.json"):
            self.assertIn(rel, failures[0]["detail"], failures)

    def test_same_name_evidence_json_is_not_a_ledger(self) -> None:
        self._write("product/requirements/bug-login/requirement.md",
                    "# bug-login\n\n**类型**：初始需求\n")
        self._write("product/requirements/bug-login/bugs/record.json",
                    '{"schema_version": 1, "note": "现场抓包夹具"}\n')
        result = ledger.validate(self.root)
        self.assertEqual(result.status, "PASS", result.checks)

    def test_rejects_symlinked_legacy_bugs_directory(self) -> None:
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "report.md").write_text("type: bug\n", encoding="utf-8")
        (self.root / ".atlas").mkdir()
        (self.root / ".atlas" / "bugs").symlink_to(outside, target_is_directory=True)
        self._assert_landing_failure(".atlas/bugs")

    def test_rejects_symlinked_canonical_record(self) -> None:
        self._requirement("bug-login")
        outside = Path(self.temp.name) / "record.json"
        outside.write_text("{}\n", encoding="utf-8")
        (self.root / "product" / "requirements" / "bug-login" / "record.json").symlink_to(outside)
        result = ledger.validate(self.root)
        self.assertEqual(result.status, "FAIL", result.checks)
        self.assertTrue(any(
            item["status"] == "FAIL" and "record.json" in item["check"]
            and "symlink" in item["detail"] for item in result.checks
        ), result.checks)

    def test_rejects_duplicate_dedupe_key(self) -> None:
        report_hash = hashlib.sha256(b"shared report evidence\n").hexdigest()
        dedupe_key = f"baseline#R-01:{report_hash}"
        self._record("bug-one", dedupe_key)
        single = ledger.validate(self.root)
        self.assertEqual(single.status, "PASS", single.checks)
        self._record("bug-two", dedupe_key)
        duplicate = ledger.validate(self.root)
        self.assertEqual(duplicate.status, "FAIL", duplicate.checks)
        self.assertTrue(any(
            item["status"] == "FAIL" and "dedupe_key" in item["detail"]
            for item in duplicate.checks
        ), duplicate.checks)

    def test_requirement_change_record_passes_and_missing_record_fails(self) -> None:
        req_root = self.root / "product" / "requirements" / "change-one"
        req_root.mkdir(parents=True)
        (req_root / "requirement.md").write_text(
            "# change\n\n**类型**：需求变更\n**关联需求**：baseline#R-01\n**状态**：已收口\n",
            encoding="utf-8")
        (req_root / "work").mkdir()
        report = b"change request evidence\n"
        (req_root / "work" / "变更请求.md").write_bytes(report)
        missing = ledger.validate(self.root)
        self.assertEqual(missing.status, "FAIL", missing.checks)
        write_record(req_root, new_record(
            "change-one", "baseline#R-01", "prod", hashlib.sha256(report).hexdigest(),
            report_path="work/变更请求.md"))
        valid = ledger.validate(self.root)
        self.assertEqual(valid.status, "PASS", valid.checks)
        record = json.loads((req_root / "record.json").read_text(encoding="utf-8"))
        record["dedupe_key"] = f"baseline#R-01:{record['report']['sha256']}"
        refresh_hashes(record)
        (req_root / "record.json").write_text(json.dumps(record, ensure_ascii=False),
                                               encoding="utf-8")
        invalid = ledger.validate(self.root)
        self.assertEqual(invalid.status, "FAIL", invalid.checks)

    def test_legacy_and_typed_defect_keys_dedupe_semantically(self) -> None:
        report_hash = hashlib.sha256(b"shared report evidence\n").hexdigest()
        self._record("bug-one", f"baseline#R-01:{report_hash}")
        self._record("bug-two", f"缺陷:work/缺陷报告.md:baseline#R-01:{report_hash}")
        result = ledger.validate(self.root)
        self.assertEqual(result.status, "FAIL", result.checks)
        self.assertTrue(any("dedupe_key" in item["detail"] for item in result.checks
                            if item["status"] == "FAIL"), result.checks)

    def test_valid_triage_without_record_passes_validator_cli(self) -> None:
        self._requirement("triage-duplicate", conclusion="重复", evidence="与 bug-one 重复")
        self.assertFalse((self.root / "product" / "requirements" / "triage-duplicate" / "record.json").exists())
        direct = ledger.validate(self.root)
        self.assertEqual(direct.status, "PASS", direct.checks)
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), "--root", str(self.root), "--json"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "PASS")
        self.assertFalse(any(item["status"] == "FAIL" for item in payload["checks"]))


    def test_not_applicable_requires_conclusion_and_evidence(self) -> None:
        req_root = self.root / "product/requirements" / "triage"
        self._requirement("triage")
        report = b"triage evidence\n"
        (req_root / "work").mkdir()
        (req_root / "work" / "缺陷报告.md").write_bytes(report)
        record = new_record("triage", "baseline#R-01", "test", hashlib.sha256(report).hexdigest())
        record["backflow_status"] = "not_applicable"
        refresh_hashes(record)
        (req_root / "record.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        result = ledger.validate(self.root)
        self.assertEqual(result.status, "FAIL", result.checks)
        self.assertTrue(any("合法分诊结论" in item["detail"] or "非空证据" in item["detail"]
                            for item in result.checks if item["status"] == "FAIL"), result.checks)

    def test_not_applicable_rejects_task_reference(self) -> None:
        req_root = self.root / "product/requirements" / "triage"
        self._requirement("triage", conclusion="重复", evidence="与 bug-one 重复")
        report = b"triage evidence\n"
        (req_root / "work").mkdir()
        (req_root / "work" / "缺陷报告.md").write_bytes(report)
        record = new_record("triage", "baseline#R-01", "test", hashlib.sha256(report).hexdigest())
        record["backflow_status"] = "not_applicable"
        refresh_hashes(record)
        write_record(req_root, record)
        self._write(".atlas/tasks/T-1/task.json", json.dumps({
            "id": "T-1", "title": "triage", "status": "todo", "depends_on": [],
            "affected_domains": [], "acs": [], "created_at": "2026-01-01",
            "requirement_root": "product/requirements/triage",
        }, ensure_ascii=False))
        result = ledger.validate(self.root)
        self.assertEqual(result.status, "FAIL", result.checks)
        self.assertTrue(any("not_applicable 不得被任务卡引用" in item["detail"]
                            for item in result.checks if item["status"] == "FAIL"), result.checks)

    def test_rejects_standalone_defect_without_related_requirement(self) -> None:
        """M254：缺陷缺关联需求时必须被拒绝。"""
        req = self._requirement("standalone")
        req.write_text(req.read_text(encoding="utf-8").replace(
            "**关联需求**：baseline#R-01\n", ""), encoding="utf-8")
        result = ledger.validate(self.root)
        self.assertEqual(result.status, "FAIL", result.checks)
        self.assertTrue(any("关联需求" in item["detail"]
                            for item in result.checks if item["status"] == "FAIL"), result.checks)


    def test_flat_and_work_report_shapes_share_dedupe(self) -> None:
        """同一证据换路径形态仍是重复：work/ 与扁平按文件名归一。"""
        report = b"same evidence\n"
        digest = hashlib.sha256(report).hexdigest()
        for slug, report_rel in (("bug-work", "work/缺陷报告.md"),
                                 ("bug-flat", "缺陷报告.md")):
            self._requirement(slug)
            req_root = self.root / "product" / "requirements" / slug
            path = req_root / report_rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(report)
            record = new_record(slug, "baseline#R-01", "test", digest,
                                report_path=report_rel)
            write_record(req_root, record)
        result = ledger.validate(self.root)
        self.assertEqual(result.status, "FAIL", result.checks)
        self.assertTrue(any("dedupe_key" in item["detail"] for item in result.checks
                            if item["status"] == "FAIL"), result.checks)

    def test_flat_report_path_and_ambiguity(self) -> None:
        """#79：扁平报告与 work/ 等价；两份并存 ⇒ 歧义（有无 record 都拦）。"""
        req_root = self.root / "product" / "requirements" / "bug-flat"
        req_root.mkdir(parents=True)
        (req_root / "requirement.md").write_text(
            "# bug\n\n**类型**：缺陷\n**关联需求**：baseline#R-01\n**状态**：已收口\n",
            encoding="utf-8")
        report = b"flat report evidence\n"
        (req_root / "缺陷报告.md").write_bytes(report)
        (req_root / "work").mkdir()
        (req_root / "work" / "缺陷报告.md").write_bytes(report)
        ambiguous = ledger.validate(self.root)
        self.assertEqual(ambiguous.status, "FAIL", ambiguous.checks)
        self.assertTrue(any("歧义" in item["detail"] for item in ambiguous.checks
                            if item["status"] == "FAIL"), ambiguous.checks)
        (req_root / "work" / "缺陷报告.md").unlink()
        write_record(req_root, new_record(
            "bug-flat", "baseline#R-01", "test", hashlib.sha256(report).hexdigest(),
            report_path="缺陷报告.md"))
        flat = ledger.validate(self.root)
        self.assertEqual(flat.status, "PASS", flat.checks)


if __name__ == "__main__":
    unittest.main()
