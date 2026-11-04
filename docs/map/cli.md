# L1 · CLI 与装配子系统

> 子系统 #1 / 上级地图:[index.md](index.md) / 锚定版本:v0.2.0-beta.7(2026-10-25 复核)
> 一句话:**把 atlas 装进目标仓 `.atlas/` 并保持副本与源包对账**——命令面薄、装配器厚,一切「副本漂移」在这个子系统的三个对账面(版本戳 / manifest / 回灌)里现形。

## 它不是什么

- 不做升级链:`npm install -g` 升级后用 `--force` 常规化不被支持(B-1 强口径否决)——升级走显式 `install.sh --update`。
- 不碰业务代码:只写 `.atlas/`、skill 瘦桩、wiring 触点;目标仓产品侧零落笔。
- 不是包管理器:没有依赖解析;`bin/atlas.js` 是命令路由,不是运行时。

## 文件清单

| 文件 | 行数 | 角色 |
|---|---|---|
| `bin/atlas.js` | 438 | CLI 入口:命令面总表见 `printHelp`(`bin/atlas.js:18`)= init / update / upgrade / check / review / eval / console / report / version,分派在同文件 `switch (command)`;平台探测拆到 `bin/platform.js`(Trellis 用 which/where、bash 只认 Git Bash、Python 按平台探测 3.10+) |
| `install.py` | 842 | 装配单源:白名单拷贝 + 版本戳 + manifest + 66 条 `c()` 自检 + 图谱探测;叶子脚本(layout / apply-patches / apply-wiring / pkg_digest / ablation / evidence_archive)复用不重写 |
| `install.sh` | 58 | 薄 wrapper:头部用法说明 + `exec python3 install.py`(装配逻辑零残留,自检门守) |
| `scripts/run_python.js` | 92 | 钩子平台中立启动器:`.trellis/config.yaml` 的 after_archive 调它;运行时解析 Python 3.10+(win32 py -3/真实 python,剔除 WindowsApps stub),转发 argv/退出码,强制 PYTHONUTF8=1 |
| `scripts/pkg_digest.py` | — | 内容摘要算法单点(`ASSEMBLY_COVER_DIRS`,`scripts/pkg_digest.py:52`):装配版本门两侧共用,防双端漂移 |
| `scripts/backflow.py` | — | 副本 ⇄ 源包三态回灌(`diff_trees`,`scripts/backflow.py:60`;`apply`,`scripts/backflow.py:97`) |
| `patches/`(4 族) | — | 锚点式版本化补丁:workflow-plan-apply / project-wiring / workflow-root-cause / workflow-skill-routing |

## 核心机制

### 1. 装配六步(`install.py`;`install.sh` 薄 wrapper)

`[1/6]` 整包 → `.atlas/`(`atlas_dest`,`install.py:472`,白名单目录拷贝,不整目录删,保住 `.atlas/runs/` 运行态)→ `[2/6]` skill 瘦桩(引用契约不复制正文)→ `[4/6]` 骨架 → `[5/6]` Trellis workflow 补丁(遍历 patches/)→ `[6/6]` 项目接线 → 图谱后端探测(可选)→ 自检段(`say("自检")`,`install.py:664`,65 条 `c()` 声明)。`--dry-run`(F54)零落盘、双摘要可见化;`--update` 刷新已装配副本。

### 2. 装配基线三件(D145/D146/D147)

`.atlas/VERSION` 内容摘要戳(落点 `install.py:790` `stamp_file`)与 `.atlas/MANIFEST.json` 逐文件基线(同点落),摘要算法单源在 `pkg_digest.py`——atlas_check 装配版本门按「配对校验先行」重算对账:戳在而 manifest 缺 = 显式「旧装配」半态,不是失败。写序先 manifest 后 VERSION。

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
| test_install_selfcheck | 自检引用必须存在:63 条 `check` 指向的文件必须真落下 |
| test_backflow | 三态语义 + SOURCE_ONLY 护栏钉 |
| Trellis | patches 族把 apply / 工作流步骤织进 `.trellis/workflow.md` |

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
3. **自检是装配的一部分**:声称落下的每个文件必须真落下——63 条声明本身就是契约。
