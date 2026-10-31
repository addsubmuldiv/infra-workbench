# 用户技能验收记录

日期：2026-11-01（Asia/Hong_Kong）。工作分支 codex/user-skills，独立 managed worktree；未合并或推送 main。

## 已验证

- 后端针对性集合：62 通过（统一 MCP、技能存储/API、真实 Deep Agents 图、聊天兼容）。模型在自动测试中使用可控替身，执行图和 MCP 使用实际框架。
- 大范围回归：548 通过、8 跳过、3 排除；排除了 tests/test_auth.py，并将三个 Windows 原生 PTY 用例拆开运行。原始全量运行在原生 PTY 阶段挂起，停止的仅为本次拥有的测试进程。
- 三个原生 PTY 用例分别重跑：各 1 通过。
- tests/test_auth.py 单独重跑：2 通过、1 失败。失败 test_password_login_then_provision_and_verify_key[False]：临时私钥文件权限导致 OpenSSH 验证失败，返回 password_session；同时存在 Windows GBK 解码线程警告。SSH/terminal 及对应测试文件本次均未修改，不能声称全量全绿。
- 前端 209 项测试通过；TypeScript、Vite 生产构建通过；构建清单引用文件存在。内置技能打包路径沿用现有配置，未重新制作桌面安装包。
- pip check 通过；Git diff 空白检查通过。
- 独立审查后修复：编辑/复制保留二进制附件、停用及卸载移除旧虚拟文件、MCP 本轮快照一致性、草稿恢复、内置私有工具依赖、旧 MCP content 字段兼容。

大范围命令：

```powershell
python -m pytest -q --ignore=tests/test_auth.py -k 'not native_pty_roundtrip_resize_and_close_uses_only_its_own_process and not native_pty_preserves_argument_boundaries_without_duplicating_executable and not native_pty_advertises_xterm_without_changing_parent_environment' -o faulthandler_timeout=45
```

## 真实模型

运行 scripts/validate-user-skills.py，复用当前配置的模型和系统凭据读取机制，使用独立 work/user-skills-live/data，无服务器机器列表、无原聊天数据。

- 第一轮：create_skill_draft → validate_skill_draft → install_skill_draft 全部成功，约 22.6 秒。
- 第二轮：读取刚安装技能的 SKILL.md 成功，约 11.8 秒；实际记录 name/version/source。
- 验证报告位于 work/user-skills-live/report.json，不包含密钥、接口地址或回答正文。

## 界面

使用 127.0.0.1:18769 独立服务和 work/skills-ui-validation 数据目录，浏览器实际完成新建粘贴、安装、详情、停用、启用。AI 助手技能选择器可发现新安装技能。主应用 8765 未重启、未修改配置。

技能权限和模型调用仍遵循现有工具实现。脚本作为附件保存但不执行；静态校验不等于业务步骤已试运行。预览服务仅供本机检查，独立数据不会自动迁移到主应用。
