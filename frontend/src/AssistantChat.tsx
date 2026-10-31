import React,{useEffect,useRef,useState} from 'react';
import {Check,ChevronDown,LoaderCircle,MessageSquare,Plus,Send,Square,Trash2} from 'lucide-react';
import {chatRequest,loadChatId,saveChatId,toolNames,toolStatus,type Chat,type ChatItem,type ChatTool} from './agentChat';
import {useAppConfirm} from './AppConfirm';
import './agentChat.css';

const suggestions=['找出我正在运行的推理服务','检查当前机器的系统和 Python 环境','读取指定机器上的配置文件并解释'];
export function AssistantChat({configured,selectedHostIds}:{configured:boolean;selectedHostIds:string[]}){
  const [items,setItems]=useState<ChatItem[]>([]),[chat,setChat]=useState<Chat|null>(null),[text,setText]=useState('');
  const [busy,setBusy]=useState('load'),[error,setError]=useState(''),[restricted,setRestricted]=useState(false);
  const request=useRef<AbortController|null>(null),poll=useRef<AbortController|null>(null),tail=useRef<HTMLDivElement>(null);
  const current=useRef<string|null>(null),alive=useRef(true);
  const {confirm,confirmation}=useAppConfirm();
  const apply=(value:Chat)=>{current.current=value.id;setChat(value);saveChatId(value.id);setItems(old=>[value,...old.filter(item=>item.id!==value.id)].slice(0,30))};
  useEffect(()=>{
    alive.current=true;const controller=new AbortController();
    chatRequest<{items:ChatItem[]}>('','GET',undefined,controller.signal).then(async value=>{
      if(!alive.current)return;setItems(value.items);
      const saved=loadChatId();const id=value.items.find(item=>item.id===saved)?.id||value.items[0]?.id;
      if(id){const value=await chatRequest<Chat>('/'+id,'GET',undefined,controller.signal);if(alive.current)apply(value)}
    }).catch(e=>{if(alive.current&&e.name!=='AbortError')setError(e.message)}).finally(()=>{if(alive.current)setBusy('')});
    return()=>{alive.current=false;controller.abort();request.current?.abort();poll.current?.abort()};
  },[]);
  useEffect(()=>{
    if(!chat?.active_run)return;
    const controller=new AbortController();poll.current=controller;let timer:ReturnType<typeof setTimeout>;
    const tick=async()=>{
      try{
        const value=await chatRequest<Chat>('/'+chat.id,'GET',undefined,controller.signal);
        if(controller.signal.aborted||current.current!==chat.id)return;
        apply(value);
        if(value.active_run)timer=setTimeout(tick,850);
      }catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:'无法读取处理进度')}
    };
    timer=setTimeout(tick,400);
    return()=>{controller.abort();clearTimeout(timer)};
  },[chat?.id,chat?.active_run]);
  useEffect(()=>{tail.current?.scrollIntoView({behavior:'smooth',block:'nearest'})},[chat?.turns.length]);
  const act=async(name:string,fn:(signal:AbortSignal)=>Promise<void>)=>{
    if(request.current)return;
    const controller=new AbortController();request.current=controller;setBusy(name);setError('');
    try{await fn(controller.signal)}catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:'对话操作失败')}
    finally{request.current=null;if(alive.current)setBusy('')}
  };
  const send=(event?:React.FormEvent)=>{
    event?.preventDefault();if(!text.trim()||busy||chat?.active_run)return;
    const message=text.trim();void act('send',async signal=>{
      const target=chat||await chatRequest<Chat>('','POST',{},signal);apply(target);
      const value=await chatRequest<Chat>('/'+target.id+'/messages','POST',{content:message,selected_host_ids:selectedHostIds,restrict_to_selected:restricted},signal);
      if(alive.current){apply(value);setText('')}
    });
  };
  const newChat=()=>act('new',async signal=>{const value=await chatRequest<Chat>('','POST',{},signal);if(alive.current){apply(value);setText('')}});
  const switchChat=(id:string)=>act('switch',async signal=>{const value=await chatRequest<Chat>('/'+id,'GET',undefined,signal);if(alive.current){apply(value);setText('')}});
  const remove=async()=>{
    if(!chat||!await confirm('删除这段本机对话和工具记录？不会影响服务器上的文件或进程。'))return;
    void act('delete',async signal=>{await chatRequest('/'+chat.id,'DELETE',undefined,signal);const value=await chatRequest<{items:ChatItem[]}>('','GET',undefined,signal);if(!alive.current)return;setItems(value.items);setChat(null);current.current=null;if(value.items[0])apply(await chatRequest<Chat>('/'+value.items[0].id,'GET',undefined,signal))});
  };
  const running=!!chat?.active_run;
  return <section className="agent-chat" aria-label="服务器 Agent 对话">
    <div className="chat-toolbar"><label className="chat-session-picker"><MessageSquare size={16}/><select aria-label="选择对话" disabled={!!busy} value={chat?.id||''} onChange={event=>switchChat(event.target.value)}>{!chat&&<option value="">新对话</option>}{items.map(item=><option value={item.id} key={item.id}>{item.active_run?'处理中 · ':''}{item.title}</option>)}</select><ChevronDown size={13}/></label><div><button className="secondary" disabled={!!busy} onClick={newChat}><Plus size={14}/>新对话</button><button className="icon-button" aria-label="删除当前对话" disabled={!!busy||!chat||running} onClick={remove}><Trash2 size={15}/></button></div></div>
    <div className="chat-scope"><label><input type="checkbox" checked={restricted} disabled={!!busy||running} onChange={event=>setRestricted(event.target.checked)}/>仅允许检查左侧所选的 {selectedHostIds.length} 台机器</label><span>{restricted?'工具操作限于所选范围':'可查询全部已添加机器；点击左侧机器不会自动缩小范围'}</span></div>
    {error&&<div className="assistant-error" role="alert">{error}</div>}
    <div className="chat-transcript" aria-label="对话消息" aria-live="polite">
      {!chat?.turns.length&&<div className="chat-welcome"><span><MessageSquare size={27}/></span><h3>直接描述你想了解的服务器信息</h3><p>可以连续追问“刚才那台”“只看 A2”。助手会查询真实数据，展示读取和检查的过程。</p><div>{suggestions.map(item=><button key={item} disabled={!!busy} onClick={()=>setText(item)}>{item}</button>)}</div></div>}
      {chat?.turns.map(turn=><article key={turn.id} className={'chat-turn '+turn.role} aria-label={turn.role==='user'?'用户消息':'助手消息'}><div className="chat-turn-label">{turn.role==='user'?'你':'AI 助手'}{turn.elapsed_ms!==undefined&&<small>{(turn.elapsed_ms/1000).toFixed(1)} 秒</small>}</div><div className="chat-turn-body">{turn.tools?.length? <div className="chat-tool-list">{turn.tools.map(tool=><ToolTrace key={tool.id} tool={tool}/>)}</div>:null}{turn.content&&<div className="chat-message-text">{turn.content}</div>}{turn.status==='running'&&<div className="chat-working"><LoaderCircle className="spin" size={14}/>{turn.tools?.some(tool=>tool.status==='running')?'正在执行只读工具…':'正在分析或整理结果…'}</div>}{turn.status&&['failed','limited','cancelled','interrupted'].includes(turn.status)&&<small className="chat-incomplete">{turn.status==='cancelled'?'已取消':turn.status==='interrupted'?'上次处理已中断':turn.status==='limited'?'已达本轮步骤上限':'本轮未完成'}</small>}</div></article>)}
      <div ref={tail}/>
    </div>
    <form className="chat-composer" onSubmit={send}><textarea aria-label="对话消息输入" placeholder="例如：列出我的 vLLM 进程，再检查其中一台的监听端口" value={text} maxLength={4000} rows={3} disabled={!!busy||running} onChange={event=>setText(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)&&!event.nativeEvent.isComposing){event.preventDefault();send()}}}/><div className="chat-composer-bottom"><small>文件片段及检查结果会发给当前模型，常见凭据字段会脱敏。仅提供只读操作。</small>{running?<button type="button" className="secondary" disabled={!!busy} onClick={()=>act('cancel',async signal=>{const value=await chatRequest<Chat>('/'+chat!.id+'/cancel','POST',{},signal);if(alive.current)apply(value)})}><Square size={13}/>取消本轮</button>:<button className="primary" disabled={!!busy||!configured||!text.trim()||restricted&&!selectedHostIds.length}>{busy==='send'?<LoaderCircle size={15} className="spin"/>:<Send size={15}/>}发送</button>}</div><span className="chat-shortcut">Ctrl / ⌘ + Enter 发送 · 对话保存在本机，最多 20 轮；更早内容可能不再传给模型，请按需重新查询。</span></form>
    {confirmation}
  </section>;
}

function ToolTrace({tool}:{tool:ChatTool}){
  return <details className={'chat-tool '+tool.status}><summary>{tool.status==='running'?<LoaderCircle size={14} className="spin"/>:tool.status==='succeeded'?<Check size={14}/>:<Square size={12}/>}<strong>{toolNames[tool.name]||tool.name}</strong>{tool.target&&<span>{tool.target}</span>}<small>{toolStatus[tool.status]||tool.status}</small></summary><div className="chat-tool-details">{tool.arguments&&<><label>参数</label><pre>{tool.arguments}</pre></>}{tool.output&&<><label>工具返回</label><pre>{tool.output}</pre></>}<small>开始于 {new Date(tool.started*1000).toLocaleString('zh-CN')}{tool.finished&&` · ${(tool.finished-tool.started).toFixed(1)} 秒`}</small></div></details>;
}
