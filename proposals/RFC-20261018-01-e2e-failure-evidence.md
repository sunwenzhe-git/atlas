# RFC-20261018-01 · E2E 真跑失败自动留证(failure evidence:trace + screenshot,失败才落盘)

> **来源**:OpenHands v1.26「browser record」机制的机制级审查(2026-10-18 外部发版雷达首跑五条情报;独立评审裁定五条中唯一有仓库实锤缺口的采纳项)。
> **评审轮记**:`proposals/REVIEW-2026-10-18-e2e-failure-evidence.md`(两轮,含引用核验与对账修订)。
> **拍板**:2026-10-18 维护者「可以,按你推荐的继续」。格式对齐 `proposals/TEMPLATE.md` 四段式。

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态(抽象)

任何「真跑偶发红、复跑即绿」的节拍类现场:当前管道对失败现场的取证上限是**文本**——
运行 stdout 尾部 80 行 + 控制台账本快照(`tail` 仅失败时保留)。凡需要「元素当时的
几何 / 命中点 / 时序」的缺陷判据,都只能靠**临时探针脚本**现场手写,探针落入 `/tmp`
即跨会话不可复算。

### 1.2 客观证据

1. 生成的 `playwright.config.ts` 两轨模板只声明 `reporter: json → .atlas-run/results.json`
   与 `use: { baseURL, launchOptions }`,**无 `trace` / `screenshot` / `video` 键**——
   `scripts/gen_e2e_scripts.py:1549`(python 轨)/ `:1580`(node 轨),两轨 `use:` 对象
   `:1563`、`:1594`。
2. 失败证据恒为文本 80 行:采集点 `scripts/e2e_console.py:520`(`raw[-80:]`),
   落账条件 `e2e_console.py:591-592`(`not ok` 才带 tail),docstring `e2e_console.py:582`
   「落账本的快照条目:失败才带输出尾部(80 行,与运行期同长)」。
3. 探针考古已付两次现场成本:
   - `duty-review/bugs.md:16`(D98 动词批 / 案 6 所属链):「2026-10-17 追路探针
     `/tmp/atlas-probe-trace.mjs`,A/B 双版对照」;
   - `duty-review/QUEUE.md` 归档区案 6:递交件含「/tmp 探针三件」。
   与本仓信条「凡改流水线,必留取证、必记决策」(`proposals/README.md` 首行)相悖。
4. 悬空判据在等证据源:`duty-review/bugs.md:17` 未解观察(hover 禁用按钮首跑偶发
   `Element is not visible`,3 次连跑全绿)的**升判条件已写明** = 「复现 ≥2 次且能给出
   固定节拍证据(trace / 连续截图)⇒ 转 DR4」。即:门已立在条文上,缺的恰是常驻留证面。

### 1.3 动机一句话

`bugs.md:17` 的升判条件 @ 「复现 ≥2 次 + 固定节拍证据(trace / 连续截图)」两者都取决于一个
**不存在的机制**——本 RFC 补的就是这个常驻、失败才落、逐字节可复算的机制;trace 从
「缺陷调查用的临时工具」升为「判据证据源」。

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案

生成物两轨 `use:` 对象补两键,**仅此两键**:

```yaml
# python / node 两轨 playwright.config.ts 模板(scripts/gen_e2e_scripts.py)
use:
  baseURL: …
  trace: 'retain-on-failure'
  screenshot: 'only-on-failure'
```

- 落点:Playwright 缺省产物目录 `test-results/`(trace.zip + screenshot),**不发明产物管理器**。
- 语义:`retain-on-failure` ⇒ 全绿轮零新增构件(验收判据随之可写「失败面存在 / 成功面不存在」)。
- 动词词表(固定、封闭,契约占位 §5.5)语义不动,只给失败面补证。

### 2.2 考虑过的备选与被否 / 不做什么

| 备选 | 判 | 理由 |
|---|---|---|
| `video: on`(含 retain-on-failure) | **本期不做,缓行** | trace 自带 DOM 快照 / 网络 / action log,trace viewer 即逐帧回放器——video 是 trace 的粗粒度投影,不是平行能力;多一键 = 双轨同构面 +2、普查钉 +1,收益为零。**缓行条件**:实跑出现「trace 留证覆盖不了某取证需求」的现场 ⇒ 另起决策行,不自动升格。 |
| 独立「录制管理器 / 上传通道 / 轮转清理」 | 不做 | 运行时平台机制(同源 OpenHands①、cline Cloud①),Atlas 零运行时;产物管理归采纳仓。 |
| 给 mock / fixtures 环节加留证 | 不做 | `rings/e2e/reference.md` §8.3 fixtures 收紧三门已覆盖其面;留证只对真跑门负责。 |
| **失败自动重试 N 次再留证** | **明示不采** | 与缺陷判据方向相反:`duty-review/bugs.md:16`「节拍类首跑不坐实、复跑复现才改判」——重试会把节拍类真缺陷静默吸收成绿(D102 ④「把红灯训练成噪声」同族)。留证对象是**首跑失败现场**,不消红。防复读机裁决已落 `duty-review/QUEUE.md` 归档区(2026-10-18,外部情报再提 retry 类建议引用即可否)。 |
| trace 全量常录(`retain-on-failure` → `on`) | 不做 | 磁盘面成本 × 每用例;成功轮留证无消费方。 |

### 2.3 刺痛代价与兼容性

1. **不溯及已装配副本(咬合点,防「契约新语法被旧副本静默吸收」)**,对齐
   `shared/single-source.md` §3 迁移仪式「新源生效 ⇔ 旧源显式失效」口径:副本行为由
   副本内生成器决定,v3 副本有手工移植前科(`duty-review/bugs.md` 安装与装配段,
   「正式解法 = `install.sh --update` 重装配(待批)」)。**本批能力的咬合点 = 下一次
   `install.sh --update` / 首装重装配**;重装配前「契约已声明留证而现场无 trace」属
   **如实态、非缺陷,巡检不得误报**——与 D103 相抵点登记(升档落地须先排除「有门但无
   形态」类)同一写法。
2. **留证含业务内容**:trace / 截图落在采纳仓本地 `test-results/`,不进 atlas 上报通道
   (§15 零业务上下文出站面不受牵连);`.atlas-run/` 的 results.json 形态不变
   (`e2e_console.py:582` 快照契约不动;账面 80 行尾部在结果摘要侧加一行留证路径说明,
   不做任何解析)。
3. **不解决 D103 盲区**:人工会话取出类的「CI 不可复现」真身是登录态不是取证手段,
   trace 只重放**已发生**的失败。门行盲区面表述不改。

## 3. 改动面清单 (Affected Surface)

| # | 文件 | 动作 |
|---|---|---|
| 1 | `scripts/gen_e2e_scripts.py` | 两轨 cfg 模板 `use:` 各 +2 键(合计 4 行文本)+ 各 1 行注明契约锚 |
| 2 | `rings/e2e/reference.md` §7.1(生成器契约) | +1 条(硬):失败留证三口径(失败才落盘 / 咬合点 / 升判接线) |
| 3 | `shared/gates.md` 2.2「E2E 真跑」行 | 逐格纪律只升本行:失败留证落点 + 咬合点一句 |
| 4 | `tests/test_gen_e2e_scripts.py` | +3 钉(§4.1) |
| 5 | `scripts/mutation_proof.py` 调用方(MB10/MB11) | 本批以 CLI 调 `proof()` 实跑,报告含注入 diff(§4.2) |

## 4. 验证与测试结果 (Verification)

### 4.1 钉(`tests/test_gen_e2e_scripts.py`)

1. **双轨同构钉**(`test_failure_evidence_both_tracks_declare_trace`):两轨生成的
   `playwright.config.ts` 必须各自含 `trace` 与 `screenshot` 键——缺任一轨 ⇒ 红
   (双份同构漂移普查家族)。
2. **值形态钉**(`test_failure_evidence_values_are_closed`):值必须恰为
   `retain-on-failure` / `only-on-failure`(写成 `on` / 全量留证 ⇒ 红)。
3. **零变化走向钉**(`test_failure_evidence_zero_change_semantics`):留证键随**同一
   模板字符串**发射 ⇒ 覆盖口只有源码,不做 `ATLAS_E2E_EVIDENCE` 类开关——加环境开关
   等于给「成功轮也留证」开后门(成功轮留证无消费方);本钉锁死「无覆盖口」。

### 4.2 变异(MB10 / MB11,CLI 跑 `proof()`,报告含注入 diff)

- **MB10**:摘掉任一轨 trace 键 ⇒ 钉 1 红;逐字节还原一致。
- **MB11**:把 `retain-on-failure` 改成 `on` ⇒ 钉 2 红;还原一致。
- 四段协议(基线 GREEN → 注入 RED → 逐字节还原 → 再 GREEN)由 `scripts/mutation_proof.py`
  承载,`run_with_clean_pycache` 防 `.pyc` 假阳性 / `MutationNotApplied` 防 `str.replace`
  静默假阴性。

### 4.3 现场咬合(首轮留证生效日)

- 人为注入一条夜跑红用例 ⇒ `test-results/` 出现 trace(含失败 step 快照)+ screenshot;
- 其后全绿轮 ⇒ 目录无新增构件。
- 咬合记录按 D98/D101 先例登入 `shared/gates.md` 2.2 行(逐格:只升本行证据)。

### 4.4 悬空判据接线(本 RFC 的第二收益)

留证落点即 `duty-review/bugs.md:17` 升判条件的证据源:后续 hover 观察若复现 ≥2 次,
取证直接取 `test-results/` trace(不再手写 /tmp 探针);届时按 DR4 转「hover 前置
可见性等待」契约或生成器条款。
