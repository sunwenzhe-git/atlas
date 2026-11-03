# 实例⑤审查一键编排（atlas review）

> 提案编号：RFC-20261103-05
> 状态：已实现（Implemented，待评审/合并）
> 影响范围：脚本工具（scripts/）· 共享内核（_support/）· 契约（shared/）· 模板（templates/）· CLI（bin/）
> 关联：`RFC-20261103-01`（v4 scope manifest，本 RFC 的输入）；`shared/closeout.md` 步骤 10；`shared/independent-review.md` §10。
> 并行批避号：同日 `RFC-20261103-02/03/04` 已由另一会话占用，本批取 `-05`。

---

## 1. 现象与取证

### 1.1 触发形态

- **规则 / 环节**：`shared/closeout.md` 步骤 10（实例⑤实现代码独立审查）。
- **触发时机**：域实现落码后、域收口前。
- **具体行为**：步骤 10 是 6 步手工命令——组 background → `<cli> review --preview` 取 N → `<cli> review --format json` → `cli_review_convert` → `validate_review_report` → `review_closure`。每一步都要人记忆参数；`--scope-manifest`（RFC-01）又多一步，现场容易漏带，漏带后 v4 报告只 WARN「未复算」，门形同虚设。

### 1.2 客观证据

- `shared/closeout.md` 步骤 10 当前是 6 条手工命令（2026-11-03 实读），无单一入口。
- `shared/gates.md` 2.1 行记录实例⑤已接入：执行器 `ocr`，2026-10-31 真实仓副本 r1/r2 首跑已做；`README` 曾写「外部执行器接入中」，与 gates 行矛盾（2026-11-03 已修镜像面）。
- `templates/stack-profile.yaml` 无 `impl_review` 字段；`shared/stack-profile.md` §2 无该字段契约——采用者只能从 `closeout.md` 反推配置名。
- `shared/independent-review.md` §10 已定义执行器与 N/M，但无「编排器」入口。

---

## 2. 决策与权衡

### 2.1 核心定案

1. **新增 `scripts/atlas_review.py` + `atlas review` 子命令**，只做编排，不重写判据：
   - `atlas review --unit <需求ID> --from <ref> --to <ref> [--expected-files N] [--scope <描述>] [--round N] [--delta-only --base-sha <sha> --head-sha <sha>] [--reviewed-files a,b,c] [--cli <name>] [--background <file>] [--inputs/--no-inputs] [--dry-run] [--json]`
   - 内部顺序：`make_review_inputs`（可选，失败只 WARN）→ 组 background（指针化）→ preview 取 N → `<cli> review` 出 `cli.json` → 用 `coverage.completed`（或 `--reviewed-files`）生成 `scope-manifest.json` → `cli_review_convert` → `validate_review_report --scope-manifest` → `review_closure`。
   - 子步失败按原退出码透传；converter/validator 的 `FAIL`（exit 1）继续跑完后续观察步后整体 exit 1；输入错误（exit 2）立即停。
   - `--dry-run` 只跑 preview（只读）并打印将执行的命令，不写盘。
2. **`--cli` 覆盖默认 `impl_review.cli`**；`impl_review.llm` 为 null ⇒ `SKIP` + 原因（不算已审），与 `closeout.md` 前置一致。
3. **background 指针化**：不复制正文。自动生成 `background.md`，只写需求卡 / 域级 PRD / 用例分片 / `inputs/MANIFEST.json` 的路径与「审查焦点三问见 §10.4」；也接受 `--background` 显式文件。
4. **`impl_review` 字段进契约与模板**：`shared/stack-profile.md` §2 增 `impl_review: {cli, llm}`；`templates/stack-profile.yaml` 增注释块（`cli: null` / `llm: null`）；`_support/stack_profile.py` 的 `_DEFAULTS` / `_DICT_SECTIONS` / 段解析分支纳入 `impl_review`。
5. **真 CLI flag 形态出厂锁**：`atlas_review.py` 暴露 `PREVIEW_FLAGS` / `REVIEW_FLAGS`；测试读 `shared/closeout.md` 步骤 10 的两条命令，逐 flag 双向集合比对。契约改了、编排器没跟上 ⇒ 测试红。
6. **不做真实 `ocr` 冒烟**：当前环境无 `impl_review.llm` / `ocr` 配置；fixture 全链 + flag 锁先落，真实仓冒烟待有配置时补，登记观察行。

### 2.2 备选方案与否定理由

- **备选 A：把 6 步写成一个 shell 脚本**
  - 否定理由：参数解析、JSON 解析、失败分级、dry-run 都要重写；Python 与现有脚本同栈，且能被 `bin/atlas.js` 统一转发。
- **备选 B：让 `atlas review` 自己组装语义 background（摘要 + AC 摘录）**
  - 否定理由：编排器不调模型；摘录会造第二真相源。只给指针，语义由审查者读原文。
- **备选 C：默认全工作区 scope**
  - 否定理由：已在 RFC-01 否决（并行 WIP 恒假红）；本 RFC 只消费 `coverage.completed` 实审集。
- **备选 D：把真实 `ocr` 冒烟作为本批验收硬条件**
  - 否定理由：当前环境无配置；强行要求会把批次卡在环境上。fixture 全链 + flag 锁 + `--dry-run` 先保证编排正确；真实冒烟登记观察。

### 2.3 代价与兼容性

- `atlas review` 是新增入口，不改既有 6 步手工路径；`closeout.md` 只加一句「可用 `atlas review` 一键走全」，正文判据不复制。
- `impl_review` 字段进 parser defaults：既有 profile 未声明 ⇒ `None`，行为不变（`SKIP` 同旧）。
- `templates/stack-profile.yaml` 新增注释块：不影响既有项目解析；新装配项目可见字段。
- `--inputs` 默认开；项目无 PRD/E2E 资产时 `make_review_inputs` 失败只 WARN，不阻断审查。

---

## 3. 改动面清单

- [x] **契约/文档**：`shared/stack-profile.md` §2 `impl_review`；`shared/closeout.md` 步骤 10 一句「可用 atlas review」；`shared/gates.md` 2.1 实例⑤行补「一键入口」；`CHANGELOG.md`；`docs/map` 计数。
- [x] **代码**：新增 `scripts/atlas_review.py`；改 `bin/atlas.js`（`case 'review'` 转发）；改 `_support/stack_profile.py`（`impl_review` 解析）。
- [x] **模板**：`templates/stack-profile.yaml` 增 `impl_review` 注释块。
- [x] **测试**：新增 `tests/test_atlas_review.py`（fixture 全链 / dry-run / 失败透传 / SKIP / flag 形态锁 / `--cli` 覆盖）。
- [ ] **真实冒烟**：待有 `impl_review.llm` / `ocr` 配置的真实仓；不在本批硬条件。

---

## 4. 验证与测试结果

**实现批实跑（2026-11-03）**：

```bash
$ python3 -m pytest tests/test_atlas_review.py -q
13 passed in 5.74s

$ python3 -m pytest tests/test_atlas_review.py tests/test_shared_kernel.py \
      tests/test_install_selfcheck.py tests/test_canonical_consistency.py \
      tests/test_map_anchors.py -q
50 passed in 31.74s

$ python3 -m pytest tests/ -q
1106 passed, 5 skipped in 345.95s (0:05:45)
```

端到端手测（临时项目 + shebang fake CLI）：
- 全链 exit 0，产出 `background.md` / `cli.json` / `scope-manifest.json` / `review.json`（v4）/ `closure.json`；
- `review.json` `schema_version=4`，`review_scope.files[0].path=src/a.ts`；
- validator 行 `[PASS] 评审范围内容封口（v4）`。

**变异证明（四段协议）**：

| 变异 | 注入点 | 结果 | 还原 sha256 |
|---|---|---|---|
| M169 | `atlas_review.py` 的 validator argv 删掉 `--scope-manifest` | `test_full_chain_writes_v4_report` 红 | `6db3de5cef50…` |
| M170 | `parse_preview_n` 退回 `return None` | `test_full_chain_writes_v4_report` 红（exit 2） | `6db3de5cef50…` |

### 4.5 留出验证

- **触发面核对**：本 RFC 新增入口与 `impl_review` 字段，**不改门/校验器判据** ⇒ D156 路径：不适用；仍实跑路径交叉检查：`git diff --name-only` 命中 `scripts/atlas_review.py` / `_support/stack_profile.py` / `bin/atlas.js` / `shared/{stack-profile,closeout,gates}.md` / `templates/stack-profile.yaml` / `docs/map/*` / `tests/test_atlas_review.py`；`closeout_derive.py --diff-base HEAD` 输出「本轮改动 35 文件（自有对账面 20）；派生步骤 1 / 2 / 3 / 5 / 7」，并给 `_support/review_policy.py` / `_support/stack_profile.py` / `_support/review_scope_core.py` 三条未命中 WARN——`_support/` 不在触发表路径族，属既有缺口（RFC-01 §4.5 已登记），本 RFC 不扩族。
- **三态**：不适用（非系统性修复）；真实 `ocr` 冒烟未做，已在 §2.3 与观察行登记。


---

## 5. 验收判据

1. `atlas review` fixture 全链 exit 0，产出 `background.md` / `cli.json` / `scope-manifest.json` / `review.json`（v4）/ `closure.json`。
2. `--dry-run` 不写盘，stdout 含 preview / review / convert / validate / closure 五条命令与 N。
3. fake CLI exit 7 ⇒ atlas review exit 7（透传，不吞）。
4. `impl_review.llm` 为 null ⇒ `SKIP` exit 0，不写报告。
5. flag 形态锁：`shared/closeout.md` 两条命令的 flag 集合 == `PREVIEW_FLAGS` / `REVIEW_FLAGS`；契约改一处即红。
6. `--cli` 覆盖 stack-profile 的 `impl_review.cli`。
7. 全量测试绿；`shared/stack-profile.md` / 模板 / parser 三者字段一致。
