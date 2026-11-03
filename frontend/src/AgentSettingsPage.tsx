import {getLocale} from './i18n';
import {t} from './i18n';
import {ui} from './assistantLocale';
import {AgentProfilePicker} from './AgentProfilePicker';
import React,{useEffect,useState} from 'react';
import {Bot,Check,ChevronDown,LoaderCircle,Plug,ShieldCheck,Trash2} from 'lucide-react';
import {agentDirty,agentPayload,agentRequest,defaultAgentConfig,protocolNames,type ContextCapacity,type AgentConfig,type AgentTest,type AgentView} from './agentSettings';
import './settings.css';
import './agentSettings.css';

export function AgentSettingsPage(){
  const [form,setForm]=useState<AgentConfig>(defaultAgentConfig);
  const [saved,setSaved]=useState<AgentView|null>(null),[key,setKey]=useState(''),[remember,setRemember]=useState(true);
  const [pending,setPending]=useState('load'),[error,setError]=useState(''),[message,setMessage]=useState('');
  const [capacity,setCapacity]=useState<ContextCapacity|null>(null);
  const [models,setModels]=useState<string[]>([]),[result,setResult]=useState<AgentTest|null>(null);
  const apply=(value:AgentView)=>{
    setSaved(value);setKey('');setModels([]);setCapacity(null);
    setForm({profile_id:value.active_id,base_url:value.base_url,protocol:value.protocol,model:value.model,timeout_seconds:value.timeout_seconds,context_window:value.context_window||null});
    setRemember(value.can_remember&&(value.api_key_saved||!value.has_api_key));
    setResult(value.last_test);
  };
  useEffect(()=>{
    let alive=true;
    agentRequest<AgentView>().then(async value=>{if(alive){apply(value);if(value.model){const context=await agentRequest<ContextCapacity>('/context','POST');if(alive)setCapacity(context)}}}).catch(e=>{if(alive)setError(e.message)})
      .finally(()=>{if(alive)setPending('')});
    return()=>{alive=false};
  },[]);
  const dirty=agentDirty(form,saved,key,remember);
  useEffect(()=>{
    let alive=true;
    const refresh=()=>{void agentRequest<AgentView>().then(value=>{
      if(!alive||value.active_id===saved?.active_id)return;
      if(dirty){setError(ui("接口已在其他窗口切换。请重新加载设置后再编辑。"));return}
      apply(value);setError('');
    }).catch(e=>{if(alive)setError(e.message)})};
    window.addEventListener('infra-workbench:agent-settings-changed',refresh);window.addEventListener('focus',refresh);
    return()=>{alive=false;window.removeEventListener('infra-workbench:agent-settings-changed',refresh);window.removeEventListener('focus',refresh)};
  },[dirty,saved?.active_id]);
  const change=<K extends keyof AgentConfig>(name:K,value:AgentConfig[K])=>{
    setForm(old=>({...old,...(name==='model'||name==='base_url'?{context_window:null}:{}),[name]:value}));setMessage('');setError('');setResult(null);
    if(name==='base_url')setModels([]);
    if(name==='base_url'||name==='model'||name==='context_window')setCapacity(null);
  };
  const act=async(name:string,action:()=>Promise<void>)=>{
    setPending(name);setError('');setMessage('');
    try{await action()}catch(e){setError(e instanceof Error?e.message:ui("操作失败，请重试"))}
    finally{setPending('')}
  };
  const save=(event:React.FormEvent)=>{
    event.preventDefault();
    void act('save',async()=>{
      const value=await agentRequest<AgentView>('','PUT',agentPayload(form,key,remember));
      apply(value);setKey('');setMessage(ui("Agent 设置已保存。填写模型名称后，可以测试连接。"));
      window.dispatchEvent(new Event('infra-workbench:agent-settings-changed'));
      if(value.model)setCapacity(await agentRequest<ContextCapacity>('/context','POST'));
    });
  };
  const fetchModels=()=>act('models',async()=>{
    const value=await agentRequest<{models:string[];truncated:boolean}>('/models','POST',agentPayload(form,key,remember));
    setModels(value.models);
    setMessage(value.models.length?t(`已获取 ${value.models.length} 个模型，请在下方列表中选择。${value.truncated?ui("当前仅显示部分模型，仍可手动填写其他模型 ID。"):''}`,`Fetched ${value.models.length} models. Choose one below. ${value.truncated?ui("当前仅显示部分模型，仍可手动填写其他模型 ID。"):''}`):ui("接口没有提供可选模型，请手动填写模型名称。"));
  });
  const test=()=>act('test',async()=>{
    setResult(null);
    try{setResult(await agentRequest<AgentTest>('/test?profile_id='+encodeURIComponent(saved!.active_id),'POST'))}
    catch(e){const view=await agentRequest<AgentView>();if(view.active_id===saved?.active_id){setSaved(view);setResult(view.last_test)}throw e}
  });

  return <section className="settings-page agent-settings" aria-label={ui("Agent 模型接口")}>
    <div className="settings-section-title"><Bot size={20}/><div><h2>{ui("Agent 模型接口")}</h2><p>{ui("连接你选择的模型服务，供工作台内置的 AI 功能使用。")}</p></div><span className="agent-protocol-badge">{ui("OpenAI 兼容")}</span></div>
    <AgentProfilePicker manage disabled={!!pending||dirty} onChange={value=>{apply(value);setMessage(ui("已切换接口配置。"));setError('')}}/>
    <div className="settings-layout">
      <form className="settings-card" onSubmit={save}>
        <div className="agent-form-heading"><Plug size={18}/><div><h3>{ui("连接设置")}</h3><p>{ui("支持 OpenAI 官方接口、兼容网关和本地模型服务。")}</p></div></div>
        <fieldset className="agent-fields" disabled={!!pending||!saved}>
          <label className="form-label">{ui("接口 URL")}<input aria-label={ui("Agent 接口 URL")} type="url" required maxLength={2048} spellCheck={false} autoComplete="off" value={form.base_url} placeholder="https://api.example.com/v1" onChange={event=>change('base_url',event.target.value)}/></label>
          <p className="settings-help">{ui("填写服务商提供的 API 地址，通常以 /v1 结尾；也支持粘贴完整的 /responses 或 /chat/completions 地址。")}</p>
          <label className="form-label">{ui("接口协议")}<select aria-label={ui("Agent 接口协议")} value={form.protocol} onChange={event=>change('protocol',event.target.value as AgentConfig['protocol'])}>
            <option value="auto">{ui("自动兼容（优先 Responses）")}</option><option value="responses">OpenAI Responses</option><option value="chat_completions">OpenAI Chat Completions</option>
          </select></label>
          <p className="settings-help">{ui("自动模式先尝试 Responses；接口明确不支持时再尝试 Chat Completions。服务商指定协议时，也可以手动选择。")}</p>
          <label className="form-label">API key<input aria-label="Agent API key" type="password" autoComplete="new-password" maxLength={2048} value={key} placeholder={saved?.has_api_key?ui("已配置，留空保留原 key"):ui("填写 API key；无认证的本地服务可留空")} onChange={event=>{setKey(event.target.value);setResult(null);setMessage('');setError('');setModels([])}}/></label>
          <label className="settings-remember"><input type="checkbox" disabled={!saved?.can_remember} checked={remember&&!!saved?.can_remember} onChange={event=>{setRemember(event.target.checked);setResult(null)}}/>{ui("记住 API key，保存到系统安全存储")}</label>
          <p className="settings-help">{saved?.can_remember?ui("取消勾选后，key 仅在本次后台运行期间有效。"):ui("当前环境仅支持在本次后台运行期间保留 key。")}{ui("更换接口地址时需要重新填写 key。")}</p>
          <div className="agent-model-heading"><label className="form-label" htmlFor="agent-model-name">{ui("模型名称")}</label><button type="button" className="text-button" onClick={fetchModels} disabled={!form.base_url.trim()}>{pending==='models'?<LoaderCircle size={13} className="spin"/>:<ChevronDown size={13}/>}{ui("获取模型")}</button></div>
          <input className="agent-model-input" id="agent-model-name" aria-label={ui("Agent 模型名称")} list="agent-model-options" maxLength={200} autoComplete="off" value={form.model} placeholder={ui("填写服务商提供的模型 ID")} onChange={event=>change('model',event.target.value)}/>
          <datalist id="agent-model-options">{models.map(model=><option key={model} value={model}/>)}</datalist>
          {models.length>0&&<label className="form-label">{ui("已获取的模型")}<select aria-label={ui("选择已获取的模型")} value={models.includes(form.model)?form.model:''} onChange={event=>{if(event.target.value)change('model',event.target.value)}}><option value="">{ui("请选择模型")}</option>{models.map(model=><option key={model} value={model}>{model}</option>)}</select></label>}
          <p className="settings-help">{ui("可以直接输入模型 ID；不支持获取模型列表的服务仍可手动配置。")}</p>
          <label className="form-label">{ui("上下文容量（token，可选）")}<input aria-label={ui("模型上下文容量")} type="number" min={4096} max={20000000} step={1} placeholder={ui("自动从当前模型服务读取")} value={form.context_window||''} onChange={event=>change('context_window',event.target.value?Number(event.target.value):null)}/></label>
          <p className="settings-help">{ui("留空时自动读取服务商的模型容量；接口没有提供容量或部署限制更小时，可手动填写。手动值优先生效。")}</p>
          <div className="settings-help" role="status">{capacity?t(`${capacity.source==='provider'?ui("服务商返回"):capacity.source==='manual'?ui("手动设置"):ui("无法自动识别，暂用保守值")}：${capacity.tokens.toLocaleString()} token；约 ${capacity.trigger_tokens.toLocaleString()} token 时自动压缩。${capacity.source==='fallback'?ui("请核对服务商文档并填写实际容量。"):''}`,`${capacity.source==='provider'?ui("服务商返回"):capacity.source==='manual'?ui("手动设置"):ui("无法自动识别，暂用保守值")}: ${capacity.tokens.toLocaleString()} tokens; automatic compaction at about ${capacity.trigger_tokens.toLocaleString()} tokens. ${capacity.source==='fallback'?ui("请核对服务商文档并填写实际容量。"):''}`):dirty?ui("保存后读取当前模型容量。"):pending?ui("正在读取模型容量…"):ui("尚未读取模型容量。")}</div>
          <button type="button" className="text-button" disabled={!!pending||dirty||!saved?.model} onClick={()=>act('context',async()=>setCapacity(await agentRequest<ContextCapacity>('/context','POST')))}>{ui("重新读取模型容量")}</button>
          <label className="form-label agent-timeout">{ui("请求超时（秒）")}<input aria-label={ui("Agent 请求超时")} type="number" required min={5} max={120} value={form.timeout_seconds} onChange={event=>change('timeout_seconds',Number(event.target.value))}/></label>
        </fieldset>
        {saved?.credential_error&&<div className="settings-error" role="alert">{saved.credential_error}</div>}
        {error&&<div className="settings-error" role="alert">{error}<button type="button" className="text-button" disabled={!!pending} onClick={()=>act('load',async()=>{apply(await agentRequest<AgentView>());setError('')})}>{ui("重新加载设置（放弃未保存修改）")}</button></div>}
        {message&&<div className="settings-success" role="status"><Check size={15}/>{message}</div>}
        <div className="settings-save"><button className="primary" disabled={!!pending||!saved}>{pending==='save'?ui("正在保存…"):ui("保存 Agent 设置")}</button><button type="button" className="secondary" disabled={!!pending||!saved||dirty||!saved.model} onClick={test}>{pending==='test'?<LoaderCircle size={15} className="spin"/>:<Plug size={15}/ >}{pending==='test'?ui("正在测试…"):ui("测试连接")}</button>
          {!saved&&pending!=='load'&&<button type="button" className="secondary" onClick={()=>act('load',async()=>apply(await agentRequest<AgentView>()))}>{ui("重新加载")}</button>}
        </div>
        <p className="settings-help">{dirty?ui("填写或修改后请先保存，再测试连接。"):ui("测试会向当前服务发送一条简短消息，可能产生少量 API 费用。不会发送服务器、进程或终端内容。")}</p>
      </form>
      <aside className="settings-aside">
        <div className="settings-card"><h3><ShieldCheck size={17}/>{ui("API key 保存在本机")}</h3><p>{ui("key 不写入数据库、浏览器存储或项目文件，读取设置时也不会返回。")}</p><div className="settings-credential">{saved?.api_key_saved?ui("已保存到系统安全存储"):saved?.has_api_key?ui("仅本次后台运行中可用"):ui("尚未配置 API key")}</div><button className="secondary wide" disabled={!!pending||!saved?.has_api_key} onClick={()=>act('forget',async()=>{apply(await agentRequest<AgentView>('/api-key?profile_id='+encodeURIComponent(saved!.active_id),'DELETE'));setKey('');setModels([]);setMessage(ui("API key 已删除。"));window.dispatchEvent(new Event('infra-workbench:agent-settings-changed'))})}><Trash2 size={14}/>{ui("删除 API key")}</button></div>
        <div className="settings-card"><h3>{ui("连接测试")}</h3>{result?<div className="agent-test-result" role="status"><strong className={result.ok?'agent-test-ok':''}>{result.ok?ui("已收到模型回复"):ui("连接测试失败")}</strong>{result.protocol&&<span>{protocolNames[result.protocol]} · {result.model}</span>}{result.elapsed_ms!==undefined&&<span>{ui("耗时 ")}{(result.elapsed_ms/1000).toFixed(2)} {ui(" 秒")}</span>}{result.preview&&<pre>{result.preview}</pre>}<small>{new Date(result.updated*1000).toLocaleString(getLocale()==='en'?'en-US':'zh-CN')}</small></div>:<p>{pending==='test'?ui("正在等待模型返回文本…"):ui("保存设置后点击「测试连接」，检查当前协议、模型和 key 是否可用。")}</p>}</div>
        <div className="settings-card"><h3>{ui("与外部 Agent 的区别")}</h3><p>{ui("这里配置工作台调用的模型 API。Codex、Claude Code 等外部 Agent 连接工作台时，使用下方的 MCP 设置。")}</p><p>{ui("「AI 助手」使用这里的模型理解请求，并按需读取技能、调用工作台工具。")}</p></div>
      </aside>
    </div>
  </section>;
}
