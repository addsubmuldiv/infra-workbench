import {CodexHost,CodexItems,CodexQuestionForm} from './CodexHost';
import {type CodexOptions} from './agentChat';
import {AgentPermissions,ApprovalCard} from './AgentPermissions';
import {permissionScope,type PermissionMode,type PermissionScope,type ChatDraft} from './agentChat';
import {takeTerminalContext,TERMINAL_CONTEXT_EVENT,type TerminalAttachment} from '../terminal/terminalContext';
import {AssistantEnginePicker,type AssistantEngine} from './AssistantEnginePicker';
import {getLocale} from '../../shared/i18n';
import {t} from '../../shared/i18n';
import {ui} from './assistantLocale';
import {AgentProfilePicker} from './AgentProfilePicker';
import {ContextUsageMeter} from './ContextUsageMeter';
import {ChatSessionPicker} from './ChatSessionPicker';
import {ChatModelPicker} from './ChatModelPicker';
import {workspaceStorage} from '../../workspace/workspaceState';
import {useWorkspaceValue} from '../../workspace/workspaceHooks';
import React,{useEffect,useLayoutEffect,useRef,useState} from 'react';
import {Check,Settings2,Sparkles,Server,TriangleAlert,ChevronDown,LoaderCircle,Plus,Send,Square,Trash2} from 'lucide-react';
import {chatReplyTime,applyChatEvent,chatRequest,isVisibleCodexItem,loadChatId,saveChatId,shouldFollowChat,watchChat,toolNames,toolPresentation,type Chat,type ChatItem,type ChatTool,type ChatTurn} from './agentChat';
import {useAppConfirm} from '../../shared/AppConfirm';
import './agentChat.css';
import {ChatMarkdown} from './ChatMarkdown';
import {installedSkill,skillRequest,type SkillMeta} from './skills';
import './skills.css';
import {SkillMessageInput} from './SkillMessageInput';

const AssistantA2ui=React.lazy(()=>import('./AssistantA2ui'));

const engineName=(engine?:AssistantEngine)=>engine==='claude'?'Claude Code':engine==='opencode'?'OpenCode':engine==='codex'?'Codex':'Deep Agents';
const suggestions=['检查可用资源和运行中的服务','分析训练日志并找出异常','帮我设置资源监控'];
type ComposerDraft={chatId:string|null;text:string|null;skills:string[]|null};
function legacyComposer():ComposerDraft{
  const draft:ComposerDraft={chatId:loadChatId(),text:null,skills:null};
  try{
    const text=JSON.parse(workspaceStorage.getItem('workspace:chat-draft')??'null');
    const skills=JSON.parse(workspaceStorage.getItem('workspace:chat-skills')??'null');
    if(typeof text==='string'&&text)draft.text=text;
    if(Array.isArray(skills)&&skills.length)draft.skills=skills.filter(name=>typeof name==='string');
  }catch{/* Use the server draft when legacy preferences cannot be read. */}
  return draft;
}

export function AssistantChat({configured,selectedHostIds,model,openSettings}:{configured:boolean;selectedHostIds:string[];model?:string;openSettings?:()=>void}){
  const [attachments,setAttachments]=useState<TerminalAttachment[]>(takeTerminalContext);
  useEffect(()=>{const receive=()=>setAttachments(old=>[...old,...takeTerminalContext()]);window.addEventListener(TERMINAL_CONTEXT_EVENT,receive);return()=>window.removeEventListener(TERMINAL_CONTEXT_EVENT,receive)},[]);
  const [engine,setEngine]=useWorkspaceValue<AssistantEngine>('workspace:assistant-engine','deepagents');
  const [resourceViewEnabled,setResourceViewEnabled]=useState(false);
  const [permissionMode,setPermissionMode]=useWorkspaceValue<PermissionMode>('workspace:chat-permission-mode','ask');
  const [localRoots,setLocalRoots]=useWorkspaceValue('workspace:chat-local-roots','');
  const [remoteRoots,setRemoteRoots]=useWorkspaceValue('workspace:chat-remote-roots','');
  const [externalMcp,setExternalMcp]=useWorkspaceValue('workspace:chat-external-mcp','');
  const [codexOptions,setCodexOptions]=useWorkspaceValue<CodexOptions>('workspace:chat-codex-options',{collaboration_mode:'default',cwd:'',model:'',effort:'',multi_agent:false,enabled_mcp_servers:[],enabled_plugins:[]});
  const [draftCodex,setDraftCodex]=useState<CodexOptions|null>(null);
  const [draftPermissions,setDraftPermissions]=useState<PermissionScope|null>(null);
  const [profileId,setProfileId]=useState<string|undefined>(undefined);
  const [items,setItems]=useState<ChatItem[]>([]),[chat,setChat]=useState<Chat|null>(null);
  const [legacyDraft]=useState(legacyComposer);
  const [composer,setComposer]=useWorkspaceValue('workspace:chat-composer:v1',legacyDraft);
  const composerId=chat?.id??null;
  const defaultComposer={chatId:composerId,text:chat?.draft?.content??'',skills:chat?.draft?.selected_skill_names??[]};
  const text=(composer.chatId===composerId?composer.text:null)??defaultComposer.text;
  const selectedSkills=(composer.chatId===composerId?composer.skills:null)??defaultComposer.skills;
  const resourceView=engine==='deepagents'&&resourceViewEnabled;
  const hasExtraContext=attachments.length>0||selectedSkills.length>0;
  const setText=(value:React.SetStateAction<string>)=>setComposer(old=>{
    const draft=old.chatId===composerId?old:defaultComposer;
    return {...draft,text:typeof value==='function'?value(draft.text??defaultComposer.text):value};
  });
  const setSelectedSkills=(value:string[])=>setComposer(old=>({...(old.chatId===composerId?old:defaultComposer),skills:value}));
  const [busy,setBusy]=useState('load'),[error,setError]=useState(''),[restricted,setRestricted]=useWorkspaceValue('workspace:chat-restricted',false),[subscriptionVersion,setSubscriptionVersion]=useState(0);
  const [skills,setSkills]=useState<SkillMeta[]>([]),[skillError,setSkillError]=useState('');
  const request=useRef<AbortController|null>(null),subscription=useRef<AbortController|null>(null),transcript=useRef<HTMLDivElement>(null),follow=useRef(true);
  const chatValue=useRef<Chat|null>(null);
  const [steering,setSteering]=useState(false);
  const [draftScope,setDraftScope]=useState<{selected_host_ids:string[];restrict_to_selected:boolean}|null>(null);
  const scopeHostIds=draftScope?.selected_host_ids??selectedHostIds,scopeRestricted=draftScope?.restrict_to_selected??restricted;
  const steerRequest=useRef<AbortController|null>(null);
  const current=useRef<string|null>(null),alive=useRef(true);
  const selectionRevision=useRef(0),remoteSelection=useRef<AbortController|null>(null);
  const {confirm,confirmation}=useAppConfirm();
  const apply=(value:Chat,persistSelection=true)=>{
    const previous=chatValue.current;
    if(previous?.id===value.id&&previous.updated>value.updated)return;
    const changed=previous?.id!==value.id;
    if(changed||previous?.draft&&!value.draft){
      const draft=value.draft;
      setDraftScope(draft?{selected_host_ids:draft.selected_host_ids??[],restrict_to_selected:!!draft.restrict_to_selected}:null);
      setDraftPermissions(draft?{permission_mode:draft.permission_mode??'ask',local_roots:draft.local_roots??[],remote_roots:draft.remote_roots??{},external_mcp_servers:draft.external_mcp_servers??[]}:null);
      setDraftCodex(draft?.codex_options??null);
    }
    if(changed){
      if(previous||value.draft)setAttachments(value.draft?.terminal_attachments??[]);
      if(value.draft)setResourceViewEnabled(!!value.draft.resource_view);
      follow.current=true;
      steerRequest.current?.abort();steerRequest.current=null;setSteering(false);
    }
    current.current=value.id;chatValue.current=value;setChat(value);
    if(changed&&value.draft?.engine)setEngine(value.draft.engine);
    else if(value.turns.length&&(changed||previous?.engine!==value.engine))setEngine(value.engine||'deepagents');
    setItems(old=>[value,...old.filter(item=>item.id!==value.id)]);
    if(changed&&persistSelection&&loadChatId()!==value.id)saveChatId(value.id);
  };
  useEffect(()=>workspaceStorage.subscribe('iwb-assistant-chat',()=>{
    const id=loadChatId();
    remoteSelection.current?.abort();remoteSelection.current=null;
    if(!id||id===current.current)return;
    selectionRevision.current++;
    request.current?.abort();
    steerRequest.current?.abort();
    const controller=new AbortController();remoteSelection.current=controller;
    void chatRequest<Chat>('/'+id,'GET',undefined,controller.signal).then(value=>{
      if(alive.current&&!controller.signal.aborted&&loadChatId()===id){subscription.current?.abort();apply(value,false)}
    }).catch(e=>{if(alive.current&&!controller.signal.aborted)setError(e.message)}).finally(()=>{
      if(remoteSelection.current===controller)remoteSelection.current=null;
    });
  }),[]);
  useEffect(()=>{
    let disposed=false;let controller:AbortController|undefined;
    const load=()=>{
      controller?.abort();controller=new AbortController();const active=controller;
      void skillRequest<{items:SkillMeta[]}>('','GET',undefined,active.signal).then(value=>{
        if(disposed||active.signal.aborted)return;
        const enabled=value.items.filter(skill=>skill.enabled);
        setSkills(enabled);setSkillError('');
        setComposer(old=>{
          if(old.chatId!==composerId||!old.skills?.length)return old;
          const available=old.skills.filter(name=>enabled.some(skill=>skill.name===name));
          return available.length===old.skills.length?old:{...old,skills:available};
        });
      }).catch(e=>{if(!disposed&&!active.signal.aborted)setSkillError(e.message)});
    };
    load();window.addEventListener('infra-workbench:skills-changed',load);window.addEventListener('focus',load);
    return()=>{disposed=true;controller?.abort();window.removeEventListener('infra-workbench:skills-changed',load);window.removeEventListener('focus',load)};
  },[composerId,chat?.active_run]);
  useEffect(()=>{
    alive.current=true;const controller=new AbortController();const revision=selectionRevision.current;
    chatRequest<{items:ChatItem[]}>('','GET',undefined,controller.signal).then(async value=>{
      if(!alive.current)return;setItems(value.items);
      const saved=loadChatId();const id=value.items.find(item=>item.id===saved)?.id||value.items[0]?.id;
      if(id){const value=await chatRequest<Chat>('/'+id,'GET',undefined,controller.signal);if(alive.current&&!controller.signal.aborted&&selectionRevision.current===revision)apply(value)}
    }).catch(e=>{if(alive.current&&e.name!=='AbortError')setError(e.message)}).finally(()=>{if(alive.current)setBusy('')});
    return()=>{alive.current=false;controller.abort();remoteSelection.current?.abort();request.current?.abort();subscription.current?.abort();steerRequest.current?.abort()};
  },[]);
  useEffect(()=>{
    if(!chat?.active_run)return;
    const id=chat.id,controller=new AbortController();subscription.current=controller;
    void watchChat(id,{signal:controller.signal,onEvent:event=>{
      if(controller.signal.aborted||!alive.current||current.current!==id)return;
      const previous=chatValue.current;if(!previous)return;
      const next=applyChatEvent(previous,event);
      if(next===previous)return false;
      if(next){apply(next);setError('')}
      else{chatValue.current=null;current.current=null;setChat(null);setItems(old=>old.filter(item=>item.id!==id));controller.abort()}
    },onError:error=>{if(!controller.signal.aborted&&current.current===id)setError(error.message)}});
    return()=>{controller.abort();if(subscription.current===controller)subscription.current=null};
  },[chat?.id,chat?.active_run,subscriptionVersion]);
  useLayoutEffect(()=>{
    const view=transcript.current;
    if(view&&follow.current)view.scrollTop=view.scrollHeight;
  },[chat]);
  const act=async(name:string,fn:(signal:AbortSignal,isCurrent:()=>boolean)=>Promise<void>)=>{
    if(request.current||remoteSelection.current)return;
    const controller=new AbortController();request.current=controller;setBusy(name);setError('');
    const revision=selectionRevision.current;
    const isCurrent=()=>alive.current&&!controller.signal.aborted&&selectionRevision.current===revision;
    try{await fn(controller.signal,isCurrent)}catch(e){if(isCurrent())setError(ui(e instanceof Error?e.message:"对话操作失败"))}
    finally{request.current=null;if(alive.current){setBusy('');if(current.current===null&&chatValue.current){current.current=chatValue.current.id;setSubscriptionVersion(value=>value+1)}}}
  };
  const running=!!chat?.active_run;
  const runMode=running?chat?.turns.find(turn=>turn.id===chat.active_run)?.permission_mode:undefined;
  const canSteer=running&&chat?.engine==='codex';
  const canSend=!!text.trim()&&!busy&&!steering&&(!resourceView||!hasExtraContext)&&(running?canSteer:(engine!=='deepagents'||configured)&&(!scopeRestricted||scopeHostIds.length>0));

  const send=(event?:React.FormEvent)=>{
    event?.preventDefault();
    if(!canSend||request.current||steerRequest.current||remoteSelection.current)return;
    // A stream update can change the run before the composer has rerendered.
    if(chatValue.current?.id!==chat?.id||chatValue.current?.active_run!==chat?.active_run)return;
    const message=text.trim();
    if(chat?.active_run)return steer(chat.id,chat.active_run,message);
    return act('send',async (signal,isCurrent)=>{
      const permissions=resourceView?permissionScope('read_only','','',scopeHostIds):draftPermissions??permissionScope(permissionMode,localRoots,remoteRoots,scopeHostIds,externalMcp);
      const target=chat??await chatRequest<Chat>('','POST',{},signal);
      if(!isCurrent())return;
      if(!chat){
        setComposer(old=>old.chatId===null?{...old,chatId:target.id}:old);
        apply(target);
      }
      const value=await chatRequest<Chat>('/'+target.id+'/messages','POST',{engine,profile_id:engine==='deepagents'?profileId:undefined,content:message,terminal_attachments:attachments,selected_host_ids:scopeHostIds,restrict_to_selected:scopeRestricted,selected_skill_names:selectedSkills,resource_view:resourceView||undefined,codex_options:engine==='codex'?(draftCodex??codexOptions):undefined,...permissions},signal);
      if(!isCurrent()||current.current!==target.id||value.id!==target.id)return;
      apply(value);
      setComposer(old=>old.chatId===target.id&&(!old.text||old.text.trim()===message)?{chatId:target.id,text:'',skills:[]}:old);
      setAttachments(current=>current.filter(item=>!attachments.includes(item)));
    });
  };
  const newChat=()=>act('new',async (signal,isCurrent)=>{subscription.current?.abort();current.current=null;const value=await chatRequest<Chat>('','POST',{},signal);if(isCurrent())apply(value)});
  const switchChat=(id:string)=>act('switch',async (signal,isCurrent)=>{subscription.current?.abort();current.current=null;const value=await chatRequest<Chat>('/'+id,'GET',undefined,signal);if(isCurrent())apply(value)});
  const branch=()=>{
    if(!chat||chat.active_run)return;
    const source=chat.id;
    return act('branch',async (signal,isCurrent)=>{
      const value=await chatRequest<{chat:Chat;draft:ChatDraft}>('/'+source+'/branch','POST',{},signal);
      if(!isCurrent()||current.current!==source)return;
      subscription.current?.abort();apply({...value.chat,draft:value.draft});
    });
  };
  const steer=async(id:string,run:string,content:string)=>{
    const controller=new AbortController();steerRequest.current=controller;setSteering(true);setError('');
    const revision=selectionRevision.current;
    const isCurrent=()=>alive.current&&!controller.signal.aborted&&current.current===id&&selectionRevision.current===revision;
    try{
      const value=await chatRequest<Chat>('/'+id+'/steer','POST',{content,run_id:run},controller.signal);
      if(isCurrent()){apply(value);setText(old=>old.trim()===content?'':old)}
    }catch(e){if(isCurrent())setError(e instanceof Error?e.message:t('补充指令发送失败','Failed to send supplemental instruction'))}
    finally{if(steerRequest.current===controller){steerRequest.current=null;if(alive.current)setSteering(false)}}
  };
  const remove=async()=>{
    if(!chat||!await confirm(ui("删除这段本机对话和工具记录？不会影响服务器上的文件或进程。")))return;
    if(current.current!==chat.id)return;
    void act('delete',async (signal,isCurrent)=>{await chatRequest('/'+chat.id,'DELETE',undefined,signal);const value=await chatRequest<{items:ChatItem[]}>('','GET',undefined,signal);if(!isCurrent())return;setItems(value.items);if(value.items[0]){const next=await chatRequest<Chat>('/'+value.items[0].id,'GET',undefined,signal);if(isCurrent())apply(next)}else{setChat(null);chatValue.current=null;current.current=null;setAttachments([])}});
  };
  return <section className="agent-chat" aria-label={ui("AI 工作台对话")}>
    <div className="chat-toolbar"><ChatSessionPicker items={items} value={chat?.id||''} disabled={!!busy} onChange={switchChat}/><div><button className="icon-button" aria-label={ui("新对话")} title={ui("新对话")} disabled={!!busy} onClick={newChat}><Plus size={16}/></button><details className="chat-more"><summary aria-label={ui("对话选项")}>•••</summary><div><button disabled={!!busy||!chat||running||!chat.turns.some(turn=>turn.role==='user')} onClick={branch}>{t("从上一轮之前分支","Branch before the previous round")}</button><p>{t("分支保留此前的对话，并恢复上一轮用户消息供编辑。已执行的命令和文件修改不会回退。","Branch keeps earlier conversation and restores the previous user message for editing. Executed commands and file changes are not rolled back.")}</p><button disabled={!!busy||!chat||running} onClick={remove}><Trash2 size={14}/>{ui("删除当前对话")}</button><p>{ui("对话保存在本机，上下文较长时会自动压缩早期内容。文件片段和检查结果会发送给当前模型，常见凭据字段会脱敏。")}</p></div></details></div></div>
    <details className="chat-configuration"><summary><Settings2 size={14}/><span>{engineName(engine)}{engine==='deepagents'&&model?' · '+model:''}</span><small>{t('模型与上下文','Model and context')}</small><ChevronDown size={13}/></summary><div>
      <AssistantEnginePicker value={engine} onChange={setEngine} disabled={!!busy||!!chat?.active_run}/>{engine==='deepagents'&&<AgentProfilePicker onChange={value=>setProfileId(value.active_id)}/>}
      {engine==='codex'&&<CodexHost value={draftCodex??codexOptions} onChange={value=>{if(draftCodex)setDraftCodex(value);else setCodexOptions(value)}} disabled={!!busy||!!chat?.active_run}/>}
      {engine==='deepagents'&&<ContextUsageMeter chat={chat} model={model}/>}
    </div></details>
    {error&&<div className="assistant-error" role="alert">{error}</div>}
    <div ref={transcript} className="chat-transcript" aria-label={ui("对话消息")} aria-live="polite" onScroll={()=>{if(transcript.current)follow.current=shouldFollowChat(transcript.current)}}>
      {!chat?.turns.length&&<div className="chat-welcome"><span><Sparkles size={27}/></span><h3>{ui("你希望完成什么？")}</h3><p>{ui("检查资源、整理文件、预约机器或设置监控，直接描述你想完成的事情。")}</p><div>{suggestions.map(item=><button key={item} disabled={!!busy} onClick={()=>setText(ui(item))}>{ui(item)}</button>)}</div></div>}
      {chat?.turns.map(turn=><article key={turn.id} className={'chat-turn '+turn.role} aria-label={turn.role==='user'?ui("用户消息"):ui("助手消息")}><div className="chat-turn-label">{turn.role==='user'?ui("你"):ui("AI 助手")}{turn.role==='assistant'&&turn.model&&<small title={turn.profile_name}>{turn.model}</small>}{turn.resource_view&&<small>{t('资源视图 · 只读','Resource view · Read only')}</small>}{turn.a2ui_prototype&&<small>{t('A2UI 原型 · 模拟数据','A2UI prototype · synthetic data')}</small>}{turn.role==='assistant'&&<ReplyTimestamp created={turn.created}/ >}{turn.elapsed_ms!==undefined&&<small>{(turn.elapsed_ms/1000).toFixed(1)} {ui(" 秒")}</small>}</div><div className="chat-turn-body">{turn.context_compaction&&<div className="chat-compaction" role="status">{turn.context_compaction.status==='running'?<LoaderCircle size={14} className="spin"/>:turn.context_compaction.status==='completed'?<Check size={14}/>:<TriangleAlert size={14}/>}<span>{turn.context_compaction.status==='running'?ui("正在压缩上下文…"):turn.context_compaction.status==='completed'?ui("前面的上下文已压缩"):ui("上下文压缩未完成")}</span><small>{turn.context_compaction.status==='completed'?ui("后续使用摘要和近期消息，本地聊天记录保留"):turn.context_compaction.status==='running'?ui("正在整理早期内容，完成后继续回复"):ui("请查看本轮处理结果后重试")}</small></div>}{!!turn.selected_skill_names?.length&&<div className="chat-skill-receipt">{ui("本轮指定技能：")}{turn.selected_skill_names.map(name=>`@${name}`).join('、')}</div>}{!!turn.skills_read?.length&&<div className="chat-skill-receipt">{ui("已读取技能：")}{turn.skills_read.map(skill=>`${skill.name} · v${skill.version}`).join('、')}</div>}<ExecutionSteps turn={turn} chatId={chat!.id}/>{!!turn.terminal_attachments?.length&&<div>{turn.terminal_attachments.map((item,index)=><details key={index}><summary>{t('终端附件','Terminal attachment')} · {item.label}{item.truncated?t(' · 已截断',' · Truncated'):''}</summary><small>{item.host_id} · {item.terminal_id} · {item.cwd||t('目录未知','Unknown directory')} · {item.captured_at}</small><pre>{item.content}</pre></details>)}</div>}{turn.supplemental_instructions?.map((instruction,index)=><div className="chat-supplement-receipt" key={index}><small>{t("已发送补充指令","Supplemental instruction sent")} · {new Date(instruction.created*1000).toLocaleTimeString()}</small><div>{instruction.content}</div></div>)}{turn.codex_questions?.map(question=><CodexQuestionForm key={question.id} request={question} chatId={chat!.id} activeRun={chat!.active_run} onUpdate={value=>{if(current.current===value.id)apply(value)}}/>)}{turn.approvals?.map(approval=><ApprovalCard key={approval.id} approval={approval} chatId={chat!.id} activeRun={chat!.active_run} onUpdate={value=>{if(current.current===value.id)apply(value)}}/>)}{turn.content&&<div className={"chat-message-text"+(turn.status==='running'?' streaming':'')}>{turn.role==='assistant'?<ChatMarkdown streaming={turn.status==='running'}>{turn.error_code==='codex_new_chat_required'?ui(turn.content):turn.content}</ChatMarkdown>:turn.content}</div>}{turn.a2ui&&<React.Suspense fallback={null}><AssistantA2ui message={turn.a2ui}/></React.Suspense>}{turn.a2ui_rejected&&<small className="chat-incomplete">{t('生成的界面未通过校验。','The generated interface did not pass validation.')}</small>}{turn.status==='running'&&turn.provider_status&&<small role="status">{turn.provider_status}</small>}{turn.status==='running'&&<div className="chat-working"><span className="chat-stream-dot"/>{turn.tools?.some(tool=>tool.status==='running')?ui("正在执行工具…"):turn.content?ui("正在接收回复…"):ui("正在分析或整理结果…")}</div>}{turn.status&&['failed','limited','cancelled','interrupted'].includes(turn.status)&&<small className="chat-incomplete">{turn.status==='cancelled'?ui("已取消"):turn.status==='interrupted'?ui("上次处理已中断"):turn.status==='limited'?ui("已达本轮步骤上限"):ui("本轮未完成")}</small>}</div></article>)}
    </div>
    <form className="chat-composer" onSubmit={send}>{draftScope&&<div className="chat-supplement-receipt" role="status">{draftScope.restrict_to_selected?t("沿用分支机器范围：","Restored branch machine scope: ")+ (draftScope.selected_host_ids.join(", ")||t("未选择机器","No machines selected")):t("沿用分支范围：允许操作全部已添加机器","Restored branch scope: all added machines")}<button type="button" disabled={!!busy||running} onClick={()=>setDraftScope(null)}>{t("改用当前机器选择与范围","Use current machine selection and scope")}</button></div>}<details className="chat-context"><summary><Server size={13}/><span>{scopeRestricted?t(`操作范围：所选 ${scopeHostIds.length} 台机器`,`Scope: ${scopeHostIds.length} selected machines`):t(`当前上下文：${scopeHostIds.length?`选中 ${scopeHostIds.length} 台机器`:ui("未选择机器")}`,`Context: ${scopeHostIds.length?`${scopeHostIds.length} machines selected`:ui("未选择机器")}`)}</span><Settings2 size={13}/>{ui("调整")}</summary><div className="chat-scope"><label><input type="checkbox" checked={scopeRestricted} disabled={!!busy||running||!!draftScope} onChange={event=>setRestricted(event.target.checked)}/>{ui("仅允许操作所选的 ")}{scopeHostIds.length} {ui(" 台机器")}</label><span>{engine==='codex'?t('机器选择仅约束工作台 MCP；原生 Shell 可越过此范围执行 ssh 或访问本机凭据。','Machine selection constrains workbench MCP only; native Shell can run ssh or access local credentials beyond this scope.'):scopeRestricted?ui("工具操作限于所选范围"):ui("可操作全部已添加机器；选择机器不会自动限制操作范围")}</span></div></details>{attachments.map((item,index)=><details key={index}><summary>{t('终端附件','Terminal attachment')} · {item.label} · {item.source==='selection'?t('选区','Selection'):t('当前屏幕','Visible screen')}{item.truncated?t(' · 已截断',' · Truncated'):''}</summary><small>{item.host_id} · {t("标签","Tab")} {item.terminal_id} · {t("会话","Session")} {item.session_id||t('临时','Temporary')} · {item.cwd||t('目录未知','Unknown directory')} · {item.captured_at}</small><pre>{item.content}</pre><button type="button" onClick={()=>setAttachments(old=>old.filter((_,i)=>i!==index))}>{t('移除附件','Remove attachment')}</button></details>)}
      <SkillMessageInput text={text} onChange={setText} skills={resourceView?[]:skills} selected={selectedSkills} onSelect={setSelectedSkills}
        disabled={!!busy||(running&&!canSteer)} readOnly={steering} supplemental={canSteer} error={skillError} onSend={send}/>
      <div className="chat-composer-bottom">
        <div className="chat-composer-settings">
          {!resourceView&&<AgentPermissions codex={engine==='codex'} existingCodexChat={chat?.engine==='codex'&&!!chat.turns.length}
            mode={runMode??permissionMode} onMode={setPermissionMode}
            localRoots={localRoots} onLocalRoots={setLocalRoots} remoteRoots={remoteRoots} onRemoteRoots={setRemoteRoots}
            externalMcp={externalMcp} onExternalMcp={setExternalMcp} hostCount={scopeHostIds.length}
            disabled={!!busy||running} running={running} restoredScope={draftPermissions} onUseDefaults={()=>setDraftPermissions(null)}/>}
          {engine==='deepagents'&&<button type="button" className="chat-resource-view" aria-pressed={resourceView}
            disabled={!!busy||running||(!resourceView&&hasExtraContext)}
            title={t('读取当前机器范围内已有的设备和占卡进程采样','Read existing device and accelerator process samples within the current machine scope')}
            onClick={()=>setResourceViewEnabled(value=>!value)}>{resourceView?t('资源视图 · 只读','Resource view · Read only'):t('资源视图','Resource view')}</button>}
          {engine==='deepagents'?<ChatModelPicker model={model} openSettings={openSettings}/>:<small>{engineName(engine)} · {engine==='codex'?(draftCodex??codexOptions).model||t('CLI 默认模型','CLI default model'):t('本机默认模型','Local default model')}</small>}
        </div>
        <div className="chat-composer-actions">
          {running&&<button type="button" className="secondary" disabled={!!busy} onClick={()=>act('cancel',async (signal,isCurrent)=>{
            const value=await chatRequest<Chat>('/'+chat!.id+'/cancel','POST',{run_id:chat!.active_run},signal);
            if(isCurrent()&&current.current===value.id)apply(value);
          })}><Square size={13}/>{ui("取消本轮")}</button>}
          {(!running||canSteer)&&<button type="submit" className="primary" disabled={!canSend}>
            {busy==='send'||steering?<LoaderCircle size={15} className="spin"/>:<Send size={15}/>}
            <span className="chat-send-label">{canSteer?t('发送补充指令','Send supplemental instruction'):ui("发送")}</span>
          </button>}
        </div>
      </div>
      {resourceView&&hasExtraContext&&<small className="chat-shortcut" role="status">{t('资源视图只读取设备和占卡进程。请移除附件或指定技能后发送。','Resource view reads device and accelerator process data. Remove attachments or selected skills to send.')}</small>}
      {running&&!canSteer
        ?<small className="chat-shortcut chat-steer-unavailable">{t(`当前 ${engineName(chat?.engine)} 引擎不支持运行中补充指令。`,`${engineName(chat?.engine)} does not support supplemental instructions during a run.`)}</small>
        :<span className="chat-shortcut">{ui("Enter 发送 · Shift + Enter 换行")}</span>}
    </form>
    {confirmation}
  </section>;
}

function ExecutionSteps({turn,chatId}:{turn:ChatTurn;chatId:string}){
  const tools=turn.tools??[];
  const codexItems=(turn.codex_items??[]).filter(isVisibleCodexItem);
  const count=tools.length+codexItems.length;
  if(!count)return null;

  const running=tools.some(tool=>tool.status==='running')||codexItems.some(item=>item.status==='running'||item.status==='inProgress');
  const warning=tools.some(tool=>['failed','warning'].includes(toolPresentation(tool).status))||codexItems.some(item=>item.status==='failed');
  return <details className="chat-execution">
    <summary>
      <span>{running?<LoaderCircle size={14} className="spin"/>:warning?<TriangleAlert size={14}/>:<Check size={14}/>} {ui("执行步骤")}</span>
      <small>{running?ui("执行中 · "):''}{count} {ui(" 步")}</small>
      <ChevronDown size={13}/>
    </summary>
    <div className="chat-tool-list">
      {tools.map(tool=><ToolTrace key={tool.id} tool={tool}/>)}
      {!!codexItems.length&&<CodexItems items={codexItems} chatId={chatId} runId={turn.id}/>}
    </div>
  </details>;
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
