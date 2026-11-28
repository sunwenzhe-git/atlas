"""M248: RFC-20261125-01 P3 Runtime Topology counterexamples.

First paragraph declaration: removing source-file hash comparison, dynamic-field
tracking, or dangling-edge validation must turn this suite red. The real
four-stage mutation_proof is .atlas/runs/mutation-proof/M248.txt.
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

from _support.governance_schema import load_schema, validate, validate_topology  # noqa: E402
from _support.runtime_topology import (  # noqa: E402
    TopologyError,
    check_topology,
    refresh_topology,
    rollback_topology,
)
from scripts.atlas_topology import main as topology_main  # noqa: E402
from validators.validate_runtime_topology import main as validator_main  # noqa: E402

COMPOSE = """name: shop
services:
  api:
    image: registry.example/api:1
    ports:
      - "8080:80"
    depends_on:
      db:
        condition: service_healthy
    networks:
      - backend
    environment:
      API_TOKEN: super-secret-compose
  db:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: super-secret-db
    networks:
      - backend
networks:
  backend: {}
"""

HELM = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  labels:
    app: api
spec:
  template:
    metadata:
      labels:
        app: api
    spec:
      containers:
        - name: api
          image: registry.example/api:2
          ports:
            - containerPort: 9090
          volumeMounts:
            - name: config
              mountPath: /etc/config
      volumes:
        - name: config
          secret:
            secretName: api-secret
---
apiVersion: v1
kind: Service
metadata:
  name: api
spec:
  selector:
    app: api
  ports:
    - port: 80
      targetPort: 9090
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: db
spec:
  serviceName: db
  template:
    spec:
      containers:
        - name: db
          image: postgres:16
          ports:
            - containerPort: 5432
---
apiVersion: v1
kind: Service
metadata:
  name: db
spec:
  selector:
    app: db
  ports:
    - port: 5432
"""

KONG = """_format_version: "3.0"
services:
  - name: api
    url: http://api-upstream:8000/base
    routes:
      - name: public
        paths:
          - /v1
    plugins:
      - name: rate-limiting
        config:
          minute: 10
          secret: super-secret-kong
upstreams:
  - name: api-upstream
    targets:
      - target: 10.0.0.8:8000
"""


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def refresh(root: Path, glob: str, **changes):
    options = dict(project="shop", environment="dev", cluster="local", release="r1",
                   scan_globs=[glob], owner="platform", due="2099-12-31", mode="shadow")
    options.update(changes)
    return refresh_topology(root, **options)


def artifact(root: Path) -> dict:
    return json.loads((root / ".adapter-out/topology.json").read_text(encoding="utf-8"))


def manifest(root: Path) -> dict:
    return json.loads((root / ".adapter-out/topology/manifest.json").read_text(encoding="utf-8"))


def nodes(root: Path) -> dict[str, dict]:
    return {item["name"]: item for item in artifact(root)["items"] if item.get("node") is True}


def edges(root: Path) -> list[dict]:
    return [item for item in artifact(root)["items"] if item.get("edge") is True]


def snapshot(root: Path) -> dict[str, bytes]:
    base = root / ".adapter-out"
    return {path.relative_to(base).as_posix(): path.read_bytes()
            for path in sorted(base.rglob("*")) if path.is_file()}


def assert_topology(root: Path) -> None:
    value = artifact(root)
    assert validate_topology(value) == []
    assert validate(value, load_schema("runtime-topology")) == []
    assert value["inputs"]["project"] == "shop"
    assert value["source_files"] == sorted(set(value["source_files"]))
    for item in value["items"]:
        source = root / item["source_file"]
        assert item["line"] >= 1
        assert item["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_compose_golden_nodes_dependencies_networks_and_secret_redaction(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    result = refresh(tmp_path, "compose.yaml")
    assert result["verdict"] == "PASS" and result["rc"] == 0
    assert_topology(tmp_path)
    value = artifact(tmp_path)
    assert value["coverage"]["parsed"] == 1
    assert nodes(tmp_path)["api"]["id"] == "shop:dev:local:r1:none:api"
    assert nodes(tmp_path)["api"]["namespace"] is None
    assert nodes(tmp_path)["api"]["ports"] == ["8080:80"]
    assert nodes(tmp_path)["db"]["image"] == "postgres:16"
    relations = {(edge["kind"], edge["relation"]) for edge in edges(tmp_path)}
    assert ("depends_on", "depends_on") in relations
    assert ("network", "network:backend") in relations
    assert "super-secret" not in json.dumps(value)


def test_helm_golden_workloads_containers_services_and_volume_relations(tmp_path):
    write(tmp_path, "helm/templates/workloads.yaml", HELM)
    result = refresh(tmp_path, "helm/templates/*.yaml")
    assert result["verdict"] == "PASS" and result["rc"] == 0
    assert_topology(tmp_path)
    value = artifact(tmp_path)
    assert value["coverage"]["parsed"] == 4
    by_id = {item["id"]: item for item in value["items"] if item.get("node") is True}
    assert by_id["shop:dev:local:r1:none:api"]["image"] == "registry.example/api:2"
    assert by_id["shop:dev:local:r1:none:api"]["ports"] == [9090]
    assert by_id["shop:dev:local:r1:none:db"]["image"] == "postgres:16"
    assert any(edge["kind"] == "routes_to" and edge["port"] == 80 for edge in edges(tmp_path))
    assert any(edge["relation"].startswith("volume:") for edge in edges(tmp_path))
    assert "api-secret" not in json.dumps(value)


def test_kong_golden_service_route_upstream_and_plugin(tmp_path):
    write(tmp_path, "kong.yaml", KONG)
    result = refresh(tmp_path, "kong.yaml")
    assert result["verdict"] == "PASS" and result["rc"] == 0
    assert_topology(tmp_path)
    value = artifact(tmp_path)
    assert value["coverage"]["parsed"] == 1
    kinds = {item["kind"] for item in value["items"] if item.get("node") is True}
    assert {"kong_service", "kong_route", "kong_plugin"} <= kinds
    relations = {(edge["kind"], edge["relation"]) for edge in edges(tmp_path)}
    assert ("routes_to", "route") in relations
    assert ("upstream", "upstream") in relations
    assert ("plugin", "plugin:rate-limiting") in relations
    assert "super-secret-kong" not in json.dumps(value)


def test_kong_url_without_upstream_keeps_explicit_target_node(tmp_path):
    text = KONG.split("upstreams:\n", 1)[0]
    write(tmp_path, "kong.yaml", text)
    result = refresh(tmp_path, "kong.yaml", mode="enforce")
    assert result["verdict"] == "PASS", result
    value = artifact(tmp_path)
    assert value["coverage"]["parse_errors"] == []
    assert any(edge["kind"] == "upstream" for edge in value["items"] if edge.get("edge"))
    targets = {edge["to"] for edge in value["items"] if edge.get("edge") and edge["kind"] == "upstream"}
    assert any(item.get("node") and item["id"] in targets for item in value["items"])


def test_helm_control_flow_is_explicitly_unverified(tmp_path):
    text = HELM.replace("          image: registry.example/api:2",
                        "          {{- if .Values.useLegacy }}\n          image: demo/legacy\n          {{- else }}\n          image: registry.example/api:2\n          {{- end }}")
    write(tmp_path, "helm/templates/workloads.yaml", text)
    result = refresh(tmp_path, "helm/templates/*.yaml", mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2, result
    assert any("控制流" in item["message"] for item in result["findings"])


def test_frozen_topology_corpus_runs_through_real_adapter(tmp_path):
    corpus = json.loads((PKG_ROOT / "tests/fixtures/governance/corpus.json").read_text())
    for kind, text in corpus["topology"].items():
        root = tmp_path / kind
        rel = "compose.yaml" if kind in ("compose", "dynamic") else "kong.yaml" if kind == "kong" else "helm/templates/workloads.yaml"
        write(root, rel, text)
        result = refresh(root, rel if kind != "dynamic" else "compose.yaml", mode="enforce")
        expected = "UNVERIFIED" if kind == "dynamic" else "PASS"
        assert result["verdict"] == expected, (kind, result)


@pytest.mark.parametrize("rel,old,new", [
    ("compose.yaml", '"8080:80"', '"8081:80"'),
    ("kong.yaml", "10.0.0.8:8000", "10.0.0.9:8000"),
])
def test_port_or_upstream_change_without_refresh_is_fail_rc1_in_enforce(tmp_path, rel, old, new):
    write(tmp_path, rel, COMPOSE if rel == "compose.yaml" else KONG)
    assert refresh(tmp_path, rel)["verdict"] == "PASS"
    path = tmp_path / rel
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    result = check_topology(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert result["cause"] == "topology_stale"
    assert any("hash" in finding["message"].lower() or "摘要" in finding["message"] for finding in result["findings"])


def test_comment_only_hash_change_is_stale(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    refresh(tmp_path, "compose.yaml")
    write(tmp_path, "compose.yaml", COMPOSE + "# changed bytes\n")
    result = check_topology(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1 and result["cause"] == "topology_stale"


@pytest.mark.parametrize("change", ["add", "delete"])
def test_scan_glob_file_set_add_or_delete_is_stale(tmp_path, change):
    write(tmp_path, "deploy/compose.yaml", COMPOSE)
    refresh(tmp_path, "deploy/*.yaml")
    if change == "add":
        write(tmp_path, "deploy/compose.extra.yaml", COMPOSE.replace("name: shop", "name: other"))
    else:
        (tmp_path / "deploy/compose.yaml").unlink()
    result = check_topology(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert result["cause"] == "topology_stale"
    assert any("文件集" in finding["message"] for finding in result["findings"])


def test_dynamic_fields_are_field_level_unverified_with_owner_due_and_static_facts(tmp_path):
    text = COMPOSE.replace("registry.example/api:1", "{{ .Values.image }}")
    text = text.replace('"8080:80"', '"{{ .Values.port }}:80"')
    write(tmp_path, "compose.yaml", text)
    result = refresh(tmp_path, "compose.yaml", mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert result["cause"] == "topology_unverified"
    value = artifact(tmp_path)
    assert validate_topology(value) == []
    assert nodes(tmp_path)["api"]["image"] is None and nodes(tmp_path)["api"]["ports"] == []
    assert nodes(tmp_path)["db"]["image"] == "postgres:16"
    assert edges(tmp_path)
    unverified = value["coverage"]["unverified_fields"]
    api = next(item for item in unverified if item["id"].endswith(":api"))
    assert set(api["fields"]) == {"image", "ports"}
    assert api["owner"] == "platform" and api["due"] == "2099-12-31"
    assert "{{ .Values.image }}" not in json.dumps(value)


def test_topology_io_error_is_unverified_rc2(tmp_path, monkeypatch):
    import _support.runtime_topology as topology
    write(tmp_path, "compose.yaml", COMPOSE)
    refresh(tmp_path, "compose.yaml")

    def unavailable(_root):
        raise OSError("injected I/O")

    monkeypatch.setattr(topology, "_load_pointer", unavailable)
    result = topology.check_topology(tmp_path, mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert result["cause"] == "topology_unverified"


def test_dynamic_exemption_requires_explicit_owner_and_due(tmp_path):
    text = COMPOSE.replace("registry.example/api:1", "{{ .Values.image }}")
    write(tmp_path, "compose.yaml", text)
    for owner, due in ((None, None), ("platform", None), (None, "2099-12-31")):
        result = refresh(tmp_path, "compose.yaml", mode="enforce", owner=owner, due=due)
        assert result["verdict"] == "UNVERIFIED" and result["cause"] == "topology_unverified"
        assert not (tmp_path / ".adapter-out/topology.json").exists()


def test_dynamic_node_name_is_not_guessed(tmp_path):
    text = COMPOSE.replace("  api:\n    image:", "  {{ .Values.name }}:\n    image:", 1)
    text = text.replace("  db:\n    image:", "  db:\n    depends_on:\n      - {{ .Values.name }}\n    image:", 1)
    write(tmp_path, "compose.yaml", text)
    result = refresh(tmp_path, "compose.yaml", mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert "api" not in nodes(tmp_path)
    assert "db" in nodes(tmp_path)
    assert artifact(tmp_path)["coverage"]["parse_errors"] == []
    assert artifact(tmp_path)["coverage"]["unverified_fields"]
    assert all(item.get("source_file") == "compose.yaml"
               for item in artifact(tmp_path)["coverage"]["unverified_fields"])


def test_secret_values_never_enter_topology_or_rendered_generation(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    write(tmp_path, "kong.yaml", KONG)
    refresh(tmp_path, "*.yaml")
    for path in (tmp_path / ".adapter-out").rglob("*"):
        if path.is_file():
            assert b"super-secret" not in path.read_bytes()


def test_symlink_source_is_unverified_and_does_not_replace_last_known_good(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    refresh(tmp_path, "*.yaml")
    before = snapshot(tmp_path)
    write(tmp_path, "real.yaml", COMPOSE.replace("name: shop", "name: other"))
    try:
        (tmp_path / "compose.link.yaml").symlink_to("real.yaml")
    except OSError as exc:
        if sys.platform == "win32" and getattr(exc, "winerror", None) == 1314:
            pytest.skip("当前 Windows 用户没有创建符号链接的特权")
        raise
    result = refresh(tmp_path, "*.yaml", mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert any("符号链接" in finding["message"] for finding in result["findings"])
    assert snapshot(tmp_path) == before


def test_malformed_yaml_is_unverified_rc2_and_preserves_pointer(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    refresh(tmp_path, "compose.yaml")
    before = manifest(tmp_path)
    write(tmp_path, "compose.yaml", "services:\n  api:\n    image: [broken\n")
    result = refresh(tmp_path, "compose.yaml", mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert result["cause"] == "topology_unverified"
    assert manifest(tmp_path) == before
    assert check_topology(tmp_path)["cause"] == "topology_stale"


def test_invalid_schema_fails_rc1(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    refresh(tmp_path, "compose.yaml")
    value = artifact(tmp_path)
    value["unexpected"] = True
    (tmp_path / ".adapter-out/topology.json").write_text(json.dumps(value), encoding="utf-8")
    result = check_topology(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert result["cause"] == "topology_stale"
    assert any("schema" in finding["message"].lower() for finding in result["findings"])


def test_dangling_edge_fails_rc1(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    refresh(tmp_path, "compose.yaml")
    value = artifact(tmp_path)
    edge = next(item for item in value["items"] if item.get("edge") is True)
    edge["to"] = "shop:dev:local:r1:none:missing"
    (tmp_path / ".adapter-out/topology.json").write_text(json.dumps(value), encoding="utf-8")
    result = check_topology(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert any("悬空边" in finding["message"] for finding in result["findings"])


def test_duplicate_service_identity_is_unverified_not_false_fail(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    write(tmp_path, "compose.override.yaml", COMPOSE.replace("registry.example/api:1", "registry.example/api:2"))
    result = refresh(tmp_path, "compose*.yaml", mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert (tmp_path / ".adapter-out/topology.json").is_file()
    assert any(item["fields"] == ["identity"] for item in artifact(tmp_path)["coverage"]["unverified_fields"])


def test_unknown_deployment_file_is_unverified(tmp_path):
    write(tmp_path, "templates/ingress.yaml", "apiVersion: networking.k8s.io/v1\nkind: Ingress\n")
    result = refresh(tmp_path, "templates/*.yaml", mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2


def test_values_yaml_is_not_misidentified_as_compose(tmp_path):
    write(tmp_path, "chart/values.yaml", "services:\n  frontend:\n    image: node:20\n")
    result = refresh(tmp_path, "chart/values.yaml", mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert not (tmp_path / ".adapter-out/topology.json").exists()


def test_compose_long_depends_on_is_supported(tmp_path):
    text = COMPOSE.replace("    depends_on:\n      - db\n", "    depends_on:\n      - service: db\n        condition: service_started\n")
    write(tmp_path, "compose.yaml", text)
    assert refresh(tmp_path, "compose.yaml", mode="enforce")["verdict"] == "PASS"


def test_helm_dynamic_service_spec_is_unverified_not_crash(tmp_path):
    text = HELM.split("\n---\n")[1].replace("spec:\n", "spec: {{ .Values.spec }}\n", 1)
    write(tmp_path, "helm/service.yaml", text)
    result = refresh(tmp_path, "helm/*.yaml", mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2


def test_kong_route_plugin_links_to_route(tmp_path):
    text = KONG.replace("      - name: rate-limiting\n", "      - name: rate-limiting\n        route: public\n")
    write(tmp_path, "kong.yaml", text)
    refresh(tmp_path, "kong.yaml", mode="enforce")
    assert any(item.get("edge") and item.get("kind") == "plugin"
               and item.get("to", "").startswith("shop:dev:local:r1:none:api/")
               for item in artifact(tmp_path)["items"])


def test_edge_ids_are_stable_across_processes(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    command = [sys.executable, str(PKG_ROOT / "scripts/atlas_topology.py"), "--root", str(tmp_path),
               "--mode", "enforce", "refresh", "--project", "shop", "--environment", "dev",
               "--cluster", "local", "--release", "r1", "--scan-glob", "compose.yaml", "--json"]
    subprocess.run(command, check=True, capture_output=True, text=True)
    before = (tmp_path / ".adapter-out/topology/manifest.json").read_bytes()
    subprocess.run(command, check=True, capture_output=True, text=True)
    assert (tmp_path / ".adapter-out/topology/manifest.json").read_bytes() == before


def test_empty_scan_is_unverified_not_pass(tmp_path):
    result = refresh(tmp_path, "missing/*.yaml", mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2


def test_helm_service_and_workload_link_across_files(tmp_path):
    documents = HELM.split("\n---\n")
    write(tmp_path, "helm/deployment.yaml", documents[0])
    write(tmp_path, "helm/service.yaml", documents[1])
    refresh(tmp_path, "helm/*.yaml", mode="enforce")
    assert any(item.get("edge") and item.get("kind") == "routes_to" for item in artifact(tmp_path)["items"])


def test_kong_global_plugin_is_static_node(tmp_path):
    text = KONG.replace("upstreams:\n", "plugins:\n  - name: prometheus\n    config:\n      secret: hidden\nupstreams:\n")
    write(tmp_path, "kong.yaml", text)
    refresh(tmp_path, "kong.yaml", mode="enforce")
    assert any(item.get("node") and item.get("name") == "global/prometheus" for item in artifact(tmp_path)["items"])
    assert "hidden" not in json.dumps(artifact(tmp_path))


def test_malformed_helm_template_is_unverified_not_crash(tmp_path):
    write(tmp_path, "helm/templates/x.yaml", HELM.replace("  template:\n", "  template: {{ .Values.template }}\n", 1))
    result = refresh(tmp_path, "helm/templates/*.yaml", mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2


def test_refresh_is_byte_idempotent_and_reuses_generation(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    first = refresh(tmp_path, "compose.yaml")
    before = snapshot(tmp_path)
    generations = list((tmp_path / ".adapter-out/topology/generations").iterdir())
    second = refresh(tmp_path, "compose.yaml")
    assert first == second
    assert snapshot(tmp_path) == before
    assert list((tmp_path / ".adapter-out/topology/generations").iterdir()) == generations


def test_rollback_only_switches_pointer_and_preserves_generations(tmp_path):
    path = write(tmp_path, "compose.yaml", COMPOSE)
    first = refresh(tmp_path, "compose.yaml")
    old_bytes = snapshot(tmp_path)
    write(tmp_path, "compose.yaml", COMPOSE.replace("registry.example/api:1", "registry.example/api:2"))
    second = refresh(tmp_path, "compose.yaml")
    assert first["generation"] != second["generation"]
    before_rollback = snapshot(tmp_path)
    old_generation = tmp_path / f".adapter-out/topology/generations/{first['generation']}"
    old_generation_bytes = {p.name: p.read_bytes() for p in old_generation.iterdir()}
    restored = rollback_topology(tmp_path, mode="shadow")
    assert restored["generation"] == first["generation"]
    assert manifest(tmp_path)["generation"] == first["generation"]
    assert artifact(tmp_path) == json.loads(old_bytes["topology.json"])
    assert {p.name: p.read_bytes() for p in old_generation.iterdir()} == old_generation_bytes
    assert all(path in before_rollback for path in snapshot(tmp_path))
    assert check_topology(tmp_path)["cause"] == "topology_stale"


def test_pointer_failure_keeps_last_known_good_and_fixed_artifact(tmp_path, monkeypatch):
    write(tmp_path, "compose.yaml", COMPOSE)
    refresh(tmp_path, "compose.yaml")
    before = snapshot(tmp_path)
    write(tmp_path, "compose.yaml", COMPOSE.replace("postgres:16", "postgres:17"))
    import _support.runtime_topology as support
    original = support.atomic_write_json

    def fail_pointer(path, value):
        if Path(path).name == "manifest.json":
            raise OSError("injected pointer failure")
        return original(path, value)

    monkeypatch.setattr(support, "atomic_write_json", fail_pointer)
    with pytest.raises(TopologyError, match="pointer"):
        refresh(tmp_path, "compose.yaml")
    assert artifact(tmp_path) == json.loads(before["topology.json"])
    assert manifest(tmp_path)["generation"] in before["topology/manifest.json"].decode()


def test_projection_failure_after_pointer_switch_restores_last_known_good(tmp_path, monkeypatch):
    write(tmp_path, "compose.yaml", COMPOSE)
    refresh(tmp_path, "compose.yaml")
    before = snapshot(tmp_path)
    before_manifest = manifest(tmp_path)
    before_render = (tmp_path / ".atlas/spec/structure/global/runtime-topology.md").read_bytes()
    write(tmp_path, "compose.yaml", COMPOSE.replace("postgres:16", "postgres:17"))
    import _support.runtime_topology as support
    original = support.atomic_write_bytes
    failed = False

    def fail_render(path, data):
        nonlocal failed
        if Path(path).name == "runtime-topology.md" and "/.adapter-out/topology/generations/" not in Path(path).as_posix() and not failed:
            failed = True
            raise OSError("injected projection failure")
        return original(path, data)

    monkeypatch.setattr(support, "atomic_write_bytes", fail_render)
    with pytest.raises(TopologyError, match="投影写入失败"):
        refresh(tmp_path, "compose.yaml")
    assert (tmp_path / ".adapter-out/topology.json").read_bytes() == before["topology.json"]
    assert manifest(tmp_path) == before_manifest
    assert (tmp_path / ".atlas/spec/structure/global/runtime-topology.md").read_bytes() == before_render


def test_manifest_business_digest_tamper_is_detected(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    refresh(tmp_path, "compose.yaml")
    pointer = manifest(tmp_path)
    pointer["business_digest"] = "0" * 64
    (tmp_path / ".adapter-out/topology/manifest.json").write_text(json.dumps(pointer), encoding="utf-8")
    result = check_topology(tmp_path, mode="enforce")
    assert result["verdict"] == "FAIL" and result["rc"] == 1
    assert any("business_digest" in finding["message"] for finding in result["findings"])


def test_off_is_unverified_rc2_and_writes_nothing(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    result = refresh(tmp_path, "compose.yaml", mode="off")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2 and result["mode"] == "off"
    assert not (tmp_path / ".adapter-out").exists()
    assert check_topology(tmp_path, mode="off")["rc"] == 2


def test_no_cluster_commands_are_executed(tmp_path, monkeypatch):
    write(tmp_path, "compose.yaml", COMPOSE)

    def forbidden(*args, **kwargs):
        raise AssertionError("cluster command executed")

    monkeypatch.setattr(subprocess, "run", forbidden)
    assert refresh(tmp_path, "compose.yaml")["verdict"] == "PASS"
    assert check_topology(tmp_path)["verdict"] == "PASS"


def test_cli_and_validator_exit_codes_and_rollback(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    cli = [sys.executable, str(PKG_ROOT / "scripts/atlas_topology.py"), "--root", str(tmp_path)]
    args = ["--mode", "enforce", "refresh", "--project", "shop", "--environment", "dev", "--cluster", "local",
            "--release", "r1", "--scan-glob", "compose.yaml", "--json"]
    assert topology_main(cli[2:] + args) == 0
    validator = [sys.executable, str(PKG_ROOT / "validators/validate_runtime_topology.py"),
                 "--root", str(tmp_path), "--mode", "shadow", "--json"]
    checked = subprocess.run(validator, capture_output=True, text=True)
    assert checked.returncode == 0 and json.loads(checked.stdout)["verdict"] == "PASS"
    write(tmp_path, "compose.yaml", COMPOSE.replace("postgres:16", "postgres:17"))
    checked = subprocess.run(validator[:-3] + ["--mode", "enforce", "--json"], capture_output=True, text=True)
    assert checked.returncode == 1 and json.loads(checked.stdout)["cause"] == "topology_stale"
    assert topology_main(cli[2:] + args) == 0
    assert topology_main(cli[2:] + ["rollback", "--json"]) == 0


def test_adapter_accepts_absolute_inside_root_out_but_rejects_escape(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    adapter = [sys.executable, str(PKG_ROOT / "adapters/runtime_topology.py"), "--root", str(tmp_path),
               "--project", "shop", "--environment", "dev", "--cluster", "local", "--release", "r1",
               "--scan-glob", "compose.yaml", "--json"]
    inside = subprocess.run(adapter + ["--out", str(tmp_path / ".adapter-out/topology.json")],
                            capture_output=True, text=True)
    assert inside.returncode == 0, inside.stdout + inside.stderr
    assert validate_topology(artifact(tmp_path)) == []
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    rejected = subprocess.run(adapter + ["--out", str(outside)], capture_output=True, text=True)
    assert rejected.returncode == 1 and not outside.exists()


def test_helm_dynamic_image_and_selector_are_field_level_unverified(tmp_path):
    text = HELM.replace("image: registry.example/api:2", "image: {{ .Values.image }}")
    text = text.replace("    app: api\n  ports:", "    app: {{ .Values.app }}\n  ports:")
    write(tmp_path, "helm/templates/workloads.yaml", text)
    result = refresh(tmp_path, "helm/templates/*.yaml", mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    value = artifact(tmp_path)
    assert validate_topology(value) == []
    fields = {tuple(item["fields"]) for item in value["coverage"]["unverified_fields"]}
    assert ("image",) in fields and ("selector",) in fields
    assert "{{ .Values.image }}" not in json.dumps(value)


def test_helm_control_blocks_are_explicitly_unverified(tmp_path):
    text = HELM.replace("image: registry.example/api:2",
                        "image: {{ .Values.image.repository }}:{{ .Values.image.tag }}")
    text = "{{- if .Values.enabled }}\n" + text + "{{- end }}\n"
    write(tmp_path, "helm/templates/workloads.yaml", text)
    result = refresh(tmp_path, "helm/templates/*.yaml", mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    assert any("控制流" in item["message"] for item in result["findings"])
    assert not (tmp_path / ".adapter-out/topology.json").exists()


def test_kong_top_level_route_and_plugin_link_to_service(tmp_path):
    text = KONG + """routes:
  - name: extra
    service: api
    paths: [/extra]
plugins:
  - name: key-auth
    service: api
"""
    write(tmp_path, "kong.yaml", text)
    result = refresh(tmp_path, "kong.yaml")
    assert result["verdict"] == "PASS" and result["rc"] == 0
    relations = {(item["kind"], item["relation"]) for item in artifact(tmp_path)["items"] if item.get("edge")}
    assert ("routes_to", "route") in relations
    assert ("plugin", "plugin:key-auth") in relations


def test_identity_unverified_carries_source_and_unknown_scope_blocks(tmp_path):
    write(tmp_path, "a.yaml", "services:\n  api:\n    image: demo/api:1\n")
    write(tmp_path, "b.yaml", "services:\n  api:\n    image: demo/api:2\n")
    refresh(tmp_path, "*.yaml")
    fields = artifact(tmp_path)["coverage"]["unverified_fields"]
    identity = next(item for item in fields if item["fields"] == ["identity"])
    assert identity["source_file"] in {"a.yaml", "b.yaml"}
    from _support.runtime_topology import scope_topology_result
    result = {"verdict": "UNVERIFIED", "cause": "topology_unverified", "generation": "x",
              "metrics": {"parsed": 1}, "rc": 2, "findings": []}
    assert scope_topology_result(result, {"coverage": {"unverified_fields": [{"id": "x"}]}}, [])["verdict"] == "UNVERIFIED"
    assert scope_topology_result(result, {"coverage": {"unverified_fields": [identity]}}, [identity["source_file"]])["verdict"] == "UNVERIFIED"


def test_dynamic_namespace_and_app_are_field_level_unverified(tmp_path):
    text = COMPOSE.replace("  api:\n    image:", "  api:\n    namespace: '${NS}'\n    app: '${APP}'\n    image:", 1)
    write(tmp_path, "compose.yaml", text)
    result = refresh(tmp_path, "compose.yaml", mode="enforce")
    assert result["verdict"] == "UNVERIFIED" and result["rc"] == 2
    fields = artifact(tmp_path)["coverage"]["unverified_fields"]
    api = next(item for item in fields if item["id"].endswith(":api"))
    assert set(api["fields"]) == {"namespace", "app"}
    assert api["source_file"] == "compose.yaml"


def test_same_id_dynamic_sources_are_not_merged_across_files(tmp_path):
    write(tmp_path, "a.yaml", "services:\n  api:\n    image: '${IMAGE}'\n")
    write(tmp_path, "b.yaml", "services:\n  api:\n    image: demo/api:1\n")
    refresh(tmp_path, "*.yaml")
    fields = [item for item in artifact(tmp_path)["coverage"]["unverified_fields"]
              if item.get("source_file") == "a.yaml" and "image" in item["fields"]]
    assert len(fields) == 1


def test_identity_conflict_records_both_sources_for_scope(tmp_path):
    write(tmp_path, "a.yaml", "services:\n  api:\n    image: demo/api:1\n")
    write(tmp_path, "b.yaml", "services:\n  api:\n    image: demo/api:2\n")
    refresh(tmp_path, "*.yaml")
    fields = [item for item in artifact(tmp_path)["coverage"]["unverified_fields"]
              if item["fields"] == ["identity"]]
    assert {item["source_file"] for item in fields} == {"a.yaml", "b.yaml"}
    from _support.runtime_topology import scope_topology_result
    result = {"verdict": "UNVERIFIED", "cause": "topology_unverified", "generation": "x",
              "metrics": {"parsed": 1}, "rc": 2, "findings": []}
    scoped = scope_topology_result(result, artifact(tmp_path), ["a.yaml"])
    assert scoped["verdict"] == "UNVERIFIED" and scoped["rc"] == 2


def test_same_business_refresh_rejects_corrupt_previous_pointer(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    refresh(tmp_path, "compose.yaml")
    pointer_path = tmp_path / ".adapter-out/topology/manifest.json"
    pointer = json.loads(pointer_path.read_text())
    pointer["business_digest"] = "0" * 64
    pointer_path.write_text(json.dumps(pointer))
    with pytest.raises(TopologyError, match="business_digest"):
        refresh(tmp_path, "compose.yaml")
    with pytest.raises(TopologyError, match="business_digest"):
        refresh(tmp_path, "compose.yaml", mode="enforce")
    write(tmp_path, "compose.yaml", COMPOSE.replace("postgres:16", "postgres:18"))
    with pytest.raises(TopologyError, match="business_digest"):
        refresh(tmp_path, "compose.yaml", mode="enforce")


def test_refresh_rejects_extra_entries_in_existing_generation(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    current = refresh(tmp_path, "compose.yaml")
    directory = tmp_path / ".adapter-out/topology/generations" / current["generation"]
    (directory / "unbound.txt").write_text("extra")
    with pytest.raises(TopologyError, match="额外|非普通"):
        refresh(tmp_path, "compose.yaml")


def test_rollback_rejects_extra_entries_and_incomplete_source_manifest(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    refresh(tmp_path, "compose.yaml")
    write(tmp_path, "compose.yaml", COMPOSE.replace("postgres:16", "postgres:17"))
    refresh(tmp_path, "compose.yaml")
    pointer_path = tmp_path / ".adapter-out/topology/manifest.json"
    pointer = json.loads(pointer_path.read_text())
    old_dir = tmp_path / ".adapter-out/topology/generations" / pointer["previous_generation"]
    (old_dir / "unbound.txt").write_text("extra")
    before = pointer_path.read_bytes()
    with pytest.raises(TopologyError, match="额外|非普通"):
        rollback_topology(tmp_path)
    assert pointer_path.read_bytes() == before
    (old_dir / "unbound.txt").unlink()
    pointer["previous_pointer"]["source_files"] = {}
    pointer_path.write_text(json.dumps(pointer))
    before = pointer_path.read_bytes()
    with pytest.raises(TopologyError, match="source_files"):
        rollback_topology(tmp_path)
    assert pointer_path.read_bytes() == before


def test_rollback_pointer_failure_preserves_current_generation(tmp_path, monkeypatch):
    write(tmp_path, "compose.yaml", COMPOSE)
    refresh(tmp_path, "compose.yaml")
    write(tmp_path, "compose.yaml", COMPOSE.replace("postgres:16", "postgres:17"))
    current = refresh(tmp_path, "compose.yaml")
    before = snapshot(tmp_path)
    import _support.runtime_topology as support
    original = support.atomic_write_json

    def fail_pointer(path, value):
        if Path(path).name == "manifest.json":
            raise OSError("injected rollback failure")
        return original(path, value)

    monkeypatch.setattr(support, "atomic_write_json", fail_pointer)
    with pytest.raises(TopologyError, match="回滚 pointer"):
        rollback_topology(tmp_path)
    assert manifest(tmp_path)["generation"] == current["generation"]
    assert snapshot(tmp_path) == before


def test_dynamic_cli_returns_two_and_missing_artifact_is_unverified(tmp_path):
    write(tmp_path, "compose.yaml", COMPOSE)
    cli = [sys.executable, str(PKG_ROOT / "scripts/atlas_topology.py"), "--root", str(tmp_path),
           "--mode", "enforce", "refresh", "--project", "shop", "--environment", "dev", "--cluster", "local",
           "--release", "r1", "--scan-glob", "compose.yaml", "--json"]
    initial = subprocess.run(cli, capture_output=True, text=True)
    assert initial.returncode == 0
    write(tmp_path, "compose.yaml", COMPOSE.replace("registry.example/api:1", "${IMAGE}"))
    dynamic = subprocess.run(cli, capture_output=True, text=True)
    assert dynamic.returncode == 2 and json.loads(dynamic.stdout)["verdict"] == "UNVERIFIED"
    assert (tmp_path / ".adapter-out/topology.json").is_file()
    (tmp_path / ".adapter-out/topology.json").unlink()
    (tmp_path / ".adapter-out/topology/manifest.json").unlink()
    missing = subprocess.run([sys.executable, str(PKG_ROOT / "validators/validate_runtime_topology.py"),
                              "--root", str(tmp_path), "--mode", "enforce", "--json"],
                             capture_output=True, text=True)
    assert missing.returncode == 2 and json.loads(missing.stdout)["verdict"] == "UNVERIFIED"
    assert validator_main(["--root", str(tmp_path), "--mode", "off", "--json"]) == 2
