## Context

AI 助手面板底部的模型按钮（如 "glm-5.3-flash ▾"）目前点击后跳转到设置页才能换模型。目标：点击该按钮直接在助手内弹出一个模型列表（数据来自当前接口配置的 API，即设置页「获取模型」同款数据源），点选即切换，不离开助手；设置页入口保留在弹层里。

关键现状（已探明）：
- 按钮：`frontend/src/AssistantChat.tsx:99`（`.chat-model`，onClick=openSettings）。
- 模型列表后端：`POST /api/settings/agent/models`（`backend/agent_api.py` `AgentAPIService.models()`，body 为空时用已保存配置+key）。
- 切模型不能直接复用 `PUT /api/settings/agent`（要求传全部字段+api_key/remember，有误清 key 的风险）→ 后端加一个只改 model 的轻量端点。
- 凭据 identity 只含 base_url（agent_api.py:80），切模型不影响 key；上下文容量缓存以 (base_url, model, key) 为键，自动失效重读。
- 刷新机制已有：`infra-workbench:agent-settings-changed` 事件会让 InfraAssistantPage 的 /status、顶部 AgentProfilePicker 自动刷新。

## 改动

### 后端 `backend/agent_api.py`
1. 新增请求模型 `ModelSwitch(BaseModel)`：`{profile_id?: str, model: str}`，model 复用 `AgentAPISettings.valid_model` 校验规则（strip、去控制字符，≤200）。
2. `AgentAPIService` 新增 `set_model(body)`：校验 profile_id 与当前激活一致（复用 `check_profile`）；只更新激活 profile 的 `config['model']` 并清空 `context_window`（与设置页改模型时清容量的行为一致，见 AgentSettingsPage.tsx:38）；`persist(config=...)`；重置 `last_test`；返回 `view()`。
3. 注册路由 `PUT /api/settings/agent/model`，ValueError → 400（与现有路由写法一致）。该路由带 `X-IWB` 本地页头校验，自动继承。

### 前端
1. 新组件 `frontend/src/ChatModelPicker.tsx`：
   - `<details className="chat-model-picker">` 弹层（沿用 `chat-more` 的 details 弹层模式，assistantWindow.css:42），向上展开（composer 在面板底部）。
   - 首次打开时并行请求：`GET /api/settings/agent`（拿 active_id 与当前模型）和 `POST /api/settings/agent/models`（空 body → 用已保存配置/key）。加载中显示 spinner；失败在弹层内显示错误 + 「打开模型设置」按钮（openSettings 兜底，保持原入口）。
   - 弹层内容：过滤输入框（列表最长 500 条）+ 滚动模型列表，当前模型打勾（Check 图标）；底部固定「打开模型设置」入口。
   - 点选模型 → `PUT /api/settings/agent/model` `{model, profile_id: active_id}`；成功后 dispatch `infra-workbench:agent-settings-changed`（状态、上下文用量、顶部配置选择器自动刷新），并用返回 view 立即更新按钮标签，然后收起弹层。切换期间显示 spinner；profile 已被切换等错误显示在弹层内。
2. `AssistantChat.tsx:99`：把模型按钮替换为 `<ChatModelPicker model={model} openSettings={openSettings}/>`。
3. 样式加在 `frontend/src/agentChat.css`（AssistantChat 已 import）：弹层向上定位（bottom:100%）、列表 max-height 滚动、条目 hover/check 样式，配色沿用现有 `--line/--panel/--hover/--muted` 变量；兼容 compact 模式。

### 不改动
- `/api/assistant/status`、ContextUsageMeter、AgentProfilePicker 均走现有事件刷新，无需修改。

## 验证
1. 后端：`python -m pytest tests/test_agent_api.py tests/test_agent_profiles.py -q`（在 tests/ 补一个 set_model 路由用例：切模型成功并清空 context_window、profile 不匹配时 400、仍要求本地页头）。
2. 前端：`cd frontend && npm run build`（含 tsc --noEmit）和 `npm test`。
3. 端到端：启动应用，在 AI 助手底部点模型按钮 → 出现从 API 拉取的列表 → 选择另一模型 → 按钮标签与顶部「模型 / 接口」同步更新；再发一条消息确认使用新模型。