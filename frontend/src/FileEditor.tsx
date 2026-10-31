import React,{useEffect,useState,useRef} from 'react';
import {createPortal} from 'react-dom';
import {LoaderCircle,Save,X,Minus,PanelTopOpen} from 'lucide-react';
import {fileOperation,type TextDocument} from './files';
import {fitFileWindow,moveFileWindow,type WindowFrame} from './fileWindow';
const TextEditor=React.lazy(()=>import('./TextEditor').then(module=>({default:module.TextEditor})));

export function FileEditor({host,path,close,saved,changed,busyChanged,closeRequest}:{host:string;path:string;close:()=>void;saved:()=>void;changed:(dirty:boolean)=>void;busyChanged:(busy:boolean)=>void;closeRequest:React.RefObject<((after?:()=>void)=>void)|null>}){
  const [doc,setDoc]=useState<TextDocument|null>(null),[text,setText]=useState(''),[busy,setBusy]=useState(true),[error,setError]=useState(''),[message,setMessage]=useState('');
  const [pendingClose,setPendingClose]=useState<{after:()=>void}|null>(null);
  const [minimized,setMinimized]=useState(false);
  const viewport=()=>({width:window.innerWidth,height:window.innerHeight});
  const [frame,setFrame]=useState(()=>fitFileWindow({x:window.innerWidth-824,y:100,width:800,height:Math.min(560,window.innerHeight-140)},viewport()));
  const gesture=useRef<{pointer:number;kind:'move'|'resize';x:number;y:number;frame:WindowFrame}|null>(null);
  useEffect(()=>{const resize=()=>setFrame(old=>fitFileWindow(old,viewport()));window.addEventListener('resize',resize);return()=>window.removeEventListener('resize',resize)},[]);
  const startGesture=(event:React.PointerEvent,kind:'move'|'resize')=>{
    if(event.button!==0||gesture.current)return;
    if(kind==='move'&&(event.target as HTMLElement).closest('button,select,input,a,textarea'))return;
    event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);
    gesture.current={pointer:event.pointerId,kind,x:event.clientX,y:event.clientY,frame};
  };
  const moveGesture=(event:React.PointerEvent)=>{
    const start=gesture.current;if(!start||start.pointer!==event.pointerId)return;
    const dx=event.clientX-start.x,dy=event.clientY-start.y;
    setFrame(start.kind==='move'?moveFileWindow(start.frame,dx,dy,viewport(),minimized):fitFileWindow({...start.frame,width:start.frame.width+dx,height:start.frame.height+dy},viewport()));
  };
  const endGesture=(event:React.PointerEvent)=>{if(gesture.current?.pointer===event.pointerId)gesture.current=null};
  const toggleMinimized=()=>{if(minimized)setFrame(old=>fitFileWindow(old,viewport()));setMinimized(!minimized)};
  const dirty=doc!==null&&text!==doc.content;
  useEffect(()=>{let active=true;void fileOperation<TextDocument>(host,{op:'read',path}).then(value=>{if(active){setDoc(value);setText(value.content)}}).catch(e=>{if(active)setError(e instanceof Error?e.message:String(e))}).finally(()=>{if(active)setBusy(false)});return()=>{active=false}},[host,path]);
  useEffect(()=>{changed(dirty);return()=>changed(false)},[dirty]);
  useEffect(()=>{busyChanged(busy);return()=>busyChanged(false)},[busy]);
  useEffect(()=>{if(!dirty)return;const guard=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue=''};window.addEventListener('beforeunload',guard);return()=>window.removeEventListener('beforeunload',guard)},[dirty]);
  const leave=(after:()=>void=close)=>{if(busy)return;if(dirty){setMinimized(false);setPendingClose({after})}else after()};
  useEffect(()=>{closeRequest.current=leave;return()=>{closeRequest.current=null}});
  const save=async()=>{
    if(!doc||busy)return false;if(!dirty)return true;
    setBusy(true);setError('');setMessage('');
    try{const next=await fileOperation<TextDocument>(host,{op:'save',path,content:text,revision:doc.revision});setDoc(next);setText(next.content);setMessage('已保存到服务器');saved();return true}
    catch(e){setError(e instanceof Error?e.message:String(e));return false}finally{setBusy(false)}
  };
  return createPortal(<section className={'file-editor floating '+(minimized?'minimized':'')} role="dialog" aria-modal="false" aria-label={'编辑文件 '+path} style={{left:frame.x,top:frame.y,width:minimized?'min(320px, calc(100vw - 16px))':frame.width,height:minimized?56:frame.height}} onPointerMove={moveGesture} onPointerUp={endGesture} onPointerCancel={endGesture} onLostPointerCapture={endGesture} onKeyDown={event=>{if(event.defaultPrevented)return;if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();void save()}else if(event.key==='Escape'){event.stopPropagation();if(pendingClose)setPendingClose(null);else leave()}}}>
    <div className="file-editor-heading" onPointerDown={event=>startGesture(event,'move')}><div tabIndex={0} aria-label="移动文本编辑器，方向键调整位置" onKeyDown={event=>{if(event.target!==event.currentTarget)return;const offsets:Record<string,[number,number]>={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]};const offset=offsets[event.key];if(offset){event.preventDefault();setFrame(old=>moveFileWindow(old,...offset,viewport(),minimized))}}}><h3 title={path}>{dirty?'● ':''}{path.split('/').pop()}</h3>{!minimized&&<p title={path}>{path}</p>}</div>{!minimized&&<button className="primary" disabled={!doc||busy||!dirty} onClick={()=>void save()}>{busy?<LoaderCircle size={15} className="spin"/>:<Save size={15}/>}保存</button>}<button className="icon-button" aria-label={minimized?'恢复文本编辑器':'最小化文本编辑器'} title={minimized?'恢复编辑窗口':'最小化（保留未保存内容）'} onClick={toggleMinimized}>{minimized?<PanelTopOpen size={17}/>:<Minus size={17}/>}</button><button className="icon-button" aria-label="关闭文本编辑器" disabled={busy} onClick={()=>leave()}><X size={19}/></button></div>
    <div className="file-editor-body" hidden={minimized}>
    {error&&<p className="file-error" role="alert">{error}</p>}{message&&<p className="file-inline" role="status">{message}</p>}
    {doc?<React.Suspense fallback={<p className="file-inline">正在加载编辑工具…</p>}><TextEditor value={text} readOnly={busy} onChange={value=>{setText(value);setMessage('')}}/></React.Suspense>:busy?<p className="file-inline"><LoaderCircle size={16} className="spin"/>正在打开文本文件…</p>:<p className="file-inline">可关闭此窗口，使用下载功能在本地打开文件。</p>}
    <div className="file-editor-footer"><span>UTF-8 · {doc?.newline??'—'} · {text.split('\n').length} 行 · 文本上限 1 MiB</span><span>{dirty?'尚未保存':'Ctrl/⌘+S 保存'}</span></div>
    </div>
    {!minimized&&<div className="file-window-resize" role="separator" aria-label="调整文本编辑器大小" tabIndex={0} onPointerDown={event=>startGesture(event,'resize')} onKeyDown={event=>{const offsets:Record<string,[number,number]>={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]};const offset=offsets[event.key];if(offset){event.preventDefault();setFrame(old=>fitFileWindow({...old,width:old.width+offset[0],height:old.height+offset[1]},viewport()))}}}/>}
    {pendingClose&&<div className="file-confirm-shade"><div className="file-confirm" role="alertdialog" aria-label="保存文件修改"><h3>保存修改后再关闭？</h3><p>{path}</p><p>未保存的内容会丢失。</p><div><button className="secondary" disabled={busy} onClick={()=>setPendingClose(null)}>取消</button><button className="secondary" disabled={busy} onClick={()=>pendingClose.after()}>不保存</button><button className="primary" disabled={busy} onClick={async()=>{if(await save())pendingClose.after();else setPendingClose(null)}}>保存并关闭</button></div></div></div>}
  </section>,document.body);
}
