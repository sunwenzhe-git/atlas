# 提案标题：简明扼要陈述本次改动（如：支持 FastAPI 子路由嵌套提取）

> 提案编号：RFC-YYYYMMDD-序号（例如：`RFC-20261008-01`）  
> 提案作者：@GitHub用户名  
> 关联状态：草案 (Draft) | 已定案 (Accepted) | 已合并 (Merged)  
> 影响范围：核心契约 (shared) | 环契约 (rings) | 校验器 (validators) | 适配器 (adapters) | 脚本工具 (scripts)

---

## 1. 现象与取证 (The Problem & Evidence)

详细陈述你在真实业务项目中遇到的 Atlas 流水线缺陷、契约盲区或规则不合理之处。**必须带真实代码或报错取证，拒绝主观推测。**

### 1.1 触发场景与业务背景
* **项目形态**：（如：Next.js + FastAPI 全栈项目 / 单体后端项目）
* **触发时机**：（如：在执行 `atlas apply` 时 / 运行 `validate_testids.py` 时 / 跑 E2E 控制台慢动作时）
* **具体行为**：（描述 Atlas 的异常反应，如：校验器误报、某个语法未被识别、某个流程产生死锁）

### 1.2 客观证据与日志 (Minimal Evidence)
给出截取的终端报错输出、Git Diff 或最小可复现的代码片段：

```text
# 贴出具体的报错信息、不合理的校验输出或异常日志
[FAIL] validate_structure: 未找到路由端点 ...
```

---

## 2. 决策与权衡 (The Decision & Trade-offs)

陈述针对该问题的解决思路。**必须解释为什么这么改，以及该方案的潜在代价。**

### 2.1 核心定案 (The Decision)
* **方案总结**：用一两句话陈述你拍板的最终解法（如：“在路由适配器中增加递归子路由解析逻辑，将未挂载的前缀继承给子路由”）；
* **为何这是正解**：解释该方案如何从根本上消除第 1 节的问题。

### 2.2 考虑过的备选方案及否定理由 (Considered Alternatives)
列出你在思考过程中曾经想过、但最终放弃的备选方案，并写出否决原因：
* **备选方案 A**：例如“在 stack-profile.yaml 中让人工手动配置所有嵌套路由”
  * *否定理由*：增加人类的心智负担，违背了逆向自动提取代码事实的初衷。
* **备选方案 B**：例如“忽略所有子路由报错，降级为 SKIP”
  * *否定理由*：产生静默漏审假阳性，破坏了门禁的严肃性。

### 2.3 必须警惕的刺痛代价与兼容性影响 (Trade-offs)
* 本次改动是否破坏了既有项目的兼容性？
* 是否增加了脚本的执行耗时？
* 存量项目拉取该改动后，是否需要重新运行 `atlas init` 或刷新事实？

---

## 3. 改动面清单 (Affected Surface)

列出为了落地该决策，你具体修改了 Atlas 仓库中的哪些文件：

- [ ] **契约/文档**：如 `shared/global-rules.md`、`rings/structure/reference.md`
- [ ] **代码逻辑**：如 `adapters/routes.py`、`validators/validate_structure.py`
- [ ] **测试防线**：如 `tests/test_adapter_routes.py`（**强约束：必须包含测试用例或 M 系列变异钉子**）
- [ ] **版本装配**：`package.json` 或 `install.sh`（若涉及）

---

## 4. 验证与测试结果 (Verification)

在提交 PR 前，本地必须运行并通过 Atlas 全套测试与自检：

```bash
# 1. 运行修改项相关的具体单元测试
pytest tests/test_adapter_routes.py

# 2. 运行出厂级全量测试套件（必须全绿）
pytest tests/

# 3. 运行 Atlas 快速自检
python3 scripts/atlas_check.py --fast
```

* **测试结果**：`XXX passed, 0 failed`
* **自检结论**：`OK`
