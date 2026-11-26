"""M248: Helm/Kubernetes static topology adapter.

First paragraph declaration: dropping selector/Service matching or volume relation
extraction must turn tests/test_runtime_topology.py red. Mutation evidence is
.atlas/runs/mutation-proof/M248.txt. Secret values and template directives are not read.
"""
from __future__ import annotations

from _support.runtime_topology import (
    TopologyError,
    block_end,
    dynamic,
    edge,
    find_line,
    node,
    unverified,
)


def _metadata(document: dict) -> dict:
    value = document.get("metadata")
    if not isinstance(value, dict) or not isinstance(value.get("name"), str):
        raise TopologyError("Kubernetes metadata.name 必须为静态字符串")
    return value


def _container_block(text: str, start: int):
    line = find_line(text, "containers", start)
    indent = len(text.splitlines()[line - 1]) - len(text.splitlines()[line - 1].lstrip(" "))
    end = block_end(text, line, indent)
    starts = [number for number, raw in enumerate(text.splitlines()[line:end], line + 1)
              if raw.lstrip().startswith("- name:")]
    return line, end, starts


def parse(text: str, source_file: str, sha256: str, inputs: dict, *, owner: str,
          due: str, document: dict, offset: int = 0) -> tuple[list[dict], dict]:
    """Extract workload/container facts, Service selectors and volume attachments."""
    coverage = {"unverified_fields": [], "parse_errors": []}
    kind = document.get("kind")
    metadata = _metadata(document)
    name = metadata["name"]
    if dynamic(name):
        unverified(coverage, f"{source_file}:{offset + 1}", ["name"], owner, due)
        return [], coverage
    kind_line = find_line(text, "kind", offset)
    metadata_line = find_line(text, "metadata", kind_line)
    spec_line = find_line(text, "spec", metadata_line)
    name_line = find_line(text, "name", metadata_line, spec_line, indent=2)
    namespace = metadata.get("namespace")
    if dynamic(namespace):
        unverified(coverage, f"{source_file}:{name_line}", ["namespace"], owner, due)
        namespace = None
    spec = document.get("spec") if isinstance(document.get("spec"), dict) else {}
    template = spec.get("template") if isinstance(spec.get("template"), dict) else {}
    pod = template.get("spec") if isinstance(template.get("spec"), dict) else {}
    metadata = template.get("metadata") if isinstance(template.get("metadata"), dict) else {}
    labels = metadata.get("labels") if isinstance(metadata.get("labels"), dict) else {}
    app = labels.get("app") if isinstance(labels.get("app"), str) and not dynamic(labels["app"]) else None
    if kind == "Service":
        ports = []
        fields = ["spec"] if not isinstance(document.get("spec"), dict) else []
        for port in spec.get("ports") or []:
            value = port.get("port") if isinstance(port, dict) else None
            if dynamic(value):
                fields.append("ports")
            elif isinstance(value, (int, str)):
                ports.append(value)
            else:
                fields.append("ports")
        if app is None:
            selector_value = spec.get("selector") if isinstance(spec.get("selector"), dict) else {}
            selector_app = selector_value.get("app")
            if isinstance(selector_app, str) and not dynamic(selector_app):
                app = selector_app
        current = node(inputs, "service", f"service-{name}", source_file, name_line, sha256,
                       namespace=namespace, app=app, ports=ports)
        selector = spec.get("selector") or {}
        if not isinstance(selector, dict):
            raise TopologyError(f"Service {name} selector 必须为 map")
        if any(dynamic(key) or dynamic(value) for key, value in selector.items()):
            fields.append("selector")
            selector = {}
        if fields:
            unverified(coverage, current["id"], fields, owner, due)
        current["_service_name"] = name
        current["_selector"] = selector
        current["_service_name_line"] = name_line
        return [current], coverage

    containers = pod.get("containers") or []
    if not isinstance(containers, list) or not containers:
        raise TopologyError(f"{kind} {name} 缺少 containers")
    container_line, container_end, starts = _container_block(text, spec_line)
    if not starts:
        starts = [container_line]
    ports: list = []
    image = None
    fields = ["app"] if dynamic(labels.get("app")) else []
    attachments = []
    for index, container in enumerate(containers):
        if not isinstance(container, dict):
            raise TopologyError(f"{kind} {name} container 必须为 map")
        line = starts[min(index, len(starts) - 1)]
        next_line = starts[index + 1] if index + 1 < len(starts) else container_end
        raw_image = container.get("image")
        if index == 0:
            if dynamic(raw_image):
                fields.append("image")
            elif isinstance(raw_image, str):
                image = raw_image
        for port in container.get("ports") or []:
            value = port.get("containerPort") if isinstance(port, dict) else None
            if dynamic(value):
                fields.append("ports")
            elif isinstance(value, int):
                ports.append(value)
            else:
                fields.append("ports")
        mounts_line = find_line(text, "volumeMounts", line, next_line)
        mounts_indent = len(text.splitlines()[mounts_line - 1]) - len(text.splitlines()[mounts_line - 1].lstrip(" "))
        mounts_end = block_end(text, mounts_line, mounts_indent)
        mount_starts = [number for number, raw in enumerate(text.splitlines()[mounts_line:mounts_end], mounts_line + 1)
                        if raw.lstrip().startswith("- name:")]
        for mount_index, mount in enumerate(container.get("volumeMounts") or []):
            if not isinstance(mount, dict):
                continue
            volume_name = mount.get("name")
            mount_line = mount_starts[min(mount_index, len(mount_starts) - 1)] if mount_starts else mounts_line + mount_index + 1
            if dynamic(volume_name) or dynamic(mount.get("mountPath")):
                fields.append("volumes")
                continue
            if isinstance(volume_name, str):
                # The frozen schema has no volume node kind; a self-edge records
                # the attachment without inventing a database/service node.
                attachments.append((f"volume:{container.get('name', index)}:{volume_name}", mount_line))
    volumes_line = find_line(text, "volumes", spec_line)
    volumes_indent = len(text.splitlines()[volumes_line - 1]) - len(text.splitlines()[volumes_line - 1].lstrip(" "))
    volumes_end = block_end(text, volumes_line, volumes_indent)
    volume_starts = [number for number, raw in enumerate(text.splitlines()[volumes_line:volumes_end], volumes_line + 1)
                     if raw.lstrip().startswith("- name:")]
    for volume_index, volume in enumerate(pod.get("volumes") or []):
        if not isinstance(volume, dict):
            continue
        volume_name = volume.get("name")
        volume_line = volume_starts[min(volume_index, len(volume_starts) - 1)] if volume_starts else volumes_line + volume_index + 1
        if dynamic(volume_name):
            fields.append("volumes")
        elif isinstance(volume_name, str):
            attachments.append((f"volume:{volume_name}", volume_line))
    current = node(inputs, "service", name, source_file, name_line, sha256,
                   namespace=namespace, app=app, image=image, ports=ports)
    current["_labels"] = labels
    current["_service_name"] = spec.get("serviceName")
    items = [current]
    for relation, line in attachments:
        items.append(edge(current, current, "depends_on", relation, source_file, line, sha256))
    if fields:
        unverified(coverage, current["id"], fields, owner, due)
    return items, coverage


def link_services(items: list[dict]) -> list[dict]:
    """Add Service→workload edges after all documents have been extracted."""
    workloads = [item for item in items if item.get("_labels") is not None]
    services = [item for item in items if "_selector" in item]
    result = []
    for service in services:
        selector = service["_selector"]
        for workload in workloads:
            labels = workload["_labels"]
            if selector and all(labels.get(key) == value for key, value in selector.items()):
                port = service["ports"][0] if service["ports"] else None
                result.append(edge(service, workload, "routes_to", "selector", service["source_file"],
                                   service["_service_name_line"], service["sha256"], port=port))
            elif workload.get("_service_name") == service.get("_service_name"):
                result.append(edge(service, workload, "routes_to", "serviceName", service["source_file"],
                                   service["_service_name_line"], service["sha256"]))
    return result


def finalize(items: list[dict]) -> list[dict]:
    """Resolve cross-document links and remove parser-only selector state."""
    linked = link_services(items)
    for item in items:
        for key in ("_service_name", "_selector", "_labels", "_service_name_line"):
            item.pop(key, None)
    return items + linked
