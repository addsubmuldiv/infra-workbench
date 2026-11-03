import {takeTerminalContext,TERMINAL_CONTEXT_EVENT,type TerminalAttachment} from './terminalContext';
import {AssistantEnginePicker,type AssistantEngine} from './AssistantEnginePicker';
import {getLocale} from './i18n';
import {t} from './i18n';
import {ui} from './assistantLocale';
import {AgentProfilePicker} from './AgentProfilePicker';
import {ContextUsageMeter} from './ContextUsageMeter';
import {ChatSessionPicker} from './ChatSessionPicker';
import {ChatModelPicker} from './ChatModelPicker';
import {workspaceStorage} from './workspaceState';
import {useWorkspaceValue} from './workspaceHooks';
import React,{useEffect,useLayoutEffect,useRef,useState} from 'react';
import {Check,Settings2,Sparkles,Server,TriangleAlert,ChevronDown,LoaderCircle,Plus,Send,Square,Trash2} from 'lucide-react';
import {chatReplyTime,applyChatEvent,chatRequest,loadChatId,saveChatId,shouldFollowChat,watchChat,toolNames,toolPresentation,type Chat,type ChatItem,type ChatTool} from './agentChat';
import {useAppConfirm} from './AppConfirm';
import './agentChat.css';
import {ChatMarkdown} from './ChatMarkdown';
import {installedSkill,skillRequest,type SkillMeta} from './skills';
import './skills.css';
import {SkillMessageInput} from './SkillMessageInput';

const suggestions=['检查可用资源和运行中的服务','分析训练日志并找出异常','帮我设置资源监控'];
export function AssistantChat({configured,selectedHostIds,model,openSettings}:{configured:boolean;selectedHostIds:string[];model?:string;openSettings?:()=>void}){
  const [attachments,setAttachments]=useState<TerminalAttachment[]>(takeTerminalContext);
  useEffect(()=>{const receive=()=>setAttachments(old=>[...old,...takeTerminalContext()].slice(-3));window.addEventListener(TERMINAL_CONTEXT_EVENT,receive);return()=>window.removeEventListener(TERMINAL_CONTEXT_EVENT,receive)},[]);
  const [engine,setEngine]=useWorkspaceValue<AssistantEngine>('workspace:assistant-engine','deepagents');
  const [profileId,setProfileId]=useState<string|undefined>(undefined);
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
    current.current=value.id;chatValue.current=value;setChat(value);if(value.turns.length)setEngine(value.engine||'deepagents');
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
    try{await fn(controller.signal)}catch(e){if(!controller.signal.aborted)setError(e instanceof Error?e.message:ui("对话操作失败"))}
    finally{request.current=null;if(alive.current){setBusy('');if(current.current===null&&chatValue.current){current.current=chatValue.current.id;setSubscriptionVersion(value=>value+1)}}}
  };
  const send=(event?:React.FormEvent)=>{
    event?.preventDefault();if(!text.trim()||busy||chat?.active_run)return;
    const message=text.trim();void act('send',async signal=>{
      const target=chat||await chatRequest<Chat>('','POST',{},signal);if(!alive.current||signal.aborted)return;apply(target);
      const value=await chatRequest<Chat>('/'+target.id+'/messages','POST',{engine,profile_id:engine==='deepagents'?profileId:undefined,content:message,terminal_attachments:attachments,selected_host_ids:selectedHostIds,restrict_to_selected:restricted,selected_skill_names:selectedSkills},signal);
      if(alive.current){apply(value);setText('');setSelectedSkills([]);setAttachments([])}
    });
  };
  const newChat=()=>act('new',async signal=>{subscription.current?.abort();current.current=null;const value=await chatRequest<Chat>('','POST',{},signal);if(alive.current){apply(value);setText('');setSelectedSkills([]);setAttachments([])}});
  const switchChat=(id:string)=>act('switch',async signal=>{subscription.current?.abort();current.current=null;const value=await chatRequest<Chat>('/'+id,'GET',undefined,signal);if(alive.current){apply(value);setText('');setSelectedSkills([]);setAttachments([])}});
  const remove=async()=>{
    if(!chat||!await confirm(ui("删除这段本机对话和工具记录？不会影响服务器上的文件或进程。")))return;
    void act('delete',async signal=>{await chatRequest('/'+chat.id,'DELETE',undefined,signal);const value=await chatRequest<{items:ChatItem[]}>('','GET',undefined,signal);if(!alive.current)return;setItems(value.items);setChat(null);chatValue.current=null;current.current=null;if(value.items[0])apply(await chatRequest<Chat>('/'+value.items[0].id,'GET',undefined,signal))});
  };
  const running=!!chat?.active_run;
  return <section className="agent-chat" aria-label={ui("AI 工作台对话")}>
    <div className="chat-toolbar"><ChatSessionPicker items={items} value={chat?.id||''} disabled={!!busy} onChange={switchChat}/><div><button className="icon-button" aria-label={ui("新对话")} title={ui("新对话")} disabled={!!busy} onClick={newChat}><Plus size={16}/></button><details className="chat-more"><summary aria-label={ui("对话选项")}>•••</summary><div><button disabled={!!busy||!chat||running} onClick={remove}><Trash2 size={14}/>{ui("删除当前对话")}</button><p>{ui("对话保存在本机，上下文较长时会自动压缩早期内容。文件片段和检查结果会发送给当前模型，常见凭据字段会脱敏。")}</p></div></details></div></div>
    <AssistantEnginePicker value={engine} onChange={setEngine} disabled={!!busy||!!chat?.active_run}/>{engine==='deepagents'&&<AgentProfilePicker onChange={value=>setProfileId(value.active_id)}/>}
    {engine==='deepagents'&&<ContextUsageMeter chat={chat} model={model}/>}
    {error&&<div className="assistant-error" role="alert">{error}</div>}
    <div ref={transcript} className="chat-transcript" aria-label={ui("对话消息")} aria-live="polite" onScroll={()=>{if(transcript.current)follow.current=shouldFollowChat(transcript.current)}}>
      {!chat?.turns.length&&<div className="chat-welcome"><span><Sparkles size={27}/></span><h3>{ui("你希望完成什么？")}</h3><p>{ui("检查资源、整理文件、预约机器或设置监控，直接描述你想完成的事情。")}</p><div>{suggestions.map(item=><button key={item} disabled={!!busy} onClick={()=>setText(ui(item))}>{ui(item)}</button>)}</div></div>}
      {chat?.turns.map(turn=><article key={turn.id} className={'chat-turn '+turn.role} aria-label={turn.role==='user'?ui("用户消息"):ui("助手消息")}><div className="chat-turn-label">{turn.role==='user'?ui("你"):ui("AI 助手")}{turn.role==='assistant'&&turn.model&&<small title={turn.profile_name}>{turn.model}</small>}{turn.role==='assistant'&&<ReplyTimestamp created={turn.created}/ >}{turn.elapsed_ms!==undefined&&<small>{(turn.elapsed_ms/1000).toFixed(1)} {ui(" 秒")}</small>}</div><div className="chat-turn-body">{turn.context_compaction&&<div className="chat-compaction" role="status">{turn.context_compaction.status==='running'?<LoaderCircle size={14} className="spin"/>:turn.context_compaction.status==='completed'?<Check size={14}/>:<TriangleAlert size={14}/>}<span>{turn.context_compaction.status==='running'?ui("正在压缩上下文…"):turn.context_compaction.status==='completed'?ui("前面的上下文已压缩"):ui("上下文压缩未完成")}</span><small>{turn.context_compaction.status==='completed'?ui("后续使用摘要和近期消息，本地聊天记录保留"):turn.context_compaction.status==='running'?ui("正在整理早期内容，完成后继续回复"):ui("请查看本轮处理结果后重试")}</small></div>}{!!turn.selected_skill_names?.length&&<div className="chat-skill-receipt">{ui("本轮指定技能：")}{turn.selected_skill_names.map(name=>`@${name}`).join('、')}</div>}{!!turn.skills_read?.length&&<div className="chat-skill-receipt">{ui("已读取技能：")}{turn.skills_read.map(skill=>`${skill.name} · v${skill.version}`).join('、')}</div>}{turn.tools?.length? <details className="chat-execution"><summary><span>{turn.tools.some(tool=>tool.status==='running')?<LoaderCircle size={14} className="spin"/>:turn.tools.some(tool=>['failed','warning'].includes(toolPresentation(tool).status))?<TriangleAlert size={14}/>:<Check size={14}/>}{ui("执行步骤")}</span><small>{turn.tools.some(tool=>tool.status==='running')?ui("执行中 · "):''}{turn.tools.length} {ui(" 步")}</small><ChevronDown size={13}/></summary><div className="chat-tool-list">{turn.tools.map(tool=><ToolTrace key={tool.id} tool={tool}/>)}</div></details>:null}{!!turn.terminal_attachments?.length&&<div>{turn.terminal_attachments.map((item,index)=><details key={index}><summary>{t('终端附件','Terminal attachment')} · {item.label}{item.truncated?t(' · 已截断',' · Truncated'):''}</summary><small>{item.host_id} · {item.terminal_id} · {item.cwd||t('目录未知','Unknown directory')} · {item.captured_at}</small><pre>{item.content}</pre></details>)}</div>}{turn.content&&<div className={"chat-message-text"+(turn.status==='running'?' streaming':'')}>{turn.role==='assistant'?<ChatMarkdown>{turn.content}</ChatMarkdown>:turn.content}</div>}{turn.status==='running'&&turn.provider_status&&<small role="status">{turn.provider_status}</small>}{turn.status==='running'&&<div className="chat-working"><span className="chat-stream-dot"/>{turn.tools?.some(tool=>tool.status==='running')?ui("正在执行工具…"):turn.content?ui("正在接收回复…"):ui("正在分析或整理结果…")}</div>}{turn.status&&['failed','limited','cancelled','interrupted'].includes(turn.status)&&<small className="chat-incomplete">{turn.status==='cancelled'?ui("已取消"):turn.status==='interrupted'?ui("上次处理已中断"):turn.status==='limited'?ui("已达本轮步骤上限"):ui("本轮未完成")}</small>}</div></article>)}
    </div>
    <form className="chat-composer" onSubmit={send}><details className="chat-context"><summary><Server size={13}/><span>{restricted?t(`操作范围：所选 ${selectedHostIds.length} 台机器`,`Scope: ${selectedHostIds.length} selected machines`):t(`当前上下文：${selectedHostIds.length?`选中 ${selectedHostIds.length} 台机器`:ui("未选择机器")}`,`Context: ${selectedHostIds.length?`${selectedHostIds.length} machines selected`:ui("未选择机器")}`)}</span><Settings2 size={13}/>{ui("调整")}</summary><div className="chat-scope"><label><input type="checkbox" checked={restricted} disabled={!!busy||running} onChange={event=>setRestricted(event.target.checked)}/>{ui("仅允许操作所选的 ")}{selectedHostIds.length} {ui(" 台机器")}</label><span>{restricted?ui("工具操作限于所选范围"):ui("可操作全部已添加机器；选择机器不会自动限制操作范围")}</span></div></details>{attachments.map((item,index)=><details key={index}><summary>{t('终端附件','Terminal attachment')} · {item.label} · {item.source==='selection'?t('选区','Selection'):t('当前屏幕','Visible screen')}{item.truncated?t(' · 已截断',' · Truncated'):''}</summary><small>{item.host_id} · {t("标签","Tab")} {item.terminal_id} · {t("会话","Session")} {item.session_id||t('临时','Temporary')} · {item.cwd||t('目录未知','Unknown directory')} · {item.captured_at}</small><pre>{item.content}</pre><button type="button" onClick={()=>setAttachments(old=>old.filter((_,i)=>i!==index))}>{t('移除附件','Remove attachment')}</button></details>)}<SkillMessageInput text={text} onChange={setText} skills={skills} selected={selectedSkills} onSelect={setSelectedSkills} disabled={!!busy||running} error={skillError} onSend={send}/><div className="chat-composer-bottom">{engine==='deepagents'?<ChatModelPicker model={model} openSettings={openSettings}/>:<small>Codex · {t('本机默认模型','Local default model')}</small>}{running?<button type="button" className="secondary" disabled={!!busy} onClick={()=>act('cancel',async signal=>{const value=await chatRequest<Chat>('/'+chat!.id+'/cancel','POST',{},signal);if(alive.current)apply(value)})}><Square size={13}/>{ui("取消本轮")}</button>:<button className="primary" disabled={!!busy||(engine==='deepagents'&&!configured)||!text.trim()||restricted&&!selectedHostIds.length}>{busy==='send'?<LoaderCircle size={15} className="spin"/>:<Send size={15}/>}<span className="chat-send-label">{ui("发送")}</span></button>}</div><span className="chat-shortcut">{ui("Enter 发送 · Shift + Enter 换行")}</span></form>
    {confirmation}
  </section>;
}

function ToolTrace({tool}:{tool:ChatTool}){
  const presentation=toolPresentation(tool);
  const installed=tool.name==='install_skill_draft'?installedSkill(tool.output,tool.status):null;
  return <>{installed&&<div className="chat-skill-installed" role="status">{t("技能 ","Skill ")}{installed.name} · v{installed.version} {ui(" 已安装，下一轮对话生效。")}</div>}<details className={'chat-tool '+presentation.status}><summary>{tool.status==='running'?<LoaderCircle size={14} className="spin"/>:presentation.status==='warning'?<TriangleAlert size={14}/>:tool.status==='succeeded'?<Check size={14}/>:<Square size={12}/>}<strong>{toolNames[tool.name]||tool.name}</strong>{tool.target&&<span>{tool.target}</span>}<small>{presentation.label}</small></summary><div className="chat-tool-details">{tool.arguments&&<><label>{ui("参数")}</label><pre>{tool.arguments}</pre></>}{tool.output&&<><label>{ui("工具返回")}</label><pre>{tool.output}</pre></>}<small>{ui("开始于 ")}{new Date(tool.started*1000).toLocaleString(getLocale()==='en'?'en-US':'zh-CN')}{tool.finished&&t(` · ${(tool.finished-tool.started).toFixed(1)} 秒`,` · ${(tool.finished-tool.started).toFixed(1)} s`)}</small></div></details></>;
}

function ReplyTimestamp({created}:{created:number}){
  const time=chatReplyTime(created);
  return time?<time className="chat-reply-time" dateTime={time.iso} title={time.full} aria-label={time.full}>{time.label}</time>:null;
}
