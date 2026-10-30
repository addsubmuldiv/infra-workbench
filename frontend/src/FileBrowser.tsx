import React,{useEffect,useRef,useState} from 'react';
import {ArrowUp,ClipboardPaste,Copy,Scissors,FilePlus,FolderPlus,MoreHorizontal,ChevronDown,ChevronRight,Download,File,Folder,FolderOpen,Home,LoaderCircle,RefreshCw,Minus,PanelTopOpen,X} from 'lucide-react';
import {listDirectory,fileOperation,type DirectoryPage,type RemoteEntry} from './files';
import {downloadOriginalLog} from './logDownload';
import './files.css';
import {FileEditor} from './FileEditor';
import {FileActionDialog,type FileAction} from './FileActionDialog';
import {fitFileWindow,moveFileWindow,type WindowFrame} from './fileWindow';

type Host={id:string;target:string};
const size=(n:number|null)=>n==null?'—':n<1024?n+' B':n<1024**2?(n/1024).toFixed(1)+' KiB':n<1024**3?(n/1024**2).toFixed(1)+' MiB':(n/1024**3).toFixed(1)+' GiB';
export function FileBrowser({host,hosts,close,requestId=host.id}:{host:Host;hosts:Host[];close:()=>void;requestId?:string}){
  const [selected,setSelected]=useState(host.id);
  const [locked,setLocked]=useState(false);
  const [minimized,setMinimized]=useState(false);
  const viewport=()=>({width:window.innerWidth,height:window.innerHeight});
  const [frame,setFrame]=useState(()=>fitFileWindow({x:(window.innerWidth-880)/2,y:40,width:880,height:Math.min(600,window.innerHeight-120)},viewport()));
  const gesture=useRef<{pointer:number;kind:'move'|'resize';x:number;y:number;frame:WindowFrame}|null>(null);
  useEffect(()=>{const resize=()=>setFrame(old=>fitFileWindow(old,viewport()));window.addEventListener('resize',resize);return()=>window.removeEventListener('resize',resize)},[]);
  const startGesture=(event:React.PointerEvent,kind:'move'|'resize')=>{
    if(event.button!==0||gesture.current)return;
    if(kind==='move'&&(event.target as HTMLElement).closest('button,select,input,a'))return;
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
  const editorClose=useRef<((after?:()=>void)=>void)|null>(null);
  const leave=(after:()=>void)=>{if(locked)return;if(editorClose.current)editorClose.current(after);else after()};
  const handledRequest=useRef(requestId);
  useEffect(()=>{
    if(handledRequest.current===requestId||locked)return;
    handledRequest.current=requestId;
    if(host.id!==selected)leave(()=>setSelected(host.id));
  },[requestId,locked]);
  const current=hosts.find(item=>item.id===selected)||host;
  return <div className="file-workspace"><section role="dialog" aria-modal="false" aria-labelledby="file-title" className={'file-browser floating '+(minimized?'minimized':'')} style={{left:frame.x,top:frame.y,width:minimized?'min(320px, calc(100vw - 16px))':frame.width,height:minimized?56:frame.height}} onPointerMove={moveGesture} onPointerUp={endGesture} onPointerCancel={endGesture} onLostPointerCapture={endGesture}>
    <header className="file-header" onPointerDown={event=>startGesture(event,'move')}><div tabIndex={0} aria-label="移动文件窗口，方向键调整位置" onKeyDown={event=>{if(event.target!==event.currentTarget)return;const offsets:Record<string,[number,number]>={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]};const offset=offsets[event.key];if(offset){event.preventDefault();setFrame(old=>moveFileWindow(old,...offset,viewport(),minimized))}}}><h2 id="file-title"><FolderOpen size={19}/>服务器文件{minimized&&<small>{current.target}</small>}</h2>{!minimized&&<p>拖动标题栏移动窗口；右下角调整大小，可同时操作 SSH 终端。</p>}</div>{!minimized&&<select aria-label="文件浏览目标机器" value={current.id} disabled={locked} onChange={e=>leave(()=>setSelected(e.target.value))}>{hosts.map(item=><option key={item.id} value={item.id}>{item.target}</option>)}</select>}<button className="icon-button" aria-label={minimized?'恢复文件窗口':'最小化文件窗口'} title={minimized?'恢复文件窗口':'最小化（保留目录和编辑状态）'} onClick={toggleMinimized}>{minimized?<PanelTopOpen size={18}/>:<Minus size={18}/>}</button><button className="icon-button" aria-label="关闭文件浏览" disabled={locked} onClick={()=>leave(close)}><X size={20}/></button></header>
    <div className="file-window-body" hidden={minimized}><BrowserBody key={current.id} host={current} onBusy={setLocked} editorClose={editorClose}/></div>
    {!minimized&&<div className="file-window-resize" role="separator" aria-label="调整文件窗口大小" tabIndex={0} onPointerDown={event=>startGesture(event,'resize')} onKeyDown={event=>{const offsets:Record<string,[number,number]>={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]};const offset=offsets[event.key];if(offset){event.preventDefault();setFrame(old=>fitFileWindow({...old,width:old.width+offset[0],height:old.height+offset[1]},viewport()))}}}/>}
  </section></div>;
}
function BrowserBody({host,onBusy,editorClose}:{host:Host;onBusy:(busy:boolean)=>void;editorClose:React.RefObject<((after?:()=>void)=>void)|null>}){
  const [root,setRoot]=useState<DirectoryPage|null>(null),[path,setPath]=useState('~');
  const [pages,setPages]=useState<Record<string,DirectoryPage>>({}),[opened,setOpened]=useState<Set<string>>(new Set());
  const [loading,setLoading]=useState<Set<string>>(new Set()),[errors,setErrors]=useState<Record<string,string>>({});
  const [error,setError]=useState(''),[message,setMessage]=useState(''),[downloading,setDownloading]=useState('');
  const [selected,setSelected]=useState<RemoteEntry|null>(null),[clipboard,setClipboard]=useState<{entry:RemoteEntry;op:'copy'|'move'}|null>(null);
  const [action,setAction]=useState<FileAction|null>(null),[operationBusy,setOperationBusy]=useState(false),[editorBusy,setEditorBusy]=useState(false),[editor,setEditor]=useState<string|null>(null);
  const [supported,setSupported]=useState(false);
  useEffect(()=>{let active=true;fetch('/api/files/capabilities').then(response=>response.ok?response.json():null).then(data=>{if(active)setSupported(data?.editing===true)}).catch(()=>{});return()=>{active=false}},[]);
  useEffect(()=>{onBusy(operationBusy||editorBusy);return()=>onBusy(false)},[operationBusy,editorBusy]);
  const [menu,setMenu]=useState<{entry:RemoteEntry;x:number;y:number}|null>(null);
  const mounted=useRef(true),epoch=useRef(0),menuRef=useRef<HTMLDivElement>(null),downloadRequest=useRef<AbortController|null>(null);
  const openRoot=async(value:string)=>{
    const request=++epoch.current;setLoading(new Set(['root']));setError('');setMenu(null);
    try{const data=await listDirectory(host.id,value);if(mounted.current&&request===epoch.current){setRoot(data);setPath(data.path);setPages({[data.path]:data});setOpened(new Set([data.path]));setErrors({})}}
    catch(e){if(mounted.current&&request===epoch.current)setError(e instanceof Error?e.message:String(e))}
    finally{if(mounted.current&&request===epoch.current)setLoading(new Set())}
  };
  useEffect(()=>{mounted.current=true;void openRoot('~');return()=>{mounted.current=false;epoch.current++;downloadRequest.current?.abort()}},[]);
  useEffect(()=>{
    if(!menu)return;
    const outside=(e:PointerEvent)=>{if(!menuRef.current?.contains(e.target as Node))setMenu(null)};
    const key=(e:KeyboardEvent)=>{if(e.key==='Escape')setMenu(null)};
    document.addEventListener('pointerdown',outside);document.addEventListener('keydown',key);
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',key)};
  },[menu]);
  const load=async(directory:string,offset=0)=>{
    if(loading.has(directory))return;const request=epoch.current;
    setLoading(old=>new Set(old).add(directory));setErrors(old=>({...old,[directory]:''}));
    try{const data=await listDirectory(host.id,directory,offset);if(!mounted.current||request!==epoch.current)return;
      setPages(old=>({...old,[directory]:{...data,entries:offset?[...new Map([...(old[directory]?.entries||[]),...data.entries].map(item=>[item.path,item])).values()]:data.entries}}));
    }catch(e){if(mounted.current&&request===epoch.current)setErrors(old=>({...old,[directory]:e instanceof Error?e.message:String(e)}))}
    finally{if(mounted.current&&request===epoch.current)setLoading(old=>{const next=new Set(old);next.delete(directory);return next})}
  };
  const toggle=(entry:RemoteEntry)=>{if(!entry.accessible)return;setMenu(null);setOpened(old=>{const next=new Set(old);if(next.has(entry.path))next.delete(entry.path);else next.add(entry.path);return next});if(!pages[entry.path])void load(entry.path)};
  const download=async(entry:RemoteEntry)=>{
    if(downloadRequest.current)return;const controller=new AbortController();downloadRequest.current=controller;setMenu(null);setDownloading(entry.path);setError('');setMessage('');
    try{const data=await downloadOriginalLog({host_id:host.id,path:entry.path},fetch,'/api/files/download',controller.signal);
      if(!mounted.current)return;
      const url=URL.createObjectURL(data.blob),link=document.createElement('a');link.href=url;link.download=data.filename;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);setMessage('已交给浏览器下载：'+entry.name);
    }catch(e){if(mounted.current)setError((e instanceof Error?e.message:String(e)).replaceAll('日志','文件'))}
    finally{if(downloadRequest.current===controller)downloadRequest.current=null;if(mounted.current)setDownloading('')}
  };
  const stage=(entry:RemoteEntry,op:'copy'|'move')=>{setClipboard({entry,op});setMenu(null);setMessage((op==='copy'?'已复制：':'已剪切：')+entry.name+'，请到目标目录点击粘贴。')};
  const paste=(directory:string)=>{if(clipboard){setMenu(null);setAction({op:clipboard.op,directory,source:clipboard.entry})}};
  const copyPath=async(entry:RemoteEntry)=>{setMenu(null);try{await navigator.clipboard.writeText(entry.path);setMessage('已复制路径')}catch{setError('无法写入系统剪贴板，请手动复制路径：'+entry.path)}};
  const switchEditor=(path:string)=>{if(editor===path)return;const open=()=>setEditor(path);if(editorClose.current)editorClose.current(open);else open()};
  const edit=(entry:RemoteEntry)=>{if(!supported){setError('文本编辑需要重启本地服务后启用');return}setMenu(null);switchEditor(entry.path)};
  const perform=async(destination:string)=>{
    if(!action)return;setOperationBusy(true);setError('');
    try{const command=action.op==='create'||action.op==='mkdir'?{op:action.op,path:destination}:{op:action.op==='rename'?'move' as const:action.op,path:action.source!.path,destination};
      await fileOperation(host.id,command);setMessage('操作完成：'+destination);if(action.op==='move')setClipboard(null);setSelected(null);
      if(root)await openRoot(root.path);if(action.op==='create')switchEditor(destination);
    }finally{setOperationBusy(false)}
  };
  const context=(event:React.MouseEvent,entry:RemoteEntry)=>{if(!entry.accessible||entry.kind==='other')return;event.preventDefault();setSelected(entry);setMenu({entry,x:Math.max(8,Math.min(event.clientX,window.innerWidth-210)),y:Math.max(8,Math.min(event.clientY,window.innerHeight-320))})};
  const children=(directory:string,depth:number):React.ReactNode=>{
    if(depth>40)return <p className="file-error">目录层级较深，请在路径栏直接打开该目录。</p>;
    const page=pages[directory];return <>
      {page?.entries.map(entry=><React.Fragment key={entry.path}><div className={'file-row '+(selected?.path===entry.path?'selected':'')} style={{paddingLeft:12+depth*20}} onContextMenu={e=>context(e,entry)}>
        <button className="file-name" disabled={!entry.accessible} aria-expanded={entry.kind==='directory'?opened.has(entry.path):undefined} aria-label={(entry.kind==='directory'?'展开目录 ':'文件 ')+entry.path} onClick={()=>{setSelected(entry);if(entry.kind==='directory')toggle(entry);else if(entry.kind==='file')edit(entry)}}>
          {entry.kind==='directory'?<>{opened.has(entry.path)?<ChevronDown size={14}/>:<ChevronRight size={14}/>}<Folder size={16}/></>:<><span className="file-indent"/><File size={15}/></>}<span title={entry.path}>{entry.name}{entry.symlink&&<small> ↗</small>}</span></button>
        <span className="file-size">{entry.kind==='directory'?'目录':size(entry.size)}</span><span className="file-date">{entry.modified?new Date(entry.modified*1000).toLocaleString('zh-CN',{hour12:false}):'—'}</span>
        {entry.kind==='file'&&<button className="icon-button" disabled={!!downloading||!entry.accessible} aria-label={'下载 '+entry.path} title="下载文件" onClick={()=>download(entry)}><Download size={14}/></button>}
        {entry.kind!=='other'&&<button className="icon-button" aria-label={'文件操作 '+entry.path} onClick={event=>context(event,entry)}><MoreHorizontal size={15}/></button>}
      </div>{entry.kind==='directory' &&opened.has(entry.path)&&children(entry.path,depth+1)}</React.Fragment>)}
      {loading.has(directory)&&<p className="file-inline" style={{paddingLeft:24+depth*20}}><LoaderCircle size={14} className="spin"/>正在读取目录…</p>}
      {errors[directory]&&<p className="file-error" style={{paddingLeft:24+depth*20}}>{errors[directory]} <button className="text-button" onClick={()=>load(directory)}>重试</button></p>}
      {page&&!page.entries.length&&!loading.has(directory)&&<p className="file-inline" style={{paddingLeft:24+depth*20}}>空目录</p>}
      {page?.next_offset!=null&&<button className="text-button file-more" disabled={loading.has(directory)} style={{marginLeft:24+depth*20}} onClick={()=>load(directory,page.next_offset!)}>加载更多（已显示 {page.entries.length} / {page.total}）</button>}
    </>;
  };
  return <><form className="file-path" onSubmit={e=>{e.preventDefault();void openRoot(path)}}><button type="button" className="icon-button" aria-label="打开主目录" onClick={()=>openRoot('~')}><Home size={16}/></button><button type="button" className="icon-button" aria-label="打开上级目录" disabled={!root||root.parent===root.path} onClick={()=>{if(root)openRoot(root.parent)}}><ArrowUp size={16}/></button><input aria-label="服务器目录路径" value={path} onChange={e=>setPath(e.target.value)} placeholder="~ 或 /data/训练目录"/><button className="secondary" disabled={loading.has('root')}>前往</button><button type="button" className="icon-button" aria-label="刷新文件目录" disabled={!root||loading.has('root')} onClick={()=>{if(root)openRoot(root.path)}}><RefreshCw size={16}/></button></form>
    <div className="file-toolbar"><button className="secondary" disabled={!supported||!root||operationBusy} onClick={()=>setAction({op:'create',directory:root!.path})}><FilePlus size={14}/>新建文件</button><button className="secondary" disabled={!supported||!root||operationBusy} onClick={()=>setAction({op:'mkdir',directory:root!.path})}><FolderPlus size={14}/>新建文件夹</button><button className="secondary" disabled={!supported||!selected||operationBusy} onClick={()=>stage(selected!,'copy')}><Copy size={14}/>复制</button><button className="secondary" disabled={!supported||!selected||operationBusy} onClick={()=>stage(selected!,'move')}><Scissors size={14}/>剪切</button><button className="secondary" disabled={!supported||!clipboard||!root||operationBusy} onClick={()=>paste(root!.path)}><ClipboardPaste size={14}/>粘贴到当前目录</button>{clipboard&&<span>{clipboard.op==='copy'?'复制':'剪切'}：{clipboard.entry.name}<button className="text-button" onClick={()=>setClipboard(null)}>取消</button></span>}{!supported&&<span>编辑与文件操作需重启本地服务启用</span>}</div>
    {error&&<div role="alert" className="file-error">{error}</div>}{message&&<p role="status" className="file-inline">{message}</p>}
    <div className="file-tree" role="region" aria-label={host.target+' 目录树'} onScroll={()=>setMenu(null)}>{loading.has('root')?<p className="file-inline"><LoaderCircle size={16} className="spin"/>正在连接并读取目录…</p>:root&&<><div className="file-columns"><strong>{root.path}</strong><span>大小</span><span>修改时间</span></div>{children(root.path,0)}</>}</div>
    <footer className="file-footer">{downloading?<><LoaderCircle size={13} className="spin"/>正在下载，请稍候…</>:'使用当前 SSH 账号 · 文本编辑 ≤ 1 MiB · 复制 ≤ 64 MiB / 1000 项 · 下载 ≤ 512 MiB'}</footer>
    {menu&&<div className="file-context" ref={menuRef} role="menu" style={{left:menu.x,top:menu.y}}>
      {menu.entry.kind==='file'&&<><button role="menuitem" disabled={!supported} onClick={()=>edit(menu.entry)}>打开并编辑</button><button role="menuitem" disabled={!!downloading} onClick={()=>download(menu.entry)}><Download size={15}/>下载文件</button></>}
      {menu.entry.kind==='directory'&&<><button role="menuitem" onClick={()=>openRoot(menu.entry.path)}>进入目录</button><button role="menuitem" disabled={!supported||!clipboard} onClick={()=>paste(menu.entry.path)}>粘贴到此目录</button></>}
      <button role="menuitem" disabled={!supported} onClick={()=>stage(menu.entry,'copy')}>复制</button><button role="menuitem" disabled={!supported} onClick={()=>stage(menu.entry,'move')}>剪切</button>
      <button role="menuitem" disabled={!supported} onClick={()=>{setAction({op:'move',source:menu.entry,directory:root!.path});setMenu(null)}}>移动到…</button>
      <button role="menuitem" disabled={!supported} onClick={()=>{setAction({op:'rename',source:menu.entry,directory:menu.entry.path.slice(0,menu.entry.path.lastIndexOf('/'))||'/'});setMenu(null)}}>重命名</button>
      <button role="menuitem" onClick={()=>copyPath(menu.entry)}>复制路径</button>
    </div>}
    {action&&<FileActionDialog action={action} close={()=>setAction(null)} submit={perform}/>}
    {editor&&<FileEditor key={editor} host={host.id} path={editor} close={()=>setEditor(null)} saved={()=>{if(root)void load(root.path)}} changed={()=>{}} busyChanged={setEditorBusy} closeRequest={editorClose}/>}

  </>;
}
