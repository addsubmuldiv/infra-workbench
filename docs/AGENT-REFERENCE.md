# 模型接口开发参考

本页面向开发者，普通用户先看 [模型配置](AGENT.md)。供应商验证记录有日期，不代表当前接口状态或所有账号可用。

## 开发接口

- `GET /api/settings/agent`：配置和安全存储状态，不包含 key。
- `PUT /api/settings/agent`：保存配置和可选 key；不调用外部模型。
- `DELETE /api/settings/agent/api-key`：删除持久和内存中的 key。
- `POST /api/settings/agent/models`：可传当前表单，也可省略以使用保存的配置；不修改保存的配置。
- `POST /api/settings/agent/test`：测试已保存的配置。
- `GET/POST /api/assistant/chats`：列出或新建会话。
- `GET/DELETE /api/assistant/chats/{id}`：读取或删除本机会话及工具记录。
- `POST /api/assistant/chats/{id}/messages`：开始一轮处理，随后读取会话获取进度。
- `POST /api/assistant/chats/{id}/cancel`：取消本轮后续处理。

修改和外部请求操作沿用本机页面的 `X-IWB` 与 Origin 校验，响应设置 `Cache-Control: no-store`。`backend/agent_api.py` 的文本适配器供后续内置功能复用；工具目录以实时 MCP tools/list 为准。

协议参考：[OpenAI Responses](https://developers.openai.com/api/reference/resources/responses/methods/create)。

统一 MCP 架构、能力目录和验证见 [UNIFIED-MCP.md](UNIFIED-MCP.md)。取消不会撤销已完成的写入，结果未知时先查询状态，避免重复预约。

上下文容量优先使用模型设置中的手动值；留空时读取当前接口的模型列表或指定模型元数据，按精确模型 ID 匹配。识别成功缓存一小时，切换接口、模型或密钥后重新识别。框架按容量的 85% 触发摘要。接口没有提供容量时，设置页明确显示“无法自动识别”，暂按 32,000 token 保守处理，可手动填写实际部署容量；不会根据模型名称猜测容量。

## DeepSeek Responses

DeepSeek profile: `https://api.deepseek.com`, protocol `responses`, model `deepseek-flash` (or `deepseek-v4-pro`), timeout 120 seconds. Each API profile keeps its own credential.

DeepSeek Responses is stateless. The workbench resends history and paired function calls/results; it does not rely on `previous_response_id`. The adapter preserves returned plain-text reasoning across tool follow-ups, including framework checkpoints. For the official DeepSeek endpoint, Responses uses `reasoning.effort=high` and a 16,384-token per-call output budget (including reasoning), rather than the generic 2,400-token budget. This is a workbench limit, not the provider maximum.

Context capacity remains metadata-driven: current `/models` returns `context_window=1048576` for both models, separately from `max_output_tokens=393216`. Manual overrides take priority. At 85%, the compression trigger is 891,289 tokens. Unknown models without capacity metadata retain the conservative fallback.

Sources checked 2026-11-01: https://api-docs.deepseek.com/zh-cn/guides/responses_api/ and https://api-docs.deepseek.com/zh-cn/quick_start/pricing/ . Live Responses streaming/function-call follow-up and `/models` capacity were verified with the configured DeepSeek credential.
