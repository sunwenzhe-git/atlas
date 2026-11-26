"""M248: Kong declarative static topology adapter.

First paragraph declaration: dropping upstream matching or plugin/route edge
extraction must turn tests/test_runtime_topology.py red. Mutation evidence is
.atlas/runs/mutation-proof/M248.txt. Plugin config and secret values are never read.
"""
from __future__ import annotations

from urllib.parse import urlsplit

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


def _items(value, label: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TopologyError(f"Kong {label} 必须为列表")
    return value


def _named(value, label: str) -> tuple[str, dict]:
    if not isinstance(value, dict) or not isinstance(value.get("name"), str):
        raise TopologyError(f"Kong {label} 必须含静态 name")
    return value["name"], value


def parse(text: str, source_file: str, sha256: str, inputs: dict, *, owner: str,
          due: str, document: dict, offset: int = 0) -> tuple[list[dict], dict]:
    """Extract Kong services, routes, upstreams and plugins without config values."""
    coverage = {"unverified_fields": [], "parse_errors": []}
    services = _items(document.get("services"), "services")
    upstreams = _items(document.get("upstreams"), "upstreams")
    items: list[dict] = []
    service_nodes: dict[str, dict] = {}
    dynamic_service_names = set()
    upstream_nodes: dict[str, dict] = {}
    service_line = find_line(text, "services", offset)
    service_end = block_end(text, service_line, 0)
    starts = [number for number, raw in enumerate(text.splitlines()[service_line:service_end], service_line + 1)
              if raw.startswith("  - name:")]

    for index, raw_service in enumerate(services):
        name, config = _named(raw_service, "service")
        line = starts[min(index, len(starts) - 1)] if starts else service_line + index + 1
        end = starts[index + 1] if index + 1 < len(starts) else service_end
        if dynamic(name):
            dynamic_service_names.add(name)
            unverified(coverage, f"{source_file}:{line}", ["name"], owner, due)
            continue
        current = node(inputs, "kong_service", name, source_file, line, sha256, app=name)
        items.append(current)
        service_nodes[name] = current
        url = config.get("url")
        if dynamic(url):
            unverified(coverage, current["id"], ["url"], owner, due)
        elif isinstance(url, str):
            parsed_url = urlsplit(url)
            if parsed_url.username or parsed_url.password:
                unverified(coverage, current["id"], ["url"], owner, due)
            else:
                current["ports"] = [parsed_url.port] if parsed_url.port else []
                current["_upstream_name"] = parsed_url.hostname

        routes_line = find_line(text, "routes", line, end)
        routes_end = block_end(text, routes_line, 4)
        route_starts = [number for number, raw in enumerate(text.splitlines()[routes_line:routes_end], routes_line + 1)
                        if raw.startswith("      - name:")]
        for route_index, raw_route in enumerate(_items(config.get("routes"), "routes")):
            route_name, _ = _named(raw_route, "route")
            route_line = route_starts[min(route_index, len(route_starts) - 1)] if route_starts else routes_line + route_index + 1
            if dynamic(route_name):
                unverified(coverage, current["id"], ["routes"], owner, due)
                continue
            route = node(inputs, "kong_route", f"{name}/{route_name}", source_file, route_line, sha256, app=name)
            items.extend([route, edge(current, route, "routes_to", "route", source_file, route_line, sha256)])

        plugins_line = find_line(text, "plugins", line, end)
        plugins_end = block_end(text, plugins_line, 4)
        plugin_starts = [number for number, raw in enumerate(text.splitlines()[plugins_line:plugins_end], plugins_line + 1)
                         if raw.startswith("      - name:")]
        for plugin_index, raw_plugin in enumerate(_items(config.get("plugins"), "plugins")):
            plugin_name, _ = _named(raw_plugin, "plugin")
            plugin_line = plugin_starts[min(plugin_index, len(plugin_starts) - 1)] if plugin_starts else plugins_line + plugin_index + 1
            if dynamic(plugin_name):
                unverified(coverage, current["id"], ["plugins"], owner, due)
                continue
            plugin = node(inputs, "kong_plugin", f"{name}/{plugin_name}", source_file, plugin_line, sha256, app=name)
            items.extend([plugin, edge(current, plugin, "plugin", f"plugin:{plugin_name}",
                                       source_file, plugin_line, sha256)])

    upstream_line = find_line(text, "upstreams", offset)
    upstream_end = block_end(text, upstream_line, 0)
    upstream_starts = [number for number, raw in enumerate(text.splitlines()[upstream_line:upstream_end], upstream_line + 1)
                       if raw.startswith("  - name:")]
    for index, raw_upstream in enumerate(upstreams):
        name, config = _named(raw_upstream, "upstream")
        line = upstream_starts[min(index, len(upstream_starts) - 1)] if upstream_starts else upstream_line + index + 1
        if dynamic(name):
            unverified(coverage, f"{source_file}:{line}", ["name"], owner, due)
            continue
        ports = []
        for target in _items(config.get("targets"), "targets"):
            value = target.get("target") if isinstance(target, dict) else None
            if dynamic(value):
                unverified(coverage, f"{source_file}:{line}", ["targets"], owner, due)
            elif isinstance(value, str) and ":" in value:
                port = value.rsplit(":", 1)[1]
                if port.isdigit():
                    ports.append(int(port))
                else:
                    unverified(coverage, f"{source_file}:{line}", ["targets"], owner, due)
        current = node(inputs, "kong_service", f"upstream-{name}", source_file, line, sha256,
                       app=name, ports=ports)
        current["_upstream_name"] = name
        items.append(current)
        upstream_nodes[name] = current

    def service_reference(config: dict, line: int) -> str | None:
        reference = config.get("service")
        if isinstance(reference, dict):
            reference = reference.get("name")
        if dynamic(reference):
            unverified(coverage, f"{source_file}:{line}", ["service"], owner, due)
            return None
        return reference if isinstance(reference, str) else None

    route_nodes = {}
    for label, node_kind, edge_kind in (("routes", "kong_route", "routes_to"),
                                        ("plugins", "kong_plugin", "plugin")):
        section_line = find_line(text, label, offset, indent=0)
        section_end = block_end(text, section_line, 0)
        section_starts = [number for number, raw in enumerate(text.splitlines()[section_line:section_end], section_line + 1)
                          if raw.startswith("  - name:")]
        for index, raw_item in enumerate(_items(document.get(label), label)):
            item_name, config = _named(raw_item, label)
            line = section_starts[min(index, len(section_starts) - 1)] if section_starts else section_line + index + 1
            service_name = service_reference(config, line)
            if dynamic(item_name):
                unverified(coverage, f"{source_file}:{line}", [label], owner, due)
                continue
            if label == "plugins" and service_name is None:
                route_name = config.get("route")
                route = route_nodes.get(route_name.get("name") if isinstance(route_name, dict) else route_name)
                if route is not None:
                    child = node(inputs, "kong_plugin", f"route/{item_name}", source_file, line, sha256,
                                 app="global")
                    items.extend([child, edge(route, child, "plugin", f"plugin:{item_name}",
                                              source_file, line, sha256)])
                    continue
                if config.get("consumer") is not None or route_name is not None:
                    unverified(coverage, f"{source_file}:{line}", ["plugins"], owner, due)
                    continue
                items.append(node(inputs, "kong_plugin", f"global/{item_name}", source_file, line, sha256,
                                  app="global"))
                continue
            if service_name is None:
                unverified(coverage, f"{source_file}:{line}", [label], owner, due)
                continue
            service = service_nodes.get(service_name)
            if service_name in dynamic_service_names:
                unverified(coverage, f"{source_file}:{line}", [label], owner, due)
                continue
            if service is None:
                parse_error(coverage, source_file, f"Kong {label} 引用缺失 service：{service_name}")
                continue
            child = node(inputs, node_kind, f"{service_name}/{item_name}", source_file, line, sha256,
                         app=service_name)
            relation = "route" if edge_kind == "routes_to" else f"plugin:{item_name}"
            items.extend([child, edge(service, child, edge_kind, relation, source_file, line, sha256)])
            if node_kind == "kong_route":
                route_nodes[item_name] = child

    for service in service_nodes.values():
        upstream_name = service.get("_upstream_name")
        upstream = upstream_nodes.get(upstream_name)
        if upstream is None and upstream_name:
            upstream = node(inputs, "kong_service", f"url-{upstream_name}", source_file,
                            service["line"], sha256, app=upstream_name,
                            ports=service["ports"])
            items.append(upstream)
            upstream_nodes[upstream_name] = upstream
        if upstream is not None:
            port = service["ports"][0] if service["ports"] else None
            items.append(edge(service, upstream, "upstream", "upstream", source_file,
                              service["line"], sha256, port=port))
        service.pop("_upstream_name", None)
    for upstream in upstream_nodes.values():
        upstream.pop("_upstream_name", None)
    return items, coverage
