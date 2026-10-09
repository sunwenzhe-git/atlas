# 30 秒快速上手

Atlas 采用现代化的一键全局 CLI 机制，你可以像使用 Trellis 一样，在任何新老项目中以极简命令启动。

---

## 1. 依赖环境准备

在开始之前，请确保你的开发环境满足以下要求：

* **Node.js 18+**（CLI 运行环境）
* **Python 3.10+**（核心校验器与生成引擎）
* **Playwright**（E2E 测试运行器：Python 或 Node 版）
* **Trellis**（推荐宿主执行器，负责需求级任务调度）
* *(可选)* **CodeGraphContext (cgc)**：若需开启图谱级跨文件逆向分析，安装 `pip install codegraphcontext`

---

## 2. 全局安装 CLI 与项目初始化

在你的终端中执行：

```bash
# 全局安装 Atlas CLI
npm install -g atlasharness

# 进入你的项目目录
cd your-project

# 一键初始化并装配 Atlas 工作流（自动探测平台、下发 Skills 与契约）
atlas init
```

> 💡 **提示**：也可以直接从 GitHub 仓库一键安装：`npm install -g sunwenzhe-git/atlas`。

### `atlas init` 会自动为你完成什么？
1. **整包镜像**：将核心契约、校验器、模板整包镜像至项目 `.atlas/`；
2. **下发专用 Skills 瘦桩**：向你的 Agent 平台目录（`.agents/skills/`、`.claude/skills/`、`.codex/skills/`）注入 `atlas-structure`, `atlas-prd`, `atlas-e2e`, `atlas-apply`, `atlas-grill`, `frontend-design` 等；
3. **注入工作流锚点补丁**：向 `.trellis/workflow.md` 注入 `Phase 1.6` 锚点补丁与执行提示；
4. **部署只读独立审查 Agent**：自动生成 `atlas-reviewer` 只读审查者配置。

---

## 3. 配置技术栈画像 (`product/stack-profile.yaml`)

安装完成后，项目根目录会生成一份技术栈画像草稿，请根据你的工程实际情况进行确认：

```yaml
product: MyAwesomeApp
origin: greenfield          # greenfield: 全新项目 | adopt: 存量老项目接入

apps:
  - name: web
    path: frontend
    role: landing           # landing: 当前主实现
  - name: api
    path: backend
    role: landing

e2e:
  runner: python-playwright
  app_base_url: http://127.0.0.1:8000
  review: null              # null = 默认使用会话模型；可配置备用模型做交叉审查

graph:                      # 可选：开启代码知识图谱后端优化逆向
  backend: cgc
```

---

## 4. 怎么快速使用？（大白话四场景）

Atlas 完全做到了**“日常全自动，低频全靠大白话”**：

### 场景 A：存量老项目首次接入（最常用）
在 Agent 对话中输入一句大白话：
```text
“帮我把这个项目接入 Atlas 工作流”
```
Agent 将自动调用 `atlas apply adopt`，逆向扫描现有代码拓扑，建立应然资产起点（不瞎猜老业务用例，只登记基线）。

### 场景 B：全新空白项目立项
对 Agent 说：
```text
“跑一下三环全量构建，建立应然基线”
```
Agent 自动调用 `atlas apply all`，全量串行初始化 `structure → prd → e2e`。

### 场景 C：日常迭代提需求（100% 自动无感）
你**无需敲任何 Atlas 命令**，像往常一样在 Trellis 中创建任务（如 `/trellis:start 优化配音列表`）：
* 工作流在 Phase 1.6 **自动静默调用** `apply <需求ID>` 完成应然资产编译；
* 需求写完收口时，自动触发钩子刷新最新代码事实。

### 场景 D：一键体检与门禁自检
随时可在终端跑一条命令检查全项目应然资产与门禁状态：
```bash
atlas check --fast
```

### 场景 E：启动可视化 E2E 控制台
在终端敲入一行命令，立刻拉起本地有头慢动作控制台：
```bash
atlas console
```
