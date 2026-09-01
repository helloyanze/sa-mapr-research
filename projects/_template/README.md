# New project template

复制本目录后按以下边界组织新实验：

```text
<project>/
├── README.md
├── config/          # 可提交的配置和 example；无密钥
├── inputs/          # 小型冻结输入
├── scripts/         # 可复现入口
├── tests/
└── results/         # 只放经过确认的小型汇总
```

完整运行数据写入 `$SAMAPR_DATA_ROOT/<project>/`。不要在新项目下创建并提交 `outputs/`、`work/`、下载缓存、模型响应或归档 ZIP。
