# 采集更新与长回复

## 页面更新

页面通过 `GET /api/state/changes?instance=…&revision=…` 等待轻量变更游标。每次采集结束都会更新游标，成功和失败都会通知。相同游标最多等待 20 秒；后台实例变化时立即返回。返回值不包含主机信息。

页面合并短时间内的通知，再读取原有 `/api/state`。已有读取尚未完成时，会在其完成后补读一次，避免错过采集结果。原有定时轮询继续处理数据过期、其他状态变化及旧后台兼容。演示模式不启动变更请求。此功能没有提高远端采集频率，也没有改变预约所依赖的采样规则。

## 局部采集

快照的 `sections` 分别记录 `system`、`ports`、`devices` 的状态和采样时间。HTTP 与助手资源查询共用分项新鲜度计算。设备命令或解析失败时，保留本轮成功采到的系统、端口信息；旧设备数据及其时间仍保留，整机设备采样仍标为失败，不能据此判为空闲或满足预约。

SSH 失败时不会重新标记旧系统数据的采样时间。主页面的 CPU/内存使用系统分项的新鲜度，并在提示中显示系统采样时间。此变更不宣称 CPU-only 主机已完整接入所有设备管理流程。

## AI 长回复

新版页面在原 SSE 请求中添加 `X-IWB-Stream: delta-v1`。首次连接及重连返回完整快照；运行中只传当前回复变化的字段，文字增长时只传后缀。文本脱敏或修订导致前缀变化时发送替换文本。工具状态变化仍及时传递。最终事件返回完整当前回复；未声明增量协议的客户端继续接收原有事件。

增量事件带基准更新时间和回复 ID。客户端遇到缺失的更新时重新连接并读取完整快照。断开订阅不停止模型或远端任务。

流式 Markdown 每 100ms 合并一次文本更新，期间保留基本 Markdown、表格和代码文本，完成后再进行公式、代码高亮和图表渲染。已完成回复复用渲染结果。此优化针对持续输出时的传输和渲染工作量，不保证模型首字响应时间变短。

## 验证入口

使用临时数据和合成响应，不需要真实 SSH 或模型接口：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_live_collection.py tests/test_chat_stream.py tests/test_api.py -q
Push-Location frontend
node --test tests/stateChanges.test.mjs tests/agentChatStreaming.test.mjs tests/latestUpdate.test.mjs tests/chatMarkdown.test.mjs
npm.cmd test
npm.cmd run build
Pop-Location
```

运行中的后台需要正常退出后重新启动才能加载后端变更；不要为了验证而中断正在使用的终端或任务。
