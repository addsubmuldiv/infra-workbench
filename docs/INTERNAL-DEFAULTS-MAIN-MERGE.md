# 内部策略整改合入 main 验证

- 原 main：`8d8c035`，包含 NPU 解析、采集状态/超时、助手查询优化三个新增提交。
- 组合合并提交：`02742fafd84747d3ad1b017833009c27e33f18c9`。源代码自动合并；仅 `frontend/dist/index.html` 和 `.iwb-build.json` 冲突，以重新构建产物解决。
- Node 生成/版本/发布测试：13 passed。
- 组合后端完整回归：992 passed、14 skipped，13 项依赖弃用警告。
- 组合前端完整测试：356 passed；正常构建和独立演示构建通过。
- 同一提交源码归档验证通过；生成一致性与 diff 检查通过。
- Windows x64 开发安装包构建通过，冻结自检 ok=true、policy_checks=14；没有运行安装器或重启正式后台，没有真实 SSH/模型调用。
- 新包：`Infra-Workbench-0.2.1-main-02742fa-x64-setup.exe`，50253590 字节；SHA-256：`d40eec0c0b1b6ee92a694ef2056060b308ac7af2430d5c862fb77136dbaebfa3`。
- 安装包及 `main-build-receipt.json`、`MAIN-SHA256SUMS.txt`、`main-runtime-self-test.json` 放在 `release/internal-defaults/`；无正式更新签名，未发布。
- 原目录在验证期间新增了与本整改重叠的 file_ops.py、file_routes.py、mcp_skills.py 改动。仅对这 3 个文件临时 stash，保留独立备份和补丁，快进 main 后恢复，逐文件核对与预计算三方合并结果一致；已移除本次临时 stash。其他未提交文件原位保留，均未纳入本次提交。
- 仅合入本地 main，不执行推送。新电脑安装及 macOS 实机验收仍未执行。

本地 main 已快进到已验证的合并结果；原目录保留其他任务全部未提交修改。合并后的安装包仅对应已提交代码，不包含这些正在进行的修改。
