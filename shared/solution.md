# atlas 共享契约 — 多仓方案层（solution，Phase 1）

> **状态**：Phase 1（2026-11-04）+ solution task 增量（2026-11-05）+ 可复现锁 / `check --strict` 增量（2026-11-07，`[Unreleased]`）。父级只做只读整合与**窄写成员任务卡**（`.trellis/tasks`）；`unified` 与成员代码提交属 Phase 2，`import`/`export` 属 Phase 3，多 host / `targets[]`、跨仓影响面与图谱、成员拆分导出属 Phase 4 可选增强，见源包提案 RFC-20261104-02 / RFC-20261105-02（装配态无 proposals）。
>
> 本层不复制成员 PRD / 域事实 / 成员 E2E；父仓持有跨仓 E2E，成员保留本地 E2E。父仓跨仓 E2E 的清单选择器是 `requirements[].case_ids`：**多成员需求必须有 `case_ids`（禁止 `cross_repo_e2e: none`）**；单成员需求 `case_ids` 或 `cross_repo_e2e: none` 二选一，两者都无 ⇒ `solution check` FAIL。资产归属的单源是 `atlas.solution.yaml` 的 `members[].assets`。

## 1. 落点

```text
<solution 根>/
├── atlas.config.yaml            # 布局（assets_root），由 _support/layout.py 解析
├── atlas.solution.yaml          # 本契约：members / mode / assets / contracts
├── atlas.solution.lock.json     # 成员 url/branch/commit + 契约指纹；被父仓 Git 跟踪，作为可复现基线
├── .atlas/                      # solution 层 Atlas 装配（Phase 1 只读检查所需）
├── <assets_root>/               # 父级 PRD / E2E / solution stack-profile
│   ├── stack-profile.yaml
│   ├── prd/prd.md               # 产品级需求源
│   ├── prd/solution-prd.md      # 跨仓域级 PRD（完整域形态）
│   └── prd/README.md            # 追溯总表（含 solution 行）
└── <member>/                    # 成员仓：untracked、不 ignore、保留自己的 .git
```

- solution 根是独立 git 仓，只跟踪 Atlas 资产、清单、锁、父级 PRD；成员目录 **untracked 且不被任何 ignore 规则覆盖**。
- 锁文件必须被父仓 Git 跟踪且与父仓 `HEAD` 一致；否则 `check --strict` 判 `FAIL`（CI 无法还原锁定版本）。
- 禁止在 solution 根 `.gitignore` / `.ignore` / `.rgignore` / `.git/info/exclude` 命中成员；子目录下的同名 ignore 文件沿成员路径逐级检测。
- 禁止设置 `status.showUntrackedFiles=no`；所有消费者用 `--untracked-files=all` 并逐成员根过滤。

## 2. 清单字段（Phase 1）

| 字段 | 必需 | 语义 |
|---|---|---|
| `version` | 是 | 固定 `1` |
| `solution` | 是 | 方案名 |
| `mode` | 是 | Phase 1 仅 `federated`；`unified` 显式拒绝 |
| `members[].name` | 是 | 成员标识，solution 内唯一 |
| `members[].path` | 是 | 相对 solution 根；拒绝绝对路径 / `..` / Atlas/Trellis 内部目录；若已被父仓跟踪（含 mode 160000）则 init/adopt 直接拒绝 |
| `members[].url` | 否 | 远端地址；仅 `http/https/ssh/git/file` 或 `user@host:path`；禁止内嵌 userinfo / token，检测到即拒绝写入清单与锁 |
| `members[].assets` | 是 | Phase 1 仅 `member` |
| `members[].kind` | 否 | `frontend` / `backend` / `fullstack` / `mobile`；供 solution stack-profile |
| `contracts[].id` | 否 | 唯一 |
| `contracts[].producer` / `consumer` | 否 | 必须是 members 名称 |
| `contracts[].producer_path` / `consumer_path` | 否 | 相对各自成员仓的文件路径 |
| `requirements[].id` | 否 | 父级需求 ID；与 `member` 组合唯一 |
| `requirements[].acs` | 否 | 父级 AC ID，顿号/逗号分隔；必须是 `solution-prd.md` AC 表的定义行 |
| `requirements[].member` | 否 | 必须是 members 名称 |
| `requirements[].task_slug` | 否 | Trellis slug；不含路径分隔符 / `..` / `MM-DD-` 前缀；创建后冻结 |
| `requirements[].scope` | 否 | 单行本地 scope；含 `#` 时必须加引号；只在成员任务 `solution.md` 中展开 |
| `requirements[].assignee` | 否 | 可选；缺省 = 成员 `.trellis/.developer` |
| `requirements[].case_ids` | 否 | 父仓跨仓 E2E 的**需求级选择器**，逗号/顿号分隔；用例 ID 文法见 `rings/e2e/reference.md` §5.3。同一 `requirement.id` 最多一行携带；不得与 `cross_repo_e2e` 同时出现 |
| `requirements[].cross_repo_e2e` | 否 | 唯一合法值 `none`；只允许**单成员需求**用它声明「没有跨仓 E2E」。同一 `requirement.id` 最多一行携带 |

**父仓跨仓 E2E 选择器口径**（RFC-20261108-02 一期）：

- **多成员需求**（同一 `requirement.id` 出现 ≥2 个 `member` 行）**必须**给 `case_ids`；写 `cross_repo_e2e: none` 或两者皆无 ⇒ `solution check` FAIL。
- **单成员需求** `case_ids` 或 `cross_repo_e2e: none` 二选一；两者皆无 ⇒ `solution check` FAIL。
- `case_ids` 是唯一选例真相；索引的 `需求` / `关联AC` 列只做追溯与人读。
- `关联AC` 一格可写多值（分隔符 `、` / `,` / `，`，逐 token 去首尾空白、逐 token 判 `AC-<CODE>-NNN`）；父仓 AC 挂靠统计按 token 拆分后求交（RFC-20261111-03 §1.6）。
- 父仓资产落点与入口见 `rings/e2e/reference.md` §10.1；`atlas solution e2e init` 幂等补 `e2e-index.md` 骨架，`--migrate` 为存量用例批量补 `成员依赖:`。

模板：`templates/atlas.solution.yaml`（字段样板；运行期解析以本契约为准，模板不参与判定）。

默认模式与 RFC 一致：Phase 1 只接受 `federated`；Phase 2 交付后，绿地项目（无成员资产）恢复默认 `unified`，已有成员资产仍默认 `federated`，`--mode` 可覆盖。

## 3. 命令（Phase 1）

```bash
atlas solution init --name <名> --member <名>=<路径> [--member ...]  # 一次创建 solution 层（清单 / 锁 / 骨架，不迁移成员资产）
atlas solution adopt [--name <名>] [--member <名>=<路径> ...]        # 识别已有成员资产
atlas solution status                                               # 只读聚合
atlas solution diff                                                 # 只读对账：成员相对锁的提交/改动
atlas solution check [--strict]                                     # 默认 WARN（AC 定义行默认 FAIL）；--strict = CI 门禁
atlas solution check --fix-acs [--apply]                            # dry-run 列出悬空 AC；--apply 行级保字节写回后重跑 gate
atlas solution check --allow-dangling-acs                           # 临时宽限：仅 A 类悬空降 WARN（0.3.0 移除 / 最迟 2026-12-31）
atlas solution lock --update                                        # 人工刷新锁（拒绝 detached HEAD）
atlas solution task create --requirement <REQ> [--dry-run|--apply]   # 父级需求 → 成员任务卡
atlas solution task status [--requirement <REQ>]                     # 只读对账
```

- `init` / `adopt` 写清单前执行 `git ls-files -s`：成员路径已被父仓跟踪（普通文件或 `160000` gitlink）直接拒绝，并给出 `git rm --cached` / 移除 `.gitmodules` 的修复指引；不再降级为 WARN。
- `init` 只在成员齐全且都不在 detached HEAD 时自动写入首版锁；成员未 clone 时暂不写，避免 `head: null` 的假锁。
- `adopt` 不移动、不复制成员资产；自动识别直属子目录中「git 仓 + Atlas 资产」的成员。
- `diff` 只读对账：按成员输出自锁以来的 commit / diffstat、已暂存 / 未暂存 / 工作区改动；锁中 commit 不在本地时显式提示先 fetch。
- `check` 的 manifest schema / 路径逃逸是输入错误（exit 2）；默认模式下成员非 git、缺 Atlas 资产、被 ignore、被跟踪/gitlink、锁漂移、PRD 骨架未补齐 ⇒ WARN。
- `check --strict` 把以下升为 `FAIL` 并返回 exit 1：锁缺失、锁未被父仓跟踪或与父仓 `HEAD` 不一致、锁↔清单 `url/path` 不一致、成员 dirty 或 dirty 无法判断、缺 URL、成员/契约版本漂移；`requirements[].acs` 引用方案 PRD 中不存在的 AC 定义行**默认即 FAIL**（`--allow-dangling-acs` 只宽限「PRD 定义非空」的 A 类悬空，写死 `0.3.0` / `2026-12-31` / `@sunwenzhe`；PRD 缺失 / 路径不匹配 / 零定义共用空集 guard ⇒ FAIL，不适用宽限）。除 AC 定义行外，其余默认仍为 WARN。采纳仓不跑 `solution check --strict` 就等于没有这道门（最小 CI 样例见 §5.1）。
- `task create` 默认 dry-run，`--apply` 才写成员 `.trellis/tasks`：固定 `--no-start`（不领取）、用 `--meta solution/requirement/member` 做幂等、写 `solution.md` 指针并 `add-context`；不写代码/资产/PRD，不自动 commit。重复/失败显式报告；`--resume`/`--update` 只处理已有任务。
- `commit` 入口保留给 Phase 2；Phase 1 调用时显式报「未交付」。

### 3.1 已交付 vs 本次新增（`[Unreleased]`）

| 能力 | 状态 |
|---|---|
| `init` / `adopt` / `status` / `check` / `lock` / `task`（federated） | Phase 1 已交付（2026-11-04/05） |
| `members[].url`、scheme 白名单、内嵌凭据拒绝 | 本次新增，未发布 |
| 锁被父仓跟踪 / 与 HEAD 一致、锁↔清单 url/path 对账、dirty 判据、detached 拒绝 | 本次新增，未发布 |
| `solution diff`（成员相对锁的提交 / diffstat / 工作区对账） | 本次新增，未发布 |
| `check --strict`（CI 门禁，`overall=FAIL` → exit 1） | 本次新增，未发布 |

## 4. 父级 PRD

- `prd.md` 是产品级需求源；`solution-prd.md` 是跨仓域级 PRD，必须按 `templates/prd/domain.md` 完整形态落盘：`domain: solution`、`domain_code: SOLUTION`、`AC-SOLUTION-NNN`（三位）、FN/R/AC、§五三列 AC 表、结构类 AC 清单；`prd.md` §五列出 `solution`，README 追溯行 7 列且计数一致。
- Phase 1 的 `solution check` 只提示「骨架未补齐」；完整形态由既有 PRD 校验器在用户补齐后验证。

## 5. 跨仓契约锁

- 锁是**可复现基线**：必须被父仓 Git 跟踪，且与父仓 `HEAD` 一致；`check --strict` 以此作为 CI 判据。
- `lock --update` 记录成员 `url / path / branch / head(commit)`、member `_meta.json.baseline` 与契约文件 `sha256`。成员处于 detached HEAD（`branch` 为 `HEAD`）时**拒绝写入**，避免锁里出现不可复现的分支名。
- 锁与清单必须一致：`path` 完全一致；`url` 完全一致（两边都空 ⇒ `--strict` FAIL）。旧锁缺少 `url` 时需重新 `lock --update` 并提交。
- 成员工作区 dirty，或无法判断（`git status` 失败）⇒ `--strict` FAIL；默认 `check` 只 WARN。
- 默认 `check` 只对漂移发 WARN，不判断语义兼容；跨仓契约的语义兼容归人工/独立评审。
- 成员内部改动不改变 solution 根 `git status`；Phase 2 的 baseline/freshness 必须把成员 HEAD + dirty 纳入。
- URL 安全：只接受 `http/https/ssh/git/file` 或 `user@host:path`；http(s) userinfo、任意形式的密码、token/签名查询参数一律拒绝写入清单与锁（避免凭据落盘）。
- 父仓只存清单、锁与父级 PRD/骨架；成员代码与成员 Atlas 资产留在成员仓，不迁移（`unified` 属 Phase 2，`import`/`export` 属 Phase 3）。
- 风险：成员目录是 untracked。在 solution 根执行 `git clean -ffdx` 会删除整个成员工作区及未提交改动；不要把它当作安全清理命令。
- 路径安全：`members[].path` 逃逸根目录直接输入错误；成员 symlink 指向根外时，契约文件哈希返回 `missing`，**不读取根外文件**。

### 5.1 CI 按锁还原（父仓只存清单与锁）

CI 不依赖任何自动还原命令：按 `atlas.solution.lock.json` 逐成员 clone + checkout，再跑 strict。

```bash
set -euo pipefail
git clone <solution-repo> solution
cd solution
git checkout <parent-ref>          # 回滚时切到目标父仓 commit，锁随之还原

node -e '
const fs = require("fs"), cp = require("child_process");
const lock = JSON.parse(fs.readFileSync("atlas.solution.lock.json", "utf8"));
for (const m of lock.members) {
  if (!m.url || !m.head) throw new Error(`成员 ${m.name} 缺少 url/head`);
  if (!fs.existsSync(m.path)) cp.execFileSync("git", ["clone", "--", m.url, m.path], { stdio: "inherit" });
  cp.execFileSync("git", ["-C", m.path, "fetch", "--all", "--prune"], { stdio: "inherit" });
  cp.execFileSync("git", ["-C", m.path, "-c", "advice.detachedHead=false", "checkout", "--detach", m.head], { stdio: "inherit" });
}
'
atlas solution check --strict
```

- 该 checkout 是 detached HEAD，仅用于 CI / 回滚；日常开发在成员仓自己的分支上进行。
- 锁必须随父仓提交；`check --strict` 会校验锁与父仓 `HEAD` 一致。
- 锁中 commit 不在本地时，先对相应成员 `fetch`。

## 6. Phase 2/3/4 边界（显式盲区）

- `unified`（Phase 2）：solution 拥有唯一资产集、成员只提供代码根；需要 baseline v2 + 成员 SHA 向量 + 多根 freshness / impact / closeout。
- `solution_commit --member`（Phase 2）：按成员仓提交代码。
- `import` / `export`（Phase 3）：成员资产迁移；旧源删除，历史归 git。
- solution 级 Trellis `packages`：Phase 1 不创建 `.trellis/`；若 solution 根已有 `.trellis/config.yaml`，`check` 只做成员 `path` 文本校验（不校验 `git: true`）；生成与完整语义校验归 Phase 2。
- Phase 4（可选增强）：多 host / `targets[]`、跨仓影响面与代码图谱、成员拆分导出、更多宿主集成；不在当前 Phase 1–3 的交付范围。
- 自动领取/自动启动不在本层：`task create` 只创建任务卡；成员仍需 `/trellis:start` 选择任务。
- 父级 `task create` 是 Phase 1 的唯一窄写例外：只写成员 `.trellis/tasks`（任务卡/指针/context），不写成员代码/资产/PRD。

### 6.1 父仓只读聚合视图（二期，2026-11-08，`RFC-20261108-02`）

- 入口：`atlas solution e2e status [--requirement <id>] [--json] [--snapshot]`；输出父仓跨仓用例 + 成员本地 E2E 摘要，不接管成员执行。
- 成员 `review_state` 按**成员根**重算（成员自己的 `repo_provenance` / `review_fingerprint`），**只读不落盘**；禁止写回成员账本/索引。
- 父仓用例 `review_state` 用父仓根 + `solution_root=True`：无 run-time `prov` ⇒ `stale`；单仓控制台既有分支不变（无 prov ⇒ `legacy`）。
- 父仓用例 `成员依赖` 必填（缺失 ⇒ `validate_e2e_index` 父仓模式 FAIL）；`成员依赖:` 与字面量 `[]` 归一为空列表；`--migrate` 只生成冒号留空形态。
- `--snapshot` 是唯一写动作，只落 `<assets_root>/e2e/reviews/aggregate/`（保留名）；聚合报告不是成员状态的第二份账本。
- 控制台逐条只读聚合（2026-11-09）：`atlas console --root <solution>` 的 `/api/cases` 增加 `scope` / `members[]` / `conflicts[]`；成员用例按 `成员名:用例ID` 复合键分组展示，跨成员同名 ID 不改本地 ID、不合并，冲突显式列出。父仓不复制成员用例正文、不代跑、不回写成员索引/账本；执行与评审回成员仓控制台，`/api/run` 与 `/api/submit` 对成员复合键 409。成员分区另给成员控制台入口链接与可直接复制的启动命令（端口 = 父仓端口 + 1 + 清单序号，确定性推导、不探测），执行与评审仍由成员进程完成。父仓控制台启动时按同一推导自动拉起成员控制台（`--no-spawn` 关闭）：已响应的成员控制台复用且退出不回收，被其它进程占用则跳过并披露原因、不抢占，未就绪如实报失败并附日志尾部，正常退出/信号时只回收自己拉起的子进程；自动拉起不转发请求，不接管执行与回写。无本地 E2E 索引（成员状态非 `ok`）的成员不拉起控制台，端口按序号保留，页面保留该成员行并标明未启动控制台、不给入口链接。`/` 为普通仓根时行为不变。

## 7. 相关契约

- 布局：`shared/layout.md`
- 技术栈画像：`shared/stack-profile.md`
- 门登记：`shared/gates.md`
- 单一真相源迁移纪律：`shared/single-source.md`
