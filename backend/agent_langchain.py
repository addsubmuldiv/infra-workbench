"""LangChain model adapter; the existing provider remains the wire transport."""
import json
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import PrivateAttr
from .chat_tools import scrub


def text_content(content):
    if isinstance(content, str):
        return content
    return '\n'.join(block.get('text', '') for block in content if isinstance(block, dict) and block.get('type') == 'text')


def wire_messages(messages):
    """Convert framework messages without leaking framework metadata to providers."""
    result = []
    for message in messages:
        if isinstance(message, SystemMessage):
            continue
        role = {'human': 'user', 'ai': 'assistant', 'tool': 'tool'}.get(message.type)
        if role is None:
            raise ValueError('模型上下文包含不支持的消息类型')
        item = dict(role=role, content=text_content(message.content))
        if role == 'tool':
            item['tool_call_id'] = message.tool_call_id
        if role == 'assistant' and isinstance(message.additional_kwargs.get('reasoning_content'),str):
            item['reasoning_content']=message.additional_kwargs['reasoning_content']
        if role == 'assistant' and message.tool_calls:
            item['tool_calls'] = [dict(id=c['id'], type='function', function=dict(
                name=c['name'], arguments=json.dumps(c['args'], ensure_ascii=False))) for c in message.tool_calls]
        result.append(item)
    return result


class WorkbenchChatModel(BaseChatModel):
    """Async-only adapter. Secrets and service objects are never model fields."""
    model_name: str = 'infra_workbench:configured'
    _provider: Any = PrivateAttr()
    _tools: Any = PrivateAttr(default=None)
    _on_start: Any = PrivateAttr(default=None)
    _on_text: Any = PrivateAttr(default=None)
    _sanitize: Any = PrivateAttr(default=None)
    _on_context: Any = PrivateAttr(default=None)

    def __init__(self, provider, *, on_start=None, on_text=None, sanitize=None, context_window=32000, on_context=None):
        super().__init__(profile={'max_input_tokens': context_window})
        self._provider = provider
        self._on_context = on_context
        self._on_start, self._on_text = on_start, on_text
        if sanitize is not None:
            self._sanitize = sanitize

    @property
    def _llm_type(self):
        return 'infra-workbench'

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        bound = self.model_copy()
        bound._tools = [convert_to_openai_tool(tool)['function'] for tool in tools]
        return bound

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError('Workbench model requires async invocation')

    def _clean_arguments(self, value):
        if isinstance(value, str):
            return self._sanitize(value) if self._sanitize else value
        if isinstance(value, list):
            return [self._clean_arguments(item) for item in value]
        if isinstance(value, dict):
            cleaned = {self._clean_arguments(key): self._clean_arguments(item) for key, item in value.items()}
            return json.loads(scrub(cleaned))
        return value

    async def _agenerate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs):
        display = self._tools is not None
        if display and self._on_start:
            self._on_start()
        if display and self._on_context:
            self._on_context(count_tokens_approximately(messages, tools=self._tools), 'request')
        instructions = '\n\n'.join(text_content(m.content) for m in messages if isinstance(m, SystemMessage))
        options = {}
        if display and self._on_text and getattr(self._provider, 'supports_streaming', False):
            options['on_text'] = self._on_text
        response = await self._provider.turn(instructions, wire_messages(messages), self._tools or [], **options)
        raw = response['message']
        calls, invalid = [], []
        for call in raw.get('tool_calls', []):
            name = self._clean_arguments(call['function']['name'])
            try:
                args = json.loads(call['function']['arguments'])
                if not isinstance(args, dict):
                    raise ValueError()
                calls.append(dict(name=name, args=self._clean_arguments(args),
                                  id=self._clean_arguments(call['id']), type='tool_call'))
            except (ValueError, TypeError):
                invalid.append(dict(name=name, args=call['function']['arguments'], id=call['id'],
                                    error='工具参数不是完整 JSON 对象', type='invalid_tool_call'))
        # Do not allow malformed arguments to become executable calls.
        if invalid:
            raise ValueError('模型工具参数不完整或无效，本轮未执行')
        content = self._sanitize(raw.get('content', '')) if self._sanitize else raw.get('content', '')
        if display and self._on_text:
            self._on_text(content, final=True)
        reply = AIMessage(content=content, tool_calls=calls, additional_kwargs=(
            {'reasoning_content':self._clean_arguments(raw['reasoning_content'])} if raw.get('reasoning_content') else {}))
        if display and self._on_context:
            self._on_context(count_tokens_approximately([*messages, reply], tools=self._tools), 'response')
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def get_num_tokens(self, text):
        # Conservative local estimate; never downloads a tokenizer at runtime.
        return max(1, sum(1 if ord(c) > 127 else .34 for c in text).__ceil__())
