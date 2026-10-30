# RFC-20261030-01：核心 FAIL 修复指引试点（附 Harness 资产映射）

> 提案编号：RFC-20261030-01  
> 提案作者：Atlas 维护者（待补 GitHub 用户名）  
> 关联状态：已落地 (Merged，2026-10-30)  
> 影响范围：校验器 (validators) | 契约 (shared/gates.md) | 测试 (tests) | 文档 (docs/concepts) | 装配刷新 (`atlas update`)

---

## 0. 评审修订摘要（2026-10-30）

独立只读评审结论：**accept with changes**。主审已抽查三条 Critical，均属实。本版修订：

1. **testids 修复方向改正**：`missing = 分片应然 − 源码实然`（`validators/validate_testids.py:669-670`）⇒ 应补源码或删分片应然，不能“在分片补声明”。adopt 的 FAIL 只由 `missing` 触发（`:683-690`），不能提示删源码。
2. **e2e 孤儿/死链方向改正**：`orphan = 分片有索引无`，`dead = 索引有分片无`（`validators/validate_e2e_index.py:401-404`）⇒ 死链补 / 删索引行，孤儿补索引行 / 删分片。
3. **AC 覆盖提示后置**：`AC覆盖对账` 的 FAIL 只在 enforce 且零挂载时出现（`validators/validate_ac_alignment.py:342-347`）；“从 PRD 移除未实现 AC”= 过门删需求，禁止写进提示。本版移出试点，Phase 2 用安全文案。
4. **§4.5 定档改正**：本 RFC 改 `validators/` + `shared/gates.md`，命中 D156 触发 (b) 路径族（`shared/gates.md:102`、`scripts/closeout_derive.py:71/74`）；但无判据翻转，留出集不可构造 ⇒ 三态 = **单案修复（无留出集）**，补 QUEUE 观察行与残留风险，不写“不适用”。
5. **复跑命令改为路径自适配**：`atlas check --fast` 在源包态可能回退到全局包（`bin/atlas.js:272-279`），无全局 CLI 的装配态不可用 ⇒ 改为自动选 `python3 .atlas/scripts/atlas_check.py --fast`（装配态）或 `python3 scripts/atlas_check.py --fast`（源包态）。
6. **试点选点调整**：去掉 `分片链接可达`（与孤儿/死链同源双红）与 `AC覆盖对账`（面窄且危险）；补 `应然落点`（`:763`）与 `分片块字段齐`（`:399`）。试点仍覆盖 3 个校验器，共 7 个检查。
7. **文档表去过度声称**：标题改为“类比映射”；State 改为“门禁判定 + 人审落账，跨会话可对账”；Scope 改为“需求级裁剪；覆盖维度只提示缺口，不替代语义审查”。
8. **同步面补齐**：`shared/gates.md:45` 162 条、`:48` 59 条随新增测试更新；`docs/map/gates.md:18` 的 `shared/gates.md(147 行)` 必须更新；`:20` 的 `tests/(36 文件)` 实为 42（已顺手修正）。
9. **落地结果（2026-10-30）**：用户拍板 A/B 与 36→42 合并落地。相关单测 230 passed；全量 880 passed / 4 skipped；`tests/test_map_anchors.py` + `tests/test_canonical_consistency.py` 17 passed；`atlas-map.check.js` 七项全过；变异 M159a–d 四段协议全 PASS（报告 `.atlas/runs/mutation-proof/`）。

---

## 1. 摘要

外部两篇文章给出的可用经验有两条：

1. Agent Harness 的失败大多不是模型不会写，而是反馈回路不完整：FAIL 只告诉它「哪里不对」，没告诉它「下一步做什么、改完跑什么」；
2. 生成侧要「少写」，验证侧要「多验」。Atlas 已经把验证侧做成硬门，缺的是让 FAIL 可被 agent 自修复的最后一百米。

本 RFC 做两件事：

- **A. 文档映射（零机制）**：在 `docs/concepts/architecture.md` 增加「Agent Harness 五子系统 ⇄ Atlas 资产」类比表，把外部课程的语言接进 Atlas 的定位；不改任何判据。
- **B. 门禁反馈试点（本 RFC 的行为面）**：给 3 个核心校验器的 7 个 FAIL 检查追加统一的 `｜修复: ...｜复跑: ...` 后缀；不改判定、状态、退出码，不加新门。

A/B 与 `tests/(36 → 42)` 已在同一个变更集落地（用户 2026-10-30 拍板）；以下保留拆分设计说明，供回滚与后续批次参考。

## 2. 现象与取证

### 2.1 触发形态

- **规则 / 环节**：`atlas check` 聚合的 `validate_testids` / `validate_e2e_index` / `validate_ac_alignment`。
- **触发时机**：agent 执行 `atlas check --fast` 或收口跑门，撞到 FAIL。
- **具体行为**：FAIL detail 给出精确差集，但没有「修复动作」与「复跑命令」；agent 需要回读校验器源码或猜。

### 2.2 客观证据与日志

真实夹具输出（2026-10-30，源包态）：

```text
[FAIL] 分页双向集合相等 —— [{"page": "home", "缺失(抽取源无)": ["home-missing-btn"], "多余(用例未引)": []}]
[FAIL] 行字段完整 —— ['E2E-HOME-001:分片空']
[FAIL] 分片链接可达 —— ['E2E-HOME-001:链接格式']
[FAIL] AC覆盖对账 —— 已声明 AC: 1，后端测试挂载覆盖: 0 (0.0%)（enforce 模式下不允许零测试挂载）
```

对应发射点：

- `validators/validate_testids.py:710`：`res.add("分页双向集合相等", "FAIL", json.dumps(unequal...) + hint)`；`hint` 只在命中模板结构时解释「为什么」，不解释「怎么修」。
- `validators/validate_e2e_index.py:389` / `:399` / `:403` / `:429`：行字段、分片块、孤儿/死链、链接可达均只给差集。
- `validators/validate_ac_alignment.py:347`：`AC覆盖对账` 只给覆盖率与「不允许零测试挂载」。

### 2.3 为什么现在做

- 课程 L10 明确：给 agent 的错误信息要带修复指引，不要只写 `Test failed`；
- Atlas 自己的收口流程（`shared/closeout.md`）要求 agent 自修复后再跑门；当前 FAIL 把「定位」做完了，把「下一步」留给了人；
- 现有局部提示（testids 动态名提示、E2E runner 的 `npm i` 提示）证明这类后缀已被接受，但它们是 ad hoc 的，只解释原因，且没有统一复跑命令。

## 3. 决策与权衡

### 3.1 定案 B：统一后缀，附加到 FAIL detail

格式：

```text
｜修复: <最小动作>｜复跑: <命令>
```

约束：

- 只加在 **FAIL** 分支；PASS / WARN / N/A 不加。
- 不改 `status` / `level` / 退出码 / 既有诊断文本；后缀只追加。
- 不改 JSON schema：`detail` 仍是字符串；`atlas_check` 按 `[FAIL]` 行透传，终端与 JSON 同时可见。
- 不新增 `_support/` 模块；每个校验器内一个 2 行私有 helper（`_fix(action)`）即可，等第 4 个消费者出现再提炼（YAGNI）。
- **复跑命令自适配**：`root/.atlas/scripts/atlas_check.py` 存在 ⇒ `python3 .atlas/scripts/atlas_check.py --fast`；否则 `python3 scripts/atlas_check.py --fast`。源包态与装配态各自正确，不依赖全局 CLI（`bin/atlas.js:272-279` 的回退不用于 hint）。
- 路径从 `lay` 取（支持自定义资产根），禁止硬编码 `product/`；名单排序、每项 cap 3、无时间戳 / 绝对路径，保证可 diff、测试稳定。
- 单行、无换行；不出现 `[FAIL]` / `[WARN]` 字样；**不出现子串 `item`**（`tests/test_validators.py:1286` 有 `assert "item" not in detail` 的反向钉）。

试点 7 个检查：

| 校验器 | 检查名 | 修复动作（要点） |
|---|---|---|
| `validate_testids` | `分页双向集合相等` | **缺项**（分片有、源码无）⇒ 在源码补 `data-testid`，或从分片 `testid:` / step / expected 移除同名；**多项**（仅 greenfield 且已实现页）⇒ 在分片补声明/引用，或删除源码多余 `data-testid`。adopt 下多项是 WARN，不提示删源码。 |
| `validate_testids` | `应然落点` | 在分片 `落点:` 行补/改 `<tid> <存在的相对路径>`，并确保文件内可解析到该 testid。 |
| `validate_e2e_index` | `行字段完整` | 在索引行补齐缺失列；`状态原因` 只在 blocked/skipped 时填且与状态匹配。 |
| `validate_e2e_index` | `索引↔分片无孤儿/死链` | **死链**（索引有、分片无）⇒ 补/修分片或删该索引行；**孤儿**（分片有、索引无）⇒ 补索引行或删分片。 |
| `validate_e2e_index` | `分片块字段齐` | 在分片 `atlas-case` 块补齐 `id/pages/precondition/step/expected/testid`。 |
| `validate_ac_alignment` | `无主AC拦截` | 先在 PRD 声明该 AC；确认测试标记写错则移除标记。 |
| `validate_ac_alignment` | `无效跳过拦截` | 去掉 skip/xfail，或补 `waiver:<理由>`。 |

为什么是这 7 个：它们覆盖 Atlas 三条主对账线（testid 双向、索引 ⇄ 分片、测试 ⇄ AC），且都是 agent 收口时最容易撞到的 FAIL。**本 RFC 没有门禁 check 级 FAIL 频次遥测**，所以「高频」是待验证假设；试点后按真实仓反馈调整，不宣称统计结论。

**Phase 2 再议**（本 RFC 不实现）：

- `分片链接可达`：与孤儿/死链对同一缺文件双红，先合并去重再决定提示落点；
- `AC覆盖对账`（enforce 零挂载）：安全文案必须是「为未覆盖 AC 补挂测试；**不得删除 AC 过门**；确实未实现 ⇒ 降 `backend_test.mode` 并登记缺口 / 人审」。等试点证明提示有效后再加，避免把“删需求”写成出路。

### 3.2 定案 A：文档映射表

位置：`docs/concepts/architecture.md` 末尾新增 `## 4. 附：Agent Harness 五子系统与 Atlas 资产的类比映射`。

| Agent Harness 子系统 | 课程落点 | Atlas 对应 | Atlas 的差异 |
|---|---|---|---|
| Instructions | AGENTS.md / CLAUDE.md | init 注入指针 + skills 瘦桩 + `shared/global-rules.md` | 入口是路由，规则随包版本化 |
| State | progress.md / feature_list.json | Trellis 任务 + 结构基线 + ADR + E2E 索引 | 门禁判定 + 人审落账，跨会话可对账（门禁只报告，不改写资产） |
| Verification | init.sh / 测试命令 | `atlas check` 两档 + 硬门 + 变异证明 | 双向对账，门禁自证会红 |
| Scope | WIP=1 / 完成定义 | 三问门 + AC + 覆盖维度 | 需求级裁剪；覆盖维度只提示缺口，不替代语义审查 |
| Session Lifecycle | session-handoff.md | apply / backfill / closeout + 人审账本 | 跨会话资产化 + 评审指纹 |

配一段边界说明：五子系统是**类比映射，不是同一层**；课程是单会话、agent 自维护，Atlas 是跨会话、入库、可对账。课程已要求验证命令通过后才改状态，但 `feature_list.json` 仍是单文件、由 agent 维护；Atlas 用 PRD / AC / E2E 三份独立资产 + 双向门 + 人审账本，防「自己批自己作业」与「资产 ⇄ 实现漂移」。外部参考列课程、Anthropic / OpenAI 的 harness 文章、arXiv:2610.34577；只作参考，不写成 Atlas 的依赖。

### 3.3 考虑过的备选方案及否定理由

- **新增 `fix` 结构化字段**：更干净，但要改 3 个 Result 类、CLI / JSON 输出与测试；当前没有第二个机器消费者，YAGNI。若将来 `atlas report` 或控制台要消费结构化修复建议，再升级。
- **共享 `_support/feedback.py`**：只 3 个消费者，且每个 hint 的生成逻辑依赖各自的差集结构；抽早了会把差异硬塞进共享层。等第 4 个消费者。
- **自动修复（`--fix`）**：会改应然资产，风险高，且与「人审 + 门禁」的对抗模型冲突；不做。
- **只写进 `shared/gates.md`**：文档到不了 FAIL 现场；agent 不会在撞门时去翻门册。
- **给所有 FAIL 都加**：diff 大、测试 churn 大，先用 7 个核心检查取证。
- **把 FAIL 降成 WARN / 加独立提示行**：会改变语义或输出格式，可能破坏下游解析；保持 FAIL 与 detail 形态不变。

### 3.4 必须警惕的刺痛代价与兼容性影响

- detail 变长；cap 3 + 排序控制上限。`atlas_check` 行会变长，但仍是单行。
- 既有测试若断言 detail 全等会破；实现前用 `rg "detail\\s*==|\\[\\\"detail\\\"\\]\\s*==" tests` 审计（当前未命中），只改全等断言；子串断言不受影响。
- hint 可能与未来判据漂移；测试只钉「存在 + 关键动作 + 复跑命令」，不钉完整文案；改判据时同步改 hint（列入 `shared/gates.md` 的反馈格式约定）。
- 装配态需 `atlas update` 才能看到新文案；发版说明里写明。
- 不新增门，不改 `shared/gates.md` 的门数；只更新受影响门的测试计数与 `docs/map` 行数 / 锚。
- FAIL 行变长可能被误读为「已解释 / 已修复」；观测同 FAIL 下一轮是否消失，不把 hint 当修复证据。

## 4. 改动面清单

- [x] `validators/validate_testids.py`：`_fix()` + `分页双向集合相等`（按 missing / orphan 分支）与 `应然落点` FAIL 后缀；路径从 `root` 自适配。
- [x] `validators/validate_e2e_index.py`：`_fix()` + `行字段完整` / `索引↔分片无孤儿/死链` / `分片块字段齐` 三条 FAIL 后缀；死链 / 孤儿方向按 §3.1。
- [x] `validators/validate_ac_alignment.py`：`_fix()` + `无主AC拦截` / `无效跳过拦截` 两条 FAIL 后缀；不出现具体框架名。
- [x] `shared/gates.md`：§1 增加「FAIL 反馈格式（试点）」约定；`validate_e2e_index` 行计数 162 → 168、`validate_ac_alignment` 行计数 59 → 62、`validate_testids` 行补 M159a/M159d 取证。
- [x] `tests/test_validators.py`：testids 双向缺项 / 应然落点 + e2e 行字段 / 孤儿死链 / 分片块 + PASS 无后缀；162 → 168。
- [x] `tests/test_validate_ac_alignment.py`：无主 AC / 无效 skip + PASS 无后缀；59 → 62。
- [x] `docs/concepts/architecture.md`：新增 §4 类比映射与边界说明（A 部分，已合并落地）。
- [x] `docs/map/gates.md`：`shared/gates.md` 147 → 149 行；`tests/` 36 → 42（顺手修正）；`docs/map/atlas-map.html` 同步 149 行；`tests/test_map_anchors.py` 绿。
- [x] `CHANGELOG.md`：`[Unreleased]` 补一条；`DESIGN.md` 本 RFC 不新增 D 号。
- [x] `duty-review/QUEUE.md`：观察室补「FAIL 修复指引试点」行（owner / 期限 / 出室条件）。
- [x] 检查 `docs/gates/iron-gates.md` / `docs/guide/`：仅 `docs/guide/changelog.md` 旧历史条目含 testid 旧文案，属历史记录不动；其余无引用。

## 5. 验证与测试结果

已真跑（2026-10-30）：

```bash
# 1. 相关单测
python3 -m pytest tests/test_validators.py tests/test_validate_ac_alignment.py -q
# 230 passed

# 2. 全量出厂测试
python3 -m pytest tests/ -q
# 880 passed, 4 skipped

# 3. 快速自检（源包态）
python3 scripts/atlas_check.py --fast
# OK（源包态 10 校验器均 SKIP：本仓不是 Atlas 目标项目；命令链路正常）

# 4. 地图锚与图
python3 -m pytest tests/test_map_anchors.py tests/test_canonical_consistency.py -q
# 17 passed
node docs/map/atlas-map.check.js
# 全部视图七项断言通过
```

实测结论：

- 7 条试点 FAIL 的 detail 均含 `｜修复:` 与 `复跑:`；
- 对应 PASS 分支不含 `修复:`；
- 既有判定 / 退出码 / 状态不变（除 detail 文本）；
- `tests/test_validators.py` 168 条、`tests/test_validate_ac_alignment.py` 62 条，计数与 `shared/gates.md` 一致；
- `tests/test_map_anchors.py` / `tests/test_canonical_consistency.py` 全绿。

变异证明（M159a–d，四段协议 + 注入 diff + 还原逐字节一致；报告 `.atlas/runs/mutation-proof/`）：

- **M159a**：`validate_testids` 的 `_fix` 返回空 ⇒ `test_testids_fail_detail_includes_repair_hint` 红；还原复绿，字节一致。
- **M159b**：`validate_e2e_index` 的 `_fix` 返回空 ⇒ `test_e2e_index_row_field_fail_includes_repair_hint` 红；还原复绿，字节一致。
- **M159c**：`validate_ac_alignment` 的 `_fix` 返回空 ⇒ `test_dangling_ac_fail_includes_repair_hint` 红；还原复绿，字节一致。
- **M159d**：把后缀加到 `分页双向集合相等` 的 PASS 分支 ⇒ `test_repair_hint_not_added_on_pass` 红；还原复绿，字节一致。

### 5.5 留出验证

**触发 (b) 命中**：diff 落在 `validators/`（校验器族）与 `shared/`（契约族），`scripts/closeout_derive.py:71/74` 的路径族表可对照；`shared/gates.md:102` / `shared/independent-review.md` §9 要求不得以「§1 没写族锚」跳过。

**三态 = 单案修复（无留出集）**：本 RFC 只追加 FAIL 文本，不改 verdict / 案数 / 通道，留出独立性判据 ①（判据输出翻转）无法满足，构造不出合格留出集。按 D156 须：

- 独立评审确认「确无可行留出集」：见 `proposals/REVIEW-20261030-01-gate-fail-repair-hints.md`；
- QUEUE 观察行：已落 `duty-review/QUEUE.md:22`；owner = 本 RFC 实施者；期限 = 下一个 beta 发版后 2 周；观察项 = 7 条 FAIL 的 hint 是否让同一 FAIL 下一轮消失 / 是否被误当已修复；
- 残留风险写入本节：hint 与判据漂移、agent 把提示当修复证据、单行变长影响可读性。

不宣称闭族。

## 6. 分批、回滚与观测

- **落地方式**：用户 2026-10-30 拍板 A/B 与 36→42 合并为一个变更集；内部仍按 B1 testids / B2 e2e index / B3 AC 分测试批次验证，回滚可按这三个批次拆。
- **回滚**：任一批只回退 detail 后缀与新增测试，判定逻辑零改动，回滚成本低。
- **观测**：先看 agent 撞门后的自修复率（同一 FAIL 在下一轮是否消失）与 hint 是否被引用；不新增机器指标，避免为试点造仪表盘。
- **扩展条件**：7 个检查的 hint 在真实项目里被证明有用（至少 2 个真实仓 / 2 轮），再扩到 Phase 2 的 `分片链接可达` / `AC覆盖对账`；若需要结构化消费，再升级 `fix` 字段。

## 7. 复核提示（评审已完成）

以下问题已由 `REVIEW-20261030-01` 回答；保留作后续复核清单：

1. 这 7 个检查是否选对？有没有更高频 / 更该先做的？
2. 追加到 `detail` vs 新增 `fix` 字段，哪个更符合 Atlas 现有契约与消费者？
3. 是否有测试 / 下游解析依赖 detail 的精确形态，会被后缀打破？
4. 文档映射表是否还有过度声称（尤其「Atlas 的差异」一列）？
5. §5.5 的「单案修复（无留出集）」定档与 QUEUE 观察项是否成立？
6. 计数 / 地图 / 装配面的同步是否有遗漏？
