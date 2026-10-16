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


def test_f41_adapter_out_single_location() -> None:
    """F41（2026-10-15，issue #8）：`.adapter-out/` 是**单一位点 = 项目根**。

    三消费者必须同址：适配器产物（`refresh_structure`）、漂移门（`atlas_check`）、图谱
    新鲜度标记（`adapters/_graph`）。此前图谱层在项目根、结构环产物在
    `.trellis/spec/structure/` 下 ⇒ 同名两处。现场因此出现「`git status` 里有
    `.adapter-out/`，而漂移门说『无 .adapter-out 产物目录』」的自相矛盾——排查者会先怀疑
    门坏，而不是去比对基准。本钉即 issue #8 ④ 要求的「把两处硬编码字面量钉在一起」：
    任一消费者改回 spec 目录即红。
    """
    import importlib.util

    def load(name: str, rel: str):
        spec = importlib.util.spec_from_file_location(name, PKG_ROOT / rel)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    rs = load("rs_single_loc", "scripts/refresh_structure.py")
    ac = load("ac_single_loc", "scripts/atlas_check.py")
    gr = load("gr_single_loc", "adapters/_graph.py")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # ① 写入侧（适配器产物 + 漂移标记）
        assert rs.adapter_out_dir(root) == root / ".adapter-out"
        # ② 读取侧（漂移门）：SKIP 文案必须**带上实际路径**，否则「SKIP 与现场不一致」时
        #    读者看不出问的是哪条路径（issue #8 ③）
        rows = ac.Row()
        ac.check_drift(root, rows)
        skip = [r for r in rows.rows if r["name"] == "结构漂移"][0]
        assert skip["status"] == "SKIP", skip
        assert str(root / ".adapter-out") in skip["detail"], skip
        # ③ 图谱层标记与上面**同址**
        assert Path(gr.INDEX_MARKER).parent == Path(rs.ADAPTER_OUT_DIRNAME), gr.INDEX_MARKER


def build(root: Path) -> None:
    sd = root / ".trellis" / "spec" / "structure"
    sd.mkdir(parents=True, exist_ok=True)   # .adapter-out 已移到项目根 ⇒ 不再顺带建 sd

    (root / ".adapter-out" / "api").mkdir(parents=True, exist_ok=True)
    (root / ".adapter-out" / "models").mkdir(parents=True, exist_ok=True)
    (sd / "_meta.json").write_text(json.dumps(META, ensure_ascii=False), encoding="utf-8")
    (root / ".adapter-out" / "routes.json").write_text(json.dumps({
        "category": "routes",
        "items": [{"path": "/home", "source_file": "app/pages/home.py", "status": "已实现"}],
    }, ensure_ascii=False), encoding="utf-8")
    (root / ".adapter-out" / "api" / "app.json").write_text(json.dumps({
        "category": "api",
        "items": [{"method": "GET", "path": "/home", "summary": "首页", "source_module": "home",
                   "source_file": "app/pages/home.py"}],
    }, ensure_ascii=False), encoding="utf-8")
    (root / ".adapter-out" / "models" / "app.json").write_text(json.dumps({
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
        sd.mkdir(parents=True, exist_ok=True)   # .adapter-out 已移到项目根 ⇒ 不再顺带建 sd

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

        # F16 回灌：适配器空产物（items: []）避免意外清空既有手写/已有结构事实 routes.md
        (root / ".adapter-out" / "routes.json").write_text(
            json.dumps({"category": "routes", "items": []}, ensure_ascii=False), encoding="utf-8")
        r = run(root, "--apply")
        assert r.returncode == 0
        assert "WARN: 适配器产物为空，保留既有手工事实" in r.stdout
        assert "首页入口" in routes_path.read_text(encoding="utf-8")


def test_duplicate_row_keys_collapse_within_one_facts_file() -> None:
    """同一事实文件内**重复行键折叠为一行**（D69 的行键级合并以「行键唯一」为前提）。

    2026-10-15 补：RPC 端点常从同域多个模块被调、同名同字段模型常在两个文件各声明一次。
    适配器**不去重**（items 粒度 = 代码里的事实；跨域重复是合法事实，各进各的域文件），
    折叠点在这里 —— 不折叠则表里出现同键同内容的重复行，而 `merge_cells` 的语义列
    在重复键上也没有归属可言。变异 M58：摘掉 `dedup_by_row_key` ⇒ 本侧红。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        (root / ".adapter-out" / "api" / "app.json").write_text(
            json.dumps({
                "category": "api",
                "items": [
                    {"method": "RPC", "path": "zeldaEasy.x.doIt", "summary": None,
                     "source_module": "app/pages/home.py", "source_file": "app/pages/home.py"},
                    {"method": "RPC", "path": "zeldaEasy.x.doIt", "summary": None,
                     "source_module": "app/pages/home_detail.py",
                     "source_file": "app/pages/home_detail.py"},
                ],
            }, ensure_ascii=False), encoding="utf-8")
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        apis = (root / ".trellis" / "spec" / "structure" / "current" / "home"
                / "apis.md").read_text(encoding="utf-8")
        assert apis.count("zeldaEasy.x.doIt") == 1, apis


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
        sd.mkdir(parents=True, exist_ok=True)   # .adapter-out 已移到项目根 ⇒ 不再顺带建 sd

        # 模拟改名：改写适配器产物（路由 /home → /home2，未走 apply 登记）
        (root / ".adapter-out" / "routes.json").write_text(json.dumps({
            "category": "routes",
            "items": [{"path": "/home2", "source_file": "app/pages/home.py", "status": "已实现"}],
        }, ensure_ascii=False), encoding="utf-8")
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr + r.stdout
        assert "结构漂移" in r.stdout, r.stdout
        marker = root / ".adapter-out" / "_drift.json"
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
        hist = root / ".adapter-out" / "_drift-history.jsonl"
        assert hist.is_file() and "/home2" in hist.read_text(encoding="utf-8")


def test_drift_dry_run_prints_without_marker() -> None:
    """dry-run 只打印漂移，不落任何盘面（含标记文件）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        run(root, "--apply")
        sd = root / ".trellis" / "spec" / "structure"
        sd.mkdir(parents=True, exist_ok=True)   # .adapter-out 已移到项目根 ⇒ 不再顺带建 sd

        (root / ".adapter-out" / "routes.json").write_text(
            json.dumps({"category": "routes", "items": [
                {"path": "/home2", "source_file": "app/pages/home.py", "status": "已实现"}
            ]}, ensure_ascii=False), encoding="utf-8")
        r = run(root)
        assert r.returncode == 0, r.stderr + r.stdout
        assert "结构漂移" in r.stdout, r.stdout
        assert not (root / ".adapter-out" / "_drift.json").exists()


def test_pipe_in_cell_value_round_trips() -> None:
    """回归（2026-10-04）：单元格值含裸 `|`（例：字段类型 `datetime | None`）曾被裸切分
    撑成 7 列静默丢弃 ⇒ 语义列合并失效 + 漂移误报。render_table 转义后必须往返一致。
    变异：render_table 摘掉转义 ⇒ 本用例红（解析丢行、漂移不收敛）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        sd = root / ".trellis" / "spec" / "structure"
        sd.mkdir(parents=True, exist_ok=True)   # .adapter-out 已移到项目根 ⇒ 不再顺带建 sd

        (root / ".adapter-out" / "models" / "app.json").write_text(json.dumps({
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


def test_multiline_cell_value_round_trips() -> None:
    """回归（2026-10-16，issue #16；RFC-20261016-01 D84）：适配器给**多行取值**时（对象 /
    函数类型字面量等），原实现原样写进单元格 ⇒ 该行在盘面断成多行 ⇒ `parse_rows` 丢掉首行
    （列数不符）、跳过续行（不以竖线开头）⇒ ① 事实丢行；② 键读不回 ⇒ 每轮刷新都判「新增」
    ⇒ 漂移标记常驻、baseline 棘轮永不释放。写侧单行化（换行 → `<br>`）后必须往返一致。

    变异：摘掉 `render_table` 的单行化 ⇒ 本用例红（丢行 + 漂移不收敛）（M-R1）；
          把换行换成**空格** ⇒ 行结构断言红（防「用空格糊过去也算修好」）（M-R2）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        sd = root / ".trellis" / "spec" / "structure"
        sd.mkdir(parents=True, exist_ok=True)

        (root / ".adapter-out" / "models" / "app.json").write_text(json.dumps({
            "category": "models",
            "items": [{"table": "users", "field": "payload",
                       "type": "{\n  a: string\n  b: { c: number }\n}",
                       "source_file": "app/pages/home.py"}],
            "enums": [],
        }, ensure_ascii=False), encoding="utf-8")
        r1 = run(root, "--apply")
        assert r1.returncode == 0, r1.stderr + r1.stdout
        # 渲染即自校（D84 条 3）必须在不变式成立时静默
        assert "WARN[render_table]" not in r1.stderr, r1.stderr
        dm = (sd / "current" / "home" / "data-models.md").read_text(encoding="utf-8")
        # ① 行结构保留：换行变 `<br>`，不得被空格把两个成员粘平
        assert "<br>" in dm, dm
        assert "b: { c: number }" in dm, dm
        assert "a: string b: {" not in dm, dm
        # ② 该行能被读回（丢行的直接标志）
        assert "| users | payload |" in dm, dm
        # ③ 第二轮：键读得回 ⇒ 无漂移、内容幂等
        before = dm
        r2 = run(root, "--apply")
        assert r2.returncode == 0, r2.stderr + r2.stdout
        assert "结构漂移" not in r2.stdout, r2.stdout
        assert not (root / ".adapter-out" / "_drift.json").exists()
        assert (sd / "current" / "home" / "data-models.md").read_text(encoding="utf-8") == before


def test_key_column_with_newline_does_not_phantom_drift() -> None:
    """D84 条 2（2026-10-16，评审 F3）：**行键列自身含换行**时，适配器原值（真换行）与
    盘面读回值（`<br>`）必须归一化等价，否则仍是同一族幻影漂移（键读不回 ⇒ 判「新增」）。

    变异：`_norm` 退回 `" ".join(str(s).split())` ⇒ 本用例红（第二轮报漂移）。
    """
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        sd = root / ".trellis" / "spec" / "structure"
        sd.mkdir(parents=True, exist_ok=True)

        (root / ".adapter-out" / "models" / "app.json").write_text(json.dumps({
            "category": "models",
            "items": [{"table": "users", "field": "a\nb", "type": "string",
                       "source_file": "app/pages/home.py"}],
            "enums": [],
        }, ensure_ascii=False), encoding="utf-8")
        r1 = run(root, "--apply")
        assert r1.returncode == 0, r1.stderr + r1.stdout
        assert "WARN[render_table]" not in r1.stderr, r1.stderr
        assert "users | a<br>b" in (sd / "current" / "home" / "data-models.md").read_text(encoding="utf-8")
        r2 = run(root, "--apply")
        assert "结构漂移" not in r2.stdout, r2.stdout
        assert not (root / ".adapter-out" / "_drift.json").exists()


def test_render_selfcheck_fires_on_unroundtrippable_row(capsys) -> None:
    """D85 条 3：渲染即自校必须**活着能咬** —— 否则它只是一段没人验证的代码。

    输入形态是**人为构造**的：整行单元格只由 `-` / `:` / 空格组成 ⇒ `parse_rows` 会把它当表头
    分隔行跳过 ⇒ 读回少一行（这是表格格式本身的残留边界，真实适配器数据到不了这里）。本用例钉
    的是机制：不变式真的被检查，且不成立时**当轮出声**。

    变异：摘掉 `_selfcheck_round_trip` 调用 ⇒ 本用例红（M-R10）。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("rs_selfcheck", SCRIPT)
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)

    rs.render_table(rs.MODEL_HEADER, [["-", "-", "-", "-", "-", "-"],
                                      ["users", "id", "int", "", "", ""]], where="probe")
    err = capsys.readouterr().err
    assert "WARN[render_table]" in err and "probe" in err, err
    # 正常形态不得出声（防「永远在报」的噪声型门）
    rs.render_table(rs.MODEL_HEADER, [["users", "id", "int", "", "", ""]], where="probe")
    assert "WARN[render_table]" not in capsys.readouterr().err


STUB_ADAPTER = '''#!/usr/bin/env python3
"""F25 夹具 stub 适配器：契约形（--root/--app/--out），按 app 写入产品 JSON。"""
import argparse
import json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--root", required=True)
ap.add_argument("--app", default=None)
ap.add_argument("--out", required=True)
a = ap.parse_args()

items_by_cat = {
    "stub_routes": [{"path": {None: "/stub-route-from-adapter"}.get(a.app, f"/stub-route-{a.app}"),
                     "source_file": "app/pages/adapter.py", "status": "已实现"}],
    "stub_models": [{"table": "users", "field": "adapter_field", "type": "int",
                     "source_file": "app/pages/adapter.py"}],
}[Path(__file__).stem]

if a.app == "broken":  # demo 失败面由 --app 名触发
    import sys
    sys.exit(3)

Path(a.out).parent.mkdir(parents=True, exist_ok=True)
Path(a.out).write_text(json.dumps({
    "category": "routes" if "routes" in Path(__file__).stem else "models",
    "items": items_by_cat,
}, ensure_ascii=False), encoding="utf-8")
'''

BROKEN_EXIT_ADAPTER = '''#!/usr/bin/env python3
import sys
sys.exit(3)
'''

ADAPTER_PROFILE = """product: demo
apps:
  - name: app
    path: app
    kind: frontend
adapters:
  routes: stub_routes
  models: stub_models
"""


def write_profile(root: Path, text: str) -> None:
    (root / "product").mkdir(parents=True, exist_ok=True)
    (root / "product" / "stack-profile.yaml").write_text(text, encoding="utf-8")


def git_ready(root: Path) -> None:
    r = lambda *a: __import__("subprocess").run(["git", "-C", str(root), *a],
                                                capture_output=True, text=True)
    r("init")
    r("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    r("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init")


def head_sha(root: Path) -> str:
    import subprocess
    return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def write_stub_adapters(root: Path, broken_exit: str | None = None) -> None:
    ad = root / "product" / "adapters_stub"   # 只写盘不做解析（解析走 .atlas/adapters）
    ad.mkdir(parents=True, exist_ok=True)
    at = root / ".atlas" / "adapters"
    at.mkdir(parents=True, exist_ok=True)
    (at / "stub_routes.py").write_text(STUB_ADAPTER, encoding="utf-8")
    (at / "stub_models.py").write_text(STUB_ADAPTER, encoding="utf-8")
    if broken_exit:
        (at / "stub_models.py").write_text(BROKEN_EXIT_ADAPTER, encoding="utf-8")


def test_chain_runs_adapters_then_refresh_in_one_pass() -> None:
    """F25+F27：--chain 一遍完成「适配器产物 → 事实区 → L2 指针」——
    首建单遍即得完整 L2 链接表（旧口径首遍空表须两遍）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        write_profile(root, ADAPTER_PROFILE)
        write_stub_adapters(root)
        r = run(root, "--chain")
        assert r.returncode == 0, r.stderr + r.stdout
        sd = root / ".trellis" / "spec" / "structure"
        sd.mkdir(parents=True, exist_ok=True)   # .adapter-out 已移到项目根 ⇒ 不再顺带建 sd

        # 适配器产物更新（routes.json 由 stub 写入新键）
        assert "stub-route-from-adapter" in (root / ".adapter-out" / "routes.json").read_text(encoding="utf-8")
        # 事实区渲染含新键
        assert "stub-route-from-adapter" in (sd / "global" / "routes.md").read_text(encoding="utf-8")
        # F27：L2 指针一遍即链接到本轮新落的事实文件
        dom = (sd / "domains" / "home.md").read_text(encoding="utf-8")
        assert "current/home/apis.md" in dom, dom


def test_chain_failure_aborts_before_refresh() -> None:
    """F25 失败语义（拍板）：任一适配器非零退出 ⇒ 中止链条不进 refresh，exit 2；
    中止前已落盘产物 = 上一轮一致态，残留无害。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        write_profile(root, ADAPTER_PROFILE)
        write_stub_adapters(root, broken_exit="models")
        r = run(root, "--chain")
        assert r.returncode == 2, r.stdout
        sd = root / ".trellis" / "spec" / "structure"
        sd.mkdir(parents=True, exist_ok=True)   # .adapter-out 已移到项目根 ⇒ 不再顺带建 sd

        # routes 适配器（顺序在前）已落盘
        assert "stub-route-from-adapter" in (root / ".adapter-out" / "routes.json").read_text(encoding="utf-8")
        # refresh 未执行 ⇒ 事实表不存在（首建场景事实表本来未落，links 不更新）
        out = (sd / "global" / "routes.md")
        # 这里 build() 的 routes.json 在 stub 前已存在旧内容（build 夹具产物），
        # refresh 未跑 ⇒ global/routes.md 仍未生成（首建）
        assert not out.exists(), "中止后不得进刷新"


def test_chain_undeclared_adapter_script_aborts() -> None:
    """F25 fail-loud：声明了适配器名但按契约解析不到脚本 ⇒ exit 2。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        write_profile(root, ADAPTER_PROFILE)  # 声明了 stub_*，但 .atlas/adapters 缺失
        r = run(root, "--chain")
        assert r.returncode == 2 and "解析失败" in r.stderr, r.stderr


def test_apply_default_never_advances_baseline() -> None:
    """F26（C2 零变化承诺）：显式 --apply 默认永不推进 baseline——git-ready 夹具 + 事实
    非空 + 零漂移，仍不推进。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        git_ready(root)
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr
        assert "advanced baseline" not in r.stdout, r.stdout
        meta_now = json.loads((root / ".trellis" / "spec" / "structure" / "_meta.json").read_text(encoding="utf-8"))
        assert meta_now["baseline"]["commit"] == "abc"


def test_chain_advances_baseline_when_clean() -> None:
    """F26 四前置全过：--chain 零漂移（首建 existed=False 合法新增）+ 事实非空
    + 产品侧干净 ⇒ baseline 推进到 HEAD。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        git_ready(root)
        write_profile(root, ADAPTER_PROFILE)
        write_stub_adapters(root)
        r = run(root, "--chain")
        assert r.returncode == 0, r.stderr
        assert "advanced baseline" in r.stdout, r.stdout
        meta_now = json.loads((root / ".trellis" / "spec" / "structure" / "_meta.json").read_text(encoding="utf-8"))
        assert meta_now["baseline"]["commit"] == head_sha(root)


def test_chain_advance_frozen_by_drift_then_override() -> None:
    """F26 诚实 ratchet：本轮零漂移才推进；有漂移 ⇒ 冻结；--advance-baseline 显式越过。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        git_ready(root)
        write_profile(root, ADAPTER_PROFILE)
        write_stub_adapters(root)
        r1 = run(root, "--chain")   # 首建: baseline=HEAD
        assert r1.returncode == 0
        sha1 = head_sha(root)  # _meta.json 此刻未提交，落盘的是 facts 所述代码态 commit（约定口径）
        # 制造漂移：改 routes 适配器产物键级
        (root / ".adapter-out" / "routes.json").write_text(json.dumps({
            "category": "routes", "items": [
                {"path": "/changed", "source_file": "app/pages/home.py", "status": "已实现"}],
        }, ensure_ascii=False), encoding="utf-8")
        r = run(root, "--apply")     # 显式 apply 漂移刷新（零推进承诺不受影响）
        assert "结构漂移" in r.stdout
        assert json.loads((root / ".trellis" / "spec" / "structure" / "_meta.json").read_text(encoding="utf-8"))["baseline"]["commit"] == sha1
        # --chain 因冻结跳过推进
        r2 = run(root, "--chain")
        assert "冻结" in r2.stdout, r2.stdout
        assert json.loads((root / ".trellis" / "spec" / "structure" / "_meta.json").read_text(encoding="utf-8"))["baseline"]["commit"] == sha1
        # 人工终审：提交漂移对应的工作（HEAD 前进）后，--advance-baseline 显式越过仍存的偏移 Freeze
        subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-m", "drift registered"], capture_output=True)
        sha2 = head_sha(root)
        assert sha2 != sha1
        r3 = run(root, "--chain", "--advance-baseline")
        assert "advanced baseline" in r3.stdout, r3.stdout
        assert json.loads((root / ".trellis" / "spec" / "structure" / "_meta.json").read_text(encoding="utf-8"))["baseline"]["commit"] == sha2


def test_advance_skips_when_product_dirty() -> None:
    """F26 第四前置：产品侧工作树脏 ⇒ SKIP（不给未审定代码背书）；.atlas/.trellis 自身写盘豁免。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        git_ready(root)
        write_profile(root, "product: demo\napps: []\nadapters: {}\n")
        (root / "svc").mkdir(parents=True, exist_ok=True)
        (root / "svc" / "pending.py").write_text("# 未提交代码\n", encoding="utf-8")
        r = run(root, "--chain")
        assert "产品侧" in r.stdout, r.stdout


def test_render_tour_lists_adapter_run_command() -> None:
    """F29：tour.md「项目概况」行含适配器来源的测试运行命令（消费闭环落在门面文件）。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        build(root)
        sd = root / ".trellis" / "spec" / "structure"
        sd.mkdir(parents=True, exist_ok=True)   # .adapter-out 已移到项目根 ⇒ 不再顺带建 sd

        (root / ".adapter-out" / "tests").mkdir(parents=True, exist_ok=True)
        (root / ".adapter-out" / "tests" / "app.json").write_text(json.dumps({
            "category": "tests",
            "items": [{"type": "unit", "location": "app/test_x.py",
                       "run_command": ".venv/bin/python -m pytest app/tests", "status": None}],
        }, ensure_ascii=False), encoding="utf-8")
        r = run(root, "--apply")
        assert r.returncode == 0, r.stderr
        tour = (sd / "tour.md").read_text(encoding="utf-8")
        assert "- 测试运行方式：`.venv/bin/python -m pytest app/tests`（来源：结构适配器 tests.json）" in tour, tour


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
