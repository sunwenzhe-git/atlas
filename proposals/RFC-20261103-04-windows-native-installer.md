# Windows 原生支持：装配器 Python 化（Node 入口保留）

> 提案编号：RFC-20261103-04
> 提案作者：Atlas 维护批（2026-11-03 外部 Windows 现场触发）
> 关联状态：草案（Draft，待拍板后实施）
> 影响范围：安装器（`install.sh` / 新增 `install.py`）· CLI 入口（`bin/`）· 项目接线（`patches/project-wiring/`）· 契约文案（`shared/` `skills/` `rings/`）· CI（`.github/workflows/`）· 测试（`tests/`）
> 关联：commit `4abcc76`（Windows fail-closed + Trellis 平台探测修复）；`RFC-20261103-01`（同日并行批次，仅编号相邻）

---

## 1. 现象与取证

### 1.1 触发形态（抽象）

* **规则 / 环节**：`atlas init` 的装配入口（`bin/atlas.js` → `install.sh`）。
* **触发时机**：Windows 11 原生 PowerShell（无 Git Bash、WSL 组件已开但未装发行版）执行 `atlas init`。
* **具体行为**：
  1. 已安装的 Trellis CLI 被误报「未检测到」（`which` 在原生 Windows 不存在）；
  2. 随后 `bash` 解析到 `C:\Windows\System32\bash.exe`（WSL 中继壳），抛 `execvpe(/bin/bash) failed`；
  3. `install.sh` 一步未跑；`res.status || 0` 在 spawn 失败（status = null）时还会把失败洗成 0。

### 1.2 客观证据

现场终端（2026-11-03 外部用户，beta.26）：

```text
PS C:\Users\Administrator\Desktop\projs\smart-cloud-factory> atlas init
Atlas 项目级资产根目录（PRD / E2E / ADR 等）[product]: PRD
[Atlas] 资产根 = PRD（Atlas 资产会放在此目录；已有文件不会被覆盖）
[Atlas] ⚠️ 提示: 未检测到 Trellis CLI。
[Atlas] Atlas 需求级执行依赖 Trellis，建议稍后安装:
        npm install -g @mindfoldhq/trellis
WSL (57772 - Relay) ERROR: CreateProcessCommon:818: execvpe(/bin/bash) failed: No such file or directory
```

安装器的 Windows 依赖面（实测）：

| 依赖 | 证据 | 原生 Windows |
|---|---|---|
| bash | `bin/atlas.js` 的 `spawnSync('bash', ['install.sh', ...])`；`install.sh` 用数组 / `BASH_SOURCE` / `set -euo pipefail` | 无 bash；System32 的 `bash.exe` 是 WSL 中继壳 |
| POSIX 工具 | `install.sh` 实际调用 `grep`/`sed`/`cp`（各 4 处） | PowerShell 的 `cp` 只是 `Copy-Item` 别名；`grep`/`sed` 无对应物 |
| python3 | `install.sh` 19 处 `python3` 调用 | python.org 安装只提供 `python.exe` / `py.exe`；`python3.exe` 多为 Store stub |
| 归档钩子 | `patches/project-wiring/apply-wiring.py` 写 `python3 .atlas/scripts/refresh_structure.py --root . --chain` | Windows 上 `python3` 命中 Store stub；Trellis 以 `subprocess.Popen(cmd, shell=True)` 执行（`common/task_utils.run_task_hooks`），失败 fail-open、只 WARN |

Trellis 的对照实现（本机 v0.7.0-beta.4 实证）：

* `bin/trellis.js` → `import("../dist/cli/index.js")`，CLI 纯 Node/TS，文件操作走 `fs`，init 路径没有 bash；
* 需要 Python 时按平台取名：`dist/configurators/shared.js:42` → `target === "win32" ? "python" : "python3"`；
* 文件模式 / 删除 / cwd 有显式 win32 分支（`utils/ablation-store.js`、`managed-removal.js`、`cwd-guard.js`）。

### 1.3 为什么不能只修 init

即便 `atlas init` 过门，后续仍会断：

* `bin/atlas.js` 的 `check` / `console` / `report` 三处 `spawnSync('python3', ...)`；
* `extensions/pi.ts:56,165,302`（`/atlas status` 扩展）同断；
* `adapters/tests.py:53` 的 `RUN_PYTEST = "python3 -m pytest"` 会被写进 E2E 产物，Agent 照抄执行；
* 归档钩子（上表）已在 Git Bash 路径下也是断的（钩子由 Trellis 的 Python 进程执行，不经 bash）。

结论：**「只让 init 过门」会把故障从装配期推迟到使用期，是更坏的体验。**

---

## 2. 决策与权衡

### 2.1 核心定案：C（Node 入口 + Python 安装器）

* **方案总结**：把 `install.sh` 的顺序编排 1:1 移植为 `install.py`，`install.sh` 退化为 `exec python3 install.py "$@"` 的兼容 wrapper；`bin/atlas.js` 的 `runInstaller` 改为「探测 Python（win32: `py -3` → `python`；POSIX: `python3` → `python`）→ 直接跑 `install.py`」。
* **为何这是正解**：
  * 一次性去掉 bash + grep/sed/cp 两个 Windows 缺失依赖，只留 Node + Python（两者都是 Atlas 的既有硬依赖）；
  * 叶子逻辑（`pkg_digest.stamp_file`、`layout.py`、`apply-patches.py`、`apply-wiring.py`、自检）**继续复用**，不产生第二实现；
  * Python 解释器在安装器内部用 `sys.executable` 自洽，不再受 `python` / `python3` 命名坑影响；
  * `install.sh` wrapper 保留 ⇒ POSIX 路径可一键回滚。

### 2.2 备选方案及否定理由

* **A. 维持 Git Bash / WSL2，裸环境 fail-closed**
  * *否定理由*：能守住「不毁」，守不住「能用」；外部 Windows 用户的第一道门就过不去。
* **B. 双脚本 `install.ps1` + `install.sh`**
  * *否定理由*：740 行双份维护；与仓内「单源 + 摘要对账」文化冲突，必然漂移（F34/F55 守卫体系防的就是这个病）。
* **D. 全量 Node 安装器（~700 行 JS）**
  * *否定理由*：并不减少依赖——`pkg_digest` / layout / patches 仍是 Python，Node 版照样要 spawn 19 次；多出一份第二实现要长期双护，收益不如 C。

### 2.3 刺痛代价与兼容性

* `install.py` 与 `install.sh` 的语义必须逐项对齐，移植期存在回归风险；用 golden 快照兜底（§4）。
* 所有 Python spawn 点需注入 `PYTHONUTF8=1`，否则非中文 locale 的 Windows 在 PIPE 捕获下输出中文会 `UnicodeEncodeError`。
* 钩子命令按写入平台二选一（`python` / `python3`）；跨 OS 共享仓库时需重跑 `atlas update` 归一解释器（判据已改为平台无关的脚本路径段）。
* 文档中的 `python3` 命令需要一句平台约定，否则 Agent 在 Windows 上会照抄失败。

### 2.4 评审已确认的约束（不可省略）

* **P0-1**：Python 探测必须收敛进 `bin/platform.js`，覆盖 `bin/atlas.js` 的 check/console/report、`extensions/pi.ts`、`adapters/tests.py`；否则「支持 Windows 原生」是半句话。
* **P0-2**：钩子平台化独立于 C 成立——Git Bash 路径下当前也是断的（Trellis `shell=True` + `python3` stub）。
* **P0-3**：钩子幂等/迁移判据必须收窄为脚本路径子串（`.atlas/scripts/refresh_structure.py --root .`），解释器 token 不参与判等。
* **P1**：Python 探针不能只看 `where`（WindowsApps stub 会命中），必须实跑 `--version` 并校验输出；win32 建议砍掉 `python3` 臂。
* **P1**：golden 快照要剥权限位、只比内容 + POSIX 相对路径；`cgc --version` 需 PATH stub；`--dry-run` 的 `trellis init` 当前不受 DRY_RUN 闸约束（`install.sh:104-108`），移植前必须显式决定语义并补用例。
* **P1**：逐字节等价要处理 CRLF（写盘点用 `newline=""` / 二进制）、>260 长路径、杀软 EPERM、F55 porcelain 两桶解析、`set -e` 传播与退出码（守卫 2 / 检查 1 / ablation 10）。

---

## 3. 改动面清单

- [x] **安装器（已落地 2026-11-03）**：新增 `install.py`（835 行单源编排）；`install.sh` 退化为 45 行薄 wrapper；`bin/atlas.js` 的 `runInstaller` 切 `resolvePython`（Windows 原生可用，Git Bash/WSL2 不再是必要条件）。
- [x] **平台探测（已落地 2026-11-03）**：`bin/platform.js` 增 `resolvePython`（`py -3` → `where python` 排除 WindowsApps；`--version` 校验 3.10+），并接入 `bin/atlas.js` / `extensions/pi.ts` / `adapters/tests.py`。
- [x] **项目接线（已先行落地）**：`patches/project-wiring/apply-wiring.py` 钩子命令按平台写 `python`/`python3`，幂等/迁移判据改为 `HOOK_CORE` 脚本路径段。
- [x] **可执行面收敛（代码面已落地 2026-11-03）**：`extensions/pi.ts` 按平台取解释器（支持 `ATLAS_PYTHON` 覆盖）、`adapters/tests.py` 的 `RUN_PYTEST` 平台化。**剩余**：`AGENTS.md` 指针段一行「Windows: `python` 替代 `python3`」。
- [x] **CI（已先行落地）**：`.github/workflows/tests.yml` 的 windows-latest 作业（平台探针、exit-code 烟测、无 POSIX 环境的 fail-closed 模拟、Git Bash 装配链路 advisory）。
- [x] **测试（已落地 2026-11-03）**：跨平台钩子与 Python 探测用例、golden harness 8 场景基线、`install.py` 双轨 `--check` 8/8 全绿；**剩余** = AGENTS.md 平台约定一行（第 6 步）。
- [x] **契约/文档（已落地 2026-11-03）**：README 平台口径改为「Windows 原生可用，需 Python 3.10+」；`CHANGELOG` 两份、`docs/map` 计数与锚点同步。

---

## 4. 验证与测试结果

本提案为草案，实施批的验收口径：

### 4.1 golden harness（先于移植）

五种场景 + 失败注入，输出 = 目录树内容 + POSIX 相对路径 + `VERSION` / `MANIFEST.json` 内容（剥权限位）：

1. fresh 靶场；
2. 已装配靶场 `--update`；
3. `--dry-run`（含「fresh + 已装 Trellis CLI」——钉 `trellis init` 是否受 DRY_RUN 闸约束）；
4. F54/F55 两道守卫三态（脏触点 + `--force` / 整目录未跟踪 / 两桶皆非空）；
5. ablation active 互锁；
6. 失败注入：缺 `layout.py`、config 非法、只读文件——断言退出码（2/1/10）。

验收：新旧安装器在 POSIX 上逐字节等价；Windows 上登记为「已知允许差异」的只有 CRLF 与权限位。

### 4.2 回归

```bash
python3 -m pytest tests/
python3 scripts/atlas_check.py --fast
python3 tests/test_install_selfcheck.py
```

### 4.3 Windows 验证

**CI（`windows-latest`，2026-11-03 落地）**：
* `windows` 作业：平台探针 + CLI exit-code + Git Bash 轨（装配器用例已转正）；
* `windows-native` 作业（纯 PowerShell）：bare `atlas init` → `check --fast`（占位符项目**断言 fail-closed exit 1**）→ `update --dry-run`（断言 VERSION 逐字节不变）、GBK(936) 控制台不崩、Python resolver 断言（本机解析到 3.10+；版本门拒 3.9、收 3.10）。

**给使用者的验收步骤（可直接转发；约 5 分钟）**：

### Atlas Windows 安装验收

**开始前请确认**（在 PowerShell 里逐条运行）：

```powershell
node --version
python --version
```

- Node.js 需要 18 或更高；Python 需要 3.10 或更高。
- 如果 `python` 提示找不到，重装 Python 时勾选 “Add python.exe to PATH”。
- 还需要 Trellis：`npm install -g @mindfoldhq/trellis`

**1. 安装 Atlas**

```powershell
npm install -g atlas-project-harness
```

**2. 建一个空目录并初始化**

```powershell
mkdir C:\atlas-smoke
cd C:\atlas-smoke
atlas init
```

- 询问「项目级资产根目录」时，直接按回车（默认 `product`）即可。
- 看到「装配完成」和「首次开户（二选一）」就说明初始化成功；这次验收不需要真的开户。
- 如果提示没有 Trellis：先 `npm install -g @mindfoldhq/trellis` 再重试；仍然卡住就用 `atlas init --force`。

**3. 确认关键文件已经生成**

```powershell
Test-Path .atlas\VERSION
Test-Path .atlas\MANIFEST.json
```

两条都应返回 `True`。

**4. 跑一次体检**

```powershell
atlas check --fast
```

- **会看到几项 FAIL，这是正常的**：刚建好的项目里，技术栈画像还是空白模板，也没有 PRD，体检会如实指出来；**此时退出码为 1 也是预期**（占位符画像未填）。
- 这一步只确认它能完整跑完、没有崩溃或乱码；不需要现在就把项目填完整。
- 如果你愿意继续：让 Agent 带你核对 `product\stack-profile.yaml` 和 PRD，再跑一次 `atlas check --fast`，这时应全部通过（退出码 0）；**真实画像下仍非 0 才是真缺陷**。

**5. 试一次「刷新预览」（不改文件）**

```powershell
$before = Get-Content .atlas\VERSION -Raw
atlas update --dry-run
$after = Get-Content .atlas\VERSION -Raw
"文件未被修改: $($before -eq $after)"
```

最后一行应输出 `文件未被修改: True`。

**6. 试一次真实刷新**

```powershell
atlas update
echo $LASTEXITCODE
```

应看到「刷新完成」，并且退出码为 `0`。

**7. 如果任何一步报错，请把这些发回**

```powershell
atlas version
node --version
python --version
where python
```

再把**出错那一步的完整输出**复制成文字（截图也可以），并说明：

- Windows 版本（如 Windows 11 23H2）
- 是否中文系统
- 是否在公司网络 / 装了安全软件

> 输出里如有业务代码或密钥，请先删掉再发。

* 真机重点覆盖 CI 覆盖不到的：中文系统 locale、企业策略（WindowsApps/AppLocker）、无 Python 裸机报错文案、长路径与杀软文件锁。

### 4.5 留出验证

* **触发面核对**：本提案是安装器/CLI 入口改动，不改门禁/校验器判据；实施批落地时按 D156 重新判定并粘贴 `git diff --name-only` + `scripts/closeout_derive.py` 原始输出。
* **现状**：不适用（草案阶段未改判据）。若实施中触及 `validators/` 或 `shared/gates.md`，按系统性修复补留出集与 pre/post 证据。

---

## 5. 分阶段实施（最小批次，6 步）

1. **B-lite（已落地）**：钩子平台化 + 幂等键收窄；windows-latest CI 烟测与 fail-closed 模拟。
2. **Python 探测单点（已完成 2026-11-03）**：`platform.js` 增 `resolvePython`，接入 `bin/atlas.js` 四处 spawn 与 `extensions/pi.ts` / `adapters/tests.py`——先终结 `atlas check` 的 Windows 断面；安装器仍要求 `python3`，由第 4 步解除。
3. **golden harness（已完成 2026-11-03）**：`proposals/RFC-20261103-04-installer-golden/harness.py`，8 场景（fresh / update / dry-run-fresh / guard-dirty / guard-untracked / ablation-active / invalid-config / missing-layout）已录基线且 `--check` 确定性自检 8/8 绿。**纪律：harness 与基线必须留在装配集之外**（proposals/）——放 `scripts/` 里加一行就会改源包摘要，把要冻结的基线自己冲掉（当日实证）。包内容变更后需重录。
4. **`install.py` 1:1 + `install.sh` wrapper（已完成 2026-11-03）**：全 spawn 注入 `PYTHONUTF8=1`；写盘点锁 `newline`；`install.sh` 45 行 thin wrapper；`bin/atlas.js` 切 `resolvePython`；golden 双轨 8/8。
5. **钩子跨 OS 用例**：`atlas update` 在解释器漂移时归一（已加用例，实施批补 golden）。
6. **文档收敛 + 真机收尾（文档面已完成 2026-11-03；真机待外部）**：AGENTS.md 指针段平台约定一行、README 支持矩阵已落地；CI 新增 windows-native 作业（bare PowerShell 全流程 + GBK 编码 + resolver 版本门断言）；**剩真机一次 bare PowerShell 全流程**（清单见 §4.3）。

**回滚**：`install.sh` wrapper 保留 ⇒ 删除 `install.py` 引用即可回到 bash 路径；`runInstaller` 改动是单点。

---

## 6. 已拍板（2026-11-03）

1. **Git Bash 口径**：定为「**可用（可选兜底）**」，不升正式。`install.sh` wrapper 已做解释器探测（`ATLAS_PYTHON` > `python3` > `python`），Git Bash 不再需要额外造 `python3` 别名；正式标签等真机复验。
2. **`--dry-run` 的 `trellis init` 语义**：选 **B（真零落盘）**——干跑只打印 `--dry-run：跳过 trellis init，不落盘`，不执行；golden 新增 `dry-run-trellis` 场景（假 trellis 会造 `.trellis/`，快照证明未执行）。
3. **钩子跨 OS 策略**：选 **B（平台无关启动器）**——新增 `scripts/run_python.js`（Node 启动器，运行时解析 Python 3.10+ 并转发 argv/退出码）；钩子命令统一为 `node .atlas/scripts/run_python.js .atlas/scripts/refresh_structure.py --root . --chain`，跨 OS 同一串可用。`apply-wiring.py` 自动把旧形态（`python3`/`python`/`py -3`）就地升级，不双注册。**注**：此选项此前被评审判为过度设计（倾向「换 OS 跑一次 update」），用户 2026-11-03 拍板选 B——理由是 config.yaml 是 git 跟踪的，跨 OS 协作场景下「记得跑 update」不可靠。代价 = 多一个 92 行启动器 + 一条自检（63→65 中 +1）。
4. **发布口径**：选 **B（beta 级支持）**——README 矩阵标「支持（beta，待真机复验后转正）」；发布说明同口径；真机按 §4.3 清单通过后去掉 beta 字样。
5. **实施时机**：**已完成**（2026-11-03 当批）。
