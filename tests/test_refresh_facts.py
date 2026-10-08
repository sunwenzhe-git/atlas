#!/usr/bin/env python3
"""refresh_structure 事实区自动渲染（H1/H2/D69）回归测试。

    python3 atlas/tests/test_refresh_facts.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PKG_ROOT / "scripts" / "refresh_structure.py"

META = {
    "atlas_version": "0.1.0", "product": "demo",
    "baseline": {"branch": "main", "commit": "abc"},
    "apps": [{"name": "app", "path": "app", "kind": "frontend", "role": "landing", "stack": "x"}],
    "categories": {}, "domains": [
        {"id": "home", "name": "首页", "apps": ["app"], "status": "候选", "globs": ["app/pages/home*"]}
    ],
}


def build(root: Path) -> None:
    sd = root / ".trellis" / "spec" / "structure"
    (sd / ".adapter-out" / "api").mkdir(parents=True, exist_ok=True)
    (sd / ".adapter-out" / "models").mkdir(parents=True, exist_ok=True)
    (sd / "_meta.json").write_text(json.dumps(META, ensure_ascii=False), encoding="utf-8")
    (sd / ".adapter-out" / "routes.json").write_text(json.dumps({
        "category": "routes",
        "items": [{"path": "/home", "source_file": "app/pages/home.py", "status": "已实现"}],
    }, ensure_ascii=False), encoding="utf-8")
    (sd / ".adapter-out" / "api" / "app.json").write_text(json.dumps({
        "category": "api",
        "items": [{"method": "GET", "path": "/home", "summary": "首页", "source_module": "home",
                   "source_file": "app/pages/home.py"}],
    }, ensure_ascii=False), encoding="utf-8")
    (sd / ".adapter-out" / "models" / "app.json").write_text(json.dumps({
        "category": "models",
        "items": [
            {"table": "users", "field": "id", "type": "int", "source_file": "app/pages/home.py"},
            {"table": "shared_t", "field": "k", "type": "str", "source_file": "app/lib/other.py"},
        ],
        "enums": [],
    }, ensure_ascii=False), encoding="utf-8")


def run(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), *extra],
                          capture_output=True, text=True)


def test_facts_rendered_and_mapped() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        sd = root / ".trellis" / "spec" / "structure"
        routes = (sd / "global" / "routes.md").read_text(encoding="utf-8")
        assert "| app | /home | home |" in routes, routes
        apis = (sd / "current" / "home" / "apis.md").read_text(encoding="utf-8")
        assert "| GET | /home | 首页 |" in apis
        dm = (sd / "current" / "home" / "data-models.md").read_text(encoding="utf-8")
        assert "| users | id | int |" in dm
        shared = (sd / "global" / "data-models-shared.md").read_text(encoding="utf-8")
        assert "shared_t" in shared                      # 无域命中 → shared
        assert not (sd / "global" / "design-tokens.md").exists()  # F 类已退役（2026-09-30）


def test_semantic_cells_preserved() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        run(root, "--apply")
        routes_path = root / ".trellis" / "spec" / "structure" / "global" / "routes.md"
        # 手动写入语义单元格「用途」，重跑应保留
        text = routes_path.read_text(encoding="utf-8")
        routes_path.write_text(text.replace("| app | /home | home |  |  |", "| app | /home | home | 首页入口 |  |"),
                               encoding="utf-8")
        run(root, "--apply")
        assert "首页入口" in routes_path.read_text(encoding="utf-8")


def test_idempotent() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        run(root, "--apply")
        r = run(root, "--apply")
        assert r.returncode == 0
        assert r.stdout.count("facts =") >= 3, r.stdout


def test_dry_run_no_write() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        r = run(root)
        assert r.returncode == 0
        assert not (root / ".trellis" / "spec" / "structure" / "global" / "routes.md").exists()


def test_drift_detected_then_cleared() -> None:
    """未登记漂移（2026-10-04 门禁负向用例 #3）：适配器产物键级增删 ⇒ 响亮输出 +
    落 `.adapter-out/_drift.json`；下一次无键级变更的 `--apply` 刷新 ⇒ 标记清除复绿。
    变异：摘掉 `record_drift` 调用 ⇒ 本用例红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        run(root, "--apply")
        sd = root / ".trellis" / "spec" / "structure"
        # 模拟改名：改写适配器产物（路由 /home → /home2，未走 apply 登记）
        (sd / ".adapter-out" / "routes.json").write_text(json.dumps({
            "category": "routes",
            "items": [{"path": "/home2", "source_file": "app/pages/home.py", "status": "已实现"}],
        }, ensure_ascii=False), encoding="utf-8")
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        assert "结构漂移" in r.stdout, r.stdout
        marker = sd / ".adapter-out" / "_drift.json"
        assert marker.is_file(), r.stdout
        d = json.loads(marker.read_text(encoding="utf-8"))
        dr = d["drifts"][0]
        assert dr["kind"] == "routes", dr
        assert any("/home2" in a for a in dr["added"]) and any("/home" in x for x in dr["removed"]), dr
        assert "/home2" in (sd / "global" / "routes.md").read_text(encoding="utf-8")
        # 第二次刷新（产物与事实表一致）⇒ 标记清除、不再告警；history 留痕供收口对账
        r2 = run(root, "--apply")
        assert r2.returncode == 0
        assert "结构漂移" not in r2.stdout, r2.stdout
        assert not marker.exists()
        hist = sd / ".adapter-out" / "_drift-history.jsonl"
        assert hist.is_file() and "/home2" in hist.read_text(encoding="utf-8")


def test_drift_dry_run_prints_without_marker() -> None:
    """dry-run 只打印漂移，不落任何盘面（含标记文件）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        run(root, "--apply")
        sd = root / ".trellis" / "spec" / "structure"
        (sd / ".adapter-out" / "routes.json").write_text(
            json.dumps({"category": "routes", "items": []}, ensure_ascii=False), encoding="utf-8")
        r = run(root)
        assert r.returncode == 0, r.stderr + r.stdout
        assert "结构漂移" in r.stdout, r.stdout
        assert not (sd / ".adapter-out" / "_drift.json").exists()


def test_pipe_in_cell_value_round_trips() -> None:
    """回归（2026-10-04）：单元格值含裸 `|`（例：字段类型 `datetime | None`）曾被裸切分
    撑成 7 列静默丢弃 ⇒ 语义列合并失效 + 漂移误报。render_table 转义后必须往返一致。
    变异：render_table 摘掉转义 ⇒ 本用例红（解析丢行、漂移不收敛）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        sd = root / ".trellis" / "spec" / "structure"
        (sd / ".adapter-out" / "models" / "app.json").write_text(json.dumps({
            "category": "models",
            "items": [
                {"table": "users", "field": "id", "type": "datetime | None",
                 "source_file": "app/pages/home.py"},
            ],
            "enums": [],
        }, ensure_ascii=False), encoding="utf-8")
        run(root, "--apply")
        dm = (sd / "current" / "home" / "data-models.md").read_text(encoding="utf-8")
        assert "datetime \\| None" in dm, dm          # 盘面转义
        # 第二次刷新：转义行被正确读回 ⇒ 无漂移、内容幂等
        before = dm
        r2 = run(root, "--apply")
        assert r2.returncode == 0
        assert "结构漂移" not in r2.stdout, r2.stdout
        assert (sd / "current" / "home" / "data-models.md").read_text(encoding="utf-8") == before


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  ✗ {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"{'FAIL' if failed else 'PASS'} ({len(tests) - failed}/{len(tests)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
