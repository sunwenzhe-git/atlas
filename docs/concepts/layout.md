# 产物落点与生命周期

Atlas 的产物**不散落**：每个文件都有唯一归属地、唯一写者、唯一覆盖策略。这一页回答三个每天都在被问到的问题 —— 东西放哪、谁能改、不用了怎么退役。

---

## 1. 四个落点

| 落点 | 归属 | `install.sh` 是否覆盖 |
|---|---|---|
| `<项目根>/.atlas/` | atlas **包产物**（共享契约、环契约、模板、适配器、校验器、刷新脚本） | 会刷新（属包，非用户数据） |
| `<项目根>/product/` | atlas **项目产物**（PRD、E2E、设计档案） | **永不覆盖** |
| `<项目根>/.trellis/spec/structure/` | **结构事实**（逆向产物；Trellis 路径注入层） | 由结构环 / 刷新脚本维护 |
| `<项目根>/.trellis/spec/conventions/` | **约定类注入薄桩**（当前仅 `testid.md`，派生视图） | 由 E2E 环维护 |

`.atlas/` 是包在项目里的唯一副本；平台 skill 目录里只放瘦桩 `SKILL.md`，第一步就指回 `.atlas/` —— **不存第二份正文**。

---

## 2. `product/` 布局

```text
product/
├── stack-profile.yaml          # 技术栈画像（atlas 认识这个项目的唯一入口）
├── design.md                   # 视觉设计档案（frontend-design skill 写；atlas 只读）
├── reviews/                    # <日期>-<主题>/ 缺口清单 + calibration.jsonl 校准账本
├── prd/                        # README.md 追溯总表 + prd.md + <domain>-prd.md
│   └── reviews/                # 独立审查报告（README.md + review.json + inputs/）
└── e2e/                        # e2e-index.md + cases/<page>.md + scripts/<page>.<ext>
    └── reviews/                # 独立审查报告 + console/ 人工评审账本（append-only）
```

结构事实落 `.trellis/spec/structure/` —— 它既是项目级事实，又能被 Trellis 任务**原生注入**消费：

```text
.trellis/spec/structure/
├── _meta.json                  # 机器：product / baseline / apps[] / domains[] / categories
├── tour.md                     # L1：paths ['**']
├── domains/<domain>.md         # L2：paths = 该域 globs
├── global/{directory-map,routes}.md
└── {current,legacy}/<domain>/{apis,data-models}.md
```

`role` 决定事实去向：`landing` → `current/`（落地实现的事实）；`legacy` → `legacy/`（事实来源，重构 / 存量项目才有 —— 没有 `legacy` app 时整个目录缺席）。同一 role 下有多个 app 时共用域级结构，域级文件内按 app 加小节。

---

## 3. 三套 `reviews/` 不要混用

| 目录 | 语义 | 产出者 |
|---|---|---|
| `product/reviews/<日期>-<主题>/` | 人机协同收集的**缺口清单 / 修订批次**（无需求卡的应然资产修订） | 人 + agent |
| `product/<环>/reviews/<日期>-<范围>/` | **独立审查报告**（`README.md` + `review.json` + `inputs/`） | 审查者 |
| `product/e2e/reviews/console/` | **人工评审账本**（append-only；语义 = 人复核**执行结果**符合业务预期） | 人（控制台提交） |

分开只有一个理由：**「谁判的」不能模糊**。

---

## 4. 产物生命周期：生 / 变 / 迁 / 死

| 态 | 纪律 |
|---|---|
| **生** | 先定应然再实现（`apply` 前置），不写空壳占位 |
| **变** | 单一真相源：同一信息只保留一处正文，其余全是指针 |
| **迁** | 真相源迁移是**一等事件**：登记迁移史 + 迁移仪式 = **完备性对账**（新源 ⊇ 旧源迁移基线集），过了才算迁完 |
| **死** | 退役三件套 + 传播义务（下节） |

### 退役三件套（硬）

1. **声明两档**：每个受影响项明确归入**删除** / **失义**（产物或规则失去宿主但要求仍在）。**无冻结档** —— 退役即删、历史归 git；工作树里留档等于留一个漂移面。
2. **迁移与失义清单**：逐项覆盖七类面 —— **状态标签 / 输入链 / 门 / 校验器 / 模板 / 装配项 / 规则**。其中「规则」最容易漏：一个环被删掉后，它承载的规则会失去宿主，而**没有任何检查会发现** ⇒ 失义项只有两种处置：**归位**（写进新宿主的契约）或**明确作废**（写明理由）。
3. **传播义务**：**回灌完成前，退役不算结束** —— 防复活属退役本体，不是后续事项。

### 状态标签带纪元

流水线级变更定义**纪元**；旧标签按映射表转义为**历史终态**，存量合法、不再产生。当前纪元 **E1**。

---

## 5. 装配版本戳

`install.sh` 装配完成时对源包算内容摘要，落 `<项目根>/.atlas/VERSION`；副本侧 `atlas_check` 周期重算并比对，不一致即 `WARN`（源包已前进 / 落后于装配态，重装前先回灌对账）。

**不依赖 git**：源包本身无仓库，摘要直接探测内容漂移 —— 比版本号更贴「对账」的本意。
