"""Shared ACP v1 stdio transport for local assistant engines."""

import asyncio
import contextlib
import json
import os
import subprocess

MCP_NAME = 'infra_workbench'


class LocalACP:
    def __init__(self, process, bridge, on_text, *, label, describe_error, configure_session=None):
        self.label = label
        self.describe_error = describe_error
        self.configure_session = configure_session
        self.process = process
        self.bridge = bridge
        self.on_text = on_text
        self.session_id = None
        self.request_id = 0
        self.content = ''
        self.received = 0
        self.mcp_tools = {f'mcp_{MCP_NAME}_{name}' for name in bridge.service.catalog()}

    async def send(self, **message):
        self.process.stdin.write(
            (json.dumps({'jsonrpc': '2.0', **message}, ensure_ascii=False) + '\n').encode()
        )
        await self.process.stdin.drain()

    def permission_outcome(self, params):
        if self.session_id and params.get('sessionId') == self.session_id:
            call = params.get('toolCall', {})
            title = call.get('title', '')
            tool = call.get('name') or (title.removeprefix('Run ') if isinstance(title, str) else '')
            if isinstance(tool, str) and tool in self.mcp_tools:
                for option in params.get('options', []):
                    if option.get('kind') == 'allow_once':
                        return {'outcome': 'selected', 'optionId': option['optionId']}
        return {'outcome': 'cancelled'}

    async def handle_agent_request(self, message):
        request_id = message['id']
        if message.get('method') == 'session/request_permission':
            outcome = self.permission_outcome(message.get('params', {}))
            await self.send(id=request_id, result={'outcome': outcome})
        else:
            await self.send(id=request_id, error={'code': -32601, 'message': 'Method not supported'})

    def handle_update(self, params):
        if not self.session_id or params.get('sessionId') != self.session_id:
            return
        update = params.get('update', {})
        content = update.get('content', {})
        if update.get('sessionUpdate') == 'agent_message_chunk' and content.get('type') == 'text':
            text = content.get('text')
            if isinstance(text, str):
                self.content += text
                if len(self.content) > 200000:
                    raise ValueError(f'{self.label} 文本超出限制。')
                self.on_text(self.visible_text())

    def visible_text(self):
        from .agent_chat import visible_stream_text

        return visible_stream_text(self.content, self.bridge.token)

    async def request(self, method, params, *, timeout):
        self.request_id += 1
        request_id = self.request_id
        async with asyncio.timeout(timeout):
            await self.send(id=request_id, method=method, params=params)
            while line := await self.process.stdout.readline():
                self.received += len(line)
                if self.received > 8 * 1024 * 1024:
                    raise ValueError(f'{self.label} ACP 输出超出限制。')
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeError):
                    raise ValueError(f'{self.label} CLI 未返回有效 ACP 消息，请检查 CLI 版本。') from None
                if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
                    raise ValueError(f'{self.label} CLI 未返回有效 ACP 消息，请检查 CLI 版本。')
                if 'method' in message:
                    if 'id' in message:
                        await self.handle_agent_request(message)
                    elif message['method'] == 'session/update':
                        self.handle_update(message.get('params', {}))
                    continue
                if message.get('id') != request_id:
                    continue
                if 'error' in message:
                    error = message['error']
                    if isinstance(error, dict):
                        explanation = self.describe_error(error)
                        if explanation:
                            raise ValueError(explanation)
                    raise ValueError(f'{self.label} ACP 请求失败，请检查 CLI 版本、账号权限和网络。')
                result = message.get('result')
                if isinstance(result, dict):
                    return result
                raise ValueError(f'{self.label} CLI 返回了未知的 ACP 响应。')
        raise ValueError(f'{self.label} CLI 提前退出，请检查 CLI 版本及登录状态。')

    async def run(self, cwd, instructions, prompt):
        capabilities = await self.request('initialize', {
            'protocolVersion': 1, 'clientCapabilities': {},
            'clientInfo': {'name': 'infra-workbench', 'version': '1'},
        }, timeout=20)
        if (capabilities.get('protocolVersion') != 1 or not
                capabilities.get('agentCapabilities', {}).get('mcpCapabilities', {}).get('http')):
            raise ValueError(f'{self.label} CLI 需要支持 ACP v1 和 HTTP MCP，请更新 CLI。')
        session = await self.request('session/new', {
            'cwd': str(cwd),
            'mcpServers': [{
                'type': 'http', 'name': MCP_NAME, 'url': self.bridge.url,
                'headers': [{'name': 'Authorization', 'value': 'Bearer ' + self.bridge.token}],
            }],
        }, timeout=90)
        self.session_id = session.get('sessionId')
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError(f'{self.label} 未返回有效会话。')
        if self.configure_session is not None:
            await self.configure_session(self, session)
        result = await self.request('session/prompt', {
            'sessionId': self.session_id,
            'prompt': [{'type': 'text', 'text': instructions + '\n\n' + prompt}],
        }, timeout=7200)
        from .agent_chat import visible_stream_text

        text = visible_stream_text(self.content, self.bridge.token, final=True)
        if result.get('stopReason') not in ('end_turn', 'refusal') or not text.strip():
            raise ValueError(f'{self.label} 未完成本轮回复。')
        self.on_text(text, final=True)
        return text

    async def close(self):
        if self.process.returncode is not None:
            return
        self.process.stdin.close()
        # Keep draining so a full stdout pipe can't block the native worker's exit.
        async def drain():
            while await self.process.stdout.read(65536):
                pass

        reader = asyncio.create_task(drain())
        try:
            await asyncio.wait_for(self.process.wait(), 3)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                self.process.kill()
            await self.process.wait()
        finally:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)


async def run_local_acp(command, env, cwd, bridge, instructions, prompt, on_text, **options):
    process = await asyncio.create_subprocess_exec(
        *command, cwd=cwd, env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, limit=1024 * 1024,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )
    acp = LocalACP(process, bridge, on_text, **options)
    try:
        return await acp.run(cwd, instructions, prompt)
    except asyncio.CancelledError:
        if acp.session_id and process.returncode is None:
            with contextlib.suppress(OSError, TimeoutError):
                await asyncio.wait_for(acp.send(method='session/cancel', params={
                    'sessionId': acp.session_id,
                }), 1)
        raise
    finally:
        await acp.close()
