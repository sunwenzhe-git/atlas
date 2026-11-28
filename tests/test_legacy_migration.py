"""RFC-20261125-01 P1 legacy migration positive/negative contract tests.

M245: removing the observed-vs-candidate conflict branch must turn the STALE
counterexample red. These tests also pin byte preservation, atomic generation
publication, rollback, symlink containment and real test evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support.governance_io import GenerationStore, atomic_write_bytes, safe_path
from _support.governance_schema import canonical_digest
from _support.argv_split import join_command
from _support.legacy_migration import ARTIFACTS, index_matches_worktree, migrate, rollback
from validators.validate_migration import check_migration, main as validate_main

PROFILE = """product: 夹具
apps:
  - name: backend
    path: src
    kind: backend
    stack: 夹具
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True,
                   capture_output=True, text=True)


def test_index_matches_worktree_distinguishes_missing_and_unavailable(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "a@b")
    _git(root, "config", "user.name", "a")
    path = root / "a.txt"
    path.write_text("one\n", encoding="utf-8")
    _git(root, "add", "a.txt")
    assert index_matches_worktree(root, "a.txt") is True
    path.write_text("two\n", encoding="utf-8")
    assert index_matches_worktree(root, "a.txt") is False
    _git(root, "rm", "--cached", "-f", "a.txt")
    assert index_matches_worktree(root, "a.txt") is False
    assert index_matches_worktree(tmp_path / "not-git", "a.txt") is None


def test_migrate_and_validator_reject_worktree_file_missing_from_index(tmp_path: Path) -> None:
    fixture(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "a@b")
    _git(tmp_path, "config", "user.name", "a")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "init")
    assert migrate(tmp_path, test_command=run_tests(tmp_path))["verdict"] == "PASS"
    _git(tmp_path, "rm", "--cached", "-f", "src/main.py")
    assert index_matches_worktree(tmp_path, "src/main.py") is False
    migrated = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert migrated["verdict"] != "PASS", migrated
    errors = json.loads((generation(tmp_path) / "parse-errors.json").read_text(encoding="utf-8"))["items"]
    assert any(item.get("kind") == "source_stale" and item.get("path") == "src/main.py"
               for item in errors), errors
    validated = check_migration(tmp_path)
    assert validated["verdict"] != "PASS", validated
    assert any(item.get("path") == "src/main.py" and "source_stale" in item.get("message", "")
               for item in validated["findings"]), validated
    assert index_matches_worktree(tmp_path, "does-not-exist.py") is None


def symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("当前 Windows 用户没有创建符号链接的特权")
        raise
CODE = """from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base
app = object()
Base = declarative_base()
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    detail_url = Column(String, nullable=False)
@app.get('/api/users')
def users():
    return []
"""
TEST = """def test_users():
    assert True
"""
GOOD_DOC = """# 旧接口
- `GET /api/users`
- `detail_url: string`
"""
STALE_DOC = """# 旧接口
- `GET /api/old-users`
- `detailUrl: string`
"""


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def fixture(root: Path, doc: str = GOOD_DOC) -> dict[str, bytes]:
    files = {
        "product/stack-profile.yaml": PROFILE,
        "src/main.py": CODE,
        "src/routes/index.jsx": "export default function Home() { return <main />; }\n",
        "tests/test_users.py": TEST,
        "pytest.ini": "[pytest]\n",
        "openspec/specs/users/spec.md": (
            "## Requirement: 用户接口\n"
            "系统应提供用户接口。\n\n"
            "### Scenario: 查询\n- **WHEN** 查询用户\n- **THEN** 返回用户列表\n"
        ),
        "openspec/changes/add-users/proposal.md": "# Proposal\n## Why\n迁移用户接口。\n",
        "openspec/changes/add-users/tasks.md": "# Tasks\n- [x] 实现用户接口\n",
        ".trellis/spec/backend/index.md": "# Backend\n## Convention\n使用现有接口。\n",
        ".trellis/tasks/backend/users.md": "# Users\n- [x] 查询用户\n",
        "README.md": doc,
        "docs/guide.md": "# Guide\n`GET /api/users`\n",
    }
    for rel, text in files.items():
        write(root, rel, text)
    return {rel: (root / rel).read_bytes() for rel in files}


def run_tests(root: Path) -> list[str]:
    return [sys.executable, "-m", "pytest", "-q", "tests/test_users.py"]


def generation(root: Path) -> Path:
    manifest = json.loads((root / ".adapter-out/migration/manifest.json").read_text(encoding="utf-8"))
    return root / ".adapter-out/migration" / manifest["path"]


def artifact(root: Path, name: str):
    return json.loads((generation(root) / name).read_text(encoding="utf-8"))


def test_positive_openspec_trellis_docs_and_real_test_evidence(tmp_path):
    original = fixture(tmp_path)
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert result["verdict"] == "PASS", result
    assert result["rc"] == 0 and result["cause"] is None
    assert check_migration(tmp_path)["verdict"] == "PASS"
    manifest = json.loads((tmp_path / ".adapter-out/migration/manifest.json").read_text())
    assert set(manifest["files"]) == set(ARTIFACTS)
    assert manifest["generation"] == manifest["business_digest"]
    assert manifest["generation"] == canonical_digest({
        name: artifact(tmp_path, name) for name in ARTIFACTS
    })
    sources = artifact(tmp_path, "source-manifest.json")["sources"]
    assert {s["tool"] for s in sources} >= {"openspec", "trellis", "legacy-docs", "code"}
    facts = artifact(tmp_path, "facts.json")
    assert {f["adapter"] for f in facts["facts"]} >= {"routes", "api", "models", "tests"}
    assert any(f["value"].get("path") == "/api/users" for f in facts["facts"] if f["adapter"] == "api")
    assert artifact(tmp_path, "stale.json")["items"] == []
    assert artifact(tmp_path, "parse-errors.json")["items"] == []
    evidence = artifact(tmp_path, "test-evidence.json")
    assert evidence["ran"] is True and evidence["exit_code"] == 0
    assert evidence["command"].startswith(join_command([sys.executable]) + " ")
    assert "commit" in evidence and evidence["environment"]
    assert "tests/test_users.py::test_users" in evidence["nodes"]
    assert evidence["output_sha256"] == hashlib.sha256(evidence["output"].encode()).hexdigest()
    assert all((tmp_path / rel).read_bytes() == body for rel, body in original.items())


def test_code_conflict_is_automatically_stale_and_document_bytes_unchanged(tmp_path):
    original = fixture(tmp_path, STALE_DOC)
    before = (tmp_path / "README.md").read_bytes()
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert result["verdict"] == "STALE" and result["rc"] == 1 and result["cause"] == "contract_stale"
    stale = artifact(tmp_path, "stale.json")["items"]
    assert {item["kind"] for item in stale} >= {"route", "field"}
    assert {item["source"]["path"] for item in stale} == {"README.md"}
    assert all(item["observed"] and item["candidate"] for item in stale)
    assert (tmp_path / "README.md").read_bytes() == before
    assert all((tmp_path / rel).read_bytes() == body for rel, body in original.items())


def test_module_results_conform_to_governance_common(tmp_path):
    from _support.governance_schema import load_schema, validate
    fixture(tmp_path, STALE_DOC)
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert validate(result, load_schema("governance-common")) == []
    checked = check_migration(tmp_path)
    assert validate(checked, load_schema("governance-common")) == []
    assert any(item["cause"] == "contract_stale" for item in checked["findings"])


def test_unknown_format_is_unverified_and_recorded(tmp_path):
    fixture(tmp_path)
    write(tmp_path, ".trellis/spec/unknown.xyz", "opaque\n")
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    errors = artifact(tmp_path, "parse-errors.json")["items"]
    assert any(item.get("path") == ".trellis/spec/unknown.xyz" and item["kind"] == "unknown_format" for item in errors)


def test_unrun_tests_are_unverified(tmp_path):
    fixture(tmp_path)
    result = migrate(tmp_path)
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    evidence = artifact(tmp_path, "test-evidence.json")
    assert evidence["ran"] is False and evidence["exit_code"] is None
    assert evidence["reason"]


def test_zero_exit_command_without_test_coverage_is_unverified(tmp_path):
    fixture(tmp_path)
    result = migrate(tmp_path, test_command=[sys.executable, "-c", "print('ok')"])
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    evidence = artifact(tmp_path, "test-evidence.json")
    assert evidence["ran"] is False and evidence["exit_code"] is None and evidence["verified"] is False
    assert evidence["nodes"] == ["tests/test_users.py::test_users"]
    assert check_migration(tmp_path)["verdict"] == "UNVERIFIED"


def test_printed_counts_and_ok_do_not_prove_test_execution(tmp_path):
    fixture(tmp_path)
    for output in ("1 passed", "OK"):
        result = migrate(tmp_path, test_command=[sys.executable, "-c", f"print({output!r})"])
        assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2


def test_echoed_node_and_skipped_test_are_not_pass_evidence(tmp_path):
    fixture(tmp_path)
    echoed = migrate(tmp_path, test_command=[sys.executable, "-c", "print('tests/test_users.py::test_users PASSED')"],
                     test_nodes=["tests/test_users.py::test_users"])
    assert echoed["verdict"] == "UNVERIFIED"
    write(tmp_path, "tests/test_users.py", "import pytest\n@pytest.mark.skip(reason='x')\ndef test_users():\n    assert True\n")
    skipped = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert skipped["verdict"] == "UNVERIFIED"
    assert artifact(tmp_path, "test-evidence.json")["verified"] is False


def test_migration_evidence_is_bound_to_head_and_environment(tmp_path):
    fixture(tmp_path)
    for args in (("init", "-q"), ("config", "user.email", "migration@example.test"),
                 ("config", "user.name", "Migration Test"), ("add", "."), ("commit", "-qm", "base")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    assert migrate(tmp_path, test_command=run_tests(tmp_path))["verdict"] == "PASS"
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "new head"], cwd=tmp_path, check=True)
    checked = check_migration(tmp_path)
    assert checked["verdict"] == "UNVERIFIED" and checked["rc"] == 2
    assert any("commit/tree/环境" in item["message"] for item in checked["findings"])


def test_staged_failing_test_cannot_be_washed_by_working_tree_pass(tmp_path):
    fixture(tmp_path)
    for args in (("init", "-q"), ("config", "user.email", "migration@example.test"),
                 ("config", "user.name", "Migration Test"), ("add", "."), ("commit", "-qm", "base")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    path = write(tmp_path, "tests/test_users.py", "def test_users():\n    assert False\n")
    subprocess.run(["git", "add", "tests/test_users.py"], cwd=tmp_path, check=True)
    path.write_text("def test_users():\n    assert True\n")
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert artifact(tmp_path, "test-evidence.json")["verified"] is False
    assert check_migration(tmp_path)["verdict"] == "UNVERIFIED"


def test_index_only_source_cannot_disappear_from_inventory(tmp_path):
    fixture(tmp_path)
    for args in (("init", "-q"), ("config", "user.email", "migration@example.test"),
                 ("config", "user.name", "Migration Test"), ("add", "."), ("commit", "-qm", "base")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    assert migrate(tmp_path, test_command=run_tests(tmp_path))["verdict"] == "PASS"
    added = write(tmp_path, "src/new.py", "VALUE = 1\n")
    subprocess.run(["git", "add", "src/new.py"], cwd=tmp_path, check=True)
    added.unlink()
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert check_migration(tmp_path)["verdict"] != "PASS"


def test_index_only_unknown_openspec_format_cannot_disappear(tmp_path):
    fixture(tmp_path)
    for args in (("init", "-q"), ("config", "user.email", "migration@example.test"),
                 ("config", "user.name", "Migration Test"), ("add", "."), ("commit", "-qm", "base")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    assert migrate(tmp_path, test_command=run_tests(tmp_path))["verdict"] == "PASS"
    added = write(tmp_path, "openspec/config.json", "{}\n")
    subprocess.run(["git", "add", "openspec/config.json"], cwd=tmp_path, check=True)
    added.unlink()
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert check_migration(tmp_path)["verdict"] != "PASS"


def test_head_source_staged_deletion_cannot_disappear(tmp_path):
    fixture(tmp_path, "# guide\n")
    for args in (("init", "-q"), ("config", "user.email", "migration@example.test"),
                 ("config", "user.name", "Migration Test"), ("add", "."), ("commit", "-qm", "base")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    assert migrate(tmp_path, test_command=run_tests(tmp_path))["verdict"] == "PASS"
    subprocess.run(["git", "rm", "-q", "docs/guide.md"], cwd=tmp_path, check=True)
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert check_migration(tmp_path)["verdict"] != "PASS"


def test_non_source_docs_files_are_not_false_staged_deletions(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "docs/config.mts", "export default {}\n")
    write(tmp_path, "docs/LICENSE", "license\n")
    for args in (("init", "-q"), ("config", "user.email", "migration@example.test"),
                 ("config", "user.name", "Migration Test"), ("add", "."), ("commit", "-qm", "base")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert result["verdict"] == "PASS", result


def test_corrupt_git_head_is_unverified_not_non_git_pass(tmp_path):
    fixture(tmp_path)
    for args in (("init", "-q"), ("config", "user.email", "migration@example.test"),
                 ("config", "user.name", "Migration Test"), ("add", "."), ("commit", "-qm", "base")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    assert migrate(tmp_path, test_command=run_tests(tmp_path))["verdict"] == "PASS"
    (tmp_path / ".git/HEAD").write_text("broken\n")
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert check_migration(tmp_path)["verdict"] == "UNVERIFIED"


def test_root_openspec_index_only_path_is_not_silently_dropped(tmp_path):
    fixture(tmp_path)
    shutil.rmtree(tmp_path / "openspec")
    for args in (("init", "-q"), ("config", "user.email", "migration@example.test"),
                 ("config", "user.name", "Migration Test"), ("add", "."), ("commit", "-qm", "base")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    assert migrate(tmp_path, test_command=run_tests(tmp_path))["verdict"] == "PASS"
    added = write(tmp_path, "openspec", "unknown\n")
    subprocess.run(["git", "add", "openspec"], cwd=tmp_path, check=True)
    added.unlink()
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2


def test_corrupt_parent_git_head_in_repo_subdirectory_is_unverified(tmp_path):
    fixture(tmp_path)
    for args in (("init", "-q"), ("config", "user.email", "migration@example.test"),
                 ("config", "user.name", "Migration Test"), ("add", "."), ("commit", "-qm", "base")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    assert migrate(tmp_path, test_command=run_tests(tmp_path))["verdict"] == "PASS"
    sub = tmp_path / "nested" / "project"
    sub.mkdir(parents=True)
    for child in tmp_path.iterdir():
        if child.name not in {".git", "nested"}:
            shutil.move(str(child), str(sub / child.name))
    (tmp_path / ".git/HEAD").write_text("broken\n")
    result = migrate(sub, test_command=run_tests(sub))
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert check_migration(sub)["verdict"] == "UNVERIFIED"


def test_publish_rejects_damaged_previous_generation(tmp_path):
    fixture(tmp_path)
    for args in (("init", "-q"), ("config", "user.email", "migration@example.test"),
                 ("config", "user.name", "Migration Test"), ("add", "."), ("commit", "-qm", "base")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    assert migrate(tmp_path, test_command=run_tests(tmp_path))["verdict"] == "PASS"
    pointer_path = tmp_path / ".adapter-out/migration/manifest.json"
    pointer = json.loads(pointer_path.read_text())
    pointer["business_digest"] = "0" * 64
    pointer_path.write_text(json.dumps(pointer))
    before = pointer_path.read_bytes()
    write(tmp_path, "README.md", "# changed\n")
    with pytest.raises(ValueError, match="pointer|digest|generation"):
        migrate(tmp_path, test_command=run_tests(tmp_path))
    assert pointer_path.read_bytes() == before


def test_head_non_ascii_source_staged_deletion_is_rejected(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "docs/中文.md", "# 中文\n")
    for args in (("init", "-q"), ("config", "user.email", "migration@example.test"),
                 ("config", "user.name", "Migration Test"), ("add", "."), ("commit", "-qm", "base")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    assert migrate(tmp_path, test_command=run_tests(tmp_path))["verdict"] == "PASS"
    subprocess.run(["git", "rm", "-q", "docs/中文.md"], cwd=tmp_path, check=True)
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2


def test_migration_check_rejects_extra_generation_entries(tmp_path):
    fixture(tmp_path)
    assert migrate(tmp_path, test_command=run_tests(tmp_path))["verdict"] == "PASS"
    (generation(tmp_path) / "unbound.txt").write_text("extra")
    result = check_migration(tmp_path)
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert any("额外" in item["message"] for item in result["findings"])


def test_parametrized_nodes_and_explicit_nodes_use_union(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "tests/test_users.py", "import pytest\n@pytest.mark.parametrize('value', [1, 2])\ndef test_users(value):\n    assert value\n")
    result = migrate(tmp_path, test_command=run_tests(tmp_path), test_nodes=["tests/test_users.py::test_users"])
    assert result["verdict"] == "PASS", result
    write(tmp_path, "tests/test_other.py", "def test_other():\n    assert True\n")
    incomplete = migrate(tmp_path, test_command=[sys.executable, "-m", "pytest", "-q", "tests/test_users.py"])
    assert incomplete["verdict"] == "UNVERIFIED"


def test_parametrized_skip_or_partial_case_is_not_verified(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "tests/test_users.py", "import pytest\n@pytest.mark.parametrize('value', [1, 2])\ndef test_users(value):\n    if value == 2:\n        pytest.skip('not executed')\n    assert value\n")
    skipped = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert skipped["verdict"] == "UNVERIFIED"
    assert artifact(tmp_path, "test-evidence.json")["verified"] is False
    write(tmp_path, "tests/test_users.py", "import pytest\n@pytest.mark.parametrize('value', [1, 2])\ndef test_users(value):\n    assert value\n")
    partial = migrate(tmp_path, test_command=[sys.executable, "-m", "pytest", "-q",
                                              "tests/test_users.py::test_users[1]"])
    assert partial["verdict"] == "UNVERIFIED"
    assert artifact(tmp_path, "test-evidence.json")["verified"] is False


def test_non_strict_xpass_is_not_verified(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "tests/test_users.py", "import pytest\n@pytest.mark.xfail(reason='unexpected pass')\ndef test_users():\n    assert True\n")
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert result["verdict"] == "UNVERIFIED"
    assert artifact(tmp_path, "test-evidence.json")["verified"] is False


def test_module_and_class_xfail_markers_block_even_with_quiet_color_output(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "tests/test_users.py", "import pytest\npytestmark = pytest.mark.xfail(reason='module')\ndef test_users():\n    assert True\n")
    result = migrate(tmp_path, test_command=run_tests(tmp_path) + ["-qq", "--color=yes"])
    assert result["verdict"] == "UNVERIFIED"
    write(tmp_path, "tests/test_users.py", "import pytest\nclass TestUsers:\n    pytestmark = pytest.mark.xfail(reason='class')\n    def test_users(self):\n        assert True\n")
    result = migrate(tmp_path, test_command=run_tests(tmp_path) + ["-qq", "--color=yes"])
    assert result["verdict"] == "UNVERIFIED"


def test_dynamic_xfail_xpass_summary_is_not_verified_with_quiet_color(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "tests/test_users.py", "def test_users():\n    assert True\n")
    write(tmp_path, "conftest.py", "import pytest\ndef pytest_collection_modifyitems(items):\n    for item in items:\n        item.add_marker(pytest.mark.xfail(reason='dynamic'))\n")
    result = migrate(tmp_path, test_command=run_tests(tmp_path) + ["-qq", "--color=yes"])
    assert result["verdict"] == "UNVERIFIED"
    assert artifact(tmp_path, "test-evidence.json")["verified"] is False


def test_junit_blocks_plugin_printed_node_and_empty_evidence(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "tests/test_other.py", "def test_other():\n    assert True\n")
    write(tmp_path, "conftest.py", "def pytest_terminal_summary(terminalreporter):\n    terminalreporter.write_line('tests/test_users.py::test_users PASSED')\n")
    result = migrate(tmp_path, test_command=[sys.executable, "-m", "pytest", "-q", "tests/test_other.py"])
    assert result["verdict"] == "UNVERIFIED"
    artifacts = {item: json.loads((generation(tmp_path) / item).read_text()) for item in ARTIFACTS}
    artifacts["test-evidence.json"].update(nodes=[], verified=False, ran=False)
    artifacts["parse-errors.json"]["items"] = []
    GenerationStore(tmp_path).publish(canonical_digest(artifacts), artifacts)
    assert check_migration(tmp_path)["verdict"] == "UNVERIFIED"


def test_route_query_and_trailing_slash_do_not_create_false_stale(tmp_path):
    fixture(tmp_path, "# API\n`GET /api/users/?limit=10`\n")
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert result["verdict"] == "PASS", result


def test_empty_legacy_document_does_not_crash(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "docs/empty.md", "")
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert result["verdict"] == "PASS", result
    assert artifact(tmp_path, "source-manifest.json")["sources"]


def test_mode_is_persisted_and_off_does_not_mutate_pointer(tmp_path):
    fixture(tmp_path)
    shadow = migrate(tmp_path, test_command=run_tests(tmp_path), mode="shadow")
    assert shadow["mode"] == "shadow" and shadow["rc"] == 0
    assert check_migration(tmp_path)["mode"] == "shadow"
    pointer = tmp_path / ".adapter-out/migration/manifest.json"
    before = pointer.read_bytes()
    off = migrate(tmp_path, test_command=run_tests(tmp_path), mode="off")
    assert off["mode"] == "off" and off["verdict"] == "UNVERIFIED" and off["cause"] is None
    assert pointer.read_bytes() == before
    checked = check_migration(tmp_path)
    assert checked["mode"] == "shadow" and checked["verdict"] == "PASS" and checked["rc"] == 0


def test_migration_rollback_cli_non_object_pointer_is_unverified(tmp_path):
    pointer = tmp_path / ".adapter-out/migration/manifest.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text("[]")
    result = subprocess.run([sys.executable, str(PKG_ROOT / "scripts/atlas_migrate.py"),
                             "--root", str(tmp_path), "--mode", "enforce", "--rollback", "--json"],
                            capture_output=True, text=True)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["verdict"] == "UNVERIFIED"


def test_migration_rollback_off_does_not_switch_pointer(tmp_path):
    fixture(tmp_path)
    command = run_tests(tmp_path)
    migrate(tmp_path, test_command=command)
    write(tmp_path, "README.md", STALE_DOC)
    migrate(tmp_path, test_command=command)
    pointer = tmp_path / ".adapter-out/migration/manifest.json"
    before = pointer.read_bytes()
    result = rollback(tmp_path, mode="off")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2 and result["mode"] == "off"
    assert pointer.read_bytes() == before


def test_migrate_cli_shadow_error_preserves_mode_and_rc0(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    symlink_or_skip(link, target, target_is_directory=True)
    result = subprocess.run([sys.executable, str(PKG_ROOT / "scripts/atlas_migrate.py"),
                             "--root", str(link), "--mode", "shadow", "--json"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["mode"] == "shadow" and payload["rc"] == 0


def test_mode_switch_keeps_rollback_point(tmp_path):
    fixture(tmp_path)
    migrate(tmp_path, test_command=run_tests(tmp_path), mode="enforce")
    migrate(tmp_path, test_command=run_tests(tmp_path), mode="shadow")
    restored = rollback(tmp_path)
    assert restored["mode"] == "enforce" and restored["verdict"] == "WARN"
    assert check_migration(tmp_path)["verdict"] == "PASS"


def test_rollback_rejects_incomplete_previous_pointer_file_set(tmp_path):
    fixture(tmp_path)
    command = run_tests(tmp_path)
    migrate(tmp_path, test_command=command)
    (tmp_path / "README.md").write_text(STALE_DOC, encoding="utf-8")
    migrate(tmp_path, test_command=command)
    pointer_path = tmp_path / ".adapter-out/migration/manifest.json"
    pointer = json.loads(pointer_path.read_text())
    removed = next(iter(pointer["previous_pointer"]["files"]))
    del pointer["previous_pointer"]["files"][removed]
    pointer_path.write_text(json.dumps(pointer))
    before = pointer_path.read_bytes()
    with pytest.raises(ValueError, match="文件清单|digest"):
        rollback(tmp_path)
    assert pointer_path.read_bytes() == before


def test_model_facts_keep_adapter_line_instead_of_first_name_match(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "src/models.py", "from sqlalchemy import Column, Integer, String\nfrom sqlalchemy.orm import declarative_base\nBase = declarative_base()\nclass A(Base):\n    __tablename__ = 'a'\n    id = Column(Integer)\nclass B(Base):\n    __tablename__ = 'b'\n    id = Column(String)\n")
    migrate(tmp_path, test_command=run_tests(tmp_path))
    fields = [item for item in artifact(tmp_path, "facts.json")["facts"]
              if item["adapter"] == "models" and item["value"].get("field") == "id"
              and item["source"]["path"] == "src/models.py"]
    assert fields and all("line" in item["source"] for item in fields)
    expected_lines = {number for number, line in enumerate((tmp_path / "src/models.py").read_text().splitlines(), 1) if "id = Column" in line}
    assert {item["source"]["line"] for item in fields} == expected_lines


def test_repeat_run_is_byte_stable_and_generated_at_is_not_business_input(tmp_path):
    fixture(tmp_path)
    command = run_tests(tmp_path)
    migrate(tmp_path, test_command=command)
    first = {name: (generation(tmp_path) / name).read_bytes() for name in ARTIFACTS}
    first_pointer = (tmp_path / ".adapter-out/migration/manifest.json").read_bytes()
    migrate(tmp_path, test_command=command)
    assert first_pointer == (tmp_path / ".adapter-out/migration/manifest.json").read_bytes()
    assert first == {name: (generation(tmp_path) / name).read_bytes() for name in ARTIFACTS}
    assert all(b"generated_at" not in body for body in first.values())


def test_symlink_source_escape_is_rejected_without_writing_outside(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    fixture(root)
    outside = tmp_path / "outside.md"
    outside.write_text("GET /api/users\n", encoding="utf-8")
    (root / "docs").mkdir(exist_ok=True)
    symlink_or_skip(root / "docs" / "escape.md", outside)
    with pytest.raises(ValueError, match="symlink|符号链接"):
        migrate(root, test_command=run_tests(root))
    assert outside.read_text(encoding="utf-8") == "GET /api/users\n"
    assert not (root / ".adapter-out/migration/manifest.json").exists()


@pytest.mark.parametrize("rel", ["../outside", "/tmp/outside", "C:\\outside", "..\\outside", "docs/../../outside"])
def test_safe_path_rejects_escape(rel, tmp_path):
    with pytest.raises(ValueError):
        safe_path(tmp_path, rel)


def test_safe_path_rejects_symlink_parent_and_file(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    symlink_or_skip(root / "link", outside, target_is_directory=True)
    with pytest.raises(ValueError):
        safe_path(root, "link/file.txt")
    target = outside / "file.txt"
    target.write_text("x", encoding="utf-8")
    symlink_or_skip(root / "file.txt", target)
    with pytest.raises(ValueError):
        safe_path(root, "file.txt")


def test_atomic_write_uses_temp_and_rename_and_preserves_old_on_failure(tmp_path, monkeypatch):
    import _support.governance_io as io
    target = tmp_path / "value.txt"
    atomic_write_bytes(target, b"old")
    real_replace = os.replace
    calls = []

    def fail(source, destination):
        calls.append((source, destination))
        if Path(destination) == target:
            raise OSError("injected")
        return real_replace(source, destination)

    monkeypatch.setattr(io.os, "replace", fail)
    with pytest.raises(OSError, match="injected"):
        atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"old"
    assert not list(tmp_path.glob(".value.txt.*.tmp"))
    assert any(Path(source).name.endswith(".tmp") for source, _ in calls)


def test_pointer_switch_rollback_and_failed_publication_keep_last_known_good(tmp_path, monkeypatch):
    fixture(tmp_path, GOOD_DOC)
    command = run_tests(tmp_path)
    migrate(tmp_path, test_command=command)
    old_pointer = (tmp_path / ".adapter-out/migration/manifest.json").read_bytes()
    old_generation = generation(tmp_path)
    (tmp_path / "README.md").write_text(STALE_DOC, encoding="utf-8")
    migrate(tmp_path, test_command=command)
    new_pointer = (tmp_path / ".adapter-out/migration/manifest.json").read_bytes()
    new_generation = generation(tmp_path)
    assert new_generation != old_generation
    assert json.loads(new_pointer)["previous_generation"] == old_generation.name
    rollback(tmp_path)
    assert (tmp_path / ".adapter-out/migration/manifest.json").read_bytes() == old_pointer
    assert old_generation.is_dir() and new_generation.is_dir()

    import _support.governance_io as io
    real_replace = os.replace

    def fail_pointer(source, destination):
        if Path(destination).name == "manifest.json":
            raise OSError("pointer switch failed")
        return real_replace(source, destination)

    monkeypatch.setattr(io.os, "replace", fail_pointer)
    (tmp_path / "README.md").write_text(GOOD_DOC + "\nchanged\n", encoding="utf-8")
    with pytest.raises(OSError, match="pointer switch failed"):
        migrate(tmp_path, test_command=command)
    assert (tmp_path / ".adapter-out/migration/manifest.json").read_bytes() == old_pointer


def test_failed_rollback_only_changes_pointer_and_keeps_current(tmp_path, monkeypatch):
    fixture(tmp_path)
    command = run_tests(tmp_path)
    migrate(tmp_path, test_command=command)
    (tmp_path / "README.md").write_text(STALE_DOC, encoding="utf-8")
    migrate(tmp_path, test_command=command)
    current = (tmp_path / ".adapter-out/migration/manifest.json").read_bytes()
    import _support.governance_io as io

    def fail(*_args):
        raise OSError("rollback failed")

    monkeypatch.setattr(io.os, "replace", fail)
    with pytest.raises(OSError, match="rollback failed"):
        rollback(tmp_path)
    assert (tmp_path / ".adapter-out/migration/manifest.json").read_bytes() == current


def test_generation_store_switches_and_restores_pointer(tmp_path):
    store = GenerationStore(tmp_path)
    one = {"schema_version": 1, "value": 1}
    two = {"schema_version": 1, "value": 2}
    one_artifacts = {name: {} for name in ARTIFACTS} | {"facts.json": one}
    two_artifacts = {name: {} for name in ARTIFACTS} | {"facts.json": two}
    one_digest = canonical_digest(one_artifacts)
    two_digest = canonical_digest(two_artifacts)
    store.publish(one_digest, one_artifacts)
    pointer_one = store.pointer_path.read_bytes()
    store.publish(two_digest, two_artifacts)
    assert json.loads(store.pointer_path.read_text())["generation"] == two_digest
    store.rollback()
    assert store.pointer_path.read_bytes() == pointer_one


def test_generation_store_rejects_extra_entries_on_reuse(tmp_path):
    store = GenerationStore(tmp_path)
    artifacts = {name: {} for name in ARTIFACTS}
    digest = canonical_digest(artifacts)
    store.publish(digest, artifacts)
    (tmp_path / ".adapter-out/migration/generations" / digest / "unbound.txt").write_text("extra")
    with pytest.raises(ValueError, match="额外|非普通"):
        store.publish(digest, artifacts)


def test_validator_source_change_is_stale_and_pointer_tamper_is_failure(tmp_path, capsys):
    fixture(tmp_path)
    migrate(tmp_path, test_command=run_tests(tmp_path))
    write(tmp_path, "README.md", GOOD_DOC + "\nnew sentence\n")
    assert check_migration(tmp_path)["verdict"] == "STALE"
    rc = validate_main(["--root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == payload["rc"] == 1 and payload["verdict"] == "STALE"
    pointer = tmp_path / ".adapter-out/migration/manifest.json"
    value = json.loads(pointer.read_text())
    value["path"] = "generations/missing"
    pointer.write_text(json.dumps(value), encoding="utf-8")
    result = check_migration(tmp_path)
    assert result["rc"] == 1 and result["verdict"] in ("FAIL", "UNVERIFIED")


def test_validator_schema_tamper_and_missing_test_evidence_are_not_pass(tmp_path, capsys):
    fixture(tmp_path)
    migrate(tmp_path, test_command=run_tests(tmp_path))
    facts = generation(tmp_path) / "facts.json"
    original_facts = facts.read_bytes()
    facts.write_text('{"schema_version":1}', encoding="utf-8")
    result = check_migration(tmp_path)
    assert result["rc"] == 1 and result["verdict"] in ("FAIL", "UNVERIFIED")
    # Restore exact bytes; publication must refuse to repair a damaged generation in place.
    facts.write_bytes(original_facts)
    migrate(tmp_path, test_command=run_tests(tmp_path))
    evidence = generation(tmp_path) / "test-evidence.json"
    value = json.loads(evidence.read_text())
    value["ran"] = False
    value["verified"] = False
    evidence.write_text(json.dumps(value), encoding="utf-8")
    rc = validate_main(["--root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == payload["rc"] == 2 and payload["verdict"] == "UNVERIFIED"


def test_validator_rejects_tampered_fact_and_contract_source_hash(tmp_path):
    fixture(tmp_path)
    migrate(tmp_path, test_command=run_tests(tmp_path))
    for name, key in (("facts.json", "facts"), ("contracts.json", "items")):
        artifacts = {item: json.loads((generation(tmp_path) / item).read_text()) for item in ARTIFACTS}
        artifacts[name][key][0]["source"]["sha256"] = "0" * 64
        GenerationStore(tmp_path).publish(canonical_digest(artifacts), artifacts)
        assert check_migration(tmp_path)["verdict"] == "FAIL"


def test_failure_and_cli_exception_results_conform_to_common_schema(tmp_path):
    from _support.governance_schema import load_schema, validate
    fixture(tmp_path)
    migrate(tmp_path, test_command=run_tests(tmp_path))
    pointer = tmp_path / ".adapter-out/migration/manifest.json"
    data = json.loads(pointer.read_text())
    data["generation"] = "0" * 64
    pointer.write_text(json.dumps(data), encoding="utf-8")
    assert validate(check_migration(tmp_path), load_schema("governance-common")) == []
    empty = tmp_path / "empty"
    empty.mkdir()
    proc = subprocess.run([sys.executable, str(PKG_ROOT / "scripts/atlas_migrate.py"), "--root", str(empty),
                           "--mode", "enforce", "--rollback", "--json"], capture_output=True, text=True)
    assert proc.returncode == 2
    assert validate(json.loads(proc.stdout), load_schema("governance-common")) == []


def test_validator_text_output_and_cli_json_exit_codes(tmp_path, capsys):
    fixture(tmp_path, STALE_DOC)
    command = run_tests(tmp_path)
    result = subprocess.run(
        [sys.executable, str(PKG_ROOT / "scripts/atlas_migrate.py"), "--root", str(tmp_path),
        "--test-command", join_command(command), "--mode", "enforce", "--json"],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)["verdict"] == "STALE"
    rc = validate_main(["--root", str(tmp_path)])
    text = capsys.readouterr().out
    assert rc == 1 and "[STALE]" in text and "README.md" in text


def test_cli_rollback_switches_pointer_without_regenerating(tmp_path):
    fixture(tmp_path)
    command = run_tests(tmp_path)
    subprocess.run([sys.executable, str(PKG_ROOT / "scripts/atlas_migrate.py"), "--root", str(tmp_path),
                    "--test-command", " ".join(command)], check=True, capture_output=True)
    old = (tmp_path / ".adapter-out/migration/manifest.json").read_bytes()
    write(tmp_path, "README.md", STALE_DOC)
    subprocess.run([sys.executable, str(PKG_ROOT / "scripts/atlas_migrate.py"), "--root", str(tmp_path),
                    "--test-command", " ".join(command)], capture_output=True)
    res = subprocess.run([sys.executable, str(PKG_ROOT / "scripts/atlas_migrate.py"), "--root", str(tmp_path),
                          "--rollback", "--json"], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    assert (tmp_path / ".adapter-out/migration/manifest.json").read_bytes() == old


def test_off_migrate_does_not_scan_run_tests_or_publish(tmp_path, monkeypatch):
    fixture(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("off mode must not collect evidence")

    monkeypatch.setattr("_support.legacy_migration._test_evidence", forbidden)
    result = migrate(tmp_path, test_command=run_tests(tmp_path), mode="off")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert not (tmp_path / ".adapter-out/migration").exists()


@pytest.mark.parametrize("module,relative", [
    ("validate_migration", ".adapter-out/migration/generations"),
    ("validate_contracts", "contracts"),
])
def test_atlas_check_does_not_skip_orphaned_generation_assets(tmp_path, module, relative):
    import shutil
    from scripts import atlas_check

    (tmp_path / relative).mkdir(parents=True)
    installed = tmp_path / ".atlas/validators"
    installed.mkdir(parents=True)
    support = tmp_path / ".atlas/_support"
    support.mkdir()
    shutil.copy(PKG_ROOT / "validators" / f"{module}.py", installed)
    for name in ("governance_io.py", "governance_schema.py", "legacy_migration.py", "semantic_contracts.py", "argv_split.py"):
        shutil.copy(PKG_ROOT / "_support" / name, support)
    rows = atlas_check.Row()
    atlas_check.check_validators(tmp_path, rows, sys.executable)
    row = next(item for item in rows.rows if item["name"] == module)
    assert row["status"] == "FAIL" and row["rc"] in (1, 2), row


def test_atlas_check_shadow_stale_is_warn_not_hard_fail(tmp_path):
    import shutil
    from scripts import atlas_check
    fixture(tmp_path, STALE_DOC)
    migrate(tmp_path, test_command=run_tests(tmp_path), mode="shadow")
    installed = tmp_path / ".atlas"
    (installed / "validators").mkdir(parents=True)
    (installed / "_support").mkdir()
    shutil.copy(PKG_ROOT / "validators/validate_migration.py", installed / "validators")
    for name in ("governance_io.py", "governance_schema.py", "legacy_migration.py", "argv_split.py"):
        shutil.copy(PKG_ROOT / "_support" / name, installed / "_support")
    rows = atlas_check.Row()
    atlas_check.check_validators(tmp_path, rows, sys.executable)
    row = next(item for item in rows.rows if item["name"] == "validate_migration")
    assert row["status"] == "WARN" and row["verdict"] == "STALE" and row["rc"] == 0


def test_node_cli_has_migrate_help_and_preserves_rc(tmp_path):
    fixture(tmp_path, STALE_DOC)
    help_result = subprocess.run(["node", str(PKG_ROOT / "bin/atlas.js"), "--help"],
                                 capture_output=True, text=True)
    assert help_result.returncode == 0 and "migrate" in help_result.stdout
    command = run_tests(tmp_path)
    result = subprocess.run(
        ["node", str(PKG_ROOT / "bin/atlas.js"), "migrate", "--root", str(tmp_path),
         "--test-command", join_command(command), "--mode", "enforce", "--json"],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)["verdict"] == "STALE"


def test_installer_selfcheck_lists_all_new_runtime_files():
    text = (PKG_ROOT / "install.py").read_text(encoding="utf-8")
    for rel in ("_support/governance_io.py", "_support/legacy_migration.py",
                "scripts/atlas_migrate.py", "validators/validate_migration.py"):
        assert rel in text


def test_validator_reports_legacy_conflict_as_stale(tmp_path):
    fixture(tmp_path, STALE_DOC)
    migrate(tmp_path, test_command=run_tests(tmp_path))
    result = check_migration(tmp_path)
    assert result["verdict"] == "STALE" and result["rc"] == 1 and result["cause"] == "contract_stale"
    assert any(item["path"] == "README.md" for item in result["findings"])


def test_new_and_removed_sources_are_stale(tmp_path):
    fixture(tmp_path)
    migrate(tmp_path, test_command=run_tests(tmp_path))
    write(tmp_path, "docs/new.md", "# New\n")
    assert check_migration(tmp_path)["verdict"] == "STALE"
    migrate(tmp_path, test_command=run_tests(tmp_path))
    (tmp_path / "docs/new.md").unlink()
    result = check_migration(tmp_path)
    assert result["verdict"] == "STALE"
    assert any("消失" in item["message"] for item in result["findings"])


def test_api_descriptor_pointer_is_explicitly_unverified(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "src/openapi.json", '{"openapi":"3.0.0","paths":{}}\n')
    result = migrate(tmp_path, test_command=run_tests(tmp_path))
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    errors = artifact(tmp_path, "parse-errors.json")["items"]
    assert any(item["kind"] == "adapter_pointer" for item in errors)


def test_atlas_check_preserves_raw_migration_verdict_cause_and_rc(tmp_path):
    import shutil
    from scripts import atlas_check

    fixture(tmp_path, STALE_DOC)
    migrate(tmp_path, test_command=run_tests(tmp_path))
    installed = tmp_path / ".atlas"
    (installed / "validators").mkdir(parents=True)
    (installed / "_support").mkdir()
    shutil.copy(PKG_ROOT / "validators/validate_migration.py", installed / "validators")
    for name in ("governance_io.py", "governance_schema.py", "legacy_migration.py", "argv_split.py"):
        shutil.copy(PKG_ROOT / "_support" / name, installed / "_support")
    rows = atlas_check.Row()
    atlas_check.check_validators(tmp_path, rows, sys.executable)
    row = next(item for item in rows.rows if item["name"] == "validate_migration")
    assert row["status"] == "FAIL"
    assert row["verdict"] == "STALE" and row["cause"] == "contract_stale" and row["rc"] == 1
    assert rows.failures[0]["code"] == 1

    write(tmp_path, ".trellis/spec/unknown.xyz", "opaque\n")
    migrate(tmp_path, test_command=run_tests(tmp_path))
    rows = atlas_check.Row()
    atlas_check.check_validators(tmp_path, rows, sys.executable)
    row = next(item for item in rows.rows if item["name"] == "validate_migration")
    assert row["status"] == "FAIL" and row["verdict"] == "UNVERIFIED"
    assert row["cause"] == "migration_unverified" and row["rc"] == 2
