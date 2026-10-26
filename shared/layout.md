# atlas 共享契约 — 目录布局与 role 语义

> atlas 产物在目标项目中的落点约定。各环按路径引用 `.atlas/shared/layout.md`。
>
> **资产根（2026-10-26，`RFC-20261026-01`）**：下文示例中的 `product/` 均为**默认资产根**。
> 项目可在根 `atlas.config.yaml` 声明 `layout.assets_root`（默认 `product`）与可选
> `layout.adr`（默认 `<assets_root>/adr`）；所有机器门、脚本、skill 契约一律经
> `_support/layout.py` 解析，不得各自写死。

## 1. 四个落点

| 落点 | 归属 | 是否被 `install.sh` 覆盖 |
|---|---|---|
| `<项目根>/.atlas/` | atlas **包产物**（共享契约、环契约、模板、适配器、刷新脚本） | 会刷新（属包，非用户数据） |
| `<项目根>/<资产根>/`（默认 `product/`） | atlas **项目产物**（PRD、E2E、设计档案、ADR） | **永不覆盖** |
| `<项目根>/.trellis/spec/structure/` | **结构事实**（逆向产物；Trellis 路径注入层） | 由结构环 / 刷新脚本维护 |
| `<项目根>/.trellis/spec/conventions/` | **约定类注入薄桩**（当前仅 `testid.md`；派生视图，正文归 E2E 环契约） | 由 E2E 环维护 |

### 1.1 资产根配置（`atlas.config.yaml`）

项目根新增（`install.sh` 首装写入，git 跟踪）：

```yaml
version: 1
layout:
  assets_root: product   # 文件存在时必填；项目相对 POSIX 路径；文件缺失时整体默认 product
  adr: docs/adr          # 可选；项目相对 POSIX 路径；缺省 <assets_root>/adr
```

- **解析顺序**：`atlas.config.yaml` 是唯一锚点；文件缺失 ⇒ 整体默认 `assets_root=product`、`adr=product/adr`（存量项目零变化）。
- **路径规则**：`assets_root` / `adr` 必须是项目根内相对 POSIX 路径；拒绝绝对路径、`..`、`.`、空段、`.atlas` / `.trellis` / 项目根本身、引号 / `#` / 换行；symlink 解析后仍须落在项目根内。
- **v1 范围**：只开放 `assets_root` 与 `adr`；`stack-profile.yaml`、`prd/`、`e2e/`、`design.md`、`reviews/`、`atlas-reports/` 由 `assets_root` 派生。e2e 三路径仍可在 `stack-profile.yaml` 显式覆盖（既有机制）。
- **装配**：`atlas init` 首次安装可交互选择或 `--assets-root` / `--adr-dir`；`atlas update` 只读配置、绝不重新提示或换根。首装所选根不是 `product` 且默认 `product/` 已有 Atlas 资产 ⇒ 拒绝（双根风险）。
- **门禁**：配置缺失 ⇒ 默认值；非法配置 ⇒ `atlas_check` 单行 `项目布局配置` FAIL；目标目录缺失 / 为空 ⇒ 沿用三态 `SKIP`；配置根与默认 `product/` 同时有资产、或 `stack-profile.yaml` 的 e2e 三路径仍指向 `product/` 而配置根已存在 e2e ⇒ 首版 WARN。
- **模板**：`templates/stack-profile.yaml` 的 e2e 三路径用 `{{ASSETS_ROOT}}` 占位，由 `install.sh` 首装渲染，避免自定义根回落 `product/`。

- `.atlas/` 是包在本项目的唯一副本；平台 skill 目录里只放瘦桩 `SKILL.md`，指回 `.atlas/`。
- **`product/adr/`（架构决策记录，2026-10-13 登记）**：项目级长效架构裁决，默认落点为 `product/adr/NNNN-<slug>.md`；可由 `layout.adr` 覆盖。按需落笔，永不覆盖。跨需求长效架构决策归此；需求内微观取舍归域级 PRD。
- **`product/design.md`（视觉设计档案，2026-10-08 登记 `#182`）**：写者 = frontend-design skill（design read / 旋钮 / 设计系统 / 强调色 / detect 豁免），atlas 不生产不覆盖；只读触点两个——走查单确认门前对照视觉方向（`rings/prd/reference.md` §4·八）+ detect 豁免 ⇔ `.impeccable/config.json` `detector.ignoreRules` 双向对账（`validators/validate_design_exemptions.py`）。
- **结构事实落 `.trellis/spec/structure/`**：既是项目级事实，又能被 Trellis 任务**原生注入**消费。仅 `tour.md`（`paths: ['**']`）与 `domains/<domain>.md`（域 globs）带 `paths:`；其余事实文档无 `paths`、按需 Read。
- **testid 薄桩落 `.trellis/spec/conventions/`**：`testid.md` 带 `paths:`（前端 app globs），供实现任务注入；它是**派生视图**（祈使句 + 指针 + 由**用例分片应然清单**派生的清单），命名规则正文归 E2E 环契约。
- **`product/prototype/`（已退役，E1 = 2026-09-27 `3508 §92`；2026-09-30 目录删除）**：atlas 不再消费。页面标识（slug）与「页 ↔ 真实路由」映射的真相源 = `product/e2e/e2e-index.md` 页面表（`rings/e2e/reference.md` §3.1）。
- **两套 `reviews/` 不同角色（2026-09-26 补，不要混用）**：
  - `product/reviews/<日期>-<主题>/` = **人机协同收集的「缺口清单 / 修订批次」**（无需求卡的应然资产修订，`3507 P2`）；`calibration.jsonl` 也在此。
  - `product/<环>/reviews/<日期>-<范围>/` = **独立审查报告**（机器/审查者产出：`README.md` + `review.json` + `inputs/`），落点归该环自己的产物目录。
  - `product/e2e/reviews/console/` = **人工评审账本**（append-only；语义 = 人复核**执行结果**符合业务预期）。与机器审查（**设计期**语义门）分开，以免「谁判的」模糊。
- **E2E 用例评审控制台是随包工具**（`.atlas/scripts/e2e_console.py` + `.atlas/templates/e2e/console/`）：项目侧只落它的运行时产物（账本 `product/e2e/reviews/console/`，append-only），**本体不进 `product/`**（`rings/e2e/reference.md` §10.1）。

## 2. 布局

> 下图以默认资产根 `product/` 为例；自定义时按 `atlas.config.yaml` 的 `layout.assets_root` 替换该层目录。

```
<项目根>/
├── README.md                       # A（技术栈/启动，可选）+ H（测试/运行，条件）
├── .trellis/                       # Trellis 原生（需求级）
│   ├── workflow.md  config.yaml
│   ├── tasks/<NN-slug>/            # 需求级：prd.md = 需求卡；atlas-apply.md = apply 执行记录
│   ├── spec/structure/             # ★ 结构事实（逆向产物）
│   │   ├── _meta.json              #   机器：product / baseline / apps[] / domains[] / categories
│   │   ├── tour.md                 #   L1：paths ['**']
│   │   ├── domains/<domain>.md     #   L2：paths = 该域 globs
│   │   ├── global/{directory-map,routes}.md
│   │   └── {current,legacy}/<domain>/{apis,data-models}.md
│   └── spec/conventions/           # 约定类注入薄桩（当前仅 testid.md；派生视图）
│       └── testid.md               #   paths = 前端 app globs；正文归 E2E 环契约
├── .atlas/                         # atlas 包（由 install.sh 装配）
├── .impeccable/                    # impeccable detect 配置（可选外部工具；config.json 的 detector.ignoreRules 须与 product/design.md 的 detect 豁免双向一致）
└── product/                        # atlas 项目级文档
    ├── adr/                        # NNNN-<slug>.md（项目级长效架构决策记录，按需落笔，永不覆盖）
    ├── stack-profile.yaml          # 技术栈画像（字段契约见 stack-profile.md）
    ├── design.md                   # 视觉设计档案（frontend-design skill 写；atlas 只读——走查对照 + 豁免对账）
    ├── reviews/                    # <日期>-<主题>/（人工缺口清单 + plans/）+ calibration.jsonl（审查校准账本，append-only）
    ├── prd/                        # README.md（追溯总表）+ prd.md + <domain>-prd.md
    │   └── reviews/                # <日期>-<范围>/ 独立审查报告（README.md + review.json + inputs/）
    # （prototype/ 已退役 E1 且于 2026-09-30 删除——新项目与存量均不再有此目录）
    └── e2e/                        # e2e-index.md + cases/<page>.md + scripts/<page>.<ext>
        └── reviews/                # 同上（E2E 环独立审查）+ console/（人工评审账本，append-only）
```

## 3. role 语义

| role | 结构事实去向 | 说明 |
|---|---|---|
| `landing` | `.trellis/spec/structure/current/<domain>/` | 落地实现的事实 |
| `legacy` | `.trellis/spec/structure/legacy/<domain>/` | 事实来源（重构/存量项目才有） |

- 域清单见 `.trellis/spec/structure/_meta.json.domains`（机器）+ `tour.md` 域速查（人读）；structure 提议 → PRD 定稿回写。
- 同一 role 下有多个 app 时共用域级结构，域级文件内按 app 加小节 /「应用」列。
- 无 `role: legacy` 的 app 时，`legacy/` 整目录缺席。
- 绿地项目：可只有 `tour.md` + `_meta.json` 起步，域级随代码增长补齐。

## 4. 约定类分流（G / I 已移出）

- 编码规范（原 I 类）与 testid 约定（原 G 类）**不在 structure 环**；testid 约定**正文归 E2E 环契约**（`.atlas/rings/e2e/reference.md` §4），编码规范不由 atlas 收口。
- testid 在 `<项目根>/.trellis/spec/conventions/testid.md` 落一份**派生薄桩**（祈使句 + 指针 + 由**用例分片应然清单**派生的 testid 清单），供 Trellis 原生注入到实现任务；它是派生视图，不复制命名规则词表。
- A（技术栈 + 启动，可选）与 H（测试 / 运行，条件）的真相源均为**项目根 `README.md`**，**不入 spec**（受控例外，见 §1；仅对应两节，过确认门）。
