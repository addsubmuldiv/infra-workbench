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
import {ChatMenuButton} from './ChatMenuButton';
import {ChatBorderBeam} from './ChatBorderBeam';
import {workspaceStorage} from '../../workspace/workspaceState';
import {useWorkspaceValue} from '../../workspace/workspaceHooks';
import React,{useEffect,useId,useLayoutEffect,useRef,useState} from 'react';
import {Activity,ArrowDown,ArrowUpRight,Check,Settings2,Sparkles,Server,TriangleAlert,ChevronDown,Ellipsis,GitBranch,LoaderCircle,Pencil,Plus,Send,Square,Trash2,FileText,Bell,Paperclip,X} from 'lucide-react';
import {assistantEngineName as engineName,chatReplyTime,applyChatEvent,chatRequest,isVisibleCodexItem,loadChatId,saveChatId,shouldFollowChat,watchChat,toolNames,toolPresentation,type Chat,type ChatItem,type ChatTool,type ChatTurn} from './agentChat';
import {useAppConfirm} from '../../shared/AppConfirm';
import {ModalDialog} from '../../shared/ModalDialog';
import type {AssistantStatus} from './infraAssistant';
import './agentChat.css';
import {OverlayScrollbar} from '../../shared/OverlayScrollbar';
import {ChatMarkdown} from './ChatMarkdown';
import {installedSkill,skillRequest,type SkillMeta} from './skills';
import './skills.css';
import {SkillMessageInput} from './SkillMessageInput';

const AssistantA2ui=React.lazy(()=>import('./AssistantA2ui'));

const suggestions=[
  {icon:Server,prompt:'检查可用资源和运行中的服务'},
  {icon:FileText,prompt:'分析训练日志并找出异常'},
  {icon:Bell,prompt:'帮我设置资源监控'},
];
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

export function AssistantChat({status,statusError,selectedHostIds,openSettings}:{status:AssistantStatus|null;statusError:string;selectedHostIds:string[];openSettings:()=>void}){
  const model=status?.model;
  const [configurationOpen,setConfigurationOpen]=useState(false),[scopeOpen,setScopeOpen]=useState(false);
  const [awayFromLatest,setAwayFromLatest]=useState(false);
  const configurationId=useId(),scopeId=useId(),sendHintId=useId();
  const renameId=useId();
  const [renameDraft,setRenameDraft]=useState<{chatId:string;title:string;error?:string}|null>(null);
  const configurationTrigger=useRef<HTMLButtonElement>(null),configurationPanel=useRef<HTMLDivElement>(null);
  const composerInput=useRef<HTMLTextAreaElement>(null);
  const focusComposerOnIdle=useRef(false);
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
      setRenameDraft(null);
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
    if(view&&follow.current)view.scrollTop=chat?.turns.length?view.scrollHeight:0;
    if(view)setAwayFromLatest(!shouldFollowChat(view));
  },[chat]);
  const jumpToLatest=()=>{
    const view=transcript.current;
    if(!view)return;
    follow.current=true;
    view.scrollTop=view.scrollHeight;
    view.focus({preventScroll:true});
    setAwayFromLatest(false);
  };
  useLayoutEffect(()=>{
    if(configurationOpen)configurationPanel.current?.focus({preventScroll:true});
  },[configurationOpen]);
  useLayoutEffect(()=>{
    if(busy||!focusComposerOnIdle.current)return;
    focusComposerOnIdle.current=false;
    composerInput.current?.focus({preventScroll:true});
  },[busy]);
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
  const needsModel=!running&&engine==='deepagents'&&!status?.configured;
  const modelWarning=!running&&engine==='deepagents'&&(statusError||status?.credential_error);
  const emptyScope=!running&&scopeRestricted&&!scopeHostIds.length;
  const incompatibleContext=resourceView&&hasExtraContext;
  const canSend=!!text.trim()&&!busy&&!steering&&!incompatibleContext&&(running?canSteer:!needsModel&&!emptyScope);
  const settingsLocked=!!busy||running;
  const assistantLabel=[engine==='deepagents'?t('内置助手','Built-in assistant'):engineName(engine),engine==='deepagents'?model:engine==='codex'?(draftCodex??codexOptions).model:''].filter(Boolean).join(' · ');
  const scopeLabel=scopeRestricted?t(`仅限所选 ${scopeHostIds.length} 台`,`Selected machines (${scopeHostIds.length})`):t('全部机器','All machines');
  const dismissConfiguration=()=>{setConfigurationOpen(false);configurationTrigger.current?.focus({preventScroll:true})};

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
  const newChat=()=>act('new',async (signal,isCurrent)=>{
    subscription.current?.abort();current.current=null;
    const value=await chatRequest<Chat>('','POST',{},signal);
    if(isCurrent()){apply(value);setConfigurationOpen(false);focusComposerOnIdle.current=true}
  });
  const switchChat=(id:string)=>act('switch',async (signal,isCurrent)=>{subscription.current?.abort();current.current=null;const value=await chatRequest<Chat>('/'+id,'GET',undefined,signal);if(isCurrent())apply(value)});
  const branch=()=>{
    if(!chat||chat.active_run)return;
    const source=chat.id;
    return act('branch',async (signal,isCurrent)=>{
      const value=await chatRequest<{chat:Chat;draft:ChatDraft}>('/'+source+'/branch','POST',{},signal);
      if(!isCurrent()||current.current!==source)return;
      subscription.current?.abort();apply({...value.chat,draft:value.draft});setConfigurationOpen(false);focusComposerOnIdle.current=true;
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
  const saveTitle=(event:React.FormEvent)=>{
    event.preventDefault();
    const title=renameDraft?.title.trim();
    if(!renameDraft||!title||current.current!==renameDraft.chatId)return;
    const id=renameDraft.chatId;
    return act('rename',async (signal,isCurrent)=>{
      try{
        const value=await chatRequest<Chat>('/'+id,'PATCH',{title},signal);
        if(isCurrent()&&current.current===id){apply(value);setRenameDraft(null)}
      }catch(e){
        if(isCurrent())setRenameDraft(previous=>previous?.chatId===id?{...previous,error:e instanceof Error?ui(e.message):t('无法保存对话名称','Could not save the conversation name')}:previous);
      }
    });
  };
  return <section className="agent-chat" aria-label={ui("AI 工作台对话")}>
    <div className="chat-toolbar">
      <ChatSessionPicker items={items} value={chat?.id||''} disabled={!!busy} onChange={switchChat}/>
      <div className="chat-toolbar-actions">
        <button type="button" className="chat-control chat-new" disabled={!!busy} onClick={newChat}>
          <Plus size={16} aria-hidden="true"/>{ui("新对话")}
        </button>
        <button ref={configurationTrigger} type="button" className="chat-control chat-configuration-trigger"
          aria-label={t('引擎与模型','Engine and model')+' · '+assistantLabel}
          title={t('引擎与模型','Engine and model')+' · '+assistantLabel}
          aria-expanded={configurationOpen} aria-controls={configurationOpen?configurationId:undefined}
          onClick={()=>setConfigurationOpen(value=>!value)}>
          <Settings2 size={16} aria-hidden="true"/><span>{assistantLabel}</span>
        </button>
        <ChatMenuButton label={ui("对话选项")} triggerClassName="chat-control chat-more-trigger"
          actions={[
            {label:t('重命名对话','Rename conversation'),icon:<Pencil size={15}/>,disabled:!!busy||!chat,
              onSelect:()=>{if(chat)setRenameDraft({chatId:chat.id,title:chat.title})}},
            {label:t('编辑上一条消息并新建分支','Edit last message in a new branch'),icon:<GitBranch size={15}/>,
              description:t('保留原对话和已执行的操作。','Keeps the original conversation and completed actions.'),
              disabled:settingsLocked||!chat?.turns.some(turn=>turn.role==='user'),onSelect:branch},
            {label:ui('删除当前对话'),icon:<Trash2 size={15}/>,danger:true,disabled:settingsLocked||!chat,onSelect:remove},
          ]}>
          <Ellipsis size={17} aria-hidden="true"/>
        </ChatMenuButton>
      </div>
    </div>
    {error&&<div className="assistant-error" role="alert">{error}</div>}
    <div className="chat-transcript-frame">
    <div hidden={!configurationOpen} className="chat-configuration" id={configurationId} ref={configurationPanel} tabIndex={-1} role="region"
      aria-label={t('引擎与模型','Engine and model')} onKeyDown={event=>{if(event.key==='Escape'){event.stopPropagation();dismissConfiguration()}}}>
      <div className="chat-configuration-heading">
        <strong>{t('引擎与模型','Engine and model')}</strong>
        <button type="button" className="chat-control" aria-label={t('收起引擎设置','Close engine settings')} onClick={dismissConfiguration}><X size={15}/></button>
      </div>
      {running&&<p className="chat-configuration-note">{t('当前任务结束后可以更改引擎与模型。','Engine and model can be changed when this run ends.')}</p>}
      <AssistantEnginePicker value={engine} onChange={setEngine} disabled={settingsLocked}/>
      {engine==='deepagents'&&<>
        <AgentProfilePicker disabled={settingsLocked} onChange={value=>setProfileId(value.active_id)}/>
        <div className="chat-model-row"><span>{t('模型','Model')}</span><ChatModelPicker model={model} disabled={settingsLocked}/></div>
        {model&&<ContextUsageMeter chat={chat} model={model}/>}
        <button type="button" className="chat-text-action" onClick={()=>{setConfigurationOpen(false);openSettings()}}>
          {ui('打开模型设置')}<ArrowUpRight size={14} aria-hidden="true"/>
        </button>
      </>}
      {engine==='codex'&&<CodexHost value={draftCodex??codexOptions} onChange={value=>{if(draftCodex)setDraftCodex(value);else setCodexOptions(value)}} disabled={settingsLocked}/>}
    </div>
      <div ref={transcript} className="chat-transcript" tabIndex={0} aria-label={ui("对话消息")} onScroll={()=>{
        if(!transcript.current)return;
        follow.current=shouldFollowChat(transcript.current);
        setAwayFromLatest(!follow.current);
      }}>
      {busy==='load'||busy==='switch'?<div className="chat-loading" role="status"><LoaderCircle size={17} className="spin"/>{t('正在打开对话…','Opening conversation…')}</div>:
        !chat?.turns.length&&<div className="chat-welcome">
          <span className="chat-welcome-icon"><Sparkles size={21} aria-hidden="true"/></span>
          <h3>{t('今天要检查什么？','What are you working on?')}</h3>
          <p>{t('直接输入问题，或选一个示例开始。','Write a question or start with a suggestion.')}</p>
          <div className="chat-suggestions">{suggestions.map(({icon:Icon,prompt})=><button key={prompt} type="button" disabled={!!busy}
            onClick={()=>{const example=ui(prompt);setText(old=>old.trim()?(old+'\n'+example).slice(0,4000):example);composerInput.current?.focus()}}>
            <Icon size={15} aria-hidden="true"/><span>{ui(prompt)}</span><ArrowUpRight size={14} aria-hidden="true"/>
          </button>)}</div>
        </div>}
      {busy!=='switch'&&chat?.turns.map(turn=>{
        const isAssistant=turn.role==='assistant';
        const isRunning=turn.status==='running';
        const needsApproval=turn.approvals?.some(approval=>approval.status==='pending');
        const needsAnswer=turn.codex_questions?.some(question=>question.status==='pending');
        const activity=needsApproval?t('等待你批准操作','Waiting for your approval'):
          needsAnswer?t('等待你回答问题','Waiting for your answer'):
          (turn.tools?.some(tool=>tool.status==='running')||turn.codex_items?.some(item=>isVisibleCodexItem(item)&&(item.status==='running'||item.status==='inProgress')))?ui('正在执行工具…'):
          turn.content?ui('正在接收回复…'):ui('正在分析或整理结果…');
        return <article key={turn.id} className={'chat-turn '+turn.role} aria-label={isAssistant?ui('助手消息'):ui('用户消息')}>
          <div className="chat-turn-label">
            <strong>{isAssistant?ui('AI 助手'):ui('你')}</strong>
            {isAssistant&&turn.model&&<small title={turn.profile_name}>{turn.model}</small>}
            {turn.resource_view&&<small>{t('资源视图 · 只读','Resource view · Read only')}</small>}
            {turn.a2ui_prototype&&<small>{t('A2UI 原型 · 模拟数据','A2UI prototype · synthetic data')}</small>}
            {isAssistant&&<ReplyTimestamp created={turn.created}/>}
            {turn.elapsed_ms!==undefined&&<small>{(turn.elapsed_ms/1000).toFixed(1)} {ui(' 秒')}</small>}
          </div>
          <div className="chat-turn-body">
            {turn.context_compaction&&<div className="chat-compaction" role="status">
              {turn.context_compaction.status==='running'?<LoaderCircle size={14} className="spin"/>:turn.context_compaction.status==='completed'?<Check size={14}/>:<TriangleAlert size={14}/>}
              <span>{turn.context_compaction.status==='running'?ui('正在压缩上下文…'):turn.context_compaction.status==='completed'?ui('前面的上下文已压缩'):ui('上下文压缩未完成')}</span>
              <small>{turn.context_compaction.status==='completed'?ui('后续使用摘要和近期消息，本地聊天记录保留'):turn.context_compaction.status==='running'?ui('正在整理早期内容，完成后继续回复'):ui('请查看本轮处理结果后重试')}</small>
            </div>}
            {!!turn.selected_skill_names?.length&&<div className="chat-skill-receipt">{ui('本轮指定技能：')}{turn.selected_skill_names.map(name=>'@'+name).join('、')}</div>}
            {!!turn.skills_read?.length&&<div className="chat-skill-receipt">{ui('已读取技能：')}{turn.skills_read.map(skill=>skill.name+' · v'+skill.version).join('、')}</div>}
            <ExecutionSteps turn={turn} chatId={chat.id}/>
            {!!turn.terminal_attachments?.length&&<div>{turn.terminal_attachments.map((item,index)=><details key={index}>
              <summary>{t('终端附件','Terminal attachment')} · {item.label}{item.truncated?t(' · 已截断',' · Truncated'):''}</summary>
              <small>{item.host_id} · {item.terminal_id} · {item.cwd||t('目录未知','Unknown directory')} · {item.captured_at}</small>
              <pre>{item.content}</pre>
            </details>)}</div>}
            {turn.supplemental_instructions?.map((instruction,index)=><div className="chat-supplement-receipt" key={index}>
              <small>{t('已发送补充指令','Supplemental instruction sent')} · {new Date(instruction.created*1000).toLocaleTimeString()}</small>
              <div>{instruction.content}</div>
            </div>)}
            {turn.codex_questions?.map(question=><CodexQuestionForm key={question.id} request={question} chatId={chat.id} activeRun={chat.active_run} onUpdate={value=>{if(current.current===value.id)apply(value)}}/>)}
            {turn.approvals?.map(approval=><ApprovalCard key={approval.id} approval={approval} chatId={chat.id} activeRun={chat.active_run} onUpdate={value=>{if(current.current===value.id)apply(value)}}/>)}
            {turn.content&&<div className={'chat-message-text'+(isRunning?' streaming':'')}>
              {isAssistant?<ChatMarkdown streaming={isRunning}>{turn.error_code==='codex_new_chat_required'?ui(turn.content):turn.content}</ChatMarkdown>:turn.content}
            </div>}
            {turn.a2ui&&<React.Suspense fallback={null}><AssistantA2ui message={turn.a2ui}/></React.Suspense>}
            {turn.a2ui_rejected&&<small className="chat-incomplete">{t('生成的界面未通过校验。','The generated interface did not pass validation.')}</small>}
            {isRunning&&turn.provider_status&&<small role="status">{turn.provider_status}</small>}
            {isRunning&&<div className="chat-working" role="status"><span className="chat-stream-dot" aria-hidden="true"/>{activity}</div>}
            {turn.status&&['failed','limited','cancelled','interrupted'].includes(turn.status)&&<small role="status" className="chat-incomplete">
              {turn.status==='cancelled'?ui('已取消'):turn.status==='interrupted'?ui('上次处理已中断'):turn.status==='limited'?ui('已达本轮步骤上限'):ui('本轮未完成')}
            </small>}
          </div>
        </article>;
      })}
      </div>
      <OverlayScrollbar scrollRef={transcript}/>
      {!!chat?.turns.length&&awayFromLatest&&<button type="button" className="chat-jump-latest" onClick={jumpToLatest}>
        <ArrowDown size={15} aria-hidden="true"/>{t('回到最新消息','Jump to latest')}
      </button>}
    </div>
    <form className="chat-composer" onSubmit={send}>
      {(needsModel||modelWarning)&&<div className="chat-setup">
        <span role="status">{modelWarning?ui(modelWarning):status?t('配置模型后即可发送。也可以切换到本机 CLI。','Configure a model or switch to a local CLI to send messages.'):t('正在读取模型配置…','Checking model configuration…')}</span>
        {(status||statusError)&&<button type="button" className="chat-text-action" onClick={openSettings}>{t('配置模型','Configure model')}<ArrowUpRight size={13} aria-hidden="true"/></button>}
      </div>}
      <div className="chat-input-box" data-generating={running||busy==='send'||undefined}>
        <ChatBorderBeam/>
        {!!attachments.length&&<div className="chat-attachments">{attachments.map((item,index)=><div className="chat-attachment" key={index}>
          <details><summary><Paperclip size={14} aria-hidden="true"/><span>{item.label}</span><ChevronDown size={13} aria-hidden="true"/></summary>
            <small>{item.host_id} · {t('标签','Tab')} {item.terminal_id} · {t('会话','Session')} {item.session_id||t('临时','Temporary')} · {item.cwd||t('目录未知','Unknown directory')} · {item.captured_at} · {item.source==='selection'?t('选区','Selection'):t('当前屏幕','Visible screen')}{item.truncated?t(' · 已截断',' · Truncated'):''}</small>
            <pre>{item.content}</pre>
          </details>
          <button type="button" className="chat-control" aria-label={t('移除附件','Remove attachment')+' · '+item.label}
            onClick={()=>setAttachments(old=>old.filter((_,i)=>i!==index))}><X size={15}/></button>
        </div>)}</div>}
        <SkillMessageInput input={composerInput} text={text} onChange={setText} skills={resourceView?[]:skills} selected={selectedSkills} onSelect={setSelectedSkills}
          disabled={!!busy||(running&&!canSteer)} readOnly={steering} supplemental={canSteer} error={skillError} onSend={send}/>
        <div className="chat-composer-bottom">
          <div className="chat-composer-settings">
            <button type="button" className="chat-control" aria-haspopup="dialog"
              aria-label={t('机器范围','Machine scope')+' · '+scopeLabel} onClick={()=>setScopeOpen(true)}>
              <Server size={14} aria-hidden="true"/><span>{scopeLabel}</span><ChevronDown size={12} aria-hidden="true"/>
            </button>
            {!resourceView&&<AgentPermissions codex={engine==='codex'} existingCodexChat={chat?.engine==='codex'&&!!chat.turns.length}
              mode={runMode??permissionMode} onMode={setPermissionMode}
              localRoots={localRoots} onLocalRoots={setLocalRoots} remoteRoots={remoteRoots} onRemoteRoots={setRemoteRoots}
              externalMcp={externalMcp} onExternalMcp={setExternalMcp} hostCount={scopeHostIds.length}
              disabled={settingsLocked} running={running} restoredScope={draftPermissions} onUseDefaults={()=>setDraftPermissions(null)}/>}
            {engine==='deepagents'&&<button type="button" className="chat-control chat-resource-view" aria-pressed={resourceView}
              disabled={settingsLocked} title={t('读取当前机器范围内已有的设备和占卡进程采样','Read existing device and accelerator process samples within the current machine scope')}
              onClick={()=>setResourceViewEnabled(value=>!value)}><Activity size={14} aria-hidden="true"/><span>{resourceView?t('资源视图 · 只读','Resource view · Read only'):t('资源视图','Resource view')}</span></button>}
          </div>
          <div className="chat-composer-actions">
            {running&&<button type="button" className="secondary" disabled={!!busy} onClick={()=>act('cancel',async (signal,isCurrent)=>{
              const value=await chatRequest<Chat>('/'+chat!.id+'/cancel','POST',{run_id:chat!.active_run},signal);
              if(isCurrent()&&current.current===value.id)apply(value);
            })}><Square size={13}/>{ui("取消本轮")}</button>}
            {(!running||canSteer)&&<button type="submit" className="primary" disabled={!canSend} aria-describedby={sendHintId}
              title={canSteer?t('发送补充指令','Send supplemental instruction'):ui('发送')}
              aria-label={canSteer?t('发送补充指令','Send supplemental instruction'):ui('发送')}>
              {busy==='send'||steering?<LoaderCircle size={15} className="spin"/>:<Send size={15}/>}
            </button>}
          </div>
        </div>
      </div>
      <div id={sendHintId} className="chat-composer-hint">
        {incompatibleContext?<span role="status">{t('资源视图只读取设备和占卡进程。发送前请移除附件和技能，或关闭资源视图。','Resource view reads only devices and accelerator processes. Remove attachments and skills or turn off resource view to send.')}</span>:
          emptyScope?<span role="status">{t('请先选一台机器，或在机器范围中切换到全部机器。','Select a machine or switch to all machines before sending.')}</span>:
          running&&!canSteer?<span role="status" className="chat-steer-unavailable">{t(`${engineName(chat?.engine)} 正在回复，结束后可以继续发送。`,`${engineName(chat?.engine)} is responding. You can send another message when it finishes.`)}</span>:
          <span className="chat-shortcut">{ui("Enter 发送 · Shift + Enter 换行")}{!resourceView&&!running&&' · '+t('@ 选技能','@ for skills')}</span>}
      </div>
    </form>
    {scopeOpen&&<ModalDialog className="chat-scope-dialog" labelledBy={scopeId} onDismiss={()=>setScopeOpen(false)}>
      <h2 id={scopeId}>{t('机器范围','Machine scope')}</h2>
      <p>{scopeHostIds.length?t('当前选中 '+scopeHostIds.length+' 台机器。',scopeHostIds.length+' machines selected.') :t('工作台还未选中机器。','No machines are selected in Workbench.')}</p>
      {draftScope?<><p role="status">{t('这条草稿沿用分支的机器范围。','This draft uses the machine scope from its branch.')}{scopeRestricted&&scopeHostIds.length>0&&' '+scopeHostIds.join(', ')}</p>
        <button type="button" className="secondary" disabled={settingsLocked} onClick={()=>setDraftScope(null)}>{t('改用当前机器选择与范围','Use current machine selection and scope')}</button></>:
        <fieldset disabled={settingsLocked}>
          <legend className="chat-sr-only">{t('机器范围','Machine scope')}</legend>
          <label><input type="radio" name={scopeId} checked={!scopeRestricted} onChange={()=>setRestricted(false)}/><span>{t('全部已添加的机器','All added machines')}</span></label>
          <label><input type="radio" name={scopeId} checked={scopeRestricted} onChange={()=>setRestricted(true)}/><span>{t('仅限工作台所选机器','Only machines selected in Workbench')}</span></label>
        </fieldset>}
      {engine==='codex'&&<p>{t('机器范围仅约束工作台 MCP。Codex 原生 Shell 仍可自行连接其他机器。','Machine scope limits Workbench MCP only. The native Codex shell can connect to other machines independently.')}</p>}
      <footer><button type="button" className="primary" data-dialog-focus onClick={()=>setScopeOpen(false)}>{t('完成','Done')}</button></footer>
    </ModalDialog>}
    {renameDraft&&renameDraft.chatId===chat?.id&&<ModalDialog className="chat-rename-dialog" labelledBy={renameId}
      onDismiss={()=>{if(busy!=='rename')setRenameDraft(null)}}>
      <form onSubmit={saveTitle}>
        <h2 id={renameId}>{t('重命名对话','Rename conversation')}</h2>
        <label>{t('对话名称','Conversation name')}
          <input type="text" maxLength={120} required data-dialog-focus value={renameDraft.title} readOnly={busy==='rename'}
            onFocus={event=>event.currentTarget.select()}
            onChange={event=>setRenameDraft({...renameDraft,title:event.target.value,error:undefined})}/>
        </label>
        {renameDraft.error&&<p role="alert">{renameDraft.error}</p>}
        <footer>
          <button type="button" className="secondary" disabled={busy==='rename'} onClick={()=>setRenameDraft(null)}>{t('取消','Cancel')}</button>
          <button type="submit" className="primary" disabled={!renameDraft.title.trim()||!!busy}>{busy==='rename'?t('保存中…','Saving…'):t('保存','Save')}</button>
        </footer>
      </form>
    </ModalDialog>}
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
