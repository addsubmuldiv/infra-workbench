import {UI_TUNNEL_POLL_MS} from './internalDefaults.ts';
import {useEffect,useId,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {ArrowDown,Link2,LoaderCircle,Plus,Unplug,X} from 'lucide-react';
import {t,useLocale} from './i18n';
import './sshTunnels.css';

export type TunnelRule={id:string;name:string;direction:'remote'|'local';local_port:number;remote_port:number;auto_reconnect:boolean;auto_start:boolean;before_vscode:boolean;status:string;error:string;error_code:string|null;connected_at:number|null;next_retry_at:number|null};
type Host={id:string;target:string;auth?:string;ssh_tunnels?:TunnelRule[];ssh_password?:{password_saved:boolean|null}};
type Draft=Pick<TunnelRule,'name'|'direction'|'local_port'|'remote_port'|'auto_reconnect'|'auto_start'|'before_vscode'>;
const defaults=():Draft=>({name:t('Codex 代理','Codex proxy'),direction:'remote',local_port:7890,remote_port:18899,auto_reconnect:true,auto_start:false,before_vscode:false});
const running=(status:string)=>['connecting','connected','reconnecting'].includes(status);
function statusText(status:string){return status==='connected'?t('已连接','Connected'):status==='connecting'?t('正在连接','Connecting'):status==='reconnecting'?t('正在重连','Reconnecting'):status==='error'?t('连接失败','Connection failed'):t('未连接','Disconnected')}
function withRule(rules:TunnelRule[],rule:TunnelRule){
  return rules.some(item=>item.id===rule.id)?rules.map(item=>item.id===rule.id?rule:item):[...rules,rule];
}
export async function tunnelRequest(host:string,path='',method='GET',body?:unknown){
  const response=await fetch(`/api/hosts/${encodeURIComponent(host)}/tunnels${path}`,{method,headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:t('隧道操作失败，请检查输入','Tunnel operation failed; check the inputs'));
  return data;
}

export function SSHTunnelButton({host,disabled=false}:{host:Host;disabled?:boolean}){
  const [open,setOpen]=useState(false),[live,setLive]=useState<TunnelRule[]|null>(null);
  useEffect(()=>{setLive(null)},[host.ssh_tunnels]);
  const rules=live??host.ssh_tunnels??[];
  const status=rules.some(r=>r.status==='error')?'error':rules.some(r=>r.status==='reconnecting')?'reconnecting':rules.some(r=>r.status==='connecting')?'connecting':rules.some(r=>r.status==='connected')?'connected':'stopped';
  const title=t('SSH 隧道','SSH tunnels')+' · '+statusText(status)+(rules.length?` · ${rules.filter(r=>r.status==='connected').length}/${rules.length}`:'');
  return <><button className={'ssh-open ssh-tunnel-button tunnel-'+status} disabled={disabled} title={disabled?t('演示模式不建立真实隧道','Tunnels are unavailable in demo mode'):title} aria-label={host.target+' '+title} aria-haspopup="dialog" onClick={()=>setOpen(true)}><Link2 size={16}/><i className={'tunnel-dot '+status}/></button>{open&&<SSHTunnelPanel host={host} close={()=>setOpen(false)} onRules={setLive}/>}</>;
}

export function SSHTunnelPanel({host,close,onRules,onStarted=close}:{host:Host;close:()=>void;onRules:(rules:TunnelRule[])=>void;onStarted?:()=>void}){
  useLocale();
  const dialog=useRef<HTMLDialogElement>(null),title=useId(),description=useId();
  const [rules,setRules]=useState<TunnelRule[]>(host.ssh_tunnels??[]),[selected,setSelected]=useState<string|null>(null);
  const [draft,setDraft]=useState<Draft>(defaults),[error,setError]=useState(''),[busy,setBusy]=useState(false),[loaded,setLoaded]=useState(false);
  const [probe,setProbe]=useState<{reachable:boolean|null;message:string}|null>(null),[now,setNow]=useState(Date.now());
  const initialized=useRef(false),mounted=useRef(true),acting=useRef(false);
  useEffect(()=>{const previous=document.activeElement;const element=dialog.current;element?.showModal();return()=>{element?.close();if(previous instanceof HTMLElement&&previous.isConnected)previous.focus()}},[]);
  function choose(rule:TunnelRule|null){setSelected(rule?.id??null);setDraft(rule?{name:rule.name,direction:rule.direction,local_port:rule.local_port,remote_port:rule.remote_port,auto_reconnect:rule.auto_reconnect,auto_start:rule.auto_start,before_vscode:rule.before_vscode??false}:defaults());setProbe(null);setError('')}
  useEffect(()=>{
    mounted.current=true;let active=true;let timer:ReturnType<typeof setTimeout>;
    async function load(){
      try{
        const data:TunnelRule[]=await tunnelRequest(host.id);
        if(active&&!acting.current){setRules(data);onRules(data);setLoaded(true);if(!initialized.current){initialized.current=true;if(data[0])choose(data[0])}}
      }catch(e){if(active)setError(e instanceof Error?e.message:String(e))}
      if(active)timer=setTimeout(load,UI_TUNNEL_POLL_MS);
    }
    void load();const clock=setInterval(()=>setNow(Date.now()),1000);
    return()=>{active=false;mounted.current=false;clearTimeout(timer);clearInterval(clock)};
  },[host.id,onRules]);
  const rule=rules.find(r=>r.id===selected),active=!!rule&&running(rule.status);
  const dirty=!!rule&&Object.keys(draft).some(key=>draft[key as keyof Draft]!==rule[key as keyof Draft]);
  const update=<K extends keyof Draft>(key:K,value:Draft[K])=>{setDraft(old=>({...old,[key]:value}));setProbe(null)};
  async function act(action:()=>Promise<void>,refresh=true){
    if(acting.current)return;acting.current=true;setBusy(true);setError('');
    try{await action();if(refresh&&mounted.current){const data=await tunnelRequest(host.id);if(mounted.current){setRules(data);onRules(data)}}}catch(e){if(mounted.current)setError(e instanceof Error?e.message:String(e))}finally{acting.current=false;if(mounted.current)setBusy(false)}
  }
  async function save(connect:boolean){
    await act(async()=>{
      const saved:TunnelRule=connect&&rule&&!dirty?rule:
        await tunnelRequest(host.id,selected?`/${selected}`:'',selected?'PUT':'POST',draft);
      if(mounted.current){
        choose(saved);
        setRules(old=>withRule(old,saved));
      }
      if(!connect)return;
      const started:TunnelRule=await tunnelRequest(host.id,`/${saved.id}/start`,'POST');
      if(mounted.current){
        onRules(withRule(rules,started));
        onStarted();
      }
    },!connect);
  }
  const route=draft.direction==='remote'?[t('远端','Remote'),draft.remote_port,t('本机','Local'),draft.local_port]:[t('本机','Local'),draft.local_port,t('远端','Remote'),draft.remote_port];
  const elapsed=rule?.connected_at?Math.max(0,Math.floor((now/1000-rule.connected_at)/60)):0;
  return createPortal(<dialog ref={dialog} className="ssh-tunnel-panel" aria-labelledby={title} aria-describedby={description} onCancel={e=>{e.preventDefault();close()}}>
    <header className="tunnel-heading"><div><h2 id={title}><Link2 size={21}/>{t('SSH 隧道','SSH tunnels')}</h2><p>{host.target}</p></div><button className="icon-button" aria-label={t('关闭','Close')} onClick={close}><X size={20}/></button></header>
    <div className="tunnel-body">
      {rules.length>0&&<nav className="tunnel-rules" aria-label={t('已保存的隧道','Saved tunnels')}>{rules.map(item=><button key={item.id} className={selected===item.id?'selected':''} onClick={()=>choose(item)} disabled={busy}><i className={'tunnel-dot '+item.status}/><span>{item.name}</span></button>)}<button disabled={busy} onClick={()=>choose(null)}><Plus size={14}/>{t('新增','New')}</button></nav>}
      <form onSubmit={e=>{e.preventDefault();void save(true)}}>
        <fieldset disabled={busy||active||!loaded}>
          <label>{t('名称','Name')}<input required maxLength={80} value={draft.name} onChange={e=>update('name',e.target.value)}/></label>
          <label>{t('转发方向','Direction')}<select value={draft.direction} onChange={e=>update('direction',e.target.value as Draft['direction'])}><option value="remote">{t('远端访问本机（代理）','Remote to local (proxy)')}</option><option value="local">{t('本机访问远端（服务）','Local to remote (service)')}</option></select></label>
          <div className="tunnel-ports"><label>{t('本机端口','Local port')}<input required type="number" min={1} max={65535} step={1} value={draft.local_port} onChange={e=>update('local_port',Number(e.target.value))}/></label><label>{t('远端端口','Remote port')}<input required type="number" min={1} max={65535} step={1} value={draft.remote_port} onChange={e=>update('remote_port',Number(e.target.value))}/></label></div>
        </fieldset>
        <div className="tunnel-route"><span>{route[0]} <code>127.0.0.1:{route[1]}</code></span><ArrowDown size={17}/><span>{route[2]} <code>127.0.0.1:{route[3]}</code></span></div>
        <div className="tunnel-status" role="status"><i className={'tunnel-dot '+(rule?.status??'stopped')}/><strong>{statusText(rule?.status??'stopped')}</strong>{rule?.status==='connected'&&<span>{t(`运行 ${elapsed} 分钟`,`Active for ${elapsed} min`)}</span>}{rule?.status==='reconnecting'&&rule.next_retry_at&&<span>{t(`${Math.max(0,Math.ceil(rule.next_retry_at-now/1000))} 秒后重试`,`Retry in ${Math.max(0,Math.ceil(rule.next_retry_at-now/1000))}s`)}</span>}</div>
        {rule?.error&&<p className="tunnel-error" role="alert">{tunnelError(rule.error_code,rule.error)}</p>}
        {probe&&<p className={'tunnel-probe '+(probe.reachable===false?'failed':'')} role="status">{probeText(probe.reachable)}</p>}
        {host.auth==='password_session'&&host.ssh_password?.password_saved!==true&&<p className="tunnel-note">{t('独立隧道需要保存 SSH 密码。请在机器的 SSH 密码设置中保存后再连接。','Independent tunnels need a saved SSH password. Save it in the machine SSH password settings before connecting.')}</p>}
        <fieldset className="tunnel-options" disabled={busy||active||!loaded}><label><input type="checkbox" checked={draft.auto_reconnect} onChange={e=>update('auto_reconnect',e.target.checked)}/>{t('断线自动重连','Reconnect after network failure')}</label><label><input type="checkbox" checked={draft.auto_start} onChange={e=>update('auto_start',e.target.checked)}/>{t('软件启动时连接','Connect on app startup')}</label><label><input type="checkbox" checked={draft.before_vscode} onChange={e=>update('before_vscode',e.target.checked)}/>{t('打开 VS Code 前连接此隧道','Connect before opening VS Code')}</label></fieldset>
        {active&&<p className="tunnel-note">{t('断开后可修改配置。','Disconnect to edit this configuration.')}</p>}
        {error&&<p className="tunnel-error" role="alert">{error}</p>}
        <div className="tunnel-actions">{active?<><button type="button" className="secondary" disabled={busy||rule?.status!=='connected'} onClick={()=>void act(async()=>{const result=await tunnelRequest(host.id,`/${selected}/probe`,'POST');if(mounted.current)setProbe(result)})}>{t('检测目标端口','Check target port')}</button><button type="button" className="tunnel-disconnect" disabled={busy} onClick={()=>void act(async()=>{await tunnelRequest(host.id,`/${selected}/stop`,'POST');setProbe(null)})}><Unplug size={15}/>{rule?.status==='connected'?t('断开隧道','Disconnect'):t('取消连接','Cancel connection')}</button></>:<><button type="button" className="secondary" disabled={busy||!loaded} onClick={()=>{const form=dialog.current?.querySelector('form');if(form?.reportValidity())void save(false)}}>{t('保存','Save')}</button><button className="primary" disabled={busy||!loaded}>{busy?<LoaderCircle size={15} className="spin"/>:<Link2 size={15}/>} {!selected||dirty?t('保存并连接','Save and connect'):t('连接隧道','Connect')}</button></>}</div>
      </form>
      {selected&&!active&&<button className="text-button tunnel-delete" disabled={busy} onClick={()=>void act(async()=>{await tunnelRequest(host.id,`/${selected}`,'DELETE');if(mounted.current)choose(null)})}>{t('删除此配置','Delete configuration')}</button>}
      <p id={description} className="tunnel-footnote">{t('监听与目标地址均设为 127.0.0.1。关闭窗口后隧道继续在托盘后台运行，退出后台时断开。','Listening and target addresses are set to 127.0.0.1. Tunnels keep running in the tray after closing the window and disconnect when the backend exits.')}</p>
    </div>
  </dialog>,document.body);
}

function probeText(reachable:boolean|null){return reachable===true?t('目标 TCP 端口可达；尚未验证代理协议或外网访问。','Target TCP port is reachable; proxy protocol and internet access have not been tested.'):reachable===false?t('目标 TCP 端口不可达，请确认对应服务正在运行。','Target TCP port is unreachable. Check that the service is running.'):t('隧道已连接，请通过本机监听端口验证远端服务。','Tunnel is connected. Use the local listening port to verify the remote service.')}
function tunnelError(code:string|null,fallback:string){
  const messages:Record<string,[string,string]>={AUTH_REQUIRED:['SSH 认证失败，请配置免密登录或保存 SSH 密码。','SSH authentication failed. Configure key login or save the SSH password.'],HOST_KEY:['SSH 主机密钥未通过校验，请先核对机器身份。','SSH host key verification failed. Verify the machine identity.'],FORWARD_REJECTED:['监听端口被占用或服务器拒绝转发，请检查端口和 SSH 转发权限。','The listening port is occupied or forwarding was rejected. Check the port and SSH forwarding permissions.'],CONNECTION_LOST:['SSH 网络连接中断或超时。','SSH network connection was lost or timed out.'],CONNECTION_FAILED:['无法建立隧道，请检查 SSH 配置、认证和转发权限。','Could not establish the tunnel. Check SSH configuration, authentication and forwarding permissions.'],SSH_PASSWORD_UNAVAILABLE:['未保存 SSH 密码，请先在机器的 SSH 密码设置中保存。','No SSH password saved. Save it in the machine SSH password settings.'],CREDENTIAL_IDENTITY_CHANGED:['SSH 目标、账号或路由已变化，请重新保存密码。','The SSH target, user or route changed. Save the password again.']};
  const message=code?messages[code]:null;return message?t(...message):fallback;
}
