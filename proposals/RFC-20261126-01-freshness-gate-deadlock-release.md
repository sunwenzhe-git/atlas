# 提案标题：finish 结构事实新鲜度门死锁解除（申报式本地脏面豁免 + --advance-baseline 扩越脏树）

> 提案编号：RFC-20261126-01  
> 提案作者：@sunwenzhe-git  
> 关联状态：已定案 (Accepted)——tech-proposal-reviewer 双评修后通过（2026-11-26；1 Critical + 4 Major + 4 Minor 全采纳），当日落刀  
> 关联 issue：#78（pipeline 自感知上报，2026-11-26）  
> 影响范围：脚本工具 (scripts) | 执行层 workflow | 装配模板 (install) | 契约文档 (shared/gates.md)

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

* **规则 / 环节**：`atlas workflow finish` 的结构事实新鲜度前置（RFC-20261122-05）与 `refresh_structure.py` 基线自进（F26）。
* **触发时机**：两类真实仓形态——
  * **D-A（常驻本地面）**：多模块开发仓中工作树常驻开发者刻意不提交的本地调整（本地脚本 / 配置 / 并行半成品）。任何独立任务卡 finish 都因全仓非豁免脏路径被 `freshness_fail` 拒收；连续两次扣完 charged 预算（`max_verify_attempts` 缺省 2）后连 verify 都被预算门拒收（exit 3）——任务卡永久滞留 `in_progress`，被迫绕开 finish。
  * **D-B（多卡序列 + 暂存实现）**：卡 A 提交后 HEAD 前移，卡 B 实现恰在暂存区（收口契约）时重刷结构事实：`--chain` 因「产品侧未提交改动」（含暂存实现）拒推进 baseline；`--advance-baseline` 只越过「漂移冻结」与「空转态」两前置，**不越过脏树拒进** ⇒ 「实现先行、刷新滞后」的时序形态下 baseline 推进通道全被堵死（评审 M4 改述：卡 B 动工前的干净树窗口内 `--chain` 仍可正常推进——死锁本质是时序脆弱性，非绝对不可达）⇒ 卡 B finish 恒 FAIL。

### 1.2 客观证据与日志 (Minimal Evidence)

```text
workflow_finish.py:476-492  _worktree_dirty_paths：全仓非豁免（未暂存 ∪ 未跟踪）一律算脏
workflow_finish.py:532-536  baseline ≠ HEAD ⇒ FAIL，文案只指 --chain
workflow_finish.py:739-744  --force 不绕本门（评审 M4 有意）
workflow_causes.py:48       freshness_fail 充值（charged）
atlas_workflow.py:474-486   charged ≥ max_verify_attempts ⇒ verify 拒收（exit 3，要求人工）
refresh_structure.py:702-707  maybe_advance_baseline：porcelain 任一非豁免路径 ⇒ 拒推进（暂存实现也算脏）
refresh_structure.py:634-651  --advance-baseline 仅越过 drift 冻结与空转态，不越过脏树
```

issue #78 现场证据：开发者完成单卡并暂存/提交后执行 finish，因**全仓其它路径**不干净被连续拒收并耗尽预算。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

**三件，全部保守扩越、不降门强度：**

1. **新配置旋钮 `structure.local_dirty_paths`**（`.atlas/config.yaml`）：
   * 语义 = 本仓**常驻且永不入库**的本地面**申报清单**；条目为 POSIX 前缀（`scratch/` 目录前缀、`notes.md` 单文件精确）。
   * 判据单源：loader `load_local_dirty_paths(root)` 落 `refresh_structure.py`（finish 与 advance 同吃一份，fail-soft：无文件/无键/坏形状 ⇒ 空表，不猜）。
   * finish 侧脏面**三分诊**：`脏 ∩ 暂存任务范围`（半暂存，审查锚失效风险）⇒ FAIL（charged）不变；`脏 − 暂存 − 已申报` ⇒ FAIL（charged）但**报错文案直接给出可粘贴的 config.yaml 申报片段**（「停下人工」一步可执行）；仅已申报脏面 ⇒ PASS，reason 追加「已申报本地脏面 N 条（不阻断）」留痕。
   * advance 侧：已申报路径与 `.atlas/` 等豁免前缀同待遇（单一判据源）。
2. **`--advance-baseline` 扩越脏树拒进**：override 时不再因脏路径 return，改为 **loud log 逐条列出被忽略的未豁免脏路径**（显式人工背书语义从「漂移冻结 / 空转态」扩到「脏树」）。自动 `--chain`（无 flag）语义不变：未申报脏面仍拒推进。D-B 解除：卡 B 暂存态下 `refresh_structure.py --chain --advance-baseline` 可重锚。
3. **finish 文案升级**：stale-baseline 报错补第二通道明示「树非干净（含暂存实现）⇒ `--chain` 追加 `--advance-baseline` 显式背书」。

**不动**（与既有评审定案对齐）：`freshness_fail` 充值属性不变（剩余 FAIL 面全部是 agent 可修复动作或应升级人工）；`--force` 不绕本门（评审 M4）；自动 `--chain` 的保守拒进；PASS/SKIP/FAIL 三态不引入 WARN 态——test_finish_structure_blocks_unstaged_dirty（T-S7）钉的正是「无暂存实现 + 产品侧未跟踪文件 ⇒ FAIL」的实质保护：若整体降 WARN，`finish --force` + 未提交实现将静默收口归档，门变虚。issue 提案②的「任务范围外降 WARN」以申报清单形态落地（显式、可审计、按仓声明一次），不做按卡隐式收窄。

### 2.2 最强反方与证伪条件 (Strongest Counterargument & Falsification)

* **最强反方论证**：申报清单让 agent 可以顺手把任意路径写进 config.yaml 把门「申报掉」——门强度从机器硬门倒退为 agent 自我申报。该反方同时否决了「整体降 WARN」备选（更弱）与「按适配器扫描面收窄」备选（空转态仓无扫描面，判据不可得）。
* **证伪条件**（评审 C1 修正后）：申报载体 = `.atlas/config.yaml`（与 workflow 参数同文件，架构正确），该文件**不入库** ⇒ 人审点不在 git diff，在**消费侧留痕**——① finish 申报豁免时 PASS reason 逐条列豁免清单（归档 task.json 在 `.atlas/tasks/` 白名单内入库可审）；② advance 申报消费 loud log 逐条列路径；③ 半暂存面不受申报影响恒 FAIL。判别检查：`discriminating_check{command: "归档 task.json 的 structure_freshness.reason 与 advance stdout 均逐条列出被豁免路径", expected_if_false: "任一消费位点静默吞掉申报清单"}`；构造半暂存 + 已申报同路径用例 ⇒ finish 必须 FAIL。
* **其他备选**：
  * 全局降 WARN —— 否决（见 2.1 不动段，T-S7 实质保护丢失）。
  * finish 时自动代跑 refresh —— 否决（refresh 写事实面，隐式写盘违反「不手写快照」纪律且放大失败面）。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* 存量项目：无 _meta.json / 非仓 ⇒ SKIP 不变；已开户仓拉新装配后行为不变（旋钮缺省空表 = 现状严格语义），仅报错文案更可执行。
* `.atlas/config.yaml` 模板加注释段：`--update` 保留既有文件不覆盖（既有语义），存量仓要新旋钮需手动加或删文件重建——文案里给片段即是兜底。
* 耗时：loader 一次正则扫描，无新增进程调用。
* 长期维护：一个旋钮 + 一处判据单源（refresh_structure.py），无新门、无新校验器；`--advance-baseline` 扩越后 facts 语义在脏树下 = 「人工背书的 worktree 态」，docstring 与 `shared/gates.md` §2.1 盲区列同步声明该例外。

**评审结论回填（2026-11-26，1C+4M+4m 全采纳）**：C1 申报载体矛盾（原「人审点 = git diff 根配置」为空心论证——`.atlas/config.yaml` 不入库且根 `atlas.config.yaml` 是 layout 专属面塞段会炸 `load_layout` 消费者，已改消费侧留痕三件套：finish reason 清单入归档 task.json / advance loud log / 半暂存恒 FAIL）；M1 匹配语义定案（`/` 结尾=前缀、否则精确 + 非法条目校验 + 负例钉）；M2 advance 侧补 `-c core.quotePath=false` 与 finish 同口径；M3 既有测试文案子串兼容显式承诺（T-S7「未暂存/未跟踪」、T-S6「refresh_structure.py」/「--advance-baseline」全保留，实测全绿）；M4 D-B 改述为时序脆弱性；m1 行号校正；m2 `docs/map/gates.md` 实为 L1 导航页不含 §2.1 正文（锚面 = `test_map_anchors` 计数锚）；m3 旋钮只认 `structure:` 段防跨段误命中；m4 override 被忽略面 loud log + 盲区列声明。

---

## 3. 改动面清单 (Affected Surface)

- [ ] **契约/文档**：`shared/gates.md` §2.1 新鲜度行改写 + 旋钮登记（`docs/map/gates.md` 为 L1 导航页不含本行正文，无需镜像——评审 m2；计数锚面 = `test_map_anchors`）
- [ ] **代码逻辑**：`scripts/refresh_structure.py`（loader + maybe_advance_baseline override 扩越 + docstring）、`_support/workflow_finish.py`（脏面三分诊 + 文案）、`install.py`（.atlas/config.yaml 模板注释段）
- [ ] **测试防线**：`tests/test_atlas_workflow.py` 新钉（declared-only PASS 留痕 / 半暂存恒 FAIL / 未申报 FAIL 含申报片段 / advance declared 推进 / advance 未申报仍拒 / override 脏树推进 loud log）+ 既有 T-S7~T-S11 回归
- [ ] **留出验证（§4.5）**：触发面 = 系统性修复（pipeline 上报）：pre-fix 红 = D-A/D-B 死锁复现用例；post-fix 绿 = 同用例经申报/背书通道可达 PASS；反面包 = 半暂存恒 FAIL
- [ ] **版本装配**：装配面变（install.py 模板）⇒ installer golden 干净 worktree 重录（fresh 场景）

---

## 4. 验证与测试结果 (Verification)

```bash
pytest tests/test_atlas_workflow.py
pytest tests/
python3 scripts/atlas_check.py --fast
```

* **测试结果**：2492 passed, 0 failed, 6 skipped（全量 11m15s；含新钉 T-S12~T-S15 + refresh_facts 四钉 + 既有 T-S6/T-S7/T-S9/T-S11 回归）
* **自检结论**：OK（`scripts/atlas_check.py --fast`；docs/map 计数/行数/符号锚经 `test_map_anchors.py --fix` 后全绿）
