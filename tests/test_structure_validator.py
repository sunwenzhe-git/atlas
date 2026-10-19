#!/usr/bin/env python3
"""`validators/validate_structure.py` 的「喂坏输入必红」判据（`3509 §119`，批 6 第 8 项配套）。

**为什么单独一个文件**：`shared/gates.md` 的取证等级盘点发现 —— 其余四个校验器都有
「坏输入 ⇒ FAIL」的用例，而 **`validate_structure` 一条都没有**（全仓测试文件里零提及）
⇒ 它的「会咬」从来没有证据。本文件补上，并把该门升为 `出厂级（本轮实测）`。

六侧坏输入（每侧对应一个真判据，不是形态摆设）：
  1. 缺 `_meta.json`；
  2. `domains[]` 的 id 非法 / 重复；
  3. `current/<域>/` 缺 `apis.md`（类别覆盖）；
  4. `tour.md` / `domains/*.md` 的 `paths:` 写成**标量**（不是块列表 ⇒ 不会被注入）；
  5. 表格里的「来源文件」指向**不存在**的路径；
  6. `directory-map.md` 的**列头**不符契约。

变异证明：M14 把「类别覆盖 · 域级 apis/data-models」判据改成恒 True ⇒ 第 3 侧红；
M26 把 routes 语义列判据改成恒不告警 ⇒ `test_structure_routes_empty_semantic_columns_warn` 红（`§B121`，WARN 通道）。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("validate_structure_under_test",
                                                  PKG_ROOT / "validators" / "validate_structure.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vst = _load()

META = {
    "product": "夹具产品",
    "apps": [{"name": "web", "path": "web"}],
    "domains": [{"id": "demo", "globs": ["web/**"]}],
    "categories": {"A": "skipped", "H": "covered"},
}
TOUR = """---
paths:
  - '**'
---

# 夹具结构速查

| 域 | 一句话 |
|---|---|
| demo | 夹具域 |
"""
DOMAIN_DOC = """---
paths:
  - 'web/**'
---

# demo 域

夹具域说明。
"""
DIRECTORY_MAP = """# 目录与模块地图

| 路径 | 类型 | 职责（一句话） | 域 | 备注 |
|---|---|---|---|---|
| web | 前端 | 夹具 | demo | |
"""
ROUTES = """# 路由与页面

| 页面/路由 | 域 | 用途 | 关键交互 | 实现状态 | 来源文件 |
|---|---|---|---|---|---|
| / | demo | 首页 | 无 | 未开始 | web |
"""
ROUTES_GAP = """# 路由与页面

| 页面/路由 | 域 | 用途 | 关键交互 | 实现状态 | 来源文件 |
|---|---|---|---|---|---|
| /login | — |  |  | — | web |
"""
APIS_POINTER = """# demo 接口

真相源：夹具自带接口描述；访问方式：夹具。
"""
DATA_MODELS = """# demo 数据模型

| 表/模型 | 字段 | 类型 | 约束/默认 | 关系 | 枚举 |
|---|---|---|---|---|---|
| 夹具表 | id | int | 主键 | 无 | 无 |
"""


def mk(root: Path, *, meta: dict | None = None, tour: str = TOUR,
       apis: str | None = APIS_POINTER, directory_map: str = DIRECTORY_MAP,
       routes: str = ROUTES, profile: str | None = None) -> None:
    spec = root / ".trellis" / "spec" / "structure"
    (spec / "domains").mkdir(parents=True, exist_ok=True)
    (spec / "global").mkdir(parents=True, exist_ok=True)
    (spec / "current" / "demo").mkdir(parents=True, exist_ok=True)
    (root / "web").mkdir(exist_ok=True)                      # apps[].path 存在 ⇒ 非绿地
    (spec / "_meta.json").write_text(json.dumps(meta or META, ensure_ascii=False), encoding="utf-8")
    (spec / "tour.md").write_text(tour, encoding="utf-8")
    (spec / "domains" / "demo.md").write_text(DOMAIN_DOC, encoding="utf-8")
    (spec / "global" / "directory-map.md").write_text(directory_map, encoding="utf-8")
    (spec / "global" / "routes.md").write_text(routes, encoding="utf-8")
    if apis is not None:
        (spec / "current" / "demo" / "apis.md").write_text(apis, encoding="utf-8")
    (spec / "current" / "demo" / "data-models.md").write_text(DATA_MODELS, encoding="utf-8")
    if profile is not None:
        product = root / "product"
        product.mkdir(exist_ok=True)
        (product / "stack-profile.yaml").write_text(profile, encoding="utf-8")


PROFILE_WIRED_API = (
    "product: 夹具产品\n"
    "origin: adopt\n"
    "apps:\n"
    "  - name: web\n"
    "    path: web\n"
    "    kind: fullstack\n"
    "    role: landing\n"
    "    stack: react+fastapi\n"
    "adapters:\n"
    "  routes: routes_adapter\n"
    "  api: api_adapter\n"
    "  models: null\n"
    "  tests: null\n"
)


def _res(root: Path):
    # 注意：本校验器的 Result 用 `rows`（`ok: bool`），其余四个用 `checks`（`level: str`）
    return {c["check"]: c for c in vst.validate(root).rows}


def _tmp():
    import tempfile
    return tempfile.TemporaryDirectory()


def test_structure_baseline_passes() -> None:
    """正例必须先绿（否则后面各侧的红说明不了任何事）。"""
    with _tmp() as td:
        root = Path(td)
        mk(root)
        res = _res(root)
        bad = [k for k, c in res.items() if c.get("ok") is False]
        assert not bad, {k: res[k]["detail"] for k in bad}


def test_structure_missing_meta_fails() -> None:
    with _tmp() as td:
        root = Path(td)
        mk(root)
        (root / ".trellis" / "spec" / "structure" / "_meta.json").unlink()
        res = _res(root)
        assert res["域模型"]["ok"] is False and "_meta.json" in res["域模型"]["detail"], res["域模型"]


def test_structure_bad_domain_ids_fail() -> None:
    with _tmp() as td:
        root = Path(td)
        meta = dict(META, domains=[{"id": "Demo_Bad", "globs": ["web/**"]},
                                   {"id": "demo", "globs": ["web/**"]}])
        mk(root, meta=meta)
        res = _res(root)
        assert res["域模型 · domains[]"]["ok"] is False, res["域模型 · domains[]"]


def test_structure_missing_role_file_fails() -> None:
    """类别覆盖：`current/<域>/` 缺 `apis.md` ⇒ FAIL。

    变异 M14：把该判据改成恒 True ⇒ 本用例红。
    """
    with _tmp() as td:
        root = Path(td)
        mk(root, apis=None)
        res = _res(root)
        assert res["类别覆盖 · 域级 apis/data-models"]["ok"] is False, \
            res["类别覆盖 · 域级 apis/data-models"]
        assert "apis.md" in res["类别覆盖 · 域级 apis/data-models"]["detail"]


def test_structure_scalar_paths_fail() -> None:
    """`paths:` 写成标量 ⇒ 不会被注入 ⇒ FAIL（契约要求块列表）。"""
    with _tmp() as td:
        root = Path(td)
        mk(root, tour=TOUR.replace("paths:\n  - '**'", "paths: '**'"))
        res = _res(root)
        assert res["注入结构 paths 块列表"]["ok"] is False, res["注入结构 paths 块列表"]


def test_structure_unresolvable_source_file_fails() -> None:
    """表格里的「来源文件」指向不存在的路径 ⇒ FAIL（来源可定位）。"""
    with _tmp() as td:
        root = Path(td)
        mk(root, routes=ROUTES.replace("| / | demo | 首页 | 无 | 未开始 | web |",
                                       "| / | demo | 首页 | 无 | 未开始 | `web/src/ghost.tsx` |"))
        res = _res(root)
        assert res["来源可定位"]["ok"] is False, res["来源可定位"]
        assert "ghost" in res["来源可定位"]["detail"]


def test_structure_wrong_table_columns_fail() -> None:
    """`directory-map.md` 列头与契约不一致 ⇒ FAIL（表格列）。"""
    with _tmp() as td:
        root = Path(td)
        mk(root, directory_map=DIRECTORY_MAP.replace(
            "| 路径 | 类型 | 职责（一句话） | 域 | 备注 |", "| 路径 | 类型 | 说明 |"))
        res = _res(root)
        assert res["表格列"]["ok"] is False, res["表格列"]

def test_structure_routes_empty_semantic_columns_warn() -> None:
    """`§B121` 判据：语义列（用途/关键交互/实现状态）留空的行 ⇒ WARN 指名；WARN 不置红。"""
    with _tmp() as td:
        root = Path(td)
        mk(root, routes=ROUTES_GAP)
        v = vst.validate(root)
        assert v.ok, "WARN 不得置红"
        hits = [w for w in v.warns if w["check"] == "routes 语义列"]
        assert hits and "/login" in hits[0]["detail"] and "用途" in hits[0]["detail"], v.warns


def test_structure_routes_filled_semantic_columns_no_warn() -> None:
    """语义列补齐（或「—」占位）⇒ 无 WARN；占位与留空必须分得开。"""
    with _tmp() as td:
        root = Path(td)
        mk(root)  # 基线 ROUTES 语义列齐全
        v = vst.validate(root)
        assert not [w for w in v.warns if w["check"] == "routes 语义列"], v.warns


def test_structure_categories_prefix_tolerance() -> None:
    """F17 回灌：categories A/H 写 'H: skipped'、'H：covered' 等前缀容错提取关键字。"""
    meta_tolerant = dict(META)
    meta_tolerant["categories"] = {"A": "A: covered", "H": "H：covered"}
    with _tmp() as td:
        root = Path(td)
        mk(root, meta=meta_tolerant)
        res = _res(root)
        assert res["类别覆盖 · categories A/H"]["ok"] is True

    meta_tolerant["categories"] = {"A": "A: covered", "H": "H: added"}
    with _tmp() as td:
        root = Path(td)
        mk(root, meta=meta_tolerant)
        res = _res(root)
        assert res["类别覆盖 · categories A/H"]["ok"] is True

    meta_bad = dict(META)
    meta_bad["categories"] = {"A": "unknown", "H": "covered"}
    with _tmp() as td:
        root = Path(td)
        mk(root, meta=meta_bad)
        res = _res(root)
        assert res["类别覆盖 · categories A/H"]["ok"] is False


def test_f38_categories_prose_mention_is_not_a_declaration() -> None:
    """F38（2026-10-15，issue #6）：A/H 是**枚举声明**，判据读状态不读措辞。

    旧 `_cat_token` 是全文子串匹配（`re.search(r'\\bkw\\b', s)`）⇒ **只要字段里提到过**
    关键词就算通过。后果：描述「尚未完成」的措辞被判成「已完成」——H 类恰好是 `adopt`
    下**唯一不允许 `skipped`** 的类别（既有项目必须把「怎么跑」记下来），是收口时最需要
    它咬住的一格。

    四侧坏输入逐条对齐 issue 现场实证：前三条旧实现在**假绿**，第四条是旧实现唯一能
    正确报红的形态。
    """
    cases = {
        "待核准：…核准后补写为 added": "描述『尚未补写』却含 added",
        "covered 与否未定，也不含其他词": "明文说不确定",
        "这个类别 stayed skipped 因为没人管": "散文里提到 skipped",
        "本轮不做": "干脆没提关键词",
        "本轮不做，因为：added": "散文 + 冒号后带 token（防标签前缀被滥用成绕行道）",
    }
    for val, why in cases.items():
        for key in ("A", "H"):
            meta = dict(META)
            meta["categories"] = {**META["categories"], key: val}
            with _tmp() as td:
                root = Path(td)
                mk(root, meta=meta)
                row = _res(root)["类别覆盖 · categories A/H"]
                assert row["ok"] is False, f"{key}={val!r} 必须 FAIL（{why}）"


def test_f38_categories_declaration_with_evidence_passes() -> None:
    """F38 正控：token 声明在首位、取证文本接在 `：` / `（` 之后 ⇒ 通过。

    保住契约本来就允许的写法（token 之后放散文取证），确保新判据不是「一律从严」。
    """
    for val, key in (("covered：根 README「技术栈」「快速开始」两节齐备", "A"),
                     ("added：根 README 补了测试/运行说明", "H"),
                     ("covered（既有测试说明齐备）", "H"),
                     ("A: covered", "A"),
                     ("H：added", "H")):
        meta = dict(META)
        meta["categories"] = {**META["categories"], key: val}
        with _tmp() as td:
            root = Path(td)
            mk(root, meta=meta)
            row = _res(root)["类别覆盖 · categories A/H"]
            assert row["ok"] is True, f"{key}={val!r} 应通过，实得 {row['detail']}"



def test_f42_adapter_gaps_are_warned_not_failed() -> None:
    """F42（2026-10-15，issue #3 ④）：`_meta.json.adapter_gaps` 非空 ⇒ `WARN` 逐条指名。

    「未接」本身不是缺陷（契约：未接 ≠ 缺陷，而是「源即真相」的判定结果），所以不置红；
    但**必须可见**——不登记的话两种性质完全不同的处境在产物里同形（都是
    `maintained_by: agent`）：(a) 设计结论「源即真相，不接」；(b) **工具覆盖不足**
    （逐件判定表判「接」但本栈 0 命中）。采用者会把 (b) 读成 (a)，而该类别的
    `structure ↔ 代码` 对账平面永久缺口且无人知道它不是预期的。

    变异证明：摘掉 `add_warn` 分支 ⇒ 本用例红（缺口重新变成不可见）。
    """
    meta = dict(META)
    meta["adapter_gaps"] = {"routes": "0 命中（文件式路由 + .tsx）"}
    with _tmp() as td:
        root = Path(td)
        mk(root, meta=meta)
        res = vst.validate(root)
        assert res.ok, "缺口是 WARN，不得置红"          # 未接 ≠ 缺陷
        got = [w for w in res.warns if w["check"] == "适配器缺口"]
        assert got, res.warns                            # 但必须可见
        assert "routes" in got[0]["detail"] and "0 命中" in got[0]["detail"], got[0]


def test_f42_absent_or_empty_gaps_produce_no_noise() -> None:
    """F42：`adapter_gaps` 缺失或空对象 ⇒ **不产行、不产 WARN**（否则每个项目都多一条噪声）。"""
    for gaps in (None, {}):
        meta = dict(META)
        if gaps is not None:
            meta["adapter_gaps"] = gaps
        with _tmp() as td:
            root = Path(td)
            mk(root, meta=meta)
            res = vst.validate(root)
            assert not [w for w in res.warns if w["check"] == "适配器缺口"], res.warns
            assert all(c["ok"] is not False for c in res.rows if "适配器缺口" in c["check"]), res.rows


def test_f42_malformed_gaps_field_fails() -> None:
    """F42：形态非法（非对象）⇒ FAIL——契约把它定为「类别 → 取证」的对象。"""
    meta = dict(META)
    meta["adapter_gaps"] = ["routes"]
    with _tmp() as td:
        root = Path(td)
        mk(root, meta=meta)
        res = _res(root)
        assert res["适配器缺口 · 形态"]["ok"] is False, res.get("适配器缺口 · 形态")


def test_f31_case_id_reference_not_flagged_as_todo_placeholder() -> None:
    """F31（R7）：结构文档自然语言引用用例 ID（`E2E-TODO-004`，`-TODO-` 非独立 token）
    **不再**被占位符黑名单误杀；裸 `TODO`/`TODO:` 仍逐一拦截（fail-closed 不松）。"""
    with _tmp() as td:
        root = Path(td)
        mk(root)
        doc = root / ".trellis" / "spec" / "structure" / "domains" / "demo.md"
        doc.write_text(
            "# demo 域结构\n\n"
            "- 本域改动对照用例 `E2E-TODO-001` 至 `E2E-TODO-004`（自然语言引用）。\n",
            encoding="utf-8")
        res = _res(root)
        assert res["占位符"]["ok"] is True, res["占位符"]

    with _tmp() as td:
        root = Path(td)
        mk(root)
        doc = root / ".trellis" / "spec" / "structure" / "domains" / "demo.md"
        doc.write_text("# demo 域结构\n\n- 事项：TODO 待补充。\n", encoding="utf-8")
        res = _res(root)
        assert res["占位符"]["ok"] is False, "裸 TODO 必须命中（不放宽）"
        assert "TODO" in res["占位符"]["detail"], res["占位符"]

    with _tmp() as td:
        root = Path(td)
        mk(root)
        doc = root / ".trellis" / "spec" / "structure" / "domains" / "demo.md"
        doc.write_text("# demo 域结构\n\n- 事项：TODO: 后续补充判定。\n", encoding="utf-8")
        res = _res(root)
        assert res["占位符"]["ok"] is False, "TODO: 冒号形态必须命中"


def test_f33_api_pointer_form_waives_domain_apis_md() -> None:
    """F33（R8 收束）：D 类指针形态（OpenAPI 机器可读描述）落 `global/apis-shared.md`
    真相源行 ⇒ 该域 `apis.md` 缺失**合规**（免去手写域级指针）；data-models.md 不豁免。"""
    with _tmp() as td:
        root = Path(td)
        mk(root)  # 基线：current/demo 有 apis.md + data-models.md（夹具默认）
        add = root / ".trellis" / "spec" / "structure" / "current" / "other"
        add.mkdir(parents=True)
        (add / "data-models.md").write_text(DATA_MODELS, encoding="utf-8")
        meta2 = dict(META)
        meta2["domains"] = list(meta2["domains"]) + [
            {"id": "other", "name": "其他", "apps": ["app"], "status": "候选",
             "globs": ["app/pages/other*"]}]
        (root / ".trellis" / "spec" / "structure" / "_meta.json").write_text(
            json.dumps(meta2, ensure_ascii=False), encoding="utf-8")

        # 无指针行 ⇒ 缺 apis.md FAIL（原语义不放松）
        res = _res(root)
        assert res["类别覆盖 · 域级 apis/data-models"]["ok"] is False, res

        # 指针行命中 domain 的 app 名 ⇒ 豁免 PASS
        ptr_md = root / ".trellis" / "spec" / "structure" / "global" / "apis-shared.md"
        ptr_md.write_text(
            "# 跨域共享接口 / 真相源入口\n\n"
            "| 方法 | 路径 | 用途 | 请求要点 | 响应要点 | 来源模块 |\n"
            "|---|---|---|---|---|---|\n"
            "| — | OpenAPI: app 公开描述 | 真相源入口 |  |  | app |\n",
            encoding="utf-8")
        res2 = _res(root)
        assert res2["类别覆盖 · 域级 apis/data-models"]["ok"] is True, res2
        # 负例：app 名不匹配的指针行不豁免
        ptr_md.write_text(
            "# 跨域共享接口\n\n"
            "| 方法 | 路径 | 用途 | 请求要点 | 响应要点 | 来源模块 |\n"
            "|---|---|---|---|---|---|\n"
            "| — | OpenAPI: 另一 app | 真相源入口 |  |  | other-app |\n",
            encoding="utf-8")
        res3 = _res(root)
        assert res3["类别覆盖 · 域级 apis/data-models"]["ok"] is False, res3


def test_f34b_spec_relative_sibling_reference_resolves() -> None:
    """F34b（R8 收束）：结构文档中 `.trellis/spec/structure/` **内部相对引用**（如
    `global/routes.md`、`current/demo/apis.md`）以结构 spec 根为锚解析合法——
    旧口径只按项目根/app 根解析 ⇒ 结构文档引用兄弟文件被迫写全路径（F7 病根）。
    幻影引用（指向不存在的文件）照 FAIL（fail-closed 不松）。"""
    ref = ("- 结构上下文：`global/routes.md` 与 `current/demo/apis.md` 是本域的兄弟事实文件。\n")
    with _tmp() as td:
        root = Path(td)
        mk(root)
        doc = root / ".trellis" / "spec" / "structure" / "domains" / "demo.md"
        doc.write_text("# demo 域结构\n\n" + ref, encoding="utf-8")
        res = _res(root)
        assert res["来源可定位"]["ok"] is True, res["来源可定位"]

    with _tmp() as td:
        root = Path(td)
        mk(root)
        doc = root / ".trellis" / "spec" / "structure" / "domains" / "demo.md"
        doc.write_text("# demo 域结构\n\n- 幻影引用：`global/no-such-file.md`。\n",
                       encoding="utf-8")
        res = _res(root)
        assert res["来源可定位"]["ok"] is False, "幻影引用必须仍命中（不放宽）"
        assert "no-such-file" in res["来源可定位"]["detail"]


# ---------------------------------------------------- D 类接线态 ⇔ 形态声明（2026-10-15）

def _wire_warns(v):
    return [w for w in v.warns if w["check"] == "D 类接线态与形态声明混写"]


def test_f43_wired_api_with_pointer_d_warns() -> None:
    """接线态跨产物混写：`adapters.api` 已接线而 `categories.D` 锚定声明为**指针**形态 ⇒
    WARN 指名（`shared/stack-profile.md` §3.5：指针 / 未取证形态不得接源码枚举适配器）。

    变异证明（M64）：摘掉判定分支 ⇒ 本用例红（混写重新变得不可见）。
    另覆盖同族「未取证」形态。"""
    for d_val, why in (("指针（有机器可读描述：网关 /openapi.json，可在仓外）", "指针"),
                       ("未取证：用户尚未答复有无机器可读描述", "未取证")):
        meta = dict(META)
        meta["categories"] = {"A": "skipped", "H": "covered", "D": d_val}
        with _tmp() as td:
            root = Path(td)
            mk(root, meta=meta, profile=PROFILE_WIRED_API)
            v = vst.validate(root)
            assert v.ok, "接线态混写是 WARN，不得置红"
            got = _wire_warns(v)
            assert got, (d_val, [w["check"] for w in v.warns])
            assert "api_adapter" in got[0]["detail"], got[0]
            assert why in got[0]["detail"] and "§3.5" in got[0]["detail"], got[0]


def test_f43_wired_api_with_list_form_stays_silent() -> None:
    """正控：`adapters.api` 接线 + `categories.D` 锚定声明为**清单**形态（用户确认无
    描述）⇒ 合法一致态，不产行不产 WARN（新判据不得一律从严）。"""
    meta = dict(META)
    meta["categories"] = {"A": "skipped", "H": "covered",
                          "D": "清单（用户确认无机器可读描述）"}
    with _tmp() as td:
        root = Path(td)
        mk(root, meta=meta, profile=PROFILE_WIRED_API)
        v = vst.validate(root)
        assert not _wire_warns(v), v.warns


def test_f43_wired_api_with_gaps_registration_warns() -> None:
    """`adapter_gaps` 登记了 `api`（接线前置未满足）而 profile 仍接线 ⇒ 同为混写，WARN。
    与 F42 的缺口可见性并存：两条 WARN 触发面不同（登记可见 / 接线态矛盾），不互相掩盖。"""
    meta = dict(META)
    meta["adapter_gaps"] = {"api": "0 items（桩检查未识别 .tsx 调用点）"}
    with _tmp() as td:
        root = Path(td)
        mk(root, meta=meta, profile=PROFILE_WIRED_API)
        v = vst.validate(root)
        got = _wire_warns(v)
        assert got and "adapter_gaps" in got[0]["detail"], v.warns
        assert [w for w in v.warns if w["check"] == "适配器缺口"], "F42 的缺口 WARN 必须仍在"
        assert v.ok, "WARN 不置红"


def test_f43_prose_mention_undeclared_and_missing_profile_stay_silent() -> None:
    """F38 同族三侧静默：① 散文提及「指针」不算声明（锚定判据）；② `adapters.api`
    未声明（null）时指针形态是合法降级；③ profile 缺失⇒不产行（profile 合法性
    归 validate_stack_profile，本器不重复告警、不假红）。"""
    meta_prose = dict(META)
    meta_prose["categories"] = {"A": "skipped", "H": "covered",
                                "D": "指针与否未定：用户没来得及答"}
    with _tmp() as td:
        root = Path(td)
        mk(root, meta=meta_prose, profile=PROFILE_WIRED_API)
        assert not _wire_warns(vst.validate(root)), "散文提及 ≠ 声明（F38 口径）"

    meta_pointer = dict(META)
    meta_pointer["categories"] = {"A": "skipped", "H": "covered",
                                  "D": "指针（网关文档站）"}
    meta_pointer["adapter_gaps"] = {}
    profile_null_api = PROFILE_WIRED_API.replace("  api: api_adapter\n", "  api: null\n")
    with _tmp() as td:
        root = Path(td)
        mk(root, meta=meta_pointer, profile=profile_null_api)
        assert not _wire_warns(vst.validate(root)), "api=null + 指针形态 ⇒ 合法降级"

    with _tmp() as td:
        root = Path(td)
        mk(root, meta=meta_pointer)   # 无 profile
        assert not _wire_warns(vst.validate(root)), "profile 缺失 ⇒ 不产行"


# ---------------------------------------------------- F44：D 形态指针判据锚定化

LIST_APIS_WITH_PROSE = """# demo 接口

| 方法 | 路径 | 用途 | 请求要点 | 响应要点 | 来源模块 |
|---|---|---|---|---|---|
| POST | /echo | 夹具端点 | — | — | backend |

## 语义说明

本域接口的真相源由网关维护，本表只收客户端调用点；网关文档不在仓内。
"""


def test_f44_list_form_prose_mention_of_zhenxiangyuan_not_flagged() -> None:
    """F44（2026-10-15）：清单型 `apis.md` 的语义段**提到**「真相源」⇒ 不得判「清单与
    指针混写」FAIL。旧判据是无锚定全文子串（issue #6 同族疾病在 D 形态残留）。
    变异证明（M66）：`is_pointer` 退回全文子串 ⇒ 本用例红（假 FAIL 复活）。"""
    with _tmp() as td:
        root = Path(td)
        mk(root, apis=LIST_APIS_WITH_PROSE)
        res = _res(root)
        assert res["D 形态"]["ok"] is True, res["D 形态"]


def test_f44_anchored_pointer_still_detected_both_sides() -> None:
    """锚定判据两侧都不松：①行首 `真相源：` 仍是指针形态（夹具基线即此形态）；②
    清单表 + 声明位指针条目（表格单元格首 `真相源：`）仍判**混写 FAIL**（fail-closed
    不放宽——真混写必须咬）；③无表且无锚定声明 ⇒ 「既非清单也非指针」照 FAIL。"""
    # ① 基线指针文件（APIS_POINTER = `真相源：…` 行首声明）通过既有基线用例覆盖。
    with _tmp() as td:
        root = Path(td)
        mk(root)  # baseline: pointer form passes
        assert _res(root)["D 形态"]["ok"] is True

    # ② 清单表 + 声明位指针 = 真混写 ⇒ FAIL
    with _tmp() as td:
        root = Path(td)
        mk(root, apis=LIST_APIS_WITH_PROSE.replace(
            "本域接口的真相源由网关维护，本表只收客户端调用点；网关文档不在仓内。",
            "| — | OpenAPI: 网关描述 | 真相源：网关文档站 |  |  | web |"))
        res = _res(root)
        assert res["D 形态"]["ok"] is False, "真混写必须仍咬（fail-closed 不放宽）"
        assert "混写" in res["D 形态"]["detail"], res["D 形态"]

    # ③ 无表、无锚定声明（提及也不在声明位）⇒ 既非清单也非指针
    with _tmp() as td:
        root = Path(td)
        mk(root, apis="# demo 接口\n\n有人提到接口的真相源在别处，但本文件什么形态都不是。\n")
        res = _res(root)
        assert res["D 形态"]["ok"] is False


def test_truth_carriers_validation() -> None:
    """issue #25：truth_carriers 事实载体声明，文件存在且非空 PASS，不存在或空 FAIL。"""
    meta_good = dict(META)
    meta_good["truth_carriers"] = {
        "quickstart": "AGENTS.md",
        "H": "docs/test.md"
    }
    with _tmp() as td:
        root = Path(td)
        mk(root, meta=meta_good)
        (root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
        (root / "docs").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "test.md").write_text("# Test Guide\n", encoding="utf-8")
        res = _res(root)
        assert res["类别覆盖 · 事实载体"]["ok"] is True

    # 坏输入：文件不存在
    with _tmp() as td:
        root = Path(td)
        mk(root, meta=meta_good)
        res = _res(root)
        assert res["类别覆盖 · 事实载体"]["ok"] is False
        assert "不存在" in res["类别覆盖 · 事实载体"]["detail"]
