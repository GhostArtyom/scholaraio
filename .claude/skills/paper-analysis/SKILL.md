---
name: paper-analysis
description: Use when the user wants detailed analysis of a specific paper, says "详细解析", "分析这篇论文", "帮我看看这篇论文", or gives author + keywords to identify a paper for deep analysis.
---
# 论文详细解析

对用户指定的单篇论文进行结构化深度分析，用专业但直白的语言讲清楚核心内容，输出为完整的 Analysis 文件。

## 核心原则

- **直接指定论文**：用户已知道要看哪篇，不需要从模糊关键词搜索筛选
- **省去用户逐页阅读**：替用户读完并提炼核心内容，不是翻译原文
- **专业但不炫技**：用户有量子领域研究背景，避免过度使用比喻或科普语言
- **证据先行**：所有论断基于原文（L4 全文、图表），区分事实与作者宣称
- **灰暗诚实**：指出方法缺陷、过度宣称和逻辑漏洞，不盲从权威

## 执行逻辑

### 1. 解析用户输入，定位目标论文

用户输入可能的形式：
- 论文目录名（如 `Yin-2026-iSwitch`）
- 作者 + 关键词（如 "Jones surface code 架构"）
- 标题片段（如 "architecting scalable trapped ion"）
- DOI / UUID

若输入模糊，先搜索确认：

```bash
scholaraio search "<关键词>" --limit 5
# 或语义搜索
scholaraio usearch "<描述>" --limit 5
```

找到论文后，先确认论文信息（L1 元数据），向用户展示标题、作者、年份，简短确认后继续。

### 2. 加载论文内容

```bash
scholaraio show "<paper-id>" --layer 1    # 元数据
scholaraio show "<paper-id>" --layer 2    # 摘要
scholaraio show "<paper-id>" --layer 4    # 全文
```

同时检查：
- `notes.md`：复用已有分析笔记
- `images/`：打开关键图表确认数据（坐标轴、样本量、误差棒、趋势）

### 3. 结构化分析

按以下 10 个维度进行分析。对每个维度，从原文提取证据，用自己的语言组织输出，不是罗列要点：

**1. 论文信息**
- 标题、作者（含单位）、年份、期刊/会议、DOI
- 代码/数据可用性（如有）

**2. 核心科学问题**
- 这篇论文试图解决什么问题？为什么这个问题重要？
- 在领域中的位置——谁还需要这个答案？

**3. 核心假设**
- 作者依赖的理论前提
- 硬件假设、噪声模型假设、计算模型假设
- 评估这些假设的合理性和局限性

**4. 研究设计**
- 整体研究思路：理论推导/仿真/实验/混合方法
- 关键设计决策及其理由
- 如有系统架构或框架，给出整体框图式的描述

**5. 关键方法深入**
- 如果方法有显著创新，展开解释其核心机制
- 用直观语言描述复杂的技术过程
- 必要时与已有方法做简要对比

**6. 实验结果**
- 最重要的定量/定性发现
- 与哪些基线做了对比，对比是否公平
- 消融实验的关键发现
- 实验规模（量子比特数、电路深度等）

**7. 方法严谨性评价**
- 优点：设计合理、验证充分、工程贡献清晰
- 局限：样本局限、方法缺陷、过度外推、对照缺失、开源情况
- 作者的宣称是否被实验数据充分支撑

**8. 领域贡献与定位**
- 该研究在其领域中的具体贡献
- 与已有关键工作的关系（对比表格）
- 对未来研究的可迁移性和启示

**9. 代表性参考文献**
- 文中引用的 1-3 篇奠基性工作
- 简要说明每篇与本文的关系

**10. 总结**
- 一句话概括核心贡献
- 对未来方向的 2-3 点启示

### 4. 写入文件

将分析内容写入工作区：

**文件路径**：`workspace/<workspace-name>/Author-Year-Keywords-Analysis.md`

命名规则：
- 从 `data/libraries/papers/<paper-dir>/` 截取 Author-Year-Keywords 部分
- 关键词从论文目录名取前 2-4 个核心词
- 后缀统一为 `-Analysis.md`

示例：
```
workspace/trapped-ion/Jones-2026-Architecting-Scalable-Analysis.md
workspace/error-connection/Cleland-2022-Surface-Code-Analysis.md
```

**文件格式**：
```markdown
# 论文短标题 —— 详细解析

## 论文信息
...

## 一、核心科学问题
...

## 二、核心假设
...

## 三、研究设计
...

## 四、关键方法深入
...

## 五、实验结果
...

## 六、方法严谨性评价
...

## 七、领域贡献与定位
...

## 八、代表性参考文献
...

## 九、总结
...

```

如果某维度不适用（如纯理论论文没有实验），灵活调整标题。

### 5. 聊天输出

写完文件后，在聊天中给出简短摘要（3-5 句），包括：
- 论文一句话贡献
- 最关键的一个发现或结论
- 文件路径

## 多论文处理

如果用户同时要求解析多篇论文，每篇独立分析，写入独立的 Analysis 文件。如果论文之间有内在联系（同一课题组、同一主题演进），可以在每篇分析完成后，额外生成一篇横向对比分析。

## 示例

**用户**："详细解析 Jones 2026 ASPLOS 那篇"
→ 搜索确认 → 加载 L1/L2/L4 → 按 10 维度分析 → 写入 `workspace/trapped-ion/Jones-2026-Architecting-Scalable-Analysis.md` → 聊天输出摘要

**用户**："帮我分析一下 Cleland surface code 那篇"
→ 搜索确认 → 加载内容 → 分析 → 写入 `workspace/error-connection/Cleland-2022-Surface-Code-Analysis.md`

**用户**："分析这篇 Jones surface code 架构的文章"
→ 模糊关键词 → `scholaraio search "Jones surface code architecture"` → 确认 → 加载 → 分析 → 写入文件
