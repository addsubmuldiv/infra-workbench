import {ui} from './assistantLocale';
import React,{useEffect,useState} from 'react';
import {agentRequest,type AgentView} from './agentSettings';
import {useAppConfirm} from './AppConfirm';
import './agentProfiles.css';
export function AgentProfilePicker({manage=false,disabled=false,onChange}:{manage?:boolean;disabled?:boolean;onChange?:(value:AgentView)=>void}){
  const [view,setView]=useState<AgentView|null>(null),[name,setName]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const {confirm,confirmation}=useAppConfirm();
  useEffect(()=>{
    let alive=true;
    const load=()=>{void agentRequest<AgentView>().then(value=>{if(alive){setView(value);setName(value.profiles.find(p=>p.id===value.active_id)?.name||'');setError('');if(!manage)onChange?.(value)}}).catch(e=>{if(alive)setError(e.message)})};
    load();window.addEventListener('infra-workbench:agent-settings-changed',load);window.addEventListener('focus',load);
    return()=>{alive=false;window.removeEventListener('infra-workbench:agent-settings-changed',load);window.removeEventListener('focus',load)};
  },[]);
  const act=async(path:string,method='POST',body?:unknown)=>{
    setBusy(true);setError('');
    try{const next=await agentRequest<AgentView>(path,method,body);setView(next);setName(next.profiles.find(p=>p.id===next.active_id)?.name||'');onChange?.(next);window.dispatchEvent(new Event('infra-workbench:agent-settings-changed'))}
    catch(e){setError(e instanceof Error?e.message:ui("配置操作失败"))}
    finally{setBusy(false)}
  };
  return <div className="agent-profile-picker">
    <label className="form-label">{manage?ui("当前接口配置"):ui("模型 / 接口")}<select aria-label={ui("切换模型接口")} disabled={disabled||busy||!view} value={view?.active_id||''} onChange={e=>void act('/profiles/'+e.target.value+'/activate')}>
      {!view&&<option value="">{ui("正在读取配置…")}</option>}{view?.profiles.map(p=><option key={p.id} value={p.id}>{p.name}{p.model?' / '+p.model:''}{p.id===view.default_id?ui("（默认）"):''}</option>)}
    </select></label>
    {manage&&<><label className="form-label">{ui("配置名称")}<input aria-label={ui("接口配置名称")} maxLength={100} disabled={disabled||busy} value={name} onChange={e=>setName(e.target.value)}/></label>
      <div className="agent-profile-actions">
        <button type="button" className="secondary" disabled={disabled||busy||!view} onClick={()=>void act('/profiles','POST',{name:ui("新接口配置")})}>{ui("新增配置")}</button>
        <button type="button" className="secondary" disabled={disabled||busy||!view||!name.trim()} onClick={()=>void act('/profiles/'+view!.active_id,'PUT',{name:name.trim()})}>{ui("重命名")}</button>
        <button type="button" className="secondary" disabled={disabled||busy||!view||view.active_id===view.default_id} onClick={()=>void act('/profiles/'+view!.active_id,'PUT',{name:view!.profiles.find(p=>p.id===view!.active_id)!.name,default:true})}>{ui("设为默认")}</button>
        <button type="button" className="secondary" disabled={disabled||busy||!view||view.profiles.length<2} onClick={async()=>{if(await confirm(ui("删除当前接口配置和它的 API key？已有聊天记录会保留。")))void act('/profiles/'+view!.active_id,'DELETE')}}>{ui("删除配置")}</button>
      </div>{disabled&&<p className="settings-help">{ui("请先保存下方修改，再切换或管理配置。")}</p>}</>}
    {error&&<p className="settings-error" role="alert">{error}</p>}{confirmation}
  </div>;
}
