import {useEffect,useId,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {Code2,LoaderCircle,X} from 'lucide-react';
import {t,useLocale} from './i18n';
import {openVSCode,VSCodeError,type VSCodePhase} from './vscode';
import './vscode.css';

type Host={id:string;target:string};
export function VSCodeButton({host,disabled=false}:{host:Host;disabled?:boolean}){
  const [open,setOpen]=useState(false);
  return <><button className="ssh-open" disabled={disabled} title={disabled?t('演示模式不打开本机 VS Code','Demo mode does not launch VS Code'):t('打开 VS Code，先连接勾选的 SSH 隧道','Open VS Code after connecting selected SSH tunnels')} aria-label={t('用 VS Code 连接 ','Connect with VS Code: ')+host.target} onClick={()=>setOpen(true)}><Code2 size={15}/><span>VS Code</span></button>{open&&<VSCodeLaunch host={host} close={()=>setOpen(false)}/>}</>;
}

function VSCodeLaunch({host,close}:{host:Host;close:()=>void}){
  useLocale();
  const dialog=useRef<HTMLDialogElement>(null),title=useId(),description=useId();
  const [phase,setPhase]=useState<VSCodePhase>('preparing'),[error,setError]=useState<VSCodeError|null>(null),[busy,setBusy]=useState(true);
  const controller=useRef<AbortController|null>(null),mounted=useRef(true);
  const expectedAuthority=useRef<string|undefined>(undefined);
  const closeRef=useRef(close);closeRef.current=close;
  async function run(skip=false){
    controller.current?.abort();const current=new AbortController();controller.current=current;
    setBusy(true);setError(null);setPhase(skip?'opening':'preparing');
    if(!skip)expectedAuthority.current=undefined;
    async function request(path:string,method='GET',body?:unknown){
      const signal=AbortSignal.any([current.signal,AbortSignal.timeout(20000)]);
      const response=await fetch(`/api/hosts/${encodeURIComponent(host.id)}${path}`,{method,signal,headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body)});
      const data=await response.json();
      if(!response.ok){const detail=data.detail;const code=detail?.code??'VSCODE_REQUEST_FAILED';if(typeof detail?.expected_authority==='string')expectedAuthority.current=detail.expected_authority;throw new VSCodeError(code,detail?.message??(typeof detail==='string'?detail:t('操作失败','Operation failed')),['TUNNEL_NOT_READY','TUNNEL_START_FAILED'].includes(code)&&!!expectedAuthority.current)}
      return data;
    }
    try{
      await openVSCode({request,skip,expectedAuthority:expectedAuthority.current,prepared:value=>{expectedAuthority.current=value},signal:current.signal,phase:value=>{if(mounted.current)setPhase(value)}});
      if(mounted.current&&!current.signal.aborted)closeRef.current();
    }catch(e){
      if(mounted.current&&!current.signal.aborted)setError(e instanceof VSCodeError?e:new VSCodeError('VSCODE_REQUEST_FAILED',e instanceof Error?e.message:String(e)));
    }finally{if(mounted.current&&controller.current===current)setBusy(false)}
  }
  useEffect(()=>{
    mounted.current=true;const previous=document.activeElement;const element=dialog.current;element?.showModal();void run();
    return()=>{mounted.current=false;controller.current?.abort();element?.close();if(previous instanceof HTMLElement&&previous.isConnected)previous.focus()};
  },[host.id]);
  const opening=busy&&phase==='opening';
  function cancel(){if(opening)return;controller.current?.abort();close()}
  return createPortal(<dialog ref={dialog} className="vscode-launch" aria-labelledby={title} aria-describedby={description} onCancel={e=>{e.preventDefault();cancel()}}>
    <div className="vscode-launch-heading"><h2 id={title}><Code2 size={21}/>VS Code</h2><button className="icon-button" disabled={opening} aria-label={t('取消打开 VS Code','Cancel opening VS Code')} onClick={cancel}><X size={19}/></button></div>
    <p className="vscode-launch-target">{host.target}</p>
    {busy?<p className="vscode-launch-status" role="status"><LoaderCircle size={18} className="spin"/>{phase==='preparing'?t('正在准备连接…','Preparing connection…'):phase==='connecting'?t('正在等待 SSH 隧道连接…','Waiting for SSH tunnels…'):t('正在打开本机 VS Code…','Opening local VS Code…')}</p>:error&&<p className="vscode-launch-error" role="alert">{errorMessage(error)}</p>}
    <p id={description} className="vscode-launch-note">{t('取消打开不会断开后台隧道。VS Code 的远端连接由 Remote - SSH 扩展完成。','Cancelling does not disconnect background tunnels. The Remote - SSH extension handles the VS Code connection.')}</p>
    <div className="vscode-launch-actions"><button className="secondary" disabled={opening} onClick={cancel}>{t('取消','Cancel')}</button>{!busy&&<button className="primary" onClick={()=>void run()}>{t('重试','Retry')}</button>}{!busy&&error?.canSkip&&<button className="secondary" onClick={()=>void run(true)}>{t('仍然打开 VS Code','Open VS Code anyway')}</button>}</div>
  </dialog>,document.body);
}

function errorMessage(error:VSCodeError){
  const messages:Record<string,[string,string]>={
    VSCODE_NOT_FOUND:['未找到本机 VS Code。请安装 VS Code，并将 code 命令加入 PATH 后重试。','VS Code was not found locally. Install it and add the code command to PATH.'],
    VSCODE_LAUNCH_FAILED:['VS Code 启动失败，请检查本机安装及 Remote - SSH 扩展。','Could not launch VS Code. Check its installation and the Remote - SSH extension.'],
    TUNNEL_FAILED:['SSH 隧道连接失败或已被停止。请在隧道面板中查看原因，重试或仍然打开 VS Code。','An SSH tunnel failed or was stopped. Check its tunnel panel, retry, or open VS Code anyway.'],
    TUNNEL_TIMEOUT:['等待 SSH 隧道超过 60 秒。隧道仍由后台管理，可以重试或仍然打开 VS Code。','SSH tunnels did not connect within 60 seconds. They remain managed by the backend. Retry or open VS Code anyway.'],
    TUNNEL_NOT_READY:['SSH 隧道尚未全部连接，可以重试或仍然打开 VS Code。','Not all SSH tunnels are connected. Retry or open VS Code anyway.'],
    TUNNEL_START_FAILED:['无法启动所选 SSH 隧道，请检查端口冲突后重试，或仍然打开 VS Code。','Could not start a selected tunnel. Check for port conflicts, retry, or open VS Code anyway.'],
    VSCODE_TARGET_CHANGED:['SSH 目标已变化，请重试打开 VS Code。','The SSH target changed. Retry opening VS Code.'],
  };
  const message=messages[error.code];return message?t(...message):error.message;
}
