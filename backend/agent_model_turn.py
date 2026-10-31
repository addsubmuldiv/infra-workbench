"""Provider-neutral message history with native Responses / Chat tool calls."""
import json
from urllib.parse import urlsplit
from .agent_api import ProviderFailure


def response_input(messages):
    result=[]
    for message in messages:
        if message['role']=='tool':
            result.append(dict(type='function_call_output',call_id=message['tool_call_id'],output=message['content']))
        else:
            if message.get('content'):
                result.append(dict(role=message['role'],content=message['content']))
            for call in message.get('tool_calls',[]):
                result.append(dict(type='function_call',call_id=call['id'],name=call['function']['name'],arguments=call['function']['arguments']))
    return result


async def model_turn(service,instructions,messages,tools,*,on_text=None):
    config=dict(service.config)
    if not config.get('model'):
        raise ValueError('请先在设置中配置模型接口')
    key=service.key_for(config)
    from .agent_provider_stream import TextSink, request_stream
    sink=TextSink(on_text,key) if on_text is not None else None
    protocols=['responses','chat_completions'] if config['protocol']=='auto' else [config['protocol']]
    for index,protocol in enumerate(protocols):
        if protocol=='responses':
            payload=dict(model=config['model'],instructions=instructions,input=response_input(messages),store=False,stream=False,max_output_tokens=2400)
            if tools:payload.update(tools=[dict(type='function',**tool) for tool in tools],tool_choice='auto')
            path='/responses'
        else:
            payload=dict(model=config['model'],messages=[dict(role='system',content=instructions)]+messages,stream=False)
            if tools:payload.update(tools=[dict(type='function',function=tool) for tool in tools],tool_choice='auto')
            path='/chat/completions'
        if urlsplit(config['base_url']).hostname=='open.bigmodel.cn' and config['model'].startswith('glm-'):
            payload.update(reasoning=dict(effort='none')) if protocol=='responses' else payload.update(thinking=dict(type='disabled'))
        try:
            if sink is not None:
                payload['stream']=True
                data=await request_stream(config,key,path,payload,protocol,sink)
            else:
                data=await service.request(config,key,path,payload)
        except ProviderFailure as exc:
            if exc.unsupported and index+1<len(protocols):continue
            raise
        text=[];calls=[]
        if protocol=='responses':
            if data.get('status') not in (None,'completed'):
                raise ProviderFailure('模型响应被中断或未完成，本轮未能完成')
            for item in data.get('output',[]) if isinstance(data.get('output'),list) else []:
                if not isinstance(item,dict):continue
                if item.get('type')=='function_call':
                    calls.append(dict(id=item.get('call_id'),name=item.get('name'),arguments=item.get('arguments')))
                elif item.get('type')=='message':
                    for part in item.get('content',[]) if isinstance(item.get('content'),list) else []:
                        if isinstance(part,dict) and part.get('type')=='output_text' and isinstance(part.get('text'),str):text.append(part['text'])
        else:
            choices=data.get('choices')
            message=choices[0].get('message') if isinstance(choices,list) and choices and isinstance(choices[0],dict) else None
            if isinstance(message,dict):
                if isinstance(message.get('content'),str):text.append(message['content'])
                for call in message.get('tool_calls',[]) if isinstance(message.get('tool_calls'),list) else []:
                    function=call.get('function') if isinstance(call,dict) else None
                    if isinstance(function,dict):calls.append(dict(id=call.get('id'),name=function.get('name'),arguments=function.get('arguments')))
        if len(calls)>8 or len({c['id'] for c in calls if isinstance(c['id'],str)})!=len(calls):
            raise ProviderFailure('模型返回过多或重复的工具调用，本轮已停止')
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
        return dict(message=dict(role='assistant',content=content,**({'tool_calls':normalized} if normalized else {})),
                    model=config['model'],protocol=protocol)
