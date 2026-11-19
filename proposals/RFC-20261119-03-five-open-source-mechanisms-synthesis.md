# RFC-20261119-03: Atlas 执行层自立与线束现代化演进方案（五大开源机制综合吸收 · v3 定稿）

> 提案编号：RFC-20261119-03  
> 提案作者：Atlas 自动化管家  
> 状态：已定案 (Accepted) · v3（2026-11-19 并行双评审「修后通过」，处置见 `REVIEW-20261119-03`）  
> 修订依据：`handoff/2026-11-19-five-mechanisms-synthesis-handover.md` §2 四条刚性红线 + 首轮红队评审 + 二次并行双评审  
> 关联背景：2026-11-19 GitHub Trending 外部情报扫描（NVIDIA/SkillEvaluator、cursor/plugins、HKUDS/CLI-Anything、affaan-m/ECC、erkamyaman/rust-anything）  
> 核心目标：立足 Atlas 作为 Project Harness 的核心定位，解决存量采纳盲摸、采纳负担过重、执行层诊断闭环缺失、消融测试落地难四大痛点。

---

## 0. 修订摘要（v1 → v3）

v3 不是给 v1 打补丁，而是按「防自动化假绿」重新划线：**只吸收与 Atlas 硬门禁、真相源纪律同构的机制；凡是能用一条命令把真回归洗成假绿的机制，一律不吸收。**

| v1 机制 | v3 处置 | 原因 | 落点 |
|---|---|---|---|
| `atlas adopt --from-tests` 动态注入（Python `sitecustomize.py` / Node loader） | **废弃** | 违反 `shared/global-rules.md` §1（框架知识不得进核心）；存量单测可能删库、破坏环境或充斥 Mock，会把假数据固化成伪契约 | 改为 §3 只读静态抽取 |
| 门禁输出结构化 `fix` 可执行命令 | **降级并扩大扫描面** | Agent 会机械执行 `--apply` / `--record` 强刷基线；且现有门禁在 `detail` / `output` 里已经散落可执行改写命令 | 改为 §4 `remediation_hint` 只读诊断 + 全载荷扫描 |
| 全局 `known-diffs.jsonl` 差异放水账本 | **否决** | 本质是给挂红开后门；无状态 CI 无法可靠维系「防腐判断」；与 Golden 数学级锁定冲突 | 保留硬断言；预期变化走人工契约修订 §6 |
| 采纳分档 L0/L1/L2 概念 | **收敛为装配 Profile 三档预设** | 概念先落地为可执行的旗标宏，避免多一套抽象 | §5 `--profile=audit/adopt/strict` |
| Java 采纳仅列为普通支持对象 | **升为 Phase 3 第一优先级** | 存量企业仓 Java 占绝对多数（交接文档观察，实施前需实测样本）；Controller / JPA / JUnit 是业务规则最密集处 | §3.3 |
| `skills/atlas-ablate` 消融诊断 | **保留并收紧安全边界** | 按需诊断价值真实，但不能变成流水线硬门禁，也不能自动改真相源 | §6 + Phase 1 |

**一句话结论**：Atlas 吸收的是「机器可验证的确定性与诊断力」，不是「让 Agent 自己给自己发绿灯的自动化」。

---

## 1. 动因与问题定义 (Why)

### 1.1 四个结构性摩擦

1. **存量采纳冷启动黑盒（Adopt Friction）**：采纳仓老代码缺乏契约与文档，Agent 生成 AC/E2E 只能靠静态启发式猜测（D184），极易偏离真实业务行为。问题不在「没有动态探针」，而在「静态事实没有来源锚、没有置信度、没有人工确认面」。
2. **采纳负担过重（Adoption Bloat）**：维护者与采纳仓反复反馈「整包装配付全量疤痕价」，缺少轻量分级与逃生出口。
3. **执行层审查缺乏闭环（Check Actor Gap）**：正在自建的 `RFC-20261119-02` check 行为者（暂存区自动审查），缺乏标准的多子 Agent 编排模式；门禁报错是纯散文，Agent 撞门后原地打转。但「给 Agent 一条可执行 fix」是错误解法——正确解法是给可核查的只读诊断。
4. **消融测试与变更治理过重（Ablation & Golden Brittleness）**：此前消融测试绑定在「真跑日协议」大包袱里（交接文档记录为 30~60 分钟量级，尚未在本 RFC 中实测），导致无人敢跑；Golden 测试缺乏原子级差异声明。但「差异声明」不能变成「差异豁免账本」。

### 1.2 现状取证（源码级，可复算）

| 现象 | 证据（源码位置） | 与本 RFC 的关系 |
|---|---|---|
| 门禁 `detail` 已输出可执行改写命令 | `scripts/atlas_check.py:399`（`gen_e2e_scripts.py --apply`）、`:402`（`--bootstrap-review`）、`:671`（`write_claim.py release --file`） | R1 不是「未来风险」，是存量载荷已可被 Agent 直接执行 |
| 门禁 WARN 行原样进入 `--json` 的 `rows[]` | `scripts/atlas_check.py:134-147` | Phase 2 必须扫 `rows[].detail`，不能只扫 `failures[]` |
| `restore` 失败会保留 active | `scripts/ablation.py:667-686`（smoke 失败 / 冲突直接 `return 2`，未清 active） | §6 不得宣称「失败也不留 active」；必须给人工恢复指引 |
| `audit` 相关旗标仍写 `.atlas/`、配置与 skill | `install.py:29`（`atlas.config.yaml`）、`install.py:631-648`（skill 复制） | §5 的「零侵入」措辞必须改为「不写项目接线与 workflow 补丁」 |
| `api` 适配器只产 5 个字段 | `adapters/api.py:333-339`（`method/path/summary/source_module/source_file`） | §3.3.1 不能声称「现有基础补 DTO 字段」；需独立静态解析器 |
| `_jpa.py` 行记录无行号 | `adapters/_jpa.py:172-181`（字段行无 `line`）、`:285`（仅 `source_file`） | §3.3.2 需补行号，才能满足「事实带来源锚」 |
| 新增 skill 会触发装配面门禁 | `tests/test_install_selfcheck.py:74`（`NON_RING_SKILLS`）、`docs/map/index.md:109`（`〔数:skills=8〕`）、`docs/map/atlas-map.html:496`（「7 个 agent 执行入口」） | Phase 1 改动面必须一次列全 |
| `ledger_snapshot.py` 没有 `--check` | `scripts/ledger_snapshot.py:172-175`（只有 `paths/--root/--write/--json`；缺省即 dry-run） | 验收命令不得写不存在的 `--check` |

### 1.3 五标的只吸收什么

| 标的 | 可吸收机制 | 明确不吸收 |
|---|---|---|
| `NVIDIA/SkillEvaluator` | 「带/不带 skill」A/B 实测判影响的分层思路 | 把评测结论直接当门禁绿灯 |
| `cursor/plugins` | `thermos` 多实例并行评审 + 确定性合流；Agent-Native CLI 规范 | 把子 Agent 判定当最终门（终审必须是确定性代码） |
| `HKUDS/CLI-Anything` | 贡献面测试基线 + 单一正本 + 定期加固轮（作为背景原则，不单独立项） | 无 |
| `affaan-m/ECC` | 「每宿主只走一条安装路径」装配互斥；low-context / no-hooks 轻载出口 | 多套装配路径并存 |
| `erkamyaman/rust-anything` | 无损字面量 Codec；门禁失败可诊断；事实集来源指纹（stale 判红） | `from_tests` 动态穿透；`known-diffs.jsonl` 全局放水；可执行 `fix` |

### 1.4 四条刚性红线（本 RFC 的最高约束）

| # | 红线 | 本 RFC 的落地判据 |
|---|---|---|
| R1 | 门禁输出严禁提供可自动覆盖基线的改写指令 | 只输出 `remediation_hint`（自然语言诊断）；禁止 `fix` / `autofix` / 任何 `--write` `--record` `--force` `--apply` `release` 类命令；**扫描面 = 完整 `--json` 载荷（rows + failures + detail + output + hint）**，不是只扫 hint；改真相源必须由人显式决策 |
| R2 | 存量采纳严禁动态侵入拉起未知测试 | 100% 只读静态分析（AST / 注解 / 正则签名）；不执行目标代码、不注入 `sitecustomize.py`、不装 Node loader、不跑目标仓测试 |
| R3 | 坚决否决全局放水容忍账本 | 不引入 `known-diffs.jsonl` 或任何跨用例豁免表；Golden 保持硬断言；预期变化必须改契约/AC 本身并留人审记录 |
| R4 | 存量采纳第一优先级覆盖 Java | Spring Controller / JPA 实体 / JUnit 5 + AssertJ 静态逆推为第一批深挖对象；Zero-JVM：不依赖 JDK/Maven/Gradle，不执行 `mvn test` |

> **R1 范围澄清**：R1 约束的是**门禁输出载荷**，不约束人工/进程显式执行的维护命令。人可以在终端运行 `ledger_snapshot.py --write` 或 golden `--record`；门禁不得把这类命令作为「修复建议」喂给 Agent。
>
> **R4 有意收窄**：交接文档写「enum 状态机」，但静态解析只能可靠产出**枚举值集 + 显式赋值点**，不能凭值集推断迁移。本 RFC 明确收窄为前者；若维护者要求状态迁移，需要另立「显式状态迁移代码分析」子项。

---

## 2. 方案全景架构

```text
┌────────────────────────────────────────────────────────────────────────┐
│              Atlas Project Harness 现代化演进（v3 · 防假绿版）          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
    ┌─────────────────┬─────────────┴───────────┬──────────────────┐
    ▼                 ▼                         ▼                  ▼
【支柱一：静态采纳】 【支柱二：执行层诊断】   【支柱三：分档装配】 【支柱四：按需消融】
 Spring/JPA/JUnit     RFC-02 CLI 审查执行器    互斥装配 Profile     atlas-ablate 诊断
 只读静态解析          remediation_hint 诊断     audit/adopt/strict  全量门集校验
 事实锚 + AC 草稿      全载荷防改写扫描          旗标宏向下兼容      失败保留 active 供人恢复
```

四支柱共享同一条纪律：**任何自动化都不得在无人决策的情况下改写真相源或基线。**

---

## 3. 支柱一：存量采纳的只读静态真值抽取（Adopt Static Ingestion）

### 3.1 原则：只读、零执行、零 JVM、产物不落真相源

- 只读扫描源码文本与结构（AST / 花括号匹配 / 注解正则），不导入目标模块、不执行目标函数、不启动目标进程。
- 不写目标仓的真相源目录；所有产物落 `.adapter-out/adopt/`（`shared/stack-profile.md` 已登记的中间产物单一位点），属于**中间产物**，不是 PRD/契约真相源。
- **禁止清单**（出现即视为方案违规）：
  - Python：`sitecustomize.py`、`PYTHONPATH` 注入、`pytest` 插件挂钩、`sys.settrace`；
  - Node/TS：`--require` / `--loader` / `resolve hook` / 临时包装模块；
  - Java：`mvn test`、`gradle test`、`java -jar`、启动 Spring 上下文；
  - 任何「先跑目标仓测试再采集出入参」的形态。

> 说明：Atlas 自身的出厂测试（`pytest tests/`）不受此限；本条约束的是**采纳仓**。

### 3.2 产物、来源锚与 stale 判据

每次静态抽取产出两件套（均落 `.adapter-out/adopt/`）：

1. **结构事实底稿 `facts.json`**：端点、DTO、实体、枚举、测试断言等结构化事实，每条必须带：
   ```json
   {
     "kind": "endpoint",
     "source": {"file": "src/main/java/.../OrderController.java", "line": 88},
     "payload": { "...": "..." }
   }
   ```
2. **AC 草稿 `ac-draft.md` / `ac-draft.json`**：每条 AC 草稿必须带 `来源`、`断言原文摘要`、`confidence`、`confirmed: false`、`status=待人工确认`。

**stale 判据（只判红，不自动重录）**：

- `facts.json` 头部记录 `generated_at` / `source_fingerprints`（每个源文件的 sha256）/ `git_commit`；
- Phase 3 新增 `validators/validate_adopt_facts.py` 消费该文件：源文件 sha256 不一致 ⇒ **FAIL（stale）**，提示「源已变化，需重新静态抽取并由人确认差异」；
- AC 草稿进入 PRD 前必须由人把 `confirmed` 改为 `true`；`validate_prd` 拒绝 `source: adopt-draft` 且 `confirmed: false` 的 AC；
- 严禁在门禁载荷中输出 `--record` / `--write` 之类自动重录命令（R1）。

> `validate_adopt_facts.py` 是 Phase 3 的新增门，必须同步 `scripts/atlas_check.py` 的 `VALIDATORS`、`shared/gates.md` §2.2 与全部计数锚；落地前不得宣称「stale 已判红」。

### 3.3 Java 第一优先级：Spring / JPA / JUnit 5 静态解析

Java 是存量企业仓的绝对多数（交接文档观察；Phase 3 开工前用 3 个真实仓抽样确认）。Phase 3 必须先做 Java，再做 TS/JS。

#### 3.3.1 Spring Controller 静态推导

**落点**：新增 `adapters/java_web.py`（框架知识的合法落点），由 `scripts/adopt_static.py` 直接调用；**不注册进 `scripts/refresh_structure.py` 的 `ADAPTER_CATEGORIES`**，避免污染 `api` 契约与结构事实表。

解析方式：静态文本 + 花括号匹配 + 注解正则，不依赖 JDK parser。

- 类级 `@RestController` / `@Controller` + `@RequestMapping("/base")`；方法级 `@GetMapping` / `@PostMapping` / `@PutMapping` / `@DeleteMapping` / `@PatchMapping` / `@RequestMapping(method=...)`；
- 未声明动词的 `@RequestMapping` 记 `ANY`（不猜）；
- 提取：HTTP 动词、路径（保留 `{id}` 占位，不做运行时解析）、handler 方法名、参数列表（`@RequestBody` / `@PathVariable` / `@RequestParam` / 普通 DTO）、返回类型（`ResponseEntity<T>` 解包）；
- DTO 字段：按简单类名在同一仓内索引类声明，抽取字段名 / 类型 / `@Column` 约束（仅 JPA 侧）；**同名多候选 ⇒ `ambiguous: true` 并列候选，不猜**；
- **明确不做**：SpEL、`params` / `headers` 条件映射、接口继承映射、AOP 改写后的真实路径、Lombok 生成字段、`record` 组件展开、嵌套 Controller、多行注解参数的复杂拼装。

**已知解析边界**（必须写进测试反面包，不得静默）：

- 同行 `@RestController public class C { ... }` 与单行 `@GetMapping("/x") public String x()` **已实测支持**（见 `tests/test_adopt_static.py` 与手工探针），不再列为盲区；
- 多行注解参数的**复杂嵌套**拼装、Lombok 生成字段、`record` 组件展开、嵌套 Controller 内部方法仍不支持；
- 上述形态一律输出 `confidence=low` 或 `ambiguous: true`，并记 `parse_warnings[]`，不得静默当「无端点」。

事实样例：

```json
{
  "kind": "endpoint",
  "source": {"file": "src/main/java/.../OrderController.java", "line": 88},
  "payload": {
    "http": "POST",
    "path": "/api/orders/{id}/cancel",
    "controller": "OrderController",
    "handler": "cancel",
    "request": {"body": "CancelRequest", "path": ["id"], "query": []},
    "response": "OrderView",
    "ambiguous": false
  }
}
```

#### 3.3.2 JPA / 实体模型解析

复用并小幅增强 [`adapters/_jpa.py`](../adapters/_jpa.py)：

- 识别 `@Entity` / `@MappedSuperclass` / `@Embeddable`；
- 合并 `@MappedSuperclass` 父类字段与 `@Embedded` 内嵌字段；
- 抽取表名（`@Table`，无则类名，**不猜数据库命名策略**）、字段名、类型、`@Column` 约束（非空 / 唯一 / 长度）、主键 / 自增、关系类型；
- `@Enumerated` 字段关联 `enum` 值集；
- **增强项**：行记录补 `line`（`FIELD_RE` 匹配时记录行号），保持 `parse_project()` 三元返回形状不变，避免打断 `adapters/models.py` 的解包；
- **同名类冲突**：`by_name` 后写覆盖时改为 `ambiguous` 标记并列候选，不静默取最后一个；
- **明确不做**：Bean Validation（`@NotNull` / `@Size` / `@Min`）、JPA 继承策略推断、懒加载、`@Convert` 自定义转换、数据库命名策略。

**诚实边界**：`_jpa.py` 只产出**枚举值集**（`meaning` 为空），不推断状态迁移。若某字段存在显式赋值/校验点，可另出「显式赋值点清单」；**不得仅凭枚举值编造状态机**。

#### 3.3.3 JUnit 5 + AssertJ 静态逆向为 AC 草稿

**落点**：新增 `adapters/java_tests.py`（框架知识合法落点），由 `scripts/adopt_static.py` 直接调用；**不注册进 `refresh_structure` 的 `tests` 类别**（该类别契约只有 `type/location/run_command/status`，没有 AC/断言位），避免契约污染。

扫描 `src/test/java/**`：

- 测试单元：`@Test` / `@ParameterizedTest` 方法；`@DisplayName` 优先作为 AC 标题，缺失则用方法名；
- 断言抽取：
  - `assertEquals(expected, actual)` / `assertTrue` / `assertFalse` / `assertNull` / `assertThrows`；
  - AssertJ 链：`assertThat(actual).isEqualTo(expected)` / `.hasSize(n)` / `.contains(...)` / `.isNotNull()` / `assertThatThrownBy(...)`；
- **只抽静态可判形态**：expected 为字面量或同文件常量 ⇒ `confidence=high`；actual 表达式复杂 / 断言嵌套 / 依赖 Mock 行为 ⇒ `confidence=medium|low`；
- 聚类：按测试类 → 业务能力，按 `@DisplayName` / 方法名词元聚类为 AC 草稿；
- 每条 AC 草稿：
  ```json
  {
    "id": "AC-DRAFT-001",
    "source": {"file": "src/test/java/.../OrderServiceTest.java", "line": 42, "test": "shouldRejectNegativeAmount"},
    "display_name": "负金额下单应被拒绝",
    "assertions": ["assertThat(result.getCode()).isEqualTo(\"INVALID_AMOUNT\")"],
    "confidence": "high",
    "confirmed": false,
    "status": "待人工确认"
  }
  ```
- **反假绿**：AC 草稿不是门禁；只有 `confirmed: true` 后才可进入 PRD。`confidence != high` 或断言含 Mock 的，必须显式标注「不可直接作为验收判据」。

#### 3.3.4 Zero-JVM 铁律与失败模式

- 全部由 Atlas 内置 Python 脚本完成静态文本 / 结构分析；
- 不依赖本地 JDK / Maven / Gradle，不执行 `mvn test` / `gradle test`；
- 解析失败（编码异常、语法超出解析能力）⇒ 该文件 **WARN + 跳过并记名**，不静默、不猜；
- 端点 / 实体 / AC 的统计数字必须可由 `facts.json` 复算，禁止手写汇总；
- `scripts/adopt_static.py` 只做编排，不得出现 Spring / JUnit 注解字面量；框架知识全部留在 `adapters/`，并新增测试确保该边界不被突破（既有 `tests/test_no_framework_names.py` 不扫 `scripts/`，需补一条专项断言）。

### 3.4 TS / JS 次优先

Java 跑通后，按同一套产物契约扩展 TS/JS：

- 导出函数 / 类型 / 接口；
- 路由声明（`routes` / router 定义）；
- 测试文件中的 `describe` / `it` / `expect` 静态抽取；
- 同样只读、零执行、带来源锚。

### 3.5 无损字面量 Codec（值域收窄）

保留 `rust-anything` 的无损 marker 思路，但**只用于静态可产出的字面量事实**：

- `{"$num": "NaN"}` / `{"$num": "-0"}` / `{"$num": "Infinity"}`；
- `{"$bigint": "12345678901234567890"}`；
- `{"$utf16": [55357]}`（单个孤立代理项；`[55357, 56832]` 是合法 😀 代理对，不是畸形样本）；
- 不再声称可捕获 `undefined` / `Map` / `Set` 等运行期形态——静态抽取看不到它们。

### 3.6 反假绿与置信度纪律

- `facts.json` 只陈述「源码里写了什么」，不陈述「运行时一定怎样」；
- AC 草稿默认 `confirmed: false`；`confidence=low` 不得进入 PRD；
- 任何「静态抽取 → 自动生成门禁 → 门禁全绿」的链路一律禁止；门禁只认人确认后的契约。

---

## 4. 支柱二：执行层审查与门禁只读诊断闭环

### 4.1 复用 RFC-20261119-02 已定案执行器（不另立子 Agent 体系）

`RFC-20261119-02` 已明确：会话外触发拉不起宿主子代理，执行面 = 沿实例⑤ 既有 CLI 独立审查进程，审查判据零新增、扇出 ≤4。本 RFC **不另立**「架构合规 / 安全越权 / 测试基线」三类子 Agent，也不重复定义编排。

本 RFC 只保留一条边界声明：

- 多个实例⑤ CLI 审查进程可以并行，但**终审必须是确定性代码**（merge-ready 门）；子进程意见只是输入，不得直接作为绿灯。

### 4.2 门禁输出：`remediation_hint` 只读诊断协议

**删除** v1 的 `fix` 字段。任何门禁的机器返回格式中：

- 禁止出现 `fix` / `autofix` / `apply_command` / `record_command` 等字段；
- 禁止在 `detail` / `output` / `remediation_hint` 中出现可直接执行的基线覆盖命令（`--write` / `--record` / `--force` / `--apply` / `release` / `git apply` / `rm -rf` 等）；
- `command` 字段的语义是**已执行的诊断命令（证据）**，不是修复指令；但它不再整类豁免——只允许「只读校验器调用」白名单（如 `python3 .atlas/validators/validate_*.py ...`、`python3 -m pytest ...`），出现改写类旗标即判红。

**现有存量清场**（Phase 2 必做，逐条改为 hint 或删除命令片段）：

- `scripts/atlas_check.py:399`：`gen_e2e_scripts.py --apply`
- `scripts/atlas_check.py:402`：`gen_e2e_scripts.py --bootstrap-review`
- `scripts/atlas_check.py:671`：`write_claim.py release --file <路径>`
- `scripts/atlas_check.py` 其余 `--write` / `--record` / `--force` 提示

建议 schema（注意：现有失败载荷键是 `name`，不是 `gate`）：

```json
{
  "name": "对齐测试(.atlas/tests)",
  "detail": "pytest 退出码 1：2 failed, 1750 passed",
  "command": "python3 -m pytest .atlas/tests -q",
  "code": 1,
  "output": "…",
  "remediation_hint": {
    "category": "regression",
    "text": "先判断失败用例是本次改动的预期行为变化，还是真回归。若预期，需由人显式更新契约/测试真相源并在提交说明中记录理由；若回归，回查最近一次改动。不要用脚本批量重写断言或重录基线。"
  }
}
```

`category` 取值封闭为：`regression`（疑似真回归）、`truth-source-change`（真相源需人更新）、`environment`（环境/依赖）、`ambiguous`（无法归因）。

**防回归门（Phase 2 必做）**：

1. **运行时载荷扫描**：扫描完整 `--json`（`rows[]` + `failures[]`），对 `detail` / `output` / `remediation_hint` 禁改写命令模式；`command` 按只读白名单校验；
2. **源码级扫描**：AST / 字面量扫描 `scripts/atlas_check.py` 的 `Row.add` / `failures.append` 键集合与禁用模式，挡住「未来新增门又塞 `fix`」；
3. **注入式反例**：夹具里塞 `fix` / `--write` / `--record` ⇒ 必须判红；并登记 M 钉；
4. **WARN 行覆盖**：WARN 也进 `rows[]`，必须在扫描面内，不能只测 FAIL。

### 4.3 Agent-Native CLI 设计规范

- 显式 flags 优先，拒绝隐式交互式问答；
- stdout 纯结构化数据（JSON / 行协议），stderr 纯诊断日志；
- 退出码严格语义化；
- `--json` 输出带 `schema_version`，字段只增不改语义；
- **不得设计「撞门后自动执行修复」的闭环**；Agent 可以依据 `remediation_hint` 自行调查，但改真相源必须回到人。

### 4.4 与现有 `atlas check` 的兼容性

- 现有 `failures[]` 的 `name` / `detail` / `command` / `code` / `output` 保持不变；
- 新增 `remediation_hint` 为**可选**字段，旧消费者忽略即可；
- 清场存量 `--apply` / `--write` 文案属于「输出内容变更」，需在变更说明中列明，不改变门判据；
- 不为每个门一次性铺满 hint；按真实撞门频率逐步补，避免制造无人阅读的噪声。

---

## 5. 支柱三：装配 Profile 三档预设与互斥

### 5.1 装配互斥原则

- 一个项目只允许单一主装配状态，严禁同时加载多套 hook 或重复线束；
- Profile 只是**旗标宏**，不新增装配分支；底层正交旗标保持完全可用、语义不变。

### 5.2 三档预设

| Profile | 定位 | 等价展开 | 实际写盘 | 适用 |
|---|---|---|---|---|
| `audit` | 体检档：不写项目接线与 workflow 补丁 | `--no-patch --no-wiring --no-trellis` | 仍写 `.atlas/`、`atlas.config.yaml`、平台 skill 瘦桩、资产根骨架 | 只想偶发跑检查、不愿改项目 hooks/CI 的仓 |
| `adopt` | 渐进档：存量开户推荐默认 | `--no-wiring`（保留 `.atlas/`、skills、Trellis 骨架与 workflow 补丁，不写项目接线） | 同上 + Trellis 骨架 + workflow 补丁 | 存量仓已有自己的 CI / hooks，先接入 Atlas 资产与门禁 |
| `strict` | 全管档 | 无附加旗标（全量装配 + 项目接线） | 全量 | 绿地项目或愿意接受执行层拦截的仓 |

> **措辞纠正**：`audit` 不是「零写盘 / 零侵入」，只是「不写项目接线与 workflow 补丁」。若需要真正零写盘体检，必须在临时副本中执行，或另立 `--check-only` 模式（本 RFC 不做）。

### 5.3 兼容性与安全

- `atlas init --profile=<x> --dry-run` 必须打印展开后的实际旗标集，禁止黑盒；
- 显式旗标与 profile 冲突时，**显式旗标优先**；无法判定的组合直接拒绝并说明；
- `bin/atlas.js` 必须透传 `--profile`，且在 `--dry-run` / `--profile` 下不得无条件执行 `trellis init`、不得交互式询问资产根；
- 不改变 `install.py` 现有任何旗标的语义；
- 不为 Profile 新增配置文件字段，避免第二真相源。

---

## 6. 支柱四：按需消融诊断与无豁免防腐

### 6.1 `skills/atlas-ablate`：全量消融诊断（唯一模式）

**定位**：非流水线硬门禁，只在用户明确要求时触发；**触发即全量，不存在单机制模式**。执行面为 [`scripts/ablate_all.py`](../scripts/ablate_all.py)：它自动枚举当前门的全量机制，在项目外隔离副本中逐一摘除/还原，只出观测矩阵。与 `atlas eval` 的分工：`atlas eval` 做 base/candidate commit 对照且不宣称净收益；`atlas-ablate` 做门机制摘除观测，同样不宣称净收益。

**全量范围**：`atlas_check.py` 的 `VALIDATORS` 全量（每器一个机制）+ 所有 `rows.add` 内联门函数（调度器 `check_validators` 除外）。范围由 `catalog.json` 决定，不写死数量；装配期 hook / skill / wiring 与真跑 E2E 用例不在同一测量面。

**流程**：

1. **只读盘点**：`ablate_all.py --root . --catalog-only`，确认机制总数与 `VALIDATORS`、内联函数一致；目录为空或不可解析 ⇒ 停止，不得退化为单机制。
2. **隔离副本**：复制 root 到项目外临时目录（排除 `.git` / `node_modules` / 缓存）；全部摘除只发生在副本，**不使用 `git apply` 等 git 写操作**，目标工作树只读。
3. **基线**：副本上 `atlas_check.py --fast --json` 至少 3 轮；`rc` 必须为 0/1 且可解析；存在 `FAIL` 或轮间状态漂移 ⇒ 停止，无法归因。
4. **逐机制摘除**：校验器删除副本中的 `validators/<name>.py`；内联门仅把目标函数内 `rows.add(...)` 替换为 `pass`，其他函数字节不动。
5. **单轮观测**：fast 面每个机制跑一轮；非 fast 面（factory / E2E）先跑一次完整门册，基线为 `FAIL` / `SKIP` / `N/A` 时记「不可归因」，不当作 ok；超时或无效记「未覆盖 + 原因」。
6. **逐字节还原**：写回原始字节、恢复权限、复算 sha256；任一还原失败 ⇒ 立即停止整批，保留证据目录并报告失败路径，不得用 `git checkout` / `reset --hard` 绕过。
7. **产出全量矩阵**：`matrix.json` / `summary.md` 每机制一行，给状态迁移、其他行变化、Δ行耗时、可归因、判定；零破损只写「无可观测差异」，不推断「机制无用」；耗时差未超出基线噪声带时不得归因。

**测量有效性**（否则输出「无效」，不得下结论）：

- 每次观测的 `rc` 必须是 0 或 1，且 `--json` 可解析；`rc=124/127`、空载荷、损坏 JSON ⇒ 本次观测无效；
- fast 面基线默认 3 轮，轮间状态必须一致；耗时归因必须给出基线噪声带，未超出噪声带时只能写「不可归因」；
- 非 fast 面只有单次基线时，只报状态迁移，不报耗时归因；基线为 `FAIL` / `SKIP` / `N/A` 时记「不可归因」，不当作 ok；
- 还原后 sha256 必须与摘除前逐字节一致；否则整批无效。

**安全边界**：

- 全部摘除/还原只发生在项目外隔离副本；目标工作树只读；
- 不使用 `git apply` / `git checkout` / `git reset` 等 git 写操作；
- 不启动服务、不杀进程、不改真相源、不自动生成 `--record`；
- 不提供「撞门自动修复」；失败即停。

### 6.2 明确否决：全局 `known-diffs.jsonl`

**为什么不做**：

1. 全局差异账本本质是「挂红豁免表」，一条记录就能让真回归长期绿灯；
2. 无状态 CI runner 中无法可靠判断「这条差异是否仍应存在」，防腐逻辑会被绕过；
3. 与 Atlas Golden 的硬断言纪律冲突；
4. 与 R1 同源风险：任何「一条命令维护豁免」的机制都会被 Agent 机械化滥用。

**替代方案**：

- 预期行为变化 ⇒ **显式修改契约 / AC / Golden 基线本身**，并在提交说明与评审记录中写明理由；
- 修改真相源必须人审，工具只提供只读诊断；
- 不存在「豁免表」，因此也不需要「stale 豁免清理门」——从根上消除死尸规则。

### 6.3 保留 rust-anything 的正确部分

- **来源指纹**：任何事实/用例集都必须记录源文件 sha256；源变 ⇒ stale 判红（只判红，不重录）；承载者 = Phase 3 的 `validate_adopt_facts.py`；
- **无损字面量 Codec**：见 §3.5；
- **门禁可诊断**：见 §4.2，但输出是 hint 不是 fix。

---

## 7. 改动面清单与三期落地

### 7.1 第一期：消融诊断 Skill 包装（极简速赢）

**目标**：把全量消融协议包装成 `atlas-ablate` Skill，不新增门禁；触发即全量，不提供单机制模式。

| 文件 | 动作 |
|---|---|
| `skills/atlas-ablate/SKILL.md` | 新增；frontmatter 必须 `name: atlas-ablate`（`install.py` 精确匹配目录名）；正文 < 20000 字符；写明「全量唯一模式」 |
| `scripts/ablate_all.py` | 新增；自动枚举 `VALIDATORS` + 内联门行，项目外隔离副本逐机制摘除/逐字节还原，输出 `matrix.json` / `summary.md` |
| `tests/test_ablate_all.py` | 新增；目录枚举、行摘除、端到端还原、无单机制入口 |
| `tests/test_install_selfcheck.py` | `NON_RING_SKILLS` 增加 `"ablate"`（否则环退役对称判据红） |
| `docs/map/index.md` | `〔数:skills=…〕` 由 `scripts/ledger_snapshot.py --write` 刷新 |
| `docs/map/atlas-map.html` | 「7 个 agent 执行入口」清单与计数同步（新增 atlas-ablate） |
| `docs/ecosystem/skills.md` | 用户可见 skill 目录同步 |
| `docs/design/distribution.md` | 在非环 skill 例外清单中追加 `atlas-ablate`（与 apply / onegate 同列） |
| `docs/guide/quick-start.md` | 若列 skill 清单，同步；无清单则不动 |
| `proposals/RFC-20261103-04-installer-golden/*.json` | 装配集变化 ⇒ 必须重录；重录前先跑 `harness.py --check` 确认现状，`--record` 由人批，diff 只允许 atlas-ablate 相关条目 |

**验收（按顺序）**：

1. `python3 -m pytest tests/test_install_selfcheck.py tests/test_canonical_consistency.py -q` 全绿；
2. `python3 scripts/ledger_snapshot.py`（缺省 dry-run，rc=1 表示有漂移）无漂移；
3. `python3 tests/refresh_count_anchors.py`（缺省 dry-run）无漂移；
4. `bash install.sh --no-patch --target <临时目录>` 后确认 `.agents/skills/atlas-ablate/SKILL.md` 落地且 `name:` 正确；
5. `python3 proposals/RFC-20261103-04-installer-golden/harness.py --check` 全绿（重录后）；
6. `python3 scripts/atlas_check.py --fast` 在**已装配的临时项目**中无 FAIL（源包态全 SKIP，不作为有效验收）。

**不做**：不新增流水线门，不改 `install.py` 旗标语义，不把 `atlas-ablate` 设成自动触发。

### 7.2 第二期：只读修复指引与 Agent-Native CLI 规范

| 文件 | 动作 |
|---|---|
| `scripts/atlas_check.py` | `Row` / `failures` 增加可选 `remediation_hint`；`--json` 增加 `schema_version`；清场 4 条存量可执行文案 |
| `tests/test_atlas_check.py`（或新增专项） | 运行时全载荷扫描 + 源码级 AST 扫描 + 注入式反例 + M 钉 |
| `shared/gates.md` | 登记 hint 协议与扫描门（不新增门行则只改文） |
| `docs/map/*` | 行数锚、`出厂测试文件` 计数、html 计数由刷新器更新 |

**验收**：旧消费者行为不变；失败载荷可机读；无任何自动覆盖基线的字段；注入 `fix` / `--write` 必红。

**D156**：Phase 2 改门禁输出判据面并新增规则 ⇒ 触发 §4.5，必须附留出集、pre-fix 红证、post-fix 绿证与 M 钉登记。

### 7.3 第三期：Adopt 静态采纳增强（Java 优先）与 Profile 瘦身

**拆批**：

- **3a（事实面）**：Spring Controller + JPA 实体 + `validate_adopt_facts.py`（stale 门）
- **3b（建议面）**：JUnit 5 + AssertJ → AC 草稿 + `validate_prd` 的 `confirmed:false` 拒绝

| 文件 | 动作 |
|---|---|
| `adapters/java_web.py` | **新增**：Spring Controller / DTO 静态解析器，由 `scripts/adopt_static.py` 直接调用，不注册 `refresh_structure` 类别 |
| `adapters/_jpa.py` | 补 `line` 行号、同名类 `ambiguous`；保持 `parse_project()` 三元返回形状，避免打断 `adapters/models.py` |
| `adapters/java_tests.py` | **新增**：JUnit 5 + AssertJ 静态解析 → AC 草稿；由 `adopt_static.py` 直接调用，不注册 `tests` 类别 |
| `scripts/adopt_static.py` | **新增**：只做编排与产物落盘；不得出现 Spring/JUnit 注解字面量 |
| `validators/validate_adopt_facts.py` | **新增**：`facts.json` 源指纹 stale 判红；登记 `VALIDATORS`、`shared/gates.md` §2.2 |
| `validators/validate_prd.py` | 增加「`source: adopt-draft` 且 `confirmed: false` ⇒ FAIL」 |
| `scripts/atlas_check.py` | `VALIDATORS` +1；计数锚 `校验器` / `校验器文件` / `编排门行` 同步 |
| `install.py` | `--profile=audit|adopt|strict` 旗标宏；`--dry-run` 打印展开 |
| `bin/atlas.js` | 透传 `--profile`；`--dry-run` / `--profile` 下不自动 `trellis init`、不交互式询问 |
| `tests/` | 三个解析器夹具 + 反面包（不可读文件、歧义 DTO、Mock 断言、无断言测试、同行注解、多行注解） |
| `tests/test_no_framework_names.py` 或专项 | 确保 `scripts/adopt_static.py` 无框架字面量 |
| `docs/map/*`、`shared/stack-profile.md` | 计数锚与契约说明（仅 `.adapter-out/adopt/` 中间产物，不改 `api` / `tests` 契约） |

**验收**：

- Zero-JVM：测试环境不安装 JDK/Maven/Gradle 也能全绿；
- 所有事实带 `source.file:line`；
- AC 草稿全部 `confirmed: false`，`confidence=low` 不进入 PRD；
- `facts.json` 源指纹变化 ⇒ stale FAIL，且不输出自动重录命令；
- Profile 展开可由 `--dry-run` 逐字核对，正交旗标语义不变；
- 新增测试文件/校验器后，`出厂测试文件`、`校验器`、`最大单件` 等计数锚全部刷新。

**D156**：Phase 3a 新增 validator、Phase 3b 改 `validate_prd` 判据 ⇒ 均触发 §4.5，必须附留出集与 pre-fix 红证。

---

## 8. 决策与权衡

### 8.1 核心定案

1. **采纳只读静态化**：放弃动态穿透，换取零破坏与可审计来源锚；代价是无法获得运行时真值，需用「草稿 + 人审」补足。
2. **门禁只读诊断化**：放弃可执行 `fix`，换取真回归不被自动洗白；代价是 Agent 自愈需多轮调查，速度变慢。
3. **拒绝差异豁免账本**：保持硬断言；代价是预期变化必须改契约本身，迁移成本更高，但长期无死尸规则。
4. **Java 优先**：Phase 3 先把 Spring/JPA/JUnit 静态面做扎实，再谈其他栈；代价是 TS/JS 采纳延后。
5. **Profile 只是旗标宏**：不新增装配分支；代价是表达力有限，但可控、可核对。

### 8.2 最强反方与证伪条件

**最强反方**：静态抽取永远无法证明运行时行为；AC 草稿可能把错误假设写进 PRD，反而制造更隐蔽的假绿。没有动态验证，Atlas 的「真值」只是源码文本的另一种猜测。

**回应**：承认静态抽取不产运行时真值。因此本方案不把静态结果直接变成门禁，而是：
- 事实与 AC 草稿必须带来源锚、置信度、`confirmed: false`；
- 只有人确认后才进入 PRD/门禁；
- 真实行为仍需由 E2E / 人工验收在运行期证明；
- 这比「动态注入把 Mock 假数据固化成伪契约」更可控。

**证伪条件（可执行）**：

- 在一个真实 Java 采纳仓的副本中抽取 20 个端点 + 20 个 JUnit 测试，人工核对 AC 草稿：
  - 若 `confidence=high` 的草稿被人工判定「语义错误」的比例 **> 20%**，或
  - 若端点路径/动词静态推导错误率 **> 10%**，
  ⇒ 判定 Phase 3 Java 静态方案不达预期，停止扩展并重新评估；
- 命令/路径：`python3 scripts/adopt_static.py --root <副本仓> --out .adapter-out/adopt`，人工抽样核对，记录错误数。

### 8.3 刺痛代价与兼容性

- **采纳收益变慢**：静态抽取 + 人审比动态探针慢，但不会破坏目标仓；这是刻意选择的代价。
- **Agent 自愈变慢**：`remediation_hint` 不给命令，Agent 需要自己调查；换来真回归不被洗白。
- **预期变化成本上升**：没有豁免账本，任何预期变化都要改契约；换来长期无死尸规则。
- **Profile 抽象风险**：三档宏可能掩盖旗标细节；用 `--dry-run` 展开 + 显式旗标优先来兜底。
- **长期维护**：新增的静态解析器是框架知识，必须留在 `adapters/`；Atlas 核心仍框架无关。

### 8.4 被否备选

| 备选 | 否决理由 |
|---|---|
| 动态 `--from-tests` 探针 | 违反 R2；目标仓单测副作用不可控；Mock 假数据会固化成伪契约 |
| 全局 `known-diffs.jsonl` | 违反 R3；给挂红开后门；无状态 CI 无法防腐 |
| 结构化 `fix` 自动自愈 | 违反 R1；Agent 会机械强刷基线，真 Bug 被洗白 |
| 直接放宽 Golden 断言 | 与 R3 同源；数学级锁定被破坏 |
| 把静态 AC 草稿直接设为门禁 | 假绿风险更高；静态结果未经人审不得成为判据 |

---

## 9. 验证与测试结果

本 RFC 为设计文档；**Phase 1 已实施，Phase 2/3 未实施**。实施阶段按批次回填：

- Phase 1：定向测试 + 计数锚 + golden 重录 + 临时装配验证（见 §7.1 与 §9.2）；
- Phase 2：`atlas check --json` 协议测试 + 全载荷扫描 + 注入式反例 + M 钉；
- Phase 3：Java 夹具测试 + 反面包 + Zero-JVM 环境验证 + 新增 validator 的留出集。

### 9.1 留出验证（§4.5）

- **本 RFC 文档本身**：仅修改提案文档，不改门 / 校验器 / 契约判据 ⇒ **不适用**。
- **Phase 1**：触及装配面（`skills` 计数、非环 skill 白名单、golden 装配树），按 D156 的「改门/校验器/契约判据」不触发，但装配面变化必须附：
  - `tests/test_install_selfcheck.py` 与 `tests/test_canonical_consistency.py` 的原始输出；
  - `scripts/ledger_snapshot.py`（dry-run）与 `tests/refresh_count_anchors.py`（dry-run）输出；
  - golden `--check` 重录前后的原始输出与 diff 范围说明。
- **Phase 2**：改 `atlas check --json` 载荷并新增扫描规则 ⇒ **触发 D156**，必须附留出集、pre-fix 红证、post-fix 绿证与 M 钉登记（`shared/gates.md`）。
- **Phase 3a/3b**：新增 `validate_adopt_facts.py`、改 `validate_prd.py` ⇒ **触发 D156**，必须附留出集与 pre-fix 红证。
- **三态**：本 RFC 不宣称闭族；实施批次按各自证据另行判定。

### 9.2 Phase 1 实施回填（2026-11-19）

**已落地**：

- 新增 `skills/atlas-ablate/SKILL.md`（3080 字符；frontmatter `name: atlas-ablate`，`install.py` 目录名精确匹配通过）；
- `tests/test_install_selfcheck.py` 的 `NON_RING_SKILLS` 增加 `ablate`；
- `docs/map/index.md` 的 `〔数:skills〕` 经 `ledger_snapshot.py --write` 刷新为 9；
- `docs/map/atlas-map.html`、`docs/ecosystem/skills.md`、`docs/design/distribution.md`、`docs/guide/quick-start.md` 同步入口/例外/清单；
- 未提交（按用户约束）。

**验证结果**：

| 检查 | 结果 |
|---|---|
| `python3 -m pytest tests/test_install_selfcheck.py -q` | **10 passed**（18 条 skill 引用全部可达；环退役对称含 `ablate` 后仍绿） |
| `python3 -m pytest tests/test_map_anchors.py -q` | **8 passed**（计数锚与行数锚已刷新） |
| `python3 scripts/atlas_check.py --fast`（源包态） | **OK，无 FAIL**（源包态无 `.atlas/`，校验器多为 SKIP，仅作冒烟） |
| 临时目录 `bash install.sh --no-patch --no-wiring --no-trellis --target <tmp>` | **rc=0**；`.agents/skills/atlas-ablate/SKILL.md` 落地且 `name:` 正确；`.atlas/scripts/ablation.py`、`atlas_check.py` 均存在 |
| 临时装配项目 `atlas_check.py --fast` | 仅 `validate_stack_profile` / `validate_prd` 因占位符未替换而 FAIL（装配器已声明属预期），`装配版本` / `消融残留` 均 ok |
| `python3 -m pytest tests/test_canonical_consistency.py -q` | **19 passed**（原 adopt 文档断链已改为指向 `docs/guide/legacy-adoption.md`） |
| `python3 proposals/RFC-20261103-04-installer-golden/harness.py --check` | **红，且在 Phase 1 之前已红**：差异含 `_support/workflow_*.py`、`bin/atlas.js`、`scripts/atlas_review.py` 等大量无关条目；本批新增差异仅为 `atlas-ablate` 一条。**未重录**：重录会吸收并行会话与历史漂移，违反「diff 只允许 atlas-ablate 相关条目」；待拥有这些改动的批次统一重录 |
| `python3 tests/refresh_count_anchors.py --write` | 写后自检 `collect_docs / check_snapshot / check_freshness` 全绿 |

**遗留**：

- golden 基线整体过期（既有 + 并行会话）——由对应批次统一重录，并在 diff 中隔离本 skill 条目；本批不重录以避免吸收无关漂移。

### 9.3 Phase 2 / Phase 3 实施回填（2026-11-19）

**Phase 2（只读诊断）已落地**：

- `scripts/atlas_check.py`：新增 `SCHEMA_VERSION` / `FORBIDDEN_PAYLOAD_KEYS` / `FORBIDDEN_PAYLOAD_PATTERNS` / `payload_violations()` / `command_is_readonly()`；`Row.add` 支持 `remediation_hint`，FAIL 行自动带只读诊断；`--json` 增加 `schema_version=1`；人读失败行打印「诊断」。
- 清场 3 处存量可执行文案：`生成物最新` 的 `--apply` / `--bootstrap-review`、`写面残留` 的 `write_claim.py release --file`；改为自然语言 hint。
- `tests/test_gate_payload_policy.py`：7 条（干净载荷、禁用键、detail/output/hint 改写模式、command 白名单、Row hint、运行时 `--json` 全载荷、源码 `rows.add` 字符串与失败载荷键集合）。

**Phase 3a（Java 事实面）已落地**：

- `adapters/java_web.py`：Spring Controller / DTO 静态解析（同行注解、路径拼接、`@RequestBody` / `@PathVariable` / `@RequestParam`、`ResponseEntity<T>` 解包、DTO 歧义列候选、`parse_warnings`）。
- `adapters/_jpa.py`：字段补 `line`；同名类不再静默覆盖，输出 `ambiguous` / `ambiguous_classes`；保持三元返回形状。
- `scripts/adopt_static.py`：只读编排，产出 `.adapter-out/adopt/facts.json` / `ac-draft.json` / `ac-draft.md`；`--verify` 做源指纹 stale 检查。
- `validators/validate_adopt_facts.py`：未生成 ⇒ SKIP；schema/源指纹/AC `confirmed` 异常 ⇒ FAIL；已注册进 `VALIDATORS`、`shared/gates.md`、`install.py` 自检。
- `tests/test_adopt_static.py`：6 条（事实/AC 抽取、stale 门、`--verify`、PRD 确认闸、编排器零框架字面量、同行注解形态）。

**Phase 3b（AC 建议面 + Profile）已落地**：

- `adapters/java_tests.py`：JUnit 5 + AssertJ 静态解析 → AC 草稿，`confirmed:false`、置信度、Mock 依赖标记。
- `validators/validate_prd.py`：新增 `adopt_draft_findings()` 与「Adopt AC 确认」检查，拒绝 `source: adopt-draft` 未 `confirmed: true` 的 PRD。
- `install.py`：`--profile=audit|adopt|strict` 旗标宏，`--dry-run` 打印展开；`bin/atlas.js` 在 `--dry-run` / `--profile` 下跳过 trellis 自动初始化与交互询问。
- `tests/test_install_profile.py`：5 条（audit/adopt/strict 展开、分离参数、未知 profile、CLI 帮助）。

**验证**：

| 检查 | 结果 |
|---|---|
| 全量出厂测试 `python3 -m pytest tests -q` | **1865 passed, 10 skipped**（9:55；无 FAIL） |
| 定向套件（Phase 2/3 + 既有 check/prd/adapter） | **164 passed** |
| `test_map_anchors` / `test_install_selfcheck` / `test_canonical_consistency` | **8 / 10 / 19 passed** |
| `atlas_check.py --fast`（源包态） | OK，无 FAIL |
| 临时装配项目（Phase 3 文件） | `.atlas/scripts/adopt_static.py`、`.atlas/adapters/java_web.py`、`java_tests.py`、`.atlas/validators/validate_adopt_facts.py` 均落地；`validate_adopt_facts` 已注册为 SKIP（无 facts） |
| 装配后 `adopt_static.py` 端到端 | 1 端点 / 1 AC 草稿；`validate_adopt_facts` PASS；源文件改动后 rc=1（stale） |
| 计数锚 | `校验器文件=13`、`出厂测试文件=86`、`install.py 自检声明=70`；`ledger_snapshot` 与 `refresh_count_anchors` 均无漂移 |

### 9.4 Phase 1 口径修订：全量唯一模式（2026-11-19）

**用户定案**：「执行消融测试就是全量，不存在第二种」。原 skill 的「单机制默认 + 批量可选」不符合该口径，已修订：

- `skills/atlas-ablate/SKILL.md`：改为「触发即全量」；删除单机制入口与「需要清单才批量」表述；底座改为 `ablate_all.py`；
- 新增 `scripts/ablate_all.py`：自动枚举 `VALIDATORS` 全量 + `atlas_check.py` 内联门函数（调度器 `check_validators` 除外），在项目外隔离副本中逐机制摘除/单轮观测/逐字节还原；
- 不使用 `git apply` 等 git 写操作；目标工作树只读；基线 `FAIL` 或轮间漂移即停；还原 sha256 不一致即停；
- 新增 `tests/test_ablate_all.py`：4 条（全量目录、行摘除、端到端还原、无单机制入口）；
- 全局副本 `~/.agents/skills/atlas-ablate/SKILL.md` 与仓内副本 sha256 一致。

**当前目录口径**：13 个校验器 + 10 个内联门函数 = 23 个机制（由 `catalog.json` 动态给出，不写死）。非 fast 面（factory / E2E）只观测一次；基线为 `FAIL` / `SKIP` / `N/A` 时记「不可归因」。

**验证**：`tests/test_ablate_all.py` **4 passed**；`ablate_all.py --catalog-only` 输出 `{"total":23,"validators":13,"inline":10}`；源包态 3 轮全量冒烟完成：23 机制，20 摘除，1 未覆盖（`check_layout` 基线无行），2 不可归因（`check_factory` / `check_e2e` 非 fast 基线为 SKIP），**0 还原失败**。

---

## 10. 开放问题（待拍板）

1. **`adopt` Profile 的精确展开**：本 RFC 暂定 `--no-wiring`（保留 Trellis 骨架与 workflow 补丁）。若维护者认为存量仓连 Trellis 也不应默认创建，则改为 `--no-wiring --no-trellis`，与 `audit` 的差异只剩 workflow 补丁。
2. **Phase 3 的 AC 草稿验收阈值**：本 RFC 暂定 `confidence=high` 的人工语义错误率 ≤ 20%、端点错误率 ≤ 10%；若维护者要求更严，则先只做事实面（Controller/JPA），暂不做 JUnit→AC。
3. **TS/JS 是否与 Java 同批**：本 RFC 建议 Java 单独成批，TS/JS 后置；若项目组合以 Node 为主，可对调优先级。

---

## 11. 结论

v3 的核心不是「少做」，而是「把自动化限制在不会制造假绿的地方」：

- 存量采纳：只读静态抽取，Java 优先，事实带锚，AC 待 `confirmed: true`；
- 执行层：复用 RFC-02 已定案 CLI 审查执行器 + 只读 `remediation_hint`，终审仍是确定性代码；
- 装配：三档 Profile 只做旗标宏，互斥且可核对；
- 消融：触发即全量，隔离副本逐机制摘除/逐字节还原，完整门集校验，无豁免账本。

请实施批重点核对：四条红线是否逐条落地、Java 静态方案是否存在过度承诺、Phase 1 的装配面登记是否完整、Phase 2 的全载荷扫描是否真正挡住 `detail` / `output` 绕过。
