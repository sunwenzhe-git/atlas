# L1 · CLI 与装配子系统

> 子系统 #1 / 上级地图:[index.md](index.md) / 锚定版本:见 index.md 数字快照(2026-10-25 复核)
> 一句话:**把 atlas 装进目标仓 `.atlas/` 并保持副本与源包对账**——命令面薄、装配器厚,一切「副本漂移」在这个子系统的三个对账面(版本戳 / manifest / 回灌)里现形。

## 它不是什么

- 不做升级链:`npm install -g` 升级后用 `--force` 常规化不被支持(B-1 强口径否决)——升级走显式 `install.sh --update`。
- 不碰业务代码:只写 `.atlas/`、skill 瘦桩、wiring 触点;目标仓产品侧零落笔。
- 不是包管理器:没有依赖解析;`bin/atlas.js` 是命令路由,不是运行时。

## 文件清单

| 文件 | 行数 | 角色 |
|---|---|---|
| `bin/atlas.js` | 702 | CLI 入口:命令面总表见 `printHelp`(`bin/atlas.js:18`)= init / update / upgrade / check / migrate / incident / docs / topology / contracts / receipt / classify / calibrate / metrics / workflow / change / bug / solution / review / eval / e2e / console / report / apply / version,分派在同文件 `switch (command)`;平台探测拆到 `bin/platform.js`(bash 只认 Git Bash、Python 按平台探测 3.10+)；change/bug 共用新版脚本，workflow 本地旧脚本按 `ATLAS_CHANGE_AUTO_V1` 能力门回落包内新版 |
| `install.py` | 998 | 装配单源:白名单拷贝 + 版本戳 + manifest + 78 条 `c()` 自检 + 图谱探测;叶子脚本(layout / apply-patches / apply-wiring / pkg_digest / ablation / evidence_archive)复用不重写 |
| `install.sh` | 56 | 薄 wrapper:头部用法说明 + `exec python3 install.py`(装配逻辑零残留,自检门守) |
| `scripts/atlas_workflow.py` | 1011 | 执行层调度:plan / dispatch / context / verify / finish / status / progress / archive / run;任务账本 `.atlas/tasks`(收口后归档到 `tasks/archive/<YYYY-MM>/`,`status --all` 可查),`--paths`(最小注入) / `--round` / `--resolves` 透传;`context` 为只读查询(不写盘、不改状态);`progress` 为只读进度探针(RFC-20261122-02,聚合派工/暂存/审查轮次/覆盖矩阵四格;命中=路径级存在性非内容级证据,AC 结论只认 verify);verify 末尾跑需求条目覆盖对账(逐卡 WARN,`_support/workflow_verify.py`)+需求落点跨卡对账(漏领/幽灵引用/状态机 WARN,RFC-20261122-03)+机制文档提示族残部(疑似死 paths/词表点名/死测试锚/申报死行 WARN,RFC-20261122-04)+**机制文档触及申报判决门**(前置判定带,触及未跟改未申报⇒FAIL rc1 扣预算 `mechanism_undeclared`/词表两档非法⇒`mechanism_paths_invalid`,申报面=卡目录 `mech-declares.md`,触及提示 WARN 同日退役,RFC-20261123-01);plan 支持需求落点模式(`--requirement` 指向落点,卡持领取引用行、正文指针化,初始需求/需求变更/缺陷三类增量与基线关联检查,重跑保持指针,RFC-20261122-03/20261124-01);verify 对需求变更/缺陷在评审前自动回推并暂存 exact 产物，finish 缺失/过期自动补跑且变化后强制 reverify；finish 硬校验结构事实新鲜度(baseline≡HEAD ∧ 无非豁免未暂存/未跟踪改动,跳过刷新⇒FAIL 带修复命令,空转态经 --advance-baseline 重锚,RFC-20261122-05),关联卡全归档且 completed 后按类型返回/提醒产品事实回写(D211);回收面(RFC-20261122-07):失败双轨记账(attempts.jsonl,cause 封闭词表单源 _support/workflow_causes.py)+verify 尝试预算门(charged≥上限⇒rc3 拒绝+budget_exceeded 留痕)+退出码封闭(0/1/2/3/130,:332 按 cause 分流)+deferred 存量缺陷台账(门判定前提取,fingerprint 幂等)+status 聚合(attempts/坏行/deferred 开放,含归档卡) |
| `scripts/atlas_change.py` | 21 | 需求变更/缺陷统一入口；`atlas_bug.py` 保留实现与缺陷别名 |
| `_support/bug_backflow.py` | 883 | 变更/缺陷回推内核：OID 指纹、影响面分析、精确写入集、claim+rollback 事务、校验器编排、v2 review/finish 锚 |
| `_support/bug_record.py` | 577 | 变更/缺陷台账 schema 运行时校验、typed/legacy dedupe、canonical JSON 哈希、append-only history 与原子存储 |
| `validators/validate_bug_ledger.py` | 224 | canonical 变更/缺陷根/record schema/dedupe/history 与 legacy 双落点守卫 |
| `scripts/pkg_digest.py` | — | 内容摘要算法单点(`ASSEMBLY_COVER_DIRS`,`scripts/pkg_digest.py:52`):装配版本门两侧共用,防双端漂移 |
| `scripts/backflow.py` | — | 副本 ⇄ 源包三态回灌(`diff_trees`,`scripts/backflow.py:60`;`apply`,`scripts/backflow.py:97`) |
| `patches/`(1 族) | — | 项目接线补丁:project-wiring(AGENTS.md 指针 / 测试配置 / pi 扩展 / .gitignore) |

## 核心机制

### 1. 装配四步(`install.py`;`install.sh` 薄 wrapper)

`[1/4]` 整包 → `.atlas/`(`atlas_dest`,`install.py:544`,白名单目录拷贝,不整目录删,保住 `.atlas/runs/` 运行态)→ `[2/4]` skill 瘦桩(引用契约不复制正文)→ `[3/4]` 骨架 → `[4/4]` 项目接线(AGENTS.md 指针 / 测试配置 / `.gitignore` / pi 扩展)→ 图谱后端探测(可选)→ 自检段(`say("自检")`,`install.py:785`,121 条 `c()` 声明)。`--dry-run`(F54)零落盘、双摘要可见化;`--update` 刷新已装配副本。

### 2. 装配基线三件(D145/D146/D147)

`.atlas/VERSION` 内容摘要戳(落点 `install.py:946` `stamp_file`)与 `.atlas/MANIFEST.json` 逐文件基线(同点落),摘要算法单源在 `pkg_digest.py`——atlas_check 装配版本门按「配对校验先行」重算对账:戳在而 manifest 缺 = 显式「旧装配」半态,不是失败。写序先 manifest 后 VERSION。

### 3. 三态回灌(`backflow.py`)

副本侧改动相对源包分 NEW / DIFF / SOURCE_ONLY;SOURCE_ONLY 拒绝护栏防方向搞反(源包不存在的文件不回灌),并发写入有哨兵;回灌前 drift_check 比对 mtime/size。

### 4. 接线五触点(project-wiring 补丁)

AGENTS.md 指针 / after_finish hook / pytest 兜底 / `.gitignore` 追加 `.adapter-out/` / pi 扩展——单向接线,无退役对称(装机时写入,不承诺反向摘除)。

### 5. 补丁幂等

锚点式版本化补丁按块指纹(片段正文 sha256 前 8 位)判定:指纹同 ⇒ skipped,异 ⇒ 整块替换——可重放,不整体覆盖用户的 `workflow.md`。

## 对外接口(谁咬它)

| 消费方 | 触点 |
|---|---|
| atlas_check 装配版本门 | VERSION 戳 + MANIFEST 基线 ⇔ 源包重算 |
| test_install_selfcheck | 自检引用必须存在:121 条 `c()` 声明指向的文件必须真落下 |
| test_backflow | 三态语义 + SOURCE_ONLY 护栏钉 |
| 执行层 | `atlas workflow` 把 apply / 工作流步骤写进 `.atlas/tasks` 任务卡与派工单 |

### 6. 需求变更/缺陷自动回推链（issues #75/#76）

实现暂存 → `atlas workflow verify` 在评审前自动回推并暂存 exact 产物 → `atlas review` 封存 v2 `change_backflow` 独立锚 → `atlas workflow finish` 复算实现 OID、canonical 产物哈希与 history/delete 锚。finish 自动补跑后必须 reverify；语义冲突必须签字；legacy 双落点由 `validate_bug_ledger` 拒绝。

## 显式盲区

- 旧副本的新语法吸收问题不归装配器治(归生成器值域封闭 D98);`install.sh --update` 是咬合点,存量副本不自动升级。
- wiring 五触点装机即写,无对称退役。
- npm 升级链显式不支持(用 `--force` 的风险自负,提示但不拦)。

## 演化锚

| 决策 | 内容 |
|---|---|
| D92 / F54 / F55(2026-10-16) | dry-run 挂闸 + 未跟踪 WARN 放行 + 双摘要;守卫两语义 |
| D121(#37,2026-10-20) | prepare 注入 ATLAS_CASE_ID |
| D124(#38,2026-10-20) | 就绪门浏览器判据 probe_browser |
| D145/D146/D147(2026-10-23) | 装配基线 manifest + PRD 变更记录 5 列 + 显式无 |

## 讲述时的三个抓手

1. **副本是资产就有对账面**:版本戳 / manifest / 回灌三态——「装配 ≠ 开户,装完还要对得上」。
2. **白名单 + 不整删**:装配器知道自己的边界(哪些目录归它),也知道别人的运行态(`.atlas/runs/`)不能碰。
3. **自检是装配的一部分**:声称落下的每个文件必须真落下——120 条声明本身就是契约。
