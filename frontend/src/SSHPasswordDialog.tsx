import {t,useLocale} from './i18n';
import React,{useEffect,useState} from 'react';
import {KeyRound,LoaderCircle,Trash2,X} from 'lucide-react';

type Settings={password_saved:boolean|null;can_remember:boolean;error?:string|null};

export function SSHPasswordDialog({host,close,updated}:{host:{id:string;target:string};close:()=>void;updated:()=>Promise<void>}){
  useLocale();
  const [settings,setSettings]=useState<Settings|null>(null),[password,setPassword]=useState('');
  const [pending,setPending]=useState(false),[error,setError]=useState('');
  const endpoint='/api/hosts/'+encodeURIComponent(host.id)+'/ssh-password';
  const request=async(method='GET',body?:unknown)=>{
    const response=await fetch(endpoint,{method,headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
    const value=await response.json();if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:t("SSH 密码操作失败","SSH password operation failed"));return value as Settings;
  };
  useEffect(()=>{let active=true;request().then(value=>{if(active)setSettings(value)}).catch(e=>{if(active)setError(e.message)});return()=>{active=false}},[host.id]);
  const save=async(e:React.FormEvent)=>{
    e.preventDefault();if(pending||!password)return;setPending(true);setError('');
    try{await request('POST',{password});setPassword('');await updated();close()}
    catch(e){setError(e instanceof Error?e.message:t("SSH 密码验证失败","SSH password verification failed"))}
    finally{setPending(false)}
  };
  const forget=async()=>{
    if(pending)return;setPending(true);setError('');
    try{setSettings(await request('DELETE'));setPassword('');await updated()}
    catch(e){setError(e instanceof Error?e.message:t("删除失败","Deletion failed"))}
    finally{setPending(false)}
  };
  return <div className="modal-shade"><section role="dialog" aria-modal="true" aria-labelledby="ssh-password-title" className="modal sudo-modal"><div className="modal-header"><div><div className="eyebrow">CONNECT / SSH PASSWORD</div><h2 id="ssh-password-title">{host.target} {t(" · SSH 密码"," · SSH password")}</h2></div><button className="icon-button" disabled={pending} aria-label={t("关闭 SSH 密码设置","Close SSH password settings")} onClick={close}><X size={20}/></button></div>
    <form onSubmit={save}><div className="sudo-state"><KeyRound size={18}/><div><strong>{!settings?t("正在读取状态…","Reading status…"):settings.password_saved===null?t("无法确认已保存状态","Unable to confirm saved status"):settings.password_saved?t("SSH 密码已保存","SSH password saved"):t("尚未保存 SSH 密码","No SSH password saved")}</strong><small>{t("按机器保存在当前用户的系统凭据管理器，与 sudo 密码分别管理。","Saved per machine in the current user's system credential manager, separately from the sudo password.")}</small></div></div>
      <label className="form-label">{t("SSH 登录密码","SSH login password")}<input aria-label={t("SSH 登录密码","SSH login password")} type="password" autoComplete="off" maxLength={2048} value={password} disabled={pending||!settings?.can_remember} onChange={e=>setPassword(e.target.value)} placeholder={t("输入密码后验证并保存","Enter a password to verify and save")}/></label>
      <p className="subtle">{t("需要密码登录的 agent 可通过 MCP 工具 显式读取此密码，自行连接服务器。保存前验证账号和密码；不会安装密钥或修改远端配置。","Agents requiring password login can explicitly read this password through MCP tools to connect to the server. The account and password are verified before saving; no keys are installed and no remote configuration is changed.")}</p>
      {settings&&!settings.can_remember&&<p className="error-banner">{t("此系统暂不支持保存 SSH 密码。","Saving SSH passwords is not supported on this system.")}</p>}
      {(error||settings?.error)&&<div role="alert" className="connection-error">{error||settings?.error}</div>}
      <div className="modal-footer"><button type="button" className="text-button sudo-forget" aria-label={t("删除已保存的 SSH 密码","Delete saved SSH password")} disabled={pending||!settings||settings.password_saved===false} onClick={forget}><Trash2 size={14}/>{t("删除保存的密码","Delete saved password")}</button><button className="primary" disabled={pending||!password||!settings?.can_remember}>{pending?<LoaderCircle size={16} className="spin"/>:<KeyRound size={16}/ >}{pending?t("正在验证…","Verifying…"):t("验证并保存","Verify and save")}</button></div>
    </form></section></div>
}
