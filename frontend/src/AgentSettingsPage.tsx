import React,{useEffect,useState} from 'react';
import {Bot,Check,ChevronDown,LoaderCircle,Plug,ShieldCheck,Trash2} from 'lucide-react';
import {agentDirty,agentPayload,agentRequest,defaultAgentConfig,protocolNames,type AgentConfig,type AgentTest,type AgentView} from './agentSettings';
import './settings.css';
import './agentSettings.css';

export function AgentSettingsPage(){
  const [form,setForm]=useState<AgentConfig>(defaultAgentConfig);
  const [saved,setSaved]=useState<AgentView|null>(null),[key,setKey]=useState(''),[remember,setRemember]=useState(true);
  const [pending,setPending]=useState('load'),[error,setError]=useState(''),[message,setMessage]=useState('');
  const [models,setModels]=useState<string[]>([]),[result,setResult]=useState<AgentTest|null>(null);
  const apply=(value:AgentView)=>{
    setSaved(value);
    setForm({base_url:value.base_url,protocol:value.protocol,model:value.model,timeout_seconds:value.timeout_seconds});
    setRemember(value.can_remember&&(value.api_key_saved||!value.has_api_key));
    setResult(value.last_test);
  };
  useEffect(()=>{
    let alive=true;
    agentRequest<AgentView>().then(value=>{if(alive)apply(value)}).catch(e=>{if(alive)setError(e.message)})
      .finally(()=>{if(alive)setPending('')});
    return()=>{alive=false};
  },[]);
  const dirty=agentDirty(form,saved,key,remember);
  const change=<K extends keyof AgentConfig>(name:K,value:AgentConfig[K])=>{
    setForm(old=>({...old,[name]:value}));setMessage('');setError('');setResult(null);
    if(name==='base_url')setModels([]);
  };
  const act=async(name:string,action:()=>Promise<void>)=>{
    setPending(name);setError('');setMessage('');
    try{await action()}catch(e){setError(e instanceof Error?e.message:'操作失败，请重试')}
    finally{setPending('')}
  };
  const save=(event:React.FormEvent)=>{
    event.preventDefault();
    void act('save',async()=>{
      const value=await agentRequest<AgentView>('','PUT',agentPayload(form,key,remember));
      apply(value);setKey('');setMessage('Agent 设置已保存。填写模型名称后，可以测试连接。');
      window.dispatchEvent(new Event('infra-workbench:agent-settings-changed'));
    });
  };
  const fetchModels=()=>act('models',async()=>{
    const value=await agentRequest<{models:string[];truncated:boolean}>('/models','POST',agentPayload(form,key,remember));
    setModels(value.models);
    setMessage(value.models.length?`已获取 ${value.models.length} 个模型，可在模型名称输入框中选择。${value.truncated?'列表仅显示前 500 个。':''}`:'接口没有提供可选模型，请手动填写模型名称。');
  });
  const test=()=>act('test',async()=>{
    setResult(null);
    try{setResult(await agentRequest<AgentTest>('/test','POST'))}
    catch(e){const view=await agentRequest<AgentView>();setSaved(view);setResult(view.last_test);throw e}
  });

  return <section className="settings-page agent-settings" aria-label="Agent 模型接口">
    <div className="settings-section-title"><Bot size={20}/><div><h2>Agent 模型接口</h2><p>连接你选择的模型服务，供工作台内置的 AI 功能使用。</p></div><span className="agent-protocol-badge">OpenAI 兼容</span></div>
    <div className="settings-layout">
      <form className="settings-card" onSubmit={save}>
        <div className="agent-form-heading"><Plug size={18}/><div><h3>连接设置</h3><p>支持 OpenAI 官方接口、兼容网关和本地模型服务。</p></div></div>
        <fieldset className="agent-fields" disabled={!!pending||!saved}>
          <label className="form-label">接口 URL<input aria-label="Agent 接口 URL" type="url" required maxLength={2048} spellCheck={false} autoComplete="off" value={form.base_url} placeholder="https://api.example.com/v1" onChange={event=>change('base_url',event.target.value)}/></label>
          <p className="settings-help">填写服务商提供的 API 地址，通常以 /v1 结尾；也支持粘贴完整的 /responses 或 /chat/completions 地址。</p>
          <label className="form-label">接口协议<select aria-label="Agent 接口协议" value={form.protocol} onChange={event=>change('protocol',event.target.value as AgentConfig['protocol'])}>
            <option value="auto">自动兼容（优先 Responses）</option><option value="responses">OpenAI Responses</option><option value="chat_completions">OpenAI Chat Completions</option>
          </select></label>
          <p className="settings-help">自动模式先尝试 Responses；接口明确不支持时再尝试 Chat Completions。服务商指定协议时，也可以手动选择。</p>
          <label className="form-label">API key<input aria-label="Agent API key" type="password" autoComplete="new-password" maxLength={2048} value={key} placeholder={saved?.has_api_key?'已配置，留空保留原 key':'填写 API key；无认证的本地服务可留空'} onChange={event=>{setKey(event.target.value);setResult(null);setMessage('');setError('');setModels([])}}/></label>
          <label className="settings-remember"><input type="checkbox" disabled={!saved?.can_remember} checked={remember&&!!saved?.can_remember} onChange={event=>{setRemember(event.target.checked);setResult(null)}}/>记住 API key，保存到系统安全存储</label>
          <p className="settings-help">{saved?.can_remember?'取消勾选后，key 仅在本次后台运行期间有效。':'当前环境仅支持在本次后台运行期间保留 key。'}更换接口地址时需要重新填写 key。</p>
          <div className="agent-model-heading"><label className="form-label" htmlFor="agent-model-name">模型名称</label><button type="button" className="text-button" onClick={fetchModels} disabled={!form.base_url.trim()}>{pending==='models'?<LoaderCircle size={13} className="spin"/>:<ChevronDown size={13}/>}获取模型</button></div>
          <input className="agent-model-input" id="agent-model-name" aria-label="Agent 模型名称" list="agent-model-options" maxLength={200} autoComplete="off" value={form.model} placeholder="填写服务商提供的模型 ID" onChange={event=>change('model',event.target.value)}/>
          <datalist id="agent-model-options">{models.map(model=><option key={model} value={model}/>)}</datalist>
          <p className="settings-help">可以直接输入模型 ID；不支持获取模型列表的服务仍可手动配置。</p>
          <label className="form-label agent-timeout">请求超时（秒）<input aria-label="Agent 请求超时" type="number" required min={5} max={120} value={form.timeout_seconds} onChange={event=>change('timeout_seconds',Number(event.target.value))}/></label>
        </fieldset>
        {saved?.credential_error&&<div className="settings-error" role="alert">{saved.credential_error}</div>}
        {error&&<div className="settings-error" role="alert">{error}</div>}
        {message&&<div className="settings-success" role="status"><Check size={15}/>{message}</div>}
        <div className="settings-save"><button className="primary" disabled={!!pending||!saved}>{pending==='save'?'正在保存…':'保存 Agent 设置'}</button><button type="button" className="secondary" disabled={!!pending||!saved||dirty||!saved.model} onClick={test}>{pending==='test'?<LoaderCircle size={15} className="spin"/>:<Plug size={15}/ >}{pending==='test'?'正在测试…':'测试连接'}</button>
          {!saved&&pending!=='load'&&<button type="button" className="secondary" onClick={()=>act('load',async()=>apply(await agentRequest<AgentView>()))}>重新加载</button>}
        </div>
        <p className="settings-help">{dirty?'填写或修改后请先保存，再测试连接。':'测试会向当前服务发送一条简短消息，可能产生少量 API 费用。不会发送服务器、进程或终端内容。'}</p>
      </form>
      <aside className="settings-aside">
        <div className="settings-card"><h3><ShieldCheck size={17}/>API key 保存在本机</h3><p>key 不写入数据库、浏览器存储或项目文件，读取设置时也不会返回。</p><div className="settings-credential">{saved?.api_key_saved?'已保存到系统安全存储':saved?.has_api_key?'仅本次后台运行中可用':'尚未配置 API key'}</div><button className="secondary wide" disabled={!!pending||!saved?.has_api_key} onClick={()=>act('forget',async()=>{apply(await agentRequest<AgentView>('/api-key','DELETE'));setKey('');setModels([]);setMessage('API key 已删除。');window.dispatchEvent(new Event('infra-workbench:agent-settings-changed'))})}><Trash2 size={14}/>删除 API key</button></div>
        <div className="settings-card"><h3>连接测试</h3>{result?<div className="agent-test-result" role="status"><strong className={result.ok?'agent-test-ok':''}>{result.ok?'已收到模型回复':'连接测试失败'}</strong>{result.protocol&&<span>{protocolNames[result.protocol]} · {result.model}</span>}{result.elapsed_ms!==undefined&&<span>耗时 {(result.elapsed_ms/1000).toFixed(2)} 秒</span>}{result.preview&&<pre>{result.preview}</pre>}<small>{new Date(result.updated*1000).toLocaleString('zh-CN')}</small></div>:<p>{pending==='test'?'正在等待模型返回文本…':'保存设置后点击「测试连接」，检查当前协议、模型和 key 是否可用。'}</p>}</div>
        <div className="settings-card"><h3>与外部 Agent 的区别</h3><p>这里配置工作台调用的模型 API。Codex、Claude Code 等外部 Agent 连接工作台时，使用下方的 MCP 设置。</p><p>左侧「AI 助手」使用这里的模型进行跨机器查找和资源变化归纳，模型只在你主动查询时调用。</p></div>
      </aside>
    </div>
  </section>;
}
