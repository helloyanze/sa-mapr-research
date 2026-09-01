# Stage 2 v2.1.1 reproduction

本目录是从原论文工作区抽取的 20 Bug A/R/C 实验实现。它保留运行代码、冻结输入、Evidence Contracts、prompt、schema、JavaParser checker 和测试，不包含旧输出、模型响应、工作 checkout 或 API Key。

请从仓库根目录运行：

```bash
./scripts/doctor.sh
./scripts/run-stage2.sh prepare
./scripts/run-stage2.sh preflight
./scripts/run-stage2.sh full
```

数据挂载关系：

| 容器内目录 | 宿主目录 |
|---|---|
| `work/` | `$SAMAPR_DATA_ROOT/stage2/work/` |
| `outputs/` | `$SAMAPR_DATA_ROOT/stage2/legacy-outputs/` |
| `outputs_revised_mve/` | `$SAMAPR_DATA_ROOT/stage2/runs/` |
| `protocol_locks/` | `$SAMAPR_DATA_ROOT/stage2/protocol-locks/` |

新运行必须基于干净 Git 提交生成协议锁。旧正式锁位于 `analyses/stage2-correctness/inputs/provenance/`，不得复制到新运行中使用。
