# 提案标题：无父级缺陷直填路由入口 + AGENTS.md atlas 指针块置顶注入

> 提案编号：RFC-20261126-02  
> 提案作者：@sunwenzhe-git  
> 关联状态：已定案 (Accepted)——tech-proposal-reviewer 双评修后通过（2026-11-26；3 Major + 5 Minor 全采纳），当日落刀  
> 关联 issue：#77（pipeline 自感知上报，2026-11-26）  
> 影响范围：脚本工具 (scripts) | 装配接线 (patches/project-wiring) | 技能面 (skills) | 装配模板 (install)

---

## 1. 现象与取证 (The Problem & Evidence)

### 1.1 触发形态（抽象）

* **规则 / 环节**：缺陷 canonical 落点（`atlas change`/`atlas bug`）与 AGENTS.md atlas 指针块注入。
* **触发时机**：
  * 用户口头报一个**无父级需求落点**的历史缺陷；`atlas change/bug` bootstrap 硬性要求 `--requirement <slug#R-NN>`（`_related_target` 校验父级落点存在 + 状态合法 + 条目存在）⇒ `bug_backflow_missing` 拒绝，无第二条路。eb25713（2026-11-26）刚把独立缺陷记录在 validate_bug_ledger + record 面拒收——治理立场正确，但把「无父级历史缺陷」逼到了墙角。
  * 采纳仓 AGENTS.md 较长（issue 实证 27157B）时，宿主规则窗口截断尾部（实证截去尾 3235B，atlas 块恰在 L422-445 全段丢失）⇒ agent 根本看不到 workflow 规则 ⇒ 直接改码手工评审跳过 atlas workflow。
* **具体行为**：agent 绕开执行层（无审查、无账本、无回推）；或卡在 `bug_backflow_missing` 反复重试同一拒绝路径。

### 1.2 客观证据与日志 (Minimal Evidence)

```text
scripts/atlas_bug.py:188-191   落点不存在 ⇒ 强制 --requirement <slug#R-NN> --report --stage（单通道）
_support/bug_backflow.py:108-127  _related_target：父级落点/状态/条目三重校验，无父级 ⇒ bug_backflow_missing
_support/bug_record.py:243-244   validate_record：**关联需求** 必填（eb25713 硬化）
patches/project-wiring/apply-wiring.py:70-74  wire_agents：无块 ⇒ 追加 EOF
issue #77 现场证据：AGENTS.md 27157B，宿主截尾 3235B，<!-- ATLAS:START --> 位于 L422-445 全段被截
```

**关键事实：直填门已存在、只是没有路由。** `atlas workflow plan --unit <ID>` 不带 `--requirement` 即直填模式（cmd_plan else 分支，旧行为逐字节保留）；直填卡无 `requirement_root` ⇒ `validate_backflow` 首行即 `applicable: False` ⇒ verify/finish 全流程畅通。缺的只是「让 agent 知道并走这条路」的入口。

---

## 2. 决策与权衡 (The Decision & Trade-offs)

### 2.1 核心定案 (The Decision)

**三件，路由级修复、零 schema 变更：**

1. **bootstrap 报错改双通道指引**：`atlas bug/change` 无既有落点时的报错文案从单通道改为——
   * 有父级需求 ⇒ `atlas change --unit <slug> --requirement <base#R-NN> --report <报告> --stage <stage>`（建变更/缺陷落点，走台账+回推封印）；
   * **无父级需求（历史遗留缺陷）⇒ `atlas workflow plan --unit <slug>` 直填建卡**（现象/证据写任务卡 PRD，走同一条独立审查 + finish 门，不建变更/缺陷落点）。
2. **路由入口写进两处技能面**：`skills/atlas-change/SKILL.md` 增「无父级缺陷路由」节；`patches/project-wiring/agent-pointer.md` 增一行路由口径（口头报缺陷先判父级：有父级走 atlas change；无父级走 workflow plan 直填）。
3. **指针块置顶注入**：`apply-wiring.py::wire_agents` 改三态——(a) 块不存在 ⇒ **文件头前置**（保留全部原内容）；(b) 块存在且不在头部 ⇒ 原位摘除 + 头部前置（迁移语义，幂等收敛到置顶）；(c) 块已在头部 ⇒ 原位替换（现状幂等路径）。存量仓下次 `atlas init --update` / `install.sh --update` 自动迁移。`tests/test_project_wiring.py` 断言面从「追加 EOF」改「置顶」。

**为何正解**：#77 三个子项同根——入口只在文档尾部 + 台账面强绑定，让 agent 在「宿主截断 + 无父级」叠加场景下只剩绕开 workflow 一条路。直填路由给无父级缺陷一条**带审查的正规通道**（保留 eb25713「缺陷台账必须锚定需求」治理立场：要台账就必须有父级；无父级就别建台账，但审查与收口门一分不少），置顶让入口免遭截断。

### 2.2 最强反方与证伪条件 (Strongest Counterargument & Falsification)

* **最强反方论证**：置顶注入改宿主文档首屏——AGENTS.md 开头常是项目简介 / 角色设定，atlas 块插队改变阅读优先级；且存量仓迁移会让 `git diff` 出现大段块位移噪音。该反方同时否决了「EOF 注入 + 压缩块体积」备选（压缩不可控宿主窗口上限）与「注入第一个标题后」备选（宿主文档结构多样，有/无 H1、front-matter 皆有可能，判据复杂且仍可能落入截断窗）。
* **证伪条件**：块自带 `<!-- ATLAS:START/END -->` 标记与「由 install.py 幂等维护」尾注，宿主语义是规则叠加非替换；EOF 截断是实测已发生故障（issue 证据 27157B/截 3235B），置顶是唯一结构性防截断位。判别检查：`discriminating_check{command: "head -1 <采纳仓>/AGENTS.md", expected_if_false: "<!-- ATLAS:START -->"}`——若某宿主被实证对**头部**做截断（窗口取头弃尾的反向形态），本方案错，回退 EOF 并另案。
* **直填路由反方**：无父级缺陷不进台账 ⇒ 反查面（`atlas change list`）缺失。证伪：直填卡仍在 `.atlas/tasks/` 账本内（task.json + PRD + 审查报告 + attempts 台账齐全），追溯面不缺；缺的只是 change 台账的 diff 级回推封印——那是「有父级才建台账」立场的直接推论，非缺陷。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)

* 存量仓 `--update` 后 AGENTS.md 块从尾部迁移到头部：一次性 diff 噪音，内容逐字节不变（除位置）；「标记不成对」保护不变（评审 m3 扩展：标记计数 ≠1（含多对粘贴复读）一律报错不改）。迁移通道例外（评审 m2）：profiles `audit`/`adopt` 为 `--no-wiring`，`--update` 不重跑接线 ⇒ 该两类宿主迁移不自动发生，需手动 `python3 .atlas/patches/project-wiring/apply-wiring.py --target . --apply`；常规通道 = `bash install.sh --update`。
* `atlas bug` 是 `atlas change` 兼容别名：文案改动单点（bootstrap 报错），两命令同吃。
* 装配面变（apply-wiring.py + agent-pointer.md）⇒ installer golden 干净 worktree 重录。
* 长期维护：无新门、无新字段；一处注入函数 + 两处文档。

---

## 3. 改动面清单 (Affected Surface)

- [ ] **代码逻辑**：`patches/project-wiring/apply-wiring.py`（wire_agents 三态置顶）、`scripts/atlas_bug.py`（bootstrap 双通道文案）
- [ ] **技能/装配内容**：`skills/atlas-change/SKILL.md`（路由节）、`patches/project-wiring/agent-pointer.md`（路由行）
- [ ] **契约/文档**：`shared/gates.md` §2.5 接线门册行（评审 M1 必补：置顶三态语义 + 用例计数锚 8→12）；`patches/project-wiring/README.md` 措辞同步；`DESIGN.md` 新增 D215 行（评审 m5：防后来者按 D73 历史 EOF 描述「修回」）；`docs/guide/` 无「末尾/EOF」措辞（已核）
- [ ] **测试防线**：`tests/test_project_wiring.py`（置顶三态新钉 + 不成对保护回归）；`tests/test_cli_commands.py` 或 bug 面测试（报错文案含双通道）；golden 重录（fresh 等涉 wiring 场景）
- [ ] **留出验证（§4.5）**：触发面 = 系统性修复（pipeline 上报）：pre-fix 红 = 27KB+ 截断形态 / 无父级报错单通道；post-fix 绿 = 置顶存活 + 双通道文案可达直填卡 finish PASS；反面包 = 不成对标记仍拒绝修改
- [ ] **版本装配**：同 RFC-20261126-01 一并重录 golden、一并发版

---

## 4. 验证与测试结果 (Verification)

```bash
pytest tests/test_project_wiring.py tests/test_apply_wiring.py
pytest tests/
python3 scripts/atlas_check.py --fast
```

* **测试结果**：2492 passed, 0 failed, 6 skipped（全量 11m15s；wiring 12 例 + bug 双通道文案钉；test_apply_wiring 23 例零改动全绿）
* **自检结论**：OK（`scripts/atlas_check.py --fast`；docs/map 计数/行数/符号锚经 `test_map_anchors.py --fix` 后全绿）
