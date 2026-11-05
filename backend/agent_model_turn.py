"""Responses message history with native function calls and matching outputs."""
import json
import time
from urllib.parse import urlsplit
from .agent_api import ProviderFailure


def response_input(messages, *, reasoning=False):
    result=[]
    for message in messages:
        if message['role']=='tool':
            result.append(dict(type='function_call_output',call_id=message['tool_call_id'],output=message['content']))
        else:
            if reasoning and message.get('reasoning_content'):
                result.append(dict(type='reasoning',content=[dict(type='reasoning_text',text=message['reasoning_content'])]))
            if message.get('content'):
                result.append(dict(role=message['role'],content=message['content']))
            for call in message.get('tool_calls',[]):
                result.append(dict(type='function_call',call_id=call['id'],name=call['function']['name'],arguments=call['function']['arguments']))
    return result


async def model_turn(service,instructions,messages,tools,*,on_text=None):
    config=dict(service.config)
    if not config.get('model'):
        raise ValueError('请先在设置中配置模型接口')
    deepseek=urlsplit(config['base_url']).hostname=='api.deepseek.com'
    key=service.key_for(config)
    from .agent_provider_stream import TextSink, request_stream
    started=time.monotonic()
    first_text=None
    def emit(text):
        nonlocal first_text
        if text and first_text is None:first_text=round((time.monotonic()-started)*1000)
        on_text(text)
    sink=TextSink(emit,key) if on_text is not None else None
    protocol='responses'
    payload=dict(model=config['model'],instructions=instructions,input=response_input(messages,reasoning=deepseek),store=False,stream=False)
    # Preserve optional MCP fields instead of Responses strict normalization.
    # The shared MCP server still validates arguments and host scope.
    if tools:payload.update(tools=[dict(tool,type='function',strict=tool.get('strict',False)) for tool in tools],tool_choice='auto')
    if deepseek:payload.update(reasoning=dict(effort='high'))
    if urlsplit(config['base_url']).hostname=='open.bigmodel.cn' and config['model'].startswith('glm-'):
        payload.update(reasoning=dict(effort='none'))
    if sink is not None:
        payload['stream']=True
        data=await request_stream(config,key,'/responses',payload,protocol,sink,client=getattr(service,'_http_client',None))
    else:
        data=await service.request(config,key,'/responses',payload)
    text=[];calls=[];reasoning=[]
    if data.get('status') not in (None,'completed'):
        raise ProviderFailure('模型响应被中断或未完成，本轮未能完成')
    for item in data.get('output',[]) if isinstance(data.get('output'),list) else []:
        if not isinstance(item,dict):continue
        if deepseek and item.get('type')=='reasoning':
            reasoning.extend(p['text'] for p in item.get('content',[]) if isinstance(p,dict) and p.get('type')=='reasoning_text' and isinstance(p.get('text'),str))
        if item.get('type')=='function_call':
            calls.append(dict(id=item.get('call_id'),name=item.get('name'),arguments=item.get('arguments')))
        elif item.get('type')=='message':
            for part in item.get('content',[]) if isinstance(item.get('content'),list) else []:
                if isinstance(part,dict) and part.get('type')=='output_text' and isinstance(part.get('text'),str):text.append(part['text'])
    normalized=[]
    for call in calls:
        if not all(isinstance(call[field],str) and 0<len(call[field])<=limit for field,limit in (('id',200),('name',100),('arguments',12000))):
            raise ProviderFailure('模型工具调用格式无效，本轮未执行')
        if sink is not None:
            try:
                arguments=json.loads(call['arguments'])
                if not isinstance(arguments,dict):raise ValueError()
            except ValueError:
                raise ProviderFailure('模型工具调用参数不完整或无效，本轮未执行') from None
        normalized.append(dict(id=call['id'],type='function',function=dict(name=call['name'],arguments=call['arguments'])))
    # A fleet inspection can legitimately return many independent calls.
    # Reject ambiguous identities, rather than imposing a batch-size limit.
    if len({call['id'] for call in normalized}) != len(normalized):
        raise ProviderFailure('模型返回的工具调用 ID 重复，本轮未执行这些调用')
    content=''.join(text)
    if key:
        content=content.replace(key,'[已隐藏 API key]')
        for call in normalized:
            call['id']=call['id'].replace(key,'[已隐藏 API key]')
            for field in ('name','arguments'):
                call['function'][field]=call['function'][field].replace(key,'[已隐藏 API key]')
    if not content.strip() and not normalized:
        raise ProviderFailure('模型未返回文本或工具调用，请重试')
    if sink is not None:content=sink.emit(content,final=True)
    reasoning_text=''.join(reasoning)
    if key:reasoning_text=reasoning_text.replace(key,'[redacted]')
    return dict(message=dict(role='assistant',content=content,**({'reasoning_content':reasoning_text} if reasoning_text else {}),**({'tool_calls':normalized} if normalized else {})),
                model=config['model'],protocol=protocol,usage=provider_usage(data.get('usage')),
                metrics=dict(request_bytes=len(json.dumps(payload,ensure_ascii=False).encode('utf-8')),
                             first_text_ms=first_text))


def provider_usage(value):
    """Only numeric counters are retained, never arbitrary provider metadata."""
    if not isinstance(value,dict):return {}
    result={k:v for k,v in value.items() if k in ('input_tokens','output_tokens','total_tokens') and type(v) is int and v>=0}
    for group,key in (('input_tokens_details','cached_tokens'),('output_tokens_details','reasoning_tokens')):
        details=value.get(group)
        if isinstance(details,dict) and type(details.get(key)) is int and details[key]>=0:
            result[key]=details[key]
    return result
