---
name: new-papers
description: Use when the user says “检查新论文”, “入库新论文”, or “解析新论文” for the Brainstorming Error Correction, Trapped-Ion, and Neutral-Atom folders. Scan for candidates, ingest when requested, and analyze after ingestion when requested. Do not run at session startup.
---
# 处理 Brainstorming 新论文

仅当用户要求检查、入库或解析这些目录中的新论文时执行。开启新会话、打开仓库或普通研究任务均不主动扫描；不创建后台监听或定时任务。用户只是在讨论或修改 skill、引用触发词作为例子时，不执行实际扫描或入库。

## 按用户意图执行

| 用户请求 | 流程 | 是否再询问入库 |
| --- | --- | --- |
| 检查新论文 | 扫描、去重、列出候选 | 是，等待用户选择后才入库 |
| 入库新论文 | 扫描、去重、展示本批次范围、执行入库 | 不重复确认，用户已授权本批次论文入库 |
| 解析新论文 | 扫描、去重、入库、逐篇分析论文内容并生成解析文件 | 不重复确认，用户已授权入库及内容分析 |

“入库新论文”和“解析新论文”默认处理本次扫描中未忽略、未入库的论文；用户指定目录、编号或文件时，以指定范围为准。不能把课件、笔记、海报等直接当作论文入库，类型不确定的项目先列出并澄清，同时继续处理范围明确的论文。用户明确要求检查 inbox 或指定其他来源时，按该来源及相应 skill 执行，不自动改扫 Brainstorming。

“解析新论文”在这里指入库后的论文内容分析，由 `paper-analysis` skill 执行；PDF 转 Markdown 是入库过程中的转换步骤。只有入库请求时，不额外生成论文解析报告。

## 扫描与筛选

从仓库根目录运行：

```bash
bash .claude/skills/new-papers/scripts/scan.sh
```

脚本自动查找 `/mnt/e/Study/Brainstorming` 或 `/mnt/c/Study/Brainstorming`，以唯一存在的目录为根目录。如果两处同时存在或都不存在，说明原因并停止；可通过 `SCHOLARAIO_BRAINSTORMING_ROOT` 环境变量显式指定根目录。不合并两块盘，也不静默切换来源。检查范围为根目录下的三个目录及其子目录，扩展名大小写不敏感：

- `Error Correction/`
- `Architecture/3.Trapped-Ion/`
- `Architecture/4.Neutral-Atom/`

扫描只读取 PDF 文件，不解析正文、不调用 API、不复制或移动源文件。扫描记录和候选清单保存在该 skill 的 `state/` 目录，不使用 `workspace/`。读取脚本生成的 `.claude/skills/new-papers/state/report.json`，按以下方式处理：

1. 目录不可访问或扫描失败时说明原因，不把失败当作没有新论文，也不重置历史记录。
2. 按 SHA-256 识别文件内容；同一内容的不同路径合并展示。首次扫描没有时间基线，候选称为“尚未确认入库的现有 PDF”，不能称为刚新增。后续扫描区分新增内容和此前尚未处理的候选。
3. `library_matches` 中 `sha256` 为内容完全相同的已入库文件；`source_file` 或 `title` 只是疑似已入库，结合库中元数据核验。不能仅凭近似标题断言已入库；不确定的补入候选列表。若库路径配置有变化，先依据当前 `Config` 更新脚本中的库路径。
4. 将 `candidates` 和核验后仍不确定的项目按目录分组列出，包含编号、文件名、相对路径和修改时间。文件修改时间不等于存入时间。脚本会生成 `.claude/skills/new-papers/state/candidates.md` 完整清单；列表过长时向用户提供链接及数量。基于文件名区分论文、疑似笔记、课件及海报，优先展示论文，其他 PDF 仍保留在清单中，不擅自永久排除。
5. 仅检查时，有候选就询问“是否入库？可以回复全部、编号，或暂不入库。”并等待选择；已要求入库或解析时直接进入后续流程。没有待处理论文时说明结果，不自动把目标扩大到整个已有库。

## 入库与解析

获得入库授权后，读取 [ingest skill](../ingest/SKILL.md)。只复制本批次选中的 PDF 到当前配置的 inbox，避免同名覆盖，保留源目录原件。先检查其他 inbox 待处理内容，避免顺带处理未授权文件；必要时用独立批次配置隔离所有 inbox，再运行 `uv run scholaraio pipeline ingest`。MinerU 不可用、失败或 token 过期时立即说明并暂停，不能自动改用其他解析器。

记录本批次“源文件 → 库中记录 ID”的对应关系，以库中实际生成或去重后已存在的记录为入库成功依据。失败和 pending 均保留为待处理，不能因已扫描、已询问或已复制就标记成功。下一次扫描会重新与实际库中记录比对。

用户要求“解析新论文”时，入库完成后读取 [paper-analysis skill](../paper-analysis/SKILL.md)，只分析本批次成功入库或去重后确认存在的目标记录。目标已由本流程定位，不再要求用户逐篇确认。按 L1/L2/L4 加载元数据、摘要和全文，检查关键图表，并按 `paper-analysis` 约定逐篇生成 `workspace/<主题>/Author-Year-Keywords-Analysis.md`。复用已有 workspace；没有对应 workspace 时按论文主题选择路径。失败或缺少全文的目标单独报告，不编造解析结果，也不因此跳过其他已成功的目标。

最后报告本批次已入库、去重、失败或 pending 的结果；解析请求还要给出各篇解析文件链接。

## 忽略记录与本地状态

“暂不入库”仅表示本次不处理；除非用户明确说“以后忽略”，不要持久排除。明确要求永久忽略时，将对应 SHA-256 合并到 `.claude/skills/new-papers/ignored.json` 数组并去重，保留已有记录。文件内容变化后会重新成为候选。

用户已确认的历史基线：2026 年 11 月以前未入库的现有 PDF 不需要入库。本次按 Asia/Hong_Kong 时区的文件修改时间，将早于 2026-11-01 的 38 个未匹配文件的 SHA-256 加入忽略列表。该确认针对现有文件内容，不要每个月自动扩大忽略范围；新发现的不同内容仍正常检查。

该 skill、脚本和 `ignored.json` 随 Git 同步。忽略记录仅包含内容摘要，不依赖盘符或绝对路径。`state/` 中的扫描历史和候选清单仅保存在本地，由 `.gitignore` 排除。
