"""M248: Compose static topology adapter.

First paragraph declaration: dropping dynamic image/port/dependency handling must
turn tests/test_runtime_topology.py red. Mutation evidence is
.atlas/runs/mutation-proof/M248.txt. Environment and secret values are never read.
"""
from __future__ import annotations

from _support.runtime_topology import (
    TopologyError,
    block_end,
    dynamic,
    edge,
    find_item_line,
    find_line,
    node,
    parse_error,
    unverified,
)


def _list_line(text: str, value: str, start: int, end: int) -> int:
    for number, raw in enumerate(text.splitlines()[start:end], start + 1):
        if raw.strip() == f"- {value}":
            return number
    return start + 1


def parse(text: str, source_file: str, sha256: str, inputs: dict, *, owner: str,
          due: str, document: dict, offset: int = 0) -> tuple[list[dict], dict]:
    """Extract services, images, ports, dependencies and shared networks."""
    coverage = {"unverified_fields": [], "parse_errors": []}
    services = document.get("services")
    if not isinstance(services, dict):
        raise TopologyError("Compose services 必须为 map")
    items: list[dict] = []
    by_name: dict[str, dict] = {}
    dynamic_names = set()
    spans: dict[str, tuple[int, int]] = {}
    for name, config in services.items():
        line = find_line(text, str(name), offset, indent=2)
        end = block_end(text, line, 2)
        spans[name] = (line, end)
        if dynamic(name):
            dynamic_names.add(name)
            unverified(coverage, f"{source_file}:{line}", ["name"], owner, due)
            continue
        if not isinstance(config, dict):
            raise TopologyError(f"Compose service {name} 必须为 map")
        namespace = config.get("namespace") if isinstance(config.get("namespace"), str) else None
        app = config.get("app") if isinstance(config.get("app"), str) else None
        fields = []
        if dynamic(namespace):
            fields.append("namespace")
            namespace = None
        if dynamic(app):
            fields.append("app")
            app = None
        image = config.get("image")
        if dynamic(image):
            fields.append("image")
            image = None
        elif image is not None and not isinstance(image, str):
            raise TopologyError(f"Compose service {name} image 必须为字符串")
        ports = []
        raw_ports = config.get("ports") or []
        if not isinstance(raw_ports, list):
            raise TopologyError(f"Compose service {name} ports 必须为列表")
        for port in raw_ports:
            if dynamic(port):
                fields.append("ports")
            elif isinstance(port, (int, str)):
                ports.append(port)
            elif isinstance(port, dict) and isinstance(port.get("target"), int):
                ports.append(port["target"])
            else:
                fields.append("ports")
        current = node(inputs, "service", name, source_file, line, sha256,
                       namespace=namespace, app=app, image=image, ports=ports)
        by_name[name] = current
        items.append(current)
        if fields:
            unverified(coverage, current["id"], fields, owner, due)

    for name, current in by_name.items():
        line, end = spans[name]
        config = services[name]
        dependencies = config.get("depends_on") or {}
        if isinstance(dependencies, dict):
            entries = list(dependencies)
        elif isinstance(dependencies, list):
            entries = [item.get("service") if isinstance(item, dict) else item for item in dependencies]
            if any(not isinstance(item, str) for item in entries):
                raise TopologyError(f"Compose service {name} depends_on 长语法缺 service")
        else:
            raise TopologyError(f"Compose service {name} depends_on 必须为 map/list")
        dep_line = find_line(text, "depends_on", line, end, indent=4)
        dep_end = block_end(text, dep_line, 4)
        for dependency in entries:
            if dynamic(dependency):
                unverified(coverage, current["id"], ["depends_on"], owner, due)
                continue
            if dependency in dynamic_names:
                unverified(coverage, current["id"], ["depends_on"], owner, due)
                continue
            if dependency not in by_name:
                parse_error(coverage, source_file, f"Compose depends_on 引用缺失服务：{dependency}")
                continue
            anchor = find_line(text, str(dependency), dep_line, dep_end, indent=6) \
                if isinstance(dependencies, dict) else _list_line(text, str(dependency), dep_line, dep_end)
            items.append(edge(current, by_name[dependency], "depends_on", "depends_on",
                              source_file, anchor, sha256))

        networks = config.get("networks") or {}
        entries = list(networks) if isinstance(networks, dict) else networks
        if not isinstance(entries, list):
            raise TopologyError(f"Compose service {name} networks 必须为 map/list")
        network_line = find_line(text, "networks", line, end, indent=4)
        network_end = block_end(text, network_line, 4)
        for network in entries:
            if dynamic(network):
                unverified(coverage, current["id"], ["networks"], owner, due)
                continue
            anchor = find_line(text, str(network), network_line, network_end, indent=6) \
                if isinstance(networks, dict) else _list_line(text, str(network), network_line, network_end)
            current.setdefault("_networks", []).append((str(network), anchor))

    for left in by_name.values():
        for right in by_name.values():
            if left["id"] >= right["id"]:
                continue
            right_networks = {name: line for name, line in right.get("_networks", [])}
            for network, line in left.get("_networks", []):
                if network in right_networks:
                    items.append(edge(left, right, "network", f"network:{network}",
                                      source_file, line, sha256))
    for current in by_name.values():
        current.pop("_networks", None)
    return items, coverage
