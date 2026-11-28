"""RFC-20261125-01 P4 semantic counterexamples, including M249.

Removing the observed field type comparison must turn the type-drift test red.
The real four-stage proof is stored at .atlas/runs/mutation-proof/M249.txt.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support.governance_schema import canonical_digest, load_schema, validate
from _support.siblings import load_module
from _support.semantic_contracts import (
    SemanticError, check_contracts, reconcile_contract, refresh_contracts, semantic_digests,
)
from validators.validate_contracts import main as validate_main

PROFILE = """product: 语义夹具
apps:
  - name: backend
    path: src
    kind: backend
    stack: 夹具
  - name: frontend
    path: web
    kind: frontend
    stack: 夹具
"""
CODE = """from sqlalchemy import Column, Integer, String, Enum
from sqlalchemy.orm import declarative_base
Base = declarative_base()
class Search(Base):
    __tablename__ = 'search'
    id = Column(Integer, primary_key=True)
    detail_url = Column(String, nullable=False)
    status = Column(Enum('SearchStatus', 'NEW', 'PAID', name='SearchStatus'), nullable=False)
@app.get('/api/search')
def search():
    return []
"""
TEST = "def test_search():\n    assert True\n"
VIEW = "export function Search() { return <div data-testid=\"search-result\" />; }\n"


def write(root: Path, rel: str, text: str | bytes) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def _autocrlf(root: Path, enabled: bool) -> None:
    value = "true" if enabled else "false"
    result = subprocess.run(["git", "config", "core.autocrlf", value], cwd=root,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError as exc:
        if sys.platform == "win32" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("当前 Windows 用户没有创建符号链接的特权")
        raise


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def fixture(root: Path) -> str:
    write(root, "product/stack-profile.yaml", PROFILE)
    write(root, "src/main.py", CODE)
    write(root, "tests/test_search.py", TEST)
    write(root, "pytest.ini", "[pytest]\n")
    write(root, "web/search.tsx", VIEW)
    git(root, "init", "-q")
    _autocrlf(root, False)
    git(root, "config", "user.email", "semantic@example.test")
    git(root, "config", "user.name", "Semantic Test")
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    return git(root, "rev-parse", "HEAD")


def expected_store() -> dict:
    return {
        "schema_version": 1,
        "clauses": [{
            "clause_id": "R-07", "request_id": "REQ-search", "task_id": "01",
            "contracts": [
                {"kind": "route", "value": "GET /api/search"},
                {"kind": "field", "name": "id", "type": "integer", "required": True},
                {"kind": "field", "name": "detail_url", "type": "string", "required": True},
                {"kind": "field", "name": "status", "type": "SearchStatus", "required": True},
                {"kind": "enum", "name": "SearchStatus", "values": ["NEW", "PAID"]},
                {"kind": "testid", "value": "search-result"},
                {"kind": "tests", "value": "tests/test_search.py"},
            ],
        }],
    }


def seed_expected(root: Path) -> None:
    write(root, "contracts/expected.json", json.dumps(expected_store(), ensure_ascii=False))


def refresh(root: Path, commit: str, mode: str = "enforce") -> dict:
    _autocrlf(root, False)
    git(root, "add", ".")
    extractor = load_module("validate_testids")
    version = "validate_testids@" + hashlib.sha256(
        (PKG_ROOT / "validators/validate_testids.py").read_bytes()).hexdigest()[:12]
    return refresh_contracts(root, base=commit, head=commit, mode=mode, write=True,
                             testid_extractor=extractor, testid_version=version)


def check(root: Path, mode: str = "enforce") -> dict:
    _autocrlf(root, False)
    extractor = load_module("validate_testids")
    version = "validate_testids@" + hashlib.sha256(
        (PKG_ROOT / "validators/validate_testids.py").read_bytes()).hexdigest()[:12]
    return check_contracts(root, mode=mode, testid_extractor=extractor, testid_version=version)


def read_store(root: Path, name: str) -> dict:
    return json.loads((root / "contracts" / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("kind,expected,observed,verdict", [
    ("field", {"name": "detailUrl", "type": "string", "required": True},
     {"name": "detailUrl", "type": "integer", "required": True}, "FAIL"),
    ("field", {"name": "detailUrl", "type": "string", "required": True},
     {"name": "detailUrl", "type": "string", "required": False}, "FAIL"),
    ("field", {"name": "detailUrl", "type": "string", "required": True},
     {"name": "detail", "type": "object", "required": True}, "FAIL"),
    ("enum", {"name": "SearchStatus", "values": ["NEW", "PAID"]},
     {"name": "SearchStatus", "values": ["NEW", "PAID", "CANCELLED"]}, "FAIL"),
    ("testid", {"value": "search-result"}, {"value": "search-item"}, "FAIL"),
    ("testid", {"value": "search-result"}, None, "UNVERIFIED"),
    ("route", "GET /api/search/?limit=10", {"method": "GET", "path": "/api/search"}, "PASS"),
    ("route", "GET /api/search", {"method": "POST", "path": "/api/search"}, "FAIL"),
])
def test_reconcile_contract_counterexamples(kind, expected, observed, verdict):
    finding = reconcile_contract({"kind": kind, **expected} if isinstance(expected, dict)
                                 else {"kind": kind, "value": expected}, observed)
    if verdict == "PASS":
        assert finding is None
    else:
        assert finding is not None and finding["verdict"] == verdict


def test_schema_rejects_wrong_types_missing_required_and_new_enum_kind():
    expected = expected_store()
    assert validate(expected, load_schema("semantic-expected")) == []
    broken = copy.deepcopy(expected)
    broken["clauses"][0]["contracts"][1]["required"] = "true"
    assert validate(broken, load_schema("semantic-expected"))
    broken = copy.deepcopy(expected)
    del broken["clauses"][0]["contracts"][1]["type"]
    assert validate(broken, load_schema("semantic-expected"))
    broken = copy.deepcopy(expected)
    broken["clauses"][0]["contracts"][0]["kind"] = "unknown"
    assert validate(broken, load_schema("semantic-expected"))
    assert validate({}, load_schema("semantic-observed"))
    assert validate({}, load_schema("semantic-graph"))


def test_positive_adapter_projection_three_files_and_three_digests(tmp_path):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    before = (tmp_path / "contracts/expected.json").read_bytes()
    result = refresh(tmp_path, commit)
    assert result["verdict"] == "PASS" and result["rc"] == 0, result
    assert (tmp_path / "contracts/expected.json").read_bytes() == before
    assert {"expected.json", "observed.json", "graph.json", "manifest.json", "generations"} <= {
        p.name for p in (tmp_path / "contracts").iterdir()}
    manifest = json.loads((tmp_path / "contracts/manifest.json").read_text())
    assert (tmp_path / "contracts" / manifest["path"]).is_dir()
    digests = semantic_digests(tmp_path)
    assert set(digests) == {"expected", "observed", "graph"}
    assert len(set(digests.values())) == 3
    observed = read_store(tmp_path, "observed.json")
    graph = read_store(tmp_path, "graph.json")
    assert graph["expected_digest"] == digests["expected"]
    assert graph["observed_digest"] == digests["observed"]
    assert observed["base"]["commit"] == commit and observed["head"]["commit"] == commit
    assert {fact["kind"] for fact in observed["facts"]} >= {"route", "field", "enum", "testid", "tests"}
    for fact in observed["facts"]:
        assert fact["source"]["line"] >= 1
        assert hashlib.sha256((tmp_path / fact["source"]["path"]).read_bytes()).hexdigest() == fact["source"]["sha256"]
        assert fact["adapter_version"]
    for edge in graph["edges"]:
        fact = next(item for item in observed["facts"] if item["id"] == edge["to"])
        assert edge["from"] == "R-07" and edge["source"] == fact["source"]
        assert edge["sha256"] == canonical_digest(fact["value"])
        assert edge["adapter_version"] == fact["adapter_version"]
        assert edge["base"]["commit"] == commit and edge["head"]["commit"] == commit
    assert check(tmp_path, mode="enforce")["verdict"] == "PASS"


@pytest.mark.parametrize("rel,old,new", [
    ("src/main.py", "detail_url = Column(String, nullable=False)", "detail_url = Column(Integer, nullable=False)"),
    ("src/main.py", "detail_url = Column(String, nullable=False)", "detail_url = Column(String, nullable=True)"),
    ("src/main.py", "'NEW', 'PAID'", "'NEW', 'PAID', 'CANCELLED'"),
    ("src/main.py", "@app.get('/api/search')", "@app.get('/api/other')"),
    ("web/search.tsx", 'data-testid="search-result"', 'data-testid="search-item"'),
])
def test_deterministic_drift_is_fail_rc1_in_enforce(tmp_path, rel, old, new):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    path = write(tmp_path, rel, (tmp_path / rel).read_text(encoding="utf-8").replace(old, new))
    del old
    result = refresh(tmp_path, commit)
    assert result["verdict"] == "FAIL" and result["rc"] == 1 and result["cause"] == "contract_stale", result
    assert result["findings"]
    assert path.exists()


def test_missing_testid_and_new_clause_without_evidence_are_fail(tmp_path):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    write(tmp_path, "web/search.tsx", "export function Search() { return <div />; }\n")
    result = refresh(tmp_path, commit)
    assert result["verdict"] == "FAIL" and result["rc"] == 1, result
    assert any("testid" in item["message"] for item in result["findings"])
    write(tmp_path, "web/search.tsx", VIEW)
    expected = expected_store()
    expected["clauses"].append({"clause_id": "R-08", "request_id": "REQ-new", "task_id": "02",
                                "contracts": [{"kind": "testid", "value": "not-implemented"},
                                              {"kind": "field", "name": "new_field", "type": "string", "required": True},
                                              {"kind": "route", "value": "GET /api/new"}]})
    write(tmp_path, "contracts/expected.json", json.dumps(expected))
    result = refresh(tmp_path, commit)
    assert result["verdict"] == "FAIL" and result["rc"] == 1, result


def test_missing_adapter_and_dynamic_testid_are_unverified(tmp_path, monkeypatch):
    import _support.semantic_contracts as semantic
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    original = semantic._run_adapter

    def missing(root, name, out):
        if name == "models":
            raise RuntimeError("adapter missing")
        return original(root, name, out)

    monkeypatch.setattr(semantic, "_run_adapter", missing)
    result = refresh(tmp_path, commit)
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2, result
    monkeypatch.setattr(semantic, "_run_adapter", original)
    write(tmp_path, "web/search.tsx", 'const id = makeId(); <div data-testid={`${id}-row`} />;\n')
    result = refresh(tmp_path, commit)
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2, result


def test_stale_legacy_document_is_not_promoted_or_modified(tmp_path):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    legacy = write(tmp_path, "README.md", "# 旧文档\n`GET /api/old`\n`detailUrl: integer`\n")
    before = legacy.read_bytes()
    result = refresh(tmp_path, commit)
    assert result["verdict"] == "PASS", result
    assert legacy.read_bytes() == before
    assert read_store(tmp_path, "expected.json") == expected_store()


def test_modes_shadow_off_and_enforce_preserve_raw_verdict_and_rc(tmp_path):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    write(tmp_path, "src/main.py", (tmp_path / "src/main.py").read_text().replace(
        "detail_url = Column(String, nullable=False)", "detail_url = Column(Integer, nullable=False)"))
    default = refresh(tmp_path, commit, None)
    assert default["mode"] == "shadow" and default["verdict"] == "FAIL" and default["rc"] == 0
    shadow = refresh(tmp_path, commit, "shadow")
    assert shadow["verdict"] == "FAIL" and shadow["rc"] == 0
    off = refresh(tmp_path, commit, "off")
    assert off["verdict"] == "UNVERIFIED" and off["rc"] == 2 and off["cause"] is None
    enforce = refresh(tmp_path, commit, "enforce")
    assert enforce["verdict"] == "FAIL" and enforce["rc"] == 1
    common = load_schema("governance-common")
    assert validate(default, common) == []
    assert validate(off, common) == []
    assert validate(enforce, common) == []


def test_refresh_rejects_expected_change_between_projection_and_publication(tmp_path, monkeypatch):
    import _support.semantic_contracts as semantic

    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    assert refresh(tmp_path, commit)["verdict"] == "PASS"
    pointer = tmp_path / "contracts/manifest.json"
    before = pointer.read_bytes()
    original = semantic._project_adapters

    def project_then_change(*args, **kwargs):
        observed = original(*args, **kwargs)
        changed = expected_store()
        changed["clauses"][0]["request_id"] = "REQ-concurrent"
        write(tmp_path, "contracts/expected.json", json.dumps(changed))
        return observed

    monkeypatch.setattr(semantic, "_project_adapters", project_then_change)
    with pytest.raises(SemanticError, match="expected"):
        refresh(tmp_path, commit)
    assert pointer.read_bytes() == before
    checked = check(tmp_path)
    assert checked["verdict"] == "FAIL" and checked["cause"] == "contract_stale"


def test_publication_hashes_the_same_expected_bytes_it_publishes(tmp_path):
    import _support.semantic_contracts as semantic

    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    assert refresh(tmp_path, commit)["verdict"] == "PASS"
    changed = expected_store()
    changed["clauses"][0]["request_id"] = "REQ-new-snapshot"
    write(tmp_path, "contracts/expected.json", json.dumps(changed))
    semantic._publish_stores(tmp_path, read_store(tmp_path, "observed.json"),
                             read_store(tmp_path, "graph.json"))
    pointer = read_store(tmp_path, "manifest.json")
    directory = tmp_path / "contracts" / pointer["path"]
    artifacts = {name.removesuffix(".json"): json.loads((directory / name).read_text()) for name in pointer["files"]}
    assert canonical_digest(artifacts) == pointer["generation"]
    assert read_store(tmp_path, "expected.json") == artifacts["expected"] == changed


def test_semantic_publication_failure_keeps_pointer_and_last_known_good(tmp_path, monkeypatch):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    assert refresh(tmp_path, commit)["verdict"] == "PASS"
    pointer = tmp_path / "contracts/manifest.json"
    before = pointer.read_bytes()
    import _support.semantic_contracts as semantic
    original = semantic.atomic_write_bytes

    def fail_fixed_graph(path, data):
        if Path(path) == tmp_path / "contracts/graph.json":
            raise OSError("injected graph snapshot failure")
        return original(path, data)

    monkeypatch.setattr(semantic, "atomic_write_bytes", fail_fixed_graph)
    with pytest.raises(OSError, match="injected"):
        refresh(tmp_path, commit)
    assert pointer.read_bytes() == before
    checked = check(tmp_path, mode="enforce")
    assert checked["verdict"] == "PASS", json.dumps(checked, ensure_ascii=False)


def test_non_object_semantic_pointer_is_fail_not_crash(tmp_path):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    refresh(tmp_path, commit)
    (tmp_path / "contracts/manifest.json").write_text("[]")
    result = check(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1


def test_semantic_check_rejects_pointer_tamper_extra_files_and_symlink(tmp_path):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    assert refresh(tmp_path, commit)["verdict"] == "PASS"
    pointer = tmp_path / "contracts/manifest.json"
    manifest = json.loads(pointer.read_text())
    original = pointer.read_bytes()
    manifest["business_digest"] = "0" * 64
    pointer.write_text(json.dumps(manifest))
    assert check(tmp_path, mode="enforce")["verdict"] == "FAIL"
    pointer.write_bytes(original)
    generation = tmp_path / "contracts" / json.loads(original)["path"]
    (generation / "unbound.txt").write_text("extra")
    assert check(tmp_path, mode="enforce")["verdict"] == "FAIL"
    (generation / "unbound.txt").unlink()
    pointer.unlink()
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    symlink_or_skip(pointer, outside)
    assert check(tmp_path, mode="enforce")["verdict"] == "FAIL"
    with pytest.raises(SemanticError, match="manifest"):
        refresh(tmp_path, commit)
    assert pointer.is_symlink()


def test_first_manifest_failure_never_falls_back_to_fixed_projection(tmp_path, monkeypatch):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    import _support.semantic_contracts as semantic
    original = semantic.atomic_write_json

    def fail_pointer(path, value):
        if Path(path) == tmp_path / "contracts/manifest.json":
            raise OSError("injected first pointer failure")
        return original(path, value)

    monkeypatch.setattr(semantic, "atomic_write_json", fail_pointer)
    with pytest.raises(OSError, match="injected"):
        refresh(tmp_path, commit)
    result = check(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1


def test_semantic_rollback_cli_non_object_pointer_is_structured_fail(tmp_path):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    refresh(tmp_path, commit)
    (tmp_path / "contracts/manifest.json").write_text("[]")
    result = subprocess.run([sys.executable, str(PKG_ROOT / "scripts/atlas_contracts.py"),
                             "--root", str(tmp_path), "--mode", "enforce", "--json", "rollback"],
                            capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads(result.stdout)["verdict"] == "FAIL"


def test_semantic_rollback_refuses_to_overwrite_changed_expected(tmp_path):
    from _support.semantic_contracts import rollback_contracts
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    refresh(tmp_path, commit)
    expected = expected_store()
    expected["clauses"][0]["request_id"] = "REQ-user-edit"
    write(tmp_path, "contracts/expected.json", json.dumps(expected))
    refresh(tmp_path, commit)
    pointer = tmp_path / "contracts/manifest.json"
    before_pointer = pointer.read_bytes()
    before_expected = (tmp_path / "contracts/expected.json").read_bytes()
    result = rollback_contracts(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert pointer.read_bytes() == before_pointer
    assert (tmp_path / "contracts/expected.json").read_bytes() == before_expected


def test_semantic_rollback_off_does_not_switch_pointer(tmp_path):
    from _support.semantic_contracts import rollback_contracts
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    refresh(tmp_path, commit)
    write(tmp_path, "src/main.py", CODE + "# next\n")
    refresh(tmp_path, commit)
    pointer = tmp_path / "contracts/manifest.json"
    before = pointer.read_bytes()
    result = rollback_contracts(tmp_path, mode="off")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2 and result["mode"] == "off"
    assert pointer.read_bytes() == before


def test_semantic_rollback_switches_to_previous_generation(tmp_path):
    from _support.semantic_contracts import rollback_contracts
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    assert refresh(tmp_path, commit)["verdict"] == "PASS"
    first = json.loads((tmp_path / "contracts/manifest.json").read_text())["generation"]
    write(tmp_path, "src/main.py", CODE + "# next generation\n")
    assert refresh(tmp_path, commit)["verdict"] == "PASS"
    result = rollback_contracts(tmp_path)
    assert result["generation"] == first
    assert json.loads((tmp_path / "contracts/manifest.json").read_text())["generation"] == first
    write(tmp_path, "src/main.py", CODE)
    git(tmp_path, "add", "src/main.py")
    assert check(tmp_path, mode="enforce")["verdict"] == "PASS"


def test_publish_rejects_damaged_previous_semantic_generation(tmp_path):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    assert refresh(tmp_path, commit)["verdict"] == "PASS"
    pointer = tmp_path / "contracts/manifest.json"
    manifest = json.loads(pointer.read_text())
    manifest["business_digest"] = "0" * 64
    pointer.write_text(json.dumps(manifest))
    before = pointer.read_bytes()
    write(tmp_path, "src/main.py", CODE.replace("postgres:16", "postgres:17"))
    with pytest.raises(SemanticError, match="manifest|digest|generation"):
        refresh(tmp_path, commit)
    assert pointer.read_bytes() == before


def test_graph_digest_and_source_tamper_are_fail(tmp_path):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    assert refresh(tmp_path, commit)["verdict"] == "PASS"
    manifest = json.loads((tmp_path / "contracts/manifest.json").read_text())
    generation = tmp_path / "contracts" / manifest["path"]
    graph_path = generation / "graph.json"
    graph_bytes = graph_path.read_bytes()
    graph = json.loads(graph_bytes)
    graph["expected_digest"] = "0" * 64
    graph_path.write_text(json.dumps(graph))
    result = check(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    graph_path.write_bytes(graph_bytes)
    assert refresh(tmp_path, commit)["verdict"] == "PASS"
    manifest = json.loads((tmp_path / "contracts/manifest.json").read_text())
    observed_path = tmp_path / "contracts" / manifest["path"] / "observed.json"
    observed_bytes = observed_path.read_bytes()
    observed = json.loads(observed_bytes)
    observed["facts"][0]["source"]["sha256"] = "0" * 64
    observed_path.write_text(json.dumps(observed))
    assert check(tmp_path, mode="enforce")["verdict"] == "FAIL"


def test_cli_returns_real_enforce_rc_and_json(tmp_path):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    write(tmp_path, "src/main.py", (tmp_path / "src/main.py").read_text().replace(
        "detail_url = Column(String, nullable=False)", "detail_url = Column(Integer, nullable=False)"))
    git(tmp_path, "add", ".")
    result = subprocess.run([sys.executable, str(PKG_ROOT / "scripts/atlas_contracts.py"),
                             "--root", str(tmp_path), "--base", commit, "--head", commit,
                             "--mode", "enforce", "--write", "--json", "check"],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "FAIL" and payload["cause"] == "contract_stale"
    assert validate_main(["--root", str(tmp_path), "--mode", "off", "--json"]) == 2


def test_staged_blob_not_working_tree_controls_projection_and_check(tmp_path):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    assert refresh(tmp_path, commit)["verdict"] == "PASS"
    path = write(tmp_path, "src/main.py", (tmp_path / "src/main.py").read_text().replace(
        "detail_url = Column(String, nullable=False)", "detail_url = Column(Integer, nullable=False)"))
    git(tmp_path, "add", "src/main.py")
    path.write_text(CODE, encoding="utf-8")
    assert check(tmp_path, mode="enforce")["verdict"] == "FAIL"
    extractor = load_module("validate_testids")
    version = "validate_testids@" + hashlib.sha256(
        (PKG_ROOT / "validators/validate_testids.py").read_bytes()).hexdigest()[:12]
    result = refresh_contracts(tmp_path, base=commit, head=commit, mode="enforce",
                               testid_extractor=extractor, testid_version=version)
    assert result["verdict"] == "FAIL" and result["cause"] == "contract_stale", result
    assert check(tmp_path, mode="enforce")["verdict"] == "FAIL"


def test_new_staged_orphan_route_is_fail_even_if_worktree_restored(tmp_path):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    assert refresh(tmp_path, commit)["verdict"] == "PASS"
    path = write(tmp_path, "src/main.py", CODE + "\n@app.post('/api/orphan')\ndef orphan():\n    return []\n")
    _autocrlf(tmp_path, False)
    git(tmp_path, "add", "src/main.py")
    path.write_text(CODE, encoding="utf-8")
    extractor = load_module("validate_testids")
    version = "validate_testids@" + hashlib.sha256(
        (PKG_ROOT / "validators/validate_testids.py").read_bytes()).hexdigest()[:12]
    result = refresh_contracts(tmp_path, base=commit, head=commit, mode="enforce",
                               testid_extractor=extractor, testid_version=version)
    assert result["verdict"] == "FAIL" and result["cause"] == "contract_stale", result
    assert any("未挂条款" in item["message"] for item in result["findings"])


def test_head_tree_projection_does_not_fall_back_to_current_index(tmp_path):
    base = fixture(tmp_path)
    seed_expected(tmp_path)
    write(tmp_path, "src/main.py", CODE.replace(
        "detail_url = Column(String, nullable=False)", "detail_url = Column(Integer, nullable=False)"))
    git(tmp_path, "add", "src/main.py")
    git(tmp_path, "commit", "-qm", "integer head")
    head = git(tmp_path, "rev-parse", "HEAD")
    _autocrlf(tmp_path, False)
    write(tmp_path, "src/main.py", CODE)
    git(tmp_path, "add", "src/main.py")
    extractor = load_module("validate_testids")
    version = "validate_testids@" + hashlib.sha256(
        (PKG_ROOT / "validators/validate_testids.py").read_bytes()).hexdigest()[:12]
    result = refresh_contracts(tmp_path, base=base, head=head, mode="enforce",
                               testid_extractor=extractor, testid_version=version)
    assert result["verdict"] == "FAIL" and result["cause"] == "contract_stale", result


def test_node_level_test_contract_is_unverified_when_adapter_only_has_file(tmp_path):
    commit = fixture(tmp_path)
    expected = expected_store()
    expected["clauses"][0]["contracts"] = [{"kind": "tests", "value": "tests/test_search.py::test_a"}]
    write(tmp_path, "contracts/expected.json", json.dumps(expected))
    result = refresh(tmp_path, commit)
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2, result
    assert any("缺少观测证据" in item["message"] for item in result["findings"])


def test_non_ascii_staged_orphan_route_is_fail(tmp_path):
    commit = fixture(tmp_path)
    seed_expected(tmp_path)
    assert refresh(tmp_path, commit)["verdict"] == "PASS"
    write(tmp_path, "src/新增.py", "@app.get('/api/orphan')\ndef orphan():\n    return []\n")
    _autocrlf(tmp_path, False)
    git(tmp_path, "add", "src/新增.py")
    result = refresh(tmp_path, commit)
    assert result["verdict"] == "FAIL" and result["cause"] == "contract_stale", result
    assert any("未挂条款" in item["message"] for item in result["findings"])


def test_unimplemented_adapter_dimensions_are_explicit_unverified(tmp_path):
    commit = fixture(tmp_path)
    expected = expected_store()
    expected["clauses"][0]["contracts"].extend([
        {"kind": "error_code", "value": "E_SEARCH"},
        {"kind": "config", "value": "search.page_size"},
        {"kind": "cli", "value": "--limit"},
        {"kind": "state", "value": {"from": "NEW", "to": "PAID"}},
        {"kind": "ac", "value": "AC-SEARCH-007"},
    ])
    write(tmp_path, "contracts/expected.json", json.dumps(expected))
    assert validate(expected, load_schema("semantic-expected")) == []
    result = refresh(tmp_path, commit)
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2, result
    assert sum(item["cause"] == "contract_unverified" for item in result["findings"]) >= 5


def test_missing_expected_is_unverified_not_auto_generated(tmp_path):
    commit = fixture(tmp_path)
    with pytest.raises(SemanticError):
        refresh(tmp_path, commit)
    assert not (tmp_path / "contracts/expected.json").exists()
