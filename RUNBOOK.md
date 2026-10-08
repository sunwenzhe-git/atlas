# atlas 复现手册（RUNBOOK）

> **换工作区 / 重跑整个 atlas 时先读本文件**，按 §0 → §1 → §2 → §3 → §4 顺序执行。
> 只记**可操作步骤与前置**；设计依据见 `DESIGN.md` 与知识库（vault 内 `<vault>/atlas/`，契约 `shared/knowledge.md`），执行契约见 `shared/` + `rings/*/reference.md` + `apply/reference.md`。

---

## 0. 前置：Trellis CLI 版本必须匹配项目

目标项目 `.trellis/.version` 记录生成该项目的 Trellis 版本；**全局 CLI 必须 ≥ 该项目版本**——否则 `trellis update` 的行为不代表项目版本，Plan 挂载补丁（`patches/workflow-plan-apply/`）可能被 `trellis update` 冲掉（未决 B2）。

```bash
trellis --version                       # 全局 CLI
cat <项目根>/.trellis/.version          # 项目 pin
```

- 落后就升：`trellis upgrade --tag <项目版本>`（或 `--tag beta` 取最新 beta）；先 `--dry-run` 看命令。
- 两行版本号必须相等（或全局 CLI 更高）。**本文件不写死版本号**——它随升级立刻过期（§5 的“写死计数无对账”教训：对账靠上面两条命令）。换机 / 换工作区后**必须重做本步**。
- 注意：`trellis update` 会把 `.trellis/config.yaml` 的**本地改动**视为冲突并覆盖——atlas 的 `after_finish` hook（`refresh_structure.py`）由 §1 的 **`install.sh` 第 6 步接线自动登记**（幂等），升级后重跑 `install.sh` 即恢复（或升级时选保留本地版本）。同理，`AGENTS.md` 的 atlas 指针段由该步写入 Trellis 区块**外**，不受 `trellis update` 覆盖。

### 0.5 图谱前置（可选；profile 声明 `graph.backend` 的项目才需要）

```bash
cgc --version                      # 后端（CodeGraphContext，MIT）；uv tool install codegraphcontext
```

- **文法缓存预热（一次性）**：cgc 首次索引会从 GitHub Releases 联网下载 tree-sitter 文法 dylib——GitHub 资产直连不通的环境**必挂代理跑一次**（缓存落 `~/Library/Caches/tree-sitter-language-pack/`，之后永久离线可用；缺失时消费者表现为长时间无输出，勿误判为死锁）：

  ```bash
  https_proxy=http://127.0.0.1:7897 python3 -c "from tree_sitter_language_pack import download; download(['python','typescript','javascript','tsx','bash','java'])"
  ```

- 纪律：图谱消费者**用前现刷**（`_graph.py` ensure_index，见 `shared/stack-profile.md` §3.6）；install.sh 对声明了 graph 的项目自动探测 cgc（缺失 = WARN 不阻断，消费者运行时显式 `not_ready` / 降级）。

---

## 1. 装配 atlas 包

```bash
bash atlas/install.sh --target <项目根> --dry-run   # 先看计划（本工作区惯用 --target codebases）
bash atlas/install.sh --target <项目根>             # 实装
```

装：整包 → `<项目根>/.atlas/`；5 个 skill 瘦桩（`atlas-{structure,prd,e2e,apply,design-review}`）→ `.claude/skills/` 与 `.agents/skills/`；`product/` 骨架（三环，**不建**已退役的 `product/prototype/`）；**Plan 挂载补丁打进 `.trellis/workflow.md`**（锚点幂等；`--no-patch` 可跳过）；**项目接线**——`AGENTS.md` 的 atlas 指针段 + `.trellis/config.yaml` 的 `after_finish` hook（幂等；`--no-wiring` 可跳过）；并**清理历史单入口 `atlas` skill 与源包已退役的 `atlas-*` 瘦桩**（实例：E1 退役的 `atlas-prototype`）。

- 已装配过的目标默认**硬停**（`ATLAS_ALLOW_OVERWRITE=1` 显式越过）——防分歧窗口内旧源包覆盖副本侧改动；新项目开户与 `--dry-run` 不受限。

- 补丁目的 = 在 Phase 1 插 `#### 1.6 项目级资产更新` + `[workflow-state:planning]` 面包屑 enforcement（决策 D64/D66）。
- 手动重放补丁（Trellis 升级后）：

```bash
python3 atlas/patches/workflow-plan-apply/apply-patches.py \
  --target codebases --spec atlas/patches/workflow-plan-apply/spec.json --apply
```

---

## 2. 首建项目级资产（三环全量）

按 `结构 → PRD → E2E`：逐个触发 `atlas-structure` / `atlas-prd` / `atlas-e2e`，或用 `atlas-apply` 的 `all` 模式一次按序跑三环（**E1：原型环已移除**，2026-09-27；应然 UI 的 testid 应然随用例分片产出，见 `rings/e2e/reference.md` §4/§6.2）。

- **门控**：`product/prd/prd.md` §零若有待决策，PRD 只产全局、E2E 只落空骨架——先清零产品待决策再往下。
- 结构事实落 `.trellis/spec/structure/`；A（技术栈/启动）与 H（测试/运行）落项目根 `README.md`。

---

## 3. 接需求（需求式增量）

走 Trellis Plan（原生入口）；其 **1.6 步**自动调 `atlas-apply` 的 `apply <需求ID>`：

读需求卡 → 推导影响面 → 按 `prd → e2e` 增量更新（E1：原型环已移除）→ 跑机器校验 → 写 `.trellis/tasks/<需求ID>/atlas-apply.md`。

**需求 ID = Trellis task id**；**需求卡 = 该 task 的 `prd.md`**。

---

## 4. 收口

**收口按 `.atlas/shared/closeout.md` 逐步跑**（门自检 → 装配面核对 → 台账对账 → vault 同步 → 回灌登记 → 知识库 rebuild → 提交）；**门总账** = `.atlas/shared/gates.md`（一门一行、含显式盲区与取证等级；**不在表 = 不存在**）。

实现后：真实应用跑 E2E（**E1 单段**：`stack-profile.yaml` 的 `e2e.app_base_url`）→ 全 `green`（或 `blocked` 带原因）→ `after_finish` hook 刷结构事实（`refresh_structure.py`）→ Trellis `update-spec` + `finish`。

- `e2e.app_base_url` 为空 ⇒ E2E 跑不起来：`atlas_check` 记 **`SKIP`**（显式可见跳过），**不得**当作已验收。真栈跑通前，E1 口径下的实现类工作无法验收。
- 首跑前先读 `rings/e2e/reference.md` §5.4 的**首跑分类协议**（mock 语义残留 / 命名漂移 / 真缺陷三分类，不分类不得批量回写状态）。

---

## 5. 状态自检（换机 / 接手先跑；**不在此处写死状态**）

状态随每轮变化，写死即过期（实例：本节曾是 2026-09-20 的快照，三轮后仍在报“四环已就绪 / 原型待跑”）。**当前进度与下一步的唯一落点** = 知识库 `<vault>/atlas/2026091715433508-atlas-discussion-log` 顶部的「当前进度 / 待办」节（vault 路径从 `product/stack-profile.yaml` 的 `knowledge.vault` 读）。

```bash
trellis --version && cat .trellis/.version      # 版本对齐（§0）
ls .atlas/rings/                                # 期望：e2e prd structure（三环）
ls <平台>/skills/atlas-*                        # 期望：atlas-{structure,prd,e2e,apply,design-review}
python3 .atlas/scripts/atlas_check.py --root . --fast   # 门一行一门：ok|FAIL|WARN|SKIP
```

- 结果里 `SKIP` 是**一等结论**（“未走到这一步”），不是通过；红/绿结论以门自己的输出为准。

---

## 6. 改 atlas 包之后

- 改契约 / 模板 / 校验器：先改 `atlas/`（canonical），再重跑 `install.sh` 同步到目标项目（已装配过的目标需 `ATLAS_ALLOW_OVERWRITE=1`）。
- 跑回归：`python3 check-all.py`（或 `--only atlas`）。
- **容器与装配面是同一条判据面**：`install.sh` 的自检只检查“它在装配时声称会落下的文件” ⇔ 包内确实存在（`tests/test_install_selfcheck.py`）。新增/删除包内件时它必须一起绿，否则新项目开户会以“装配失败”退出。
- 同步知识库：按 `shared/knowledge.md`，写 vault 内 `<vault>/atlas/`（改契约 → 对应环 note + 3507/3508；未决变化 → 3509）。

### 机器校验命令（改过 `product/` 后跑）

```bash
python3 .atlas/scripts/atlas_check.py              --root .         # 门总览（逐行读；SKIP 必须带原因）
python3 .atlas/validators/validate_stack_profile.py --root .
python3 .atlas/validators/validate_structure.py     --root .
python3 .atlas/validators/validate_prd.py           --root .
python3 .atlas/validators/validate_testids.py       --root .
python3 .atlas/validators/validate_e2e_index.py     --root .
python3 .atlas/validators/validate_design_exemptions.py --root .   # 设计档案 detect 豁免 ⇔ .impeccable 配置；无档案 SKIP
python3 .atlas/scripts/gen_e2e_scripts.py           --root . --apply   # 需 e2e.app_base_url
python3 .atlas/scripts/refresh_structure.py         --root . --apply
```

---

## Guidance

换工作区重跑时**按 §0 → §1 → §2 → §3 → §4 顺序**；**§0 的 CLI 版本核对不能跳**——否则 `trellis update` 会冲掉 `#### 1.6` 挂载补丁。改动 `atlas/` 后跑 `python3 check-all.py` 并同步 Obsidian。
