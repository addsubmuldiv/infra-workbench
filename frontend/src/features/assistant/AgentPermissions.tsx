import {useId,useRef,useState} from 'react';
import {ChevronDown,Settings2,Shield} from 'lucide-react';
import {t} from '../../shared/i18n';
import {chatRequest,type Chat,type ChatApproval,type PermissionMode,type PermissionScope} from './agentChat';
import {ChatMenuButton} from './ChatMenuButton';
import {ModalDialog} from '../../shared/ModalDialog';
import './agentPermissions.css';

type PermissionProps={
  codex?:boolean;
  existingCodexChat:boolean;
  mode:PermissionMode;
  onMode:(value:PermissionMode)=>void;
  localRoots:string;
  onLocalRoots:(value:string)=>void;
  remoteRoots:string;
  onRemoteRoots:(value:string)=>void;
  externalMcp:string;
  onExternalMcp:(value:string)=>void;
  hostCount:number;
  disabled:boolean;
  running:boolean;
  restoredScope?:PermissionScope|null;
  onUseDefaults:()=>void;
};

export function AgentPermissions({mode,onMode,localRoots,onLocalRoots,remoteRoots,onRemoteRoots,externalMcp,onExternalMcp,hostCount,disabled,running,restoredScope,onUseDefaults,codex=false,existingCodexChat}:PermissionProps){
  const [showSettings,setShowSettings]=useState(false);
  const titleId=useId();
  const label=t('权限模式','Permission mode');
  const options:Array<{id:PermissionMode;label:string;description:string}>=[
    {id:'ask',label:t('按需批准','Ask'),description:codex
      ?t('原生命令和文件变更按 CLI 策略请求批准。','Native commands and file changes follow CLI approval policy.')
      :t('访问新目录或执行命令时请求批准。','Asks before accessing a new directory or running commands.')},
    {id:'read_only',label:t('只读','Read only'),description:t('允许读取和查询，禁止写入和执行 Shell 命令。','Allows reads and queries. Blocks writes and shell commands.')},
    {id:'full',label:t('完全访问','Full access'),description:codex
      ?t('无需逐项批准。机器范围仅约束工作台 MCP。','Skips individual approvals. Machine scope limits workbench MCP only.')
      :t('按当前账号权限操作。所选机器范围仍有效。','Uses current account permissions within the selected machine scope.')},
  ];
  const currentMode=restoredScope?.permission_mode??mode;
  const modeLabel=options.find(option=>option.id===currentMode)?.label??options[0].label;
  const advancedLabel=t('高级权限设置','Advanced permissions');
  const codexNote=t('已有 Codex 对话沿用启动时的权限。更改后，请新建对话。','Existing Codex chats keep their startup permissions. Start a new chat after changing them.');
  const note=running?t('本轮运行中，权限设置暂不可修改。','Permission settings are locked while this turn runs.'):
    restoredScope?t('本条草稿沿用分支权限。','This draft uses the restored branch permissions.'):
    codex&&existingCodexChat?codexNote:undefined;

  return <>
    <ChatMenuButton label={label} triggerLabel={label+' · '+modeLabel}
      triggerClassName={'chat-permission-trigger'+(currentMode==='full'?' full':'')} menuClassName="chat-permission-menu"
      preferAbove value={currentMode} options={options.map(option=>({...option,disabled:disabled||!!restoredScope}))}
      description={note} onChange={id=>onMode(id as PermissionMode)}
      action={{label:advancedLabel,icon:<Settings2 size={14} aria-hidden="true"/>,onSelect:()=>setShowSettings(true)}}>
      <Shield size={14} aria-hidden="true"/><span>{modeLabel}</span><ChevronDown size={12} aria-hidden="true"/>
    </ChatMenuButton>
    {showSettings&&<ModalDialog className="agent-permissions-dialog" labelledBy={titleId} onDismiss={()=>setShowSettings(false)}>
      <h2 id={titleId}>{advancedLabel}</h2>
      {restoredScope?<>
        <p>{t('这条草稿已恢复分支的权限和工作目录。','This draft includes the permissions and directories restored from the branch.')}</p>
        <pre>{JSON.stringify({local_roots:restoredScope.local_roots,remote_roots:restoredScope.remote_roots,external_mcp_servers:restoredScope.external_mcp_servers},null,2)}</pre>
        <button type="button" className="secondary" disabled={disabled} onClick={onUseDefaults}>{t('改用当前权限设置','Use current permission settings')}</button>
      </>:<>
        <p>{t('可以为下一轮预先授权目录，或连接额外的 MCP 服务。','Preauthorize directories or connect additional MCP services for the next turn.')}</p>
        {note&&<small>{note}</small>}
        <label>
          {t('本机目录（每行一个绝对路径）','Local directories (one absolute path per line)')}
          <textarea rows={2} value={localRoots} readOnly={disabled} onChange={event=>onLocalRoots(event.target.value)} placeholder={String.raw`C:\projects\example`}/>
        </label>
        <label>
          {t(`服务器工作目录（对所选 ${hostCount} 台机器生效，每行一个绝对路径）`,`Server directories (for ${hostCount} selected machines, one absolute path per line)`)}
          <textarea rows={2} value={remoteRoots} readOnly={disabled} onChange={event=>onRemoteRoots(event.target.value)} placeholder="/home/user/project"/>
        </label>
        <label>
          {t('外部 MCP 服务（最多 3 个）','External MCP services (up to 3)')}
          <textarea rows={3} value={externalMcp} readOnly={disabled} onChange={event=>onExternalMcp(event.target.value)} placeholder="research https://example.com/mcp"/>
        </label>
        <small>{t('每行填写「名称 HTTP(S) 地址」。仅支持 Streamable HTTP，不支持 stdio 或密钥请求头。请只配置可信服务。按需批准模式会在连接前询问。只读模式仅允许服务明确标为只读的工具。','Enter “name HTTP(S) URL” on each line. Only Streamable HTTP is supported. Stdio and secret headers are unavailable. Use trusted services. Ask mode requests approval before connecting. Read only permits tools explicitly marked read only by the service.')}</small>
      </>}
      <footer><button type="button" className="primary" data-dialog-focus onClick={()=>setShowSettings(false)}>{t('完成','Done')}</button></footer>
    </ModalDialog>}
  </>;
}

export function ApprovalCard({approval,chatId,activeRun,onUpdate}:{approval:ChatApproval;chatId:string;activeRun:string|null;onUpdate:(chat:Chat)=>void}){
 const [submitting,setSubmitting]=useState(false),[error,setError]=useState('');const pending=useRef(false);
 const decide=async(decision:'approve'|'reject'|'session')=>{if(pending.current||approval.status!=='pending'||activeRun!==approval.run_id)return;pending.current=true;setSubmitting(true);setError('');try{onUpdate(await chatRequest<Chat>('/'+chatId+'/approvals/'+approval.id,'POST',{run_id:approval.run_id,decision}))}catch(error){setError(error instanceof Error?error.message:t('批准操作失败','Approval action failed'))}finally{pending.current=false;setSubmitting(false)}};
 const hasPath=!!(approval.arguments.path||approval.arguments.file_path||approval.arguments.cwd);
 const native=approval.tool.startsWith('codex_');
 const canGrantScope=approval.can_session!==false&&(native?approval.can_session===true:hasPath&&!approval.arguments.sudo&&(['local_read_file','local_list_files','local_write_file','local_edit_file','local_execute'].includes(approval.tool)||approval.tool==='execute_server_command'&&!!approval.arguments.cwd)&&(!approval.arguments.host_id||approval.tool==='execute_server_command'));
 const actionable=approval.status==='pending'&&activeRun===approval.run_id;
 return <section className="agent-approval" aria-label={t('工具操作批准','Tool approval')}><strong>{approval.tool}</strong><div>{approval.target||t('本地电脑','Local computer')}</div><p>{approval.reason}</p><pre>{JSON.stringify(approval.arguments,null,2)}</pre>{actionable&&canGrantScope&&approval.grant_path&&<small>{t('本次对话可授权的目录：','Directory available for this conversation: ')}{approval.grant_path}</small>}{actionable?<div className="agent-approval-actions"><button type="button" disabled={submitting} onClick={()=>void decide('approve')}>{t('允许一次','Allow once')}</button>{canGrantScope&&<button type="button" disabled={submitting} onClick={()=>void decide('session')}>{native?t('在本次 Codex 会话中允许','Allow for this Codex session'):['local_execute','execute_server_command','execute_cluster_command'].includes(approval.tool)?t('在本对话中允许此目录的 Shell 命令','Allow Shell commands in this directory for this conversation'):approval.grant_kind==='read'?t('本对话允许读取此目录','Allow reads in this directory for this conversation'):approval.grant_kind==='write'?t('本对话允许写入和编辑此目录','Allow writes and edits in this directory for this conversation'):t('本对话允许此工具访问该目录','Allow this tool in this directory for this conversation')}</button>}<button type="button" disabled={submitting} onClick={()=>void decide('reject')}>{t('拒绝','Reject')}</button></div>:<small>{({pending:t('该运行已结束','This run has ended'),approved:t('已批准','Approved'),rejected:t('已拒绝','Rejected'),cancelled:t('已取消','Cancelled'),interrupted:t('已中断','Interrupted')})[approval.status]}</small>}{error&&<p role="alert">{error}</p>}</section>;
}
