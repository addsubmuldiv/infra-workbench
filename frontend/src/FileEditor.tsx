import React,{useEffect,useState,useRef} from 'react';
import {LoaderCircle,Save,X} from 'lucide-react';
import {fileOperation,type TextDocument} from './files';

export function FileEditor({host,path,close,saved,changed,busyChanged,closeRequest}:{host:string;path:string;close:()=>void;saved:()=>void;changed:(dirty:boolean)=>void;busyChanged:(busy:boolean)=>void;closeRequest:React.RefObject<((after?:()=>void)=>void)|null>}){
  const [doc,setDoc]=useState<TextDocument|null>(null),[text,setText]=useState(''),[busy,setBusy]=useState(true),[error,setError]=useState(''),[message,setMessage]=useState('');
  const [pendingClose,setPendingClose]=useState<{after:()=>void}|null>(null);
  const area=useRef<HTMLTextAreaElement>(null);
  const dirty=doc!==null&&text!==doc.content;
  useEffect(()=>{let active=true;void fileOperation<TextDocument>(host,{op:'read',path}).then(value=>{if(active){setDoc(value);setText(value.content)}}).catch(e=>{if(active)setError(e instanceof Error?e.message:String(e))}).finally(()=>{if(active)setBusy(false)});return()=>{active=false}},[host,path]);
  useEffect(()=>{changed(dirty);return()=>changed(false)},[dirty]);
  useEffect(()=>{busyChanged(busy);return()=>busyChanged(false)},[busy]);
  useEffect(()=>{if(!dirty)return;const guard=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue=''};window.addEventListener('beforeunload',guard);return()=>window.removeEventListener('beforeunload',guard)},[dirty]);
  const leave=(after:()=>void=close)=>{if(busy)return;if(dirty)setPendingClose({after});else after()};
  useEffect(()=>{closeRequest.current=leave;return()=>{closeRequest.current=null}});
  const save=async()=>{
    if(!doc||busy)return false;if(!dirty)return true;
    setBusy(true);setError('');setMessage('');
    try{const next=await fileOperation<TextDocument>(host,{op:'save',path,content:text,revision:doc.revision});setDoc(next);setText(next.content);setMessage('已保存到服务器');saved();return true}
    catch(e){setError(e instanceof Error?e.message:String(e));return false}finally{setBusy(false)}
  };
  return <section className="file-editor" role="dialog" aria-modal="true" aria-label={'编辑文件 '+path} onKeyDown={event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();void save()}else if(event.key==='Escape'){event.stopPropagation();if(pendingClose)setPendingClose(null);else leave()}}}>
    <div className="file-editor-heading"><div><h3>{dirty?'● ':''}{path.split('/').pop()}</h3><p>{path}</p></div><button className="primary" disabled={!doc||busy||!dirty} onClick={()=>void save()}>{busy?<LoaderCircle size={15} className="spin"/>:<Save size={15}/>}保存</button><button className="icon-button" aria-label="关闭文本编辑器" disabled={busy} onClick={()=>leave()}><X size={19}/></button></div>
    {error&&<p className="file-error" role="alert">{error}</p>}{message&&<p className="file-inline" role="status">{message}</p>}
    {doc?<textarea autoFocus ref={area} spellCheck={false} aria-label="文件文本内容" value={text} readOnly={busy} onChange={event=>{setText(event.target.value);setMessage('')}} onKeyDown={event=>{if(event.key==='Tab'){event.preventDefault();const start=event.currentTarget.selectionStart,end=event.currentTarget.selectionEnd;setText(old=>old.slice(0,start)+'  '+old.slice(end));requestAnimationFrame(()=>area.current?.setSelectionRange(start+2,start+2))}}}/>:busy?<p className="file-inline"><LoaderCircle size={16} className="spin"/>正在打开文本文件…</p>:<p className="file-inline">可关闭此窗口，使用下载功能在本地打开文件。</p>}
    <div className="file-editor-footer"><span>UTF-8 · {doc?.newline??'—'} · {text.split('\n').length} 行 · 文本上限 1 MiB</span><span>{dirty?'尚未保存':'Ctrl+S 保存'}</span></div>
    {pendingClose&&<div className="file-confirm-shade"><div className="file-confirm" role="alertdialog" aria-label="保存文件修改"><h3>保存修改后再关闭？</h3><p>{path}</p><p>未保存的内容会丢失。</p><div><button className="secondary" disabled={busy} onClick={()=>setPendingClose(null)}>取消</button><button className="secondary" disabled={busy} onClick={()=>pendingClose.after()}>不保存</button><button className="primary" disabled={busy} onClick={async()=>{if(await save())pendingClose.after();else setPendingClose(null)}}>保存并关闭</button></div></div></div>}
  </section>;
}
