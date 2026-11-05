# 按功能运行测试

日常修改使用 `scripts/run_tests.py` 选择相关功能，避免每次运行全部后端测试。该入口只负责选测，不删除测试，也不改变原有测试逻辑。分组以文件为单位，包含该功能的单元测试和集成测试，不能将分组通过视为全项目回归通过。

在仓库根目录使用项目虚拟环境运行。Windows 示例：

```powershell
# 列出分组；检查是否遗漏新增测试或保留了已删除文件
.\.venv\Scripts\python.exe scripts/run_tests.py --list --check

# 文件功能：同时运行对应的 Python 和前端测试
.\.venv\Scripts\python.exe scripts/run_tests.py files

# 跨功能修改可选多个组，重复测试文件只执行一次
.\.venv\Scripts\python.exe scripts/run_tests.py ssh terminal

# 只改前端或后端时缩小范围
.\.venv\Scripts\python.exe scripts/run_tests.py workspace --scope frontend
.\.venv\Scripts\python.exe scripts/run_tests.py reservations --scope backend

# 先预览实际命令，不执行测试
.\.venv\Scripts\python.exe scripts/run_tests.py assistant mcp --dry-run

# 完整回归，包括 scripts 和 desktop 的 Node 测试、分组入口自身测试
.\.venv\Scripts\python.exe scripts/run_tests.py --all
```

macOS/Linux 将 Python 路径替换为 `.venv/bin/python`。入口调用当前 Python 解释器；执行前端或构建工具测试时，PATH 中还需有 Node.js，前端依赖需已安装。

| 分组 | 功能范围 |
|---|---|
| `core` | 基础 API、存储、资源判断、认证、凭据、sudo |
| `monitoring` | 采集、缓存、刷新、资源查询、历史和进程指标 |
| `hosts` | 主机名称、列表、Excel 导入、主机密钥、集群 |
| `reservations` | 单机和集群预约、通知、邮件和投递 |
| `ssh` | SSH 连接、密码、代理、隧道、端口转发、VS Code |
| `terminal` | 终端生命周期、工作区、补全、命令模板和填入 |
| `files` | 文件读写、搜索、传输、文件夹上传下载、日志和精度对比 |
| `assistant` | 模型配置、上下文、聊天、流式输出、Skills 和 Agent 引擎 |
| `mcp` | 工具 schema、参数与范围校验、传输协议及跨入口集成 |
| `workspace` | 多窗口偏好、界面布局、语言、新手引导和演示模式 |
| `desktop` | 托盘、浮窗、启动器、桌面运行时和更新 |
| `distribution` | 安装器、资源打包、源码归档、版本和发布工具 |
| `policy` | 内部参数生成、限制传播和分组入口自身校验 |

## 如何选择范围

- 只修改某个功能内部的实现，运行对应组。新增或修改具体测试时，也可以直接通过 pytest 或 Node 指定文件、用例。
- 修改跨功能调用链，选择所有受影响的组。例如文件 MCP 工具运行 `files mcp`，预约助手运行 `reservations assistant mcp`，SSH 终端运行 `ssh terminal`。
- 修改 `backend/app.py`、共享存储、认证/凭据边界、共用请求层或依赖版本等广泛影响行为的代码，执行全量回归。`core` 是基础能力测试，不能替代所有调用方的验证。
- 完成一项较大改动或发布前，执行全量回归。原有 `python -m pytest tests -q` 和 `frontend` 中的 `npm test` 仍可使用；它们不会因本入口而自动缩小范围。
- 该入口不分析 Git diff，也不自动推断依赖关系。功能测试存在交叉归属，执行前可用 `--dry-run` 检查范围。

执行器为每次运行设置临时 `IWB_DATA`，不沿用正在使用的工作台数据目录。前端与 Node 工具测试之前仍执行内部参数产物一致性检查；任一阶段失败即返回该失败退出码，不继续后续阶段。原生浮窗实测等显式开关沿用原测试约定，不由选测入口开启。

## 维护分组

分组清单位于 `scripts/run_tests.py` 的 `GROUPS`。新增、删除或重命名测试文件时，同步更新清单。运行 `--check` 会对照 `tests/test_*.py`、`frontend/tests/*.test.mjs`、`scripts/test_*.py`、`scripts/*.test.mjs` 和 `desktop/*.test.mjs`，缺失或未分配的文件都会报错。日常分组执行也会先做这项检查，避免新增测试悄悄漏跑。

入口自身验证：

```powershell
.\.venv\Scripts\python.exe -m pytest scripts/test_test_groups.py -q
```

分组执行不替代前端构建、Rust 测试或部署脚本验证。修改前端产品源码仍需 `npm run build` 并更新 `frontend/dist`；Rust、原生窗口和分发验证继续遵循项目协作说明。Compatibility 工作流保留全量后端验证，并检查分组清单与选测入口。
