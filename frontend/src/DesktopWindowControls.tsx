import {Copy,Minus,Square,X} from 'lucide-react';
import {useEffect,useState} from 'react';
import {t,useLocale} from './i18n';
import './desktopTitlebar.css';

type Action='status'|'drag'|'minimize'|'toggle-maximize'|'close';
type Invoke=(action:Action)=>Promise<boolean>;

export function hasDesktopTitlebar(target:Window):Invoke|undefined {
  const native=target as Window&{__iwbDesktopTitlebar?:boolean;__TAURI_INTERNALS__?:{
    invoke:(command:string,args:{action:Action})=>Promise<boolean>;
  }};
  const bridge=native.__TAURI_INTERNALS__;
  if(native.__iwbDesktopTitlebar&&typeof bridge?.invoke==='function'){
    return action=>bridge.invoke('main_window_action',{action});
  }
}

export function DesktopWindowControls({invoke}:{invoke:Invoke}){
  useLocale();
  const [maximized,setMaximized]=useState(false);
  useEffect(()=>{
    let active=true;
    const update=()=>{void invoke('status').then(value=>{if(active)setMaximized(value)}).catch(()=>{})};
    update();
    window.addEventListener('resize',update);
    return()=>{active=false;window.removeEventListener('resize',update)};
  },[invoke]);
  const maximizeLabel=maximized?t('还原窗口','Restore window'):t('最大化窗口','Maximize window');
  const minimizeLabel=t('最小化窗口','Minimize window');
  const closeLabel=t('关闭窗口','Close window');
  return <div className="desktop-window-controls">
    <button type="button" aria-label={minimizeLabel} title={minimizeLabel} onClick={()=>void invoke('minimize').catch(()=>{})}><Minus size={15}/></button>
    <button type="button" aria-label={maximizeLabel} title={maximizeLabel} onClick={()=>void invoke('toggle-maximize').then(setMaximized).catch(()=>{})}>{maximized?<Copy size={13}/>:<Square size={13}/>}</button>
    <button type="button" aria-label={closeLabel} title={closeLabel} className="desktop-window-close" onClick={()=>void invoke('close').catch(()=>{})}><X size={16}/></button>
  </div>;
}
