---
name: atlas-release
description: "Atlas 仓库专用自动化发布与推送技能。全自动处理网络代理（7897）、全量测试门禁、版本推导防跳号、四处版本落点同步、Git 提交打标推送、NPM prerelease 发布与 registry 轮询验证。"
---

# Atlas 自动化发版与推送技能 (Atlas Release Skill)

本 Skill 专为 **Atlas** 治理引擎仓库（`github.com/sunwenzhe-git/atlas`，NPM 包 `atlas-project-harness`）定制，固化多轮实证沉淀的《推送与发版机械规范》，在全新会话中执行可大幅节省上下文。

## 🎯 触发时机

当用户提及以下意图时调用本 Skill：
- "发布", "发版", "推送并发布", "本地还有提交吗，发一版", "发一下"
- 显式调用 `/atlas-release`

---

## ⚡ 极速执行方式（推荐）

仓库已内置全套经过实战检验的机械化发版工具 `scripts/release.py`：

```bash
# 1. 状态诊断（只读）：查看代理、本地未推送提交、工作区改动、npm当前版本与下一个推荐版本
python3 scripts/release.py --status

# 2. 模拟运行（不写盘、不推送、不发布）：运行全量测试并预演版本计算
python3 scripts/release.py --check

# 3. 全自动完整发布（自动跑测试、同步版本、打标签、推送、发 npm 并轮询生效）
python3 scripts/release.py --auto
```

---

## 📋 核心发版纪律与关键落点（严防踩坑）

如果需要人工或逐步介入，必须严格遵循以下 **6 大纪律**：

### 1. 网络代理（必须走 7897 端口）
- **现象**：本机直连 GitHub 443 必超时（`Failed to connect to github.com port 443 after 75s`）。
- **规则**：所有 `git fetch`、`git push`、`git ls-remote` 命令必须添加代理环境变量：
  ```bash
  https_proxy=http://127.0.0.1:7897 git push origin main vX.Y.Z
  ```

### 2. 版本推导防跳号（CHANGELOG 标题 ≠ 实际发版）
- **痛点**：并行会话经常预先在 CHANGELOG 写了未发布的版本段落，如果轻信文档标题容易导致版本**跳号**。
- **唯一真相源**：发版前必须以 **NPM Registry 真实版本** 与 **Git Tag** 判定顺延号：
  ```bash
  npm view atlas-project-harness dist-tags
  git tag -l --sort=-v:refname | head -5
  ```
- **规则**：若 npm 当前为 `0.2.0-beta.1`，下一个发版版本严格为 `0.2.0-beta.2`。npm 规则禁止覆盖已发布版本，跳号无法逆向填补。

### 3. 版本号五处落点同步（一次升版，全处修改）
1. `package.json`: `"version": "0.X.Y-beta.N"`
2. `README.md` 徽章: `<img src="https://img.shields.io/badge/version-0.X.Y--beta.N-blue.svg" alt="Version" />`
   - **注意**：shields.io 规范要求版本与 tag 之间必须为**双连字符** `--beta.N`，误写单连字符会导致徽章渲染异常。
3. `docs/.vitepress/config.mts`: `{ text: 'v0.X.Y-beta.N', link: 'https://github.com/sunwenzhe-git/atlas/releases' }`
4. `CHANGELOG.md`: 将顶部的 `## [Unreleased]` 收拢为 `## [v0.X.Y-beta.N] - YYYY-MM-DD`。
5. `docs/guide/changelog.md`: 同步将 `## [Unreleased]` 收拢或同步最新版本说明。

### 4. 严苛测试门禁
发版前必须跑通测试，出现任何失败严禁发版：
```bash
# 规范一致性门禁（钉子测试与文档计数）
pytest tests/test_canonical_consistency.py -q

# 全量回归套件
pytest tests/ -q
```

### 5. 功能提交与发版 Chore 分离
- 若工作区有业务代码改动（`feat(...)` 或 `fix(...)`），**先作为独立的特性 commit 提交入库**。
- 随后修改版本号与 CHANGELOG，提交发版专用 commit：
  ```bash
  git commit -am "chore(release): v0.X.Y-beta.N"
  git tag v0.X.Y-beta.N
  ```

### 6. NPM Prerelease 发布与异步生效轮询
- **发布命令**：
  ```bash
  # prerelease 必须显式声明 --tag beta，否则 npm 拒绝发布
  npm publish --tag beta

  # 立即更新 latest dist-tag
  npm dist-tag add atlas-project-harness@0.X.Y-beta.N latest
  ```
- **传播延迟机制**：
  - `npm publish` 返回 `PUT 202`（`Your package is being processed`）属于后台异步排队。
  - **切勿短时间重复执行 publish**，否则会触发 `E409 Conflict - Cannot publish over previously staged version`。
- **轮询验证**：
  使用带时间戳 cache-buster 的请求轮询 registry 直至新版本生效：
  ```bash
  curl -s "https://registry.npmjs.org/atlas-project-harness?t=$(date +%s)" | jq '.["dist-tags"]'
  ```
  确认 `beta` 和 `latest` 双双指向目标版本。

---

## 🛠️ 标准发版执行流模板

在对话中协助用户发版时的标准化四步走：

1. **第一步：看现场**
   ```bash
   python3 scripts/release.py --status
   ```
2. **第二步：清工作区**
   若有功能代码未提交，先 `git add` 并提交对应 `feat/fix`。
3. **第三步：跑脚本**
   ```bash
   python3 scripts/release.py --auto
   ```
4. **第四步：报结果**
   汇报最终 Git 提交 hash、Tag、NPM 生效版本，并提示用户在采纳仓更新：
   ```bash
   atlas upgrade && atlas update
   ```
