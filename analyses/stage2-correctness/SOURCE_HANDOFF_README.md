# SA-MAPR v2.1.1 Stage 2 下一 Agent 交接包

## 交接目标

本包交给“正确性感知的配对统计分析与论文结论 Agent”。其任务是在不改动正式生成和 correctness audit 冻结结果的前提下，完成配对效应、验证器、mapping、类别、成本分析，并正式回答 RQ1–RQ4 / H1–H4。

直接把根目录的 `NEXT_AGENT_PROMPT.md` 全文作为下一 Agent 的首条提示词。

## 包内结构

```text
NEXT_AGENT_PROMPT.md
HANDOFF_README.md
SOURCE_PACKAGE_REFERENCES.md
data/
  correctness_audit_full/   完整 developer-patch correctness audit（含审计 packet）
  mechanical/               正式生成的逐 Bug 与汇总机械结果
protocol/                   协议审计、协议锁、配置与 20 Bug 冻结清单
research_context/           RQ/Hypothesis、主控规格、机械结果冻结版结论
source_task/                correctness audit 原始任务书
PACKAGE_MANIFEST.csv        本交接包文件哈希清单（ZIP 外部生成前写入）
```

## 冻结结论锚点

- Run ID：`stage2_mve_formal_20260825T210517`
- Protocol Lock：`stage2-v2.1.1-7a7d2bd44d0bc085`
- 20 Bugs、60 primary runs、122 attempts。
- Correct：A=7/20、R=10/20、C=9/20。
- A→R gains/harms=3/0；R→C=0/1；A→C=3/1。
- Correctness Audit Gate：`STAGE2_CORRECTNESS_AUDIT_COMPLETE`。

这些数字是交接核对锚点，不替代下一 Agent 从 CSV/JSON 独立重算。

## 范围与安全

- 包内没有 `.env`、API key、模型凭据、工作 checkout 或 122 份原始模型响应。
- 包内输入均应按只读处理。
- 不允许重新生成 patch，也不允许把 plausible 当作 correct。
- 需要语义追溯时，优先查看 `data/correctness_audit_full/audit_packets/` 与 `developer_patches/`。

## 完整源包

若后续确实需要 122 attempts、raw responses、prompts 或完整 patches，请使用 `SOURCE_PACKAGE_REFERENCES.md` 中的正式生成包及哈希另行传输；统计收口任务默认不需要这些大体量内容。

