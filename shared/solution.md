# atlas 共享契约 — 多仓方案层（solution，Phase 1）

> **状态**：Phase 1（2026-11-04）。只做 `federated` 的只读整合；`unified`、成员代码提交、import/export、multi-root impact/closeout 属 Phase 2/3，见源包提案 RFC-20261104-02（装配态无 proposals）。
>
> 本层不复制 PRD / 域事实 / E2E；它只拥有清单、锁、父级 PRD 与跨仓声明。资产归属的单源是 `atlas.solution.yaml` 的 `members[].assets`。

## 1. 落点

```text
<solution 根>/
├── atlas.config.yaml            # 布局（assets_root），由 _support/layout.py 解析
├── atlas.solution.yaml          # 本契约：members / mode / assets / contracts
├── atlas.solution.lock.json     # 成员 HEAD + 契约文件指纹（人工 lock --update）
├── .atlas/                      # solution 层 Atlas 装配（Phase 1 只读检查所需）
├── <assets_root>/               # 父级 PRD / E2E / solution stack-profile
│   ├── stack-profile.yaml
│   ├── prd/prd.md               # 产品级需求源
│   ├── prd/solution-prd.md      # 跨仓域级 PRD（完整域形态）
│   └── prd/README.md            # 追溯总表（含 solution 行）
└── <member>/                    # 成员仓：untracked、不 ignore、保留自己的 .git
```

- solution 根是独立 git 仓，只跟踪 Atlas 资产、清单、锁、父级 PRD；成员目录 **untracked 且不被任何 ignore 规则覆盖**。
- 禁止在 solution 根 `.gitignore` / `.ignore` / `.rgignore` / `.git/info/exclude` 命中成员；否则 Qoder Grep 与 cgc 图谱会失明。
- 禁止设置 `status.showUntrackedFiles=no`；所有消费者用 `--untracked-files=all` 并逐成员根过滤。

## 2. 清单字段（Phase 1）

| 字段 | 必需 | 语义 |
|---|---|---|
| `version` | 是 | 固定 `1` |
| `solution` | 是 | 方案名 |
| `mode` | 是 | Phase 1 仅 `federated`；`unified` 显式拒绝 |
| `members[].name` | 是 | 成员标识，solution 内唯一 |
| `members[].path` | 是 | 相对 solution 根；拒绝绝对路径 / `..` / Atlas/Trellis 内部目录 |
| `members[].assets` | 是 | Phase 1 仅 `member` |
| `members[].kind` | 否 | `frontend` / `backend` / `fullstack` / `mobile`；供 solution stack-profile |
| `contracts[].id` | 否 | 唯一 |
| `contracts[].producer` / `consumer` | 否 | 必须是 members 名称 |
| `contracts[].producer_path` / `consumer_path` | 否 | 相对各自成员仓的文件路径 |
| `requirements` | 否 | Phase 1 只登记存在性，不解析 |

模板：`templates/atlas.solution.yaml`（字段样板；运行期解析以本契约为准，模板不参与判定）。

## 3. 命令（Phase 1）

```bash
atlas solution init --name <名> --member <名>=<路径> [--member ...]  # 一次创建 solution 层
atlas solution adopt [--name <名>] [--member <名>=<路径> ...]        # 识别已有成员资产
atlas solution status                                               # 只读聚合
atlas solution check                                                # 只读检查（语义全 WARN）
atlas solution lock --update                                        # 人工刷新锁
```

- `init` 装配完整 `.atlas`（共享契约 / 校验器 / 脚本；`--no-trellis` 跳过 Trellis 初始化与 `.trellis` 骨架），不修改成员仓。
- `adopt` 不移动、不复制成员资产；自动识别直属子目录中「git 仓 + Atlas 资产」的成员。
- `check` 的 manifest schema / 路径逃逸是输入错误（exit 2）；成员非 git、缺 Atlas 资产、被 ignore、被跟踪/gitlink、锁漂移、PRD 骨架未补齐 ⇒ WARN。
- `commit` 入口保留给 Phase 2；Phase 1 调用时显式报「未交付」。

## 4. 父级 PRD

- `prd.md` 是产品级需求源；`solution-prd.md` 是跨仓域级 PRD，必须按 `templates/prd/domain.md` 完整形态落盘：`domain: solution`、`domain_code: SOLUTION`、`AC-SOLUTION-NNN`（三位）、FN/R/AC、§五三列 AC 表、结构类 AC 清单；`prd.md` §五列出 `solution`，README 追溯行 7 列且计数一致。
- Phase 1 的 `solution check` 只提示「骨架未补齐」；完整形态由既有 PRD 校验器在用户补齐后验证。

## 5. 跨仓契约锁

- `lock --update` 记录成员 HEAD / branch / member `_meta.json.baseline` 与契约文件 `sha256`。
- `check` 只对漂移发 WARN，不判断语义兼容；跨仓契约的语义兼容归人工/独立评审。
- 成员内部改动不改变 solution 根 `git status`；Phase 2 的 baseline/freshness 必须把成员 HEAD + dirty 纳入。

## 6. Phase 2/3 边界（显式盲区）

- `unified`：solution 拥有唯一资产集、成员只提供代码根；需要 baseline v2 + 成员 SHA 向量 + 多根 freshness / impact / closeout。
- `solution_commit --member`：按成员仓提交代码（Phase 2）。
- `import` / `export`：成员资产迁移（Phase 3；旧源删除，历史归 git）。
- solution 级 Trellis `packages`：Phase 1 不创建 `.trellis/`；若 solution 根已有 `.trellis/config.yaml`，`check` 只做成员 `path` 文本校验（不校验 `git: true`）；生成与完整语义校验归 Phase 2。
- 跨仓代码图谱 / 调用链影响面不在 Phase 1。

## 7. 相关契约

- 布局：`shared/layout.md`
- 技术栈画像：`shared/stack-profile.md`
- 门登记：`shared/gates.md`
- 单一真相源迁移纪律：`shared/single-source.md`
