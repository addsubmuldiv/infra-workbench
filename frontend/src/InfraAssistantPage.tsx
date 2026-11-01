import {useWorkspaceValue} from './workspaceHooks';
import React,{useEffect,useRef,useState} from 'react';
import {ArrowUpRight,Clock,History,LoaderCircle,Search,Server,Sparkles,Terminal} from 'lucide-react';
import {assistantRequest,rowTitle,type AssistantStatus,type ChangeHistory,type ResourceSummary,type SearchResult} from './infraAssistant';
import './infraAssistant.css';
import {AssistantChat} from './AssistantChat';

const examples=['我的 vLLM 在哪台机器？','找 4 个空闲 NPU，每个至少 40 GiB','我开的 tmux 在哪里？'];
const stamp=(value:number|null|undefined)=>value?new Date(value*1000).toLocaleString('zh-CN'):'尚无记录';

export function InfraAssistant({locate,openTerminal,openSettings,selectedHostIds=[],compact=false}:{compact?:boolean;locate:(hostId:string,devices:string[])=>void;openTerminal:(hostId:string)=>void;openSettings:()=>void;selectedHostIds?:string[]}){
  const [tab,setTab]=useState<'chat'|'search'|'changes'>('chat'),[status,setStatus]=useState<AssistantStatus|null>(null);
  const [query,setQuery]=useWorkspaceValue('workspace:assistant-query',''),[refresh,setRefresh]=useWorkspaceValue('workspace:assistant-refresh',false),[search,setSearch]=useState<SearchResult|null>(null);
  const [hours,setHours]=useWorkspaceValue('workspace:assistant-hours',1),[history,setHistory]=useState<ChangeHistory|null>(null),[summary,setSummary]=useState<ResourceSummary|null>(null);
  const [pending,setPending]=useState(''),[error,setError]=useState(''),[historyError,setHistoryError]=useState('');
  const controller=useRef<AbortController|null>(null),[highlight,setHighlight]=useState<number[]>([]);
  useEffect(()=>{
    let request:AbortController;
    const refresh=()=>{
      request?.abort();const next=new AbortController();request=next;
      assistantRequest<AssistantStatus>('/status','GET',undefined,next.signal).then(value=>{if(!next.signal.aborted){setStatus(value);setError('')}}).catch(e=>{if(!next.signal.aborted)setError(e.message)});
    };
    refresh();window.addEventListener('infra-workbench:agent-settings-changed',refresh);
    return()=>{request.abort();controller.current?.abort();window.removeEventListener('infra-workbench:agent-settings-changed',refresh)};
  },[]);
  useEffect(()=>{
    const request=new AbortController();setHistory(null);setSummary(null);setHighlight([]);setHistoryError('');
    assistantRequest<ChangeHistory>('/changes?hours='+hours,'GET',undefined,request.signal).then(setHistory).catch(e=>{if(e.name!=='AbortError')setHistoryError(e.message)});
    return()=>request.abort();
  },[hours]);
  const act=async(name:string,task:(signal:AbortSignal)=>Promise<void>)=>{
    if(controller.current)return;
    const request=new AbortController();controller.current=request;setPending(name);setError('');
    try{await task(request.signal)}catch(e){if(e instanceof Error&&e.name!=='AbortError')setError(e.message)}
    finally{controller.current=null;setPending('')}
  };
  const submit=(event:React.FormEvent)=>{event.preventDefault();if(!query.trim())return;void act('search',async signal=>{
    const result=await assistantRequest<SearchResult>('/search','POST',{query:query.trim(),refresh},signal);setSearch(result);
  })};
  const summarize=()=>act('summary',async signal=>{
    const result=await assistantRequest<ResourceSummary>('/summary','POST',{hours},signal);setSummary(result);setHistory(result.history);setHighlight([]);
  });
  const reloadHistory=()=>act('history',async signal=>{setHistory(await assistantRequest<ChangeHistory>('/changes?hours='+hours,'GET',undefined,signal));setSummary(null);setHighlight([]);setHistoryError('')});

  return <section className={"infra-assistant"+(compact?" compact":"")} aria-label="AI 资源助手">
    {!compact&&<div className="assistant-intro"><span className="assistant-mark"><Sparkles size={23}/></span><div><h2>用 AI 操作工作台</h2><p>描述目标，查看执行过程和结果。</p></div></div>}
    {tab!=='chat'&&<div className="assistant-navigation"><button className="text-button" onClick={()=>setTab('chat')}><Sparkles size={13}/>返回对话</button><details className="assistant-utilities"><summary aria-label="更多助手功能">•••</summary><div><button onClick={()=>setTab('search')}><Search size={14}/>跨机器查找</button><button onClick={()=>setTab('changes')}><History size={14}/>资源变化摘要</button><button onClick={openSettings}><ArrowUpRight size={14}/>模型设置</button></div></details></div>}
    {error&&<div className="assistant-error" role="alert">{error}</div>}
    {status&&!status.configured&&<div className="assistant-note">请先在模型设置中配置接口和模型名称。采样记录不依赖模型，仍会持续积累。</div>}
    {status?.credential_error&&<div className="assistant-error">{status.credential_error}</div>}
    <div className="assistant-tab-content assistant-chat-tab" hidden={tab!=='chat'}><AssistantChat configured={!!status?.configured} selectedHostIds={selectedHostIds} model={status?.model} openSettings={openSettings} onSearch={()=>setTab('search')} onChanges={()=>setTab('changes')}/></div>
    <div className="assistant-tab-content assistant-scroll-tab" hidden={tab!=='search'}>
      <form className="assistant-query" onSubmit={submit}><label htmlFor="fleet-query">你想找什么？</label><div className="assistant-query-input"><textarea id="fleet-query" aria-label="跨机器查找问题" rows={2} maxLength={1000} value={query} onChange={event=>setQuery(event.target.value)} placeholder="例如：我的推理服务在哪台机器？" disabled={!!pending}/><button className="primary" disabled={!!pending||!status?.configured||!query.trim()}>{pending==='search'?<LoaderCircle size={17} className="spin"/>:<Search size={17}/ >}{pending==='search'?'正在查找…':'查找'}</button></div><div className="assistant-query-options"><label><input type="checkbox" checked={refresh} disabled={!!pending} onChange={event=>setRefresh(event.target.checked)}/>查询前重新采集（最多等待 25 秒）</label><span>仅发送你的问题给模型；实际匹配在本机完成。</span></div><div className="assistant-examples">{examples.map(example=><button type="button" key={example} disabled={!!pending} onClick={()=>setQuery(example)}>{example}</button>)}</div></form>
      {search&&<div className="assistant-results" aria-live="polite"><div className="assistant-result-heading"><div><h3>找到 {search.total} 项匹配结果</h3><p>问题：{search.query}</p></div><span>{search.model} · {(search.elapsed_ms/1000).toFixed(2)} 秒</span></div>
        <div className="assistant-conditions">{search.plan.scope==='resources'?`同机至少 ${search.plan.count} 个 ${search.plan.kind||'同类型设备'} · 每个剩余 ≥ ${search.plan.min_free_gib} GiB${search.plan.idle?' · 无可见计算进程':''}`:`${search.plan.scope==='sessions'?'tmux 会话':search.plan.scope==='hosts'?'机器':'占卡进程'}${search.plan.keywords.length?' · 关键字：'+search.plan.keywords.join(' / '):''}${search.plan.owner?' · 用户：'+(search.plan.owner==='__self__'?'各机器当前 SSH 账号':search.plan.owner):''}`}{search.plan.host&&` · 机器：${search.plan.host}`}</div>
        {search.items.map((row,index)=><article className="assistant-result-card" key={`${row.host_id}-${row.type}-${index}`}><div className="assistant-result-name"><Server size={17}/><strong>{row.alias}</strong><span>{rowTitle(row)}</span></div>{row.device_ids.length>0&&<p>设备：{row.device_ids.join('、')}</p>}{row.command&&<pre>{row.command}</pre>}{row.cwd&&<p className="assistant-path">工作目录：{row.cwd}</p>}{row.type==='session'&&<p>{row.attached?'有已连接的客户端':'当前没有客户端连接'}；会话属于该机器的 SSH 登录账号。</p>}{row.devices&&<p>{row.devices.map(d=>`${d.id}：${d.memory_free===null?'未知':(d.memory_free/1024**3).toFixed(1)+' GiB'}`).join(' · ')}</p>}<footer><small>采集于 {stamp(row.collected_at)}</small><div><button className="text-button" onClick={()=>locate(row.host_id,row.device_ids)}>查看机器 <ArrowUpRight size={13}/></button><button className="text-button" onClick={()=>openTerminal(row.host_id)}><Terminal size={13}/>打开终端</button></div></footer></article>)}
        {search.total===0&&<div className="assistant-empty">在已查清的数据中未找到匹配项。请同时查看下方未查清的机器和查询范围。</div>}
        {(search.coverage.unavailable.length>0||search.coverage.unknown.length>0||search.coverage.self_unknown.length>0)&&<div className="assistant-note"><strong>部分信息未查清</strong>{search.coverage.unavailable.length>0&&<p>离线、过期或刷新未完成：{search.coverage.unavailable.map(item=>item.alias).join('、')}</p>}{search.coverage.unknown.map(item=><p key={item}>{item}</p>)}{search.coverage.self_unknown.length>0&&<p>无法确认“我的”归属：{search.coverage.self_unknown.join('、')}。需要新一轮采集取得当前 SSH 用户。</p>}</div>}
        <details className="assistant-scope"><summary>查询范围与限制 · 已检查 {search.coverage.searched_hosts} 台机器</summary>{search.coverage.limitations.map(item=><p key={item}>{item}</p>)}{search.truncated&&<p>结果仅显示前 200 项，请缩小条件。</p>}</details>
      </div>}
      {!search&&<div className="assistant-empty"><Search size={25}/><p>查找占卡进程、空闲设备、tmux 会话或已添加的机器。</p><small>模型只理解条件，不生成或执行远端命令。</small></div>}
    </div>
    <div className="assistant-tab-content assistant-scroll-tab" hidden={tab!=='changes'}>
      <div className="assistant-history-toolbar"><label>时间范围<select aria-label="资源变化时间范围" value={hours} disabled={!!pending} onChange={event=>setHours(Number(event.target.value))}><option value={1}>最近 1 小时</option><option value={6}>最近 6 小时</option><option value={24}>最近 24 小时</option><option value={168}>最近 7 天</option></select></label><div><button className="secondary" disabled={!!pending} onClick={reloadHistory}>刷新记录</button><button className="primary" disabled={!!pending||!history||!status?.configured||history.event_count===0} onClick={summarize}>{pending==='summary'?<LoaderCircle size={16} className="spin"/>:<Sparkles size={16}/ >}{pending==='summary'?'正在归纳…':'生成变化摘要'}</button></div></div>
      {historyError&&<div className="assistant-error" role="alert">{historyError}</div>}
      {history&&<><div className="assistant-history-meta"><span><Clock size={14}/>开始记录：{stamp(history.recording_started_at)}</span><span>最近采样：{stamp(history.last_observed_at)}</span><span>{history.event_count} 条变化</span></div>{history.error&&<div className="assistant-note">{history.error}</div>}
        {summary&&<section className="assistant-summary" aria-label="AI 变化归纳"><div className="assistant-result-heading"><h3><Sparkles size={17}/>AI 变化归纳</h3><span>{summary.model||'无须调用模型'} · {(summary.elapsed_ms/1000).toFixed(2)} 秒</span></div>{summary.groups.map((group,index)=><div className="assistant-summary-group" key={index}><p>{group.text}</p><div>{group.event_ids.map(id=><button className="assistant-citation" key={id} onClick={()=>{setHighlight(group.event_ids);document.getElementById('resource-event-'+id)?.scrollIntoView({behavior:'smooth',block:'center'})}}>记录 #{id}</button>)}</div></div>)}<small>{summary.message}</small></section>}
        <p className="assistant-disclosure">生成摘要时，向当前模型发送下面的机器别名和采样变化，不包含密钥、完整启动命令或终端原文。模型只在点击时调用。</p>
        <div className="assistant-fact-heading"><h3>原始采样事实</h3><span>{history.truncated?'仅显示最近 100 条':'与摘要引用一一对应'}</span></div>
        {history.events.map(event=><article id={'resource-event-'+event.id} className={'assistant-event '+(highlight.includes(event.id)?'highlighted':'')} key={event.id}><span className="assistant-event-dot"/><div><div className="assistant-event-heading"><strong>{event.alias}</strong><span>#{event.id} · {stamp(event.created)}</span></div><p>{event.description}</p><button className="text-button" onClick={()=>locate(event.host_id,[])}>查看机器 <ArrowUpRight size={12}/></button></div></article>)}
        {history.event_count===0&&<div className="assistant-empty"><History size={27}/><p>这段时间尚无变化记录。</p><small>首次采样只建立基线；后续采样出现占用或连接状态变化时才会记录。不会补造过去的历史。</small></div>}
        <details className="assistant-scope"><summary>记录范围与限制</summary>{history.limitations.map(item=><p key={item}>{item}</p>)}</details>
      </>}
    </div>
  </section>;
}
