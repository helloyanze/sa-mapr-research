# Stage 2 correctness-aware analysis

`inputs/` 是从既有正式结果中抽取的只读、小型分析输入：

- `correctness/`：60 个 A/R/C primary rows、correctness 审计表、developer patches 和派生表；
- `mechanical/`：成本、运行清单、mapping 与机械验证汇总；
- `protocol/`：原正式运行配置、协议审计和 20 Bug 清单；
- `provenance/`：原正式协议锁。

未复制的材料包括 audit packet 重复源码、完整模型响应、逐 attempt 日志、SpotBugs XML 和历史 ZIP。需要语义复审时，应通过原论文工作区或外部归档恢复，不能从 Git 猜测。

输入 Gate：

```bash
./scripts/run-analysis.sh validate
```

后续正式统计实现放在本目录的 `scripts/analyze.py`，并由 `./scripts/run-analysis.sh full` 调用。输出挂载到 `$SAMAPR_DATA_ROOT/analysis/stage2-correctness/`，确认后再选择小型汇总发布至仓库根目录 `results/`。
