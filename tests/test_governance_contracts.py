"""RFC-20261125-01 P0：schema、canonical digest 与冻结语料边界。"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))
from _support.governance_corpus import expand_heldout
from _support.governance_schema import canonical_bytes, canonical_digest, load_schema, validate, validate_receipt, validate_topology

FIXTURES = PKG_ROOT / "tests" / "fixtures" / "governance"
HELDOUT_SPEC = PKG_ROOT / "shared" / "schemas" / "heldout-spec.json"
HELDOUT_SPEC_SHA256 = "77ac0da783c9eeb6948053cbc79f15600bfe4ac14c792843271ef57ad93d6dd5"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_canonical_digest_is_stable_across_key_and_array_order() -> None:
    left = {"z": [{"b": 2, "a": 1}, {"a": 0}], "a": "中文"}
    right = {"a": "中文", "z": [{"a": 0}, {"a": 1, "b": 2}]}
    assert canonical_bytes(left) == canonical_bytes(right)
    assert canonical_digest(left) == hashlib.sha256(canonical_bytes(left)).hexdigest()


def test_canonical_rejects_non_string_keys() -> None:
    import pytest
    with pytest.raises(TypeError):
        canonical_bytes({1: "a", "1": "b"})


def test_common_schema_binds_cause_verdict_rc_and_off() -> None:
    schema = load_schema("governance-common")
    good = {"schema_version": 1, "module": "semantic", "mode": "enforce", "verdict": "UNVERIFIED", "cause": "contract_unverified", "rc": 2, "findings": []}
    assert validate(good, schema) == []
    assert validate({**good, "rc": 0}, schema)
    assert validate({**good, "cause": "contract_stale"}, schema)
    assert validate({**good, "mode": "off", "cause": None, "verdict": "PASS", "rc": 0}, schema)
    assert validate({**good, "mode": "off", "verdict": "UNVERIFIED", "rc": 2}, schema)
    assert validate({**good, "verdict": "FAIL", "cause": None, "rc": 1}, schema)
    assert validate({**good, "verdict": "FAIL", "cause": "docs_stale", "rc": 3}, schema)
    shadow = {**good, "mode": "shadow", "rc": 0}
    assert validate(shadow, schema) == []


def test_na_requires_owner_due_and_reason() -> None:
    schema = load_schema("governance-common")
    value = {"schema_version": 1, "module": "docs", "mode": "enforce", "verdict": "N/A", "cause": None, "rc": 0, "findings": [{"cause": "not_applicable", "message": "reason", "owner": "o", "due": "2026-12-01"}]}
    assert validate(value, schema) == []
    assert validate({**value, "findings": []}, schema)
    assert validate({**value, "findings": [{"cause": "not_applicable", "message": "reason"}]}, schema)


def test_semantic_stores_have_independent_schemas_and_digests() -> None:
    source = {"path": "src/api.py", "line": 3, "sha256": "0" * 64}
    expected = {"schema_version": 1, "clauses": [{"clause_id": "R-07", "contracts": [{"kind": "field", "name": "detailUrl", "type": "string", "required": True, "source": source}]}]}
    revision = {"commit": "1234567", "digest": "0" * 64}
    observed = {"schema_version": 1, "base": revision, "head": revision, "adapter_version": "1", "facts": [{"id": "f1", "kind": "field", "value": {"name": "detailUrl", "type": "string", "required": True}, "adapter_version": "1", "source": source}], "sources": [source], "changed_paths": [], "coverage": {"parsed": 1, "unverified_fields": [], "parse_errors": []}}
    graph = {"schema_version": 1, "expected_digest": canonical_digest(expected), "observed_digest": canonical_digest(observed), "edges": [{"id": "e1", "base": {"commit": "1234567"}, "head": {"commit": "1234567"}, "from": "R-07", "to": "f1", "kind": "clause_contract_observed", "source": source, "sha256": "0" * 64, "adapter_version": "1"}]}
    assert validate(expected, load_schema("semantic-expected")) == []
    assert validate(observed, load_schema("semantic-observed")) == []
    assert validate(graph, load_schema("semantic-graph")) == []
    assert canonical_digest(expected) != canonical_digest(observed) != canonical_digest(graph)
    assert validate({**observed, "facts": [{"id": "f1"}]}, load_schema("semantic-observed"))
    assert validate({**graph, "edges": [{"id": "e1"}]}, load_schema("semantic-graph"))


def test_topology_schema_enforces_identity_and_dynamic_fields() -> None:
    schema = load_schema("runtime-topology")
    value = {"category": "topology", "items": [], "source_files": ["compose.yaml"], "adapter_version": "1", "coverage": {"parsed": 1, "unverified_fields": [{"id": "p:e:c:r:api", "fields": ["image"], "owner": "o", "due": "2026-12-01"}], "parse_errors": []}, "inputs": {"project": "p", "environment": "e", "cluster": "c", "release": "r", "scan_globs": ["compose*.yaml"]}}
    assert validate(value, schema) == []
    assert validate({**value, "coverage": {**value["coverage"], "unverified_fields": [{"id": "p:e:c:r:api", "fields": ["image"]}]}}, schema)
    broken = json.loads(json.dumps(value))
    broken["coverage"]["unverified_fields"][0].pop("fields")
    assert validate(broken, schema)
    broken = json.loads(json.dumps(value))
    broken["coverage"]["unverified_fields"][0]["fields"] = []
    assert validate(broken, schema)
    node = {"node": True, "id": "p:e:c:r:default:api", "kind": "service", "name": "api", "namespace": "default", "app": None, "image": "demo/api:1", "ports": [8080], "source_file": "compose.yaml", "line": 2, "sha256": "0" * 64}
    assert validate_topology({**value, "items": [node]}) == []
    assert validate_topology({**value, "items": [{**node, "id": "api"}]})
    assert validate_topology({**value, "items": [{**node, "id": "p:e:c:r::api", "namespace": None}]})
    none_node = {**node, "id": "p:e:c:r:none:api", "namespace": None}
    assert validate_topology({**value, "items": [none_node]}) == []
    edge = {"edge": True, "id": "e1", "kind": "depends_on", "from": node["id"], "to": "missing", "relation": "depends_on", "source_file": "compose.yaml", "line": 3, "sha256": "0" * 64}
    assert validate_topology({**value, "items": [node, edge]})
    assert validate({**value, "items": [{k: v for k, v in node.items() if k != "source_file"}]}, schema)


def test_incident_closed_requires_signed_verification_and_contained_is_not_resolved() -> None:
    schema = load_schema("incident")
    base = {"schema_version": 1, "id": "INC-20261125-001", "title": "x", "status": "resolved", "severity": "SEV2", "owner": "o", "started_at": "2026-11-25T00:00:00Z", "detected_at": "2026-11-25T00:00:00Z", "resolved_at": "2026-11-25T01:00:00Z", "environment": "test", "services": ["api"], "impact": "x", "evidence": [{"id": "ev1", "type": "log", "path": "evidence/log.txt", "sha256": "0" * 64}], "hypotheses": [], "root_cause": {"summary": "x", "evidence_refs": ["ev1"]}, "contributing_factors": [], "resolution": {"summary": "x", "verification_refs": ["ev1"], "verified_by": "o", "verified_at": "2026-11-25T01:00:00Z", "before": "3/5", "after": "5/5"}, "actions": [], "links": {"request_id": None, "task_ids": [], "review_refs": [], "spec_refs": []}, "previous_status": None}
    assert validate(base, schema) == []
    assert validate({**base, "evidence": []}, schema)
    assert validate({**base, "resolution": None}, schema)
    contained = {**base, "status": "contained", "resolved_at": None, "previous_status": "resolved"}
    assert validate(contained, schema) == []
    assert validate({**contained, "resolved_at": base["resolved_at"]}, schema)
    assert validate({**contained, "root_cause": None}, schema)
    event_schema = load_schema("incident-timeline-event")
    event = {"schema_version": 1, "id": "t1", "ts": "2026-11-25T01:00:00Z", "kind": "rollback", "actor": "o", "summary": "containment failed", "evidence_refs": [], "from": "resolved", "to": "contained"}
    assert validate(event, event_schema) == []
    assert validate({**event, "from": "detected"}, event_schema)


def test_receipt_requires_three_semantic_digests_enforce_modes_and_result_mapping() -> None:
    schema = load_schema("workflow-receipt")
    value = {"schema_version": 1, "unit": "01", "task_id": "01", "requirement_id": None, "clause_ids": [], "incident_ids": [], "resolves_incidents": [], "doc_ids": [], "topology_refs": [], "topology_required": False, "migration_required": False, "classification_required": False, "base": "0" * 40, "diff_range": "0", "staged_patch": {"path": ".atlas/runs/workflow-receipt/staged.patch", "sha256": "0" * 64}, "tree_hash": "0" * 40, "semantic_expected_digest": "0" * 64, "semantic_observed_digest": "0" * 64, "semantic_graph_digest": "0" * 64, "validators": [{"module": "semantic", "verdict": "PASS", "rc": 0, "digest": "0" * 64}], "validator_evidence": {}, "validator_code_sha256": {}, "review": {"path": "review.json", "artifact_path": ".atlas/runs/workflow-receipt/review.json", "sha256": "0" * 64, "status": "PASS", "scope_sha256": "0" * 64}, "origin": {"schema_version": 1, "unit": "01", "review_path": "review.json", "review_sha256": "0" * 64, "review_scope_sha256": "0" * 64, "base": "0" * 40, "generated_at": "2026-11-25T00:00:00Z"}, "in_scope_modules": ["semantic"], "module_modes": {"semantic": "enforce"}, "generated_at": "2026-11-25T00:00:00Z", "workflow_version": "1"}
    assert validate_receipt(value) == []
    assert validate_receipt({**value, "in_scope_modules": ["semantic", "docs"]})
    assert validate_receipt({**value, "doc_ids": ["DOC-guide"]})
    assert validate_receipt({**value, "resolves_incidents": ["INC-20261125-001"]})
    assert validate_receipt({**value, "topology_required": True})
    assert validate_receipt({**value, "topology_refs": ["topology.json"]})
    assert validate_receipt({**value, "validators": [{"module": "semantic", "verdict": "N/A", "rc": 0, "digest": "0" * 64, "reason": "x", "owner": "o", "due": "2026-12-01"}]}) == []
    assert validate_receipt({**value, "validators": [{"module": "semantic", "verdict": "N/A", "rc": 0, "digest": "0" * 64}]})
    assert validate_receipt({**value, "module_modes": {}})
    assert validate({k: v for k, v in value.items() if k != "tree_hash"}, schema)
    assert validate({**value, "module_modes": {}}, schema)
    assert validate({**value, "module_modes": {"semantic": "shadow"}}, schema)
    failed = {"module": "semantic", "verdict": "FAIL", "rc": 1, "digest": "0" * 64}
    assert validate({**value, "validators": [failed]}, schema) == []
    assert validate_receipt({**value, "validators": [failed]})
    assert validate({**value, "validators": [{"module": "semantic", "verdict": "UNVERIFIED", "rc": 2, "digest": "0" * 64}]}, schema) == []
    assert validate({**value, "validators": []}, schema)
    assert validate({**value, "in_scope_modules": []}, schema)


def test_docs_registry_rejects_escape_and_event_requires_evidence() -> None:
    registry = load_schema("docs-governance")
    document = {"id": "DOC-guide", "path": "docs/guide.md", "owner": "o", "kind": "guide", "status": "active", "reviewed_at": "2026-11-25", "review_due": "2026-12-25", "source_paths": ["src/app.py"], "links": []}
    value = {"version": 1, "documents": [document]}
    assert validate(value, registry) == []
    assert validate({**value, "documents": [{**document, "path": "../../etc/passwd"}]}, registry)
    assert validate({**value, "documents": [{**document, "source_paths": ["../../etc/passwd"]}]}, registry)
    assert validate({**value, "documents": [{**document, "path": "C:\\Windows\\x"}]}, registry)
    assert validate({**value, "documents": [{**document, "source_paths": ["..\\..\\secret"]}]}, registry)
    event_schema = load_schema("docs-governance-event")
    digests = {"document": "0" * 64, "sources": {"src/app.py": "0" * 64}}
    event = {"schema_version": 1, "event_id": "e1", "ts": "2026-11-25T00:00:00Z", "actor": "o", "doc_id": "DOC-guide", "kind": "touch", "evidence": "review-1", "old": digests, "new": digests}
    assert validate(event, event_schema) == []
    assert validate({**event, "evidence": ""}, event_schema)
    assert validate({**event, "ts": "2026-11-25"}, event_schema)


def test_schema_loader_rejects_duplicate_keys(tmp_path, monkeypatch) -> None:
    import pytest
    import _support.governance_schema as kernel
    (tmp_path / "duplicate.json").write_text('{"type":"object","type":"string"}', encoding="utf-8")
    monkeypatch.setattr(kernel, "SCHEMA_DIR", tmp_path)
    with pytest.raises(ValueError, match="重复键"):
        kernel.load_schema("duplicate")


def test_frozen_corpus_hashes_are_external_constants() -> None:
    assert _sha(HELDOUT_SPEC) == HELDOUT_SPEC_SHA256
    manifest = json.loads((FIXTURES / "corpus-manifest.json").read_text(encoding="utf-8"))
    assert set(manifest) == {"corpus.json"}
    assert manifest["corpus.json"] == _sha(FIXTURES / "corpus.json")


def test_source_inventory_is_internally_consistent() -> None:
    inventory = json.loads((PKG_ROOT / "proposals" / "RFC-20261125-01-P0-source-inventory.json").read_text(encoding="utf-8"))
    payload = {k: v for k, v in inventory.items() if k != "canonical_digest"}
    assert canonical_digest(payload) == inventory["canonical_digest"]
    assert inventory["base"] == "1477ca1c5130fe7e0cb89f83e011186d62925b31"
    assert all((PKG_ROOT / row["path"]).exists() for row in inventory["files"])


def test_heldout_meets_minimum_samples_and_has_unique_fingerprints() -> None:
    samples = expand_heldout()
    for module in ("semantic", "docs", "incident", "topology"):
        positive = sum(item["expected"] in ("PASS", "WARN") for item in samples[module])
        negative = sum(item["expected"] in ("FAIL", "STALE", "UNVERIFIED") for item in samples[module])
        assert positive >= 20 and negative >= 20, (module, positive, negative)
    assert sum(item["expected"] == "PASS" for item in samples["receipt"]) >= 4
    assert sum(item["expected"] == "FAIL" for item in samples["receipt"]) >= 4
    for label in ("initial", "change", "bug"):
        assert sum(item["expected"] == label for item in samples["classification"]) >= 50
    fingerprints = [item["fingerprint"] for items in samples.values() for item in items]
    assert len(fingerprints) == len(set(fingerprints))
    assert len({json.dumps(item["input"], sort_keys=True) for item in samples["receipt"] if item["expected"] == "PASS"}) >= 4
    assert all(item["input"].get("source_text") for item in samples["topology"])
    assert all(len(item["input"]["source_digest"]) == 64 for item in samples["topology"])
    assert all(item["input"]["dynamic_fields"] == ["url"] for item in samples["topology"] if item["input"]["format"] == "kong" and item["expected"] == "UNVERIFIED")
    assert all(item["expected"] == "abstain" for item in samples["classification"] if "abstain" in item["id"])
