"""RFC-20261125-01 P2 public CLI, check and finish wiring."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))
from scripts import atlas_check


def test_node_cli_routes_incident_and_docs_with_real_rc(tmp_path):
    for command in ("incident", "docs", "topology"):
        help_result = subprocess.run(["node", str(PKG_ROOT / "bin" / "atlas.js"), "--help"],
                                     capture_output=True, text=True)
        assert help_result.returncode == 0 and command in help_result.stdout
        result = subprocess.run(["node", str(PKG_ROOT / "bin" / "atlas.js"), command,
                                 "--root", str(tmp_path), "--mode", "off", "--json", "check"],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 2, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["verdict"] == "UNVERIFIED" and payload["rc"] == 2


def test_contracts_receipt_and_p5_clis_are_routed(tmp_path):
    for command in ("contracts", "receipt"):
        result = subprocess.run(["node", str(PKG_ROOT / "bin" / "atlas.js"), command,
                                 "--root", str(tmp_path), "--mode", "off", "--json"],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 2, result.stdout + result.stderr
        assert json.loads(result.stdout)["verdict"] == "UNVERIFIED"
    heldout = subprocess.run(["node", str(PKG_ROOT / "bin" / "atlas.js"), "classify",
                              "heldout", "--json"], capture_output=True, text=True, timeout=30)
    assert heldout.returncode == 0 and json.loads(heldout.stdout)["tuning_allowed"] is False
    metrics = subprocess.run(["node", str(PKG_ROOT / "bin" / "atlas.js"), "metrics",
                              "--root", str(tmp_path), "--json"], capture_output=True, text=True, timeout=30)
    assert metrics.returncode == 2 and json.loads(metrics.stdout)["module"] == "metrics"


def test_docs_cli_honors_environment_off(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DOCS_MODE", "off")
    result = subprocess.run(["node", str(PKG_ROOT / "bin" / "atlas.js"), "docs",
                             "--root", str(tmp_path), "--json", "touch", "DOC-guide",
                             "--by", "o", "--evidence", "file:src/app.py"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert json.loads(result.stdout)["verdict"] == "UNVERIFIED"


def test_topology_and_semantic_clis_honor_environment_off(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_TOPOLOGY_MODE", "off")
    topology = subprocess.run(["node", str(PKG_ROOT / "bin" / "atlas.js"), "topology",
                               "--root", str(tmp_path), "--json", "check"],
                              capture_output=True, text=True, timeout=30)
    assert topology.returncode == 2
    payload = json.loads(topology.stdout)
    assert payload["verdict"] == "UNVERIFIED" and payload["mode"] == "off"
    monkeypatch.setenv("ATLAS_SEMANTIC_MODE", "off")
    contracts = subprocess.run(["node", str(PKG_ROOT / "bin" / "atlas.js"), "contracts",
                                "--root", str(tmp_path), "--json"],
                               capture_output=True, text=True, timeout=30)
    assert contracts.returncode == 2
    payload = json.loads(contracts.stdout)
    assert payload["verdict"] == "UNVERIFIED" and payload["mode"] == "off"


def test_governance_causes_preserve_atomic_exit_codes():
    from _support.workflow_causes import exit_code_for
    expected = {
        "migration_unverified": 2, "contract_stale": 1, "contract_unverified": 2,
        "incident_evidence_missing": 1, "incident_not_resolved": 1, "incident_unverified": 2,
        "docs_stale": 1, "docs_owner_missing": 1, "docs_unverified": 2,
        "topology_stale": 1, "topology_unverified": 2, "receipt_stale": 1,
        "receipt_unverified": 2, "calibration_unverified": 2,
    }
    assert {cause: exit_code_for(cause) for cause in expected} == expected


def test_topology_precheck_uses_recursive_glob_and_baseline_deletions(tmp_path):
    from scripts.atlas_workflow import _topology_precheck_needed
    (tmp_path / "compose.yaml").write_text("services:\n  api:\n    image: demo:1\n")
    topology = {"inputs": {"scan_globs": ["**/compose*.yaml"]}, "source_files": ["old/compose.yaml"]}
    assert _topology_precheck_needed(tmp_path, topology, ["compose.yaml"])
    assert _topology_precheck_needed(tmp_path, topology, ["old/compose.yaml"])
    assert _topology_precheck_needed(tmp_path, topology, ["compose.extra.yaml"])
    assert not _topology_precheck_needed(tmp_path, topology, ["README.md"])


def test_topology_verify_uses_staged_index_for_cached_deletion(tmp_path):
    from scripts.atlas_workflow import _check_staged_topology
    from _support.runtime_topology import refresh_topology
    (tmp_path / "compose.yaml").write_text("services:\n  api:\n    image: demo/api:1\n")
    for args in (("init", "-q"), ("config", "user.email", "topology@example.test"),
                 ("config", "user.name", "Topology Test"), ("add", "."), ("commit", "-qm", "base")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    assert refresh_topology(tmp_path, project="shop", environment="dev", cluster="local",
                            release="r1", scan_globs=["compose.yaml"])["verdict"] == "PASS"
    subprocess.run(["git", "rm", "--cached", "-q", "compose.yaml"], cwd=tmp_path, check=True)
    assert (tmp_path / "compose.yaml").is_file()
    result = _check_staged_topology(tmp_path, "enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1, result
    assert any("文件集变化" in item["message"] for item in result["findings"])


def test_finish_topology_refresh_uses_staged_snapshot(tmp_path):
    from _support.workflow_finish import _refresh_staged_topology
    from _support.runtime_topology import refresh_topology
    compose = tmp_path / "compose.yaml"
    compose.write_text("services:\n  api:\n    image: demo/api:1\n")
    for args in (("init", "-q"), ("config", "user.email", "topology@example.test"),
                 ("config", "user.name", "Topology Test"), ("add", "."), ("commit", "-qm", "base")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    options = dict(project="shop", environment="dev", cluster="local", release="r1",
                   scan_globs=["compose.yaml"], mode="enforce", owner="platform", due="2099-12-31")
    assert refresh_topology(tmp_path, **options)["verdict"] == "PASS"
    compose.write_text("services:\n  api:\n    image: '${IMAGE}'\n")
    subprocess.run(["git", "add", "compose.yaml"], cwd=tmp_path, check=True)
    compose.write_text("services:\n  api:\n    image: demo/api:1\n")
    result = _refresh_staged_topology(tmp_path, options)
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2, result
    topology = json.loads((tmp_path / ".adapter-out/topology.json").read_text())
    assert topology["coverage"]["unverified_fields"]


def test_staged_paths_preserve_non_ascii_names(tmp_path):
    from _support.workflow_finish import staged_files
    for args in (("init", "-q"), ("config", "user.email", "topology@example.test"),
                 ("config", "user.name", "Topology Test")):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "配置.yaml").write_text("services: {}\n")
    subprocess.run(["git", "add", "配置.yaml"], cwd=tmp_path, check=True)
    assert staged_files(tmp_path) == ["配置.yaml"]


def test_gate_preconditions_follow_custom_assets_root(tmp_path):
    (tmp_path / "atlas.config.yaml").write_text("version: 1\nlayout:\n  assets_root: governance\n", encoding="utf-8")
    pre = atlas_check._gate_preconditions(tmp_path)
    assert pre["validate_incident"][0] == "governance/incidents"
    assert pre["validate_docs_governance"][0] == "governance/docs/governance.yaml"


def test_atlas_check_preserves_governance_validator_json(tmp_path, monkeypatch):
    validators = tmp_path / ".atlas" / "validators"
    validators.mkdir(parents=True)
    for name in ("validate_migration", "validate_incident", "validate_docs_governance", "validate_runtime_topology", "validate_contracts", "validate_receipt", "validate_calibration"):
        (validators / f"{name}.py").write_text("# fixture\n", encoding="utf-8")
    (tmp_path / ".adapter-out/migration").mkdir(parents=True)
    (tmp_path / ".adapter-out/migration/manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "product/incidents").mkdir(parents=True)
    (tmp_path / "product/docs").mkdir(parents=True)
    (tmp_path / "product/docs/governance.yaml").write_text("version: 1\ndocuments: []\n", encoding="utf-8")
    (tmp_path / ".adapter-out/topology.json").write_text("{}", encoding="utf-8")
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts/manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".atlas/runs").mkdir(parents=True)
    (tmp_path / ".atlas/runs/workflow-receipt.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".atlas/runs/governance-calibration.json").write_text("{}", encoding="utf-8")
    payloads = {
        "validate_migration": {"verdict": "UNVERIFIED", "cause": "migration_unverified", "rc": 2, "findings": []},
        "validate_incident": {"verdict": "FAIL", "cause": "incident_evidence_missing", "rc": 1, "findings": []},
        "validate_docs_governance": {"verdict": "FAIL", "cause": "docs_stale", "rc": 0, "findings": []},
        "validate_runtime_topology": {"verdict": "UNVERIFIED", "cause": "topology_unverified", "rc": 2, "findings": []},
        "validate_contracts": {"verdict": "FAIL", "cause": "contract_stale", "rc": 1, "findings": []},
        "validate_receipt": {"verdict": "UNVERIFIED", "cause": "receipt_unverified", "rc": 2, "findings": []},
        "validate_calibration": {"verdict": "UNVERIFIED", "cause": "calibration_unverified", "rc": 2, "findings": []},
    }
    monkeypatch.setattr(atlas_check, "run", lambda cmd, cwd, timeout=1800: (
        payloads[Path(cmd[1]).stem]["rc"], json.dumps(payloads[Path(cmd[1]).stem])))
    rows = atlas_check.Row()
    atlas_check.check_validators(tmp_path, rows, sys.executable)
    for name, expected in payloads.items():
        row = next(item for item in rows.rows if item["name"] == name)
        assert (row["verdict"], row["cause"], row["rc"]) == (expected["verdict"], expected["cause"], expected["rc"])
        assert row["status"] == ("WARN" if expected["rc"] == 0 else "FAIL")


def test_finish_incident_consumer_blocks_bad_resolution_but_not_association(tmp_path):
    from _support.incident import validate_task_incidents
    assert validate_task_incidents(tmp_path, {"incident_ids": ["INC-20261125-001"]}) == []
    blocked = validate_task_incidents(tmp_path, {"resolves_incidents": ["INC-20261125-001"]})
    assert blocked[0]["rc"] == 1 and blocked[0]["mode"] == "enforce"
