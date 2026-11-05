# 内部数字参数整改实施方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将需要维护的软件默认策略和重复限制集中到一个源码配置文件，保留协议、算法、安全流程和布局常量的所属位置；迁移期间保持当前行为。

**Architecture:** 以 `config/internal-defaults.jsonc` 为唯一手工维护来源，由确定性生成器产生 Python 和 TypeScript 常量。后台与前端通过各自生成文件消费同一参数；远端探针使用随源码生成的独立常量，不能依赖本机模块或运行目录。首轮不迁移 Rust 更新流程、不增加运行时配置加载与热更新。

**Tech Stack:** JSONC、Node.js、Python、TypeScript；复用现有 npm、pytest、Tauri 构建流程，不引入配置框架。

**Spec:** 本文第 1–6 节为设计约定；依据 `docs/INTERNAL-PARAMETERS.md` 的候选清单与当前业务源码。清单不是所有数字的穷举，迁移前需补查实际调用链。

## 全局约束

- 首轮只移动来源，不调整数值、默认行为、刷新频率、并发数和能力范围。
- `version.json` 继续独立管理应用版本；不把依赖版本、数据库版本或协议版本并入内部配置。
- 配置随源码和安装包生成产物发布，不读取用户数据目录中的同名文件，不提供编辑界面或环境变量覆盖。
- 运行时只使用生成的常量；源码 Python 运行、安装版运行和远端 probe 均不要求 Node.js。
- 沿用共享服务校验、机器范围与取消行为，HTTP、内置助手和外部 MCP 不增加独立校验实现。
- 新增或修改用户可见提示沿用现有中英文机制；限制值改变时提示和服务校验一致。
- 用户已经保存的刷新频率、窗口尺寸等继续优先；内部默认值不能覆盖共享工作空间状态。
- 演示使用静态生成值，不为读取限制请求真实后台。
- 资源缺失和过期保留未知状态、采样时间；预约不变成锁定或调度。
- `frontend/dist` 继续随仓库分发，涉及前端时构建并提交变化后的产物。
- 不重启当前后台，不连接真实 SSH、模型或邮件服务，除非执行阶段另有明确授权。

## 审查重点

1. 非默认值能否传到所有消费者，而不只是默认值相同时恰好通过测试？任务 1、2 用临时配置修改值进行验证。
2. 远端 probe 能否独立执行，无本机包、无配置文件且不受用户输入覆盖？任务 2 独立子进程验证。
3. 旧前端连接新后台时，容量提示可能不一致，但服务端仍必须执行权威校验；任务 2 明确兼容策略。
4. 源码缺配置、生成文件过期或生成中失败时，是否会悄悄恢复旧默认值？任务 1、5 验证失败行为。
5. 保存过的用户偏好、演示模式与不同语言是否保持原行为？任务 4 覆盖恢复和隔离测试。

## 1. 范围与取舍

### 1.1 迁入内部 JSON

只迁移有明确维护价值的策略，按用途命名，不按语言或文件归类。

| 分组 | 首轮拟纳入 | 当前源码中的示例 | 优先级 |
|---|---|---|---|
| `files` | 单文件上传、文件夹总量、条目数、清单大小、文本编辑、复制大小和条目数 | 上传 512 MiB；文本 1 MiB；复制 64 MiB；文件夹 10000 项；清单 1 MiB | P1 |
| `logs` | 下载总量、读取总量、记录数、单行大小 | 512 MiB、64 MiB、10000 条、65536 字节 | P1 |
| `imports` | 工作簿大小、行数、ZIP 条目数与解压总量 | 2 MiB、100 行、2000 项、16 MiB | P1 |
| `skills` | 上传包、解压总量、单文件、文件数量 | 2 MiB、8 MiB、1 MiB、128 项 | P1 |
| `ssh` | 默认连接预算、跳板附加预算、采集命令预算、保活参数 | 20 秒、20 秒、35 秒、60 秒/3 次 | P2 |
| `transfers` | 活跃并发、保留任务数、任务过期时间、传输超时 | `file_transfers.py`：2、32、600 秒、600 秒 | P2 |
| `history` | 变化历史和资源历史的保留时长、变化记录数上限 | 7 天、30 天、10000 条 | P2 |
| `assistant` | 元数据缓存、失败缓存、查询预算和默认上下文 | `agent_context.py`：3600 秒、60 秒、8 秒、32000 token | P3 |
| `notifications` | 待发送通知有效期 | 120 秒 | P3 |
| `ui` | 业务列表轮询、提示持续时间、合并刷新延迟 | 迁移前逐个核对；不同业务不能仅因数值相同就合并 | P3 |

上表为本次核实的示例，不代表全部默认值已完成逐项签字。尤其不要根据历史记忆把未在当前源码定位到的“模型列表缓存 14 天”写入配置；执行前先确认现有实现。

同为 512 MiB 的上传、下载和文件夹限制分别命名。它们目前相同并不能证明未来必须一起修改；同一业务限制在多个位置重复使用时才共用一个键。

### 1.2 继续保留在模块中的命名常量

| 类别 | 位置或示例 | 原因与后续处理 |
|---|---|---|
| 数据可信度 | `reservations.py` 的 `MAX_SAMPLE_GAP`；`resource_stats.py` 的 `max(45, refresh_interval + 40)` | 属于判断规则；本轮不动，后续专门设计与回归 |
| 安装退出和恢复 | Rust 更新器中的退出、监听消失、恢复观察时间 | 关联进程安全；保留模块内，不能套用普通 HTTP 超时 |
| 启动等待链 | 桌面、launcher、PowerShell 多阶段预算 | 先画出内外预算关系，首轮不跨语言统一；后端普通连接超时不等于启动期限 |
| 并发语义 | `queue.Queue(maxsize=1)` | 可能表示只保留最新状态；改成容量参数会改变算法 |
| 绘图和布局 | `floating_layout.py` 的最小/默认/最大尺寸、缩放；图标路径和边距 | 已按布局职责集中；不进入全局配置 |
| 局部性能细节 | 读写块大小、绘图 LRU 容量、短暂线程等待、动画帧间隔 | 无明确维护需求时保留；不为消除数字而迁移 |
| 协议和身份边界 | PID 范围、哈希长度、路径字符规则、凭据平台限制 | 在对应校验模块维护，修改时需要协议或平台依据 |

### 1.3 保持固定定义

- 单位换算：`1024 ** 2`、`1024 ** 3`、秒与毫秒换算。
- 数据范围：利用率 0–100、必填数量至少 1 等定义。
- 协议、schema、数据库规则版本号及字段格式。
- 现有用户偏好本身：刷新频率、预约等待时间、窗口大小等仍在原有状态中存储，不复制一份到内部 JSON。

## 2. 配置格式与接口

建议使用 JSON：现有 Node 工具可直接读取，支持嵌套对象、类型检查和稳定生成。INI 也能表达简单配置，但本项目没有必要再引入一套解析与类型转换。

示意结构（键名为设计提案，数值来自已核实示例）：

```json
{
  "files": {
    "upload_max_bytes": 536870912,
    "folder_upload_max_bytes": 536870912,
    "folder_upload_max_entries": 10000,
    "folder_manifest_max_bytes": 1048576,
    "text_edit_max_bytes": 1048576,
    "copy_max_bytes": 67108864,
    "copy_max_entries": 1000
  },
  "ssh": {
    "connect_timeout_seconds": 20,
    "jump_extra_timeout_seconds": 20,
    "collection_timeout_seconds": 35,
    "keepalive_interval_seconds": 60,
    "keepalive_count_max": 3
  },
  "history": {
    "changes_retention_days": 7,
    "changes_max_events": 10000,
    "resources_retention_days": 30
  }
}
```

规则：

- 每个键有明确类型、单位、用途、消费者和迁移前数值；配置源使用 JSONC，逐项写中文注释，注明单位、用途和调整边界。
- 容量用整数 bytes，预算用带单位后缀的 seconds/milliseconds，保留策略用 days，比例用 ratio，禁止含糊的 `timeout` 或 `limit`。
- 生成器拒绝重复键、未知键、缺失键、布尔值代替数字、非有限数、非整数容量及越界值。
- 合法范围由生成器的 schema/校验代码维护；JSON 不能修改自己的校验规则。范围需结合每项用途确定，不能临时编造统一上限。
- 现有硬性资源上限若需放大，必须单独说明内存、磁盘、解压和并发影响并执行边界验证；本轮不改变现值。
- 不建立 `global_timeout`。连接、执行、取消、清理、安装分别命名；内层超时与外层预算的关系在对应测试中表达。
- 生成 Python 常量，不导出可变全局 dict；前端采用只读常量导出。调用方不得在运行中修改。

## 3. 文件职责与生成策略

以下为拟新增文件，不表示已经创建。

| 文件 | 职责 |
|---|---|
| `config/internal-defaults.jsonc` | 唯一手工维护的内部策略数值 |
| `scripts/generate-internal-defaults.mjs` | 验证配置，生成产物，提供 `--check`；无网络、无用户数据访问 |
| `scripts/internal-defaults-schema.mjs` | 键、类型、允许范围及目标常量映射；保持简单，不引入通用配置框架 |
| `backend/internal_defaults.py` | 自动生成 Python 常量，提交仓库，供后台与托盘使用 |
| `frontend/src/internalDefaults.ts` | 自动生成前端需要的公开子集，提交仓库 |
| `docs/INTERNAL-DEFAULTS.md` | 各键的单位、含义、消费者、维护方法和重建要求 |
| `scripts/generate-internal-defaults.test.mjs` | 生成、校验、非默认值与过期检测测试 |
| `tests/test_internal_defaults.py` | 业务消费者与独立 probe 的行为验证 |

生成器接口建议：`generateInternalDefaults(root, {check: false})`，CLI 为 `node scripts/generate-internal-defaults.mjs [--check]`。

生成内容稳定排序、UTF-8、LF，不写时间戳；全部读取和校验通过后再写入。单文件采用临时文件替换；多文件生成中断后由 `--check` 检出不一致，不能声称具有跨文件事务性。

保留生成文件是为了让源码运行与安装版无需 Node。后台运行不自动重建；缺少生成文件明确失败，不偷偷套用另一份默认数字。

Rust 暂不新增生成器和 serde 配置读取。确有跨 Rust/Python 共享的策略后，再评估生成 `internal_defaults.rs`，而不是首轮就迁移所有桌面时间参数。

## 4. 远端探针与跨入口一致性

`file_transfers.py`、`log_download.py` 目前会读取探针源码后通过 SSH 执行。远端没有本机 `backend` 包，也不保证能读取项目配置，这是本次迁移的关键约束。

方案：生成器为需要限制的独立 probe 写入明确标记的自动生成常量区；业务代码区保留人工维护。生成只允许替换成对且唯一的标记区，标记丢失或重复立即失败。后续若收益明确再拆模板，不在本轮同时重写探针组织方式。

- probe 保持可以作为独立源码通过 stdin 执行，不导入本机生成模块。
- 只生成受 schema 校验的内部数字，不用请求参数覆盖上限，不把用户文本拼进源码。
- 单文件上传、文件夹上传、下载与本机预校验使用同一个业务键；不能只改后台而漏掉 probe。
- HTTP、助手工具和外部 MCP 仍调用已有业务服务。工具 schema、描述及错误提示中的数字同步引用，避免另建一套限制。
- 前端生成值用于提前提示；服务端始终是最终校验方。首轮不新增配置下发接口。
- 前后端来自不同版本时，后台拒绝应显示实际限制及清楚的错误；不承诺旧 UI 的提前提示完全准确，也不放宽服务校验来兼容旧前端。
- 演示直接使用前端静态生成值，不能为取得参数访问真实 API。

## 5. 构建、发版与运行边界

- 前端 dev/build/demo 入口先生成；桌面 `run.mjs` 在前端构建和 Python 打包前生成。
- CI 在单元测试、Cargo 检查和打包前执行生成；另有只检查已提交产物的步骤，防止 CI 自动修复后掩盖漏提交。`--check` 必须先于自动生成执行。
- 保留现有版本同步机制，不把内部配置混进 `sync-version.mjs` 的版本替换逻辑。两个生成过程无互相改写。
- 源码分发继续从提交生成归档，不能打包工作区生成值。归档前验证该提交中配置与生成文件一致，不修改归档来源提交。
- PyInstaller 将生成模块作为普通 Python 依赖收集；自检验证独立 probe 确实被打入安装运行时。
- 修改配置后需要重新生成并提交产物；涉及前端还需重新构建 dist，涉及桌面分发则重建安装包。已运行进程不会热更新常量。
- 不让内部配置的变化覆盖用户保存的偏好，不更换数据库键，不引入自动数据迁移。

## 6. 迁移步骤与验收

每个任务可独立审查和回滚。默认按顺序实施，不要求多代理并行；每阶段通过相关测试后再迁移下一组。

### 任务 1：配置与生成基础设施

**文件：** 新增第 3 节的配置、生成器、schema、生成模块、文档及生成测试。

- [ ] 整理第一批参数表：键、现值、单位、消费者、校验范围；只纳入 P1 项。
- [ ] 先写临时目录测试：合法配置、重复/缺失/未知键、错误类型、范围错误、稳定输出、过期生成文件与失败不部分写入。
- [ ] 实现生成器和 `--check`。不改现有业务消费者。
- [ ] 使用不同于生产默认值的临时配置生成产物并验证，防止测试只证明默认值巧合一致。
- [ ] 校验生成的 Python/TS 可导入；生成文件头标明来源及命令。
- [ ] 提交可单独工作的生成基础设施。

**验收：** 重复生成无 diff；修改一个源值能够被 `--check` 检出；非法配置不产生新产物；正常运行不需要 JSON 文件或 Node。

### 任务 2：文件、日志、导入和技能限制

**主要文件：** `backend/file_ops.py`、`file_transfers.py`、`file_upload_probe.py`、`folder_upload_probe.py`、`folder_download_probe.py`、`log_download.py`、`log_reader.py`、`server_import.py`、`skill_service.py`、`mcp_skills.py`；前端上传/编辑/导入/技能消费者在迁移前按引用定位。

**现有回归：** `tests/test_file_ops.py`、`test_file_transfers.py`、`test_folder_upload.py`、`test_folder_download.py`、`test_server_import.py`、`test_user_skills.py`、`test_skill_integration.py`；前端对应 files、folder-upload、file-transfers、server-import、skills 测试。

- [ ] 先补边界测试：上限恰好通过、上限加 1 拒绝；数量限制同样覆盖，不只验证报错字符串。
- [ ] 增加小型非默认限制测试，使用临时目录和小数据证明多个消费者实际读取相同来源，避免创建数百 MiB 测试文件。
- [ ] 将本机校验和 probe 标记区替换为同源常量，保持路径、权限、校验、取消与传输流处理。
- [ ] 同步 MCP schema、工具说明及中英文动态提示；数量/单位格式化不重复写死限制值。
- [ ] 用独立子进程执行生成后的 probe，验证无本机导入依赖且不能被请求放宽上限。
- [ ] 覆盖旧前端提示与后台拒绝不一致时的错误展示，以及演示零外部请求。
- [ ] 跑本阶段回归、前端测试和构建，通过后独立提交。

**验收：** 迁移前后所有边界相同；更改一个内部限制并重建后，本地、probe、前端提示与工具 schema 同步；HTTP 与 MCP 不绕过共享校验。

### 任务 3：SSH、传输预算和历史保留

**主要文件：** `backend/ssh.py`、`file_transfers.py`、`resource_history.py`、`resource_stats.py`。

**现有回归：** `tests/test_ssh_timeouts.py`、`test_ssh_proxy.py`、`test_file_transfers.py`、`test_resource_stats.py`、`test_history_time_ranges.py`。

- [ ] 先写现有默认值与自定义 SSH 配置优先级测试，并核对超时嵌套关系。
- [ ] 迁移连接/采集/保活参数；保留当前非零 SSH 配置覆盖规则、跳板预算、取消和错误分类，不顺便修订其语义。
- [ ] 迁移传输并发和任务保留策略；不把并发数与 `maxsize=1` 的状态队列合并。
- [ ] 迁移 7/30 天保留与记录上限；清理算法、批次和事务方式不变。
- [ ] 用可控时钟验证过期边界、清理范围、活跃任务不被回收，保留未知采样和时间戳。
- [ ] 执行相关回归后独立提交，不进行真实 SSH 联调。

**验收：** 默认连接预算及覆盖优先级不变；历史在同一时间边界清理；采样新鲜度和预约判断没有行为变更。

### 任务 4：助手缓存、通知及 UI 策略

**主要文件：** `backend/agent_context.py`、`notifications.py`；前端业务轮询、提示和刷新合并模块按清单逐一定位。

**现有回归：** `tests/test_agent_context.py`、`test_notifications.py`；前端 context-usage-meter、notifications、reservations 等相关测试。

- [ ] 先记录元数据成功/失败缓存、查询预算、默认容量的来源与优先级。
- [ ] 迁移策略默认值，保留手工容量 > 可用提供方元数据 > 默认容量的现有选择关系。压缩触发比例等行为规则首轮保留原位。
- [ ] 将通知有效期与 UI 提示时长分开；不改变已读、通知发送或失败重试语义。
- [ ] 分别迁移业务轮询；不把 500ms、1s、3s 等不同消费者机械收敛到同一个值。
- [ ] 用 fake timers 和假模型元数据验证到期行为，无真实 API 请求。
- [ ] 验证已保存偏好恢复、跨窗口同步和演示隔离；跑前端测试与构建后独立提交。

**验收：** 首次默认行为不变；已保存的用户偏好不被覆盖；缓存身份隔离、失效与模型切换保持正确。

### 任务 5：接入所有入口与交付检查

**修改文件：** `frontend/package.json`、`desktop/run.mjs`、`.github/workflows/desktop.yml`、实际测试/发布工作流、`CONTRIBUTING.md`；源码归档检查需结合 `scripts/source_archive.py` 实现与既有测试。

- [ ] 先补测试验证 `--check` 在自动生成前拒绝过期已提交产物。
- [ ] 将生成接到 dev/build/demo、桌面、CI，保留版本同步和签名要求。
- [ ] 使用临时 Git 仓库或临时快照验证源码归档读取同一提交，不携带工作区配置或用户数据。
- [ ] 执行完整验证并记录结果；只说明实际执行的平台和外部依赖范围。
- [ ] 更新维护文档，列明“改源配置 → 生成 → 测试/构建 → 提交生成产物”的步骤和回滚方法。
- [ ] 完成 diff 检查后提交本阶段；推送、发布和重启另按用户实际授权执行。

**最终验证命令（拟新增生成入口实施后）：**

```powershell
node scripts/generate-internal-defaults.mjs --check
node --test scripts/generate-internal-defaults.test.mjs scripts/sync-version.test.mjs desktop/release.test.mjs
.\.venv\Scripts\python.exe -m pytest tests -q
Push-Location frontend
npm.cmd test
npm.cmd run build
npm.cmd run build:demo
Pop-Location
node scripts/generate-internal-defaults.mjs --check
git diff --check
```

若实现阶段涉及 Rust 源码，再执行 `desktop/src-tauri` 中的 Cargo 检查/测试。本方案首轮不改 Rust 源码，不能把前端或 Python 测试通过表述为 Windows/macOS 安装包实机验证。

## 7. 回滚与完成定义

- 每阶段回滚该阶段代码和生成文件，保留其他已验证阶段。无数据库迁移、无用户配置转换。
- 不手改生成文件作为长期修复。紧急修复仍改 JSON、生成并测试，或者完整回退对应提交。
- 修改单个已迁移参数后，所有实际消费者从同一来源取得值；配置无效或产物过期能够在交付前被拒绝。
- 普通启动与远端执行均不新增外部依赖；权限、机器范围、取消、共享偏好及演示隔离保持原行为。
- 单位、协议值和局部算法保留在代码中是预期结果，不把“搜索不到数字字面量”作为验收条件。
- 数据新鲜度、预约判断、更新器恢复和跨平台启动预算留作独立后续任务；需要改变行为时另写设计与边界测试。

本轮交付仅为方案文档；上述配置、生成器与迁移均尚未实施。
