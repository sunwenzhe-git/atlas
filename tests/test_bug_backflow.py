#!/usr/bin/env python3
"""Standard-library regression tests for canonical defect backflow."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support import bug_backflow as backflow
from _support import bug_record as records
from scripts import atlas_bug

BUG_ID = "bug-login"
RELATED = "baseline#R-01"
RECORD_REL = f"product/requirements/{BUG_ID}/record.json"
REQUIREMENT_REL = f"product/requirements/{BUG_ID}/requirement.md"
REPORT_REL = f"product/requirements/{BUG_ID}/work/缺陷报告.md"
FIXED_AT = "2026-01-02T03:04:05+00:00"


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=Atlas Test", "-c", "user.email=atlas-test@example.invalid", *args],
        cwd=root, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result.stdout


def file_state(root: Path) -> dict[str, tuple[str, bytes | str]]:
    state: dict[str, tuple[str, bytes | str]] = {}
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if name != ".git")
        base = Path(current)
        for name in sorted(files):
            path = base / name
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                state[rel] = ("symlink", os.readlink(path))
            else:
                state[rel] = ("file", path.read_bytes())
    return state


class BugBackflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="atlas-bug-backflow-")
        self.addCleanup(self.temp.cleanup)
        self.root = (Path(self.temp.name) / "repo").resolve()
        self.root.mkdir()
        git(self.root, "init", "-q")
        self._write("src/service.py", "def calculate():\n    return 1\n")
        self._write("src/record.json", '{"implementation": 1}\n')
        self._write("baseline.txt", "symlink target\n")
        self._write("product/stack-profile.yaml", "origin: adopt\n")
        self._write(
            "product/requirements/baseline/requirement.md",
            "# 基线需求\n\n**类型**：初始需求\n**状态**：已确认\n",
        )
        self._write(
            "product/requirements/baseline/items.md",
            "# 条目\n\n| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n"
            "| R-01 | baseline#R-01 | 行为 | 登录失败不得继续 |\n",
        )
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "baseline")

    def _write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def _prepare_bug(self, *, code: str | None = None,
                     requirement_prefix: str = "", requirement_extra: str = "") -> Path:
        # Keep downstream cases independent from bootstrap's own coverage below.
        req_root = self.root / "product" / "requirements" / BUG_ID
        (req_root / "work").mkdir(parents=True)
        report = "现象：登录失败\n期望：可重试\n"
        requirement = (
            f"# 缺陷 {BUG_ID}\n\n**类型**：缺陷\n**关联需求**：{RELATED}\n**状态**：候选\n"
        )
        (req_root / "requirement.md").write_text(
            requirement_prefix + requirement + requirement_extra, encoding="utf-8", newline="",
        )
        (req_root / "items.md").write_text(
            "# 落点条目表\n\n| ID | 页码 | 章节 | 原文 |\n|---|---|---|---|\n"
            "| R-01 | baseline#R-01 | 关联需求 | 引用既有行为条款 |\n",
            encoding="utf-8", newline="",
        )
        (req_root / "work" / "缺陷报告.md").write_text(report, encoding="utf-8", newline="")
        record = records.new_record(BUG_ID, RELATED, "test", hashlib.sha256(report.encode()).hexdigest())
        records.write_record(req_root, record)
        if code is not None:
            self._write("src/service.py", code)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "bug intake")
        return req_root

    def _artifact_paths(self, req_root: Path) -> set[str]:
        return backflow.artifact_paths(self.root, req_root, records.read_record(req_root))

    def _stage_full_oids(self, *paths: str) -> None:
        # Isolate git's default abbreviation; the fingerprint test asserts full OIDs.
        git(self.root, "config", "core.abbrev", "40")
        git(self.root, "add", *paths)

    def _run_bug(self, *args: str) -> tuple[subprocess.CompletedProcess, dict]:
        result = subprocess.run(
            [sys.executable, str(PKG_ROOT / "scripts" / "atlas_bug.py"),
             "--root", str(self.root), "--json", *args],
            capture_output=True, text=True, timeout=120,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.fail(f"atlas_bug did not return JSON: rc={result.returncode}\n{result.stdout}\n{result.stderr}")
        return result, payload

    def _assert_unsupported(self, rel: str) -> None:
        req_root = self.root / "product" / "requirements" / BUG_ID
        with self.assertRaises(backflow.BackflowError) as raised:
            backflow.source_snapshot(self.root, "staged", None, self._artifact_paths(req_root))
        self.assertEqual(raised.exception.cause, "bug_backflow_unsupported_object_type")
        self.assertIn(rel, str(raised.exception))

    def _decision_fixture(self, tokens: tuple[str, ...] = ("E_LOGIN",)) -> tuple[Path, dict, Path]:
        code = "".join(f'VALUE_{index} = "{token}"\n' for index, token in enumerate(tokens))
        replacement_code = "".join(
            f'VALUE_{index} = "changed-{index}"\n' for index in range(len(tokens))
        )
        requirement_prefix = "---\nversion: 1.2.3\ndate: 2026-01-01\n---\n\n"
        requirement_extra = "\n" + "\n".join(f"文档引用 {token}" for token in tokens)
        requirement_extra += (
            "\n\n## 变更记录\n\n"
            "| 版本 | 日期 | 变更内容及原因 | 影响 | 结论与后续 |\n"
            "|---|---|---|---|---|\n"
            "| 1.2.3 | 2026-01-01 | 初稿 | 无 | 已校验 |\n"
        )
        req_root = self._prepare_bug(
            code=code, requirement_prefix=requirement_prefix,
            requirement_extra=requirement_extra,
        )
        self._write("src/service.py", replacement_code)
        self._stage_full_oids("src/service.py")
        result, payload = self._run_bug(
            "run", "--unit", BUG_ID, "--from", "staged", "--root-cause", "错误标识符已移除",
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(payload["status"], "conflict")
        record = records.read_record(req_root)
        self.assertEqual(record["backflow_status"], "needs_decision")
        # Every executable hunk also has an adapter-proof conflict.  Keep the
        # fixture focused on the identifier conflicts that carry exact old text.
        identifier_conflicts = [
            conflict for conflict in record["conflicts"]
            if conflict["old"] in tokens
        ]
        self.assertEqual(len(identifier_conflicts), len(tokens))
        requirement_bytes = (req_root / "requirement.md").read_bytes()
        decisions = []
        for index, conflict in enumerate(identifier_conflicts):
            decisions.append({
                "id": f"decision-{index + 1}", "conflict_id": conflict["id"],
                "path": REQUIREMENT_REL,
                "old_sha256": hashlib.sha256(requirement_bytes).hexdigest(),
                "old": conflict["old"], "new": "已确认移除",
                "by": "reviewer", "at": FIXED_AT, "conclusion": "文档与实现一致",
            })
        adapter_conflict = next(
            conflict for conflict in record["conflicts"]
            if "adapter" in conflict["reason"]
        )
        decisions.append({
            "id": f"decision-{len(tokens) + 1}",
            "conflict_id": adapter_conflict["id"], "path": REQUIREMENT_REL,
            "old_sha256": hashlib.sha256(requirement_bytes).hexdigest(),
            "old": f"# 缺陷 {BUG_ID}", "new": f"# 缺陷 {BUG_ID}",
            "by": "reviewer", "at": FIXED_AT, "conclusion": "行为语义已人工确认",
        })
        simulated = requirement_bytes.decode("utf-8")
        for decision in decisions:
            decision["old_sha256"] = hashlib.sha256(simulated.encode("utf-8")).hexdigest()
            simulated = simulated.replace(decision["old"], decision["new"], 1)
        decision_payload = {
            "bug": BUG_ID, "source_sha256": record["source"]["sha256"],
            "decisions": decisions,
        }
        decision_path = Path(self.temp.name) / "decisions.json"
        decision_path.write_text(json.dumps(decision_payload, ensure_ascii=False), encoding="utf-8")
        return req_root, decision_payload, decision_path

    def _assert_rejected_decision_writes_nothing(self, mutate, expected_message: str) -> None:
        req_root, payload, decision_path = self._decision_fixture(("E_LOGIN", "E_TIMEOUT"))
        mutate(payload)
        decision_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        before = file_state(self.root)
        result, output = self._run_bug(
            "run", "--unit", BUG_ID, "--from", "staged", "--root-cause", "错误标识符已移除",
            "--decision-file", str(decision_path),
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output["cause"], "bug_backflow_pending")
        self.assertIn(expected_message, output["message"])
        self.assertEqual(file_state(self.root), before, "rejected decision changed repository files")
        self.assertEqual(records.read_record(req_root)["backflow_status"], "needs_decision")

    def test_record_schema_roundtrip_and_history_genesis(self) -> None:
        req_root = self.root / "product" / "requirements" / "roundtrip-bug"
        (req_root / "work").mkdir(parents=True)
        report = b"roundtrip evidence\n"
        (req_root / "work" / "缺陷报告.md").write_bytes(report)
        (req_root / "requirement.md").write_text(
            "# Roundtrip\n\n**类型**：缺陷\n**关联需求**：baseline#R-01\n**状态**：候选\n",
            encoding="utf-8",
        )
        with patch.object(records, "utc_now", return_value=FIXED_AT):
            record = records.new_record(
                "roundtrip-bug", RELATED, "test", hashlib.sha256(report).hexdigest())
            genesis_hash = record["content_sha256"]
            records.append_history(
                record, "analysis", source_sha256=record["source"]["sha256"],
                document_sha256={"product/prd/demo-prd.md": "b" * 64},
            )
        records.write_record(req_root, record)
        loaded = records.read_record(req_root)
        self.assertEqual(loaded, record)
        self.assertEqual(records.validate_record(loaded, requirement_root=req_root), [])
        self.assertEqual(loaded["content_sha256"], records.record_content_hash(loaded))
        self.assertEqual(loaded["history"][0]["seq"], 1)
        self.assertEqual(loaded["history"][0]["event"], "bootstrap")
        self.assertIsNone(loaded["history"][0]["prev_content_sha256"])
        self.assertEqual(loaded["history"][1]["seq"], 2)
        self.assertEqual(loaded["history"][1]["prev_content_sha256"], genesis_hash)
        self.assertEqual(loaded["history"][1]["document_sha256"], {"product/prd/demo-prd.md": "b" * 64})

    def test_bootstrap_with_valid_related_requirement(self) -> None:
        req_root = backflow.bootstrap_defect(self.root, BUG_ID, RELATED, "现象\n", "prod")
        self.assertEqual(req_root, self.root / "product" / "requirements" / BUG_ID)
        fields, findings = backflow.strict_requirement_fields(req_root)
        self.assertEqual(findings, [])
        self.assertEqual(fields["类型"], "缺陷")
        self.assertEqual(fields["关联需求"], RELATED)
        report = (req_root / "work" / "缺陷报告.md").read_bytes()
        record = records.read_record(req_root)
        self.assertEqual(record["report"]["sha256"], hashlib.sha256(report).hexdigest())
        self.assertEqual(record["dedupe_key"],
                         f"缺陷:work/缺陷报告.md:{RELATED}:{record['report']['sha256']}")
        self.assertEqual(records.validate_record(record, requirement_root=req_root), [])

    def test_bootstrap_rejects_missing_related_baseline(self) -> None:
        shutil.rmtree(self.root / "product" / "requirements" / "baseline")
        with self.assertRaises(backflow.BackflowError) as raised:
            backflow.bootstrap_defect(self.root, BUG_ID, RELATED, "现象\n", "test")
        self.assertEqual(raised.exception.cause, "bug_backflow_missing")
        self.assertFalse((self.root / "product" / "requirements" / BUG_ID).exists())
        self.assertEqual(list((self.root / "product" / "requirements").glob(f".{BUG_ID}.*")), [])

    def test_staged_fingerprint_excludes_exact_artifacts_but_not_src_record(self) -> None:
        req_root = self._prepare_bug()
        self._write(REQUIREMENT_REL, (self.root / REQUIREMENT_REL).read_text(encoding="utf-8") + "\n文档产物\n")
        self._write(REPORT_REL, (self.root / REPORT_REL).read_text(encoding="utf-8") + "补充证据\n")
        self._write("product/prd/demo-prd.md", "# Demo PRD\n")
        record = records.read_record(req_root)
        record["root_cause"] = "文档产物不得进入实现指纹"
        record["report"]["sha256"] = hashlib.sha256((self.root / REPORT_REL).read_bytes()).hexdigest()
        record["dedupe_key"] = f"{RELATED}:{record['report']['sha256']}"
        records.refresh_hashes(record)
        records.write_record(req_root, record)
        self._write("src/record.json", '{"implementation": 2}\n')
        git(self.root, "add", REQUIREMENT_REL, REPORT_REL, "product/prd/demo-prd.md", RECORD_REL,
            "src/record.json")
        artifacts = {RECORD_REL, REQUIREMENT_REL, REPORT_REL, "product/prd/demo-prd.md"}
        snapshot = backflow.source_snapshot(self.root, "staged", None, artifacts)
        self.assertEqual([item["path"] for item in snapshot["implementation_files"]], ["src/record.json"])
        implementation = snapshot["implementation_files"][0]
        self.assertRegex(implementation["old_oid"], r"^[0-9a-f]{40}$")
        self.assertRegex(implementation["new_oid"], r"^[0-9a-f]{40}$")
        payload = {key: value for key, value in snapshot.items() if key != "sha256"}
        self.assertEqual(snapshot["sha256"], hashlib.sha256(records.canonical_bytes(payload)).hexdigest())

    def test_index_worktree_divergence_is_reported(self) -> None:
        req_root = self._prepare_bug()
        self._write("src/service.py", "def calculate():\n    return 2\n")
        git(self.root, "add", "src/service.py")
        snapshot = backflow.source_snapshot(self.root, "staged", None, self._artifact_paths(req_root))
        self._write("src/service.py", "def calculate():\n    return 3\n")
        findings = backflow.index_worktree_findings(self.root, snapshot, self._artifact_paths(req_root))
        self.assertIn("index/worktree 不一致：src/service.py", findings)

    def test_crlf_worktree_matching_index_is_not_divergence(self) -> None:
        req_root = self._prepare_bug()
        self._write("src/crlf.txt", "line one\nline two\n")
        git(self.root, "config", "core.autocrlf", "true")
        git(self.root, "add", "src/crlf.txt")
        snapshot = backflow.source_snapshot(self.root, "staged", None, self._artifact_paths(req_root))
        self.assertEqual(
            backflow.index_worktree_findings(self.root, snapshot, self._artifact_paths(req_root)),
            [])

    def test_artifact_index_worktree_divergence_is_reported(self) -> None:
        req_root = self._prepare_bug()
        record = records.read_record(req_root)
        record["root_cause"] = "staged root cause"
        records.refresh_hashes(record)
        records.write_record(req_root, record)
        git(self.root, "add", RECORD_REL)
        snapshot = backflow.source_snapshot(self.root, "staged", None, self._artifact_paths(req_root))
        record["root_cause"] = "unstaged root cause"
        records.refresh_hashes(record)
        records.write_record(req_root, record)
        findings = backflow.index_worktree_findings(self.root, snapshot, self._artifact_paths(req_root))
        self.assertIn(f"回推产物 index/worktree 不一致：{RECORD_REL}", findings)

    def test_new_symlink_is_unsupported(self) -> None:
        self._prepare_bug()
        try:
            (self.root / "src" / "link").symlink_to("../baseline.txt")
        except OSError as exc:
            if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
                self.skipTest("当前 Windows 用户没有创建符号链接的特权")
            raise
        git(self.root, "add", "src/link")
        self._assert_unsupported("src/link")

    def test_gitlink_is_unsupported(self) -> None:
        self._prepare_bug()
        nested = self.root / "src" / "vendor"
        nested.mkdir()
        git(nested, "init", "-q")
        (nested / "module.txt").write_text("nested module\n", encoding="utf-8")
        git(nested, "add", "module.txt")
        git(nested, "commit", "-qm", "nested module")
        git(self.root, "add", "src/vendor")
        self._assert_unsupported("src/vendor")

    def test_regular_file_to_symlink_type_change_is_unsupported(self) -> None:
        self._prepare_bug()
        path = self.root / "src" / "service.py"
        path.unlink()
        try:
            path.symlink_to("../baseline.txt")
        except OSError as exc:
            if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
                self.skipTest("当前 Windows 用户没有创建符号链接的特权")
            raise
        git(self.root, "add", "src/service.py")
        entries = backflow._raw_entries(self.root, "staged", None)
        self.assertEqual(entries[0]["status"], "T")
        self._assert_unsupported("src/service.py")

    def test_paths_only_spec_change_needs_decision(self) -> None:
        self._prepare_bug()
        self._write(
            ".atlas/spec/structure/domains/demo.md",
            "---\npaths:\n  - src/**\n---\n\n# Demo\n\nOnly path scope is known.\n",
        )
        git(self.root, "add", ".atlas/spec/structure/domains/demo.md")
        git(self.root, "commit", "-qm", "path scope")
        self._write("src/service.py", "def calculate():\n    return 2\n")
        self._stage_full_oids("src/service.py")
        result, payload = self._run_bug("run", "--unit", BUG_ID, "--from", "staged")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(payload["status"], "conflict")
        record = records.read_record(self.root / "product" / "requirements" / BUG_ID)
        self.assertEqual(record["backflow_status"], "needs_decision")
        self.assertTrue(any(item["action"] == "pending" for item in record["impact"]))
        self.assertTrue(any("adapter" in item["reason"] for item in record["conflicts"]))

    def test_same_identifier_executable_change_still_needs_decision(self) -> None:
        code = '<button data-testid="login-button">Old</button>\n'
        self._prepare_bug(requirement_extra="\n页面标识符 login-button。\n")
        self._write("src/page.html", code)
        git(self.root, "add", "src/page.html")
        git(self.root, "commit", "-qm", "page baseline")
        self._write("src/page.html", '<button data-testid="login-button" disabled>New</button>\n')
        self._stage_full_oids("src/page.html")
        result, payload = self._run_bug("run", "--unit", BUG_ID, "--from", "staged")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(payload["status"], "conflict")
        record = records.read_record(self.root / "product" / "requirements" / BUG_ID)
        self.assertEqual(record["backflow_status"], "needs_decision")
        self.assertFalse(any(item["action"] == "confirmed" for item in record["impact"]))
        self.assertTrue(any(item["action"] == "pending" for item in record["impact"]))
        self.assertTrue(any("adapter" in item["reason"] for item in record["conflicts"]))

    def test_decision_with_wrong_bug_writes_nothing(self) -> None:
        self._assert_rejected_decision_writes_nothing(
            lambda payload: payload.update(bug="other-bug"), "unit 与当前变更/缺陷不一致",
        )

    def test_decision_with_wrong_source_writes_nothing(self) -> None:
        self._assert_rejected_decision_writes_nothing(
            lambda payload: payload.update(source_sha256="0" * 64), "source_sha256",
        )

    def test_decision_with_wrong_old_hash_writes_nothing(self) -> None:
        def mutate(payload: dict) -> None:
            payload["decisions"][0]["old_sha256"] = "0" * 64
        self._assert_rejected_decision_writes_nothing(mutate, "摘要不匹配")

    def test_decision_that_leaves_conflict_old_value_writes_nothing(self) -> None:
        def mutate(payload: dict) -> None:
            target = next(item for item in payload["decisions"] if item["old"] == "E_LOGIN")
            target["new"] = "E_LOGIN 仍保留"
            text = (self.root / REQUIREMENT_REL).read_text(encoding="utf-8")
            for decision in payload["decisions"]:
                decision["old_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
                text = text.replace(decision["old"], decision["new"], 1)
        self._assert_rejected_decision_writes_nothing(mutate, "冲突旧值仍存在")

    def test_decision_with_partial_conflict_coverage_writes_nothing(self) -> None:
        def mutate(payload: dict) -> None:
            payload["decisions"].pop()
        self._assert_rejected_decision_writes_nothing(mutate, "未覆盖全部 conflict")

    def test_successful_decision_updates_document_version_change_and_record(self) -> None:
        req_root, _payload, decision_path = self._decision_fixture()
        result, output = self._run_bug(
            "run", "--unit", BUG_ID, "--from", "staged", "--root-cause", "错误标识符已移除",
            "--decision-file", str(decision_path),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output["status"], "ok")
        requirement = (req_root / "requirement.md").read_text(encoding="utf-8")
        self.assertIn("version: 1.2.4", requirement)
        self.assertIn("decision-1", requirement)
        self.assertIn(f"{BUG_ID} 缺陷回推", requirement)
        record = records.read_record(req_root)
        self.assertEqual(record["backflow_status"], "applied")
        self.assertEqual(records.validate_record(record, requirement_root=req_root), [])
        self.assertEqual(
            [item["id"] for item in record["decisions"]],
            ["decision-1", "decision-2"],
        )
        self.assertTrue(all(item["status"] == "resolved" for item in record["conflicts"]))
        document = record["documents"][0]
        self.assertEqual(document["path"], REQUIREMENT_REL)
        self.assertEqual(document["action"], "update")
        self.assertEqual(document["version"], {"supported": True, "before": "1.2.3", "after": "1.2.4"})
        self.assertEqual(document["change_ref"], "decision-1")
        self.assertEqual(
            document["after_sha256"], hashlib.sha256((req_root / "requirement.md").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            [event["event"] for event in record["history"]],
            ["bootstrap", "analysis", "decision_applied", "validated"],
        )
        self.assertTrue(all(item["returncode"] == 0 for item in output["validators"]))

    def test_successful_decision_is_idempotent(self) -> None:
        req_root, _payload, decision_path = self._decision_fixture()
        args = (
            "run", "--unit", BUG_ID, "--from", "staged", "--root-cause", "错误标识符已移除",
            "--decision-file", str(decision_path),
        )
        first, _first_output = self._run_bug(*args)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        record = records.read_record(req_root)
        git(self.root, "add", "--", *sorted(backflow.artifact_paths(self.root, req_root, record)))
        before = file_state(self.root)
        second, second_output = self._run_bug(*args)
        self.assertEqual(file_state(self.root), before, "rerun changed document or record")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertTrue(second_output.get("unchanged") is True)
        record = records.read_record(req_root)
        self.assertEqual(record["documents"][0]["version"]["after"], "1.2.4")
        self.assertEqual(len(record["history"]), 4)
        self.assertEqual(len(record["decisions"]), 2)


    def test_required_staged_excludes_unchanged_confirmed_and_existing_stub(self) -> None:
        req_root = self._prepare_bug()
        prd = self._write("product/prd/demo-prd.md", "# Demo\n")
        digest = hashlib.sha256(prd.read_bytes()).hexdigest()
        record = records.read_record(req_root)
        record["documents"] = [{
            "path": "product/prd/demo-prd.md", "action": "confirmed",
            "version": {"supported": False, "before": None, "after": None},
            "change_ref": None, "before_sha256": digest, "after_sha256": digest,
        }]
        records.refresh_hashes(record)
        records.write_record(req_root, record)
        self._write(".atlas/spec/conventions/testid.md", "# existing stub\n")
        self.assertEqual(
            backflow.required_staged_paths(self.root, req_root, record), {RECORD_REL})
        self.assertNotIn(".atlas/spec/conventions/testid.md",
                         backflow.artifact_paths(self.root, req_root, record))

    def test_decision_path_mismatch_writes_nothing(self) -> None:
        self._assert_rejected_decision_writes_nothing(
            lambda payload: payload["decisions"][0].update(path="product/prd/other.md"),
            "path 与 conflict.path 不一致",
        )

    def test_executable_change_with_identifier_conflict_has_generic_pending(self) -> None:
        self._prepare_bug(code='E_OLD = "old"\nreturn 1\n',
                          requirement_extra="\n文档引用 E_OLD\n")
        self._write("src/service.py", 'return 2\n')
        self._stage_full_oids("src/service.py")
        result, payload = self._run_bug("run", "--unit", BUG_ID, "--from", "staged")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        record = records.read_record(self.root / "product" / "requirements" / BUG_ID)
        self.assertTrue(any(item.get("old") == "E_OLD" for item in record["conflicts"]))
        self.assertTrue(any("adapter" in item["reason"] for item in record["conflicts"]))
        self.assertFalse(any(item["action"] == "confirmed" for item in record["impact"]))

    def test_link_after_applied_is_idempotent(self) -> None:
        req_root, _payload, _decision_path = self._decision_fixture()
        first, _ = self._run_bug(
            "run", "--unit", BUG_ID, "--from", "staged", "--root-cause", "修复",
            "--decision-file", str(_decision_path), "--commit", "abc123",
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        before = file_state(self.root)
        second, output = self._run_bug("link", BUG_ID, "--commit", "abc123")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertTrue(output["unchanged"])
        self.assertEqual(file_state(self.root), before)
        self.assertEqual(records.read_record(req_root)["links"]["commits"], ["abc123"])

    def test_report_tamper_is_detected(self) -> None:
        req_root = self._prepare_bug()
        self._write(REPORT_REL, (self.root / REPORT_REL).read_text(encoding="utf-8") + "篡改\n")
        record = records.read_record(req_root)
        findings = records.validate_record(record, requirement_root=req_root, root=self.root)
        self.assertTrue(any("report.sha256" in item for item in findings))

    def test_applied_requires_implementation_files(self) -> None:
        req_root, _payload, decision_path = self._decision_fixture()
        result, _ = self._run_bug(
            "run", "--unit", BUG_ID, "--from", "staged", "--root-cause", "修复",
            "--decision-file", str(decision_path),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = records.read_record(req_root)
        record["source"]["implementation_files"] = []
        records.refresh_hashes(record)
        findings = records.validate_record(record, requirement_root=req_root, root=self.root)
        self.assertTrue(any("至少有一个实现文件" in item for item in findings))

    def test_corrupt_array_items_return_findings(self) -> None:
        req_root = self._prepare_bug()
        record = records.read_record(req_root)
        record["documents"] = ["not-an-object"]
        records.refresh_hashes(record)
        findings = records.validate_record(record, requirement_root=req_root, root=self.root)
        self.assertTrue(any("documents[0] 必须为 object" in item for item in findings))

    def test_document_path_whitelist_rejects_implementation(self) -> None:
        req_root = self._prepare_bug()
        record = records.read_record(req_root)
        record["documents"] = [{
            "path": "src/service.py", "action": "confirmed",
            "version": {"supported": False, "before": None, "after": None},
            "change_ref": None, "before_sha256": "a" * 64, "after_sha256": "a" * 64,
        }]
        records.refresh_hashes(record)
        findings = records.validate_record(record, requirement_root=req_root, root=self.root)
        self.assertTrue(any("不在合法资产/spec 面" in item for item in findings))

    def test_spec_impact_is_classified_for_structure_validation(self) -> None:
        self._prepare_bug(code='E_SPEC = "old"\n')
        self._write(".atlas/spec/structure/domains/demo.md",
                    "---\npaths:\n  - src/service.py\n---\n\nE_SPEC\n")
        git(self.root, "add", ".atlas/spec/structure/domains/demo.md")
        git(self.root, "commit", "-qm", "spec baseline")
        self._write("src/service.py", "return 1\n")
        self._stage_full_oids("src/service.py")
        req_root = self.root / "product" / "requirements" / BUG_ID
        source = backflow.source_snapshot(self.root, "staged", None, self._artifact_paths(req_root))
        impacts, _conflicts = backflow.analyze_impact(self.root, req_root, source, self._artifact_paths(req_root))
        self.assertTrue(any(item["kind"] == "spec" for item in impacts))

    def test_repeated_needs_decision_is_byte_idempotent(self) -> None:
        self._prepare_bug()
        self._write("src/service.py", "def calculate():\n    return 2\n")
        self._stage_full_oids("src/service.py")
        first, _ = self._run_bug("run", "--unit", BUG_ID, "--from", "staged")
        self.assertEqual(first.returncode, 2, first.stdout + first.stderr)
        before = file_state(self.root)
        second, output = self._run_bug("run", "--unit", BUG_ID, "--from", "staged")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertTrue(output["unchanged"])
        self.assertEqual(file_state(self.root), before)

    def test_existing_root_rejects_requirement_mismatch(self) -> None:
        self._prepare_bug()
        result, output = self._run_bug(
            "run", "--unit", BUG_ID, "--requirement", "other#R-01")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(output["cause"], "bug_backflow_invalid")
        self.assertIn("关联需求不一致", output["message"])


    def test_task_id_inherits_requirement_root(self) -> None:
        self._prepare_bug()
        self._write(".atlas/tasks/T-INHERIT/task.json", json.dumps({
            "id": "T-INHERIT", "title": "inherit", "status": "todo", "depends_on": [],
            "affected_domains": [], "acs": [], "created_at": "2026-01-01",
            "requirement_root": f"product/requirements/{BUG_ID}",
        }, ensure_ascii=False))
        self._write("src/service.py", "def calculate():\n    return 2\n")
        self._stage_full_oids("src/service.py")
        result, payload = self._run_bug("run", "--unit", "T-INHERIT", "--from", "staged")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(payload["status"], "conflict")
        self.assertEqual(payload["bug"], "T-INHERIT")


    def test_reanalysis_preserves_resolved_conflicts_and_decisions(self) -> None:
        req_root, _payload, decision_path = self._decision_fixture()
        first, _ = self._run_bug(
            "run", "--unit", BUG_ID, "--from", "staged", "--root-cause", "修复",
            "--decision-file", str(decision_path),
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        old_decision_ids = [item["id"] for item in records.read_record(req_root)["decisions"]]
        self._write("src/service.py", "return 3\n")
        self._stage_full_oids("src/service.py")
        second, output = self._run_bug("run", "--unit", BUG_ID, "--from", "staged")
        self.assertEqual(second.returncode, 2, second.stdout + second.stderr)
        record = records.read_record(req_root)
        self.assertEqual(record["backflow_status"], "needs_decision")
        self.assertTrue(any(item["status"] == "open" for item in record["conflicts"]))
        self.assertEqual([item["id"] for item in record["decisions"]], old_decision_ids)
        self.assertEqual(records.validate_record(record, requirement_root=req_root, root=self.root), [])


    def test_quoted_non_ascii_path_still_requires_executable_decision(self) -> None:
        self._prepare_bug()
        self._write("src/实现.py", "def calculate():\n    return 1\n")
        git(self.root, "add", "src/实现.py")
        git(self.root, "commit", "-qm", "quoted path baseline")
        self._write("src/实现.py", "def calculate():\n    return 2\n")
        self._stage_full_oids("src/实现.py")
        result, payload = self._run_bug("run", "--unit", BUG_ID, "--from", "staged")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        record = records.read_record(self.root / "product" / "requirements" / BUG_ID)
        self.assertTrue(any("adapter" in item["reason"] for item in record["conflicts"]))
        self.assertFalse(any(item["action"] == "confirmed" for item in record["impact"]))

    def test_existing_standalone_defect_is_rejected(self) -> None:
        req_root = self._prepare_bug()
        requirement = req_root / "requirement.md"
        requirement.write_text(requirement.read_text(encoding="utf-8").replace(
            f"**关联需求**：{RELATED}\n", ""), encoding="utf-8")
        record = records.read_record(req_root)
        findings = records.validate_record(record, requirement_root=req_root, root=self.root)
        self.assertTrue(any("未关联既有需求" in item for item in findings), findings)
        result, output = self._run_bug("run", "--unit", BUG_ID, "--from", "staged")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(output["cause"], "bug_backflow_invalid")
        self.assertIn("未关联既有需求", output["message"])


if __name__ == "__main__":
    unittest.main()
