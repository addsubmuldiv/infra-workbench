# 应用更新

## 使用方式

从 v0.1.1 起，Windows 正式安装版会在启动后检查公开更新源。没有新版或网络不可用时，后台检查不会弹窗打断工作。进入“设置 → 桌面应用更新”可以手动检查、查看版本说明、下载更新并查看进度。

下载完成后，由用户点击“安装并重启”。原生确认窗口会显示目标版本。取消或安全检查失败后，已验证的下载会保留，可在处理问题后重试安装。

现有 v0.1.0 没有更新器，需要先手动安装 v0.1.1 一次。手动升级前请保存文件、妥善处理活动终端，并从托盘退出旧后台。后续公开版本可直接使用更新器。

浏览器、演示、开发模式和 macOS 当前不执行 Windows 自动安装流程。源码用户继续使用源码更新方式。仓库目前仍为私有；客户端没有 GitHub Token，公开前的检查可能提示无法读取公开更新源。仓库与 Release 公开后，固定地址即可供普通用户访问：

`https://github.com/addsubmuldiv/infra-workbench/releases/latest/download/latest.json`

## 安装保护

安装前检查全部桌面窗口中的未保存内容、活动终端和未完成的工作空间写入，并冻结窗口操作。后台另行检查模型任务、远程命令、文件传输、导入及在途 API/MCP 请求；忙碌时拒绝退出。远程命令状态未确认时保守处理，需先查询其状态。

检查通过后，后台停止接受新操作。原生端仅使用当前用户受保护的本地凭据，请求同一安装目录的冻结后台正常退出，并等待确定的进程句柄、监听端口和凭据文件均退出；不按进程名批量结束 Python，也不发送远程进程信号。

如果安装器无法启动，会尝试恢复后台并检查健康状态。若原后台延迟退出，更新器会继续观察原进程最多三分钟，并在安全条件满足时尝试恢复。无法确认安全状态时取消安装，不强行覆盖。成功更新会关闭桌面程序，由安装器启动新版本。用户数据目录和系统凭据不会作为更新文件删除。

## 签名与发布

更新清单包含版本、说明、各平台下载地址和签名。Tauri 更新器验证实际下载内容，并要求签名中的版本与清单版本一致；损坏、篡改、错误签名或版本不一致的包均不可安装。它不会接受调用方传入的任意更新地址或本地程序路径。

更新签名与 Windows Authenticode 代码签名不同；当前更新包具有更新签名，但 Windows 安装包仍未做 Authenticode 签名。

生产私钥保存在仓库之外：`~/.codex/secrets/infra-workbench-updater/update.key`，并已配置为本仓库的 GitHub Actions Secret `TAURI_SIGNING_PRIVATE_KEY`。请安全备份，不要提交、截图或发送私钥。软件与仓库只包含公钥。丢失私钥会影响已安装客户端的后续更新；fork 项目应生成自己的密钥并修改更新地址。

发布工作流在可信版本标签上使用加密 Secret 签名，生成各平台唯一命名的更新包、`.sig`、`latest.json` 和 `SHA256SUMS.txt`。PR 构建不读取生产签名密钥，只生成未签名测试安装包；这些产物不能进入更新清单。首次 Windows 引导发布可仅包含已构建的 Windows 平台，不会为未构建平台伪造下载地址。

本地签名构建示例（在仓库根目录）：

```powershell
$env:TAURI_SIGNING_PRIVATE_KEY = Join-Path $env:USERPROFILE '.codex/secrets/infra-workbench-updater/update.key'
$env:TAURI_SIGNING_PRIVATE_KEY_PASSWORD = ''
$env:CARGO_TARGET_DIR = Join-Path (Get-Location) 'work/release-validation/target'
Push-Location desktop
npm run build
Pop-Location
```

只做开发测试安装包时可显式设置 `IWB_UNSIGNED_BUILD=1`；该产物不生成更新签名，不可用于正式更新发布。正式签名步骤遵循 [Tauri 更新器文档](https://v2.tauri.app/plugin/updater/)。

## 验证边界

原生集成测试使用独立测试密钥和本地临时 HTTP 服务，验证正常签名下载、篡改文件、损坏签名、签名版本与清单版本不符的处理；测试从不安装示例包。生产环境仅配置固定 HTTPS 地址。

自动化还验证调用来源、状态互斥、旧版能力识别、界面保护、退出凭据、活动任务拒绝、后台关闭入口和发布清单。真实 Windows 升级、系统策略拦截、故障恢复及干净系统验收仍需实机验证，不能用构建成功代替。
