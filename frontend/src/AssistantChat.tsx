import {workspaceStorage} from './workspaceState';
import {useWorkspaceValue} from './workspaceHooks';
import React,{useEffect,useLayoutEffect,useRef,useState} from 'react';
import {Check,TriangleAlert,ChevronDown,LoaderCircle,MessageSquare,Plus,Send,Square,Trash2} from 'lucide-react';
import {applyChatEvent,chatRequest,loadChatId,saveChatId,shouldFollowChat,watchChat,toolNames,toolPresentation,type Chat,type ChatItem,type ChatTool} from './agentChat';
import {useAppConfirm} from './AppConfirm';
import './agentChat.css';
import {ChatMarkdown} from './ChatMarkdown';
import {installedSkill,skillRequest,type SkillMeta} from './skills';
import './skills.css';
import {SkillMessageInput} from './SkillMessageInput';

const suggestions=['找出我正在运行的推理服务','检查当前机器的系统和 Python 环境','读取指定机器上的配置文件并解释'];
export function AssistantChat({configured,selectedHostIds}:{configured:boolean;selectedHostIds:string[]}){
  const [items,setItems]=useState<ChatItem[]>([]),[chat,setChat]=useState<Chat|null>(null),[text,setText]=useWorkspaceValue('workspace:chat-draft','');
  const [busy,setBusy]=useState('load'),[error,setError]=useState(''),[restricted,setRestricted]=useWorkspaceValue('workspace:chat-restricted',false),[subscriptionVersion,setSubscriptionVersion]=useState(0);
  const [skills,setSkills]=useState<SkillMeta[]>([]),[selectedSkills,setSelectedSkills]=useWorkspaceValue<string[]>('workspace:chat-skills',[]),[skillError,setSkillError]=useState('');
  const request=useRef<AbortController|null>(null),subscription=useRef<AbortController|null>(null),transcript=useRef<HTMLDivElement>(null),follow=useRef(true);
  const chatValue=useRef<Chat|null>(null);
  const current=useRef<string|null>(null),alive=useRef(true);
  const {confirm,confirmation}=useAppConfirm();
  const apply=(value:Chat)=>{
    const previous=chatValue.current;
    if(previous?.id===value.id&&previous.updated>value.updated)return;
    if(current.current!==value.id)follow.current=true;
    current.current=value.id;chatValue.current=value;setChat(value);
    setItems(old=>[value,...old.filter(item=>item.id!==value.id)].slice(0,30));
  };
  useEffect(()=>{if(chat?.id)saveChatId(chat.id)},[chat?.id]);
  useEffect(()=>workspaceStorage.subscribe('iwb-assistant-chat',()=>{
    const id=loadChatId();if(!id||id===current.current)return;
    void chatRequest<Chat>('/'+id).then(value=>{if(alive.current&&loadChatId()===id){subscription.current?.abort();apply(value)}}).catch(()=>{});
  }),[]);
  useEffect(()=>{
    let disposed=false;let controller:AbortController|undefined;
    const load=()=>{controller?.abort();controller=new AbortController();const active=controller;void skillRequest<{items:SkillMeta[]}>('','GET',undefined,active.signal).then(value=>{if(!disposed&&!active.signal.aborted){const enabled=value.items.filter(skill=>skill.enabled);setSkills(enabled);setSelectedSkills(old=>old.filter(name=>enabled.some(skill=>skill.name===name)));setSkillError('')}}).catch(e=>{if(!disposed&&!active.signal.aborted)setSkillError(e.message)})};
    load();window.addEventListener('infra-workbench:skills-changed',load);window.addEventListener('focus',load);
    return()=>{disposed=true;controller?.abort();window.removeEventListener('infra-workbench:skills-changed',load);window.removeEventListener('focus',load)};
  },[chat?.active_run]);
  useEffect(()=>{
    alive.current=true;const controller=new AbortController();
    chatRequest<{items:ChatItem[]}>('','GET',undefined,controller.signal).then(async value=>{
      if(!alive.current)return;setItems(value.items);
      const saved=loadChatId();const id=value.items.find(item=>item.id===saved)?.id||value.items[0]?.id;
      if(id){const value=await chatRequest<Chat>('/'+id,'GET',undefined,controller.signal);if(alive.current)apply(value)}
    }).catch(e=>{if(alive.current&&e.name!=='AbortError')setError(e.message)}).finally(()=>{if(alive.current)setBusy('')});
    return()=>{alive.current=false;controller.abort();request.current?.abort();subscription.current?.abort()};
  },[]);
  useEffect(()=>{
    if(!chat?.active_run)return;
    const id=chat.id,controller=new AbortController();subscription.current=controller;
    void watchChat(id,{signal:controller.signal,onEvent:event=>{
      if(controller.signal.aborted||!alive.current||current.current!==id)return;
      const previous=chatValue.current;if(!previous)return;
      const next=applyChatEvent(previous,event);
      if(next){apply(next);setError('')}
      else{chatValue.current=null;current.current=null;setChat(null);setItems(old=>old.filter(item=>item.id!==id));controller.abort()}
    },onError:error=>{if(!controller.signal.aborted&&current.current===id)setError(error.message)}});
    return()=>{controller.abort();if(subscription.current===controller)subscription.current=null};
  },[chat?.id,chat?.active_run,subscriptionVersion]);
  useLayoutEffect(()=>{
    const view=transcript.current;
    if(view&&follow.current)view.scrollTop=view.scrollHeight;
  },[chat]);
  const act=async(name:string,fn:(signal:AbortSignal)=>Promise<void>)=>{
    if(request.current)return;
    const controller=new AbortController();request.current=controller;setBusy(name);setError('');
    try{await fn(controller.signal)}catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:'对话操作失败')}
    finally{request.current=null;if(alive.current){setBusy('');if(current.current===null&&chatValue.current){current.current=chatValue.current.id;setSubscriptionVersion(value=>value+1)}}}
  };
  const send=(event?:React.FormEvent)=>{
    event?.preventDefault();if(!text.trim()||busy||chat?.active_run)return;
    const message=text.trim();void act('send',async signal=>{
      const target=chat||await chatRequest<Chat>('','POST',{},signal);if(!alive.current||signal.aborted)return;apply(target);
      const value=await chatRequest<Chat>('/'+target.id+'/messages','POST',{content:message,selected_host_ids:selectedHostIds,restrict_to_selected:restricted,selected_skill_names:selectedSkills},signal);
      if(alive.current){apply(value);setText('');setSelectedSkills([])}
    });
  };
  const newChat=()=>act('new',async signal=>{subscription.current?.abort();current.current=null;const value=await chatRequest<Chat>('','POST',{},signal);if(alive.current){apply(value);setText('');setSelectedSkills([])}});
  const switchChat=(id:string)=>act('switch',async signal=>{subscription.current?.abort();current.current=null;const value=await chatRequest<Chat>('/'+id,'GET',undefined,signal);if(alive.current){apply(value);setText('');setSelectedSkills([])}});
  const remove=async()=>{
    if(!chat||!await confirm('删除这段本机对话和工具记录？不会影响服务器上的文件或进程。'))return;
    void act('delete',async signal=>{await chatRequest('/'+chat.id,'DELETE',undefined,signal);const value=await chatRequest<{items:ChatItem[]}>('','GET',undefined,signal);if(!alive.current)return;setItems(value.items);setChat(null);chatValue.current=null;current.current=null;if(value.items[0])apply(await chatRequest<Chat>('/'+value.items[0].id,'GET',undefined,signal))});
  };
  const running=!!chat?.active_run;
  return <section className="agent-chat" aria-label="服务器 Agent 对话">
    <div className="chat-toolbar"><label className="chat-session-picker"><MessageSquare size={16}/><select aria-label="选择对话" disabled={!!busy} value={chat?.id||''} onChange={event=>switchChat(event.target.value)}>{!chat&&<option value="">新对话</option>}{items.map(item=><option value={item.id} key={item.id}>{item.active_run?'处理中 · ':''}{item.title}</option>)}</select><ChevronDown size={13}/></label><div><button className="secondary" disabled={!!busy} onClick={newChat}><Plus size={14}/>新对话</button><button className="icon-button" aria-label="删除当前对话" disabled={!!busy||!chat||running} onClick={remove}><Trash2 size={15}/></button></div></div>
    <div className="chat-scope"><label><input type="checkbox" checked={restricted} disabled={!!busy||running} onChange={event=>setRestricted(event.target.checked)}/>仅允许检查左侧所选的 {selectedHostIds.length} 台机器</label><span>{restricted?'工具操作限于所选范围':'可查询全部已添加机器；点击左侧机器不会自动缩小范围'}</span></div>
    {error&&<div className="assistant-error" role="alert">{error}</div>}
    <div ref={transcript} className="chat-transcript" aria-label="对话消息" aria-live="polite" onScroll={()=>{if(transcript.current)follow.current=shouldFollowChat(transcript.current)}}>
      {!chat?.turns.length&&<div className="chat-welcome"><span><MessageSquare size={27}/></span><h3>描述你要查询或完成的服务器操作</h3><p>可以连续追问“刚才那台”“只看 A2”。可以查询资源、预约机器或对比训练日志，并查看每一步的结果。</p><div>{suggestions.map(item=><button key={item} disabled={!!busy} onClick={()=>setText(item)}>{item}</button>)}</div></div>}
      {chat?.turns.map(turn=><article key={turn.id} className={'chat-turn '+turn.role} aria-label={turn.role==='user'?'用户消息':'助手消息'}><div className="chat-turn-label">{turn.role==='user'?'你':'AI 助手'}{turn.elapsed_ms!==undefined&&<small>{(turn.elapsed_ms/1000).toFixed(1)} 秒</small>}</div><div className="chat-turn-body">{!!turn.selected_skill_names?.length&&<div className="chat-skill-receipt">本轮指定技能：{turn.selected_skill_names.map(name=>`@${name}`).join('、')}</div>}{!!turn.skills_read?.length&&<div className="chat-skill-receipt">已读取技能：{turn.skills_read.map(skill=>`${skill.name} · v${skill.version}`).join('、')}</div>}{turn.tools?.length? <div className="chat-tool-list">{turn.tools.map(tool=><ToolTrace key={tool.id} tool={tool}/>)}</div>:null}{turn.content&&<div className={"chat-message-text"+(turn.status==='running'?' streaming':'')}>{turn.role==='assistant'?<ChatMarkdown>{turn.content}</ChatMarkdown>:turn.content}</div>}{turn.status==='running'&&<div className="chat-working"><span className="chat-stream-dot"/>{turn.tools?.some(tool=>tool.status==='running')?'正在执行工具…':turn.content?'正在接收回复…':'正在分析或整理结果…'}</div>}{turn.status&&['failed','limited','cancelled','interrupted'].includes(turn.status)&&<small className="chat-incomplete">{turn.status==='cancelled'?'已取消':turn.status==='interrupted'?'上次处理已中断':turn.status==='limited'?'已达本轮步骤上限':'本轮未完成'}</small>}</div></article>)}
    </div>
    <form className="chat-composer" onSubmit={send}><SkillMessageInput text={text} onChange={setText} skills={skills} selected={selectedSkills} onSelect={setSelectedSkills} disabled={!!busy||running} error={skillError} onSend={send}/><div className="chat-composer-bottom"><small>文件片段及检查结果会发给当前模型，常见凭据字段会脱敏。支持查询和按你的要求预约、设置监控及操作文件。</small>{running?<button type="button" className="secondary" disabled={!!busy} onClick={()=>act('cancel',async signal=>{const value=await chatRequest<Chat>('/'+chat!.id+'/cancel','POST',{},signal);if(alive.current)apply(value)})}><Square size={13}/>取消本轮</button>:<button className="primary" disabled={!!busy||!configured||!text.trim()||restricted&&!selectedHostIds.length}>{busy==='send'?<LoaderCircle size={15} className="spin"/>:<Send size={15}/>}发送</button>}</div><span className="chat-shortcut">Ctrl / ⌘ + Enter 发送 · 对话保存在本机，最多 20 轮；更早内容可能不再传给模型，请按需重新查询。</span></form>
    {confirmation}
  </section>;
}

function ToolTrace({tool}:{tool:ChatTool}){
  const presentation=toolPresentation(tool);
  const installed=tool.name==='install_skill_draft'?installedSkill(tool.output,tool.status):null;
  return <>{installed&&<div className="chat-skill-installed" role="status">技能 {installed.name} · v{installed.version} 已安装，下一轮对话生效。</div>}<details className={'chat-tool '+presentation.status}><summary>{tool.status==='running'?<LoaderCircle size={14} className="spin"/>:presentation.status==='warning'?<TriangleAlert size={14}/>:tool.status==='succeeded'?<Check size={14}/>:<Square size={12}/>}<strong>{toolNames[tool.name]||tool.name}</strong>{tool.target&&<span>{tool.target}</span>}<small>{presentation.label}</small></summary><div className="chat-tool-details">{tool.arguments&&<><label>参数</label><pre>{tool.arguments}</pre></>}{tool.output&&<><label>工具返回</label><pre>{tool.output}</pre></>}<small>开始于 {new Date(tool.started*1000).toLocaleString('zh-CN')}{tool.finished&&` · ${(tool.finished-tool.started).toFixed(1)} 秒`}</small></div></details></>;
}
