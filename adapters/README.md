# atlas adapters —— 编写指南

> 适配器是 atlas 里**唯一允许认识具体技术栈**的地方（全局规则 §1：核心 / `shared/` / `rings/` / `templates/` / `validators/` 不得出现框架名）。
> 字段与调用契约的**正文唯一落在** [`../shared/stack-profile.md`](../shared/stack-profile.md) §3；本文件只讲**怎么加一个适配器**。

## 1. 什么时候需要适配器

`product/stack-profile.yaml` 的 `adapters.<category>` 声明一个适配器名；目标项目的技术栈能被某个适配器解析时，对应结构事实类别就**自动抽取**。

- 声明 `null` ⇒ 该类别**降级为 agent 撰写**（设计内行为，不是 bug）；`validate_stack_profile.py` 只对 `null` 判 OK。
- 现有 4 个类别：`routes` / `api` / `models` / `tests`（各对应 structure 的 C / D / E / H 类；F 设计 token 已退役删除，2026-09-30）。
- **没有对应适配器的栈**：由 agent 阅读代码撰写事实，并在结构基线标 `maintained_by: agent`。

## 2. 加一个适配器

1. **复制脚手架**：`cp _scaffold.py <category>.py`（`<category>` 用**通用类目名**，如 `routes` / `models`；**不要**用框架名当文件名——框架识别收在脚本**内部**，决策 D39/B11）。
2. **填三处**：`CATEGORY`、`DEFAULT_GLOBS`（按栈收窄）、`extract()`（把文件解析成 `items[]`）。
3. **每条 item 必须带 `source_file`**（项目根相对）——事实区自动渲染靠它做「表/模块 → 域」归属（`refresh_structure.py`，决策 D69/H2）。
4. **声明**：把适配器名写进目标项目 `product/stack-profile.yaml` 的 `adapters.<category>`（改写 profile 属**确认门**动作）。
5. **装配**：`install.sh` 会把 `adapters/` 整目录装到 `<目标>/.atlas/adapters/`；`shared/stack-profile.md` §3.3 的解析顺序：`.atlas/adapters/<名>` → `.atlas/adapters/<名>.py` → 目标项目根同名可执行文件。
6. **测试**：放 `<仓库>/atlas/tests/test_<category>_adapter.py`，覆盖「抽取正确 + 幂等 + 失败不产半成品」。

## 3. 契约要点（详见 `shared/stack-profile.md` §3）

- 调用：`<adapter> --root <项目根> [--app <name>] --out <json>`。
  - `--root` 传**项目根**（`source_file` 用项目根相对路径）；`--app` 传 `apps[].name` 过滤。
  - **域级类别**（`api` / `models` / `tests`）由调用方**按 app 各调一次**再合并；**全局类别**（`routes`）整项目调一次。
- 输出：`{"category", "items": [...], "source_files": [...], "adapter_version"}`；每类 `items[]` 字段见契约 §3.2。
- **只读**代码；**幂等**（同输入同输出）；失败**非零退出**且**不产半成品**；**不写文档**（渲染进 `atlas:facts` 区由 `refresh_structure.py` 完成）。
- D 类（接口）**条件形态**：项目自带机器可读描述（OpenAPI / Swagger / SDL / proto）时**不产 `items`**，改产 `{category:"api", spec_entry:"…", source_files:[…]}`（契约 §3.5）——自动渲染会把它落 `global/apis-shared.md` 作「真相源入口」。

## 4. 归属与合并（自动渲染侧）

- 适配器**不认产品域**（域是产品概念，不是代码概念）：事实区由 `refresh_structure.py --apply` 按 `source_file` → app → role → 域 → globs（最长命中）自动归属；无域命中落 `global/{apis,data-models}-shared.md`（决策 D69/H2）。
- 语义列（用途 / 关键交互 / 请求要点…）由 agent 维护，**自动渲染按行键保留**，不被覆盖。
