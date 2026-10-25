# Atlas 实现地图(创造者版)

> **读者**:造 Atlas 的人(创造者与后续演化者)。面向**用** Atlas 的人请走 `docs/guide/`。**本目录不进公开站点**(VitePress `srcExclude`,2026-10-25 拍板:私有);文中决策编号(D/M/F 系列)的流水见 `shared/gates.md` 与 `DESIGN.md`。
> **锚定版本**:v0.2.0-beta.7(2026-10-24;2026-10-25 复核)。文中行号以该版本为准,文件路径为仓根相对路径。
> **维护纪律**:每次发版时刷新本目录;引用的文件路径与行号锚由 `tests/test_map_anchors.py` 机器校验(锚存活性门,M151–M154);本图只写「现在是什么」,「为什么这么设计」归 `shared/gates.md` / `DESIGN.md` / 决策编号流水。
> **章节预算**(2026-10-25 拍板):每章 ≤120 行、核心机制 4~7 条、file:line 锚 ≤20 个、演化锚 ≤8 行——锚数即门禁成本,预算是「讲述够用、维护可控」的硬边界。

## 一页看懂:主数据流

```
业务代码 ──► 适配器抽取(adapters/) ──► 结构事实(.trellis/spec/structure/)
                                               │
Trellis 需求卡(.trellis/tasks/<ID>/prd.md)     │
        │                                      │
        ▼                                      ▼
   apply 跨环编排(apply/reference.md)──────────┘
        │  影响面推导(可调代码图谱 impact_report)
        ▼
   PRD 资产(product/prd/)──AC──► E2E 用例分片(product/e2e/cases/)
        │
        ▼
   生成器(gen_e2e_scripts.py)
        │
        ▼
   Playwright 脚本(product/e2e/scripts/)──► E2E 控制台(e2e_console.py)
        │
        ▼
   门禁编排(atlas_check.py)──► 全绿 ⇒ 域收口(closeout)
```

实现之前资产先行(应然),实现之后事实回写(实然);所有平面靠机器门对账。

## 子系统清单

| # | 子系统 | 一句话职责 | 入口 | L1 页 |
|---|---|---|---|---|
| 0 | 共享内核 | 全包单源的解析/复用实现,禁止就地复制 | `_support/`(8 件) | — |
| 1 | CLI 与装配 | 把 atlas 装进目标仓库并保持副本与源包对账 | `bin/atlas.js`、`install.sh` | [cli.md](cli.md) |
| 2 | 共享契约层 | 一切规则的真相源(门册/全局规则/布局/单源) | `shared/`(7 份)、`templates/` | — |
| 3 | 结构抽取适配器 | 从业务代码确定性抽取路由/API/模型/测试事实 | `adapters/`、`scripts/refresh_structure.py` | [adapters.md](adapters.md) |
| 4 | 代码图谱 | 外部图谱后端的唯一隔离层 + 影响面报告与对账 | `adapters/_graph.py` | [graph.md](graph.md) |
| 5 | 三环资产引擎 | structure / prd / e2e 三环的环内规程契约 | `rings/*/reference.md`、`skills/atlas-*` | — |
| 6 | apply 跨环编排 | 唯一编排件:需求 → 资产增量的四模式 | `apply/reference.md` | [apply.md](apply.md) |
| 7 | E2E 生成与控制台 | 用例分片 → Playwright 脚本 + 慢动作评审台 | `scripts/gen_e2e_scripts.py`、`scripts/e2e_console.py` | [e2egen.md](e2egen.md) |
| 8 | 门禁与校验 | 10 校验器 + 编排器 + 门册 + 变异证明 | `scripts/atlas_check.py`、`validators/` | [gates.md](gates.md) |
| 9 | 评审与收口 | 独立审查产物链 + 收口触发派生 | `shared/independent-review.md`、`scripts/closeout_derive.py` | [review.md](review.md) |
| 10 | 运营面 | 每日巡检 / 自感知上报 / 发版 | `duty-review/`、`scripts/atlas_report.py` | — |

## 各子系统速览

### 0. 共享内核 `_support/`

全包只准存在一处的实现:profile/用例块解析(`_support/stack_profile.py`、`case_block.py`)、Playwright 运行器探测与修复(`_support/pw_runner.py`)、审查策略(`_support/review_policy.py`)、URL 合并(`_support/url_merge.py`)、用例 ID 文法(`_support/case_id.py`)等 8 件。消费者经 `_support/siblings.py::load_module` 取用;`tests/test_shared_kernel.py` 守卫「同名实现全包唯一」。历史教训:就地复制导致判据分叉(双端同错 ⇒ 门恒绿),故有此层。

### 1. CLI 与装配

- `bin/atlas.js`(320 行):命令面 = `init / update / upgrade / check / console / report / version`。`init` 先探测 Trellis(`.trellis/` 缺失时自动 `trellis init`)再调装配器。
- `install.sh`(580 行):装配器。把 `shared/ rings/ apply/ scripts/ templates/ adapters/ validators/ patches/ tests/ _support/` 等白名单目录拷入目标仓 `<target>/.atlas/`,落 `.atlas/VERSION`(内容摘要戳)+ `.atlas/MANIFEST.json`(逐文件基线);`--update` 刷新、`--dry-run` 干跑零落盘;自带 54 条 `check` 自检声明。
- `patches/`(4 族):`workflow-plan-apply`(apply 挂进 Trellis 工作流)、`project-wiring`(AGENTS.md 指针 / after_finish hook / pytest 兜底 / `.gitignore` 追加 `.adapter-out/` / pi 扩展五触点)、`workflow-root-cause`、`workflow-skill-routing`。锚点式版本化补丁,可重放。
- 对账:`scripts/pkg_digest.py`(摘要算法单点)+ `scripts/backflow.py`(副本⇔源包三态回灌,SOURCE_ONLY 拒绝护栏)。

### 2. 共享契约层 `shared/`

七份 markdown 是对应机器面的真相源:`gates.md`(门登记总账)、`global-rules.md`(跨项目无框架名/确认门/退役三件套等元规则)、`stack-profile.md`(项目声明 schema)、`layout.md`(产物落点)、`single-source.md`(单一真相源纪律)、`independent-review.md`(独立审查契约)、`closeout.md`(收口触发表)。`tests/test_canonical_consistency.py` 守卫契约间互引与计数自洽。**改机器判据必同步改这里的契约正文**——这是「契约 ⇄ 实现」对账平面的源侧。

### 3. 结构抽取适配器 `adapters/` + `scripts/refresh_structure.py`

- 适配器四件:`routes.py` / `api.py` / `models.py` / `tests.py`,由 `product/stack-profile.yaml` 的 `adapters` 段声明启用。统一契约:只读、幂等、失败非零且零部分产物、输出 JSON 形如 `{category, items, source_files, adapter_version}`,落 `.adapter-out/`(项目根,运行态不入库)。
- `_lib.py` / `_scaffold.py` 是共享件;`_graph.py` 不是适配器(归子系统 4)。
- `scripts/refresh_structure.py`(797 行)把适配器产物渲染进 `.trellis/spec/structure/` 的 `atlas:facts` 标记区:键级单元格重写、语义列保留、键级增删落漂移标记 `.adapter-out/_drift.json`(由「结构漂移」门消费)。

### 4. 代码图谱 → [graph.md](graph.md)

### 5. 三环资产引擎 `rings/`

三份 `reference.md` 分别是 structure / prd / e2e 环的规程契约(环内逻辑的唯一正文);`skills/atlas-{structure,prd,e2e}` 是给 agent 的执行入口(skill 薄桩引用契约,不复制正文)。环产出:structure → `.trellis/spec/structure/`;prd → `product/prd/`(全局 prd.md + 域级 `<domain>-prd.md`);e2e → `product/e2e/e2e-index.md` + `cases/` 分片。原型环已退役(E1)。

### 6. apply 跨环编排 → [apply.md](apply.md)

### 7. E2E 生成与控制台

- `scripts/gen_e2e_scripts.py`(2383 行,全仓最大单件):用例分片(中文 DSL)编译为 Playwright `.spec.ts`。动词值域封闭(`click/hover/type/dispatch/…`,第三词即中止——治旧副本静默吸收陌生动词);登录形态三态(real/fabricated/none);独立审查有 Critical 拒绝写盘;前置未声明 ⇒ exit 3 `not_ready`。
- `scripts/gen_testid_stub.py`:老页面 testid 实然盘点薄桩(adopt 开户交尾件;缺失由 validate_testids 自愈)。
- `scripts/e2e_console.py`(1084 行):纯标准库 SSE 评审控制台(默认 `127.0.0.1:4190`),500ms 慢动作回放、逐用例三值走查、提交即解锁人工 Review、快照带评审指纹(prov: head_sha/scripts_hash)防旧账本挂新执行。
- 配套内核:`_support/pw_runner.py`(运行器可解析性判据 + 全局兜底 + 浏览器就绪探针)、`_support/url_merge.py`(base query 转发)、`_support/case_block.py` / `case_id.py` / `manual_block.py`。

### 8. 门禁与校验 → [gates.md](gates.md)

### 9. 评审与收口

- 契约:`shared/independent-review.md`(实例 ⑤ 独立审查:独立进程只读 diff 审查,「应审 N / 实审 M」对账)+ `shared/closeout.md`(收口触发表,唯一真相源)。
- 脚本链:`scripts/make_review_inputs.py`(造审查输入)→ 审查器(`agents/atlas-reviewer.md` 定义审查 agent)→ `scripts/cli_review_convert.py`(CLI 输出 ⇔ review.json 契约 + N/M 对账)→ `scripts/validate_review_report.py`(报告落盘形态门)。
- `scripts/closeout_derive.py`:按本轮 git diff 派生收口必跑步骤(触发表路径族匹配;表是真相源,派生器只解析)。

### 10. 运营面

- `duty-review/`:每日巡检(README 协议 + QUEUE 三区队列 + `bugs.md` 按环分类存量库 + `families.py` 分型);`scripts/duty_signals.sh` 只读收集五信号源。
- `scripts/atlas_report.py`:§15 自感知上报(四段式零业务上下文,`--trigger user` 不冒充自动感知)。
- `scripts/release.py` + `skills/atlas-release`:发版流程(版本串四处落点 + npm prerelease tag 纪律)。

## 数字快照(v0.2.0-beta.7)

| 量 | 值 | 出处 |
|---|---|---|
| 校验器 | 10(`atlas_check.VALIDATORS`) | `scripts/atlas_check.py:52` |
| 编排门行 | 8 类(validators / 对齐测试 / 生成物 / 审查报告 / 执行串行 / 结构漂移 / 装配版本 / 写面残留 + E2E 真跑) | `main()`(`scripts/atlas_check.py:816`) |
| 出厂测试文件 | 38 | `tests/` |
| skills | 8(含 frontend-design) | `skills/` |
| 环 | 3(structure / prd / e2e;原型环 E1 已退役) | `rings/` |
| 共享契约 | 7 份 | `shared/` |
| 共享内核 | 8 件 | `_support/` |
| install.sh 自检声明 | 54 条 | `install.sh` |
| 最大单件 | `scripts/gen_e2e_scripts.py` 2383 行 | — |

## L1 铺设计划(2026-10-25 定稿)

| 子系统 | 状态 |
|---|---|
| 代码图谱 / apply / 门禁与校验 | ✅ [graph.md](graph.md) / [apply.md](apply.md) / [gates.md](gates.md) |
| 结构抽取适配器 | ✅ [adapters.md](adapters.md) |
| E2E 生成与控制台 | ✅ [e2egen.md](e2egen.md) |
| CLI 与装配 | ✅ [cli.md](cli.md) |
| 评审与收口 | ✅ 薄章 [review.md](review.md) |
| 三环资产引擎 / 共享契约层 / 共享内核 / 运营面 | **不写 L1**(2026-10-25 拍板):正文即各环契约与 `shared/` 契约本体,写章必复制正文违反单一真相源;L0 速览 + 交互图详情页承担导航 |
