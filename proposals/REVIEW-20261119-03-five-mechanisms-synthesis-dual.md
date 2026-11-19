# 评审记录：RFC-20261119-03 五大开源机制综合吸收（并行双评审 · v3 处置）

> 评审编号：REVIEW-20261119-03  
> 评审对象：`proposals/RFC-20261119-03-five-open-source-mechanisms-synthesis.md`（v2 冻结输入）  
> 评审方式：并行双评审（`RFC-20261114-07` §4）——同一冻结输入、逐字相同指令，派两个互不可见的评审代理（甲 = `b7de813b`，乙 = `b02476d4`），均只读、未改工作树。  
> 双总裁决：**均「修后通过」**。无「退回重写」；存在一处真分歧（Java 解析器落点），按「真分歧不假合流」留痕并给出裁决。  
> 处置结果：全部 Critical / Major 已在 v3 逐条落地；Minor 除有意保留项外均已修。v3 状态 = **已定案 (Accepted)**。

---

## 1. 合流规则与总体结论

- 严重度闭集：Critical / Major / Minor；双评定级不一致取高。
- 双命中：两评独立定位到同一问题，可信度升一档。
- 真分歧：不做假合流；在 §4 单列并给裁决。
- 总体结论：方案方向正确，四条红线在措辞层面已落地；但 v2 仍存在「R1 可经 `detail` / `output` / `command` 绕过」「`--fast` 单探针制造零破损假象」「产物写目标工作树」「restore 失败留 active 与文案不符」「stale/confirmed 无机器承载」等硬问题。v3 已全部修正。

---

## 2. 合流问题清单与 v3 处置

| # | 问题 | 甲 | 乙 | 定级（取高） | 双命中 | v3 处置 |
|---|---|---|---|---|---|---|
| 1 | R1 仍可绕过：现有门禁在 `detail` / `output` 中已输出 `--apply` / `--bootstrap-review` / `release`；v2 只扫 `failures[]` 键名与 hint，且整类豁免 `command`，漏 WARN 行 | C1 | Major（Phase 2 覆盖不足） | Critical | ✓ | §1.4 明确扫描面 = 完整 `--json`（rows + failures + detail + output + hint）；§4.2 列 4 条存量清场；`command` 改只读白名单、不再整类豁免；加源码级 AST 扫描 + 注入式反例 + M 钉 |
| 2 | `--fast` 结构性跳过 factory/e2e，摘除机制必然「零破损」；单次 `run` 无重复样本；截断 64KB 使 JSON 不可解析；rc=124/127 会被误读 | C4 | Critical | Critical | ✓ | §6.1 拆分「计时用 `--fast`」与「破损判据用完整 `atlas check`」；≥3 次取中位数；排除自指门；测量无效判据；不宣称净收益 |
| 3 | `facts.json` / `ac-draft.md` 默认落 `<assets_root>/adopt/` = 写目标工作树，且未登记 layout，形成第二真相源 | C2 | Minor | Critical | ✓ | §3.1/§3.2 改为 `.adapter-out/adopt/`（已登记的中间产物单一位点），明确不是真相源；§8.2 命令同步 |
| 4 | `restore` 冲突 / smoke 失败会保留 active（`scripts/ablation.py:667-686`），v2 却宣称「不留下 active」 | C3 | Minor | Critical | ✓ | §6.1 第 6 步改为「保留 active 是现状；skill 停止并报告 active ID / conflict 文件 / 人工恢复步骤，不自动清理」 |
| 5 | 「AC 草稿须人确认」「stale 判红」只有散文，无 validator / 门禁消费；Agent 把草稿复制进 PRD 仍可过 `validate_prd` | Major | Critical | Critical | ✓ | §3.2 新增 `validators/validate_adopt_facts.py`；`validate_prd` 拒绝 `source: adopt-draft` 且 `confirmed:false`；§7.3 列计数锚与 D156 |
| 6 | `adapters/api.py` 能力被夸大：只产 5 字段，无 handler/参数/返回/DTO/ambiguous；同行注解、单行签名、多行注解会静默漏抽 | Major | Major | Major | ✓ | §3.3.1 改为新增 `adapters/java_web.py` 独立解析器；列明解析边界与 `confidence=low` / `parse_warnings[]`；不声称「补字段」 |
| 7 | `_jpa.py` 无行号、只认 `@Column`、不产 DTO、同名类后写覆盖 | Major | Major | Major | ✓ | §3.3.2 补 `line`、同名 `ambiguous`；保持三元返回形状；明确不覆盖 Bean Validation / 继承策略 / 懒加载 |
| 8 | 新增 `adapters/java_tests.py` 无调用链 / 类别未登记，是孤儿 | Major | Major | Major | ✓ | §3.3.3 明确由 `scripts/adopt_static.py` 直接调用，不注册 `refresh_structure` 的 `tests` 类别；不污染契约 |
| 9 | Phase 1/2/3 计数锚未登记；`ledger_snapshot.py --check` 与 `refresh_count_anchors.py --check` 不存在 | Major | Major | Major | ✓ | §7.1 改缺省 dry-run 命令；§7.1/§7.3 补 `docs/map/*`、`出厂测试文件`、`校验器`、`最大单件`、html 计数；§9.1 列命令 |
| 10 | `audit` 号称零侵入，实际仍写 `.atlas/`、config、skills；`bin/atlas.js` 无条件 `trellis init` 且忽略 `--no-trellis` / `--dry-run` | Major | Major | Major | ✓ | §5.2 措辞改为「不写项目接线与 workflow 补丁」，列实际写盘；§5.3/§7.3 加 `bin/atlas.js` 透传与 dry-run 约束 |
| 11 | §4.1 与 `RFC-20261119-02` 已定案执行器冲突（宿主子代理不可用；另一套三类子 Agent） | Major | Major | Major | ✓ | §4.1 改为「复用 RFC-02 已定案 CLI 执行器，多实例并行，终审确定性代码」；不新增判据维度 |
| 12 | §4.2 schema 用 `gate`，但真实载荷键是 `name`；`结构漂移` 门永不 FAIL，示例失真 | Minor | Major | Major | ✓ | §4.2 示例改为 `name: 对齐测试(.atlas/tests)` + 真实失败文案；计数锚问题归 factory 测试说明 |
| 13 | §1 四个摩擦全是断言，无 `TEMPLATE.md` 要求的取证 | Major | — | Major | — | §1.2 新增源码级取证表（8 条 file:line）；未实测的 30~60 分钟与 Java 占比标为「交接文档观察 / 实施前实测」 |
| 14 | Phase 1 把 golden 重录写成「可只跑定向测试并记录未执行项」，等于允许留红基线 | Major | — | Major | — | §7.1 改为强制：`harness.py --check` 红→绿；`--record` 由人批；diff 只允许 atlas-ablate 条目 |
| 15 | Phase 1 清单缺 frontmatter `name`、quick-start、`docs/ecosystem/skills.md`、`distribution.md` 例外、`atlas-map.html` 手抄清单 | Major | Major | Major | ✓ | §7.1 文件表补齐；验收加一次临时目录 `install.sh --no-patch` 验证 |
| 16 | 与既有 `atlas eval` 重复且口径相反（eval 不宣称净收益） | — | Major | Major | — | §6.1 明确分工；输出改「观测摘要」，不宣称净收益、不自动建议移除 |
| 17 | `--allow-dirty` 语义误述（只放行触碰集外 dirty） | Minor | Minor | Minor | ✓ | §6.1 第 1 步改写 |
| 18 | 静态能力边界清单不全（单行注解、多行注解、Lombok、record、嵌套 Controller、params/headers） | Minor | Minor | Minor | ✓ | §3.3.1 补「明确不做」与「已知解析边界」 |
| 19 | `scripts/adopt_static.py` 若含框架字面量违反 `global-rules.md` §1，且 `test_no_framework_names` 不扫 scripts | Minor | Minor | Minor | ✓ | §3.3.4 / §7.3 加专项断言，框架知识只留 `adapters/` |
| 20 | `atlas check --fast` 在源包态全 SKIP，作为 Phase 1 验收几乎无鉴别力 | — | Minor | Minor | — | §7.1 验收改为定向测试 + 临时装配项目；源包态 `--fast` 明确不作有效验收 |
| 21 | Codec 示例 `[55357, 56832]` 是合法 😀 代理对，不是畸形 | Minor | — | Minor | — | §3.5 改 `[55357]` 并注明 |
| 22 | R4 原写「enum 状态机」，v2 收窄为值集 + 显式赋值点 | Minor | — | Minor | — | §1.4 末尾显式记为「对 R4 的有意收窄，需维护者确认」 |
| 23 | CLI-Anything 的「贡献面测试基线 / 加固轮」列在吸收表但无落点 | Minor | — | Minor | — | §1.3 标为「背景原则，不单独立项」 |
| 24 | `api` / `models` items 契约未同步（若新增字段） | Minor | Major（关联 #6/#7） | Major | ✓ | 裁决：`java_web.py` / `java_tests.py` 不进 `refresh_structure`，产物只落 `.adapter-out/adopt/`，不改 `api` / `tests` 契约 |
| 25 | 消融自身写 `.atlas/runs/check-events.jsonl` 会撞脏树守卫 | Minor | Minor | Minor | ✓ | §6.1 第 1 步加 `--state` 登记运行态文件 |
| 26 | 新增 `scripts/adopt_static.py` 过大可能顶掉「最大单件」锚 | — | Minor | Minor | — | §7.3 验收要求刷新 `最大单件` 计数锚 |

---

## 3. 双评一致的建设性方向（v3 已采纳）

1. **R1 从「改字段」升级为「全载荷清场 + 源码级防线」**：只删 `fix` 字段不够，必须扫 `detail` / `output` / WARN / `command` 白名单，并防未来门回潮。
2. **消融探针必须区分「计时」与「判据」**：`--fast` 只能计时；破损判据必须用完整门集，且排除自指门。
3. **静态采纳必须带「机器可消费的人审闸门」**：`confirmed:false` + `validate_prd` + `validate_adopt_facts`，否则「人审」只是口号。
4. **Java 解析器要先承认边界**：把同行注解、多行注解、Lombok、record、嵌套 Controller 等列为已知不支持，比事后「补字段」更诚实。
5. **装配 Profile 只做旗标宏**：不新增分支，`--dry-run` 展开，显式旗标优先。

---

## 4. 真分歧与裁决

### 分歧 1：Java 解析器落点

- **甲**：新增 `adapters/java_web.py`，独立解析器，避免重写 `api.py` 的风险。
- **乙**：不要新增孤儿 adapter；并入 `adapters/tests.py` 或作为 `scripts/adopt_static.py` 内部模块，且必须登记类别与契约。

**裁决（v3）**：新增 `adapters/java_web.py` 与 `adapters/java_tests.py`，但**由 `scripts/adopt_static.py` 直接调用**，不注册 `refresh_structure` 的 4 类类别，产物只落 `.adapter-out/adopt/`。理由：

- 框架知识必须留在 `adapters/`（`global-rules.md` §1）；
- 不登记类别 ⇒ 不污染 `api` / `tests` 契约，不需要改 `refresh_structure` 渲染；
- 有明确调用者 ⇒ 不是孤儿；
- `adopt_static.py` 只做编排，不含框架字面量，并加专项测试。

### 分歧 2：R1 是否约束人工进程命令

- **甲**：全载荷扫描，`command` 也不能整类豁免。
- **乙**：R1 只约束门禁输出载荷，不约束人工进程；否则与 `ledger_snapshot.py --write` / golden `--record` 自相矛盾。

**裁决（v3）**：两者合并——R1 约束**门禁输出载荷**（含 `command` 的只读白名单）；人工/进程显式执行的维护命令不受 R1 约束。§1.4 加范围澄清，§4.2 加 `command` 白名单规则。

---

## 5. 作者回应（四分法）

- **自证面直接修**：#1–#12、#14–#15、#17–#21、#23–#26 全部落 v3；关键事实经作者 grep 复核（`atlas_check.py:399/402/671`、`ablation.py:667-686`、`api.py:333-339`、`_jpa.py:172-181`、`install.py:29/631-648`、`ledger_snapshot.py:172-175`）。
- **判断面回应留痕**：#13 的实测数据（Java 占比、消融耗时）暂不伪造，标为「交接文档观察 / 实施前实测」；#16 与 `atlas eval` 的分工写入 §6.1；#22 的 R4 收窄显式登记，等待维护者确认。
- **真取舍升级一次**：§10 三个开放问题（`adopt` 精确展开、AC 草稿阈值、TS/JS 排序）留待维护者拍板；v3 给推荐默认值，不阻塞 Phase 1。
- **回评审按派工**：本记录即 v3 的处置面；Phase 2/3 实施批按 D156 另行留出验证。

---

## 6. 遗留风险与观察项

1. **`validate_adopt_facts.py` 已落地**：已注册进 `VALIDATORS` / `shared/gates.md` / `install.py` 自检；未生成 facts ⇒ SKIP，源指纹不一致 ⇒ FAIL。事实语义质量仍归人审。
2. **`java_web.py` 解析边界**：同行注解 / 多行注解 / Lombok / record 等已知不支持；Phase 3 必须用反面包钉住「不确定 ⇒ `confidence=low`」。
3. **golden 重录**：Phase 1 装配集变化必须重录；重录 diff 只允许 atlas-ablate 相关条目。**实施回填**：`harness.py --check` 在本批之前已整体过期（含 `_support/workflow_*.py`、`bin/atlas.js`、`scripts/atlas_review.py` 等无关差异），本批新增差异仅 `atlas-ablate` 一条；为避免吸收无关漂移，**本批未重录**，待拥有这些改动的批次统一重录并在 diff 中隔离本条目。
4. **R1 存量清场**：Phase 2 删除 4 条可执行文案可能改变用户可见输出；需在变更说明中列明，不改变门判据。
5. **`atlas-ablate` 的测量结论**：单次样本、`--fast` 漏门、rc=124/127 都会制造假结论；skill 必须以「测量无效」为显式出口，不得强行给净价值。
6. **adopt 文档断链（已修）**：`handoff/2026-11-19-rust-anything-eval.md:35` 已改指 `docs/guide/legacy-adoption.md`；`test_canonical_consistency` 现 19 passed。

---

## 7. Phase 1–3 实施验证（2026-11-19）

| 检查 | 结果 |
|---|---|
| `tests/test_install_selfcheck.py` | 10 passed（18 条 skill 引用可达；含 `ablate` 的环退役对称仍绿） |
| `tests/test_map_anchors.py` | 8 passed |
| `tests/test_canonical_consistency.py` | 19 passed |
| `scripts/atlas_check.py --fast`（源包态） | OK，无 FAIL |
| 临时目录装配 `install.sh --no-patch --no-wiring --no-trellis` | rc=0；skill 落地且 `name: atlas-ablate` 正确；Phase 3 的 adopt_static / java_web / java_tests / validate_adopt_facts 均落地 |
| Phase 2/3 定向套件 | 164 passed（check / prd / adapter / payload policy / adopt / profile） |
| 全量出厂测试 | 1865 passed, 10 skipped（9:55；无 FAIL） |
| 装配后 `adopt_static.py` 端到端 | 1 端点 / 1 AC 草稿；stale 门 PASS；改源后 rc=1 |
| `harness.py --check` | 既有多条无关差异 + 本批 1 条 `atlas-ablate`；未重录（见 §6.3） |

---

## 8. 结论

**修后通过**。v3 已逐条处置两评的 Critical / Major；Phase 1（`atlas-ablate`）、Phase 2（`remediation_hint` + 全载荷扫描）、Phase 3（Java 静态抽取 + stale 门 + PRD 确认闸 + Profile）均已实施并通过定向验证。仓库级 golden 为既有基线问题，已登记，非本批引入。
