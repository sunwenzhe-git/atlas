# 项目级资产根可配置：`atlas.config.yaml` + 单一布局解析

> 提案编号：`RFC-20261026-01`
> 提案作者：（当前会话）
> 关联状态：已定案并实施验证 (Accepted；2026-10-26 用户按推荐拍板，独立评审 v1/v2 修后通过，终审通过；实现与 §7 回填完成，落 `DESIGN.md` D152)
> 影响范围：核心契约 (shared) | 环契约 (rings) | 校验器 (validators) | 脚本工具 (scripts) | 适配器 (adapters) | 模板 (templates) | Pi 扩展 (`extensions/pi.ts`) | 版本装配 (install.sh) | CLI (`bin/atlas.js`)
> 关联 issue：[#42](https://github.com/sunwenzhe-git/atlas/issues/42)（ADR 目录硬编码；本提案把单点问题上升为资产根布局配置）

> **v2 修订（2026-10-26，独立评审「修后通过」）**：补齐模板渲染 / `extensions/pi.ts` / `refresh_structure` 脏树豁免 / `make_review_inputs` 默认路径 / `install.sh` 既有 `.atlas` 硬停与零写预检 / 写侧模板字面量 / 配置边界（version、重复键、symlink、路径逃逸）/ 守恒测试的多语言覆盖。v1 的核心定案不变。

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

**① 项目级资产根写死，存量项目无法沿用既有文档布局**

* **规则 / 环节**：`validators/validate_adr.py` 的 `ADR_DIR_RELPATH`、`scripts/atlas_check.py` 的 `_GATE_PRECONDITIONS`、`_support/stack_profile.py` 的 profile 定位、`install.sh` 的骨架创建，均把项目级资产根固定为 `product/`。
* **触发时机**：存量项目已有独立文档规范，明确 ADR / PRD / E2E 的唯一目录不在 `product/` 下，执行 `atlas check` 或 `atlas init` 时。
* **具体行为**：Atlas 的 ADR 门看不到项目权威 ADR（无 `product/adr/` ⇒ `SKIP`）；Agent 按 `shared/independent-review.md` / `skills/atlas-design-review/SKILL.md` 仍写 `product/adr/` ⇒ 「项目单一真相源」与「Atlas 资产根」形成双源。改 `.atlas/` 副本不可持续：它是包产物，`install.sh --update` 会整包覆盖，且默认不入项目版本管理。

**② 只改校验器不够：模板、宿主扩展、写侧仍在写死 `product/`**

* **模板与 profile**：`templates/stack-profile.yaml:49-51` 的 `cases_dir` / `index` / `scripts_dir` 默认写 `product/e2e/...`；`install.sh:291` 原样复制该模板；`gen_e2e_scripts.py:1353,1361,1391,1731` **优先读 profile 值**、缺失才回退 `product/e2e/...`。只改解析器，生成器仍按 profile 里的 `product` 走。
* **宿主扩展**：`extensions/pi.ts:50,54,109,116` 用 `product/stack-profile.yaml` 与 `product/prd/prd.md` 判定开户态；自定义根会被误判为「未开户」，并继续提示 `product/prd`。
* **写侧**：`templates/prd/global.md:12,18`、`templates/prd/domain.md:15,153`、`templates/e2e/console/app.js:82,367`、`templates/e2e/console/index.html:23,68`、`skills/frontend-design/SKILL.md:129,389`、`skills/frontend-design/references/tuning-verbs.md:5`、`RUNBOOK.md:44` 仍把 `product/` 当唯一定点。
* **既有旧产物逻辑**：`scripts/refresh_structure.py:51` 的 `CLEAN_EXEMPT_PREFIXES` 只豁免 `product/`；自定义根后 Atlas 自己写的资产会被判成「产品侧有未提交改动」，基线自进永久冻结。`scripts/make_review_inputs.py:28` 的 `DEFAULTS` 同样写死 `product/e2e|prd`。

**③ 装配语义与「首次选择」冲突**

* `install.sh:118` 在目标已有 `.atlas/` 时**硬停**（除非 `--update` 或 `ATLAS_ALLOW_OVERWRITE=1`）。因此「重复 `atlas init` 不重新提示」不成立——v1 RFC 草案把它写成测试步骤是错误的；正确行为是首次 `init` 选根，之后刷新走 `atlas update`。
* `install.sh --update` 目前没有「先校验布局配置再覆盖」的次序；非法配置若先刷新 `.atlas/`，会把包换成新版本、项目资产根却仍不可解析，留下半态。
* 首次安装若目标已有 `product/stack-profile.yaml` 而用户选了 `docs`，直接建骨架会形成双根；必须在写盘前预检并拒绝。

**④ 单点补 ADR 目录不是完整解**

* `product/` 是 `stack-profile.yaml` / `prd/` / `e2e/` / `design.md` / `reviews/` / `atlas-reports/` 的共同根；只把 ADR 改成 `docs/adr` 会形成「半自定义」，`closeout_derive`、控制台、执行器、审查输入生成器各自维护前缀，后续每加一个资产就再加一个配置键。

### 1.2 客观证据（仓库侧，可直接复现）

```text
validators/validate_adr.py:33          ADR_DIR_RELPATH = Path("product") / "adr"
scripts/atlas_check.py:88-90           "validate_adr": ("product/adr", "前置未声明…")
scripts/atlas_check.py:253,339,593     执行串行 / 审查报告 / E2E 真跑写死 product/e2e
_support/stack_profile.py:2            """… product/stack-profile.yaml 单源解析器。"""
install.sh:282-292                     建 product/e2e/cases、落 product/stack-profile.yaml
install.sh:463-465                     check product/stack-profile、product/e2e/cases
templates/stack-profile.yaml:49-51     cases_dir/index/scripts_dir = product/e2e/...
scripts/gen_e2e_scripts.py:1353,1361,1391,1731  profile 优先 / 回退 product/e2e
extensions/pi.ts:50,54,109,116         开户检测 / 提示写死 product
scripts/make_review_inputs.py:28       DEFAULTS = product/e2e|prd
scripts/refresh_structure.py:51        CLEAN_EXEMPT_PREFIXES 含 "product/"
```

耦合面（2026-10-26 源包实测）：

* Python / Shell 生产侧 **21 个文件**出现 `root / "product"` 类路径构造：validators 10、scripts 7、adapters 4，共 58 处；另有 `product/` 字面量约 85 处（validators 22、scripts 57、adapters 4、`_support` 2，含注释 / 文档字符串与路径字符串，与前者有重叠）。
* 契约 / skill / apply / rings 文档中 `product/` 共 **131 行**引用（19 个文件）；`rings/e2e/reference.md` 37、`apply/reference.md` 15、`shared/single-source.md` 13、`shared/layout.md` 10。另有 templates / RUNBOOK / README / docs 的一批字面量，未计入这 131 行。
* **25 个测试文件**涉及 `product`，其中 14 个直接写 `product/` 路径。
* 未发现任何 `PRODUCT_ROOT` / `ATLAS_*PRODUCT` / CLI `--profile` / 环境变量形式的资产根覆盖入口。

issue #42 的「改 `docs/adr` 后聚焦测试 9 passed」不能直接采信为「改动很小」。隔离副本实测：只把 `ADR_DIR_RELPATH` 改为 `docs/adr`，`pytest tests/test_validate_adr.py -q` ⇒ **9 failed**——夹具与断言写死 `product/adr`（`tests/test_validate_adr.py:34`、`:68`）。若同时改了测试，应附完整 diff 与命令；本提案按「生产 + 模板 + 测试 + 契约都要动」估算改动面。

**⑤ 为什么现在提**

* `DESIGN.md:436` §11 明确支持 `origin: adopt` 存量接入；存量项目的既有文档布局是接入前提，不是边缘场景。
* `product/` 在 `shared/layout.md:15`、`shared/single-source.md:25` 被登记为项目级 ADR 单一真相源；它已经是契约，不是临时目录。把它做成可配置，属于框架级布局抽象，必须走 RFC。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

**总原则：项目根新增一个 git 跟踪的布局锚点 `atlas.config.yaml`；所有资产路径经 `_support/layout.py` 单一解析；缺省值保持 `product/`，存量项目零变化。**

**① 配置锚点与 schema**

项目根新增 `atlas.config.yaml`（可见文件，不是 `.atlas.config.yaml`，避免与包目录 `.atlas/` 混淆）：

```yaml
version: 1
layout:
  assets_root: product   # 文件存在时必填；项目相对 POSIX 路径；文件缺失时整体默认 product
  adr: docs/adr          # 可选；项目相对 POSIX 路径；缺省 <assets_root>/adr
```

* **为什么放项目根**：布局配置必须先于「资产根」被读到；`product/stack-profile.yaml` 在资产根内部，存在鸡生蛋问题；`.atlas/` 是包产物，会被 `install.sh --update` 刷新；`.trellis/config.yaml` 会被 `trellis update` 覆盖本地改动（`RUNBOOK.md:19`）。
* **文件缺失 vs 文件存在**：`atlas.config.yaml` 不存在 ⇒ 整体默认 `assets_root=product`、`adr=product/adr`（存量项目零变化）；文件存在 ⇒ `version` 与 `layout.assets_root` 必填，`adr` 可选。
* **`version: 1` 必须显式存在**：缺失 / 非整数 / 未知版本 ⇒ FAIL；后续 schema 演进不靠猜。
* **严格键空间**：只允许 `version` 与 `layout.assets_root` / `layout.adr`；未知键、重复键、非字符串 ⇒ FAIL，不静默忽略（防 `asset_root` 这类拼写错误把门悄悄关掉）。
* **路径规则（统一项目根相对 POSIX）**：`assets_root` 与 `adr` 都必须落在项目根内；拒绝绝对路径、`..`、`.`、空串、`.atlas` / `.trellis` / 项目根本身；解析后 `realpath` 仍须在项目根内（symlink 指向根外 ⇒ FAIL）；`assets_root` 若已存在必须是目录，不能是普通文件；`adr` 可以是 `assets_root` 之外的目录，但必须在项目根内。配置内统一 `/`，解析时归一。
* **命名**：用 `assets_root`，不用 `product_root`——`stack-profile.yaml` 已有 `product:` 字段表示**产品名**（`_support/stack_profile.py:21`），复用会撞语义。

**② 单一解析器 `_support/layout.py`**

新增随包内核模块，暴露：

* `load_layout(root: Path) -> Layout`：读 `atlas.config.yaml`；文件缺失 ⇒ 默认 `assets_root=product`、`adr=<assets_root>/adr`；文件非法 ⇒ 抛 `LayoutError`（响亮，不回落）。
* `Layout` 派生属性（v1 固定集合）：
  * `assets_root`
  * `stack_profile` = `<assets_root>/stack-profile.yaml`
  * `design` = `<assets_root>/design.md`
  * `prd_dir` = `<assets_root>/prd`
  * `e2e_dir` = `<assets_root>/e2e`
  * `adr_dir` = `layout.adr` 或 `<assets_root>/adr`
  * `reviews_dir` = `<assets_root>/reviews`
  * `reports_dir` = `<assets_root>/atlas-reports`
  * `e2e_index` / `e2e_cases_dir` / `e2e_scripts_dir` / `e2e_fixtures_dir` / `e2e_reviews_dir` / `console_ledger`（由 `e2e_dir` 派生）
* `layout.adr` **按项目根解析**，不按 `assets_root` 解析——这样 `assets_root=product` + `adr=docs/adr` 可用，直接回应 issue #42。
* 复用 `_support/stack_profile.py` 的 `strip_inline_comment` / `yaml_scalar`，不新造第二套 YAML 方言；重复键检测由 layout 解析器自己做。
* 提供只读 CLI 供 skill / Agent / 非 Python 消费者 / install.sh 调用：
  * 源包态：`python3 _support/layout.py --root <项目根> --print <assets_root|adr|prd|e2e|design|stack_profile|...>`
  * 装配态：`python3 .atlas/_support/layout.py ...`
  * `--validate`（安装前校验配置整体）、`--validate-value`（init 提示输入的单值校验）

**③ 消费面：机器门 + 写侧 + 模板 + 宿主扩展全部走解析器**

* 机器侧：10 个校验器、11 个 scripts、4 个 adapters、`_support` 2 个模块、`install.sh`、`patches/project-wiring/apply-wiring.py` 一律改为 `load_layout(root)`，禁止再出现 `root / "product"` 这类构造。
* 重点补漏（评审实测）：
  * `scripts/refresh_structure.py:51`：`CLEAN_EXEMPT_PREFIXES` 改为**运行时由 layout 派生**，至少包含 `assets_root/`、`adr_dir/`、`e2e_dir/`、`prd_dir/`、`design`、`reviews_dir/`、`reports_dir/`；否则自定义根会被自己的写盘判成脏。
  * `scripts/make_review_inputs.py:28`：`DEFAULTS` 改为 layout 派生（e2e-index / cases / prd 的 glob）。
  * `scripts/atlas_check.py:253,339,593`：执行串行、审查报告形态、E2E 真跑的路径全部走 layout。
  * `scripts/gen_e2e_scripts.py:1353,1361,1391,1731`：profile 定位与各路径回退全部走 layout；profile 里显式写的路径仍是项目相对路径、优先级不变。
  * `scripts/closeout_derive.py:69-71`：ADR / E2E / PRD 事件前缀改为 layout 派生；**`atlas.config.yaml` 变更登记为「契约」类事件**（不是「建议」），触发布局相关复核。
  * `extensions/pi.ts:50,54,109,116`：开户检测与提示改为调用 `python3 .atlas/_support/layout.py --print ...`（旧装配无 helper 或 python3 缺席 ⇒ 回退默认 `product` 并显式提示，不静默假装已开户）。
  * `templates/stack-profile.yaml:49-51`：改为 `{{ASSETS_ROOT}}` 占位；`install.sh:291` 渲染后写入；模板本身不再出现 `product/e2e/...` 字面量。
  * `templates/prd/global.md:12,18`、`templates/prd/domain.md:15,153`、`templates/e2e/console/app.js:82,367`、`templates/e2e/console/index.html:23,68`：改为占位符或运行时注入；控制台由 `e2e_console.py` 在 serve 时替换，PRD 模板由 apply / skill 按 layout 渲染。
  * `skills/frontend-design/SKILL.md:129,389`、`references/tuning-verbs.md:5`：设计档案路径改为「资产根 / design.md 由 `atlas.config.yaml` 解析」。
  * `RUNBOOK.md:44`、`README.md`、`docs/**`：安装说明与示例同步；示例可保留默认 `product/`，但首次出现处注明默认值与配置入口。
* `scripts/validate_review_report.py:22`、`scripts/cli_review_convert.py:16` 经核实仅 docstring 示例，不改代码；若示例仍含 `product/`，顺手改成 `<资产根>/...`。
* `bin/atlas.js:110,303` 仅帮助文案；改为「默认资产根」措辞，不承载路径解析。

**④ 模板与 profile 的一致性**

* 首次安装写 `stack-profile.yaml` 时，必须按 `assets_root` 渲染 `cases_dir` / `index` / `scripts_dir`（`templates/stack-profile.yaml` 用 `{{ASSETS_ROOT}}` 占位），避免「配置 `docs`、生成器按模板 `product` 走」。
* `gen_e2e_scripts` 的路径优先级不变：profile 显式值 > layout 派生默认值。profile 里的路径仍是**项目相对**，允许项目做混合布局（例如 `assets_root=product`、`e2e` 放 `docs/`）。
* 一致性巡检：若 `assets_root != product` 且 profile 的 e2e 三路径仍全部指向 `product/`，而配置根下已存在 e2e 目录 ⇒ **WARN** 指名「疑似模板未渲染 / 路径漂移」，不覆盖用户显式值；首版 WARN，有真实遗漏再升档。
* `atlas.config.yaml` 与 profile 的路径都按项目根解析；文档必须写清两者优先级，避免「配置一个、profile 一个」的第二真相源。

**⑤ init / update 行为边界（与现有 `install.sh` 硬停守卫对齐）**

* `atlas init`（判定次序固定）：
  1. **已有 `.atlas/`** ⇒ 沿用现有守卫 **exit 1**，提示改用 `atlas update`；无论是否带 `--assets-root` 都不在同一命令里换根。
  2. **无 `.atlas/`、已有 `atlas.config.yaml`** ⇒ 先 validate 该配置；`--assets-root` 与配置不一致 ⇒ exit 2；一致或未给 flag ⇒ 按配置建骨架。
  3. **无 `.atlas/`、无配置** ⇒ 首次安装：TTY 且未给 `--assets-root` 时询问一次
     `Atlas 项目级资产根目录（PRD / E2E / ADR 等）[product]:`
     回车 = `product`；说明「已有文件不会被覆盖」。非 TTY / 已给 flag ⇒ 用 flag 或默认 `product`。
  * `--assets-root <dir>` / `--adr-dir <dir>` 供非交互 / CI 使用。
  * 首次安装若所选根不是 `product`，且默认 `product/` 下已有任何 Atlas 资产（`stack-profile.yaml`、`prd/`、`e2e/`、`adr/`、`design.md`、`reviews/`、`atlas-reports/` 任一存在）⇒ **exit 2**（双根风险），零写；用户须先手工迁移或明确选择 `product`。
* `install.sh`：
  * 作为**唯一配置写入点**：首次安装（非 `--update`）且无配置时，按 flag / 默认值写 `atlas.config.yaml`；写前经 `_support/layout.py --validate` 校验，非法路径不落盘、不装配。**写配置先于建骨架**。
  * 对**生效配置**（既有或新写）一律先 `layout.py --validate`，再写任何文件；既有配置非法 ⇒ exit 2、零写。
  * `--update` **先校验配置再覆盖**：配置非法 ⇒ exit 2、零写；合法则只读配置，**绝不写配置、绝不提示**；无配置 ⇒ 默认 `product`（存量项目零变化）。
  * `--update` 时若 `--assets-root` 与现有配置不一致 ⇒ exit 2。
  * `templates/stack-profile.yaml` 按 `assets_root` 渲染；`install.sh:463-465` 的自检路径改为动态解析。
* **不支持运行中改根**：v1 不提供自动迁移。改根 = 手工移动资产 + 改配置；`atlas_check` 对「配置根与默认 `product/` 同时存在资产」给 WARN（首版不判红），点名双根与迁移出路。

**⑥ 门禁语义**

* 配置缺失 ⇒ 默认值，不新增门、不新增红。
* 配置非法 ⇒ `atlas_check` 新增一行 `项目布局配置` **FAIL**；依赖该布局的门不再各自重复报红（统一指名「布局配置无效，未执行」）。这不是新的语义判据，而是边界解析失败，FAIL 合理。
* 配置合法但目标目录缺失 / 为空 ⇒ 沿用现有三态 `SKIP`（ADR / design / e2e / prd 等前置未声明），不放宽、不伪红。
* 双根检测（配置根 ≠ `product` 且 `product/stack-profile.yaml` 存在；或 `layout.adr` 与 `<assets_root>/adr` 同时存在）⇒ **首版 WARN**，按「新判据先 WARN、有真实遗漏再升档」纪律处理。
* 模板 / profile 路径漂移（§④）⇒ 首版 WARN；不因 WARN 改写 profile。

**⑦ v1 边界**

* 只支持 `assets_root` + `adr` 两个可配置项；PRD / E2E / design / reviews / reports 默认由 `assets_root` 派生；e2e 三路径仍可在 `stack-profile.yaml` 显式覆盖（既有机制，不新增键）。
* `stack-profile.yaml` 在 v1 固定在 `<assets_root>/stack-profile.yaml`，不单独覆盖（引导锚点已归 `atlas.config.yaml`，后续有真实需求再加键）。
* 不自动探测 `docs/` / `doc/` / `spec/`——显式配置优先，避免猜测与误伤。
* 不把符号链接作为官方方案；仅允许路径解析后仍落在项目根内的 symlink。

### 2.2 考虑过的备选方案及否定理由 (Considered Alternatives)

* **备选 A：把 `layout` 放进 `product/stack-profile.yaml`**
  * *否定理由*：引导问题——要读 `stack-profile.yaml` 先得知道资产根；且 `stack-profile.yaml` 自身路径也可能需要被配置。
* **备选 B：放进 `.trellis/config.yaml`**
  * *否定理由*：跨工具耦合；`trellis update` 会覆盖本地改动（`RUNBOOK.md:19`）；Atlas 的 after_finish hook 也要靠重跑 install 恢复，不适合承载布局真相。
* **备选 C：只给环境变量 / CLI flag**
  * *否定理由*：不可随项目版本管理持久化；团队与 CI 各自设置会漂移；`atlas check` / 控制台 / 执行器多入口都要重复传参。
* **备选 D：自动探测 `docs/` 或 `product/`**
  * *否定理由*：隐式、歧义、误伤；两个目录同时存在时无判定依据；违背「显式契约优先」。
* **备选 E：项目内符号链接 `product -> docs`**
  * *否定理由*：Git 路径前缀消费者（`closeout_derive`）看到的是 `docs/...`，会漏触发；跨平台符号链接支持不一；隐藏魔法，排障成本高。只能作为临时现场手段，不进契约。
* **备选 F：只做 `layout.adr` 单点覆盖**
  * *否定理由*：只解 ADR，不解资产根；PRD / E2E / 控制台仍写死 `product/`；后续再加根配置会形成两套机制。
* **备选 G：直接全局把默认 `product/` 改名为 `docs/`**
  * *否定理由*：破坏全部存量项目与测试；迁移成本远大于配置抽象。
* **备选 H：每次 install / update 都提示用户选根**
  * *否定理由*：破坏 CI / Agent 自动化；update 必须只读，重复提示会导致换根与资产分裂。
* **备选 I：配置放 `.atlas/`**
  * *否定理由*：包产物会被整包刷新覆盖；默认不入项目版本管理，团队无法复现。
* **备选 J：改用 `atlas.config.json` 以便 `extensions/pi.ts` 直接解析**
  * *否定理由*：与 `stack-profile.yaml` 的 YAML 风格不一致、无注释；pi 扩展通过 `layout.py --print` 读取，仍保持单一解析。若未来去 Python 化再评估 JSON。
* **备选 K：生成 `.atlas/LAYOUT.json` 供非 Python 消费者读取**
  * *否定理由*：生成物与源配置可能漂移；用户改 `atlas.config.yaml` 后未跑 update 就会读到旧视图。helper CLI 是单源。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* **改动面大**：Python/Shell 生产侧 21 个文件、契约 131 行、25 个测试文件，另有 templates / extensions / docs；必须分阶段落地，不能一次性字符串替换。建议顺序：解析器 + 单测 → 机器消费者 → 模板 / 宿主扩展 → install/init UX → 写侧契约与 skill → 全量 + 真跑。每阶段保持默认 `product` 绿。
* **模板是最容易漏的第二真相源**：只改校验器不改 `templates/stack-profile.yaml`，新项目会生成 `product/e2e` 路径；必须渲染 + 一致性 WARN + 生成器测试三件套。
* **新配置面**：新增一个项目根文件与一类失败模式（非法路径、拼写错误、双根、profile 路径漂移）。用严格键空间 + `atlas_check` 单行 FAIL 收敛，不把解析错误散落到各门。
* **命名空间风险**：`docs/` 是通用文档区，Atlas 会在其下创建 `stack-profile.yaml`、`prd/`、`e2e/`、`reviews/`。若目标项目的 `docs/` 并非 Atlas 专用资产区，建议用 `docs/atlas/` 这类子目录，或只覆盖 `layout.adr`；文档需明确提示，避免把 Atlas 文件混入项目自由文档。
* **存量项目**：无配置 ⇒ 默认 `product`，行为不变；`update` 不写配置、不提示。只有显式创建配置或首次 `init --assets-root` 才进入新布局。
* **改根不可回滚**：v1 不支持自动迁移；配置根与既有资产不一致时只 WARN，不自动搬文件。回滚到旧版本时，自定义根项目会看不到资产——发布说明必须写明「先迁回 `product/` 再降级」。
* **既有 `.atlas` 守卫**：重复 `atlas init` 会 exit 1；这是既有安全语义，不在本 RFC 中放宽。用户首次选根后，后续刷新一律 `atlas update`。
* **Agent 写侧一致性**：只改机器门、不改 skill / 模板会造成「门看 `docs/`、Agent 写 `product/`」；因此 131 行契约与 templates 必须同批处理，至少把写侧定点改为解析后的路径。
* **旧包兼容**：旧版 Atlas 不认识 `atlas.config.yaml`，会继续按 `product/` 工作；使用自定义根的团队必须先升级 CLI / 重装配，再创建配置。文档需给出顺序。
* **测试策略**：现有默认夹具全部保持 `product/`，避免 25 个测试文件一次性重写；新增覆盖测试集中在解析器、`atlas_check`、`validate_adr`、`install.sh`、`closeout_derive`、`refresh_structure`、`make_review_inputs`、控制台/执行器/生成器各一个 override 冒烟。另加「生产代码不得绕过解析器」的守恒测试（AST + shell/TS 正则 + 白名单），防止后续新代码重新写死 `product/`。

---

## 3. 改动面清单 (Affected Surface)

- [ ] **新增内核**：
  - `_support/layout.py`（`Layout` / `load_layout` / 严格校验 / `--print` / `--validate` / `--validate-value`）
  - `install.sh` 自检新增 `_support/layout.py` 一条（`package.json.files` 已含 `_support`，无需改）
- [ ] **配置与装配**：
  - `install.sh`：首次安装写 `atlas.config.yaml`（flag / 默认 / 交互传入，写配置先于建骨架）；`--update` 先校验后覆盖、只读不写；骨架落点、stack-profile 渲染、自检清单（:463-465）、graph 探测全部走 `load_layout`；保留既有 `.atlas` 硬停守卫
  - `bin/atlas.js`：`init` 增加 `--assets-root` / `--adr-dir` 透传与首次 TTY 提示；帮助文案中的 `product/` 改为「默认资产根」
- [ ] **机器消费者（改为 `load_layout`）**：
  - validators：`validate_adr.py`、`validate_design_exemptions.py`、`validate_stack_profile.py`、`validate_structure.py`、`validate_prd.py`、`validate_e2e_index.py`、`validate_testids.py`、`validate_e2e_mocks.py`、`validate_ac_alignment.py`、`validate_walkthrough.py`
  - scripts：`atlas_check.py`（`_GATE_PRECONDITIONS` 运行时解析 + 布局配置行；:253/:339/:593）、`atlas_verify.py`、`e2e_console.py`、`gen_e2e_scripts.py`（:1353/:1361/:1391/:1731）、`make_review_inputs.py`（:28）、`closeout_derive.py`（:69-71 + 配置事件）、`refresh_structure.py`（:51 脏树豁免）、`atlas_report.py`、`gen_testid_stub.py`、`validate_review_report.py`（docstring only）、`cli_review_convert.py`（docstring only）
  - adapters：`routes.py`、`models.py`、`_lib.py`、`_graph.py`
  - `_support`：`stack_profile.py`（调用方传路径）、`pw_runner.py`
  - `patches/project-wiring/apply-wiring.py`
  - `extensions/pi.ts`：开户检测 / 提示走 `layout.py --print`，旧装配回退默认并提示
- [ ] **模板 / 写侧**：
  - `templates/stack-profile.yaml`（e2e 三路径改 `{{ASSETS_ROOT}}`，install 渲染）
  - `templates/prd/global.md`、`templates/prd/domain.md`、`templates/e2e/console/app.js`、`templates/e2e/console/index.html`（占位符 / 运行时注入）
  - `skills/atlas-design-review/SKILL.md`、`skills/atlas-apply/SKILL.md`、`skills/atlas-prd/SKILL.md`、`skills/atlas-e2e/SKILL.md`、`skills/atlas-structure/SKILL.md`、`skills/frontend-design/SKILL.md`、`skills/frontend-design/references/tuning-verbs.md`
  - `RUNBOOK.md`
- [ ] **契约 / 文档**：
  - `shared/layout.md`（定义 `<资产根>`、配置 schema、默认值、双根 / 路径漂移 WARN）、`shared/single-source.md`、`shared/gates.md`、`shared/independent-review.md`、`shared/global-rules.md`、`shared/closeout.md`、`shared/stack-profile.md`
  - `rings/prd/reference.md`、`rings/e2e/reference.md`、`rings/structure/reference.md`、`apply/reference.md`
  - `README.md`、`docs/design/*`、`docs/gates/*`、`docs/guide/*`、`docs/map/*`（生成物按发布流程重生成，不手改 dist）
- [ ] **测试防线**：
  - 新增 `tests/test_layout.py`：默认 / `assets_root=docs` / `adr=docs/adr` / 注释引号 / 未知键 / 重复键 / version 缺失与未知 / 绝对路径 / `..` / `.` / `.atlas` / `.trellis` / 项目根 / symlink 逃逸 / `assets_root` 是普通文件 / 双根 WARN
  - `tests/test_validate_adr.py`：保留 9 条默认用例；新增 override 用例（`atlas.config.yaml` + `docs/adr`）
  - `tests/test_atlas_check.py`：前置路径随配置；非法配置单行 FAIL；依赖门不重复红；双根 WARN；:253/:339/:593 对应的 override
  - `tests/test_install_selfcheck.py`：默认首装生成 `atlas.config.yaml` 与渲染后的 `stack-profile.yaml`；`--assets-root docs` 不建 `product/`；首装 `docs` 且 `product/prd/` 等任一既有资产存在 ⇒ exit 2 零写；无 `.atlas/` 但已有配置 `product` + `--assets-root docs` ⇒ exit 2；既有配置非法 ⇒ exit 2；`--update` 不写配置且保留自定义根；非法配置首装/更新零写
  - `tests/test_cli_commands.py`：`--assets-root` / `--adr-dir` 透传；非 TTY 默认；既有 `.atlas` exit 1；不同根 exit 2
  - `tests/test_closeout_derive.py`：ADR / E2E / PRD 事件前缀随配置；`atlas.config.yaml` 触发契约事件
  - `tests/test_refresh_facts.py`：`CLEAN_EXEMPT_PREFIXES` 随配置根，不再把 `docs/` 资产判脏
  - `tests/test_make_review_inputs.py`（若不存在则并入 `tests/test_tools.py`）：DEFAULTS 随配置
  - `tests/test_e2e_console.py` / `tests/test_atlas_verify.py` / `tests/test_gen_e2e_scripts.py`：各一条 override 冒烟；生成器断言不回到 `product/e2e`
  - `extensions/pi.ts`：若现有测试框架可覆盖，加一条「docs 配置下开户态 = done」；否则人工验收记录
  - 守恒测试：Python 用 AST 扫 `root / "product"` / `Path("product")` / f-string 中的 `product/` 路径构造（除 `_support/layout.py` 与显式白名单），shell/TS 用正则扫 `product/` 字面量（含 `extensions/`）；避免把 docstring / 示例误判
  - 全消费者 custom-root 冒烟矩阵：docs 根临时项目下逐一断言 10 validators + 11 scripts + 4 adapters + pi helper 的解析结果不含 `product/`（至少覆盖 `--print` / 解析入口 / `--help` 触达的路径）
  - 变异钉子（编号按当前最大 M 递增）：摘 `load_layout` 退回 `root/"product"` ⇒ override 测试红；摘非法配置 FAIL ⇒ 红；摘 update 零写预检 ⇒ 红；摘双根 WARN ⇒ 红；摘模板渲染 ⇒ 红；摘 pi helper / review-inputs / refresh 豁免 ⇒ 对应钉红；摘 version / symlink / `adr` 相对校验 ⇒ 红
- [ ] **版本装配**：`install.sh` 自检清单 +1；`.atlas/` 装配集新增 `_support/layout.py`（`_support` 已在拷贝列表，无需改包目录）；`package.json.files` 不变

---

## 4. 验证与测试结果 (Verification)

> 本稿为草案，**未实施**；以下为验收线，实测结果待实现后回填，不预填数字。

### 4.1 单元与集成

```bash
# 1. 解析器与默认兼容
pytest tests/test_layout.py tests/test_validate_adr.py tests/test_atlas_check.py

# 2. 装配 / CLI
pytest tests/test_install_selfcheck.py tests/test_cli_commands.py

# 3. 收口 / 脏树 / 审查输入 / 控制台 / 执行器 / 生成器
pytest tests/test_closeout_derive.py tests/test_refresh_facts.py tests/test_tools.py \
       tests/test_e2e_console.py tests/test_atlas_verify.py tests/test_gen_e2e_scripts.py

# 4. 出厂全量
pytest tests/ -q

# 5. 快速自检
python3 scripts/atlas_check.py --fast
```

### 4.2 真跑咬合（临时项目，非 mock）

1. `atlas init --target /tmp/atlas-layout-probe --assets-root docs` ⇒ 断言：`docs/stack-profile.yaml`、`docs/e2e/cases/` 存在；`product/` 不存在；`atlas.config.yaml` 内容为 `version: 1 + layout.assets_root: docs`；`docs/stack-profile.yaml` 的 `cases_dir` / `index` / `scripts_dir` 全部指向 `docs/e2e/...`（模板已渲染）。
2. 在 `docs/` 下建最小 ADR / PRD / E2E 夹具 ⇒ `atlas check` 全门按 `docs/` 解析，ADR 门不再 SKIP；`gen_e2e_scripts` 生成的脚本路径不回到 `product/e2e`。
3. `atlas update` 连续两次 ⇒ 只刷 `.atlas/`，`docs/` 资产与 `atlas.config.yaml` 逐字节不变，不新建 `product/`。
4. `atlas init` 同项目重复执行 ⇒ 命中既有 `.atlas` 守卫 **exit 1**；无 `.atlas/` 但已有配置 `product` 的项目上执行 `atlas init --assets-root docs` ⇒ exit 2，零写。
5. 首装 `--assets-root docs` 且默认 `product/prd/`（或 `product/e2e/` 等任一 Atlas 资产）已存在 ⇒ exit 2，零写。
6. 非法配置（`assets_root: ../x` / `assets_root: .atlas` / 未知键 / 重复键 / version 缺失）⇒ `atlas check` 单行 FAIL；`install.sh --update` exit 2、`.atlas/` 与项目资产零变化；首装非法 ⇒ 不写 `.atlas`、不建骨架。
7. 双根：配置 `docs`，同时保留 `product/stack-profile.yaml` ⇒ WARN 点名两处资产，不自动搬移。
8. profile 漂移：配置 `docs`、`docs/e2e` 存在，但 `docs/stack-profile.yaml` 的 e2e 三路径仍写 `product/e2e` ⇒ WARN 指名「疑似模板未渲染」；显式混合布局不被改写。
9. `extensions/pi.ts`：在 `docs` 配置且 `docs/prd/prd.md` 存在的项目里，`/atlas status` 报开户态 = done；旧装配无 helper 时回退 `product` 并显式提示。

### 4.3 变异与还原

* 每枚变异按四段协议（注入 diff → 目标钉红 → 还原 → 逐字节一致 + 复跑全绿），报告落 `.atlas/runs/mutation-proof/`（运行态不入库）。
* 至少覆盖：解析器默认 / override / 非法配置 / version / symlink / `adr` 相对 / update 零写 / 双根 WARN / 模板渲染 / pi helper / review-inputs / refresh 豁免 / 单个消费者绕过解析器。

---

## 5. 实施顺序与回滚

1. **解析器先行**：`_support/layout.py` + `tests/test_layout.py`；默认 `product`，不动任何消费者 ⇒ 全量绿。
2. **机器侧收敛**：validators / scripts / adapters / support / refresh / review-inputs / closeout 改为 `load_layout`；默认夹具不变；新增 override 冒烟 + 守恒测试。
3. **模板与宿主扩展**：`templates/stack-profile.yaml` 占位渲染；`extensions/pi.ts` helper；`templates/prd` / console 占位。
4. **装配与 CLI**：`install.sh` 写配置 + 渲染 + 预检 + 动态自检；`bin/atlas.js` init 提示 / flag；补装配与 CLI 测试。
5. **写侧与文档**：skills / shared / rings / apply / RUNBOOK / README / docs；按「默认示例 + 首次注明」策略控制 131 行改动噪声。
6. **全量与真跑**：全量测试 + 临时项目咬合 + 变异；通过后按发布流程落 `DESIGN.md` 决策行与 `shared/gates.md` 登记。

**回滚**：默认根项目直接回旧版即可；自定义根项目需先把资产迁回 `product/` 并删除 `atlas.config.yaml`，否则旧版会看不到资产。发布说明必须写明该顺序。

---

## 6. 待评审拍板项

> 2026-10-26 用户已按推荐拍板：以下 1–6 全部采用推荐项。

1. **配置文件名**：`atlas.config.yaml`（推荐，可见、git 跟踪）vs `.atlas.config.yaml`（隐藏）。
2. **首次 init 是否总是写配置**：推荐 `install.sh` 首次安装即写（默认 `product` 也写，行为显式、可复现）；备选「仅非默认才写」（项目更干净，但默认值仍是隐式的）。
3. **双根 / profile 路径漂移首版语义**：推荐均 WARN（符合「新判据先 WARN」纪律）；备选直接 FAIL（更安全，但可能误伤正在迁移或有意混合布局的项目）。
4. **v1 范围**：推荐只 `assets_root` + `adr`；per-asset 的 `prd` / `e2e` / `design` / `reviews` 等键留到有真实非同构布局证据再加；e2e 三路径继续由 `stack-profile.yaml` 显式覆盖。
5. **交互提示位置**：推荐只在 `atlas init` 首次安装且 TTY 时提示；`install.sh` 本身保持非交互，只接受 flag。
6. **非 Python 消费者读取方式**：推荐 `layout.py --print`（单一解析）；备选生成 `.atlas/LAYOUT.json`（读取快，但有漂移风险）。

---

## 7. 实施与验证回填（2026-10-26）

- **实现**：`_support/layout.py`（解析 / 严格校验 / `--print` / `--print-abs` / `--validate` / `--validate-value` / `--write`）；21 个 Python/Shell 生产消费者 + 4 个 adapters + `install.sh` + `bin/atlas.js` + `extensions/pi.ts` + `templates/{stack-profile,e2e/console}` + `skills/frontend-design` 已接入；`closeout_derive` / `refresh_structure` / `make_review_inputs` 的路径族已随布局解析。
- **装配**：`install.sh` 首装写 `atlas.config.yaml`、渲染 `stack-profile.yaml`、预检双根 / 非法配置零写；`--update` 只读且不换根；`atlas init` 首次 TTY 询问（默认 `product`），`--assets-root` / `--adr-dir` 非交互；非 TTY 默认 `product`。
- **全量**：`pytest tests/` **704 passed, 4 skipped**；`tests/test_atlas_verify_playground.py` **2 passed**；`python3 scripts/atlas_check.py --fast` 源包态按既有口径 SKIP（无 `.atlas/`）。
- **真跑**：临时项目 `--assets-root docs` 生成 `docs/stack-profile.yaml`（e2e 三路径 docs）且无 `product/`；`--update` 配置/资产逐字节不变；非法配置 update exit 2 零写；双根首装 exit 2；重复 init exit 1；非 TTY CLI init 默认 product。
- **变异**：隔离副本 **M-layout-1..5**（validate_adr 回退硬编码 / check_layout 放行非法配置 / install.sh 模板回退 product / refresh 豁免回退旧常量 / closeout ADR 前缀回退）均红 → 还原逐字节一致 → 复绿。
- **遗留（v1 显式边界）**：per-asset 的 `prd` / `e2e` / `design` / `reviews` 覆盖键未开放（e2e 仍由 `stack-profile.yaml` 显式覆盖）；改根不自动迁移；`docs/map` 为版本化手工快照，按发版纪律刷新。
