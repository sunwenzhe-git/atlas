# L1 · 结构抽取适配器子系统

> 子系统 #3 / 上级地图:[index.md](index.md) / 锚定版本:v0.2.0-beta.6(2026-10-25 复核)
> 一句话:**从业务代码确定性抽取路由 / API / 模型 / 测试四类事实**,渲染进结构事实区;只读、幂等、失败零部分产物,是实然侧的唯一入口。

## 它不是什么

- 不做语义判断:抽的是确定性事实(有这条路由、有这张表),「用途 / 关键交互」等语义列归人(`rings/structure/reference.md` 规程)。
- 不是代码图谱:`adapters/_graph.py` 归子系统 #4,不被 `adapters` 段解析。
- 不回写业务代码:只读源码、产物落 `.adapter-out/`(项目根,运行态不入库)。

## 文件清单

| 文件 | 行数 | 角色 |
|---|---|---|
| `adapters/routes.py` | 781 | 路由适配器:文件式路由 + `pyxle_route`(`adapters/routes.py:120`)的 JSX `<Route>` 两种形态,`load_apps`(`adapters/routes.py:71`)解析 apps 段并合成挂载前缀 |
| `adapters/api.py` | 248 | API 适配器:OpenAPI/Swagger 描述文件(`DESCRIPTOR_FILES`,`adapters/api.py:41`)+ FastAPI/JS 路由装饰器正则双通道 |
| `adapters/models.py` | 616 | 模型适配器:AST 解析(`_index_columns`,`adapters/models.py:134`),SQLModel 式含继承字段合并 |
| `adapters/tests.py` | 179 | 测试盘点适配器:`PY_TEST_RE` / `JS_TEST_RE`(`adapters/tests.py:38`)识别 pytest / Playwright / vitest 与各自配置、运行命令 |
| `adapters/_lib.py` | 132 | 适配器共享件:文件遍历 / apps 解析 / `write_json`(`adapters/_lib.py:84`)落盘约定 |
| `adapters/_scaffold.py` | 80 | 新适配器脚手架:`CATEGORY`(`adapters/_scaffold.py:25`)占位待改 |
| `scripts/refresh_structure.py` | 797 | 事实渲染器:适配器产物 → `atlas:facts` 标记区 |

## 核心机制

### 1. 统一适配器契约

每件适配器声明 `ADAPTER` / `VERSION`(`adapters/routes.py:35`),输出 JSON 一律 `{category, items, source_files, adapter_version}`;失败非零退出且零部分产物。启用由 `product/stack-profile.yaml` 的 `adapters` 段声明,未声明 = 不启用(不是失败)。

### 2. 事实渲染:标记区内键级重写(`scripts/refresh_structure.py`)

`BEGIN` / `END`(`scripts/refresh_structure.py:41`)框出 `atlas:facts` 标记区:区内键级单元格按适配器产物重写,区外语义内容原样保留;旧行按行键对齐(`old_rows_by_key`,`scripts/refresh_structure.py:280`),三张表头(`ROUTES_HEADER`,`scripts/refresh_structure.py:202`)对 routes / api / models 各定义列序。默认 dry-run,`--apply` 写盘;预算按每域 L1+L2 ≤ `DEFAULT_MAX_TOTAL`(`scripts/refresh_structure.py:43`,9500 字符)校验。单遍化(F27):事实区先行落盘、指针层后拼装,首遍 `--apply` 即完整。

### 3. 键级漂移检测

渲染时对既有事实表做键级对比,新增/消失的行键落 `.adapter-out/_drift.json` + `_drift-history.jsonl`,由 atlas_check「结构漂移」门读出 WARN——**适配器只负责发现,门负责可见**。

### 4. 链式收口 `--chain`(F25)

`--chain` 先按声明自动执行非空适配器(全局 routes 跑一次;域级 api/models/tests 按 apps 各跑一次),后做事实刷新。失败语义:任一适配器非零 / 声明了名字却解析不到脚本 ⇒ 中止链条不进 refresh,exit 2;已落盘产物 = 上一轮一致态,无害残留。

### 5. 基线自进(F26,只随 `--chain`)

`--chain` 完成后四前置全满足才推进 `_meta.json` 的 `baseline.commit`:① 读本轮刚算出的漂移结果(不读上轮遗留);② 无键级漂移;③ 至少一份非空适配器产物(空转态不背书);④ 产品侧工作树干净(给未审定代码背书违背诚实 ratchet)。任一不满足 ⇒ SKIP 带理由;显式 `--apply` 永不推进基线。

## 对外接口(谁咬它)

| 消费方 | 触点 |
|---|---|
| `apply adopt` | 开户第一步 = structure 全量(适配器 + 渲染) |
| `validate_structure` | 判产物形态与语义列留空 WARN;D 类接线态跨 profile 对账 |
| atlas_check 结构漂移门 | 只读 `_drift.json`,不做二次判定 |
| 代码图谱(可选) | 同为实然抽取面,但互不依赖(图谱查调用边,适配器抽声明事实) |

## 显式盲区

- 语义列(用途/关键交互/实现状态)是否写对,机器不判(留空才 WARN)。
- 覆盖有缺口:未接线的类别经 `_meta.json` 的 `adapter_gaps` 可见化(F42:未接 ≠ 缺陷,但必须可见)。
- 形态按实测栈收窄:TS/JSX 值域、SQLModel 式继承都是「实测过的栈才支持」,非泛化解析器。

## 演化锚

| 决策/事实 | 内容 |
|---|---|
| D42 | 适配器口径窄化:确定性事实,不做语义 |
| issue #8(2026-10-15) | 中间产物统一落项目根 `.adapter-out/` |
| F25/F26(2026-10-15) | `--chain` 链式收口 + 基线自进四前置 |
| D133(#40,2026-10-23) | 适配器侧缺陷修复批 |
| 实测扩面 | routes 两种形态合成挂载前缀,19 → 52 条(v2 前端试跑) |

## 讲述时的三个抓手

1. **实然侧只有这一个入口**:业务代码 → 事实的全部通道在这四件里,口径统一、失败响亮。
2. **发现与可见分层**:漂移由适配器发现、由门可见——每个部件只做自己那层。
3. **基线是诚实 ratchet**:四前置挡住「拿未审代码给自己背书」,自进不是自动放行。
