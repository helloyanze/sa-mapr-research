# Docker environment

Ubuntu 26.04 只作为宿主。镜像固定使用 Ubuntu 24.04、OpenJDK 11、Maven、Python 3.12、Defects4J 固定快照和 SpotBugs 4.10.3。

1. `./install-docker-ubuntu26.sh`
2. 将 `artifacts/cache/` 四个 ZIP 单独传到服务器。
3. `./build-image.sh`
4. `../../scripts/doctor.sh`

镜像构建仍需网络完成 Defects4J `init.sh` 下载的项目仓库、Major 和测试生成工具。四个本地 ZIP 用于固定 Defects4J 主体、Gradle 缓存和 SpotBugs 身份。
