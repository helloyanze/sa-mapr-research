# External artifacts

大文件不进入 Git。构建镜像前，将四个固定 ZIP 放入 `artifacts/cache/`。文件身份由 `artifact-catalog.json` 中的字节数与 SHA-256 确认。

推荐服务器传输：

```bash
rsync -av --progress artifacts/cache/ user@server:~/samapr/artifacts/cache/
```

不要提交缓存，也不要使用 `git add -f`。正式运行产生的完整目录放在 `${SAMAPR_DATA_ROOT:-$HOME/samapr-data}`，备份时使用对象存储、移动硬盘或单独的归档服务器。
