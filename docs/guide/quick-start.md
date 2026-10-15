# 30 秒快速上手

Atlas 采用现代化的一键全局 CLI 机制，你可以像使用 Trellis 一样，在任何新老项目中以极简命令启动。

---

## 1. 依赖环境准备

在开始之前，请确保你的开发环境满足以下要求：

* **Node.js 18+**（CLI 运行环境）
* **Python 3.10+**（核心校验器与生成引擎）
* **Playwright**（E2E 测试运行器：Node 版，由项目 `node_modules` 提供）
* **[Trellis](https://github.com/mindfold-ai/trellis)**（必需宿主执行器，负责需求级任务调度；安装：`npm install -g @mindfoldhq/trellis`）
* *(可选)* **CodeGraphContext (cgc)**：若需开启图谱级跨文件逆向分析，安装 `uv tool install codegraphcontext`（或 `pip install codegraphcontext`）

---

## 2. 全局安装 CLI 与项目初始化

在你的终端中执行：

```bash
# 全局安装 Atlas CLI
npm install -g atlas-project-harness

# 进入你的项目目录
cd your-project

# 一键初始化并装配 Atlas 工作流（自动探测平台、下发 Skills 与契约）
atlas init
```

### `atlas init` 会自动为你完成什么？

**四样主件**（atlas 与宿主执行器之间的全部耦合面）：

1. **整包镜像**：把契约、环文档、校验器、模板、适配器整包复制到项目 `.atlas/`（日后所有规则与机器校验的唯一正本；skill 与文档都指回这里，不存第二份）；
2. **下发专用 Skills 瘦桩**：按探测到的平台目录（`.agents/skills/`、`.claude/skills/`、`.codex/skills/`）各装一份轻量入口——`atlas-structure`、`atlas-prd`、`atlas-e2e`、`atlas-apply`、`atlas-grill`、`atlas-design-review`、`frontend-design`。桩本身不装规则，第一步就指回 `.atlas/`；
3. **注入工作流补丁组**：向 `.trellis/` 注入补丁组（Phase 1.6 资产更新挂载、阶段技能路由、根因分析优先红用例）与项目接线——对准模板里的稳定标记定位、用带指纹的标记包住，幂等可重放（Trellis 升级重写该文件后，重跑 `install.sh` 即自动对齐）；
4. **三处接线 + 只读审查 Agent**：`.trellis/config.yaml` 加 `after_finish` hook（每次任务收口后自动刷新结构事实）、项目 `AGENTS.md` 加一段指针、*（pi 宿主）*`.pi/` 下落地并登记 `/atlas` 控制台扩展（`/atlas status` 报**开户态**——「装配 ≠ 开户」，非 pi 项目不创建 `.pi/`），并下发 `atlas-reviewer` 只读审查者配置（工具集不含写文件与 bash）。

**两步卫生件**：清理历史遗留 / 已退役的 skill；建 `product/` 骨架（已有内容永不覆盖）。

### 升级与更新机制（Update & Upgrade）

类似 Trellis，Atlas 支持两层解耦的平滑升级机制：

1. **升级全局 CLI（`atlas upgrade`）**：  
   当 Atlas 官方发布了新版本时，自动通过 npm 拉取最新全局包：
   ```bash
   atlas upgrade              # 自动升级至 latest 标签
   atlas upgrade --tag beta   # 升级至指定标签（如 beta）
   atlas upgrade --dry-run    # 仅预览升级安装命令
   ```

2. **刷新项目内工程线束（`atlas update`）**：  
   升级全局 CLI 后，进入你的项目目录，一键安全刷新 `.atlas/` 资产与平台 Skills 瘦桩：
   ```bash
   cd your-project
   atlas update               # 安全刷新当前项目工程线束与平台 Skills
   atlas update --dry-run     # 预览更新改动，不实际写入
   ```
   > 🛡️ **安全保证**：`atlas update` 会刷新 `.atlas/` 核心契约、校验器、模板、项目接线与平台 Skills 瘦桩，并重新对账生成 `.atlas/VERSION` 版本戳；你的业务资产（如 `product/stack-profile.yaml`、已编写的 E2E 用例与领域规格等）受到严格保护，绝不覆盖。

---

## 3. 核对技术栈画像 (`product/stack-profile.yaml`)

安装完成后，项目根目录会生成一份技术栈画像草稿。**不用你手改**：首跑开户时 Agent 会带着你逐项核对（`origin` / `apps` / `role` / `adapters`）后落盘。出厂草稿含占位符，未替换占位符前 `atlas check` 必有门禁 FAIL —— 这是 fail-closed 的预期行为，不是装坏了：

```yaml
product: MyAwesomeApp
origin: greenfield          # greenfield: 全新项目 | adopt: 存量老项目接入

apps:
  - name: web
    path: frontend
    kind: frontend          # frontend | backend | fullstack | mobile
    role: landing           # landing: 当前落地实现 | legacy: 事实来源（重构/存量项目才有）
    stack: React + Vite     # 自由文本，仅作展示，atlas 不据此做任何判断
  - name: api
    path: backend
    kind: backend
    role: landing
    stack: FastAPI

adapters:                   # null = 该类事实降级为 agent 撰写
  routes: null              # 路由 / 页面清单
  api: null                 # 接口清单
  models: null              # 数据模型清单
  tests: null               # 测试现状

e2e:
  runner: node-playwright
  node_modules: frontend/node_modules   # node 运行器的依赖目录（相对项目根）
  app_base_url: http://127.0.0.1:8000
  review: null              # null = 默认使用会话模型；可配置备用模型做交叉审查

graph:                      # 可选：声明后 routes 走图谱枚举、apply 先跑影响面推导
  backend: cgc
```

> `apps[]` 的 `name` / `path` / `kind` / `role` 四项为**必填**（缺一即被 `validate_stack_profile` 判 FAIL），`origin` 只有 `greenfield` / `adopt` 两个取值。

---

## 4. 怎么快速使用？（大白话五场景）

Atlas 完全做到了**“日常全自动，低频全靠大白话”**：

### 场景 A：存量老项目首次接入（最常用）
唤起技能（确定性入口）：
```text
/atlas-apply adopt
```
也可以只说一句大白话，让 Agent 自己选模式：
```text
“帮我把这个项目接入 Atlas 工作流”
```
无论哪种入口，Agent 都会逆向扫描现有代码拓扑，建立应然资产起点（不瞎猜老业务用例，只登记基线），并在开户前与你核对画像草稿、把占位符换成真实路径。

> ⚠️ **装配 ≠ 开户**：`atlas init` 只装配线束（`.atlas/`、`product/` 骨架、AGENTS.md 指针）。**开户产物是 `product/prd/` 与 `.trellis/spec/structure/` 的内容**——两者为空就是尚未开户。所以「已经装过 atlas」不代表已接入：若 Agent 回你「已接入」或反问「是不是接过了」，直接敲 `/atlas-apply adopt`（开户按产物存在与否断点续跑）。

> 完整流程、为什么存量页面不会把门禁刷红、后端项目的补充配置，见 [存量项目接入指南 (adopt)](/guide/legacy-adoption)。

### 场景 B：全新空白项目立项
唤起技能：
```text
/atlas-apply all
```
或对 Agent 说：
```text
“跑一下三环全量构建，建立应然基线”
```
Agent 全量串行初始化 `structure → prd → e2e`。

### 场景 C：日常迭代提需求（100% 自动无感）
你**无需敲任何 Atlas 命令**，像往常一样在 Trellis 中创建任务（如 `/trellis:start 优化配音列表`）：
* 工作流在 Phase 1.6 **自动调度 Agent 执行** `atlas-apply <需求ID>` 技能完成应然资产编译；
* 需求写完收口时，自动触发钩子刷新最新代码事实。

### 场景 D：一键体检与门禁自检
随时可在终端跑一条命令检查全项目应然资产与门禁状态（`--fast` 为秒级轻量体检，仅跑静态校验器与生成物新鲜度；默认模式还会跑出厂测试与浏览器真跑）：
```bash
atlas check --fast
```

### 场景 E：启动可视化 E2E 控制台
在终端敲入一行命令，立刻拉起本地有头慢动作控制台：
```bash
atlas console
```
