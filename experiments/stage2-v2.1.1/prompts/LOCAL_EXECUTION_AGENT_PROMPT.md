# 本地执行提示词

你只负责运行本目录中的确定性脚本，不直接查看或推测 developer patch。

执行顺序：

1. 检查并编辑 `config/stage2_config.json`；
2. 设置 `LLM_API_KEY`；
3. 执行 `./run_preflight.sh`；
4. 读取 `outputs/preflight_gate.json`；
5. 只有 `pass=true` 时执行 `./run_full.sh`；
6. 最后执行 `./run_postprocess.sh`；
7. 不打开 `frozen_inputs/private_audit/` 构造修复 prompt；
8. 不把 plausible 写成 correct；
9. 不启用3个备选 Bug，除非主控书面批准。
