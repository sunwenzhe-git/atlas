#!/usr/bin/env python3
"""最小结构上下文注入（按 paths: 命中）回归测试。

守护 Trellis 同构语义：只改前端 ⇒ 派工单只出现前端域 / 约定规范，
不出现后端域，也不把 `**` 兜底塞进显式范围；globs 的 `*` 不跨目录。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from _support.workflow_context import (  # noqa: E402
    load_specs, render_specs, select_specs,
)
from _support.workflow_dispatch import assemble_curated_context  # noqa: E402


def write_spec(root: Path, rel: str, globs: list[str], body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = "---\npaths:\n" + "".join(f"  - '{g}'\n" for g in globs) + "---\n\n"
    p.write_text(fm + body, encoding="utf-8")


def make_specs(tmp: Path) -> None:
    write_spec(tmp, ".atlas/spec/structure/tour.md", ["**"], "# 项目导航\n入口地图")
    write_spec(tmp, ".atlas/spec/structure/domains/web.md", ["apps/web/**"],
               "# web 域\n前端规范：组件复用 / testid")
    write_spec(tmp, ".atlas/spec/structure/domains/api.md", ["apps/api/**"],
               "# api 域\n后端规范：接口契约")
    write_spec(tmp, ".atlas/spec/conventions/testid.md", ["apps/web/**"],
               "# testid\n前端 testid 约定")
    # 无 paths 的文件不得被注入
    write_spec(tmp, ".atlas/spec/structure/global/routes.md", [], "# 路由\n（无 paths）")


def test_only_matching_specs_are_selected(tmp_path: Path) -> None:
    make_specs(tmp_path)
    picked = select_specs(tmp_path, paths=["apps/web/src/page.tsx"])
    rels = [s["rel"] for s in picked]
    assert ".atlas/spec/structure/domains/web.md" in rels
    assert ".atlas/spec/conventions/testid.md" in rels
    assert ".atlas/spec/structure/domains/api.md" not in rels
    assert ".atlas/spec/structure/tour.md" not in rels, "显式范围不得混入 ** 兜底"


def test_domain_fallback_without_paths(tmp_path: Path) -> None:
    make_specs(tmp_path)
    picked = select_specs(tmp_path, domains=["api"])
    assert [s["rel"] for s in picked] == [".atlas/spec/structure/domains/api.md"]


def test_no_signal_only_wildcard(tmp_path: Path) -> None:
    make_specs(tmp_path)
    picked = select_specs(tmp_path)
    assert [s["rel"] for s in picked] == [".atlas/spec/structure/tour.md"]


def test_cap_at_three_keeps_domain_lens(tmp_path: Path) -> None:
    make_specs(tmp_path)
    for i in range(5):
        write_spec(tmp_path, f".atlas/spec/conventions/rule{i}.md", ["apps/web/**"], f"# r{i}")
    picked = select_specs(tmp_path, paths=["apps/web/a.ts"])
    rels = [s["rel"] for s in picked]
    assert len(picked) <= 3
    assert ".atlas/spec/structure/domains/web.md" in rels, "约定不得挤掉域透镜"
    assert sum(1 for r in rels if "/conventions/" in r) <= 1, "结构命中时约定至多补 1 份"


def test_no_paths_spec_never_loaded(tmp_path: Path) -> None:
    make_specs(tmp_path)
    rels = [s["rel"] for s in load_specs(tmp_path)]
    assert ".atlas/spec/structure/global/routes.md" not in rels


def test_wide_guide_does_not_outrank_scoped_convention(tmp_path: Path) -> None:
    """通用指南列了更多（更长的）无关 glob，也不得挤掉对口的领域约定。"""
    make_specs(tmp_path)
    write_spec(tmp_path, ".atlas/spec/conventions/frontend/index.md", ["apps/web/**"],
               "# 前端开发规范")
    write_spec(tmp_path, ".atlas/spec/conventions/guides/reuse.md",
               ["apps/web/**", "apps/api/**", "services/billing-api/**", "services/search-api/**"],
               "# 通用复用指南")
    rels = [s["rel"] for s in select_specs(tmp_path, paths=["apps/web/src/page.tsx"])]
    assert ".atlas/spec/conventions/frontend/index.md" in rels
    assert ".atlas/spec/conventions/guides/reuse.md" not in rels


def test_render_is_minimal_and_explicit(tmp_path: Path) -> None:
    make_specs(tmp_path)
    picked = select_specs(tmp_path, paths=["apps/web/a.ts"])
    text = render_specs(picked, scope_paths=["apps/web/a.ts"])
    assert "apps/web/a.ts" in text
    assert "前端规范" in text
    assert "后端规范" not in text


def test_dispatch_md_contains_only_matching_specs(tmp_path: Path) -> None:
    make_specs(tmp_path)
    tdir = tmp_path / ".atlas/tasks/T-1"
    tdir.mkdir(parents=True)
    (tdir / "prd.md").write_text("# T-1\n", encoding="utf-8")
    task = {"id": "T-1", "title": "改前端", "acs": [], "affected_domains": [],
            "paths": ["apps/web/src/a.ts"], "_dir": str(tdir)}
    text = assemble_curated_context(tmp_path, task)
    assert "domains/web.md" in text
    assert "domains/api.md" not in text
    assert "tour.md" not in text


def test_plan_paths_persist_and_dispatch_uses_them(tmp_path: Path) -> None:
    make_specs(tmp_path)
    (tmp_path / ".atlas/tasks").mkdir(parents=True)
    env = {"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin:/usr/local/bin"}
    p = subprocess.run(
        [sys.executable, str(ROOT / "scripts/atlas_workflow.py"), "plan",
         "--root", str(tmp_path), "--unit", "T-1", "--requirement", "调整前端页面",
         "--paths", "apps/web/src/a.ts"],
        capture_output=True, text=True, env=env,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    meta = json.loads((tmp_path / ".atlas/tasks/T-1/task.json").read_text(encoding="utf-8"))
    assert meta["paths"] == ["apps/web/src/a.ts"]

    p2 = subprocess.run(
        [sys.executable, str(ROOT / "scripts/atlas_workflow.py"), "dispatch",
         "--root", str(tmp_path), "--unit", "T-1"],
        capture_output=True, text=True, env=env,
    )
    assert p2.returncode == 0, p2.stdout + p2.stderr
    text = (tmp_path / ".atlas/tasks/T-1/dispatch.md").read_text(encoding="utf-8")
    assert "domains/web.md" in text and "domains/api.md" not in text


def test_replan_without_paths_preserves_them(tmp_path: Path) -> None:
    make_specs(tmp_path)
    (tmp_path / ".atlas/tasks").mkdir(parents=True)
    env = {"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin:/usr/local/bin"}
    cmd = [sys.executable, str(ROOT / "scripts/atlas_workflow.py"), "plan",
           "--root", str(tmp_path), "--unit", "T-1", "--requirement", "调整前端页面"]
    assert subprocess.run(cmd + ["--paths", "apps/web/src/a.ts"],
                          capture_output=True, text=True, env=env).returncode == 0
    assert subprocess.run(cmd, capture_output=True, text=True, env=env).returncode == 0
    meta = json.loads((tmp_path / ".atlas/tasks/T-1/task.json").read_text(encoding="utf-8"))
    assert meta["paths"] == ["apps/web/src/a.ts"], "重跑 plan 不得丢已存路径"


def test_glob_star_does_not_cross_directory(tmp_path: Path) -> None:
    write_spec(tmp_path, ".atlas/spec/conventions/ts.md", ["src/*.ts"], "# ts")
    assert select_specs(tmp_path, paths=["src/a.ts"])
    assert not select_specs(tmp_path, paths=["src/a/b.ts"]), "`*` 不得跨目录"


def test_glob_double_star_matches_zero_or_more_dirs(tmp_path: Path) -> None:
    write_spec(tmp_path, ".atlas/spec/conventions/ts.md", ["src/**/*.ts"], "# ts")
    assert select_specs(tmp_path, paths=["src/a.ts"])
    assert select_specs(tmp_path, paths=["src/a/b/c.ts"])
    write_spec(tmp_path, ".atlas/spec/structure/domains/app.md", ["apps/web/**"], "# app")
    assert select_specs(tmp_path, paths=["apps/web"]), "目录 scope 应命中 apps/web/**"


def test_trailing_slash_glob(tmp_path: Path) -> None:
    write_spec(tmp_path, ".atlas/spec/conventions/web.md", ["apps/web/"], "# web")
    assert select_specs(tmp_path, paths=["apps/web/x.ts"])


def test_explicit_empty_paths_do_not_fall_back(tmp_path: Path) -> None:
    make_specs(tmp_path)
    assert select_specs(tmp_path, paths=["", "  "]) == []
    assert select_specs(tmp_path, paths=[]) == []


def test_absolute_and_escaping_paths(tmp_path: Path) -> None:
    make_specs(tmp_path)
    root = tmp_path.resolve()
    assert select_specs(root, paths=[str(root / "apps/web/a.ts")]), "根内绝对路径应可命中"
    assert select_specs(root, paths=["../outside.ts"]) == []
    assert select_specs(root, paths=["./apps/web/a.ts"]), "./ 前缀应归一"


def test_string_task_paths_are_tolerated(tmp_path: Path) -> None:
    make_specs(tmp_path)
    tdir = tmp_path / ".atlas/tasks/T-1"
    tdir.mkdir(parents=True)
    task = {"id": "T-1", "title": "t", "acs": [], "affected_domains": [],
            "paths": "apps/web/src/a.ts", "_dir": str(tdir)}
    text = assemble_curated_context(tmp_path, task)
    assert "domains/web.md" in text and "domains/api.md" not in text


def test_frontmatter_flow_array_bom_comment_and_dupe(tmp_path: Path) -> None:
    p = tmp_path / ".atlas/spec/conventions/web.md"
    p.parent.mkdir(parents=True)
    p.write_text("\ufeff---\npaths: [\"apps/web/**\", 'apps/web/**']  # dup\n---\n\n# web\n",
                 encoding="utf-8")
    specs = load_specs(tmp_path)
    assert specs and specs[0]["paths"] == ["apps/web/**"]


def test_domain_match_is_exact_or_prefixed(tmp_path: Path) -> None:
    make_specs(tmp_path)
    write_spec(tmp_path, ".atlas/spec/structure/domains/web-api.md", ["a/**"], "# web-api")
    picked = select_specs(tmp_path, domains=["domains"])
    assert [s["name"] for s in picked] == ["tour"], "父目录名不得当域命中"
    names = [s["name"] for s in select_specs(tmp_path, domains=["web"])]
    assert "web" in names and "web-api" in names


def test_fence_escapes_embedded_backticks(tmp_path: Path) -> None:
    write_spec(tmp_path, ".atlas/spec/conventions/x.md", ["a/**"], "示例：\n```ts\nconst a=1\n```")
    picked = select_specs(tmp_path, paths=["a/b.ts"])
    text = render_specs(picked, scope_paths=["a/b.ts"])
    assert "````md" in text and "\n````" in text


if __name__ == "__main__":
    import tempfile
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            with tempfile.TemporaryDirectory() as td:
                fn(Path(td))
            print(f"ok {name}")
