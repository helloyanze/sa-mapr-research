# SA-MAPR Research Runtime

SA-MAPR 的独立实验仓库。仓库只保存可复现代码、冻结输入、协议、测试和小型结果；下载缓存、Defects4J checkout、模型原始响应和完整运行目录存放在仓库外。

## 目录

- `experiments/stage2-v2.1.1/`：20 Bug A/R/C 重跑实现与冻结输入。
- `analyses/stage2-correctness/`：现有正式结果的精简分析输入和后续统计代码。
- `infra/docker/`：Ubuntu 26.04 宿主上的 Docker 安装和 Ubuntu 24.04 实验镜像。
- `projects/_template/`：后续新实验项目模板。
- `artifacts/`：大文件目录约定与哈希目录；`artifacts/cache/` 不进入 Git。
- `runs/`、`results/`：前者永不提交，后者只允许经过确认的小型汇总。

## 第一次部署

```bash
git clone <你的新仓库地址> samapr
cd samapr
./infra/docker/install-docker-ubuntu26.sh
```

重新登录服务器使 `docker` 组权限生效，然后把固定依赖 ZIP 单独传入：

```text
artifacts/cache/defects4j-master.zip
artifacts/cache/defects4j-gradle-dists-v3.zip
artifacts/cache/defects4j-gradle-deps-v3.zip
artifacts/cache/spotbugs-4.10.3.zip
```

校验并构建镜像：

```bash
./infra/docker/build-image.sh
cp .env.example .env
nano .env
./scripts/doctor.sh
```

## Stage 2 重跑

所有运行数据默认写到 `~/samapr-data`，可用 `SAMAPR_DATA_ROOT` 修改。

```bash
./scripts/run-stage2.sh prepare
./scripts/run-stage2.sh preflight
./scripts/run-stage2.sh full
```

`full` 会再次执行 preflight，任何环境或 API 检查失败都会停止。新仓库重跑会生成新的 Run ID 和协议锁；旧正式结果的锁仅作为历史证据保存。

## 正式结果统计分析

```bash
./scripts/run-analysis.sh validate
```

后续统计代码放入 `analyses/stage2-correctness/scripts/`，结果先写入仓库外运行目录。只有确认后的 Markdown/CSV/JSON 汇总才复制到 `results/`。

## Git 同步规则

```bash
./scripts/install-git-hooks.sh
python3 scripts/check_repository.py
git status
```

默认限制单个候选文件不超过 5 MiB、一次暂存总量不超过 20 MiB，并拒绝 ZIP、日志、密钥和典型运行目录。不要使用 `git add -f` 绕过规则。

## 原始实验身份

- 原 Run ID：`stage2_mve_formal_20260825T210517`
- 原协议锁：`stage2-v2.1.1-7a7d2bd44d0bc085`
- 原实现提交：`513548d7f3aa779072e6ab65c57ace7455391efa`

这些值只用于核对已有正式结果，不会被迁移后的新运行复用。
