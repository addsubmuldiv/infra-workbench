import React,{useEffect,useState} from 'react';
import {KeyRound,LoaderCircle,Trash2,X} from 'lucide-react';

type Settings={password_saved:boolean|null;can_remember:boolean;error?:string|null};

export function SSHPasswordDialog({host,close,updated}:{host:{id:string;target:string};close:()=>void;updated:()=>Promise<void>}){
  const [settings,setSettings]=useState<Settings|null>(null),[password,setPassword]=useState('');
  const [pending,setPending]=useState(false),[error,setError]=useState('');
  const endpoint='/api/hosts/'+encodeURIComponent(host.id)+'/ssh-password';
  const request=async(method='GET',body?:unknown)=>{
    const response=await fetch(endpoint,{method,headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
    const value=await response.json();if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'SSH 密码操作失败');return value as Settings;
  };
  useEffect(()=>{let active=true;request().then(value=>{if(active)setSettings(value)}).catch(e=>{if(active)setError(e.message)});return()=>{active=false}},[host.id]);
  const save=async(e:React.FormEvent)=>{
    e.preventDefault();if(pending||!password)return;setPending(true);setError('');
    try{await request('POST',{password});setPassword('');await updated();close()}
    catch(e){setError(e instanceof Error?e.message:'SSH 密码验证失败')}
    finally{setPending(false)}
  };
  const forget=async()=>{
    if(pending)return;setPending(true);setError('');
    try{setSettings(await request('DELETE'));setPassword('');await updated()}
    catch(e){setError(e instanceof Error?e.message:'删除失败')}
    finally{setPending(false)}
  };
  return <div className="modal-shade"><section role="dialog" aria-modal="true" aria-labelledby="ssh-password-title" className="modal sudo-modal"><div className="modal-header"><div><div className="eyebrow">CONNECT / SSH PASSWORD</div><h2 id="ssh-password-title">{host.target} · SSH 密码</h2></div><button className="icon-button" disabled={pending} aria-label="关闭 SSH 密码设置" onClick={close}><X size={20}/></button></div>
    <form onSubmit={save}><div className="sudo-state"><KeyRound size={18}/><div><strong>{!settings?'正在读取状态…':settings.password_saved===null?'无法确认已保存状态':settings.password_saved?'SSH 密码已保存':'尚未保存 SSH 密码'}</strong><small>按机器保存在当前用户的系统凭据管理器，与 sudo 密码分别管理。</small></div></div>
      <label className="form-label">SSH 登录密码<input aria-label="SSH 登录密码" type="password" autoComplete="off" maxLength={2048} value={password} disabled={pending||!settings?.can_remember} onChange={e=>setPassword(e.target.value)} placeholder="输入密码后验证并保存"/></label>
      <p className="subtle">需要密码登录的 agent 可通过 MCP 工具 显式读取此密码，自行连接服务器。保存前验证账号和密码；不会安装密钥或修改远端配置。</p>
      {settings&&!settings.can_remember&&<p className="error-banner">此系统暂不支持保存 SSH 密码。</p>}
      {(error||settings?.error)&&<div role="alert" className="connection-error">{error||settings?.error}</div>}
      <div className="modal-footer"><button type="button" className="text-button sudo-forget" aria-label="删除已保存的 SSH 密码" disabled={pending||!settings||settings.password_saved===false} onClick={forget}><Trash2 size={14}/>删除保存的密码</button><button className="primary" disabled={pending||!password||!settings?.can_remember}>{pending?<LoaderCircle size={16} className="spin"/>:<KeyRound size={16}/ >}{pending?'正在验证…':'验证并保存'}</button></div>
    </form></section></div>
}
