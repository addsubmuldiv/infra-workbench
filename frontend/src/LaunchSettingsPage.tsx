import {ui} from './assistantLocale';
import React,{useEffect,useState} from 'react';
import {Globe,Monitor,PanelsTopLeft,Check} from 'lucide-react';
import './settings.css';
import './launchSettings.css';

type LaunchView={mode:'browser'|'desktop';show_floating:boolean;desktop_available:boolean};
async function request(method='GET',body?:unknown):Promise<LaunchView>{
  const response=await fetch('/api/settings/launch',{method,headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body)});
  const value=await response.json();
  if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:ui("无法读取启动设置，请确认后台已更新"));
  return value;
}
export function LaunchSettingsPage(){
  const [saved,setSaved]=useState<LaunchView|null>(null),[mode,setMode]=useState<LaunchView['mode']>('browser'),[floating,setFloating]=useState(true);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  useEffect(()=>{let active=true;request().then(value=>{if(active){setSaved(value);setMode(value.mode);setFloating(value.show_floating)}}).catch(error=>{if(active)setError(error.message)});return()=>{active=false}},[]);
  async function save(event:React.FormEvent){
    event.preventDefault();setBusy(true);setError('');setMessage('');
    try{const value=await request('PUT',{mode,show_floating:floating});setSaved(value);setMode(value.mode);setFloating(value.show_floating);setMessage(ui("已保存。界面启动方式在下次打开时生效，浮窗设置立即生效。"))}
    catch(error){setError(error instanceof Error?error.message:String(error))}finally{setBusy(false)}
  }
  return <section className="settings-page"><div className="settings-section-title"><PanelsTopLeft size={20}/><div><h2>{ui("启动与桌面浮窗")}</h2><p>{ui("双击 Infra Workbench 图标即可打开，选择你习惯的界面。")}</p></div></div>
    <form className="settings-card" onSubmit={save}><div className="settings-fieldset"><h3>{ui("启动时打开")}</h3><div className="launch-options" role="radiogroup" aria-label={ui("启动界面")}>
      {([{id:'browser',title:ui("浏览器界面"),description:ui("使用默认浏览器打开工作台"),Icon:Globe},{id:'desktop',title:ui("桌面窗口"),description:ui("使用独立的桌面应用窗口"),Icon:Monitor}] as const).map(option=><button type="button" role="radio" aria-checked={mode===option.id} className={'launch-option '+(mode===option.id?'selected':'')} disabled={!saved||busy||(option.id==='desktop'&&!saved.desktop_available)} key={option.id} onClick={()=>{setMode(option.id);setMessage('')}}><option.Icon size={22}/><span><strong>{option.title}</strong><small>{option.description}</small></span>{mode===option.id&&<Check size={17}/>}</button>)}
      </div>{saved&&!saved.desktop_available&&<p className="subtle">{ui("尚未安装桌面窗口程序，安装桌面版后即可选择。")}</p>}<p className="subtle">{ui("两种界面启动时二选一，共用同一套机器、主题和设置；不会同时打开。")}</p></div>
      <label className="settings-toggle"><input type="checkbox" checked={floating} disabled={!saved||busy} onChange={event=>{setFloating(event.target.checked);setMessage('')}}/><span><strong>{ui("显示桌面浮窗")}</strong><small>{ui("默认开启；浏览器界面和桌面窗口都可使用，也能在托盘菜单中开关。")}</small></span></label>
      <div className="launch-save"><button className="primary" disabled={!saved||busy||(saved.mode===mode&&saved.show_floating===floating)}>{busy?ui("正在保存…"):ui("保存启动设置")}</button></div>
      {error&&<p role="alert" className="connection-error">{error}</p>}{message&&<p role="status" className="subtle">{message}</p>}
    </form></section>;
}
