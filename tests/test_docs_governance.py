"""M247: RFC-20261125-01 P2 explicit Docs Governance counterexamples.

First paragraph declaration: removing the unchanged-body/no-evidence touch
guards must turn the stale-clearing counterexamples red. The real four-stage
mutation_proof is stored at .atlas/runs/mutation-proof/M247.txt.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from _support.docs_governance import (
    DocsGovernanceError,
    check_docs,
    check_docs_for_ids,
    list_documents,
    load_registry,
    parse_docs_yaml,
    touch_document,
)
from _support.governance_schema import load_schema, validate
from validators.validate_docs_governance import main as validator_main


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def document(**changes) -> dict:
    value = {
        "id": "DOC-guide",
        "path": "docs/guide.md",
        "owner": "docs-team",
        "kind": "guide",
        "status": "active",
        "reviewed_at": "2026-11-01",
        "review_due": "2099-12-31",
        "source_paths": ["src/app.py"],
        "links": [],
    }
    value.update(changes)
    return value


def registry(root: Path, *documents: dict, as_json: bool = False) -> Path:
    value = {"version": 1, "documents": list(documents) or [document()]}
    path = root / "product/docs/governance.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if as_json:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        lines = ["version: 1", "documents:"]
        for item in value["documents"]:
            lines.append("  - id: " + item["id"])
            for key in ("path", "owner", "kind", "status", "reviewed_at", "review_due"):
                lines.append(f"    {key}: {item[key]}")
            lines.append("    source_paths:")
            lines.extend(f"      - {source}" for source in item["source_paths"])
            lines.append("    links: [" + ", ".join(json.dumps(link, ensure_ascii=False) for link in item["links"]) + "]")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def fixture(root: Path, **changes) -> tuple[bytes, bytes]:
    write(root, "docs/guide.md", "# Guide\n\nUse the API.\n")
    write(root, "src/app.py", "VALUE = 1\n")
    registry(root, document(**changes))
    return (root / "docs/guide.md").read_bytes(), (root / "src/app.py").read_bytes()


def events(root: Path) -> list[dict]:
    path = root / "product/docs/governance-events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def baseline(root: Path) -> None:
    touch_document(root, "DOC-guide", "reviewer", "file:src/app.py#L1")


def assert_common(result: dict) -> None:
    assert validate(result, load_schema("governance-common")) == [], result


def test_yaml_subset_and_json_registry_are_equivalent(tmp_path):
    text = """# explicit declarations only
version: 1
documents:
  - id: 'DOC-guide'
    path: "docs/guide.md"
    owner: docs-team
    kind: guide
    status: active
    reviewed_at: 2026-11-01
    review_due: 2099-12-31
    source_paths: [src/app.py, 'src/config.yaml']
    links:
      - https://example.com/spec
      - docs/other.md#usage
"""
    parsed = parse_docs_yaml(text)
    assert parsed == {"version": 1, "documents": [document(source_paths=["src/app.py", "src/config.yaml"], links=["https://example.com/spec", "docs/other.md#usage"])]}
    fixture(tmp_path)
    assert load_registry(tmp_path)["documents"] == [document()]
    registry(tmp_path, as_json=True)
    assert load_registry(tmp_path)["documents"] == [document()]


@pytest.mark.parametrize("text", [
    "version: 1\nversion: 1\ndocuments: []\n",
    "version: 1\ndocuments:\n\t- id: DOC-x\n",
    "version: 1\ndocuments: [\n",
    "version: 1\ndocuments:\n  - id: DOC-x\n    owner: one\n    owner: two\n",
    "version: 1\ndocuments: &anchor []\n",
])
def test_yaml_rejects_duplicate_tabs_truncated_and_unsupported_syntax(text):
    with pytest.raises(DocsGovernanceError):
        parse_docs_yaml(text)


def test_registry_stores_declarations_not_machine_digests(tmp_path):
    write(tmp_path, "docs/guide.md", "# Guide\n")
    write(tmp_path, "src/app.py", "VALUE = 1\n")
    path = registry(tmp_path, document(summary="not allowed"))
    # The helper cannot express YAML unknown fields, so append one explicitly.
    path.write_text(path.read_text(encoding="utf-8") + "    summary: forbidden\n", encoding="utf-8")
    with pytest.raises(DocsGovernanceError):
        load_registry(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace("    summary: forbidden\n", ""), encoding="utf-8")
    baseline(tmp_path)
    event = events(tmp_path)[0]
    assert set(event["old"]) == {"document", "sources"}
    assert "summary" not in path.read_text(encoding="utf-8")


def test_positive_list_check_touch_and_event_schema_without_body_writes(tmp_path):
    doc_bytes, source_bytes = fixture(tmp_path)
    before_registry = (tmp_path / "product/docs/governance.yaml").read_bytes()
    assert list_documents(tmp_path) == [document()]
    baseline(tmp_path)
    ledger = (tmp_path / "product/docs/governance-events.jsonl").read_bytes()
    event = events(tmp_path)[0]
    assert validate(event, load_schema("docs-governance-event")) == []
    assert event["actor"] == "reviewer" and event["evidence"] == "file:src/app.py#L1"
    assert event["kind"] == "touch"
    assert event["old"]["document"] == event["new"]["document"] == hashlib.sha256(doc_bytes).hexdigest()
    assert event["new"]["sources"] == {"src/app.py": hashlib.sha256(source_bytes).hexdigest()}
    first = check_docs(tmp_path, mode="enforce")
    second = check_docs(tmp_path, mode="enforce")
    assert first == second and first["verdict"] == "PASS" and first["rc"] == 0
    assert_common(first)
    assert (tmp_path / "product/docs/governance-events.jsonl").read_bytes() == ledger
    assert (tmp_path / "docs/guide.md").read_bytes() == doc_bytes
    assert (tmp_path / "src/app.py").read_bytes() == source_bytes
    assert (tmp_path / "product/docs/governance.yaml").read_bytes() == before_registry


def test_source_change_is_fail_unchanged_touch_cannot_clear_it_then_update_and_touch_green(tmp_path):
    doc_bytes, _ = fixture(tmp_path)
    baseline(tmp_path)
    old_event = events(tmp_path)[0]
    write(tmp_path, "src/app.py", "VALUE = 2\n")
    stale = check_docs(tmp_path, mode="enforce")
    assert stale["verdict"] == "FAIL" and stale["rc"] == 1 and stale["cause"] == "docs_stale"
    assert stale["findings"]
    assert (tmp_path / "docs/guide.md").read_bytes() == doc_bytes
    with pytest.raises(DocsGovernanceError, match="正文未变化"):
        touch_document(tmp_path, "DOC-guide", "reviewer", "file:src/app.py#L1")
    assert len(events(tmp_path)) == 1
    assert check_docs(tmp_path, mode="enforce")["verdict"] == "FAIL"
    write(tmp_path, "docs/guide.md", "# Guide\n\nUse API v2.\n")
    event = touch_document(tmp_path, "DOC-guide", "reviewer", "file:docs/guide.md#L3")
    assert event["old"] == old_event["new"]
    assert event["new"]["document"] != event["old"]["document"]
    assert event["new"]["sources"]["src/app.py"] != event["old"]["sources"]["src/app.py"]
    assert check_docs(tmp_path, mode="enforce")["verdict"] == "PASS"


def test_touch_requires_actor_and_evidence_and_never_appends_on_rejection(tmp_path):
    fixture(tmp_path)
    with pytest.raises(DocsGovernanceError, match="actor"):
        touch_document(tmp_path, "DOC-guide", " ", "file:src/app.py#L1")
    with pytest.raises(DocsGovernanceError, match="证据"):
        touch_document(tmp_path, "DOC-guide", "reviewer", " ")
    assert events(tmp_path) == []


def test_no_impact_requires_source_drift_and_objective_evidence_and_is_attestation(tmp_path):
    doc_bytes, _ = fixture(tmp_path)
    baseline(tmp_path)
    write(tmp_path, "src/app.py", "VALUE = 2\n")
    for evidence in ("looks fine", "command:trust-me"):
        with pytest.raises(DocsGovernanceError, match="客观证据"):
            touch_document(tmp_path, "DOC-guide", "reviewer", evidence, no_impact=True)
    assert len(events(tmp_path)) == 1
    event = touch_document(tmp_path, "DOC-guide", "reviewer", "file:src/app.py#L1", no_impact=True)
    assert event["kind"] == "attestation"
    assert event["evidence"] == "file:src/app.py#L1"
    assert event["old"]["document"] == event["new"]["document"] == hashlib.sha256(doc_bytes).hexdigest()
    assert event["old"]["sources"] != event["new"]["sources"]
    assert check_docs(tmp_path, mode="enforce")["verdict"] == "PASS"
    with pytest.raises(DocsGovernanceError, match="仅适用"):
        touch_document(tmp_path, "DOC-guide", "reviewer", "file:src/app.py#L1", no_impact=True)


def test_cli_touch_no_impact_and_validator_exit_codes(tmp_path):
    fixture(tmp_path)
    baseline(tmp_path)
    write(tmp_path, "src/app.py", "VALUE = 2\n")
    cli = [sys.executable, str(PKG_ROOT / "scripts/atlas_docs.py"), "--root", str(tmp_path), "--mode", "enforce"]
    rejected = subprocess.run(cli + ["touch", "DOC-guide", "--by", "r", "--evidence", "file:src/app.py#L1", "--json"], capture_output=True, text=True)
    assert rejected.returncode == 1 and json.loads(rejected.stdout)["verdict"] == "FAIL"
    accepted = subprocess.run(cli + ["touch", "DOC-guide", "--by", "r", "--evidence", "file:src/app.py#L1", "--no-impact", "--json"], capture_output=True, text=True)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert json.loads(accepted.stdout)["kind"] == "attestation"
    checked = subprocess.run([sys.executable, str(PKG_ROOT / "validators/validate_docs_governance.py"), "--root", str(tmp_path), "--mode", "enforce", "--json"], capture_output=True, text=True)
    assert checked.returncode == 0 and json.loads(checked.stdout)["verdict"] == "PASS"


def test_parent_relative_link_is_allowed_but_escape_is_rejected(tmp_path):
    write(tmp_path, "README.md", "# Root\n")
    write(tmp_path, "src/app.py", "VALUE = 1\n")
    write(tmp_path, "docs/guide/a.md", "# A\n")
    registry(tmp_path, document(path="docs/guide/a.md", links=["../../README.md", "../b.md"]))
    write(tmp_path, "docs/b.md", "# B\n")
    baseline(tmp_path)
    assert check_docs(tmp_path, mode="enforce")["verdict"] == "PASS"
    registry(tmp_path, document(path="docs/guide/a.md", links=["../../../etc/passwd"]))
    assert check_docs(tmp_path, mode="enforce")["verdict"] == "FAIL"


def test_case_variant_registry_and_generated_paths_are_rejected(tmp_path):
    from _support.docs_governance import _dedicated_reason
    from _support.layout import load_layout
    assert "禁止登记" in _dedicated_reason(tmp_path, "Product/docs/governance.yaml", load_layout(tmp_path))
    assert "禁止登记" in _dedicated_reason(tmp_path, ".ATLAS/config.yaml", load_layout(tmp_path))


def test_missing_ledger_is_stale_in_enforce(tmp_path):
    fixture(tmp_path)
    (tmp_path / "product/docs/governance-events.jsonl").unlink(missing_ok=True)
    result = check_docs(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["cause"] == "docs_stale"


def test_random_hash_is_not_objective_no_impact_evidence(tmp_path):
    fixture(tmp_path)
    baseline(tmp_path)
    write(tmp_path, "src/app.py", "VALUE = 2\n")
    with pytest.raises(DocsGovernanceError, match="客观证据"):
        touch_document(tmp_path, "DOC-guide", "r", "a" * 64, no_impact=True)


def test_commit_no_impact_evidence_must_touch_and_match_sources(tmp_path):
    fixture(tmp_path)
    for args in (("init", "-q"), ("config", "user.email", "docs@example.test"),
                     ("config", "user.name", "Docs Test"), ("config", "core.autocrlf", "false"),
                     ("add", "."), ("commit", "-qm", "base")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    baseline(tmp_path)
    write(tmp_path, "README.md", "unrelated\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "unrelated"], cwd=tmp_path, check=True)
    unrelated = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    write(tmp_path, "src/app.py", "VALUE = 2\n")
    with pytest.raises(DocsGovernanceError, match="客观证据"):
        touch_document(tmp_path, "DOC-guide", "reviewer", unrelated, no_impact=True)
    subprocess.run(["git", "add", "src/app.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "source change"], cwd=tmp_path, check=True)
    relevant = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    event = touch_document(tmp_path, "DOC-guide", "reviewer", relevant, no_impact=True)
    assert event["kind"] == "attestation"
    assert check_docs(tmp_path, mode="enforce")["verdict"] == "PASS"


def test_registry_io_error_is_unverified_rc2(tmp_path, monkeypatch):
    import _support.docs_governance as docs
    fixture(tmp_path)

    def unavailable(_root):
        raise OSError("injected I/O")

    monkeypatch.setattr(docs, "load_registry", unavailable)
    result = check_docs(tmp_path, mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert result["cause"] == "docs_unverified"


def test_document_read_io_error_is_unverified_rc2(tmp_path, monkeypatch):
    import _support.docs_governance as docs
    fixture(tmp_path)
    baseline(tmp_path)

    def unavailable(_path):
        raise PermissionError("injected permission")

    monkeypatch.setattr(docs, "_hash_file", unavailable)
    result = check_docs(tmp_path, mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert result["cause"] == "docs_unverified"


def test_nested_relative_link_does_not_fall_back_to_root(tmp_path):
    write(tmp_path, "README.md", "# Root\n")
    write(tmp_path, "src/app.py", "VALUE = 1\n")
    write(tmp_path, "docs/guide/a.md", "# A\n")
    registry(tmp_path, document(path="docs/guide/a.md", links=["README.md"]))
    baseline(tmp_path)
    result = check_docs(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert any("死链" in item["message"] for item in result["findings"])


def test_no_impact_evidence_io_error_propagates_as_unverified(tmp_path, monkeypatch):
    import _support.docs_governance as docs
    fixture(tmp_path)
    baseline(tmp_path)
    write(tmp_path, "src/app.py", "VALUE = 2\n")

    def unavailable(_path):
        raise PermissionError("injected permission")

    monkeypatch.setattr(docs, "_hash_file", unavailable)
    with pytest.raises(OSError):
        touch_document(tmp_path, "DOC-guide", "reviewer", "file:src/app.py#L1", no_impact=True)


def test_evidence_digest_io_error_is_not_hashed_as_fallback(tmp_path, monkeypatch):
    import _support.docs_governance as docs
    write(tmp_path, "src/app.py", "VALUE = 1\n")

    def unavailable(_path):
        raise PermissionError("injected permission")

    monkeypatch.setattr(docs, "_hash_file", unavailable)
    with pytest.raises(OSError):
        docs._evidence_digest(tmp_path, "file:src/app.py#L1")


def test_docs_io_result_matches_common_schema_and_cli_shadow_mode(tmp_path, monkeypatch):
    import _support.docs_governance as docs
    from _support.governance_schema import load_schema, validate
    fixture(tmp_path)

    def unavailable(_root):
        raise OSError("injected I/O")

    monkeypatch.setattr(docs, "load_registry", unavailable)
    result = check_docs(tmp_path, mode="enforce")
    assert result["cause"] == "docs_unverified" and result["rc"] == 2
    assert validate(result, load_schema("governance-common")) == []
    cli = [sys.executable, str(PKG_ROOT / "scripts/atlas_docs.py"), "--root", str(tmp_path),
           "--mode", "shadow", "--json", "touch", "DOC-x", "--by", "o", "--evidence", "file:src/app.py"]
    failed = subprocess.run(cli, capture_output=True, text=True)
    assert failed.returncode == 0
    payload = json.loads(failed.stdout)
    assert payload["mode"] == "shadow" and payload["rc"] == 0 and payload["verdict"] == "FAIL"


def test_relative_markdown_link_resolves_from_document_directory(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "docs/other.md", "# Other\n")
    registry = tmp_path / "product/docs/governance.yaml"
    registry.write_text(registry.read_text().replace("links: []", "links: [other.md]"), encoding="utf-8")
    baseline(tmp_path)
    assert check_docs(tmp_path, mode="enforce")["verdict"] == "PASS"


def test_shadow_preserves_findings_off_is_unverified_rc2(tmp_path):
    fixture(tmp_path)
    baseline(tmp_path)
    write(tmp_path, "src/app.py", "VALUE = 2\n")
    shadow = check_docs(tmp_path)
    assert shadow["mode"] == "shadow" and shadow["verdict"] == "FAIL" and shadow["rc"] == 0
    assert shadow["findings"] and shadow["cause"] == "docs_stale"
    assert_common(shadow)
    off = check_docs(tmp_path, mode="off")
    assert off["mode"] == "off" and off["verdict"] == "UNVERIFIED" and off["rc"] == 2 and off["cause"] is None
    assert_common(off)
    assert validator_main(["--root", str(tmp_path), "--mode", "off", "--json"]) == 2


@pytest.mark.parametrize("rel", [
    "product/prd/prd.md",
    "product/e2e/index.md",
    ".atlas/spec/structure/global/runtime-topology.md",
    "product/adr/0001-choice.md",
    "docs/map/index.md",
    "product/requirements/REQ-demo/requirement.md",
    "product/incidents/INC-20261125-001/report.md",
    ".adapter-out/topology.json",
    ".adapter-out/adopt/facts.json",
    ".atlas/runs/workflow-receipt.json",
])
def test_specialized_and_generated_documents_are_rejected_with_one_docs_finding(tmp_path, rel):
    fixture(tmp_path, path=rel, source_paths=["src/app.py"])
    write(tmp_path, rel, "# Dedicated artifact\n")
    result = check_docs(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    findings = [item for item in result["findings"] if item.get("path") == rel]
    assert len(findings) == 1, findings
    assert findings[0]["cause"] in ("docs_stale", "docs_owner_missing")
    assert "表格" not in findings[0]["message"]


def test_mechanism_frontmatter_is_rejected_once(tmp_path):
    fixture(tmp_path, path="docs/design.md", source_paths=["src/app.py"])
    write(tmp_path, "docs/design.md", "---\nmechanism-paths: src/**\n---\n# Design\n")
    result = check_docs(tmp_path, mode="enforce")
    findings = [item for item in result["findings"] if item.get("path") == "docs/design.md"]
    assert len(findings) == 1 and "mechanism" in findings[0]["message"]


@pytest.mark.parametrize("rel", ["../outside.md", "/etc/passwd", "C:\\Windows\\x", "docs/../../outside.md"])
def test_escape_and_absolute_paths_fail(tmp_path, rel):
    fixture(tmp_path, path=rel)
    result = check_docs(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["cause"] == "docs_stale"
    assert any("schema" in item["message"] for item in result["findings"])


def test_symlink_document_and_source_fail_even_when_target_inside_root(tmp_path):
    fixture(tmp_path)
    write(tmp_path, "docs/real.md", "# Real\n")
    (tmp_path / "docs/guide.md").unlink()
    try:
        (tmp_path / "docs/guide.md").symlink_to("real.md")
    except OSError as exc:
        if sys.platform == "win32" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("当前 Windows 用户没有创建符号链接的特权")
        raise
    result = check_docs(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL"
    assert any(item.get("path") == "docs/guide.md" and "符号链接" in item["message"] for item in result["findings"])
    (tmp_path / "docs/guide.md").unlink()
    write(tmp_path, "docs/guide.md", "# Guide\n")
    (tmp_path / "src/app.py").unlink()
    try:
        (tmp_path / "src/app.py").symlink_to("../docs/real.md")
    except OSError as exc:
        if sys.platform == "win32" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("当前 Windows 用户没有创建符号链接的特权")
        raise
    result = check_docs(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL"
    assert any(item.get("path") == "src/app.py" and "符号链接" in item["message"] for item in result["findings"])


def test_missing_owner_duplicate_id_dead_link_and_overdue(tmp_path):
    fixture(tmp_path, owner=" ", links=["docs/missing.md#usage"])
    registry(tmp_path, document(owner=" ", links=["docs/missing.md#usage"]), as_json=True)
    result = check_docs(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["cause"] == "docs_owner_missing"
    assert any(item["cause"] == "docs_owner_missing" for item in result["findings"])
    assert any(item["cause"] == "docs_stale" and "死链" in item["message"] for item in result["findings"])
    registry(tmp_path, document(), document(path="docs/other.md"))
    write(tmp_path, "docs/other.md", "# Other\n")
    duplicate = check_docs(tmp_path, mode="enforce")
    assert duplicate["verdict"] == "FAIL"
    assert sum("重复 ID" in item["message"] for item in duplicate["findings"]) == 1
    registry(tmp_path, document(review_due="2020-01-01"))
    baseline(tmp_path)
    overdue = check_docs(tmp_path, mode="enforce")
    assert overdue["verdict"] == "WARN" and overdue["rc"] == 0
    assert any("超期" in item["message"] for item in overdue["findings"])


def test_empty_owner_schema_failure_uses_owner_cause(tmp_path):
    fixture(tmp_path)
    registry(tmp_path, document(owner=""), as_json=True)
    result = check_docs(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["cause"] == "docs_owner_missing"
    assert_common(result)


def test_attestation_evidence_becoming_unavailable_fails_closed(tmp_path):
    fixture(tmp_path)
    evidence = write(tmp_path, "evidence/check.txt", "checked\n")
    registry(tmp_path, document(source_paths=["src/app.py", "evidence/check.txt"]))
    baseline(tmp_path)
    write(tmp_path, "src/app.py", "VALUE = 2\n")
    touch_document(tmp_path, "DOC-guide", "reviewer", "file:evidence/check.txt#L1", no_impact=True)
    assert check_docs(tmp_path, mode="enforce")["verdict"] == "PASS"
    evidence.unlink()
    result = check_docs(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["cause"] == "docs_stale"
    assert result["findings"]


def test_local_links_check_files_fragments_and_external_links_are_not_fetched(tmp_path):
    fixture(tmp_path, links=["other.md#usage", "other.md#missing", "https://example.com/never-fetch"])
    write(tmp_path, "docs/other.md", "# Other\n\n## Usage\n")
    result = check_docs(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL"
    dead = [item for item in result["findings"] if "死链" in item["message"]]
    assert len(dead) == 1 and "#missing" in dead[0]["message"]


def test_missing_registry_is_na_and_unregistered_documents_are_ignored(tmp_path):
    write(tmp_path, "docs/unregistered.md", "# Not governed\n")
    result = check_docs(tmp_path, mode="enforce")
    assert result["verdict"] == "N/A" and result["rc"] == 0
    assert_common(result)
    fixture(tmp_path)
    baseline(tmp_path)
    write(tmp_path, "docs/unregistered.md", "# Still not governed\n")
    assert check_docs(tmp_path, mode="enforce")["verdict"] == "PASS"


def test_check_docs_for_ids_is_scoped_pure_and_missing_id_fails(tmp_path):
    fixture(tmp_path)
    other = document(id="DOC-other", path="docs/other.md", source_paths=["src/other.py"])
    registry(tmp_path, document(), other)
    write(tmp_path, "docs/other.md", "# Other\n")
    write(tmp_path, "src/other.py", "OTHER = 1\n")
    baseline(tmp_path)
    touch_document(tmp_path, "DOC-other", "reviewer", "file:src/other.py#L1")
    write(tmp_path, "src/other.py", "OTHER = 2\n")
    paths = [tmp_path / rel for rel in ("docs/guide.md", "docs/other.md", "src/app.py", "src/other.py", "product/docs/governance.yaml", "product/docs/governance-events.jsonl")]
    before = {path: path.read_bytes() for path in paths}
    first = check_docs_for_ids(tmp_path, ["DOC-guide"], mode="enforce")
    second = check_docs_for_ids(tmp_path, ["DOC-guide"], mode="enforce")
    assert first == second and first["verdict"] == "PASS"
    assert {path: path.read_bytes() for path in paths} == before
    missing = check_docs_for_ids(tmp_path, ["DOC-missing"], mode="enforce")
    assert missing["verdict"] == "FAIL" and missing["cause"] == "docs_stale"
    assert any("未登记" in item["message"] for item in missing["findings"])


def test_malformed_ledger_fails_closed_and_touch_never_rewrites_it(tmp_path):
    fixture(tmp_path)
    ledger = write(tmp_path, "product/docs/governance-events.jsonl", "{broken\n")
    before = ledger.read_bytes()
    result = check_docs(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    with pytest.raises(DocsGovernanceError):
        touch_document(tmp_path, "DOC-guide", "reviewer", "file:src/app.py#L1")
    assert ledger.read_bytes() == before


def test_layout_error_preserves_shadow_semantics_and_enforce_fails(tmp_path):
    write(tmp_path, "atlas.config.yaml", "version: 1\nlayout:\n  assets_root: ../escape\n")
    shadow = check_docs(tmp_path)
    assert shadow["mode"] == "shadow" and shadow["verdict"] == "FAIL" and shadow["rc"] == 0
    assert_common(shadow)
    enforced = check_docs(tmp_path, mode="enforce")
    assert enforced["verdict"] == "FAIL" and enforced["rc"] == 1
    assert_common(enforced)


def test_custom_assets_root_uses_shared_layout(tmp_path):
    write(tmp_path, "atlas.config.yaml", "version: 1\nlayout:\n  assets_root: assets\n")
    write(tmp_path, "docs/guide.md", "# Guide\n")
    write(tmp_path, "src/app.py", "VALUE = 1\n")
    path = tmp_path / "assets/docs/governance.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"version": 1, "documents": [document()]}), encoding="utf-8")
    assert list_documents(tmp_path) == [document()]
    baseline(tmp_path)
    assert (tmp_path / "assets/docs/governance-events.jsonl").is_file()
    assert check_docs(tmp_path, mode="enforce")["verdict"] == "PASS"
