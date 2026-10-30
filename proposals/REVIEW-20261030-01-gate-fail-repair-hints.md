# REVIEW-20261030-01：核心 FAIL 修复指引试点（RFC-20261030-01）

- **被审对象**：`proposals/RFC-20261030-01-gate-fail-repair-hints.md`（草案）
- **评审方式**：独立只读子 agent；随后主审抽查三条 Critical 的代码证据（2026-10-30）
- **总判定**：**accept with changes**（方向成立；按初版不能实现）

## Critical（均已修订）

1. **testids 修复方向反了**  
   `validators/validate_testids.py:669-670`：`missing = 分片应然 − 源码实然`。初版写“在分片补 testid 声明”，会越补越红；adopt 的 FAIL 只由 `missing` 触发（`:683-690`），不能提示删源码。  
   **处置**：改为“缺项 ⇒ 补源码或删分片应然；多项（仅 greenfield）⇒ 补分片声明/引用或删源码多余项”。

2. **e2e 孤儿/死链方向反了**  
   `validators/validate_e2e_index.py:401-404`：`orphan = 分片有索引无`，`dead = 索引有分片无`。初版“删除孤儿索引行”不存在。  
   **处置**：改为“死链 ⇒ 补/修分片或删索引行；孤儿 ⇒ 补索引行或删分片”。

3. **AC 覆盖文案危险**  
   `validators/validate_ac_alignment.py:342-347`：FAIL 只在 enforce 且零挂载时出现；初版“从 PRD 移除未实现 AC”= 过门删需求。  
   **处置**：移出试点；Phase 2 安全文案 = “补挂测试；不得删 AC 过门；确实未实现 ⇒ 降 `backend_test.mode` 并登记缺口/人审”。

4. **§4.5「不适用」站不住**  
   D156 触发 (b)：`shared/gates.md:102`、`shared/closeout.md` 步骤 3、`shared/independent-review.md` §9；`scripts/closeout_derive.py:71/74` 已把 `validators/`、`shared/` 归入校验器/契约路径族。  
   **处置**：改为 **单案修复（无留出集）**，补 QUEUE 观察行（owner/期限）与残留风险；不宣称闭族。

## Major（已修订）

1. **`atlas check --fast` 非全形态成立**  
   `bin/atlas.js:272-279` 在源包无 `.atlas/scripts` 时回退全局包；无全局 CLI 的装配态不可用。  
   **处置**：hint 自动选 `python3 .atlas/scripts/atlas_check.py --fast`（装配态）或 `python3 scripts/atlas_check.py --fast`（源包态）。

2. **试点选点不全 / 有双红**  
   漏 `应然落点`（`validate_testids.py:763`）与 `分片块字段齐`（`validate_e2e_index.py:399`）；`分片链接可达` 与孤儿/死链对同一缺文件双红；`AC覆盖对账` 面窄。  
   **处置**：试点改为 7 个检查（补 `应然落点` / `分片块字段齐`，去 `分片链接可达` / `AC覆盖对账`）；后两者 Phase 2。

3. **同步缺口**  
   `docs/map/gates.md:18` 的 `shared/gates.md(147 行)` 会变，`tests/test_map_anchors.py:343-355` 必红；`shared/gates.md:45` 162 条、`:48` 59 条须随测试更新；`docs/map/gates.md:20` 的 `tests/(36 文件)` 实为 42。  
   **处置**：已写入 RFC §4；36→42 标为存量漂移，顺手修或单拆。

4. **文档表过度声称**  
   State“状态由项目级门禁改”不实（门禁只判定/报告，不改写资产）；Scope“防形式用例”与门册语义盲区冲突；课程也要求验证后才改状态。  
   **处置**：标题改“类比映射”；State 改“门禁判定 + 人审落账”；Scope 改“覆盖维度只提示缺口，不替代语义审查”。

## Minor（已吸收）

- 行号/检查名核对：710、389、429、347 与代码一致；补 403（孤儿/死链）。
- hint 不得含 `item`（`tests/test_validators.py:1286`）、`[FAIL]/[WARN]`、换行。
- M 号在 `shared/gates.md` 证据列登记，按各门现行序列顺延。
- `无主AC` 先 PRD 声明再移除；`行字段完整` 含“状态原因/状态不匹配”；`分片链接可达` 要提补 `## <ID>` 标题（Phase 2）。
- 无精确 detail 解析器：`atlas_check.py:222-223` 按行过滤，`:916-917` 直接打印；测试均为子串钉。

## 主审抽查

- `validate_testids.py:669-670`、`:683-690`、`:710`、`:763`：核对通过。
- `validate_e2e_index.py:389`、`:399`、`:401-404`、`:429`：核对通过。
- `validate_ac_alignment.py:342-347`：核对通过。
- `scripts/closeout_derive.py:71/74`：`validators/` / `shared/` 路径族确认。
- `bin/atlas.js:272-279`：fallback 行为确认。
- `docs/map/gates.md:18/20`、`shared/gates.md:45/48`：计数与行数确认；`tests/` 实为 42 个文件。

## 用户确认与落地（2026-10-30）

用户拍板：「合在一起就行，顺手都修了」⇒ A/B 与 `tests/(36 → 42)` 合并为一个变更集落地；QUEUE owner = 实施者，期限 = 下一个 beta 发版后 2 周。

落地验证：相关单测 230 passed；全量 880 passed / 4 skipped；`tests/test_map_anchors.py` + `tests/test_canonical_consistency.py` 17 passed；`atlas-map.check.js` 七项全过；M159a–d 四段协议全 PASS（`.atlas/runs/mutation-proof/`）。
